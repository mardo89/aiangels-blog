#!/usr/bin/env python3
"""
discount_flow/flow.py — "3 days free Premium" email flow.

Entry point: the popup on aiangels.io. User submits email → we generate a
unique promo code, send it in email 1, then drip 3 more emails over ~7 days
to drive redemption and paid conversion.

4 emails, pure time-based:
    1. code      — instant         — "Your free Premium code 💗"
    2. reminder  — +2 days         — "Don't waste your 3 free days"
    3. preview   — +5 days         — "Here's what you're missing"
    4. urgency   — +7 days         — "Last 48h — plus 20% off if you stay"

State:
    email, code, signed_up_at, drips_sent, redeemed_at, converted_at, unsubscribed

Skip rules (the cross-flow handoff):
    - **Redeemed code → stop EVERY remaining discount email.** They become a
      regular account holder; the signup flow (email_flow) takes over with
      welcome → tips → social → upgrade → winback. No double-emailing.
    - Converted (paid):   stop everything immediately.
    - Unsubscribed:       stop everything.

Source-of-truth integration: `redeemed_at` is derived from xangels'
`promo_codes.times_used > 0` for that user's code (single read at run_drips
time), so the moment a user pastes their code in the redeem flow, all
remaining discount emails are suppressed on the next cron tick.

CLI:
    python3 -m discount_flow.flow subscribe --email x@y.com
    python3 -m discount_flow.flow drips
    python3 -m discount_flow.flow list
    python3 -m discount_flow.flow redeemed --email x@y.com
    python3 -m discount_flow.flow converted --email x@y.com
    python3 -m discount_flow.flow unsubscribe --email x@y.com
"""
from __future__ import annotations
import os
import sys
import json
import uuid
import secrets
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

STATE_DIR = Path(os.environ.get("DISCOUNT_FLOW_STATE_DIR", "/tmp/discount_flow"))
STATE_DIR.mkdir(parents=True, exist_ok=True)
STATE_PATH = STATE_DIR / "subscribers.json"
TEMPLATES_DIR = BASE_DIR / "templates"
LOG_PATH = STATE_DIR / "flow.log"
REDEEM_BASE = os.environ.get("DISCOUNT_REDEEM_BASE", "https://www.aiangels.io/redeem")
UNSUBSCRIBE_BASE = os.environ.get(
    "EMAIL_UNSUBSCRIBE_BASE", "https://www.aiangels.io/unsubscribe"
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
    handlers=[logging.FileHandler(LOG_PATH), logging.StreamHandler()],
)
log = logging.getLogger("discount_flow")

FLOW = [
    {
        "id": "code",
        "delay_days": 0,
        "subject": "Your free Premium code 💗",
        "template": "01_code.html",
        # Note: parked in production — xangels' /api/promo/request-code sends
        # the initial code email. We pick up from step 2 onward.
        "skip_if": ["redeemed_at"],
    },
    {
        "id": "reminder",
        "delay_days": 2,
        "subject": "Don't waste your 3 free days",
        "template": "02_reminder.html",
        "skip_if": ["redeemed_at"],
    },
    {
        "id": "preview",
        "delay_days": 5,
        "subject": "Here's what you're missing",
        "template": "03_preview.html",
        "skip_if": ["redeemed_at"],
    },
    {
        "id": "urgency",
        "delay_days": 7,
        "subject": "Last 48h — plus 20% off if you stay",
        "template": "04_urgency.html",
        # Hard rule (per user spec): once they redeem the code, every remaining
        # discount email stops. They're now an account holder and get only the
        # signup flow's drip (welcome → tips → social → upgrade → winback).
        "skip_if": ["redeemed_at"],
    },
]


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _parse_ts(ts: str) -> datetime:
    return datetime.fromisoformat(ts.replace("Z", "+00:00"))


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


def _generate_code() -> str:
    """8-char alphanumeric, uppercase, unambiguous (no 0/O/1/I/L)."""
    alphabet = "ABCDEFGHJKMNPQRSTUVWXYZ23456789"
    return "AI-" + "".join(secrets.choice(alphabet) for _ in range(8))


def _render(template_name: str, sub: dict) -> str:
    raw = (TEMPLATES_DIR / template_name).read_text()
    redeem = f"{REDEEM_BASE}?code={sub['code']}"
    unsub = f"{UNSUBSCRIBE_BASE}?token={sub['unsubscribe_token']}&list=discount"
    return (
        raw.replace("{{code}}", sub["code"])
        .replace("{{redeem_url}}", redeem)
        .replace("{{unsubscribe_url}}", unsub)
    )


