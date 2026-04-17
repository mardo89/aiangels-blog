"""
ChatGPT Search Indexing — Mastermind Strategy

ChatGPT search uses Bing's index. This script:
  1. Maps every page to its target keywords (what people ask ChatGPT)
  2. Prioritizes high-value pages first
  3. Submits all URLs via IndexNow → Bing → ChatGPT/Yandex/DuckDuckGo
  4. Tracks keyword coverage and indexing status

Run:
  python chatgpt_indexing.py              # submit all pending
  python chatgpt_indexing.py --force      # resubmit everything
  python chatgpt_indexing.py --report     # keyword coverage report only
"""

import os
import json
import time
import requests
import xml.etree.ElementTree as ET
from datetime import datetime

SITEMAP_URL = "https://www.aiangels.io/sitemap.xml"
LOG_FILE = "chatgpt_indexing_log.json"
HOST = "www.aiangels.io"
BASE_URL = "https://www.aiangels.io"

# IndexNow submits to all engines simultaneously
INDEXNOW_ENDPOINTS = [
    "https://api.indexnow.org/indexnow",
    "https://www.bing.com/indexnow",
    "https://yandex.com/indexnow",
]

# API key — set INDEXNOW_KEY in .env or use default
KEY = os.environ.get("INDEXNOW_KEY", "a1b2c3d4e5f6a7b8")

# ---------------------------------------------------------------------------
# KEYWORD STRATEGY — every page mapped to what people ask ChatGPT
# ---------------------------------------------------------------------------

# Priority 1: Landing pages — highest search volume keywords
LANDING_KEYWORDS = {
    "ai-girlfriend": [
        "ai girlfriend", "best ai girlfriend", "ai girlfriend 2026",
        "ai girlfriend app", "ai girlfriend online", "free ai girlfriend",
        "ai girlfriend chat", "talk to ai girlfriend",
    ],
    "hot-ai-girlfriend": [
        "hot ai girlfriend", "sexy ai girlfriend", "ai girlfriend nsfw",
        "nsfw ai chat", "adult ai girlfriend",
    ],
    "real-ai-girlfriend": [
        "real ai girlfriend", "realistic ai girlfriend",
        "ai girlfriend that feels real", "lifelike ai girlfriend",
    ],
    "ai-girlfriend-app": [
        "ai girlfriend app", "best ai girlfriend app 2026",
        "ai girlfriend app free", "ai girlfriend app no filter",
    ],
    "ai-sexy-chat": [
        "ai sexy chat", "sexy ai chat", "ai chat nsfw",
        "nsfw ai chatbot", "adult ai chat",
    ],
    "ai-sexting-chat": [
        "ai sexting", "ai sexting chat", "sext ai",
        "ai sexting app", "ai sexting bot",
    ],
    "ai-jerk-off-chat": [
        "ai jerk off chat", "ai joi", "ai joi chat",
    ],
    "ai-chat-18": [
        "ai chat 18+", "18+ ai chat", "adult ai chat",
        "ai chatbot 18+", "nsfw ai chat no filter",
    ],
    "create-ai-girlfriend": [
        "create ai girlfriend", "make ai girlfriend",
        "build your own ai girlfriend", "custom ai girlfriend",
    ],
}

