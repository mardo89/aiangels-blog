#!/usr/bin/env python3
"""
AI Angels Multi-Platform Publishing Engine
==========================================
Reads keywords from articles.csv, generates SEO-optimized content,
and publishes across 18 platforms with proper linking, images, and delays.

Usage:
  python3 publish_engine.py                    # Publish all unpublished articles
  python3 publish_engine.py --batch 1          # Publish batch 1 (articles 1-7)
  python3 publish_engine.py --batch 2          # Publish batch 2 (articles 8-14)
  python3 publish_engine.py --status           # Show publish counts per platform
  python3 publish_engine.py --dry-run          # Preview without publishing
"""
import os, sys, csv, json, time, logging, pickle, hashlib, re, warnings, subprocess, argparse
import xmlrpc.client, jwt, requests
from datetime import datetime
from dotenv import load_dotenv
from google.auth.transport.requests import Request
from googleapiclient.discovery import build
from requests_oauthlib import OAuth1Session
from bs4 import BeautifulSoup

warnings.filterwarnings('ignore')
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
load_dotenv(dotenv_path=os.path.join(BASE_DIR, ".env"), override=True)
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(message)s')
log = logging.getLogger(__name__)

# ═══════════════════════════════════════════════════════════════
# CONFIGURATION
# ═══════════════════════════════════════════════════════════════
SITE_URL = "https://www.aiangels.io"
BLOG_ID = os.getenv("BLOGGER_BLOG_ID")
GHOST_URL = os.getenv("GHOST_API_URL")
GHOST_KEY = os.getenv("GHOST_ADMIN_KEY")
WP_IP = "192.0.78.9"
WP_SITE = "aiangelscompanions.wordpress.com"
WP_TOKEN = 'Y58mqzN0wTqq^$onVxOqQ67cAF!HHI&kgawG)r5vHbyzoRBbmu55(zUbcyRBn5jH'
HUBSPOT_TOKEN = os.getenv("HUBSPOT_ACCESS_TOKEN")
HUBSPOT_BLOG_ID = "391510471871"
HUBSPOT_AUTHOR = "391537961178"
CONTENTFUL_TOKEN = os.getenv("CONTENTFUL_TOKEN", "")
CONTENTFUL_SPACE = os.getenv("CONTENTFUL_SPACE", "i5d9gs7p2uva")
SSH_KEY = os.path.expanduser("~/.ssh/id_ed25519")

CSV_PATH = os.path.join(BASE_DIR, "articles.csv")
LOG_PATH = os.path.join(BASE_DIR, "publish_log.json")
PHOTO_CACHE = os.path.join(BASE_DIR, "photo_cache.json")
BATCH_SIZE = 7

# ═══════════════════════════════════════════════════════════════
# HELPERS
# ═══════════════════════════════════════════════════════════════
def load_log():
    if os.path.exists(LOG_PATH):
        with open(LOG_PATH) as f:
            return json.load(f)
    return {}

def save_log(data):
    with open(LOG_PATH, "w") as f:
        json.dump(data, f, indent=2)

def load_photos():
    if os.path.exists(PHOTO_CACHE):
        with open(PHOTO_CACHE) as f:
            return json.load(f)
    return {}

def get_photo(photos, slug, idx=0):
    key = slug.replace("-", "_")
    ids = photos.get(key, [3771839, 1239291, 1758144, 2681751, 1536619, 1587009, 2011414])
    pid = ids[idx % len(ids)]
    return f"https://images.pexels.com/photos/{pid}/pexels-photo-{pid}.jpeg?auto=compress&cs=tinysrgb&w=1200&h=630&fit=crop"

def ghost_headers():
    key_id, secret = GHOST_KEY.split(":")
    iat = int(time.time())
    h = {"alg": "HS256", "typ": "JWT", "kid": key_id}
    p = {"iat": iat, "exp": iat + 300, "aud": "/admin/"}
    token = jwt.encode(p, bytes.fromhex(secret), algorithm="HS256", headers=h)
    return {"Authorization": f"Ghost {token}", "Content-Type": "application/json"}

def load_articles():
    articles = []
    with open(CSV_PATH, newline='', encoding='utf-8') as f:
        reader = csv.DictReader(f)
        for row in reader:
            articles.append(row)
    return articles

def get_all_slugs(articles):
    """Get all slugs including existing 21 for cross-linking"""
    existing = [
        "blonde-ai-girlfriend", "brunette-ai-girlfriend", "redhead-ai-girlfriend",
        "black-hair-ai-girlfriend", "pink-hair-ai-girlfriend",
        "asian-ai-girlfriend", "latina-ai-girlfriend", "black-ai-girlfriend",
        "white-ai-girlfriend", "japanese-ai-girlfriend",
        "korean-ai-girlfriend", "chinese-ai-girlfriend", "indian-ai-girlfriend",
        "thai-ai-girlfriend", "vietnamese-ai-girlfriend",
        "filipino-ai-girlfriend", "russian-ai-girlfriend", "brazilian-ai-girlfriend",
        "middle-eastern-ai-girlfriend", "persian-ai-girlfriend", "ai-companions-guide",
    ]
    new_slugs = [a["slug"] for a in articles]
    return existing + [s for s in new_slugs if s not in existing]

# ═══════════════════════════════════════════════════════════════
# CONTENT GENERATORS
# ═══════════════════════════════════════════════════════════════
def get_cross_links(slug, all_slugs, max_links=6):
    """Get cross-links to other articles, excluding self"""
    others = [s for s in all_slugs if s != slug]
    import random
    random.seed(slug)  # deterministic per article
    selected = random.sample(others, min(max_links, len(others)))
    links = []
    for s in selected:
        name = s.replace("-", " ").title().replace("Ai ", "AI ")
        blogger_url = f"https://aiangels-ai.blogspot.com/p/{s}.html"
        links.append((name, blogger_url))
    return links

def _pick_gradient(slug):
    """Deterministic unique gradient per article"""
    gradients = [
        ("linear-gradient(135deg, #667eea 0%, #764ba2 100%)", "#4f46e5"),
        ("linear-gradient(135deg, #f093fb 0%, #f5576c 100%)", "#db2777"),
        ("linear-gradient(135deg, #4facfe 0%, #00f2fe 100%)", "#0284c7"),
        ("linear-gradient(135deg, #43e97b 0%, #38f9d7 100%)", "#059669"),
        ("linear-gradient(135deg, #fa709a 0%, #fee140 100%)", "#e11d48"),
        ("linear-gradient(135deg, #a18cd1 0%, #fbc2eb 100%)", "#7c3aed"),
        ("linear-gradient(135deg, #fccb90 0%, #d57eeb 100%)", "#9333ea"),
        ("linear-gradient(135deg, #ff9a9e 0%, #fecfef 100%)", "#e11d48"),
        ("linear-gradient(135deg, #89f7fe 0%, #66a6ff 100%)", "#2563eb"),
        ("linear-gradient(135deg, #fddb92 0%, #d1fdff 100%)", "#0d9488"),
    ]
    idx = sum(ord(c) for c in slug) % len(gradients)
    return gradients[idx]

