# Agent-Readiness Deploy — Developer Handoff

## TL;DR

The aiangels.io Next.js site has **0% citation across every major AI search engine** (measured 2026-04-20 across ChatGPT, Gemini, Grok, Perplexity search, Perplexity agent). Perplexity's `/search` doesn't even return aiangels.io in the top 10 for "best ai girlfriend app" — meaning we're not in the index, so AI answers physically cannot cite us.

This bundle fixes that by shipping a full agent-readiness stack: JSON-LD schema, FAQ pages, internal linking, markdown content negotiation, AI-bot allowlisting, and `.well-known/` discovery files.

**What you're shipping:** everything in `agent-ready/`.
**Where:** the aiangels.io Next.js repo (a separate repo from this one — this repo is pure automation / publishing).
**PR checklist:** [`DEPLOY_PR.md`](DEPLOY_PR.md) — that's the actual file-by-file guide, use it as the PR description.

---

## Why now — the measured problem

Run by me on 2026-04-20 against 39 P1 landing-page keywords:

| Engine | Model | Cites aiangels.io? |
|---|---|---|
| ChatGPT | gpt-4o-mini | 0% |
| Gemini | 2.5-flash-lite | 0% |
| Grok | 4-fast-non-reasoning | 0% |
| Perplexity search | `/search` top-10 | 0% |
| Perplexity agent | `/v1/responses` fast-search | 0% |

Root cause analysis (from the Perplexity `/search` run): aiangels.io is not in Perplexity's index at all. Competitors who ARE getting cited (Candy AI, Replika, Nomi.ai, DreamGF, Muah.AI) have three things we don't:

1. **Explicit bot allowlist** with `Content-Signal` directives in `robots.txt`
2. **Structured data** — schema.org `FAQPage`, `Product`, `Organization` graphs in `<script type="application/ld+json">`
3. **LLM-friendly alternatives** — `llms.txt`, `llms-full.txt`, `Accept: text/markdown` content negotiation

This bundle ships all three, per-URL, pre-generated.

---

## What's in `agent-ready/`

Everything below is ready to copy directly into the aiangels.io Next.js repo. No code needs to be written — only merged and imported.

### 71 pre-built JSON-LD files — `public/jsonld/`
One file per URL. Each is a full schema.org `@graph` with 6 coordinated nodes: `Organization`, `WebSite`, `BreadcrumbList`, `WebPage` with speakable selectors, `FAQPage` (5 Q&As each), and `Product` (for landing/compare pages).

Broken down:
- 9 landing pages (`ai-girlfriend`, `hot-ai-girlfriend`, etc.)
- 12 competitor comparisons (`replika-alternative`, `character-ai-alternative`, etc.)
- 13 feature pages (`ai-girlfriend-memory`, `uncensored-ai-girlfriend`, etc.)
- 37 companion categories (`blonde-ai-girlfriend`, `goth-ai-girlfriend`, etc.)

### 4 drop-in React components — `app/_components/`
- `JsonLdBlock.tsx` — async server component that injects `<script type="application/ld+json">` on any page, by URL.
- `Faq.tsx` — renders 5 Q&A pairs as `<dl>` (indexable HTML) from `faq_content.json`.
- `RelatedLinks.tsx` — renders 5 semantically-related internal links from `internal_links.json`.
- `LandingOgImage.tsx` — reusable OG card template for non-profile landing pages.

### Data files (from repo root — relocate to `public/` or Supabase per your call)
- `faq_content.json` — 355 Claude-authored Q&As
- `internal_links.json` — semantic link graph, 355 internal links
- `meta_variants.json` — 426 CTR-optimized title/description variants (consumed at Blogger publish time, not on-page)

### Discovery infrastructure — `public/.well-known/`
- `agent-skills/` — skill index + 7 skill docs (how AI agents can use the site)
- `api-catalog` — RFC 9727 linkset
- `mcp/server-card.json` — MCP server discovery card
- `oauth-authorization-server` — OAuth2 discovery (endpoints can stub to 501 for v1)
- `http-message-signatures-directory` — Web Bot Auth scaffolding

