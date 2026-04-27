#!/usr/bin/env python3
"""
email_flow/flow.py — Signup → welcome → drip automation on Modal Dict.

State lives in two Modal Dicts (atomic across all containers):
    aiangels-signup-subs      email → subscriber profile
    aiangels-signup-claims    "{email}:{step}" → {sent_at, resend_id}

The atomic primitive is `claims.put(key, val, skip_if_exists=True)`:
- Returns True ↔ this caller wins the claim and sends the email
- Returns False ↔ another caller already claimed it; we silently skip
This makes duplicate sends MATHEMATICALLY IMPOSSIBLE — no race condition,
no file lock, no commit/reload dance. The DB-style guarantee, no DB.

Public API (unchanged from previous JSON-file version):
    enroll(email, name=None, source="web")
    run_drips()
    unsubscribe(email)
    unsubscribe_by_token(token)
    mark_upgraded(email)
"""
from __future__ import annotations
import os
import sys
import uuid
import argparse
import logging
from pathlib import Path
from datetime import datetime, timezone
from typing import Optional

from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent
REPO_DIR = BASE_DIR.parent
load_dotenv(dotenv_path=REPO_DIR / ".env", override=True)
sys.path.insert(0, str(REPO_DIR))
from resend_client import send_email  # noqa: E402

import modal  # noqa: E402

TEMPLATES_DIR = BASE_DIR / "templates"
LOG_PATH = BASE_DIR / "flow.log"
UNSUBSCRIBE_BASE = os.environ.get(
    "EMAIL_UNSUBSCRIBE_BASE", "https://www.aiangels.io/unsubscribe"
)

# Lazy-init Dicts so importing this module doesn't require Modal connectivity.
_subs: Optional[modal.Dict] = None
_claims: Optional[modal.Dict] = None


def _state():
    global _subs, _claims
    if _subs is None:
        _subs = modal.Dict.from_name("aiangels-signup-subs", create_if_missing=True)
    if _claims is None:
        _claims = modal.Dict.from_name("aiangels-signup-claims", create_if_missing=True)
    return _subs, _claims


logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
    handlers=[logging.StreamHandler()],
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
        "subject": "Ready to unlock everything?",
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


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _parse_ts(ts: str) -> datetime:
    return datetime.fromisoformat(ts.replace("Z", "+00:00"))


# --- Atomic claim -----------------------------------------------------------


def _claim_step(email: str, step_id: str) -> bool:
    """Atomic: True iff this caller wins the right to send. False = already sent
    by someone else, skip. Survives concurrent containers and retries."""
    _, claims = _state()
    key = f"{email}:{step_id}"
    return claims.put(key, {"sent_at": _now()}, skip_if_exists=True)


def _record_send(email: str, step_id: str, resend_id: Optional[str]) -> None:
    """After a successful send, augment the claim with the Resend message id
    (for analytics / debugging). Best-effort — claim already won."""
    _, claims = _state()
    key = f"{email}:{step_id}"
    try:
        existing = claims.get(key) or {}
        existing["resend_id"] = resend_id
        claims[key] = existing
    except Exception as e:
        log.warning("record_send post-update failed (claim already wins): %s", e)


# --- Rendering --------------------------------------------------------------


def _render(template_name: str, sub: dict) -> str:
    raw = (TEMPLATES_DIR / template_name).read_text()
    unsub = f"{UNSUBSCRIBE_BASE}?token={sub['unsubscribe_token']}"
    return raw.replace("{{unsubscribe_url}}", unsub)


def _try_send_step(sub: dict, step: dict) -> bool:
    if sub.get("unsubscribed"):
        return False
    for flag in step.get("skip_if", []):
        if sub.get(flag):
            return False
    if not _claim_step(sub["email"], step["id"]):
        # Already claimed by another caller — silent skip, no duplicate send.
        return False
    try:
        html = _render(step["template"], sub)
        result = send_email(
            subject=step["subject"],
            html=html,
            to=sub["email"],
            tags=[("flow", "signup"), ("step", step["id"]),
                  ("source", sub.get("source", "web"))],
        )
        _record_send(sub["email"], step["id"], (result or {}).get("id"))
        log.info("Sent %s → %s (resend_id=%s)", step["id"], sub["email"],
                 (result or {}).get("id"))
        return True
    except Exception as e:
        # The claim already won. Best we can do is log; cron will not retry the step.
        log.error("Send %s → %s FAILED after claim won: %s", step["id"], sub["email"], e)
        return False