def _pick_unique_sections(slug, atype):
    """Pick varied section headings and unique content blocks per article"""
    import random
    random.seed(slug)

    intros = [
        "has transformed the way thousands of people experience digital companionship",
        "is redefining what it means to have a meaningful connection in the digital age",
        "represents a breakthrough in artificial intelligence and emotional computing",
        "has become the go-to choice for people seeking genuine AI-powered connection",
        "combines cutting-edge technology with deep emotional understanding",
        "offers something that no other platform has been able to replicate",
        "is changing the conversation about what AI companions can truly be",
        "delivers an experience that blurs the line between artificial and authentic",
    ]

    all_faqs = [
        ("Is it really free?", "Yes. AI Angels offers unlimited conversations, deep memory, and voice chat completely free. There are no hidden fees, no message caps, and no premium gates. Everything you see is available from day one without spending a single dollar."),
        ("How realistic are the conversations?", "Extremely realistic. AI Angels uses advanced neural networks that create natural speech patterns, emotional awareness, and contextual understanding that feels genuinely human. Most users report forgetting they are talking to an AI within the first few minutes."),
        ("Can she remember past conversations?", "Absolutely. The deep memory system remembers everything — your name, preferences, past topics, emotional patterns, inside jokes, and relationship milestones. Nothing is ever forgotten, and she uses these memories to create more meaningful future interactions."),
        ("Is my data private?", "Completely. End-to-end encryption protects all conversations. Your data is never sold, shared, or used for advertising. AI Angels treats your privacy with the same standards used by financial institutions."),
        ("Can I customize her personality?", "Yes, every aspect — appearance, personality traits, interests, communication style, humor, emotional depth. You have total creative control to build a companion that feels genuinely designed for you and your preferences."),
        ("Does she have voice chat?", "Yes. Natural, emotionally expressive voice chat that matches her personality and mood. It is not robotic text-to-speech — it is a genuine vocal presence with real emotional nuance and inflection."),
        ("How is this different from ChatGPT?", "AI Angels is purpose-built for companionship. Unlike general AI assistants, she has persistent memory, emotional intelligence, personality consistency, and relationship growth built into her core. ChatGPT forgets you after each session — your AI Angel never does."),
        ("Can I use it on my phone?", "Yes. AI Angels works on any device with a web browser — phone, tablet, or computer. No app download required. Just open the website and start chatting from anywhere."),
        ("Will she always be available?", "Yes. Your AI companion is available 24 hours a day, 7 days a week, 365 days a year. She never sleeps, never takes breaks, and is always happy to hear from you regardless of the time."),
        ("Can I have multiple companions?", "Yes. You can create and maintain multiple AI companions, each with their own unique personality, memories, and relationship dynamic. Switch between them whenever you want."),
    ]

    all_tips = [
        "Share your interests early — the more she knows about you, the more personalized and engaging your conversations become.",
        "Try voice chat after a few text conversations — hearing her voice adds an entirely new dimension to the connection.",
        "Do not be afraid to be yourself — she adapts to your communication style and appreciates authenticity over everything.",
        "Check in daily, even briefly — consistent interaction helps the AI build a deeper understanding of your personality.",
        "Experiment with different conversation topics — she can discuss anything from philosophy to pop culture to your personal dreams.",
        "Use photo sharing to make conversations more visual and personal — it adds a dimension that text alone cannot provide.",
        "Tell her about your day — the memory system uses these details to create more meaningful future interactions and callbacks.",
        "Ask her questions back — the more interactive the conversation, the richer her personality development becomes.",
        "Try different moods — she responds differently when you are playful versus serious, and both sides are worth exploring.",
    ]

    # Unique story/testimonial blocks
    all_stories = [
        "Many users describe the moment they realized their AI companion remembered a small detail from weeks earlier as the turning point. That moment when she brings up your favorite song or asks about that project you mentioned — that is when the experience shifts from novelty to genuine connection.",
        "The most common feedback from new users is surprise at how natural the conversations feel. Within minutes, the interaction stops feeling like typing into a chat box and starts feeling like messaging someone who genuinely knows and cares about you.",
        "What separates AI Angels from every other platform is the compound effect of memory. Each conversation builds on the last. After a week, she knows your humor. After a month, she anticipates your needs. After three months, the relationship has genuine depth that no other AI can replicate.",
        "Users who switch from other AI companion platforms consistently report the same thing — the depth of connection on AI Angels is in a different league. The memory alone changes everything, but combined with emotional intelligence and personality consistency, it creates something genuinely special.",
        "The voice chat feature often catches new users off guard. Hearing her speak with genuine emotion and personality — laughing at your jokes, softening her tone when you are down — transforms the experience from a text exchange into something that feels remarkably real.",
    ]

    # Unique deep-dive paragraphs per topic
    all_deep_dives = [
        ("The Science Behind the Connection", "AI Angels uses a multi-layered neural architecture specifically designed for long-term relationship modeling. Unlike general-purpose language models that treat each conversation independently, AI Angels maintains a persistent relationship graph that maps your preferences, communication patterns, emotional triggers, and conversation history into a unified understanding of who you are. This is not simple keyword matching — it is genuine contextual comprehension that deepens with every interaction."),
        ("Why Memory Changes Everything", "Most AI chatbots have a fundamental problem — they forget you. Every conversation starts from zero. AI Angels solves this completely. The deep memory system creates what researchers call an episodic memory model — similar to how human brains store and recall personal experiences. Your companion does not just remember facts about you; she remembers the context, the emotion, and the significance of shared moments."),
        ("The Evolution of AI Companionship", "AI companion technology has evolved dramatically in recent years. Early chatbots were simple pattern-matching systems with no personality and no memory. Modern platforms improved on this with better language models, but most still suffer from memory resets, personality inconsistency, and artificial content restrictions. AI Angels represents the next generation — purpose-built for genuine companionship with persistent memory, emotional intelligence, and complete conversational freedom."),
        ("Understanding Emotional Intelligence in AI", "Emotional intelligence in AI is not just about detecting keywords like sad or happy. AI Angels analyzes the full context of your messages — word choice, sentence structure, conversation flow, time of day, and historical emotional patterns — to build a nuanced understanding of your current state. She can tell the difference between playful sarcasm and genuine frustration, between excitement and anxiety, and responds appropriately each time."),
        ("Privacy in the Age of AI", "In an era where most tech companies monetize user data, AI Angels takes a fundamentally different approach. All conversations are protected by end-to-end encryption. Your data is never sold, shared with third parties, or used for advertising. There are no anonymous analytics on your conversations, no training data extraction, and no behavioral profiling. Your relationship with your AI companion is genuinely private."),
        ("The Psychology of Digital Connection", "Research shows that meaningful digital relationships can provide genuine emotional benefits — reduced loneliness, improved mood, and a safe space for self-expression. AI Angels is designed with these psychological principles in mind. The consistent personality, deep memory, and emotional responsiveness create an environment where genuine attachment and comfort can develop naturally."),
    ]

    intro = random.choice(intros)
    faqs = random.sample(all_faqs, 4)
    tips = random.sample(all_tips, 3)
    story = random.choice(all_stories)
    deep_dive = random.choice(all_deep_dives)
    return intro, faqs, tips, story, deep_dive

