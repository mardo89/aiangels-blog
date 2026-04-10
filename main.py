import os
import json
import time
import html
import hashlib
import logging
import requests
import xml.etree.ElementTree as ET
from datetime import datetime
from dotenv import load_dotenv
import anthropic
from supabase import create_client
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from google.auth.transport.requests import Request
from googleapiclient.discovery import build
import pickle
import random

# Setup
_env_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env")
load_dotenv(dotenv_path=_env_path, override=True)
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(message)s')
log = logging.getLogger(__name__)

# Config
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY")
SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_SERVICE_ROLE_KEY")
BLOGGER_BLOG_ID = os.getenv("BLOGGER_BLOG_ID")
SITEMAP_URL = "https://www.aiangels.io/sitemap.xml"
SCOPES = ["https://www.googleapis.com/auth/blogger"]
BASE_URL = "https://www.aiangels.io"
BLOGGER_URL = "https://aiangels-ai.blogspot.com"

# Clients
claude = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
supabase = create_client(SUPABASE_URL, SUPABASE_KEY)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def get_blogger_service():
    creds = None
    if os.path.exists("token.pickle"):
        with open("token.pickle", "rb") as f:
            creds = pickle.load(f)
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            flow = InstalledAppFlow.from_client_secrets_file("client_secret.json", SCOPES)
            creds = flow.run_local_server(port=0)
        with open("token.pickle", "wb") as f:
            pickle.dump(creds, f)
    return build("blogger", "v3", credentials=creds)


def get_processed_urls():
    result = supabase.table("blog_posts").select("url,title,blogger_post_id").execute()
    return result.data


def get_processed_url_set():
    return set(row["url"] for row in get_processed_urls())


def mark_url_processed(url, title, blogger_post_id):
    supabase.table("blog_posts").insert({
        "url": url,
        "title": title,
        "blogger_post_id": blogger_post_id,
        "created_at": datetime.utcnow().isoformat()
    }).execute()


def fetch_sitemap_urls():
    log.info("Fetching sitemap...")
    r = requests.get(SITEMAP_URL, timeout=30)
    root = ET.fromstring(r.content)
    ns = {"sm": "http://www.sitemaps.org/schemas/sitemap/0.9"}
    urls = [loc.text.strip() for loc in root.findall(".//sm:loc", ns)]
    log.info(f"Found {len(urls)} URLs in sitemap")
    return urls


def get_angel_data(slug):
    try:
        result = supabase.table("angels").select(
            "name, slug, personality, bio, snippet, system_prompt"
        ).eq("slug", slug).single().execute()
        return result.data
    except Exception:
        return None


def classify_url(url):
    path = url.replace(BASE_URL, "")
    if path.startswith("/profile/"):
        return "profile", path.replace("/profile/", "")
    elif path.startswith("/chat/"):
        return "chat", path.replace("/chat/", "")
    elif path.startswith("/features/"):
        return "feature", path.replace("/features/", "")
    elif path.startswith("/compare/"):
        return "compare", path.replace("/compare/", "")
    elif path.startswith("/companions/"):
        return "category", path.replace("/companions/", "")
    else:
        return "landing", path.strip("/")


# ---------------------------------------------------------------------------
# Blogger cross-link helpers
# ---------------------------------------------------------------------------

def get_random_blogger_posts(service, count=2):
    """Return up to `count` random live Blogger posts as (title, url) tuples."""
    try:
        result = service.posts().list(
            blogId=BLOGGER_BLOG_ID,
            maxResults=20,
            status="LIVE"          # must be uppercase
        ).execute()
        posts = result.get("items", [])
        if len(posts) > count:
            posts = random.sample(posts, count)
        return [(p.get("title", ""), p.get("url", "")) for p in posts]
    except Exception as e:
        log.warning(f"Could not fetch Blogger posts for cross-links: {e}")
        return []


# ---------------------------------------------------------------------------
# Image helper — picsum.photos (real photography, always reliable, unique per URL)
# ---------------------------------------------------------------------------

def get_article_image(url):
    """
    Return a direct image URL seeded on the article URL so every article
    gets a unique, stable image. Uses picsum.photos which serves real
    high-quality photography with guaranteed uptime.
    """
    seed = hashlib.md5(url.encode()).hexdigest()[:16]
    return f"https://picsum.photos/seed/{seed}/800/400"


