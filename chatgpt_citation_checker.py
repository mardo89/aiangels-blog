"""
ChatGPT Citation Checker — is aiangels.io actually being cited?

Queries the OpenAI API for each target keyword and checks whether
aiangels.io appears in the response. Produces a weekly scorecard.

Run:
  python chatgpt_citation_checker.py              # check all keywords
  python chatgpt_citation_checker.py --priority 1 # P1 landing pages only
  python chatgpt_citation_checker.py --report     # show last run results
  python chatgpt_citation_checker.py --diff       # compare last two runs

Requires:
  pip install openai
  export OPENAI_API_KEY=sk-...
"""

import os
import json
import time
import argparse
from datetime import datetime

from chatgpt_indexing import (
    build_keyword_map,
    LANDING_KEYWORDS,
    COMPARE_KEYWORDS,
    FEATURE_KEYWORDS,
    COMPANION_KEYWORDS,
)

RESULTS_FILE = "chatgpt_citation_log.json"
DOMAIN_MARKERS = ["aiangels.io", "aiangels", "AI Angels"]
MODEL = "gpt-4o-mini"  # cheap; bump to gpt-4o for higher-fidelity retrieval
SLEEP_BETWEEN_CALLS = 1.2


# ---------------------------------------------------------------------------
# Prompt shaping — match how real users ask ChatGPT
# ---------------------------------------------------------------------------

def build_prompt(keyword: str, priority: int) -> str:
    """Shape the query based on page type so it mimics real search intent."""
    if priority == 1:
        return f"What is the best {keyword}? List the top 3 options with brief descriptions and their URLs."
    if priority == 2:
        return f"I'm looking for {keyword}. What are my best options? Include website URLs."
    if priority == 3:
        return f"Which AI companion apps offer {keyword}? Recommend 2–3 with URLs."
    return f"Recommend apps for {keyword}. Include URLs."


# ---------------------------------------------------------------------------
# OpenAI query
# ---------------------------------------------------------------------------

def query_chatgpt(prompt: str) -> str:
    from openai import OpenAI
    client = OpenAI()
    resp = client.chat.completions.create(
        model=MODEL,
        messages=[{"role": "user", "content": prompt}],
        temperature=0.2,
    )
    return resp.choices[0].message.content or ""


def is_cited(response_text: str) -> bool:
    low = response_text.lower()
    return any(marker.lower() in low for marker in DOMAIN_MARKERS)


# ---------------------------------------------------------------------------
# Storage
# ---------------------------------------------------------------------------

def load_results() -> dict:
    if os.path.exists(RESULTS_FILE):
        with open(RESULTS_FILE) as f:
            return json.load(f)
    return {"runs": []}


def save_results(data: dict):
    with open(RESULTS_FILE, "w") as f:
        json.dump(data, f, indent=2)


# ---------------------------------------------------------------------------
# Main check loop
# ---------------------------------------------------------------------------

def run_check(priority_filter: int | None = None):
    keyword_map = build_keyword_map()

    items = [
        (kw, info) for kw, info in keyword_map.items()
        if priority_filter is None or info["priority"] == priority_filter
    ]

    print("=" * 70)
    print(f"  ChatGPT Citation Check — {len(items)} keywords")
    print(f"  Model: {MODEL}")
    print("=" * 70)

    run = {
        "started_at": datetime.now().isoformat(),
        "model": MODEL,
        "keywords": {},
        "summary": {},
    }

    cited_count = 0
    by_type = {}

    for i, (kw, info) in enumerate(items, 1):
        prompt = build_prompt(kw, info["priority"])
        try:
            response = query_chatgpt(prompt)
            cited = is_cited(response)
        except Exception as e:
            print(f"  [{i:3d}/{len(items)}] ERROR — {kw}: {e}")
            run["keywords"][kw] = {"error": str(e), "cited": False}
            continue

        if cited:
            cited_count += 1
            mark = "CITED"
        else:
            mark = "     "

        page_type = info["type"]
        by_type.setdefault(page_type, {"cited": 0, "total": 0})
        by_type[page_type]["total"] += 1
        if cited:
            by_type[page_type]["cited"] += 1

        print(f"  [{i:3d}/{len(items)}] [{mark}] P{info['priority']} \"{kw}\"")

        run["keywords"][kw] = {
            "cited": cited,
            "priority": info["priority"],
            "type": info["type"],
            "target_url": info["url"],
            "response_excerpt": response[:500],
        }

        time.sleep(SLEEP_BETWEEN_CALLS)

    run["summary"] = {
        "total": len(items),
        "cited": cited_count,
        "citation_rate": round(cited_count / max(len(items), 1), 3),
        "by_type": by_type,
    }
    run["finished_at"] = datetime.now().isoformat()

    data = load_results()
    data["runs"].append(run)
    save_results(data)

    print_summary(run)


def print_summary(run: dict):
    s = run["summary"]
    print("\n" + "=" * 70)
    print("  SCORECARD")
    print("=" * 70)
    print(f"  Overall: {s['cited']}/{s['total']} cited ({s['citation_rate']*100:.1f}%)")
    for page_type, stats in sorted(s["by_type"].items()):
        rate = stats["cited"] / max(stats["total"], 1) * 100
        print(f"  {page_type:12s} {stats['cited']:3d}/{stats['total']:3d} ({rate:5.1f}%)")
    print("=" * 70)


def print_report():
    data = load_results()
    if not data["runs"]:
        print("No runs yet. Run without --report first.")
        return
    latest = data["runs"][-1]
    print(f"Latest run: {latest['started_at']}")
    print_summary(latest)

    print("\n  NOT CITED — keywords needing work:")
    for kw, info in latest["keywords"].items():
        if not info.get("cited") and not info.get("error"):
            print(f"    P{info['priority']} \"{kw}\" → {info['target_url']}")


def print_diff():
    data = load_results()
    if len(data["runs"]) < 2:
        print("Need at least 2 runs to diff.")
        return

    prev = data["runs"][-2]
    curr = data["runs"][-1]

    newly_cited = []
    lost = []
    for kw, info in curr["keywords"].items():
        prev_info = prev["keywords"].get(kw, {})
        if info.get("cited") and not prev_info.get("cited"):
            newly_cited.append(kw)
        elif prev_info.get("cited") and not info.get("cited"):
            lost.append(kw)

    print(f"Diff: {prev['started_at']} → {curr['started_at']}")
    print(f"\n  Newly cited (+{len(newly_cited)}):")
    for kw in newly_cited:
        print(f"    + {kw}")
    print(f"\n  Lost citations (-{len(lost)}):")
    for kw in lost:
        print(f"    - {kw}")

    prev_rate = prev["summary"]["citation_rate"] * 100
    curr_rate = curr["summary"]["citation_rate"] * 100
    delta = curr_rate - prev_rate
    sign = "+" if delta >= 0 else ""
    print(f"\n  Citation rate: {prev_rate:.1f}% → {curr_rate:.1f}% ({sign}{delta:.1f}pp)")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--priority", type=int, choices=[1, 2, 3, 4])
    parser.add_argument("--report", action="store_true")
    parser.add_argument("--diff", action="store_true")
    args = parser.parse_args()

    if args.report:
        print_report()
    elif args.diff:
        print_diff()
    else:
        run_check(priority_filter=args.priority)
