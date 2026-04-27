#!/usr/bin/env python3
"""
discount_flow/flow.py — "3 days free Premium" follow-ups (emails 2-4 of 4).

Source of truth: xangels' existing Supabase tables. We don't capture emails
or generate codes — xangels' /api/promo/request-code already does both. We
only add the missing follow-up nudges:

    Email 2  reminder   +2 days   "Don't waste your 3 free days"
    Email 3  preview    +5 days   "Here's what you're missing"
    Email 4  urgency    +7 days   "Last 48h — plus 20% off if you stay"

Hard rule (per user spec): the moment they redeem the code
(promo_codes.times_used > 0) every remaining discount email STOPS — they're
now an account holder and the signup flow takes over.

Atomic claim: Modal Dict 'aiangels-discount-claims' uses
Dict.put(skip_if_exists=True) — same primitive as email_flow. Duplicate
sends are mathematically impossible across containers.

Required env vars (in Modal secret 'resend-prod'):
    SUPABASE_URL                  → https://<ref>.supabase.co
    SUPABASE_SERVICE_ROLE_KEY     → service-role key (server-side only)
    RESEND_API_KEY
    EMAIL_UNSUBSCRIBE_BASE
    DISCOUNT_REDEEM_BASE          → https://www.aiangels.io/redeem (default)
"""
from __future__ import annotations
import os
import sys
import argparse
import logging
from pathlib import Path
from datetime import datetime, timezone
from typing import Optional

import requests
from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent
REPO_DIR = BASE_DIR.parent
load_dotenv(dotenv_path=REPO_DIR / ".env", override=True)
sys.path.insert(0, str(REPO_DIR))
from resend_client import send_email  # noqa: E402

import modal  # noqa: E402

TEMPLATES_DIR = BASE_DIR / "templates"
SUPABASE_URL = os.environ.get("SUPABASE_URL", "https://vxkvzzgkefrquxpirocd.supabase.co")
SUPABASE_KEY = os.environ.get("SUPABASE_SERVICE_ROLE_KEY")
REDEEM_BASE = os.environ.get("DISCOUNT_REDEEM_BASE", "https://www.aiangels.io/redeem")
UNSUBSCRIBE_BASE = os.environ.get("EMAIL_UNSUBSCRIBE_BASE", "https://www.aiangels.io/unsubscribe")

_claims: Optional[modal.Dict] = None


def _state():
    global _claims
    if _claims is None:
        _claims = modal.Dict.from_name("aiangels-discount-claims", create_if_missing=True)
    return _claims


logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
    handlers=[logging.StreamHandler()],
)
log = logging.getLogger("discount_flow")

# We deliberately skip step 1 (xangels sends initial code email already).
FLOW = [
    {"id": "reminder", "delay_days": 2, "subject": "Don't waste your 3 free days",
     "template": "02_reminder.html"},
    {"id": "preview",  "delay_days": 5, "subject": "Here's what you're missing",
     "template": "03_preview.html"},
    {"id": "urgency",  "delay_days": 7, "subject": "Last 48h — plus 20% off if you stay",
     "template": "04_urgency.html"},
]


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _parse_ts(ts: str) -> datetime:
    return datetime.fromisoformat(ts.replace("Z", "+00:00"))


# --- Supabase reads ---------------------------------------------------------


def _supabase_get(path: str, params: dict) -> list[dict]:
    if not SUPABASE_KEY:
        raise RuntimeError("SUPABASE_SERVICE_ROLE_KEY missing — set in Modal secret")
    url = f"{SUPABASE_URL}/rest/v1/{path}"
    headers = {
        "apikey": SUPABASE_KEY,
        "Authorization": f"Bearer {SUPABASE_KEY}",
    }
    r = requests.get(url, headers=headers, params=params, timeout=30)
    if r.status_code >= 400:
        raise RuntimeError(f"Supabase {r.status_code}: {r.text[:300]}")
    return r.json()