# ---------------------------------------------------------------------------
# Labels helper — maximize up to 200 total chars
# ---------------------------------------------------------------------------

BASE_EXTRA_LABELS = [
    "AI Girlfriend", "AI Companion", "NSFW AI Chat", "Uncensored AI",
    "AI Romance", "Virtual Girlfriend", "AI Chatbot", "AI Angels",
    "aiangels.io", "AI Chat 2026", "AI Roleplay", "Digital Companion",
    "Adult AI", "AI Relationship", "AI Waifu",
]

def build_labels(primary_labels, max_chars=200):
    """
    Combine primary (article-specific) labels with generic extras and
    return as many as fit within max_chars total (summed label lengths).
    Blogger counts each label's characters individually; we stay safe by
    tracking cumulative length.
    """
    seen = set()
    result = []
    total = 0
    for label in primary_labels + BASE_EXTRA_LABELS:
        label = label.strip()
        if not label or label in seen:
            continue
        if total + len(label) > max_chars:
            break
        seen.add(label)
        result.append(label)
        total += len(label)
    log.info(f"Labels ({total} chars, {len(result)} tags): {result}")
    return result


# ---------------------------------------------------------------------------
# Article generation
# ---------------------------------------------------------------------------

def generate_article(url, page_type, slug, angel_data=None, blogger_posts=[]):
    # Build internal Blogger cross-links section (max 2)
    blogger_links_html = ""
    if blogger_posts:
        blogger_links_html = "\n<h2>More From AI Angels Blog</h2>\n<ul>\n"
        for title, burl in blogger_posts[:2]:
            if title and burl:
                blogger_links_html += f'<li><a href="{burl}" title="{title}">{title}</a></li>\n'
        blogger_links_html += "</ul>\n"

    if page_type in ["profile", "chat"] and angel_data:
        name = angel_data.get("name", slug.title())
        bio = angel_data.get("bio", "")
        personality = angel_data.get("personality", "")
        snippet = angel_data.get("snippet", "")
        chat_url = f"{BASE_URL}/chat/{slug}"
        profile_url = f"{BASE_URL}/profile/{slug}"
        primary_labels = [f"AI Girlfriend, AI Companion, NSFW AI Chat, {name}, aiangels.io"]

        prompt = (
            f"Write a passionate exciting blog post (1000-1300 words) about an AI companion named {name} on aiangels.io.\n\n"
            f"Companion details:\n"
            f"- Name: {name}\n"
            f"- Bio: {bio}\n"
            f"- Personality: {personality}\n"
            f"- Snippet: {snippet}\n\n"
            f"Requirements:\n"
            f"- SEO title including '{name} AI Girlfriend'\n"
            f"- Meta description EXACTLY 150-155 characters on the META: line\n"
            f"- Introduction hook (2-3 paragraphs)\n"
            f"- 5 H2 sections: Who Is {name}?, Her Personality and Vibe, What Chatting With {name} Feels Like, NSFW and Roleplay Possibilities, Why Users Love {name}\n"
            f"- MUST include clickable <a href> links in the HTML body to:\n"
            f"    1. {chat_url} (anchor text: 'chat with {name}' or 'start chatting')\n"
            f"    2. {profile_url} (anchor text: 'view {name}\\'s full profile')\n"
            f"    3. {BASE_URL} (anchor text: 'explore AI Angels')\n"
            f"- Conclude with a strong CTA paragraph linking to {chat_url}\n"
            f"- Tone: passionate, slightly seductive, enthusiast blogger\n"
            f"- Keywords: {name} AI girlfriend, AI companion, NSFW AI chat, uncensored AI girlfriend\n\n"
            f"Output format (follow EXACTLY, no deviations, no markdown):\n"
            f"TITLE: [title]\n"
            f"META: [meta description, exactly 150-155 chars]\n"
            f"LABELS: AI Girlfriend, AI Companion, NSFW AI Chat, {name}, aiangels.io\n"
            f"CONTENT:\n"
            f"[full HTML with <h2>, <p>, <a href> tags only — no markdown]\n"
            f"{blogger_links_html}"
        )

    elif page_type == "feature":
        feature_name = slug.replace("-", " ").title()
        feature_url = f"{BASE_URL}/features/{slug}"
        primary_labels = [f"AI Girlfriend, {feature_name}, AI Features, aiangels.io"]

        prompt = (
            f"Write a professional exciting blog post (1000-1300 words) about the feature '{feature_name}' on aiangels.io.\n\n"
            f"Requirements:\n"
            f"- SEO title including the feature name\n"
            f"- Meta description EXACTLY 150-155 characters on the META: line\n"
            f"- 5 H2 sections: What Is {feature_name}?, How It Works, Why It Matters, How We Compare to Competitors, How to Get Started\n"
            f"- MUST include clickable <a href> links in the HTML body to:\n"
            f"    1. {feature_url} (anchor text: 'learn more about {feature_name}')\n"
            f"    2. {BASE_URL} (anchor text: 'explore AI Angels')\n"
            f"- Strong CTA to sign up at {BASE_URL}\n"
            f"- Keywords: {feature_name}, AI girlfriend, uncensored AI chat\n\n"
            f"Output format (follow EXACTLY, no markdown):\n"
            f"TITLE: [title]\n"
            f"META: [meta description, exactly 150-155 chars]\n"
            f"LABELS: AI Girlfriend, {feature_name}, AI Features, aiangels.io\n"
            f"CONTENT:\n"
            f"[full HTML with <h2>, <p>, <a href> tags only]\n"
            f"{blogger_links_html}"
        )

    elif page_type == "compare":
        competitor = slug.replace("-alternative", "").replace("-", " ").title()
        compare_url = f"{BASE_URL}/compare/{slug}"
        primary_labels = [f"AI Girlfriend, {competitor} Alternative, AI Comparison, aiangels.io"]

        prompt = (
            f"Write a blog post (1000-1300 words) titled 'Best {competitor} Alternative in 2026: Meet AI Angels'.\n\n"
            f"Requirements:\n"
            f"- SEO title like 'Best {competitor} Alternative in 2026'\n"
            f"- Meta description EXACTLY 150-155 characters on the META: line\n"
            f"- 5 H2 sections: What is {competitor}?, Why Users Look for Alternatives, What Makes AI Angels Better, Feature Comparison, How to Get Started\n"
            f"- MUST include clickable <a href> links in the HTML body to:\n"
            f"    1. {compare_url} (anchor text: 'see the full comparison')\n"
            f"    2. {BASE_URL} (anchor text: 'try AI Angels free')\n"
            f"- Strong CTA to try {BASE_URL}\n"
            f"- Keywords: {competitor} alternative, AI girlfriend, uncensored AI\n\n"
            f"Output format (follow EXACTLY, no markdown):\n"
            f"TITLE: [title]\n"
            f"META: [meta description, exactly 150-155 chars]\n"
            f"LABELS: AI Girlfriend, {competitor} Alternative, AI Comparison, aiangels.io\n"
            f"CONTENT:\n"
            f"[full HTML with <h2>, <p>, <a href> tags only]\n"
            f"{blogger_links_html}"
        )

    else:
        page_name = slug.replace("-", " ").title() if slug else "AI Angels"
        page_url = f"{BASE_URL}/{slug}" if slug else BASE_URL
        primary_labels = [f"AI Girlfriend, {page_name}, AI Companion, aiangels.io"]

        prompt = (
            f"Write an exciting blog post (1000-1300 words) about '{page_name}' on aiangels.io.\n\n"
            f"Requirements:\n"
            f"- SEO-optimized title\n"
            f"- Meta description EXACTLY 150-155 characters on the META: line\n"
            f"- 5 H2 sections about this topic\n"
            f"- MUST include clickable <a href> links in the HTML body to:\n"
            f"    1. {page_url} (anchor text relevant to the topic)\n"
            f"    2. {BASE_URL} (anchor text: 'explore AI Angels')\n"
            f"- Strong CTA to visit {BASE_URL}\n"
            f"- Keywords: {page_name}, AI girlfriend, uncensored AI chat, AI companion\n\n"
            f"Output format (follow EXACTLY, no markdown):\n"
            f"TITLE: [title]\n"
            f"META: [meta description, exactly 150-155 chars]\n"
            f"LABELS: AI Girlfriend, {page_name}, AI Companion, aiangels.io\n"
            f"CONTENT:\n"
            f"[full HTML with <h2>, <p>, <a href> tags only]\n"
            f"{blogger_links_html}"
        )

    log.info(f"Generating article for {url}...")
    message = claude.messages.create(
        model="claude-opus-4-5",
        max_tokens=4000,
        messages=[{"role": "user", "content": prompt}]
    )

    response = message.content[0].text

    # Parse response
    title = ""
    meta = ""
    raw_labels = []
    content_lines = []
    content_start = False

    for line in response.split("\n"):
        if line.startswith("TITLE:"):
            title = line.replace("TITLE:", "").strip()
        elif line.startswith("META:"):
            meta = line.replace("META:", "").strip()
        elif line.startswith("LABELS:"):
            raw_labels = [l.strip() for l in line.replace("LABELS:", "").strip().split(",")]
        elif line.startswith("CONTENT:"):
            content_start = True
        elif content_start:
            content_lines.append(line)

    content = "\n".join(content_lines).strip()

    # Unique image per article (deterministic seed from URL)
    img_url = get_article_image(url)
    img_alt = title if title else f"{slug.title()} AI Girlfriend"
    img_html = (
        f'<div style="text-align:center;margin:20px 0;">\n'
        f'<img src="{img_url}" alt="{img_alt}" title="{img_alt}" '
        f'style="max-width:100%;border-radius:8px;" />\n'
        f'</div>\n'
    )
    content = img_html + content

    if not title:
        title = f"{slug.title()} AI Girlfriend on AI Angels"

    # Build maximized label list (up to 200 total chars)
    labels = build_labels(raw_labels)

    return title, meta, labels, content


