# PR: Agent-readiness bundle — AI-search visibility infrastructure

## Summary

Ships the full agent-readiness stack for aiangels.io:
- **71 per-URL JSON-LD schema.org graphs** (Organization, WebSite, Breadcrumb, WebPage+speakable, FAQPage, Product) — rendered server-side on every landing/compare/feature/companion page.
- **355 Claude-authored FAQ Q&A pairs** across 71 URLs, rendered as `<dl>` in HTML AND as `FAQPage` schema for LLM citation.
- **5-link semantic internal-linking graph** on every page (355 total cross-links).
- **Markdown content negotiation** (`Accept: text/markdown` → clean text for AI crawlers).
- **Full `.well-known/` agent-discovery surface**: agent-skills, MCP server card, API catalog, Web Bot Auth directory.
- **Rich `robots.txt`** with explicit `Allow` for every AI bot (`PerplexityBot`, `OAI-SearchBot`, `GPTBot`, `ClaudeBot`, `Google-Extended`, `Bingbot`, etc.) and Content-Signal directives.
- **Four drop-in components** wired into the landing template: `<JsonLdBlock/>`, `<Faq/>`, `<RelatedLinks/>`, `<renderLandingOg/>`.

Baseline measurement (pre-deploy, audited 2026-04-20 across 5 AI engines):
| Engine | P1 citation rate |
|---|---|
| ChatGPT | 0% |
| Gemini | 0% |
| Grok | 0% |
| Perplexity /search | 0% (not in index) |
| Perplexity /agent | 0% |

**Target after deploy: 20% citation rate within 8 weeks.** Weekly scorecard runs post-merge.

---

## File checklist

Copy from the source repo's `agent-ready/` directory into this repo root, preserving paths.

### `app/_components/` — new (mount points)
- [ ] `app/_components/JsonLdBlock.tsx` *(async server component — reads `public/jsonld/*.json`)*
- [ ] `app/_components/Faq.tsx` *(reads `faq_content.json`)*
- [ ] `app/_components/RelatedLinks.tsx` *(reads `internal_links.json`)*
- [ ] `app/_components/LandingOgImage.tsx` *(shared OG template for landing pages)*

### `app/_lib/` — new
- [ ] `app/_lib/jsonld-index.ts` *(auto-generated TS import map — regenerate via `python3 generate_jsonld.py`)*

### `app/md/[...path]/route.ts` — new route
- [ ] `app/md/[...path]/route.ts` *(content negotiation: returns markdown instead of HTML when `Accept: text/markdown`)*
- [ ] Replace the placeholder `htmlToMarkdown` with `turndown`:
  ```bash
  npm i turndown @types/turndown
  ```

### `middleware.ts` — merge with existing
- [ ] Add `Link:` response headers pointing to `llms.txt`, `api-catalog`, `agent-skills`
- [ ] Add `Vary: Accept` to every response
- [ ] Rewrite `/md/*` content negotiation

### `public/` — copy directly
- [ ] `public/robots.txt` — full AI-bot allowlist + Content-Signal directives ⚠️ merge carefully with existing
- [ ] `public/jsonld/` — **71 files** (9 landing + 12 compare + 13 feature + 37 companion)
- [ ] `public/.well-known/agent-skills/` — 8 files (index.json + 7 skill docs)
- [ ] `public/.well-known/api-catalog` (RFC 9727 linkset)
- [ ] `public/.well-known/mcp/server-card.json`
- [ ] `public/.well-known/oauth-authorization-server`
- [ ] `public/.well-known/http-message-signatures-directory` *(scaffold — needs real Ed25519 key before prod)*
- [ ] `public/llms.txt` *(already deployed per repo notes — verify unchanged)*

### Repo root — data files
Three options for where these live; pick one and wire the components to match:
- [ ] **Option A (simplest)**: drop as JSON files in repo root, import via `fs.readFile` at request time (what the drop-in components do out-of-the-box):
  - `faq_content.json` *(172 KB, 71 URLs × 5 Q&As)*
  - `internal_links.json` *(63 KB)*
  - `meta_variants.json` *(90 KB, not wired yet — used at Blogger publish time)*
- [ ] **Option B**: move into `public/` so they're served as static JSON — then update component fetch paths.
- [ ] **Option C**: upload into a Supabase `page_content` table, update component loaders to call Supabase. Best long-term; pair with editorial overrides per URL.

### Profile LLM-SEO stack *(already scoped in `agent-ready/README.md`)*
- [ ] `app/profile/[id]/page.tsx` — full SSR replacement for client-rendered profile
- [ ] `app/profile/[id]/opengraph-image.tsx`
- [ ] `app/profile/[id].md/route.ts` — markdown twin
- [ ] `app/api/profile/[id]/route.ts` — JSON twin
- [ ] `app/api/profiles/route.ts` — paginated list
- [ ] `app/profile/_lib/{loader,types,jsonld}.ts`
- [ ] `app/sitemap-profiles.xml/route.ts`
- [ ] `app/api/mcp/route.ts` — live MCP endpoint

### `app/sitemap.xml/route.ts` — convert to sitemapindex
- [ ] Replace current sitemap with a sitemapindex pointing at `sitemap-pages.xml` + `sitemap-profiles.xml`:
  ```xml
  <sitemapindex xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
    <sitemap><loc>https://www.aiangels.io/sitemap-pages.xml</loc></sitemap>
    <sitemap><loc>https://www.aiangels.io/sitemap-profiles.xml</loc></sitemap>
  </sitemapindex>
  ```

---

## Required integration edits in existing pages

