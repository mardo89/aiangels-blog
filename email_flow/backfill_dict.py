#!/usr/bin/env python3
"""
email_flow/backfill_dict.py — One-shot: pre-populate Modal Dicts with every send
that's already happened (per Resend's send log) so nobody gets a duplicate.

Run as a Modal one-off (has access to the named Dicts):
    modal run email_flow/backfill_dict.py::main

What it does:
    1. Walks Resend's full email history (paginated).
    2. For each `flow=signup` send, claims the (email, step) entry in the
       aiangels-signup-claims Dict — same atomic primitive cron uses.
    3. Upserts a subscriber row in aiangels-signup-subs so run_drips() iterates
       them (with signed_up_at set to the earliest send time we have).

Result: when cron next ticks, every user who already received `welcome`
returns False on `_claim_step('welcome')` and is silently skipped. They cannot
get a duplicate. Same for tips, social, etc.

Backfilling 100 most recent sends takes ~30s. Resend's full history is bigger;
we paginate via `before` cursor.
"""
from __future__ import annotations
import os
import uuid
import time
from collections import defaultdict
from datetime import datetime, timezone

import modal

app = modal.App("aiangels-email-flow-backfill")

image = (
    modal.Image.debian_slim(python_version="3.11")
    .pip_install("requests", "python-dotenv")
)

secret = modal.Secret.from_name("resend-prod")


@app.function(image=image, secrets=[secret], timeout=900)
def main(commit: bool = False) -> dict:
    import requests

    key = os.environ["RESEND_API_KEY"]
    H = {"Authorization": f"Bearer {key}"}

    subs_dict = modal.Dict.from_name("aiangels-signup-subs", create_if_missing=True)
    claims_dict = modal.Dict.from_name("aiangels-signup-claims", create_if_missing=True)

    print(f"=== walking Resend history ===")
    sends_by_email: dict = defaultdict(dict)  # email → {step: (created_at, resend_id)}
    cursor = None
    pages = 0
    total = 0
    while True:
        url = "https://api.resend.com/emails?limit=100"
        if cursor:
            url += f"&before={cursor}"
        page = requests.get(url, headers=H, timeout=30).json().get("data", []) or []
        if not page:
            break
        for e in page:
            d = requests.get(f"https://api.resend.com/emails/{e['id']}", headers=H, timeout=30).json()
            tags = {t.get("name"): t.get("value") for t in (d.get("tags") or [])}
            if tags.get("flow") != "signup":
                continue
            step = tags.get("step")
            if not step:
                continue
            for to in d.get("to", []) or []:
                em = to.lower().strip()
                # Keep earliest send per (email, step)
                prev = sends_by_email[em].get(step)
                this = (d["created_at"], d["id"])
                if prev is None or this[0] < prev[0]:
                    sends_by_email[em][step] = this
            total += 1
        pages += 1
        cursor = page[-1]["created_at"]
        print(f"  page {pages}: cumulative signup sends inspected = {total}")
        if len(page) < 100:
            break
        time.sleep(0.2)  # polite

    print(f"=== unique recipients with sends: {len(sends_by_email)} ===")

    # Upsert subscribers (with earliest signed_up_at across all their sends)
    subs_written = 0
    claims_written = 0
    for email, steps in sends_by_email.items():
        earliest = min(s[0] for s in steps.values())
        sub = {
            "email": email,
            "name": "",
            "source": "resend-backfill",
            "signed_up_at": earliest,
            "unsubscribe_token": uuid.uuid4().hex,
            "unsubscribed": False,
            "upgraded": False,
        }
        if commit:
            # Don't overwrite if already enrolled (web container may have written newer state)
            written = subs_dict.put(email, sub, skip_if_exists=True)
            if written:
                subs_written += 1

            # Claim every step that already shipped — atomic, idempotent
            for step, (created_at, resend_id) in steps.items():
                claim = {"sent_at": created_at, "resend_id": resend_id, "backfill": True}
                if claims_dict.put(f"{email}:{step}", claim, skip_if_exists=True):
                    claims_written += 1

    if not commit:
        print(f"[dry-run] would upsert subs={len(sends_by_email)}, claims={sum(len(s) for s in sends_by_email.values())}")
    else:
        print(f"=== wrote subs (new only): {subs_written} ===")
        print(f"=== wrote claims (new only): {claims_written} ===")
    return {"emails": len(sends_by_email), "subs_written": subs_written, "claims_written": claims_written}


@app.local_entrypoint()
def run(commit: bool = False):
    result = main.remote(commit=commit)
    print(result)