# Priority 2: Competitor comparison pages — people searching alternatives
COMPARE_KEYWORDS = {
    "replika-alternative": [
        "replika alternative", "replika alternative 2026", "better than replika",
        "replika replacement", "apps like replika", "replika nsfw alternative",
    ],
    "character-ai-alternative": [
        "character ai alternative", "character.ai alternative",
        "character ai alternative nsfw", "apps like character ai",
        "character ai replacement",
    ],
    "character-ai-nsfw-alternative": [
        "character ai nsfw", "character ai nsfw alternative",
        "character ai without filter", "unfiltered character ai",
        "character ai no restrictions",
    ],
    "candy-ai-alternative": [
        "candy ai alternative", "better than candy ai",
        "candy ai replacement", "apps like candy ai",
    ],
    "crushon-ai-alternative": [
        "crushon ai alternative", "better than crushon",
        "crushon ai replacement", "apps like crushon ai",
    ],
    "janitor-ai-alternative": [
        "janitor ai alternative", "janitor ai replacement",
        "better than janitor ai", "janitor ai down alternative",
    ],
    "spicychat-alternative": [
        "spicychat alternative", "spicychat ai alternative",
        "better than spicychat", "apps like spicychat",
    ],
    "nomi-ai-alternative": [
        "nomi ai alternative", "better than nomi ai",
        "nomi replacement",
    ],
    "kindroid-alternative": [
        "kindroid alternative", "better than kindroid",
        "kindroid replacement",
    ],
    "girlfriendgpt-alternative": [
        "girlfriendgpt alternative", "girlfriend gpt alternative",
        "better than girlfriendgpt",
    ],
    "anima-ai-alternative": [
        "anima ai alternative", "better than anima ai",
        "anima replacement",
    ],
    "romantic-ai-alternative": [
        "romantic ai alternative", "better than romantic ai",
        "romantic ai replacement",
    ],
}

# Priority 3: Feature pages — specific capability queries
FEATURE_KEYWORDS = {
    "uncensored-ai-girlfriend": [
        "uncensored ai girlfriend", "uncensored ai chat",
        "ai girlfriend no filter", "ai chat no restrictions",
        "unfiltered ai girlfriend", "nsfw ai girlfriend",
    ],
    "ai-girlfriend-memory": [
        "ai girlfriend with memory", "ai that remembers",
        "ai girlfriend memory", "ai chatbot with long term memory",
    ],
    "ai-girlfriend-voice-chat": [
        "ai girlfriend voice chat", "talk to ai girlfriend voice",
        "ai girlfriend voice call", "ai girlfriend you can talk to",
    ],
    "ai-girlfriend-images": [
        "ai girlfriend images", "ai girlfriend pictures",
        "ai girlfriend photo", "ai girlfriend selfie",
    ],
    "ai-girlfriend-roleplay": [
        "ai girlfriend roleplay", "ai roleplay chat",
        "ai roleplay nsfw", "ai girlfriend rp",
    ],
    "customize-ai-girlfriend": [
        "customize ai girlfriend", "custom ai girlfriend",
        "design ai girlfriend", "make your own ai girlfriend",
    ],
    "ai-girlfriend-always-available": [
        "ai girlfriend 24/7", "ai girlfriend always online",
        "ai chat always available",
    ],
    "unlimited-ai-girlfriend-chat": [
        "unlimited ai chat", "free unlimited ai girlfriend",
        "ai girlfriend no message limit", "ai chat no limit",
    ],
    "emotional-support": [
        "ai emotional support", "ai girlfriend emotional support",
        "ai companion for loneliness", "ai chat for lonely people",
    ],
    "realistic-companions": [
        "realistic ai companion", "realistic ai girlfriend",
        "ai companion that feels real",
    ],
    "smart-ai-girlfriend": [
        "smart ai girlfriend", "intelligent ai girlfriend",
        "ai girlfriend deep conversations",
    ],
    "relationship-growth": [
        "ai relationship growth", "ai girlfriend that learns",
        "ai girlfriend evolves",
    ],
    "consistent-personality": [
        "ai consistent personality", "ai girlfriend personality",
        "ai that stays in character",
    ],
}