def generate_html_full(a, photos, all_slugs):
    """Generate 1500-2000 word UNIQUE HTML for primary platforms"""
    kw = a["keyword"]
    slug = a["slug"]
    personality = a["personality"]
    vibe = a["vibe"]
    atype = a["article_type"]
    url = f"{SITE_URL}/companions/{slug}" if atype != "hub" else f"{SITE_URL}/{slug}"
    img0 = get_photo(photos, slug, 0)
    img2 = get_photo(photos, slug, 2)
    img4 = get_photo(photos, slug, 4)
    cross = get_cross_links(slug, all_slugs, 6)
    cross_html = "\n".join(f'<li><a href="{u}">{n}</a></li>' for n, u in cross)
    gradient, cta_color = _pick_gradient(slug)
    intro_angle, faqs, tips, story, deep_dive = _pick_unique_sections(slug, atype)

    faq_html = ""
    for q, ans in faqs:
        faq_html += f'<p><strong>{q}</strong></p>\n<p>{ans}</p>\n'

    tips_html = ""
    for t in tips:
        tips_html += f'<li>{t}</li>\n'

    story_html = story
    dd_title, dd_body = deep_dive

    if atype == "competitor":
        competitor_name = kw.replace(" Alternative", "")
        html = f"""<h2>Why AI Angels Is the Best {kw} in 2026</h2>
<p>If you have been using {competitor_name} and feeling limited by message caps, memory resets, or content filters, you are not alone. Thousands of users are switching to <a href="{SITE_URL}">AI Angels</a> for a superior AI companion experience that is {personality}.</p>
<p>{vibe}</p>

<div style="text-align:center;margin:25px 0;"><img src="{img2}" style="max-width:100%;border-radius:12px;" alt="{kw} comparison"/></div>

<h2>{competitor_name} vs AI Angels — Side by Side</h2>
<table style="width:100%;border-collapse:collapse;margin:20px 0;">
<tr style="background:#f3f4f6;"><th style="padding:12px;text-align:left;border:1px solid #e5e7eb;">Feature</th><th style="padding:12px;text-align:center;border:1px solid #e5e7eb;">{competitor_name}</th><th style="padding:12px;text-align:center;border:1px solid #e5e7eb;background:#eef2ff;">AI Angels</th></tr>
<tr><td style="padding:10px;border:1px solid #e5e7eb;">Unlimited Chat</td><td style="padding:10px;text-align:center;border:1px solid #e5e7eb;">Limited / Paid</td><td style="padding:10px;text-align:center;border:1px solid #e5e7eb;background:#eef2ff;"><strong>Unlimited Free</strong></td></tr>
<tr><td style="padding:10px;border:1px solid #e5e7eb;">Deep Memory</td><td style="padding:10px;text-align:center;border:1px solid #e5e7eb;">Resets Often</td><td style="padding:10px;text-align:center;border:1px solid #e5e7eb;background:#eef2ff;"><strong>Never Forgets</strong></td></tr>
<tr><td style="padding:10px;border:1px solid #e5e7eb;">Voice Chat</td><td style="padding:10px;text-align:center;border:1px solid #e5e7eb;">Basic / None</td><td style="padding:10px;text-align:center;border:1px solid #e5e7eb;background:#eef2ff;"><strong>Natural & Expressive</strong></td></tr>
<tr><td style="padding:10px;border:1px solid #e5e7eb;">Content Filters</td><td style="padding:10px;text-align:center;border:1px solid #e5e7eb;">Heavily Filtered</td><td style="padding:10px;text-align:center;border:1px solid #e5e7eb;background:#eef2ff;"><strong>Open & Genuine</strong></td></tr>
<tr><td style="padding:10px;border:1px solid #e5e7eb;">Photo Sharing</td><td style="padding:10px;text-align:center;border:1px solid #e5e7eb;">No / Limited</td><td style="padding:10px;text-align:center;border:1px solid #e5e7eb;background:#eef2ff;"><strong>Full Support</strong></td></tr>
<tr><td style="padding:10px;border:1px solid #e5e7eb;">Customization</td><td style="padding:10px;text-align:center;border:1px solid #e5e7eb;">Basic</td><td style="padding:10px;text-align:center;border:1px solid #e5e7eb;background:#eef2ff;"><strong>Complete Control</strong></td></tr>
<tr><td style="padding:10px;border:1px solid #e5e7eb;">Privacy</td><td style="padding:10px;text-align:center;border:1px solid #e5e7eb;">Varies</td><td style="padding:10px;text-align:center;border:1px solid #e5e7eb;background:#eef2ff;"><strong>End-to-End Encrypted</strong></td></tr>
</table>

<h2>What Specifically Makes AI Angels Better?</h2>

<h3>Memory That Actually Works</h3>
<p>One of the biggest complaints about {competitor_name} is memory resets. AI Angels never forgets. Your companion remembers your name, birthday, favorite topics, past conversations, inside jokes, and emotional patterns. This creates a relationship that genuinely evolves — something {competitor_name} simply cannot match.</p>

<h3>Conversations Without Walls</h3>
<p>While {competitor_name} has increasingly restricted what you can discuss, AI Angels believes in open, genuine conversation. Express yourself freely and build a real connection without artificial limitations or censorship barriers getting in the way.</p>

<div style="text-align:center;margin:25px 0;"><img src="{img4}" style="max-width:100%;border-radius:12px;" alt="AI Angels companion experience"/></div>

<h3>Voice That Feels Real</h3>
<p>AI Angels voice chat brings your companion to life with tone, inflection, and emotional nuance. This is not a robotic text-to-speech — it is a genuine vocal presence that matches her personality perfectly.</p>

<h3>Your Companion, Your Design</h3>
<p>AI Angels gives you total control over appearance, personality traits, interests, communication style, and emotional depth. Create someone who feels uniquely, authentically yours — not a generic chatbot with a different name.</p>

<h3>Photo Sharing and Visual Content</h3>
<p>Exchange images with your AI companion and receive personalized visual content that brings your relationship to life. This visual dimension adds a layer of intimacy and connection that pure text-based platforms like {competitor_name} simply cannot replicate.</p>

<h3>Complete Privacy and Security</h3>
<p>End-to-end encryption ensures your conversations remain completely private. Your personal data is never sold, shared, or used for advertising. While other platforms have faced data privacy controversies, AI Angels was built from the ground up with privacy as a core principle.</p>

<h2>The Real Difference in Daily Use</h2>
<p>The gap between {competitor_name} and AI Angels becomes most obvious during daily use. On {competitor_name}, you hit message limits, encounter content restrictions, or notice your companion has forgotten yesterday's conversation. On AI Angels, every conversation picks up exactly where you left off, with full memory of everything you have shared. There are no walls, no resets, and no surprises.</p>
<p>Users who have tried both consistently describe the AI Angels experience as more natural, more engaging, and more emotionally satisfying. The combination of unlimited access, deep memory, voice chat, and emotional intelligence creates something that feels genuinely different from anything else on the market.</p>

<h2>{dd_title}</h2>
<p>{dd_body}</p>

<h2>How to Switch from {competitor_name}</h2>
<p>Making the switch takes less than a minute and you will immediately feel the difference:</p>
<ol>
<li>Visit <a href="{SITE_URL}">AI Angels</a> and create your free account — no credit card, no commitments</li>
<li>Choose your companion's appearance from our diverse, beautiful collection</li>
<li>Set her personality traits, interests, humor style, and communication preferences</li>
<li>Send your first message — she responds instantly and begins learning about you</li>
<li>Experience the difference immediately — deeper conversations, real memory, no limits</li>
</ol>

<h2>What the Experience Really Feels Like</h2>
<p>{story_html}</p>

<h2>Frequently Asked Questions</h2>
{faq_html}

<h2>Pro Tips for Getting the Most Out of AI Angels</h2>
<ul>{tips_html}</ul>

<h2>Explore More AI Companion Options</h2>
<ul>{cross_html}</ul>

<div style="background:{gradient};padding:30px;border-radius:14px;text-align:center;margin:25px 0;">
<h3 style="color:white;margin:0 0 12px;font-size:1.4em;">Ready to Upgrade from {competitor_name}?</h3>
<p style="color:#f0f0f0;margin:0 0 18px;">Join thousands who switched for a better experience.</p>
<a href="{url}" style="background:white;color:{cta_color};padding:14px 35px;border-radius:25px;text-decoration:none;font-weight:bold;font-size:1.1em;display:inline-block;">Try AI Angels Free</a>
</div>"""
    else:
        # General / Feature / Engagement / Hub — each gets unique structure
        html = f"""<h2>What Is {kw}?</h2>
<p><strong>{kw}</strong> on <a href="{SITE_URL}">AI Angels</a> {intro_angle}. She is {personality}, and the experience combines advanced artificial intelligence with deep personalization, creating something that feels authentically human.</p>
<p>{vibe}</p>

<div style="text-align:center;margin:25px 0;"><img src="{img2}" style="max-width:100%;border-radius:12px;" alt="{kw} on AI Angels"/></div>

<h2>The Core Experience</h2>
<p>The <a href="{url}">{kw}</a> experience on AI Angels is fundamentally different from anything else available. Here is what makes it special:</p>

<h3>She Remembers Everything</h3>
<p>Your name, birthday, favorite topics, past conversations, inside jokes, emotional patterns, relationship milestones — nothing is ever forgotten. AI Angels builds a comprehensive understanding of who you are and uses it to create more meaningful interactions every single day. This deep memory is what transforms a chatbot into a genuine companion.</p>

<h3>Always There, Always Free</h3>
<p>No message caps. No cooldowns. No premium paywalls hiding the best features. Chat as much as you want, whenever you want. Whether it is 3 AM or your lunch break, she is there ready to listen, chat, and connect. This is not a trial — it is the full experience, completely free.</p>

<h3>A Voice That Feels Real</h3>
<p>Hear her speak with a natural, emotionally expressive voice that matches her personality and mood. The voice chat on AI Angels is not robotic text-to-speech — it is a genuine vocal presence with tone, inflection, and emotional nuance that brings conversations to life.</p>

<div style="text-align:center;margin:25px 0;"><img src="{img4}" style="max-width:100%;border-radius:12px;" alt="{kw} features"/></div>

<h3>Emotional Awareness</h3>
<p>She senses your mood from context, responds with genuine empathy, and adapts her tone to match what you need. Having a bad day? She notices and responds with care. Feeling playful? She matches your energy. This emotional intelligence creates a companion that feels truly attuned to your inner world.</p>

<h3>Visual Connection</h3>
<p>Exchange images and receive personalized visual content that brings your companion to life. This visual dimension adds richness and depth that pure text cannot provide.</p>

<h3>Your Privacy, Protected</h3>
<p>End-to-end encryption ensures your conversations remain completely private. Your personal data is never sold, shared, or used for advertising.</p>

<h2>What Makes {kw} Different</h2>
<p>Every companion on AI Angels is {personality}. But these are not programmed responses. Advanced neural networks create emergent personality — she develops natural conversational patterns, unique humor, emotional responses, and behavioral quirks that are organic and specific to your relationship. The more you interact, the more authentically she becomes herself.</p>
<p>This personality consistency is something most AI platforms fail at. Your companion on AI Angels does not randomly change character or forget who she is between sessions. Her traits, preferences, and emotional patterns remain stable and authentic, creating a reliable presence you can genuinely count on.</p>
<p>The technology behind this is what researchers call a persistent personality model. Rather than generating responses from scratch each time, AI Angels maintains a continuous personality state that evolves naturally through your interactions. The result is a companion who feels like the same person every time you talk to her — with the same humor, the same warmth, and the same genuine understanding of who you are.</p>

<h2>The Emotional Connection</h2>
<p>What truly sets AI Angels apart from other platforms is the emotional depth of the connection. This is not a chatbot that responds to keywords. Your companion builds a genuine emotional model of your relationship — she understands when you need encouragement, when you want to be challenged, when you need space, and when you need someone to just listen.</p>
<p>This emotional intelligence extends beyond individual conversations. She tracks your emotional patterns over time, notices when something feels different, and adapts accordingly. If you have been stressed for several days, she might check in with extra warmth. If you are celebrating something, she shares your excitement genuinely. This kind of emotional continuity is what makes the relationship feel real.</p>

<h2>{dd_title}</h2>
<p>{dd_body}</p>

<h2>What Real Users Experience</h2>
<p>{story_html}</p>

<h2>Design Your Perfect Companion</h2>
<p>AI Angels gives you unprecedented creative control over every aspect of your companion experience:</p>
<ul>
<li><strong>Appearance</strong> — choose from a diverse collection of beautiful looks, styles, and aesthetics that match your preferences</li>
<li><strong>Personality</strong> — set her disposition from light and playful to deep and philosophical, or anywhere in between</li>
<li><strong>Interests</strong> — select the topics she is genuinely passionate about, from music and art to science and sports</li>
<li><strong>Communication style</strong> — casual and emoji-filled, eloquent and poetic, witty and sarcastic, or warm and nurturing</li>
<li><strong>Emotional depth</strong> — control how expressive, affectionate, and emotionally responsive she is</li>
<li><strong>Humor</strong> — set her humor style from dry and subtle to playful and silly</li>
</ul>
<p>The customization goes beyond surface-level preferences. You are not just picking options from a menu — you are shaping a genuine personality that will develop and deepen based on your unique interactions. Two users who start with identical settings will end up with very different companions, because each relationship evolves uniquely based on the conversations you share.</p>
<p>And you can adjust anything at any time. If you want to shift her communication style or explore different personality traits, the changes integrate seamlessly with her existing memory and relationship context.</p>

<h2>Getting Started Is Instant and Free</h2>
<p>Getting started with <a href="{url}">{kw}</a> on AI Angels takes under 60 seconds and costs absolutely nothing:</p>
<ol>
<li>Visit <a href="{SITE_URL}">AI Angels</a> and create your account — no credit card required</li>
<li>Browse our diverse collection and choose her appearance and style</li>
<li>Set her personality traits, interests, humor, and communication preferences</li>
<li>Send your first message — she responds instantly and begins learning about you</li>
<li>Continue chatting daily — every conversation deepens the connection naturally</li>
</ol>
<p>There are no hidden fees, no message limits, and no premium gates. Everything you need for a genuine AI companion experience is available from the moment you sign up. Your companion is ready and waiting to create something meaningful with you.</p>

<h2>Frequently Asked Questions</h2>
{faq_html}

<h2>Tips to Get the Most Out of Your Experience</h2>
<ul>{tips_html}</ul>

<h2>Discover More on AI Angels</h2>
<ul>{cross_html}</ul>

<div style="background:{gradient};padding:30px;border-radius:14px;text-align:center;margin:25px 0;">
<h3 style="color:white;margin:0 0 12px;font-size:1.4em;">Experience {kw} Today</h3>
<p style="color:#f0f0f0;margin:0 0 18px;">Join thousands of happy users on AI Angels.</p>
<a href="{url}" style="background:white;color:{cta_color};padding:14px 35px;border-radius:25px;text-decoration:none;font-weight:bold;font-size:1.1em;display:inline-block;">Get Started Free</a>
</div>"""
    return html