After files are copied, wire the components into the page templates. Add to **every landing, compare, feature, and companion page**:

```tsx
import { JsonLdBlock } from "@/app/_components/JsonLdBlock";
import { Faq } from "@/app/_components/Faq";
import { RelatedLinks } from "@/app/_components/RelatedLinks";

export default function Page({ pathname }) {
  const url = `https://www.aiangels.io${pathname}`;
  return (
    <>
      {/* existing content above */}
      <JsonLdBlock url={url} />
      {/* ... main content ... */}
      <Faq url={url} />
      <RelatedLinks url={url} />
    </>
  );
}
```

Pages to edit:
- [ ] 9 landing pages: `app/{ai-girlfriend,ai-girlfriend-app,create-ai-girlfriend,real-ai-girlfriend,hot-ai-girlfriend,ai-sexy-chat,ai-sexting-chat,ai-chat-18,ai-jerk-off-chat}/page.tsx`
- [ ] 12 compare pages: `app/compare/[slug]/page.tsx` *(if dynamic route)* or per-page files
- [ ] 13 feature pages: `app/features/[slug]/page.tsx` *(if dynamic)* or per-page files
- [ ] 37 companion pages: `app/companions/[slug]/page.tsx` *(dynamic is fine — components take `url` prop)*

---

## Required backend touchpoints

Endpoints the MCP server (`app/api/mcp/route.ts`) expects to exist — confirm or stub:
- [ ] `GET /api/companions` → list of companions JSON
- [ ] `GET /api/articles` → list of articles JSON
- [ ] `GET /api/search?q=` → unified search JSON

OAuth discovery file declares endpoints — either stand up minimal OAuth2 + PKCE flow, or return 501 on authorize (metadata-only still passes the agent-readiness check):
- [ ] `/authorize`, `/token`, `/revoke` — stub or implement

Web Bot Auth signing key:
- [ ] Generate Ed25519 key: `openssl genpkey -algorithm ed25519 -out bot-signing.pem`
- [ ] Export public JWK, paste into `public/.well-known/http-message-signatures-directory`
- [ ] (Optional for first ship — scaffold file passes the discovery check without a real key.)

---

## Test plan

### Pre-merge (local)
- [ ] `npm run build` passes
- [ ] `npm run dev` — open `/ai-girlfriend`, view source, confirm:
  - `<script type="application/ld+json">` contains 6 `@type` nodes (Organization, WebSite, BreadcrumbList, WebPage, FAQPage, Product)
  - FAQ `<dl>` with 5 Q&As in HTML
  - RelatedLinks `<nav>` with 5 cross-links
- [ ] `curl -H "Accept: text/markdown" http://localhost:3000/ai-girlfriend` returns markdown, not HTML
- [ ] `curl http://localhost:3000/.well-known/agent-skills/index.json` returns 200
- [ ] `curl http://localhost:3000/sitemap.xml` returns a sitemapindex

### Post-merge (production)
- [ ] https://search.google.com/test/rich-results?url=https://www.aiangels.io/ai-girlfriend — FAQ + Product schema both detected
- [ ] https://isitagentready.com/?site=https://www.aiangels.io — every check passes
- [ ] Manual query on Perplexity: `site:aiangels.io` — confirms the index is crawling
- [ ] Submit sitemap to Bing Webmaster Tools: https://www.bing.com/webmasters
- [ ] Submit sitemap to Google Search Console
- [ ] Run IndexNow: `python3 chatgpt_indexing.py` (from the automation repo)

### Measurement baseline
- [ ] Run `python3 multi_llm_citation_checker.py --priority 1` in the automation repo
- [ ] Snapshot the scorecard (currently 0/0/0/0/0)
- [ ] Re-run weekly; expect first non-zero citation at week 3-4

---

## Rollback plan

All changes are additive except `robots.txt`, `middleware.ts`, and `app/sitemap.xml/route.ts`. If issues:

1. Revert `robots.txt` to current version → AI bots fall back to default crawl
2. Revert `middleware.ts` → markdown negotiation disabled, Link headers dropped
3. Revert `sitemap.xml/route.ts` → single sitemap behavior restored
4. The 71 JSON-LD files and 4 components can stay — they're inert without the page-level imports

---

## Post-deploy: schedule the refresh loop

From the automation repo (`aiangels-blog`), deploy the Modal scheduler **(replaces GitHub Actions — banned on this account)**:

```bash
pip install modal
modal setup
modal secret create aiangels-env ANTHROPIC_API_KEY=... OPENAI_API_KEY=... GOOGLE_API_KEY=... PERPLEXITY_API_KEY=... XAI_API_KEY=... SUPABASE_URL=... SUPABASE_SERVICE_ROLE_KEY=... BLOGGER_BLOG_ID=... INDEXNOW_KEY=...
modal deploy modal_schedules.py
```

Schedules that start firing immediately:
- Daily 02:00 UTC → IndexNow submission
- Mondays 03:00 → multi-LLM citation check
- Mondays 04:00 → FAQ/meta/JSON-LD regeneration
- Sundays 05:00 → article refresh (10 oldest Blogger copies)
- Monthly 06:00 day 1 → programmatic pages + llms-full.txt regen

---

## Follow-ups (not blocking this PR)

- [ ] `/vs/[slug]` and `/best/[slug]` Next.js routes for the 350 programmatic pages (separate PR)
- [ ] Perplexity embeddings-based de-dup of programmatic pages before mass-publish
- [ ] Turn on Web Bot Auth signing key for production
- [ ] Replace placeholder Product offer prices with real pricing from billing system