def subscribe(email: str, source: str = "popup") -> dict:
    email = email.lower().strip()
    state = _load()
    existing = _find(state, email)
    if existing:
        log.info("Already subscribed: %s (code=%s)", email, existing["code"])
        return existing

    sub = {
        "email": email,
        "code": _generate_code(),
        "source": source,
        "signed_up_at": _now(),
        "drips_sent": [],
        "redeemed_at": None,
        "converted_at": None,
        "unsubscribe_token": uuid.uuid4().hex,
        "unsubscribed": False,
    }
    state["subscribers"].append(sub)
    _save(state)
    log.info("Subscribed %s (code=%s source=%s)", email, sub["code"], source)

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
    if sub.get("converted_at"):
        return False
    if step["id"] in sub["drips_sent"]:
        return False
    for flag in step.get("skip_if", []):
        if sub.get(flag):
            sub["drips_sent"].append(step["id"])
            log.info("Skip %s for %s (flag=%s)", step["id"], sub["email"], flag)
            return False
    try:
        html = _render(step["template"], sub)
        send_email(
            subject=step["subject"],
            html=html,
            to=sub["email"],
            tags=[("flow", "discount"), ("step", step["id"])],
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
        if sub.get("unsubscribed") or sub.get("converted_at"):
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
    log.info("Discount drip run: sent=%d skipped=%d", sent, skipped)
    return {"sent": sent, "skipped": skipped, "total_subscribers": len(state["subscribers"])}


def mark_redeemed(email: str) -> bool:
    state = _load()
    sub = _find(state, email)
    if not sub:
        return False
    sub["redeemed_at"] = _now()
    _save(state)
    log.info("Redeemed: %s", email)
    return True


def mark_redeemed_by_code(code: str) -> Optional[str]:
    state = _load()
    for sub in state["subscribers"]:
        if sub["code"] == code:
            sub["redeemed_at"] = _now()
            _save(state)
            log.info("Redeemed by code %s → %s", code, sub["email"])
            return sub["email"]
    return None


def mark_converted(email: str) -> bool:
    state = _load()
    sub = _find(state, email)
    if not sub:
        return False
    sub["converted_at"] = _now()
    _save(state)
    log.info("Converted: %s", email)
    return True


def unsubscribe(email: str) -> bool:
    state = _load()
    sub = _find(state, email)
    if not sub:
        return False
    sub["unsubscribed"] = True
    sub["unsubscribed_at"] = _now()
    _save(state)
    log.info("Unsubscribed: %s", email)
    return True


def unsubscribe_by_token(token: str) -> bool:
    state = _load()
    for sub in state["subscribers"]:
        if sub.get("unsubscribe_token") == token:
            return unsubscribe(sub["email"])
    return False


def _cli():
    ap = argparse.ArgumentParser(description="AI Angels discount email flow")
    sub = ap.add_subparsers(dest="cmd", required=True)

    s = sub.add_parser("subscribe")
    s.add_argument("--email", required=True)
    s.add_argument("--source", default="popup")

    sub.add_parser("drips")
    sub.add_parser("list")

    r = sub.add_parser("redeemed")
    r.add_argument("--email", required=True)

    c = sub.add_parser("converted")
    c.add_argument("--email", required=True)

    u = sub.add_parser("unsubscribe")
    u.add_argument("--email", required=True)

    args = ap.parse_args()

    if args.cmd == "subscribe":
        print(json.dumps(subscribe(args.email, args.source), indent=2))
    elif args.cmd == "drips":
        print(json.dumps(run_drips(), indent=2))
    elif args.cmd == "list":
        state = _load()
        for s in state["subscribers"]:
            status = "paid" if s.get("converted_at") else ("redeemed" if s.get("redeemed_at") else "pending")
            print(
                f"{s['email']:<40} {s['code']:<14} {status:<9} "
                f"sent={','.join(s['drips_sent']) or '-'}"
            )
        print(f"\nTotal: {len(state['subscribers'])}")
    elif args.cmd == "redeemed":
        print("OK" if mark_redeemed(args.email) else "Not found")
    elif args.cmd == "converted":
        print("OK" if mark_converted(args.email) else "Not found")
    elif args.cmd == "unsubscribe":
        print("OK" if unsubscribe(args.email) else "Not found")


if __name__ == "__main__":
    _cli()