# --- Core ops ---------------------------------------------------------------


def enroll(email: str, name: Optional[str] = None, source: str = "web") -> dict:
    email = email.lower().strip()
    subs, _ = _state()
    sub = subs.get(email)
    if sub is None:
        sub = {
            "email": email,
            "name": name or "",
            "source": source,
            "signed_up_at": _now(),
            "unsubscribe_token": uuid.uuid4().hex,
            "unsubscribed": False,
            "upgraded": False,
        }
        # put_if_absent — if two webhook calls race, only one wins; the loser
        # picks up the same canonical row below.
        if not subs.put(email, sub, skip_if_exists=True):
            sub = subs[email]  # someone else just inserted; use their version
        log.info("Enrolled %s (source=%s)", email, source)
    # Always try to send welcome — _claim_step handles dedup.
    _try_send_step(sub, FLOW[0])
    return sub


def run_drips() -> dict:
    subs, _ = _state()
    now = datetime.now(timezone.utc)
    sent, skipped = 0, 0
    total = 0
    for email, sub in subs.items():
        total += 1
        if sub.get("unsubscribed"):
            continue
        try:
            signed_up = _parse_ts(sub["signed_up_at"])
        except Exception:
            continue
        age_days = (now - signed_up).total_seconds() / 86400.0
        for step in FLOW:
            if age_days < step["delay_days"]:
                continue
            if _try_send_step(sub, step):
                sent += 1
            else:
                skipped += 1
    log.info("Drip run: sent=%d skipped=%d total_subs=%d", sent, skipped, total)
    return {"sent": sent, "skipped": skipped, "total_subscribers": total}


def unsubscribe(email: str) -> bool:
    email = email.lower().strip()
    subs, _ = _state()
    sub = subs.get(email)
    if sub is None:
        return False
    sub["unsubscribed"] = True
    sub["unsubscribed_at"] = _now()
    subs[email] = sub
    log.info("Unsubscribed %s", email)
    return True


def unsubscribe_by_token(token: str) -> bool:
    subs, _ = _state()
    for email, sub in subs.items():
        if sub.get("unsubscribe_token") == token:
            return unsubscribe(email)
    return False


def mark_upgraded(email: str) -> bool:
    email = email.lower().strip()
    subs, _ = _state()
    sub = subs.get(email)
    if sub is None:
        return False
    sub["upgraded"] = True
    sub["upgraded_at"] = _now()
    subs[email] = sub
    log.info("Marked upgraded: %s", email)
    return True


# --- CLI --------------------------------------------------------------------


def _cli():
    ap = argparse.ArgumentParser(description="AI Angels signup email flow (Modal Dict backed)")
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

    import json
    if args.cmd == "enroll":
        print(json.dumps(enroll(args.email, args.name, args.source), indent=2))
    elif args.cmd == "drips":
        print(json.dumps(run_drips(), indent=2))
    elif args.cmd == "list":
        subs, claims = _state()
        rows = list(subs.items())
        for email, s in rows:
            sent = []
            for step in FLOW:
                if claims.contains(f"{email}:{step['id']}"):
                    sent.append(step["id"])
            print(f"{email:<40} signed_up={s.get('signed_up_at','?')[:10]} "
                  f"sent={','.join(sent) or '-':<40} "
                  f"unsub={s.get('unsubscribed')} upgraded={s.get('upgraded')}")
        print(f"\nTotal: {len(rows)}")
    elif args.cmd == "unsubscribe":
        print("OK" if unsubscribe(args.email) else "Not found")
    elif args.cmd == "upgrade":
        print("OK" if mark_upgraded(args.email) else "Not found")


if __name__ == "__main__":
    _cli()
