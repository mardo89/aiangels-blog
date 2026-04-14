#!/usr/bin/env python3
"""
Bluesky Auto-Scheduler — posts content from bluesky_schedule.json
Run via GitHub Actions or manually: python3 bluesky_scheduler.py --date 2026-04-15
"""
import os, json, sys, time, logging, argparse
from datetime import datetime, date
from dotenv import load_dotenv

load_dotenv(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env"), override=True)
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(message)s')
log = logging.getLogger(__name__)

SCHEDULE_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "bluesky_schedule.json")
LOG_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "bluesky_post_log.json")

HANDLE = os.getenv("BLUESKY_HANDLE", "aiangels89.bsky.social")
APP_PASSWORD = os.getenv("BLUESKY_APP_PASSWORD", "")

def load_schedule():
    with open(SCHEDULE_FILE) as f:
        return json.load(f)

def load_log():
    if os.path.exists(LOG_FILE):
        with open(LOG_FILE) as f:
            return json.load(f)
    return {}

def save_log(data):
    with open(LOG_FILE, "w") as f:
        json.dump(data, f, indent=2)

def post_to_bluesky(text):
    from atproto import Client
    client = Client()
    client.login(HANDLE, APP_PASSWORD)
    post = client.send_post(text)
    return post.uri.split("/")[-1]

def run_day(target_date=None):
    schedule = load_schedule()
    post_log = load_log()

    if target_date is None:
        target_date = date.today().isoformat()

    day_data = None
    for day_key, data in schedule.items():
        if data["date"] == target_date:
            day_data = data
            day_name = day_key
            break

    if not day_data:
        log.info(f"No posts scheduled for {target_date}")
        return

    posts = day_data["posts"]
    log.info(f"═══ BLUESKY: {target_date} ({len(posts)} posts) ═══\n")

    for i, text in enumerate(posts):
        post_key = f"{target_date}:{i}"
        if post_key in post_log:
            log.info(f"  ⏭️  [{i+1}/{len(posts)}] (already posted)")
            continue

        try:
            result = post_to_bluesky(text)
            post_log[post_key] = {"id": result, "time": datetime.now().isoformat()}
            save_log(post_log)
            words = len(text.split())
            log.info(f"  ✅ [{i+1}/{len(posts)}] ({words}w): {result}")
        except Exception as e:
            log.error(f"  ❌ [{i+1}/{len(posts)}]: {e}")
        time.sleep(10)

    log.info(f"\n✅ Day complete: {target_date}")

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--date", type=str, default=None)
    parser.add_argument("--all", action="store_true")
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
