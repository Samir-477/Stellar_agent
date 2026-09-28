// Microsite addresses, mirroring engine/output/microsite.py so the UI shows the exact address
// before publishing: /microsites/{archetype}/{client-slug}/{full page path}.

export function slugify(text: string, limit = 60): string {
  return text.toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/^-+|-+$/g, "").slice(0, limit).replace(/-+$/g, "");
}

export function pagePath(url: string): string {
  try {
    const segments = new URL(url).pathname.split("/").map((s) => slugify(s.replace(/\.(html?|php|aspx?)$/i, "")));
    return segments.filter(Boolean).join("/") || "home";
  } catch {
    return "home";
  }
}

export function micrositeHref(archetype: string, clientSlug: string, path: string): string {
  return `/microsites/${archetype}/${clientSlug}/${path}`;
}

/** host + path, lowercase host, no trailing slash: the same comparison as engine/lib/urls.norm. */
export function sameUrl(a: string | null | undefined, b: string | null | undefined): boolean {
  const norm = (u: string) => {
    try {
      const p = new URL(u);
      return `${p.hostname.toLowerCase()}${p.pathname || "/"}`.replace(/\/+$/, "");
    } catch {
      return u;
    }
  };
  return !!a && !!b && norm(a) === norm(b);
}

export const ARCHETYPE_LABEL: Record<string, string> = {
  hospitality: "Hotels and resorts", loans: "Loans and lending", retail: "Retail", logistics: "Logistics",
};