# Priority 4: Companion category pages — niche/type keywords
COMPANION_KEYWORDS = {
    "blonde-ai-girlfriend": ["blonde ai girlfriend", "blonde ai chat"],
    "brunette-ai-girlfriend": ["brunette ai girlfriend"],
    "redhead-ai-girlfriend": ["redhead ai girlfriend", "ginger ai girlfriend"],
    "asian-ai-girlfriend": ["asian ai girlfriend", "asian ai chat"],
    "japanese-ai-girlfriend": ["japanese ai girlfriend", "japanese ai chat"],
    "korean-ai-girlfriend": ["korean ai girlfriend", "korean ai chat"],
    "chinese-ai-girlfriend": ["chinese ai girlfriend"],
    "indian-ai-girlfriend": ["indian ai girlfriend"],
    "latina-ai-girlfriend": ["latina ai girlfriend", "latin ai girlfriend"],
    "black-ai-girlfriend": ["black ai girlfriend"],
    "white-ai-girlfriend": ["white ai girlfriend"],
    "russian-ai-girlfriend": ["russian ai girlfriend"],
    "arab-ai-girlfriend": ["arab ai girlfriend", "arabic ai girlfriend"],
    "brazilian-ai-girlfriend": ["brazilian ai girlfriend"],
    "french-ai-girlfriend": ["french ai girlfriend"],
    "italian-ai-girlfriend": ["italian ai girlfriend"],
    "mexican-ai-girlfriend": ["mexican ai girlfriend"],
    "thai-ai-girlfriend": ["thai ai girlfriend"],
    "filipino-ai-girlfriend": ["filipina ai girlfriend", "filipino ai girlfriend"],
    "vietnamese-ai-girlfriend": ["vietnamese ai girlfriend"],
    "persian-ai-girlfriend": ["persian ai girlfriend"],
    "middle-eastern-ai-girlfriend": ["middle eastern ai girlfriend"],
    "swedish-ai-girlfriend": ["swedish ai girlfriend"],
    "busty-ai-girlfriend": ["busty ai girlfriend", "big boobs ai girlfriend"],
    "petite-ai-girlfriend": ["petite ai girlfriend"],
    "curvy-ai-girlfriend": ["curvy ai girlfriend"],
    "fit-ai-girlfriend": ["fit ai girlfriend", "athletic ai girlfriend"],
    "big-ass-ai-girlfriend": ["big ass ai girlfriend", "thicc ai girlfriend"],
    "milf-ai-girlfriend": ["milf ai girlfriend", "milf ai chat"],
    "goth-ai-girlfriend": ["goth ai girlfriend", "goth ai chat"],
    "e-girl-ai-girlfriend": ["e-girl ai girlfriend", "egirl ai"],
    "dominant-ai-girlfriend": ["dominant ai girlfriend", "domme ai girlfriend"],
    "submissive-ai-girlfriend": ["submissive ai girlfriend", "sub ai girlfriend"],
    "shy-ai-girlfriend": ["shy ai girlfriend"],
    "jealous-ai-girlfriend": ["jealous ai girlfriend", "possessive ai girlfriend"],
    "pink-hair-ai-girlfriend": ["pink hair ai girlfriend"],
    "black-hair-ai-girlfriend": ["black hair ai girlfriend"],
}


def build_keyword_map():
    """Build complete keyword → URL mapping with priority scores."""
    keyword_map = {}

    # Landing pages — priority 1 (highest)
    for slug, keywords in LANDING_KEYWORDS.items():
        url = f"{BASE_URL}/{slug}" if slug else BASE_URL
        for kw in keywords:
            keyword_map[kw] = {"url": url, "priority": 1, "type": "landing"}

    # Compare pages — priority 2
    for slug, keywords in COMPARE_KEYWORDS.items():
        url = f"{BASE_URL}/compare/{slug}"
        for kw in keywords:
            keyword_map[kw] = {"url": url, "priority": 2, "type": "compare"}

    # Feature pages — priority 3
    for slug, keywords in FEATURE_KEYWORDS.items():
        url = f"{BASE_URL}/features/{slug}"
        for kw in keywords:
            keyword_map[kw] = {"url": url, "priority": 3, "type": "feature"}

    # Companion categories — priority 4
    for slug, keywords in COMPANION_KEYWORDS.items():
        url = f"{BASE_URL}/companions/{slug}"
        for kw in keywords:
            keyword_map[kw] = {"url": url, "priority": 4, "type": "companion"}

    return keyword_map


