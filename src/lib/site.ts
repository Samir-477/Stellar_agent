// Single source of truth for brand facts. Metadata, JSON-LD, the sitemap and
// /llms.txt all read from here, so the brand stays identical everywhere.
// Replace the placeholder values before launch.

export const site = {
  name: "Stellar Agents",
  legalName: "Your Brand Ltd",
  description:
    "Stellar Agents diagnoses how search engines, answer engines and AI assistants read a website, and previews the fixes on the site's own pages.",
  url: process.env.NEXT_PUBLIC_SITE_URL ?? (process.env.VERCEL_URL ? `https://${process.env.VERCEL_URL}` : "http://localhost:3000"),
  locale: "en_US",
  logo: "/stellar-agents-mark.svg",
  email: "hello@example.com",
  // Official external profiles (LinkedIn, X, GitHub, Crunchbase...). Used as
  // schema.org sameAs links; keep them identical to what those profiles say.
  sameAs: [] as string[],
} as const;

export type SitePage = {
  path: string;
  title: string;
  description: string;
  lastModified: string; // ISO date, update when the page content changes
};

// Every public page goes here. The sitemap and /llms.txt are generated from
// this list, so a page missing from it is effectively an orphan.
export const pages: SitePage[] = [
  {
    path: "/",
    title: "SEO, AEO and GEO services",
    description: site.description,
    lastModified: "2026-09-27",
  },
];

export function absoluteUrl(path: string): string {
  return new URL(path, site.url).toString();
}