def fetch_eligible_captures() -> list[dict]:
    """All popup captures whose code is unredeemed, not expired, and email not
    unsubscribed (via marketing_emails)."""
    captures = _supabase_get(
        "promo_email_captures",
        {
            "select": "email,promo_code,sent_at,promo_codes(times_used,valid_until,is_active)",
            "promo_codes.times_used": "eq.0",
            "promo_codes.is_active": "eq.true",
            "order": "sent_at.desc",
            "limit": "1000",
        },
    )
    unsub = _supabase_get(
        "marketing_emails",
        {"select": "email", "unsubscribed_at": "not.is.null"},
    )
    unsub_set = {row["email"].lower().strip() for row in unsub}

    out = []
    now = _now()
    for c in captures:
        pc = c.get("promo_codes") or {}
        if not pc:
            continue
        valid_until = pc.get("valid_until")
        if valid_until:
            try:
                if _parse_ts(valid_until) < now:
                    continue
            except Exception:
                pass
        email = (c.get("email") or "").lower().strip()
        if not email or email in unsub_set:
            continue
        out.append({
            "email": email,
            "code": c.get("promo_code"),
            "sent_at": c.get("sent_at"),
            "valid_until": valid_until,
        })
    return out


def _claim_step(email: str, step_id: str) -> bool:
    return _state().put(f"{email}:{step_id}", {"sent_at": _now().isoformat()},
                        skip_if_exists=True)


def _render(template: str, capture: dict) -> str:
    raw = (TEMPLATES_DIR / template).read_text()
    redeem = f"{REDEEM_BASE}?code={capture['code']}"
    unsub = f"{UNSUBSCRIBE_BASE}?email={capture['email']}&list=discount"
    return (
        raw.replace("{{code}}", capture.get("code") or "")
           .replace("{{redeem_url}}", redeem)
           .replace("{{unsubscribe_url}}", unsub)
    )


def run_drips() -> dict:
    captures = fetch_eligible_captures()
    sent, skipped = 0, 0
    now = _now()
    for cap in captures:
        try:
            sent_at = _parse_ts(cap["sent_at"])
        except Exception:
            continue
        age_days = (now - sent_at).total_seconds() / 86400.0
        for step in FLOW:
            if age_days < step["delay_days"]:
                continue
            if not _claim_step(cap["email"], step["id"]):
                skipped += 1
                continue
            try:
                html = _render(step["template"], cap)
                send_email(
                    subject=step["subject"],
                    html=html,
                    to=cap["email"],
                    tags=[("flow", "discount"), ("step", step["id"])],
                )
                log.info("Sent discount/%s → %s (code=%s)", step["id"], cap["email"], cap["code"])
                sent += 1
            except Exception as e:
                log.error("Send discount/%s → %s failed (claim already won): %s",
                          step["id"], cap["email"], e)
    log.info("Discount drip run: sent=%d skipped=%d eligible=%d", sent, skipped, len(captures))
    return {"sent": sent, "skipped": skipped, "eligible": len(captures)}


# --- Compatibility shims for webhook.py imports (xangels owns the writes) ---
def subscribe(email: str, source: str = "popup") -> dict:
    return {"email": email, "source": source, "code": None,
            "note": "no-op: xangels handles popup capture"}


def mark_redeemed(email: str) -> bool:
    return True


def mark_redeemed_by_code(code: str) -> Optional[str]:
    return None


def mark_converted(email: str) -> bool:
    return True


def unsubscribe(email: str) -> bool:
    return True


def unsubscribe_by_token(token: str) -> bool:
    return False


def _cli():
    ap = argparse.ArgumentParser(description="Discount-flow follow-up drips")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("drips")
    sub.add_parser("eligible")
    args = ap.parse_args()
    import json
    if args.cmd == "drips":
        print(json.dumps(run_drips(), indent=2))
    elif args.cmd == "eligible":
        rows = fetch_eligible_captures()
        for r in rows[:50]:
            print(f"  {r['email']:<40} code={r['code']:<20} sent_at={r['sent_at'][:19]}")
        print(f"\ntotal eligible: {len(rows)}")


if __name__ == "__main__":
    _cli()
