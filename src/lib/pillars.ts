import type { Pillar } from "@/lib/types";

// The three disciplines, in the words a client understands. Counts come from the engine's registry.
export const PILLARS: Record<Pillar, { short: string; name: string; definition: string; outcome: string }> = {
  seo: {
    short: "SEO",
    name: "Search engine optimization",
    definition: "Making a site easy for search engines such as Google and Bing to crawl, understand and rank.",
    outcome: "Pages that can be found, are described accurately and load fast on a phone.",
  },
  aeo: {
    short: "AEO",
    name: "Answer engine optimization",
    definition: "Shaping content so a search engine can lift it as the direct answer: a featured snippet, an AI Overview or a voice reply.",
    outcome: "Customer questions answered on the site, in a form search engines can quote.",
  },
  geo: {
    short: "GEO",
    name: "Generative engine optimization",
    definition: "Getting a brand mentioned, cited and described correctly by AI assistants such as ChatGPT, Perplexity, Claude and Gemini.",
    outcome: "Facts AI systems can read, trust and repeat correctly about the business.",
  },
};

export const PILLAR_ORDER: Pillar[] = ["seo", "aeo", "geo"];
