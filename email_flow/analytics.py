#!/usr/bin/env python3
"""
email_flow/analytics.py — Per-campaign engagement report from Resend.

Usage:
    python3 -m email_flow.analytics                # last 100 sends, all-time
    python3 -m email_flow.analytics --hours 24     # last 24h only
    python3 -m email_flow.analytics --pages 5      # walk 5 pages (500 sends)

Splits by campaign + kind:
    SIGNUP
        WELCOME       (transactional first email — instant on signup)
        FOLLOW-UP     (tips +1d, social +3d, upgrade +7d, winback +14d)
    DISCOUNT
        CODE EMAIL    (transactional first email — xangels sends on popup submit)
        FOLLOW-UP     (reminder +2d, preview +5d, urgency +7d)
    OTHER             (xangels' magic-link / signup-confirm emails)
"""
from __future__ import annotations
import os
import sys
import argparse
from collections import Counter, defaultdict
from datetime import datetime, timezone, timedelta
from pathlib import Path

import requests
from dotenv import load_dotenv

REPO_DIR = Path(__file__).resolve().parent.parent
load_dotenv(REPO_DIR / ".env", override=True)


def classify(e: dict) -> tuple:
    tags = {t.get("name"): t.get("value") for t in (e.get("tags") or [])}
    flow = tags.get("flow")
    step = tags.get("step")
    subj = (e.get("subject") or "").lower()
    if flow == "signup":
        kind = "transactional_first" if step == "welcome" else "followup"
        return ("SIGNUP", kind, step or "?")
    if flow == "discount":
        kind = "transactional_first" if step == "code" else "followup"
        return ("DISCOUNT", kind, step or "?")
    if "free 3-day premium code" in subj or "100free" in subj:
        return ("DISCOUNT", "transactional_first", "code(xangels)")
    if "magic link" in subj:
        return ("XANGELS_AUTH", "transactional_first", "magic_link")
    if "confirm your signup" in subj:
        return ("XANGELS_AUTH", "transactional_first", "confirm")
    return ("OTHER", "?", "?")


def fmt_metrics(rows: list[dict]) -> dict:
    events = Counter(r.get("last_event", "unknown") for r in rows)
    delivered = events.get("delivered", 0) + events.get("opened", 0) + events.get("clicked", 0)
    opened = events.get("opened", 0) + events.get("clicked", 0)
    clicked = events.get("clicked", 0)
    bounced = events.get("bounced", 0)
    sent = len(rows)
    open_rate = (opened / delivered * 100) if delivered else 0
    click_rate = (clicked / delivered * 100) if delivered else 0
    return dict(sent=sent, delivered=delivered, opened=opened, clicked=clicked,
                bounced=bounced, open_rate=open_rate, click_rate=click_rate)


def fetch_emails(pages: int, since_hours: int | None) -> list[dict]:
    H = {"Authorization": f"Bearer {os.environ['RESEND_API_KEY']}"}
    out = []
    cursor = None
    cutoff = (datetime.now(timezone.utc) - timedelta(hours=since_hours)) if since_hours else None
    for page_n in range(pages):
        url = "https://api.resend.com/emails?limit=100"
        if cursor:
            url += f"&before={cursor}"
        page = requests.get(url, headers=H, timeout=30).json().get("data", []) or []
        if not page:
            break
        # Refresh per id for accurate last_event
        for e in page:
            d = requests.get(f"https://api.resend.com/emails/{e['id']}", headers=H, timeout=30).json()
            if cutoff:
                try:
                    if datetime.fromisoformat(d["created_at"].replace("Z", "+00:00")) < cutoff:
                        return out
                except Exception:
                    pass
            out.append(d)
        cursor = page[-1]["created_at"]
        if len(page) < 100:
            break
    return out


def print_report(detailed: list[dict]) -> None:
    groups = defaultdict(list)
    for e in detailed:
        groups[classify(e)].append(e)

    line = "=" * 100
    print(line)
    print(f"  EMAIL DATA — {len(detailed)} send records")
    print(line)

    def section(title: str, campaign: str, kinds: list[tuple]) -> None:
        print(f"\n┌─ {title} ─")
        print(f"  {'KIND':<22} {'STEP':<14} {'SENT':>5} {'DELIV':>6} {'OPEN':>5} {'CLICK':>6} {'BNCE':>5} {'OPEN%':>6} {'CLICK%':>7}")
        print(f"  {'-'*22} {'-'*14} {'-'*5} {'-'*6} {'-'*5} {'-'*6} {'-'*5} {'-'*6} {'-'*7}")
        any_rows = False
        for kind, label in kinds:
            sub_total = Counter()
            label_show = label
            for (camp, k, step), rows in sorted(groups.items()):
                if camp == campaign and k == kind:
                    m = fmt_metrics(rows)
                    print(f"  {label_show[:22]:<22} {step:<14} {m['sent']:>5} {m['delivered']:>6} "
                          f"{m['opened']:>5} {m['clicked']:>6} {m['bounced']:>5} "
                          f"{m['open_rate']:>5.1f}% {m['click_rate']:>6.1f}%")
                    label_show = ""
                    any_rows = True
                    for kkey in ("sent", "delivered", "opened", "clicked", "bounced"):
                        sub_total[kkey] += m[kkey]
            if sub_total["sent"]:
                d = sub_total["delivered"]
                op = (sub_total["opened"] / d * 100) if d else 0
                cp = (sub_total["clicked"] / d * 100) if d else 0
                print(f"  {label+' total':<22} {'':<14} {sub_total['sent']:>5} {d:>6} "
                      f"{sub_total['opened']:>5} {sub_total['clicked']:>6} {sub_total['bounced']:>5} "
                      f"{op:>5.1f}% {cp:>6.1f}%")
        if not any_rows:
            print("  (no sends in this period)")

    section("CAMPAIGN: SIGNUP (account creation flow)", "SIGNUP",
            [("transactional_first", "WELCOME (first)"),
             ("followup", "FOLLOW-UP")])

    section("CAMPAIGN: DISCOUNT CODE (popup flow)", "DISCOUNT",
            [("transactional_first", "CODE (first)"),
             ("followup", "FOLLOW-UP")])

    section("XANGELS SYSTEM EMAILS", "XANGELS_AUTH",
            [("transactional_first", "AUTH/CONFIRM")])

    other = [(s, e) for s, rows in groups.items() if s[0] not in ("SIGNUP", "DISCOUNT", "XANGELS_AUTH") for e in rows]
    if other:
        print("\n┌─ OTHER ─")
        print(f"  total: {len(other)} sends not classified")

    print("\n" + "=" * 100)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--pages", type=int, default=1, help="Resend pages to walk (100 each)")
    ap.add_argument("--hours", type=int, default=None, help="Limit to last N hours")
    args = ap.parse_args()
    detailed = fetch_emails(pages=args.pages, since_hours=args.hours)
    print_report(detailed)


if __name__ == "__main__":
    main()
