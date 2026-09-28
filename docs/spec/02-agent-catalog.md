# 2. Agent Catalog

Three kinds of components: **collectors** gather evidence, **diagnosis agents** judge it, and **action agents** produce new work on demand.

## Collectors (evidence layer)

Collectors run before agents. Each one declares what it produces and what it needs. The orchestrator runs only the collectors the selected agents require, and reuses results from a recent snapshot when they are still fresh.

| ID | Collector | What it produces | Source | Needs | Key / cost | Fresh for |
|---|---|---|---|---|---|---|
| C1 | Site Crawler | Raw server HTML, rendered HTML (headless Chromium), status codes, headers, redirect chains, robots.txt, sitemaps, llms.txt, screenshots, and responses when fetched with AI crawler user agents | Client site | — | Free | 7 days |
| C2 | Page Parser | Structured page model: title, meta, headings, passages, links, images, JSON-LD, microdata, main-content text, template ID. Every element gets a **stable locator** (CSS selector + XPath + text hash) that patches later target. | C1 | C1 | Free | per snapshot |
| C3 | Archetype Detector | Archetype + confidence + signals used. Pauses the run for team confirmation below the confidence threshold. | Rules + DeepSeek | C2 | DeepSeek | per snapshot |
| C4 | Fact Sheet | Business facts, each with ID, value, source URL and status (`site-stated`, `team-confirmed`, `conflicting`): legal name, brands, addresses, phones, services, locations, rates, licences, amenities, coverage | Site extraction (DeepSeek) + team form | C2 | DeepSeek | per snapshot |
| C5 | Query Set | Versioned search queries per client, each labelled `site-derived`, `archetype-template`, `team-added` or (later) `search-console`. Includes a **page → target query map** the team can edit. | Rules + DeepSeek + team | C2, C3 | DeepSeek | per version |
| C6 | SERP Capture | Per query, dated, India: organic top 10 and Places (Serper); AI Overview with references, PAA, featured snippet and knowledge graph on the top 8 queries (SerpAPI). Uncaptured features are recorded as "not captured", never "absent". See [09](09-provider-findings.md). | Serper + SerpAPI | C5 | Serper credits + ≤8 SerpAPI searches | 7 days |
| C7 | Question Library | De-duplicated questions with source label (`observed-autocomplete`, `on-site`, `framework-generated`), topic, and journey stage (discover / evaluate / plan / book / manage). Observed questions come from India autocomplete expansion (seeds × what/how/is/can/which/best/why/when) and SerpAPI PAA (`observed-paa`). Includes prompt-set topics as a source. | Serper autocomplete + C6 PAA + C2 + archetype question bank + DeepSeek | C2, C3, C5, C6 | Serper + DeepSeek | per snapshot |
| C8 | Competitor Capture | Competitor domains classified as `direct`, `aggregator`, `directory` or `publisher`; raw HTML of up to 3 competitors × 3 matched pages, respecting their robots.txt | C6 + fetch | C6 | Free | 7 days |
| C9 | Prompt Set | Versioned AI prompt portfolio labelled `observed` (from PAA/related), `archetype-template`, `brand` ("What is X?") or `speculative` (DeepSeek-generated) | C3, C4, C6 + DeepSeek | C3, C4 | DeepSeek | per version |
| C10 | AI Answer Capture | Raw answers per prompt × surface, with timestamp, model, prompt version and any cited URLs. Surfaces: **Google AI Overview** (from C6's SerpAPI capture, real), **DeepSeek knowledge probe**, **Groq knowledge probe**, **simulated AI search** (India top results + fetched page text → DeepSeek answers with citations, proxy). Two samples per prompt to show variance. Every answer carries its surface label. | DeepSeek, Groq, Serper | C9 | DeepSeek + Groq + Serper | 7 days |
| C11 | Performance Capture | PageSpeed Insights lab results + CrUX field data (mobile) for up to 5 template-representative URLs | Google PSI API | C2 | Free Google key | 7 days |
| C12 | Entity Footprint | Wikipedia/Wikidata entries, brand presence on archetype platforms via Serper `site:` searches. Knowledge Graph via 1 SerpAPI brand search. | Serper + SerpAPI + Wikipedia/Wikidata APIs | C3, C4 | Serper + 1 SerpAPI | 7 days |

Collector notes:

- **Page sampling (C1):** homepage first, then sitemap URLs and navigation links, picked so each page template is represented before any template repeats. Default cap 25 pages, configurable per run.
- **Politeness:** the client site is crawled with the client's permission at up to 2 requests per second. Competitors are crawled at 1 request per second and only where their robots.txt allows it.
- **Retrieval and de-duplication:** heavy embedding models don't fit in serverless functions, so passage retrieval uses Postgres full-text search (BM25-style ranking) with a DeepSeek re-rank of the top candidates. Question de-duplication uses fuzzy string matching first; for semantic de-duplication, the free `gte-small` embedding model built into Supabase Edge Functions writes vectors to `pgvector`.
- **Labels:** every model-generated item (prompts, questions, extracted facts) carries a provenance label, so reports never present a generated idea as observed demand.

## Diagnosis agents

Each agent lists the evidence it reads. None reads another agent. "Readiness" shows whether the agent's checks count toward its pillar's readiness score (see the matrix). Benchmark and observation agents report what they saw instead of scoring the site.

### SEO pillar

| ID | Agent | The question it answers | Reads | Signature output | Readiness |
|---|---|---|---|---|---|
| S1 | Crawl & Index Health | Can search engines reach, crawl and index the right pages? | C1, C2 | Indexability table per URL | Yes |
| S2 | Page Experience | Is the site fast and stable on mobile? | C11, C2 | CWV table per template (field vs lab) | Yes |
| S3 | Search Metadata | Do titles and descriptions represent each page accurately and win the click? | C2, C4, C5 | Current vs proposed title/description per page | Yes |
| S4 | On-Page Content Quality | Does each page satisfy the intent of its target query? | C2, C5, C6, C8 | Intent-match and subtopic-gap table per page | Yes |
| S5 | Keyword Themes & Cannibalization | Which search themes exist, which page owns each, and where do pages compete? | C2, C5, C6 | Cluster → page-role map | Yes |
| S6 | SERP Landscape & Competitors | Who wins these searches, with what kind of pages? | C6, C8, C2 | Dated competitor comparison per query | No (benchmark) |
| S7 | Internal Linking | Are important pages well linked with descriptive anchors? | C2 | Sample link graph + link suggestions | Yes |
| S8 | Structured Data | Is the JSON-LD valid, complete, appropriate and truthful? | C2, C4, C3 | Schema inventory + corrected JSON-LD | Yes |
| S9 | Local & Entity Consistency | Are name, address, phone and locations consistent across the site, the schema and the Google Maps listing? | C2, C4, C6 (Maps) | NAP consistency grid | Yes |
| S10 | E-E-A-T & Trust | Does the site show who is behind it and meet the trust and disclosure expectations of its archetype? | C2, C4, C3 | Trust and disclosure checklist | Yes |

### AEO pillar

| ID | Agent | The question it answers | Reads | Signature output | Readiness |
|---|---|---|---|---|---|
| A1 | Answer Coverage & Drafts | For each real question, does the site contain a complete, accurate answer? | C7, C2, C4 | Question × verdict table + answer drafts + fact checklist | Yes |
| A2 | Answer Structure & Snippet Eligibility | Are existing answers formatted so a search engine can lift them? | C2 | Passage-level formatting fixes | Yes |
| A3 | Journey Coverage | Does the site serve every stage of the customer journey? | C7, C2, C3 | Stage coverage matrix | Yes |
| A4 | Snippet & PAA Opportunities | Which featured snippets and People Also Ask boxes can the client realistically win? | C6, C2 | Opportunity table (holder, format, client eligibility) | No (opportunity) |

A4 covers the top 8 queries captured through SerpAPI each full run (see [09](09-provider-findings.md)).

### GEO pillar

| ID | Agent | The question it answers | Reads | Signature output | Readiness |
|---|---|---|---|---|---|
| G1 | AI Crawler Access & Readability | Can AI crawlers reach the site and read its content without JavaScript? | C1, C2 | Crawler access map + raw vs rendered parity | Yes |
| G2 | Citable Facts & Evidence | Do pages contain specific, first-hand, sourced facts worth quoting? | C2, C4 | Fact-density and distinctiveness per page | Yes |
| G3 | AI Share of Voice | How often do AI answers mention the brand vs competitors? | C10, C4, C8 | Mention matrix per surface | No (observation) |
| G4 | Citation Sources | Which URLs and domains do Google AI Overviews cite (real), which ranking pages does a model choose (proxy), and which URLs do models print from memory? | C10 | Cited-domain table (client / competitor / third party), labelled real, proxy or printed | No (observation) |
| G5 | AI Brand Accuracy | Is what AI says about the brand correct, current and specific? | C10, C4 | Fact-by-fact accuracy table | No (observation) |
| G6 | Off-site Entity Footprint | Is the brand present and consistent on the sources AI systems rely on? | C12, C2, C4 | Platform presence grid | Yes |

### Boundaries: who owns what

These are the checks most likely to be claimed twice, and which agent owns each.

| Topic | Owner | Not owned by |
|---|---|---|
| Canonical, noindex, robots.txt for search engines | S1 | G1 |
| robots.txt and firewall behaviour for AI crawlers | G1 | S1 |
| Raw vs rendered content (JavaScript dependency) | G1 | S1, S4 |
| Title, meta description, Open Graph | S3 | S4 |
| H1 and heading hierarchy | S4 | A2 |
| Question-style headings and answer-first openings | A2 | S4 |
| Snippet controls (`nosnippet`, `max-snippet`) | A2 | G1 |
| Contact details consistency (NAP) | S9 | G2, S10 |
| Other brand facts consistency (stats, claims) | G2 | S9 |
| Presence of contact page and grievance details | S10 | S9 |
| AI Overview citations | G4 | A4 |
| Featured snippets and PAA | A4 | G4 |
| Journey CTAs between stages | A3 | S7 |
| Link graph health (orphans, depth, anchors) | S7 | A3 |

## Action agent (on demand)

| ID | Agent | Trigger | Reads | Output |
|---|---|---|---|---|
| X1 | Content Brief | A team member picks a work-queue item (a missing page, a theme gap, an unanswered question cluster) in the dashboard | Snapshot evidence (C2, C4, C6, C7, C8) + the selected item | Writing plan: goal, audience, target queries, outline, questions to answer, verified facts to use, missing facts, internal-link ideas, competitor notes |

X1 is never part of a diagnosis run, so briefs are only produced for work the team has chosen.