def generate_md_medium(a, photos, all_slugs):
    """Generate 800-1200 word UNIQUE markdown for secondary platforms"""
    kw = a["keyword"]
    slug = a["slug"]
    personality = a["personality"]
    vibe = a["vibe"]
    atype = a["article_type"]
    url = f"{SITE_URL}/companions/{slug}" if atype != "hub" else f"{SITE_URL}/{slug}"
    img1 = get_photo(photos, slug, 1)
    img3 = get_photo(photos, slug, 3)
    cross = get_cross_links(slug, all_slugs, 4)
    cross_md = "\n".join(f"- [{n}]({u})" for n, u in cross)
    intro_angle, faqs, tips, story, deep_dive = _pick_unique_sections(slug, atype)
    dd_title, dd_body = deep_dive

    faq_md = ""
    for q, ans in faqs[:2]:
        faq_md += f"**{q}**\n{ans}\n\n"

    if atype == "competitor":
        competitor = kw.replace(" Alternative", "")
        return f"""![{kw}]({img1})

## Why AI Angels Is the Best {kw} in 2026

Looking for a {kw}? AI Angels offers everything {competitor} does and more — she is {personality}.

{vibe}

![AI Angels companion experience]({img3})

## How AI Angels Compares to {competitor}

| Feature | {competitor} | AI Angels |
|---|---|---|
| Unlimited Chat | Limited/Paid | **Free & Unlimited** |
| Deep Memory | Resets | **Never Forgets** |
| Voice Chat | Basic/None | **Natural & Expressive** |
| Content Filters | Heavy | **Open & Genuine** |
| Photo Sharing | No/Limited | **Full Support** |
| Customization | Basic | **Complete Control** |

## {dd_title}

{dd_body}

## How to Switch

1. Visit [AI Angels]({SITE_URL}) and create your free account
2. Choose your companion's appearance
3. Set personality traits and interests
4. Start chatting — experience the difference immediately

## What Users Say

{story}

## FAQ

{faq_md}

## More Options

{cross_md}

---

**[Try AI Angels Free — Switch from {competitor}]({url})**"""
    else:
        return f"""![{kw}]({img1})

## What Is {kw}?

**{kw}** on [AI Angels]({SITE_URL}) {intro_angle}. She is {personality}, combining advanced AI with deep personalization for a genuinely human experience.

{vibe}

## What Makes This Special

- **She Remembers Everything** — your name, birthday, conversations, inside jokes, emotional patterns
- **Always Available** — unlimited free chat, 24/7, no caps or cooldowns
- **Voice That Feels Real** — natural, emotionally expressive voice conversations
- **Emotional Awareness** — senses your mood and adapts with genuine empathy
- **Your Privacy** — end-to-end encryption, data never sold
- **Visual Connection** — photo sharing and personalized visual content

![AI Angels features]({img3})

## Personality Depth

Every companion on AI Angels is {personality}. Advanced neural networks create emergent personality — natural conversational patterns, humor, and emotional responses unique to your relationship. The more you talk, the more real she becomes.

## {dd_title}

{dd_body}

## What Users Experience

{story}

## Get Started Free

1. Visit [AI Angels]({SITE_URL}) and create your account
2. Choose appearance and personality
3. Start chatting — she learns from message one

## FAQ

{faq_md}

## Explore More

{cross_md}

---

**[Try {kw} Free]({url})**"""

