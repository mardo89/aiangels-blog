#!/usr/bin/env python3
"""
email_flow/flow.py — Signup → welcome → drip automation on top of Resend.

Core operations:
    enroll(email, name=None, source="web")      # add contact, send welcome immediately
    run_drips()                                  # send any follow-ups that are now due
    unsubscribe(email)                           # mark as unsubscribed (stops future drips)
    mark_upgraded(email)                         # stops the upgrade-nudge + winback

State lives in email_flow/subscribers.json — one JSON file, no DB.
Each subscriber has `drips_sent` (list of step ids already sent). The scheduler
is idempotent: it only sends a step if elapsed >= delay_days AND id not yet sent.

CLI:
    python3 -m email_flow.flow enroll --email x@y.com --name Mark
    python3 -m email_flow.flow drips                    # run scheduler (cron this)
    python3 -m email_flow.flow list                     # print subscribers
    python3 -m email_flow.flow unsubscribe --email x@y.com
    python3 -m email_flow.flow upgrade --email x@y.com
"""
from __future__ import annotations
import os
import sys
import json
import uuid
import argparse
import logging
from pathlib import Path
from datetime import datetime, timezone, timedelta
from typing import Optional

import requests
from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent
REPO_DIR = BASE_DIR.parent
load_dotenv(dotenv_path=REPO_DIR / ".env", override=True)

# Local import, running as module OR script
sys.path.insert(0, str(REPO_DIR))
from resend_client import send_email  # noqa: E402

# State lives alongside code by default (local dev) or on a mounted volume on
# Modal (prod). Override via EMAIL_FLOW_STATE_DIR for ephemeral storage.
STATE_DIR = Path(os.environ.get("EMAIL_FLOW_STATE_DIR", str(BASE_DIR)))
STATE_DIR.mkdir(parents=True, exist_ok=True)
STATE_PATH = STATE_DIR / "subscribers.json"
TEMPLATES_DIR = BASE_DIR / "templates"
LOG_PATH = STATE_DIR / "flow.log"
RESEND_AUDIENCE_ID = os.environ.get("RESEND_AUDIENCE_ID")  # optional
UNSUBSCRIBE_BASE = os.environ.get(
    "EMAIL_UNSUBSCRIBE_BASE", "https://www.aiangels.io/unsubscribe"
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
    handlers=[logging.FileHandler(LOG_PATH), logging.StreamHandler()],
)
log = logging.getLogger("email_flow")

# --- Flow definition --------------------------------------------------------

FLOW = [
    {
        "id": "welcome",
        "delay_days": 0,
        "subject": "Welcome to AI Angels",
        "template": "welcome.html",
        "skip_if": [],
    },
    {
        "id": "tips",
        "delay_days": 1,
        "subject": "3 ways to make her feel real",
        "template": "tips.html",
        "skip_if": [],
    },
    {
        "id": "social",
        "delay_days": 3,
        "subject": "5,000+ users — here's what they're saying",
        "template": "social.html",
        "skip_if": [],
    },
    {
        "id": "upgrade",
        "delay_days": 7,
        "subject": "Unlock voice, memory + unlimited chat",
        "template": "upgrade.html",
        "skip_if": ["upgraded"],
    },
    {
        "id": "winback",
        "delay_days": 14,
        "subject": "She's been thinking about you",
        "template": "winback.html",
        "skip_if": ["upgraded"],
    },
]

# --- State store ------------------------------------------------------------


def _load() -> dict:
    if not STATE_PATH.exists():
        return {"subscribers": []}
    return json.loads(STATE_PATH.read_text())


def _save(state: dict) -> None:
    STATE_PATH.write_text(json.dumps(state, indent=2))


def _find(state: dict, email: str) -> Optional[dict]:
    email = email.lower().strip()
    for s in state["subscribers"]:
        if s["email"] == email:
            return s
    return None


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _parse_ts(ts: str) -> datetime:
    return datetime.fromisoformat(ts.replace("Z", "+00:00"))


# --- Resend audience sync (optional) ----------------------------------------


def _add_to_audience(email: str, name: Optional[str]) -> Optional[str]:
    if not RESEND_AUDIENCE_ID:
        return None
    api_key = os.environ["RESEND_API_KEY"]
    first, last = ((name or "").split(" ", 1) + [""])[:2]
    resp = requests.post(
        f"https://api.resend.com/audiences/{RESEND_AUDIENCE_ID}/contacts",
        headers={"Authorization": f"Bearer {api_key}"},
        json={"email": email, "first_name": first, "last_name": last, "unsubscribed": False},
        timeout=15,
    )
    if resp.status_code >= 400:
        log.warning("Audience add failed for %s: %s %s", email, resp.status_code, resp.text)
        return None
    return resp.json().get("id")


def _remove_from_audience(contact_id: str) -> None:
    if not (RESEND_AUDIENCE_ID and contact_id):
        return
    api_key = os.environ["RESEND_API_KEY"]
    requests.patch(
        f"https://api.resend.com/audiences/{RESEND_AUDIENCE_ID}/contacts/{contact_id}",
        headers={"Authorization": f"Bearer {api_key}"},
        json={"unsubscribed": True},
        timeout=15,
    )


# --- Rendering --------------------------------------------------------------