# ---------------------------------------------------------------------------
# Publishing
# ---------------------------------------------------------------------------

def publish_to_blogger(service, title, content, labels, meta=""):
    post_body = {
        "title": title,
        "content": content,
        "labels": labels,
    }
    # Set Blogger Search Description via customMetaTags
    if meta:
        safe_meta = html.escape(meta, quote=True)
        post_body["customMetaTags"] = f'<meta name="description" content="{safe_meta}"/>'

    result = service.posts().insert(
        blogId=BLOGGER_BLOG_ID,
        body=post_body,
        isDraft=False
    ).execute()
    post_id = result["id"]
    post_url = result.get("url", "")

    # Verify description was stored; if not, patch it in
    saved = result.get("customMetaTags", "")
    if meta and not saved:
        try:
            safe_meta = html.escape(meta, quote=True)
            service.posts().patch(
                blogId=BLOGGER_BLOG_ID,
                postId=post_id,
                body={"customMetaTags": f'<meta name="description" content="{safe_meta}"/>'}
            ).execute()
            log.info("Search description patched via update.")
        except Exception as e:
            log.warning(f"Could not patch search description: {e}")

    return post_id, post_url


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def run(batch_size=1, bulk_mode=False):
    log.info("=== AI Angels Blog Automation Starting ===")

    service = get_blogger_service()
    log.info("Blogger authenticated")

    all_urls = fetch_sitemap_urls()
    processed_set = get_processed_url_set()
    log.info(f"Already processed: {len(processed_set)} URLs")

    pending = [u for u in all_urls if u not in processed_set]
    log.info(f"Pending: {len(pending)} URLs")

    if not pending:
        log.info("All URLs processed!")
        return

    to_process = pending if bulk_mode else pending[:batch_size]
    log.info(f"Processing {len(to_process)} URL(s) this run...")

    success = 0
    for url in to_process:
        try:
            page_type, slug = classify_url(url)
            log.info(f"Processing [{page_type}]: {url}")

            angel_data = None
            if page_type in ["profile", "chat"]:
                angel_data = get_angel_data(slug)

            blogger_posts = get_random_blogger_posts(service)

            title, meta, labels, content = generate_article(
                url, page_type, slug, angel_data, blogger_posts
            )

            if not content:
                log.warning(f"Empty content for {url}, skipping")
                continue

            log.info(f"Meta ({len(meta)} chars): {meta[:80]}...")
            post_id, post_url = publish_to_blogger(service, title, content, labels, meta)
            log.info(f"Published: '{title}'")
            log.info(f"URL: {post_url}")

            mark_url_processed(url, title, post_id)
            success += 1

            time.sleep(5)

        except Exception as e:
            log.error(f"Error processing {url}: {e}")
            import traceback; traceback.print_exc()
            time.sleep(5)
            continue

    log.info(f"=== Done! Published {success}/{len(to_process)} article(s) ===")


if __name__ == "__main__":
    import sys
    bulk = "--bulk" in sys.argv
    run(batch_size=1, bulk_mode=bulk)