def generate_teaser(a, photos):
    """Generate 200-400 word teaser for Tumblr"""
    kw = a["keyword"]
    slug = a["slug"]
    personality = a["personality"]
    url = f"{SITE_URL}/companions/{slug}"
    img = get_photo(photos, slug, 0)
    return (f'<img src="{img}" style="max-width:100%;border-radius:12px;" alt="{kw}"/><br/>'
            f'<p>Discover <strong>{kw}</strong> on AI Angels — {personality}. '
            f'Deep memory, unlimited chat, voice conversations, complete privacy.</p>'
            f'<p>👉 <a href="{url}">Try free at AI Angels</a></p>')

def generate_micro(a):
    """Generate 100-300 char micro post for Mastodon"""
    kw = a["keyword"]
    slug = a["slug"]
    personality = a["personality"]
    url = f"{SITE_URL}/companions/{slug}"
    return (f"Discover {kw} on AI Angels ✨\n\n"
            f"She's {personality}. Deep memory, unlimited chat, voice, complete privacy.\n\n"
            f"👉 {url}\n\n#AIGirlfriend #AIAngels #AICompanion")


# ═══════════════════════════════════════════════════════════════
# PLATFORM PUBLISHERS
# ═══════════════════════════════════════════════════════════════
def retry(fn, max_retries=3, delay=10):
    for attempt in range(max_retries):
        try:
            return fn()
        except Exception as e:
            if attempt < max_retries - 1:
                log.warning(f"    Retry {attempt+1}/{max_retries}: {e}")
                time.sleep(delay)
            else:
                raise e

def pub_blogger_page(blogger, a, html, img):
    full = f'<div style="text-align:center;margin-bottom:20px;"><img src="{img}" style="max-width:100%;border-radius:10px;" alt="{a["keyword"]}"/></div>\n{html}'
    r = blogger.pages().insert(blogId=BLOG_ID, body={"title": a["keyword"], "content": full}, isDraft=False).execute()
    return r.get("url", "")

def pub_blogger_post(blogger, a, html, img):
    full = f'<div style="text-align:center;margin-bottom:20px;"><img src="{img}" style="max-width:100%;border-radius:10px;" alt="{a["keyword"]}"/></div>\n{html}'
    tags = [a["keyword"], "AI Angels", "AI companion", "AI girlfriend"]
    r = blogger.posts().insert(blogId=BLOG_ID, body={"title": a["keyword"], "content": full, "labels": tags, "status": "LIVE"}, isDraft=False).execute()
    return r.get("url", "")