def _render(template_name: str, sub: dict) -> str:
    raw = (TEMPLATES_DIR / template_name).read_text()
    unsub = f"{UNSUBSCRIBE_BASE}?token={sub['unsubscribe_token']}"
    return raw.replace("{{unsubscribe_url}}", unsub)


# --- Core ops ---------------------------------------------------------------


def enroll(email: str, name: Optional[str] = None, source: str = "web") -> dict:
    email = email.lower().strip()
    state = _load()
    existing = _find(state, email)
    if existing:
        log.info("Already enrolled: %s (signed_up_at=%s)", email, existing["signed_up_at"])
        return existing

    contact_id = _add_to_audience(email, name)
    sub = {
        "email": email,
        "name": name or "",
        "source": source,
        "signed_up_at": _now(),
        "drips_sent": [],
        "resend_contact_id": contact_id,
        "unsubscribe_token": uuid.uuid4().hex,
        "unsubscribed": False,
        "upgraded": False,
    }
    state["subscribers"].append(sub)
    _save(state)
    log.info("Enrolled %s (source=%s)", email, source)

    _try_send_step(sub, FLOW[0])
    _save_after_send(sub)
    return sub


def _save_after_send(sub: dict) -> None:
    state = _load()
    for i, s in enumerate(state["subscribers"]):
        if s["email"] == sub["email"]:
            state["subscribers"][i] = sub
            break
    _save(state)


def _try_send_step(sub: dict, step: dict) -> bool:
    if sub.get("unsubscribed"):
        return False
    if step["id"] in sub["drips_sent"]:
        return False
    for flag in step.get("skip_if", []):
        if sub.get(flag):
            sub["drips_sent"].append(step["id"])  # record as handled-skip
            log.info("Skip %s for %s (flag=%s)", step["id"], sub["email"], flag)
            return False
    try:
        html = _render(step["template"], sub)
        send_email(
            subject=step["subject"],
            html=html,
            to=sub["email"],
            tags=[("flow", "signup"), ("step", step["id"]), ("source", sub.get("source", "web"))],
        )
        sub["drips_sent"].append(step["id"])
        sub[f"sent_{step['id']}_at"] = _now()
        log.info("Sent %s → %s", step["id"], sub["email"])
        return True
    except Exception as e:
        log.error("Send %s → %s failed: %s", step["id"], sub["email"], e)
        return False


def run_drips() -> dict:
    state = _load()
    now = datetime.now(timezone.utc)
    sent, skipped = 0, 0
    for sub in state["subscribers"]:
        if sub.get("unsubscribed"):
            continue
        signed_up = _parse_ts(sub["signed_up_at"])
        age_days = (now - signed_up).total_seconds() / 86400.0
        for step in FLOW:
            if step["id"] in sub["drips_sent"]:
                continue
            if age_days < step["delay_days"]:
                continue
            if _try_send_step(sub, step):
                sent += 1
            else:
                skipped += 1
    _save(state)
    log.info("Drip run: sent=%d skipped=%d", sent, skipped)
    return {"sent": sent, "skipped": skipped, "total_subscribers": len(state["subscribers"])}


def unsubscribe(email: str) -> bool:
    state = _load()
    sub = _find(state, email)
    if not sub:
        return False
    sub["unsubscribed"] = True
    sub["unsubscribed_at"] = _now()
    if sub.get("resend_contact_id"):
        _remove_from_audience(sub["resend_contact_id"])
    _save(state)
    log.info("Unsubscribed %s", email)
    return True


def unsubscribe_by_token(token: str) -> bool:
    state = _load()
    for sub in state["subscribers"]:
        if sub.get("unsubscribe_token") == token:
            return unsubscribe(sub["email"])
    return False


def mark_upgraded(email: str) -> bool:
    state = _load()
    sub = _find(state, email)
    if not sub:
        return False
    sub["upgraded"] = True
    sub["upgraded_at"] = _now()
    _save(state)
    log.info("Marked upgraded: %s", email)
    return True


# --- CLI --------------------------------------------------------------------


def _cli():
    ap = argparse.ArgumentParser(description="AI Angels signup email flow")
    sub = ap.add_subparsers(dest="cmd", required=True)

    e = sub.add_parser("enroll")
    e.add_argument("--email", required=True)
    e.add_argument("--name")
    e.add_argument("--source", default="web")

    sub.add_parser("drips")
    sub.add_parser("list")

    u = sub.add_parser("unsubscribe")
    u.add_argument("--email", required=True)

    g = sub.add_parser("upgrade")
    g.add_argument("--email", required=True)

    args = ap.parse_args()

    if args.cmd == "enroll":
        print(json.dumps(enroll(args.email, args.name, args.source), indent=2))
    elif args.cmd == "drips":
        print(json.dumps(run_drips(), indent=2))
    elif args.cmd == "list":
        state = _load()
        for s in state["subscribers"]:
            print(
                f"{s['email']:<40} signed_up={s['signed_up_at'][:10]} "
                f"sent={','.join(s['drips_sent']) or '-':<40} "
                f"unsub={s.get('unsubscribed')} upgraded={s.get('upgraded')}"
            )
        print(f"\nTotal: {len(state['subscribers'])}")
    elif args.cmd == "unsubscribe":
        print("OK" if unsubscribe(args.email) else "Not found")
    elif args.cmd == "upgrade":
        print("OK" if mark_upgraded(args.email) else "Not found")


if __name__ == "__main__":
    _cli()
