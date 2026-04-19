// Generic OG image generator for landing / compare / feature pages.
//
// Deploy pattern: drop this file into each route as `opengraph-image.tsx` and
// customize `loadMeta()` to fetch the right title/subtitle for that page.
//
// Example for `/ai-girlfriend/opengraph-image.tsx`:
//
//   import { renderLandingOg } from "@/app/_components/LandingOgImage";
//   export const runtime = "edge";
//   export const size = { width: 1200, height: 630 };
//   export const contentType = "image/png";
//   export default async function Image() {
//     return renderLandingOg({
//       title: "AI Girlfriend",
//       subtitle: "Unlimited, uncensored AI companion chat with memory.",
//       urlPath: "/ai-girlfriend",
//     });
//   }

import { ImageResponse } from "next/og";

export const size = { width: 1200, height: 630 };
export const contentType = "image/png";

type OgProps = { title: string; subtitle: string; urlPath: string };

export function renderLandingOg({ title, subtitle, urlPath }: OgProps) {
  return new ImageResponse(
    (
      <div
        style={{
          display: "flex",
          flexDirection: "column",
          justifyContent: "center",
          width: "100%",
          height: "100%",
          padding: 72,
          background: "linear-gradient(135deg,#1a0033 0%,#4a0070 50%,#7a1a9a 100%)",
          color: "white",
          fontFamily: "system-ui",
        }}
      >
        <div style={{ fontSize: 28, opacity: 0.75, letterSpacing: 2, textTransform: "uppercase" }}>
          AI Angels
        </div>
        <div style={{ fontSize: 104, fontWeight: 900, lineHeight: 1.05, marginTop: 18, maxWidth: 980 }}>
          {title}
        </div>
        <div style={{ fontSize: 36, marginTop: 32, opacity: 0.9, maxWidth: 1000, lineHeight: 1.35 }}>
          {subtitle}
        </div>
        <div style={{ marginTop: "auto", fontSize: 24, opacity: 0.65 }}>
          www.aiangels.io{urlPath}
        </div>
      </div>
    ),
    size,
  );
}
