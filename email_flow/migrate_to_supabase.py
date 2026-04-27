#!/usr/bin/env python3
"""
email_flow/migrate_to_supabase.py — One-shot migration from Modal Volume + Resend
history into the Supabase email_flow_subscribers table.

Goal: never re-send any email a person has already received. Source of truth
for "already received" is the union of:
    1. Resend's email log (filtered to flow=signup)
    2. Whatever drips_sent we have in Modal Volume's subscribers.json

If a step appears in either source, we mark it sent and the atomic claim_step
function will refuse to re-fire it.

Usage:
    # Run locally pointing at prod Supabase (needs SUPABASE_URL + service_role)
    python3 -m email_flow.migrate_to_supabase --dry-run
    python3 -m email_flow.migrate_to_supabase --commit

    # Or run as a one-off Modal job (recommended — has Volume access)
    modal run email_flow/migrate_to_supabase.py::run --commit

Required env vars (from .env or Modal secret):
    SUPABASE_URL                  → https://<project>.supabase.co
    SUPABASE_SERVICE_ROLE_KEY     → from Project Settings → API (service_role)
    RESEND_API_KEY
    MODAL_VOLUME_STATE_PATH       → optional, defaults to /state/signup/subscribers.json
"""
from __future__ import annotations
import os
import sys
import json
import uuid
import argparse
from pathlib import Path
from datetime import datetime, timezone
from collections import defaultdict
from typing import Optional

import requests
from dotenv import load_dotenv

REPO_DIR = Path(__file__).resolve().parent.parent
load_dotenv(dotenv_path=REPO_DIR / ".env", override=True)

SUPABASE_URL = os.environ.get("SUPABASE_URL", "https://vxkvzzgkefrquxpirocd.supabase.co")
SUPABASE_KEY = os.environ.get("SUPABASE_SERVICE_ROLE_KEY")
RESEND_API_KEY = os.environ.get("RESEND_API_KEY")
DEFAULT_VOLUME_STATE = os.environ.get("MODAL_VOLUME_STATE_PATH", "/state/signup/subscribers.json")


def fetch_all_resend_signup_sends() -> dict:
    """Returns {email: set(steps_sent)} from Resend history (flow=signup tag).

    Resend's /emails endpoint pages with `before` cursor on `created_at`. We walk
    backward 100 at a time until we exhaust them.
    """
    if not RESEND_API_KEY:
        raise RuntimeError("RESEND_API_KEY missing")
    H = {"Authorization": f"Bearer {RESEND_API_KEY}"}
    out: dict = defaultdict(set)
    seen_ids = set()
    cursor = None
    while True:
        url = "https://api.resend.com/emails?limit=100"
        if cursor:
            url += f"&before={cursor}"
        page = requests.get(url, headers=H, timeout=30).json().get("data", []) or []
        if not page:
            break
        new = [e for e in page if e["id"] not in seen_ids]
        if not new:
            break
        for e in new:
            seen_ids.add(e["id"])
            # Refresh per-id to get accurate tags + last_event
            d = requests.get(f"https://api.resend.com/emails/{e['id']}", headers=H, timeout=30).json()
            tags = {t.get("name"): t.get("value") for t in (d.get("tags") or [])}
            if tags.get("flow") != "signup":
                continue
            step = tags.get("step")
            if not step:
                continue
            for to in d.get("to", []) or []:
                out[to.lower().strip()].add(step)
        cursor = page[-1]["created_at"]
        if len(page) < 100:
            break
    return out


def load_volume_state(path: str) -> list[dict]:
    """Read Modal Volume's subscribers.json. Returns [] if not found."""
    p = Path(path)
    if not p.exists():
        print(f"[volume] {path} not found — skipping (will rely on Resend history only)")
        return []
    data = json.loads(p.read_text())
    subs = data.get("subscribers", [])
    print(f"[volume] loaded {len(subs)} subscribers from {path}")
    return subs


