// Drop-in internal links block.
//
// Usage (at the bottom of a landing/compare/feature page):
//   import { RelatedLinks } from "@/app/_components/RelatedLinks";
//   <RelatedLinks url={`https://www.aiangels.io${pathname}`} heading="You might also want" />
//
// Data source: internal_links.json at the repo root (copy into the
// aiangels.io repo or serve via a JSON API).
// Regenerate with: python generate_internal_links.py

import { promises as fs } from "node:fs";
import path from "node:path";

type Props = { url: string; heading?: string; max?: number };

type Link = { url: string; type: string; anchor: string; score: number };

async function loadLinks(): Promise<Record<string, Link[]>> {
  const full = path.join(process.cwd(), "internal_links.json");
  try {
    const raw = await fs.readFile(full, "utf8");
    return JSON.parse(raw);
  } catch {
    return {};
  }
}

export async function RelatedLinks({ url, heading = "Related", max = 5 }: Props) {
  const graph = await loadLinks();
  const links = (graph[url] ?? []).slice(0, max);
  if (links.length === 0) return null;
  return (
    <nav aria-label="Related pages" style={{ margin: "2rem 0" }}>
      <h2 style={{ fontSize: "1.25rem", fontWeight: 700 }}>{heading}</h2>
      <ul style={{ listStyle: "none", padding: 0, display: "grid", gap: ".5rem" }}>
        {links.map((link) => (
          <li key={link.url}>
            <a href={link.url} style={{ textDecoration: "underline" }}>
              {link.anchor}
            </a>{" "}
            <span style={{ opacity: 0.6, fontSize: ".875rem" }}>— {link.type}</span>
          </li>
        ))}
      </ul>
    </nav>
  );
}
