#!/usr/bin/env python3
"""Tumblr Auto-Scheduler — 3 posts/day, safe organic pace"""
import os, json, time, logging, argparse
from datetime import datetime, date
from dotenv import load_dotenv
from requests_oauthlib import OAuth1Session

load_dotenv(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env"), override=True)
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(message)s')
log = logging.getLogger(__name__)

SCHEDULE_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "tumblr_schedule.json")
LOG_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "tumblr_post_log.json")

def get_oauth():
    return OAuth1Session(
        os.getenv("TUMBLR_CONSUMER_KEY"), client_secret=os.getenv("TUMBLR_CONSUMER_SECRET"),
        resource_owner_key=os.getenv("TUMBLR_OAUTH_TOKEN"), resource_owner_secret=os.getenv("TUMBLR_OAUTH_SECRET"))

def load_log():
    if os.path.exists(LOG_FILE):
        with open(LOG_FILE) as f: return json.load(f)
    return {}

def save_log(d):
    with open(LOG_FILE, "w") as f: json.dump(d, f, indent=2)

def run_day(target_date=None):
    with open(SCHEDULE_FILE) as f: schedule = json.load(f)
    post_log = load_log()
    if target_date is None: target_date = date.today().isoformat()

    day_data = None
    for dk, d in schedule.items():
        if d["date"] == target_date:
            day_data = d; break
    if not day_data:
        log.info(f"No posts for {target_date}"); return

    oauth = get_oauth()
    posts = day_data["posts"]
    log.info(f"═══ TUMBLR: {target_date} ({len(posts)} posts) ═══\n")

    for i, p in enumerate(posts):
        key = f"{target_date}:{i}"
        if key in post_log:
            log.info(f"  ⏭️  [{i+1}/{len(posts)}] already posted"); continue
        try:
            data = {"state": "published", "tags": p["tags"]}
            if p["type"] == "photo":
                data.update({"type": "photo", "caption": p["caption"], "source": p["source"]})
            else:
                data.update({"type": "text", "body": p["body"]})
            r = oauth.post("https://api.tumblr.com/v2/blog/aiangelsofficial/post", data=data)
            pid = r.json().get("response", {}).get("id", "")
            post_log[key] = {"id": str(pid), "time": datetime.now().isoformat()}
            save_log(post_log)
            icon = "📷" if p["type"] == "photo" else "💬"
            log.info(f"  ✅ [{i+1}/{len(posts)}] {icon} {pid}")
        except Exception as e:
            log.error(f"  ❌ [{i+1}/{len(posts)}]: {e}")
        time.sleep(15)
    log.info(f"\n✅ Done: {target_date}")

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--date", type=str, default=None)
    parser.add_argument("--all", action="store_true")
    args = parser.parse_args()
    if args.all:
        with open(SCHEDULE_FILE) as f: schedule = json.load(f)
        for dk, d in sorted(schedule.items()):
            run_day(d["date"]); time.sleep(5)
    else:
        run_day(args.date)

if __name__ == "__main__":
    main()