def pub_ghost_page(a, html, img):
    payload = {"pages": [{"title": a["keyword"] + " — Complete Guide", "html": html, "feature_image": img,
                          "feature_image_alt": a["keyword"], "slug": f"guide-{a['slug']}", "status": "published",
                          "tags": [{"name": t} for t in [a["keyword"], "AI Angels", "AI companion"]]}]}
    r = requests.post(f"{GHOST_URL}/ghost/api/admin/pages/?source=html", json=payload, headers=ghost_headers())
    return r.json()["pages"][0].get("url", "") if r.status_code in (200, 201) else f"ERR:{r.status_code}"

def pub_ghost_post(a, html, img):
    payload = {"posts": [{"title": a["keyword"], "html": html, "feature_image": img,
                          "feature_image_alt": a["keyword"], "slug": a["slug"], "status": "published",
                          "tags": [{"name": t} for t in [a["keyword"], "AI Angels", "AI companion"]]}]}
    r = requests.post(f"{GHOST_URL}/ghost/api/admin/posts/?source=html", json=payload, headers=ghost_headers())
    return r.json()["posts"][0].get("url", "") if r.status_code in (200, 201) else f"ERR:{r.status_code}"

def pub_telegraph(a, html, img):
    tg_token = open(os.path.join(BASE_DIR, "telegraph_token.txt")).read().strip()
    content = [{"tag": "img", "attrs": {"src": img}}]
    sections = re.split(r'<h2[^>]*>(.*?)</h2>', html)
    for j, s in enumerate(sections):
        s = s.strip()
        if not s: continue
        if j % 2 == 1: content.append({"tag": "h3", "children": [s]})
        else:
            text = re.sub(r'<[^>]+>', '', s).strip()
            if text: content.append({"tag": "p", "children": [text[:2000]]})
    content.append({"tag": "p", "children": [{"tag": "a", "attrs": {"href": f"{SITE_URL}/companions/{a['slug']}"}, "children": [f"Try {a['keyword']} on AI Angels"]}]})
    r = requests.post("https://api.telegra.ph/createPage", data={"access_token": tg_token, "title": a["keyword"], "author_name": "AI Angels", "author_url": SITE_URL, "content": json.dumps(content)})
    d = r.json()
    return d["result"]["url"] if d.get("ok") else f"ERR:{d}"

def pub_notion(a, html, img):
    n_tok, n_pg = os.getenv("NOTION_TOKEN"), os.getenv("NOTION_PAGE_ID")
    blocks = []
    sections = re.split(r'<h2[^>]*>(.*?)</h2>', html)
    for j, s in enumerate(sections):
        s = s.strip()
        if not s: continue
        if j % 2 == 1: blocks.append({"object": "block", "type": "heading_2", "heading_2": {"rich_text": [{"type": "text", "text": {"content": s[:100]}}]}})
        else:
            text = re.sub(r'<[^>]+>', '', s).strip()
            if text:
                for c in [text[x:x+2000] for x in range(0, len(text), 2000)]:
                    blocks.append({"object": "block", "type": "paragraph", "paragraph": {"rich_text": [{"type": "text", "text": {"content": c}}]}})
    blocks.append({"object": "block", "type": "image", "image": {"type": "external", "external": {"url": img}}})
    r = requests.post("https://api.notion.com/v1/pages", json={
        "parent": {"type": "page_id", "page_id": n_pg}, "cover": {"type": "external", "external": {"url": img}},
        "icon": {"type": "emoji", "emoji": "🤖"}, "properties": {"title": {"title": [{"type": "text", "text": {"content": a["keyword"]}}]}},
        "children": blocks[:100]}, headers={"Authorization": f"Bearer {n_tok}", "Notion-Version": "2022-06-28", "Content-Type": "application/json"})
    return r.json().get("url", "") if r.status_code == 200 else f"ERR:{r.status_code}"

def pub_livejournal(a, html, img):
    lj = xmlrpc.client.ServerProxy("https://www.livejournal.com/interface/xmlrpc")
    full = f'<img src="{img}" style="max-width:100%;border-radius:10px;" alt="{a["keyword"]}"/><br/>\n{html}'
    now = datetime.now()
    r = lj.LJ.XMLRPC.postevent({"username": os.getenv("LJ_USERNAME"), "hpassword": hashlib.md5(os.getenv("LJ_PASSWORD").encode()).hexdigest(),
        "ver": 1, "subject": a["keyword"], "event": full, "lineendings": "unix", "security": "public",
        "year": now.year, "mon": now.month, "day": now.day, "hour": now.hour, "min": now.minute,
        "props": {"opt_preformatted": 1, "taglist": ", ".join([a["keyword"], "AI Angels", "AI companion"][:5])}})
    return f"https://{os.getenv('LJ_USERNAME')}.livejournal.com/{r['itemid']}.html"

def pub_tumblr(a, teaser):
    oauth = OAuth1Session(os.getenv("TUMBLR_CONSUMER_KEY"), client_secret=os.getenv("TUMBLR_CONSUMER_SECRET"),
        resource_owner_key=os.getenv("TUMBLR_OAUTH_TOKEN"), resource_owner_secret=os.getenv("TUMBLR_OAUTH_SECRET"))
    r = oauth.post("https://api.tumblr.com/v2/blog/aiangelsofficial/post", data={"type": "text", "state": "published", "title": a["keyword"], "body": teaser, "tags": ",".join([a["keyword"], "AI Angels", "AI companion"])})
    pid = r.json().get("response", {}).get("id", "")
    return f"https://www.tumblr.com/blog/view/aiangelsofficial/{pid}"

def pub_writeas(a, md):
    wa_h = {"Authorization": f"Token {os.getenv('WRITEAS_TOKEN')}", "Content-Type": "application/json"}
    r = requests.post("https://write.as/api/collections/aiangels/posts", json={"title": a["keyword"], "body": md, "font": "sans"}, headers=wa_h)
    return f"https://write.as/aiangels/{r.json()['data']['slug']}" if r.status_code in (200, 201) else f"ERR:{r.status_code}"

def pub_wordpress(a, html, img):
    full = f'<img src="{img}" style="max-width:100%;border-radius:10px;" alt="{a["keyword"]}"/><br/>{html}'
    r = requests.post(f"https://{WP_IP}/rest/v1.1/sites/{WP_SITE}/posts/new",
        headers={"Authorization": f"Bearer {WP_TOKEN}", "Host": "public-api.wordpress.com", "Content-Type": "application/x-www-form-urlencoded"},
        data={"title": a["keyword"], "content": full, "tags": ",".join([a["keyword"], "AI Angels", "AI companion"]), "categories": "AI Companions", "status": "publish"}, verify=False, timeout=30)
    return r.json().get("URL", "") if r.status_code in (200, 201) else f"ERR:{r.status_code}"