def get_priority_urls():
    """Return all URLs sorted by submission priority."""
    priority_urls = []

    # P1: Landing pages
    for slug in LANDING_KEYWORDS:
        priority_urls.append(f"{BASE_URL}/{slug}")

    # P2: Compare pages
    for slug in COMPARE_KEYWORDS:
        priority_urls.append(f"{BASE_URL}/compare/{slug}")

    # P3: Feature pages
    for slug in FEATURE_KEYWORDS:
        priority_urls.append(f"{BASE_URL}/features/{slug}")

    # P4: Companion category pages
    for slug in COMPANION_KEYWORDS:
        priority_urls.append(f"{BASE_URL}/companions/{slug}")

    return priority_urls


# ---------------------------------------------------------------------------
# Sitemap
# ---------------------------------------------------------------------------

def fetch_sitemap_urls():
    urls = []
    resp = requests.get(SITEMAP_URL, timeout=30)
    resp.raise_for_status()
    root = ET.fromstring(resp.content)
    ns = {"s": "http://www.sitemaps.org/schemas/sitemap/0.9"}

    sitemaps = root.findall("s:sitemap/s:loc", ns)
    if sitemaps:
        for sitemap_loc in sitemaps:
            sub_resp = requests.get(sitemap_loc.text.strip(), timeout=30)
            sub_resp.raise_for_status()
            sub_root = ET.fromstring(sub_resp.content)
            for url_el in sub_root.findall("s:url/s:loc", ns):
                urls.append(url_el.text.strip())
    else:
        for url_el in root.findall("s:url/s:loc", ns):
            urls.append(url_el.text.strip())

    return urls


# ---------------------------------------------------------------------------
# Log
# ---------------------------------------------------------------------------

def load_log():
    if os.path.exists(LOG_FILE):
        with open(LOG_FILE) as f:
            return json.load(f)
    return {}


def save_log(log):
    with open(LOG_FILE, "w") as f:
        json.dump(log, f, indent=2)


# ---------------------------------------------------------------------------
# IndexNow submission
# ---------------------------------------------------------------------------

def submit_batch(urls, endpoint):
    payload = {
        "host": HOST,
        "key": KEY,
        "keyLocation": f"https://{HOST}/{KEY}.txt",
        "urlList": urls,
    }
    resp = requests.post(
        endpoint,
        headers={"Content-Type": "application/json; charset=utf-8"},
        json=payload,
        timeout=30,
    )
    return resp.status_code, resp.text


# ---------------------------------------------------------------------------
# Report
# ---------------------------------------------------------------------------

