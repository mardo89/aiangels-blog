// Drop-in JSON-LD schema.org injector.
//
// Usage (in any landing/compare/feature page.tsx):
//   import { JsonLdBlock } from "@/app/_components/JsonLdBlock";
//   <JsonLdBlock url={`https://www.aiangels.io${pathname}`} />
//
// Data source: agent-ready/public/jsonld/<page_type>-<slug>.json
// Regenerate with: python generate_jsonld.py
//
// This is a server component — schema is rendered into initial HTML so AI
// crawlers see it without executing JS.

import { promises as fs } from "node:fs";
import path from "node:path";

type Props = { url: string };

function filenameFor(url: string): string | null {
  try {
    const u = new URL(url);
    const parts = u.pathname.replace(/^\/+|\/+$/g, "").split("/").filter(Boolean);
    if (parts.length === 0) return "landing-.json"; // root
    if (parts[0] === "compare" && parts[1]) return `compare-${parts[1]}.json`;
    if (parts[0] === "features" && parts[1]) return `feature-${parts[1]}.json`;
    if (parts[0] === "companions" && parts[1]) return `companion-${parts[1]}.json`;
    // Assume landing
    return `landing-${parts[0]}.json`;
  } catch {
    return null;
  }
}

async function loadSchema(url: string): Promise<object | null> {
  const fname = filenameFor(url);
  if (!fname) return null;
  const full = path.join(process.cwd(), "public", "jsonld", fname);
  try {
    const raw = await fs.readFile(full, "utf8");
    return JSON.parse(raw);
  } catch {
    return null;
  }
}

export async function JsonLdBlock({ url }: Props) {
  const schema = await loadSchema(url);
  if (!schema) return null;
  return (
    <script
      type="application/ld+json"
      // eslint-disable-next-line react/no-danger
      dangerouslySetInnerHTML={{ __html: JSON.stringify(schema) }}
    />
  );
}