def supabase_upsert(rows: list[dict], dry_run: bool = True) -> None:
    if dry_run:
        print(f"[dry-run] would upsert {len(rows)} rows. First 3:")
        for r in rows[:3]:
            print("  ", r)
        return
    if not SUPABASE_KEY:
        raise RuntimeError("SUPABASE_SERVICE_ROLE_KEY missing")
    url = f"{SUPABASE_URL}/rest/v1/email_flow_subscribers"
    H = {
        "apikey": SUPABASE_KEY,
        "Authorization": f"Bearer {SUPABASE_KEY}",
        "Content-Type": "application/json",
        "Prefer": "resolution=merge-duplicates,return=minimal",
    }
    # Upsert in batches of 200
    for i in range(0, len(rows), 200):
        batch = rows[i:i+200]
        resp = requests.post(url, headers=H, json=batch, timeout=60)
        if resp.status_code >= 400:
            raise RuntimeError(f"Supabase upsert failed: {resp.status_code} {resp.text[:500]}")
        print(f"  batch {i}-{i+len(batch)}: ok")


def merge_states(volume_subs: list[dict], resend_steps: dict) -> list[dict]:
    """Combine Modal Volume + Resend history into final upsert rows.

    Treats a step as 'sent' if it appears in EITHER source.
    """
    by_email: dict = {}
    # Start from Volume (has all state we know about)
    for sub in volume_subs:
        email = sub["email"].lower().strip()
        by_email[email] = {
            "email": email,
            "name": sub.get("name") or None,
            "source": sub.get("source") or "supabase",
            "signed_up_at": sub.get("signed_up_at"),
            "drips_sent": list(set(sub.get("drips_sent") or [])),
            "unsubscribe_token": sub.get("unsubscribe_token") or uuid.uuid4().hex,
            "unsubscribed": bool(sub.get("unsubscribed")),
            "unsubscribed_at": sub.get("unsubscribed_at"),
            "upgraded": bool(sub.get("upgraded")),
            "upgraded_at": sub.get("upgraded_at"),
            "sent_at": {k.replace("sent_", "").replace("_at", ""): v
                        for k, v in sub.items() if k.startswith("sent_") and k.endswith("_at")},
        }
    # Augment from Resend history — anyone who has a send recorded gets the step marked
    for email, steps in resend_steps.items():
        if email in by_email:
            existing = set(by_email[email]["drips_sent"])
            existing.update(steps)
            by_email[email]["drips_sent"] = sorted(existing)
        else:
            by_email[email] = {
                "email": email,
                "source": "resend-backfill",
                "signed_up_at": datetime.now(timezone.utc).isoformat(),
                "drips_sent": sorted(steps),
                "unsubscribe_token": uuid.uuid4().hex,
                "unsubscribed": False,
                "upgraded": False,
                "sent_at": {},
            }
    return list(by_email.values())


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--commit", action="store_true",
                    help="Actually write to Supabase (default is dry-run)")
    ap.add_argument("--volume-state", default=DEFAULT_VOLUME_STATE)
    args = ap.parse_args()
    dry = not args.commit

    print(f"=== Backfill from Resend history ===")
    resend_steps = fetch_all_resend_signup_sends()
    print(f"  found send history for {len(resend_steps)} unique emails")

    print(f"=== Read Modal Volume state ===")
    volume = load_volume_state(args.volume_state)

    print(f"=== Merge ===")
    rows = merge_states(volume, resend_steps)
    # Stats
    step_count: dict = defaultdict(int)
    for r in rows:
        for s in r["drips_sent"]:
            step_count[s] += 1
    print(f"  total subscribers to upsert: {len(rows)}")
    print(f"  steps already sent (skipped on next cron):")
    for s, n in sorted(step_count.items(), key=lambda x: -x[1]):
        print(f"    {s}: {n} subscribers")

    print(f"=== Upsert (dry_run={dry}) ===")
    supabase_upsert(rows, dry_run=dry)
    print("done.")


if __name__ == "__main__":
    main()