def print_report():
    keyword_map = build_keyword_map()
    log = load_log()

    print("=" * 70)
    print("KEYWORD COVERAGE REPORT — AI Angels × ChatGPT")
    print("=" * 70)

    total_kw = len(keyword_map)
    indexed_kw = 0
    by_type = {"landing": [], "compare": [], "feature": [], "companion": []}

    for kw, info in sorted(keyword_map.items(), key=lambda x: x[1]["priority"]):
        url = info["url"]
        submitted = url in log and log[url].get("status") in (200, 202)
        if submitted:
            indexed_kw += 1
        by_type[info["type"]].append((kw, url, submitted))

    for page_type, label in [
        ("landing", "LANDING PAGES (P1 — highest volume)"),
        ("compare", "COMPETITOR PAGES (P2 — alternative seekers)"),
        ("feature", "FEATURE PAGES (P3 — specific needs)"),
        ("companion", "COMPANION TYPES (P4 — niche targeting)"),
    ]:
        items = by_type[page_type]
        submitted_count = sum(1 for _, _, s in items if s)
        print(f"\n{'─' * 70}")
        print(f"  {label}")
        print(f"  {submitted_count}/{len(items)} keywords submitted")
        print(f"{'─' * 70}")
        for kw, url, submitted in items:
            status = "OK" if submitted else "PENDING"
            short_url = url.replace(BASE_URL, "")
            print(f"  [{status:7s}] \"{kw}\" → {short_url}")

    print(f"\n{'=' * 70}")
    print(f"  TOTAL: {indexed_kw}/{total_kw} keywords covered")
    print(f"  Unique URLs: {len(set(info['url'] for info in keyword_map.values()))}")
    print(f"{'=' * 70}")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    print("=" * 70)
    print("  ChatGPT / IndexNow Indexing — AI Angels Mastermind")
    print("  Submits to: Bing → ChatGPT | Yandex | DuckDuckGo")
    print("=" * 70)

    # Step 1: Fetch all sitemap URLs
    print("\n[1/4] Fetching sitemap...")
    sitemap_urls = fetch_sitemap_urls()
    print(f"  Sitemap: {len(sitemap_urls)} URLs")

    # Step 2: Build priority-ordered URL list
    print("\n[2/4] Building priority queue...")
    priority_urls = get_priority_urls()

    # Merge: priority URLs first, then remaining sitemap URLs
    seen = set(priority_urls)
    all_urls = list(priority_urls)
    for u in sitemap_urls:
        if u not in seen:
            all_urls.append(u)
            seen.add(u)

    print(f"  Priority pages: {len(priority_urls)}")
    print(f"  Total to submit: {len(all_urls)}")

    # Step 3: Filter already submitted
    log = load_log()
    pending = [
        u for u in all_urls
        if u not in log or log[u].get("status") not in (200, 202)
    ]
    already = len(all_urls) - len(pending)

    print(f"\n[3/4] Status check...")
    print(f"  Already submitted: {already}")
    print(f"  Pending: {len(pending)}")

    if not pending:
        print("\n  All URLs already submitted! Use --force to resubmit.")
        print_report()
        return

    # Step 4: Submit to all IndexNow endpoints
    print(f"\n[4/4] Submitting {len(pending)} URLs to IndexNow...")

    for endpoint in INDEXNOW_ENDPOINTS:
        engine = endpoint.split("//")[1].split("/")[0].split(".")[0]
        if engine == "api":
            engine = "indexnow-hub"

        try:
            status, resp_text = submit_batch(pending, endpoint)
            now = datetime.now().isoformat()

            if status in (200, 202):
                label = "OK" if status == 200 else "ACCEPTED"
                print(f"  {engine:15s} → {label} ({status}) — {len(pending)} URLs")
                for url in pending:
                    if url not in log or log[url].get("status") not in (200, 202):
                        log[url] = {"status": status, "submitted_at": now}
            else:
                print(f"  {engine:15s} → FAILED ({status}) — {resp_text[:100]}")
                for url in pending:
                    if url not in log or log[url].get("status") not in (200, 202):
                        log[url] = {
                            "status": status,
                            "error": resp_text[:200],
                            "submitted_at": now,
                        }
        except Exception as e:
            print(f"  {engine:15s} → ERROR — {e}")

        time.sleep(2)

    save_log(log)

    # Summary
    keyword_map = build_keyword_map()
    print(f"\n{'=' * 70}")
    print(f"  DONE!")
    print(f"  URLs submitted: {len(pending)}")
    print(f"  Keywords covered: {len(keyword_map)}")
    print(f"  Log: {LOG_FILE}")
    print(f"{'=' * 70}")
    print(f"\n  How it works:")
    print(f"  IndexNow → Bing indexes pages → ChatGPT search surfaces them")
    print(f"  When users ask ChatGPT about these keywords, your pages appear.")


if __name__ == "__main__":
    import sys

    if "--force" in sys.argv:
        if os.path.exists(LOG_FILE):
            os.remove(LOG_FILE)
            print("Cleared log. Resubmitting all URLs.\n")

    if "--report" in sys.argv:
        print_report()
    else:
        main()
        print()
        print_report()