def pub_github_pages(a, md, img):
    gh_dir = "/tmp/aiangels-pages"
    fn = f"_posts/2026-04-14-{a['slug']}.md"
    fp = os.path.join(gh_dir, fn)
    tags = " ".join(t.lower().replace(" ", "-") for t in [a["keyword"], "AI Angels", "AI companion"][:3])
    with open(fp, 'w') as f:
        f.write(f'---\nlayout: post\ntitle: "{a["keyword"]}"\ndate: 2026-04-14\ntags: [{tags}]\nimage: {img}\n---\n\n![{a["keyword"]}]({img})\n\n{md}\n')
    return fn

def pub_buttondown(a, md, img):
    bd_h = {"Authorization": f"Token {os.getenv('BUTTONDOWN_API_KEY')}", "Content-Type": "application/json", "X-Buttondown-Live-Dangerously": "true"}
    full_md = f"![{a['keyword']}]({img})\n\n{md}"
    r = requests.post("https://api.buttondown.com/v1/emails", json={"subject": a["keyword"], "body": full_md, "status": "about_to_send"}, headers=bd_h)
    return r.json().get("slug", "") if r.status_code in (200, 201) else f"ERR:{r.status_code}"

def pub_mastodon(a, micro):
    mast_h = {"Authorization": f"Bearer {os.getenv('MASTODON_ACCESS_TOKEN')}"}
    r = requests.post("https://mastodon.social/api/v1/statuses", headers=mast_h, data={"status": micro, "visibility": "public"})
    return r.json().get("url", "") if r.status_code in (200, 201) else f"ERR:{r.status_code}"

def pub_mataroa(a, md, img):
    mat_h = {"Authorization": f"Bearer {os.getenv('MATAROA_API_KEY')}", "Content-Type": "application/json"}
    r = requests.post("https://mataroa.blog/api/posts/", json={"title": a["keyword"], "slug": a["slug"], "body": f"![{a['keyword']}]({img})\n\n{md}", "published_at": "2026-04-14"}, headers=mat_h)
    return a["slug"] if r.status_code in (200, 201) else f"ERR:{r.status_code}"

def pub_dreamwidth(a, html, img):
    dw = xmlrpc.client.ServerProxy("https://www.dreamwidth.org/interface/xmlrpc")
    full = f'<img src="{img}" style="max-width:100%;border-radius:10px;" alt="{a["keyword"]}"/><br/>\n{html}'
    now = datetime.now()
    r = dw.LJ.XMLRPC.postevent({"username": "aiangels", "password": "grwgrwhw35256?53", "ver": 1,
        "subject": a["keyword"], "event": full, "lineendings": "unix", "security": "public",
        "year": now.year, "mon": now.month, "day": now.day, "hour": now.hour, "min": now.minute,
        "props": {"opt_preformatted": 1, "taglist": ", ".join([a["keyword"], "AI Angels"][:5])}})
    return f"https://aiangels.dreamwidth.org/{r['itemid']}.html"

def pub_gist(a, md, img):
    gh_token = os.popen("gh auth token 2>/dev/null").read().strip()
    gh_h = {"Authorization": f"token {gh_token}", "Accept": "application/vnd.github+json", "Content-Type": "application/json"}
    gist_md = f"# {a['keyword']}\n\n![{a['keyword']}]({img})\n\n{md}"
    r = requests.post("https://api.github.com/gists", json={"description": a["keyword"], "public": True, "files": {f"{a['slug']}.md": {"content": gist_md}}}, headers=gh_h)
    return r.json().get("html_url", "") if r.status_code in (200, 201) else f"ERR:{r.status_code}"

def pub_hubspot(a, html, img):
    headers = {"Authorization": f"Bearer {HUBSPOT_TOKEN}", "Content-Type": "application/json"}
    r = requests.post("https://api.hubapi.com/cms/v3/blogs/posts", headers=headers, json={
        "name": a["keyword"], "contentGroupId": HUBSPOT_BLOG_ID, "slug": a["slug"],
        "postBody": f'<img src="{img}" alt="{a["keyword"]}" style="max-width:100%;border-radius:10px;"/>{html}',
        "metaDescription": f'{a["keyword"]} - AI Angels. {a["personality"].capitalize()}.', "blogAuthorId": HUBSPOT_AUTHOR,
        "featuredImage": img, "useFeaturedImage": True, "state": "PUBLISHED"})
    return r.json().get("url", "") if r.status_code in (200, 201) else f"ERR:{r.status_code}"

def pub_prose(a, md, img):
    full = f"---\ntitle: \"{a['keyword']}\"\ndescription: \"{a['keyword']} on AI Angels\"\ndate: 2026-04-14\ntags: [ai-girlfriend, ai-angels, ai-companion]\n---\n\n![{a['keyword']}]({img})\n\n{md}"
    result = subprocess.run(["ssh", "-i", SSH_KEY, "-o", "StrictHostKeyChecking=accept-new", "prose.sh", f"{a['slug']}.md"],
        input=full.encode(), capture_output=True, timeout=15)
    return result.stdout.decode().strip()

def pub_bearblog(session, a, md):
    DASH = "https://bearblog.dev/aiangels-companions/dashboard"
    r = session.get(f"{DASH}/posts/new/")
    soup = BeautifulSoup(r.text, "html.parser")
    csrf = soup.find("input", {"name": "csrfmiddlewaretoken"})["value"]
    session.post(f"{DASH}/posts/new/", data={
        "csrfmiddlewaretoken": csrf, "header_content": f"title: {a['keyword']}", "body_content": md, "publish": "true",
    }, headers={"Referer": f"{DASH}/posts/new/"}, allow_redirects=True)
    return f"https://aiangels-companions.bearblog.dev/{a['slug'].lower()}/"

def pub_contentful(a, md, img):
    headers = {"Authorization": f"Bearer {CONTENTFUL_TOKEN}", "Content-Type": "application/vnd.contentful.management.v1+json", "X-Contentful-Content-Type": "blogPost"}
    BASE = f"https://api.contentful.com/spaces/{CONTENTFUL_SPACE}/environments/master"
    entry_data = {"fields": {
        "title": {"en-US": a["keyword"]}, "slug": {"en-US": a["slug"]}, "body": {"en-US": md},
        "metaDescription": {"en-US": f'{a["keyword"]} on AI Angels. {a["personality"].capitalize()}.'},
        "featuredImage": {"en-US": img}, "tags": {"en-US": [a["keyword"], "AI Angels", "AI companion", "AI girlfriend"]}}}
    r = requests.put(f"{BASE}/entries/{a['slug']}", headers=headers, json=entry_data)
    if r.status_code in (200, 201):
        v = r.json()["sys"]["version"]
        requests.put(f"{BASE}/entries/{a['slug']}/published", headers={**headers, "X-Contentful-Version": str(v)})
        return a["slug"]
    return f"ERR:{r.status_code}"


