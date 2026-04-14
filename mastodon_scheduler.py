#!/usr/bin/env python3
"""
Mastodon Auto-Scheduler
Reads mastodon_schedule.json and posts content at scheduled times.
Run via: python3 mastodon_scheduler.py --date 2026-04-15
Or via GitHub Actions cron.
"""
import os, json, sys, time, logging, argparse
from datetime import datetime, date
import requests
from dotenv import load_dotenv

load_dotenv(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env"), override=True)
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(message)s')
log = logging.getLogger(__name__)

SCHEDULE_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "mastodon_schedule.json")
LOG_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "mastodon_post_log.json")

def load_schedule():
    with open(SCHEDULE_FILE) as f:
        return json.load(f)

def load_post_log():
    if os.path.exists(LOG_FILE):
        with open(LOG_FILE) as f:
            return json.load(f)
    return {}

def save_post_log(log_data):
    with open(LOG_FILE, "w") as f:
        json.dump(log_data, f, indent=2)

def post_to_mastodon(text):
    headers = {"Authorization": f"Bearer {os.getenv('MASTODON_ACCESS_TOKEN')}"}
    r = requests.post("https://mastodon.social/api/v1/statuses", headers=headers,
        data={"status": text, "visibility": "public"})
    if r.status_code in (200, 201):
        return r.json().get("url", "")
    return f"ERR:{r.status_code}"

def run_day(target_date=None):
    """Post all content for a specific date"""
    schedule = load_schedule()
    post_log = load_post_log()

    if target_date is None:
        target_date = date.today().isoformat()

    # Find the day matching this date
    day_data = None
    for day_key, data in schedule.items():
        if data["date"] == target_date:
            day_data = data
            break

    if not day_data:
        log.info(f"No posts scheduled for {target_date}")
        return

    posts = day_data["posts"]
    log.info(f"═══ MASTODON SCHEDULE: {target_date} ({len(posts)} posts) ═══\n")

    for i, p in enumerate(posts):
        post_key = f"{target_date}:{p['time']}:{p['type']}"
        if post_key in post_log:
            log.info(f"  ⏭️  [{i+1}/{len(posts)}] {p['time']} {p['type']} (already posted)")
            continue

        try:
            url = post_to_mastodon(p["text"])
            post_log[post_key] = {"url": url, "time": datetime.now().isoformat(), "type": p["type"]}
            save_post_log(post_log)
            words = len(p["text"].split())
            log.info(f"  ✅ [{i+1}/{len(posts)}] {p['time']} {p['type']:12s} ({words}w): {url}")
        except Exception as e:
            log.error(f"  ❌ [{i+1}/{len(posts)}] {p['time']} {p['type']}: {e}")
        time.sleep(8)

    log.info(f"\n✅ Day complete: {target_date}")

def main():
    parser = argparse.ArgumentParser(description="Mastodon Auto-Scheduler")
    parser.add_argument("--date", type=str, help="Target date (YYYY-MM-DD)", default=None)
    parser.add_argument("--all", action="store_true", help="Post all remaining scheduled content now")
    args = parser.parse_args()

    if args.all:
        schedule = load_schedule()
        for day_key, data in sorted(schedule.items()):
            run_day(data["date"])
            time.sleep(5)
    else:
        run_day(args.date)

if __name__ == "__main__":
    main()