### Live endpoints — `app/`
- `app/api/mcp/route.ts` — live MCP server (stateless)
- `app/md/[...path]/route.ts` — markdown content negotiation
- `app/profile/[id]/page.tsx` + `.md` + API routes + OG image — full SSR profile stack replacing the current client-rendered version
- `app/sitemap-profiles.xml/route.ts` — per-profile sitemap

### `middleware.ts`
Adds `Link:` response headers, `Vary: Accept`, and rewrites `/md/*` for content negotiation. Merge with your existing middleware.

### `public/robots.txt`
Explicit `Allow` for every AI crawler (`PerplexityBot`, `OAI-SearchBot`, `GPTBot`, `ClaudeBot`, `Google-Extended`, `Bingbot`, `Applebot-Extended`, etc.) plus `Content-Signal` directives declaring training vs. search permissions per bot.

---

## Deploy checklist

Paste [`DEPLOY_PR.md`](DEPLOY_PR.md) into the PR body. It has:

- Full file-by-file copy list (71 JSON-LD, 4 components, middleware, well-known, etc.)
- The exact import edits to add to every landing/compare/feature/companion page
- Three options for where data files live (repo root / `public/` / Supabase) — pick one
- Backend endpoints MCP expects (`/api/companions`, `/api/articles`, `/api/search?q=`)
- Test plan (local + production)
- Rollback plan (all changes are additive except robots.txt, middleware.ts, sitemap.xml/route.ts)

---

## One decision the dev needs to make

**Where do the data JSON files live?** The drop-in components currently `fs.readFile` from repo root. Three options:

| Option | Pros | Cons |
|---|---|---|
| **A — repo root** | Zero changes to components; ship today | Data changes = code deploy |
| **B — `public/`** | Served as static JSON, can be fetched client-side too | Small component edit (fetch instead of fs.readFile) |
| **C — Supabase** | Editorial overrides per URL, no redeploy for content changes | Component loader rewrite + new DB table |

Recommendation: **Option A for v1**, migrate to C once the team wants editorial control. Regenerate content via the Python scripts in the automation repo — no hand-editing needed.

---

## After deploy — ongoing automation

The automation lives in this separate repo: https://github.com/mardo89/aiangels-blog (this repo).

Post-deploy, install the Modal scheduler (**GitHub Actions is banned on the account**):

```bash
cd /path/to/aiangels-blog
pip install modal
modal setup
modal secret create aiangels-env \
  ANTHROPIC_API_KEY=... OPENAI_API_KEY=... GOOGLE_API_KEY=... \
  PERPLEXITY_API_KEY=... XAI_API_KEY=... SUPABASE_URL=... \
  SUPABASE_SERVICE_ROLE_KEY=... BLOGGER_BLOG_ID=... INDEXNOW_KEY=...
modal deploy modal_schedules.py
```

This schedules, forever:
- **Daily** — IndexNow submission to Bing/Yandex/DuckDuckGo/ChatGPT
- **Weekly (Mon)** — multi-LLM citation scorecard → JSON log
- **Weekly (Mon)** — regenerate FAQ/meta/internal-links/JSON-LD
- **Weekly (Sun)** — publish fresh Blogger copies of the 10 oldest URLs (freshness backlinks)
- **Monthly (1st)** — expand programmatic page matrix + regenerate `llms-full.txt`

The weekly citation scorecard is the KPI — target is **0% → 20% citation rate within 8 weeks**.

---

## Future PRs (not blocking this one)

1. **`/vs/[slug]` and `/best/[slug]` routes** — 350 programmatic SEO URLs ready to ship in `programmatic_pages.json`
2. **Perplexity embeddings de-dup** — before publishing all 350, use `pplx-embed-v1-4b` to cluster semantic duplicates
3. **Web Bot Auth signing key** — generate Ed25519 key + paste JWK into `.well-known/http-message-signatures-directory`
4. **i18n pipeline** — translate 71 URLs into ES/PT/DE/FR/JA/HI via Supabase i18n tables (6× surface area)

---

## Questions? 

Everything above was built during a session in this automation repo. All scripts are committed and documented — run `python3 <script>.py --help` for any of the generators. The baseline citation log (JSON) is at `multi_llm_citation_log.json` once the in-progress baseline run completes.