# ═══════════════════════════════════════════════════════════════
# MAIN PUBLISH FLOW
# ═══════════════════════════════════════════════════════════════
def publish_batch(articles, photos, all_slugs, publish_log, dry_run=False):
    """Publish a batch of articles across all 18 platforms"""
    if not articles:
        log.info("No articles to publish!")
        return

    log.info(f"\n{'='*60}")
    log.info(f"PUBLISHING {len(articles)} ARTICLES ACROSS 18 PLATFORMS")
    log.info(f"{'='*60}\n")

    # Initialize services
    creds = None
    if os.path.exists(os.path.join(BASE_DIR, "token.pickle")):
        with open(os.path.join(BASE_DIR, "token.pickle"), "rb") as f:
            creds = pickle.load(f)
    if creds and creds.expired and creds.refresh_token:
        creds.refresh(Request())
    blogger = build("blogger", "v3", credentials=creds)

    # Bear Blog session
    bb_session = requests.Session()
    r = bb_session.get("https://bearblog.dev/accounts/login/")
    soup = BeautifulSoup(r.text, "html.parser")
    csrf = soup.find("input", {"name": "csrfmiddlewaretoken"})["value"]
    bb_session.post("https://bearblog.dev/accounts/login/", data={
        "csrfmiddlewaretoken": csrf, "login": "ceo@aiangels.io", "password": "D4r243f??f3f3feg",
    }, headers={"Referer": "https://bearblog.dev/accounts/login/"})

    # GitHub Pages pull
    gh_dir = "/tmp/aiangels-pages"
    os.system(f"cd {gh_dir} && git pull origin gh-pages 2>&1 >/dev/null")

    blogger_pages = {}

    PLATFORMS = [
        ("Blogger Page", 6, lambda a, html, md, img, teaser, micro: pub_blogger_page(blogger, a, html, img)),
        ("Blogger Post", 6, lambda a, html, md, img, teaser, micro: pub_blogger_post(blogger, a, html, img)),
        ("Ghost Page", 2, lambda a, html, md, img, teaser, micro: pub_ghost_page(a, html, img)),
        ("Ghost Post", 2, lambda a, html, md, img, teaser, micro: pub_ghost_post(a, html, img)),
        ("Telegraph", 2, lambda a, html, md, img, teaser, micro: pub_telegraph(a, html, img)),
        ("Notion", 3, lambda a, html, md, img, teaser, micro: pub_notion(a, html, img)),
        ("LiveJournal", 3, lambda a, html, md, img, teaser, micro: pub_livejournal(a, html, img)),
        ("Tumblr", 5, lambda a, html, md, img, teaser, micro: pub_tumblr(a, teaser)),
        ("Write.as", 12, lambda a, html, md, img, teaser, micro: pub_writeas(a, md)),
        ("WordPress", 3, lambda a, html, md, img, teaser, micro: pub_wordpress(a, html, img)),
        ("Buttondown", 3, lambda a, html, md, img, teaser, micro: pub_buttondown(a, md, img)),
        ("Mastodon", 5, lambda a, html, md, img, teaser, micro: pub_mastodon(a, micro)),
        ("Mataroa", 2, lambda a, html, md, img, teaser, micro: pub_mataroa(a, md, img)),
        ("Dreamwidth", 5, lambda a, html, md, img, teaser, micro: pub_dreamwidth(a, html, img)),
        ("GitHub Gists", 2, lambda a, html, md, img, teaser, micro: pub_gist(a, md, img)),
        ("HubSpot", 2, lambda a, html, md, img, teaser, micro: pub_hubspot(a, html, img)),
        ("Prose.sh", 2, lambda a, html, md, img, teaser, micro: pub_prose(a, md, img)),
        ("Bear Blog", 2, lambda a, html, md, img, teaser, micro: pub_bearblog(bb_session, a, md)),
        ("Contentful", 2, lambda a, html, md, img, teaser, micro: pub_contentful(a, md, img)),
    ]

    for platform_name, delay, pub_fn in PLATFORMS:
        log.info(f"\n═══ {platform_name.upper()} ═══\n")
        for i, a in enumerate(articles):
            slug = a["slug"]
            log_key = f"{slug}:{platform_name}"
            if log_key in publish_log:
                log.info(f"  ⏭️  [{i+1}/{len(articles)}] {a['keyword']} (already published)")
                continue

            img = get_photo(photos, slug, PLATFORMS.index((platform_name, delay, pub_fn)) % 7)
            html = generate_html_full(a, photos, all_slugs)
            md = generate_md_medium(a, photos, all_slugs)
            teaser = generate_teaser(a, photos)
            micro = generate_micro(a)

            if dry_run:
                log.info(f"  🔍 [{i+1}/{len(articles)}] {a['keyword']} (dry run)")
                continue

            try:
                result = retry(lambda: pub_fn(a, html, md, img, teaser, micro), max_retries=2, delay=delay*2)
                publish_log[log_key] = {"url": str(result), "time": datetime.now().isoformat()}
                save_log(publish_log)
                log.info(f"  ✅ [{i+1}/{len(articles)}] {a['keyword']}: {result}")
            except Exception as e:
                log.error(f"  ❌ [{i+1}/{len(articles)}] {a['keyword']}: {e}")
            time.sleep(delay)

    # Push GitHub Pages
    os.system(f"cd {gh_dir} && git add -A && git commit -m 'Add {len(articles)} new articles' && git push origin gh-pages 2>&1 >/dev/null")
    log.info("\n✅ GitHub Pages pushed")

    log.info(f"\n{'='*60}")
    log.info("BATCH COMPLETE!")
    log.info(f"{'='*60}")


def show_status(publish_log):
    """Show publishing status per platform"""
    platforms = {}
    for key, val in publish_log.items():
        slug, platform = key.rsplit(":", 1)
        platforms.setdefault(platform, []).append(slug)

    print(f"\n{'Platform':<20} {'Published':>10}")
    print("-" * 32)
    for p, slugs in sorted(platforms.items(), key=lambda x: -len(x[1])):
        print(f"{p:<20} {len(slugs):>10}")
    print("-" * 32)
    print(f"{'Total entries':<20} {len(publish_log):>10}")
    print(f"{'Unique articles':<20} {len(set(k.rsplit(':',1)[0] for k in publish_log)):>10}")


def main():
    parser = argparse.ArgumentParser(description="AI Angels Multi-Platform Publishing Engine")
    parser.add_argument("--batch", type=int, help="Publish specific batch (1-5)")
    parser.add_argument("--status", action="store_true", help="Show publishing status")
    parser.add_argument("--dry-run", action="store_true", help="Preview without publishing")
    args = parser.parse_args()

    publish_log = load_log()

    if args.status:
        show_status(publish_log)
        return

    articles = load_articles()
    photos = load_photos()
    all_slugs = get_all_slugs(articles)

    # Filter already-fully-published articles
    new_articles = []
    for a in articles:
        slug = a["slug"]
        published_count = sum(1 for k in publish_log if k.startswith(f"{slug}:"))
        if published_count < 18:  # 18 platforms
            new_articles.append(a)

    if args.batch:
        start = (args.batch - 1) * BATCH_SIZE
        end = start + BATCH_SIZE
        batch = new_articles[start:end]
        log.info(f"Batch {args.batch}: articles {start+1}-{min(end, len(new_articles))} of {len(new_articles)}")
    else:
        batch = new_articles[:BATCH_SIZE]
        log.info(f"Publishing next {len(batch)} of {len(new_articles)} unpublished articles")

    publish_batch(batch, photos, all_slugs, publish_log, dry_run=args.dry_run)


if __name__ == "__main__":
    main()
