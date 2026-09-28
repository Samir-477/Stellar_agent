# 11. Build Status and Verification (2026-09-27)

Verified end to end on a live client page: `https://www.sterlingholidays.com/resorts-hotels/regalia-agra` (hospitality).

## Built and verified

| Layer | Components | Verified how |
|---|---|---|
| Evidence | C1 Crawler, C2 Parser, C3 Archetype, C4 Fact Sheet, C5 Query Set, C6 SERP Capture, C7 Question Library, C9 Prompt Set, C10 AI Answer Capture, C8 Competitor Capture, C11 Performance Capture, C12 Entity Footprint | Live on the client site; C1–C4 also golden/unit tests |
| Agents | All 20: S1–S10, A1–A4, G1–G6 | Live runs reviewed finding by finding; golden tests with planted issues |
| Orchestrator | Task graph, Postgres queue with leases, snapshot reuse, archetype gate, inline runner | DB integration test + live runs (23 tasks per full run) |
| Intelligence | Readiness, de-duplication, cross-agent corroboration (same missing facts → one item), priority waves, root causes, observations block, LLM summary with cited ids | Live on the 20-agent run; the summary names the top observation and picks a gap, not a strength, as the opportunity |
| Output | Patch placement (incl. link inserts), annotated/fixed pages, under-the-hood view, share links | Live; 22/22 proposed changes placed on the Batch 1 combined run; security headers checked |

## Prompts in use (versioned in `engine/llm/prompt_files/`)

c3.archetype@v1, c4.facts@v2, c5.queries@v1, c7.questions@v2, s3.metadata@v2, a1.coverage@v2, a2.sections@v1, g5.claims@v2, g5.verify@v1, c10.probe@v1, c10.simulated_search@v1, s7.links@v1, s10.trust@v2, g2.facts@v2, g2.verify@v1, s4.content@v2, a3.journey@v2, s5.themes@v3, g3.mentions@v1, c8.domains@v1, intel.summary@v3.

## Differences from the design (sections 2–10)

| Area | Design | Built | Why |
|---|---|---|---|
| Queue | pgmq | The `tasks` table is the queue (row locks + leases) | Plain Postgres; portable; no extension |
| Intelligence | Full runs only | Any run with 2+ agents | Useful for partial runs and verification |
| Severity escalation | One level up on key pages | Capped at high; critical only when a check detects a blocking condition | Escalation produced "critical" for non-blocking issues |
| FAQPage / llms.txt | Info only | As designed | — |
| DeepSeek fast tier | — | `thinking` disabled for extraction/classification | Reasoning models spent the whole token budget thinking and returned nothing |
| G5 "wrong" verdicts | Single model | Confirmed by a second model family (Groq) | 4 of 8 "wrong" claims were over-strict |
| C6 | One task | One task per query; already-captured queries skipped | A timeout retry re-bought the same searches |
| A1 retrieval | Postgres full-text | In-process BM25 over sections, heading words ×3 | Headings are the best signal; fits serverless |
| S7.05 | Links to 4xx/redirects | Links to redirects only | Links to 4xx/5xx are S1.01 (reported with their source pages): no double reporting |
| S10.03 | D+L | Deterministic: JSON-LD `author`, meta author, visible "By <Name>"; reviewer on loans | Author bios aren't assessed yet |
| S4.06 | Compared with the ranking median | Fixed thresholds (150 own words; mostly template when under 100 and under 30% of the main content) | Competitor pages come with C8 |
| S4.07, S4.09 | D+L | Deterministic only (past-year offers, undated priced offers; repeated phrases) | The rules were enough on the live site; no LLM call needed |
| S4 target query | From the page-to-query map | The mapped query if it isn't the brand name, else the first non-brand query with results (reported as inferred; mismatch capped at warn) | C5 maps the entry page to the brand query |
| Critical tools (A3.02) | Free-text list per pack | `CriticalTool(key, label, stage, controls, links, text, jsonld)`; every pack also has its book-stage tool (booking, apply, cart, pickup) | A3.03 needs to know what "on to the book stage" means per archetype |
| A4.02 | S+L | Deterministic: PAA holder from SerpAPI; "answered" = a question heading sharing 60%+ of the words | No LLM needed; Google now answers most PAA with AI text and no source page |
| S5 clustering | Token overlap / SERP URL overlap | Word overlap on topic words, with place and generic words removed; place-only searches form their own themes | Shared place words ("taj mahal agra") merged unrelated topics. Synonyms ("budget"/"cheap") stay separate |
| G3.05 stability | Agreement across 2 samples per prompt | Agreement across surfaces for the same prompt | C10 takes one sample per prompt per surface (cost) |
| G4.03 printed URLs | Checked by the agent | Checked by C10 at capture (HEAD, GET fallback, SSRF guard, max 10) | Agents only read evidence; no network in agents |
| G4.04 traits of cited pages | M+L | Unverifiable until cited pages are fetched (C8) | Titles and domains alone can't show format or schema |
| C11 / S2 | Lighthouse audits by classic names | Lighthouse 13 "insight" audits (lcp-breakdown, lcp-discovery, image-delivery, render-blocking), classic names as fallback | PageSpeed now runs Lighthouse 13 |
| S2.05 | Info check | Reported as context; `counts_toward_readiness=False` | An always-passing check shouldn't raise readiness |
| C12 platforms | Serper `site:` search per platform | The C6 brand search first (free), then "name city platform" matched by the platform's name on any TLD | tripadvisor.in missed the .com listing; all 5 Sterling listings came from C6 at no cost |
| C12 Wikidata | Always checked | Needs `WIKIMEDIA_CONTACT` (email or URL) in the User-Agent; skipped and reported otherwise | Wikimedia returns 403 without contact details |
| C8 page choice | Up to 3 matched pages per competitor | Pages ranking for the client's highest-priority searches first (C5 priority) | Best-position pages were a rival's banquet and dining pages, not like for like |
| Priority | severity × confidence × reach × key-page boost ÷ effort | Adds fail 1.0 / warn 0.6 and an entry-page boost (×2.5, key pages ×1.5); a separate `harm` score (no effort) | Warnings ranked like failures; a 2-page issue elsewhere tied an entry-page failure |
| Summary headlines | Chosen by the model | Lead blocker (most severe, then most harm), lead opportunity (corroborated facts item, else the largest root cause) and lead observation chosen by rule; the model only phrases them (v3) | The model named "4 unclear titles" the biggest blocker and a strength the biggest opportunity |
| Summary digest | Top 15 items | Top 12 scored items plus a separate block of the top 4 observations | Observations (G3, G4) ranked outside the top items, so the summary never saw them |
| `missing_facts` | Free use | Only information the client must provide; items reporting the same facts are merged and listed as facts to supply | Actions ("a presence on booking.com") showed up as "blocked: needs …" |
| Runner | Uncaught errors ended the process | Task setup inside the error handling; `run_inline`/`worker_loop` survive a failure to record, back off, stop after 5 in a row; pool checks connections | A dropped Supabase connection once killed a run silently |
| S10 trust items | Free-text list per pack | `TrustItem(key, label, kind, core, facts)` in `rules/packs.py`; `kind` picks the check (S10.05/.06/.07/.08), `core` absent → fail | Checks stay archetype-agnostic |

## Lessons from the live verification (each fixed and covered by a test)

- Footer links counted as key pages → a false **critical** (robots.txt blocking /privacy-policy).
- A shared booking widget made unrelated pages look like duplicates → template-aware comparison.
- JSON-LD extraction took every `name` as the business name → business entities only; schema facts are claims, never ground truth.
- Schema on the Agra page described the Ayodhya property → S8 compares the entity with the page's subject (title, H1, opening).
- Homepage promo banner misled title suggestions → prompt v2 judges pages by H1/headings and page type.
- Autocomplete prefixes produced junk ("…agrabah") → seeds with a trailing space; brand seeds without question words; LLM rewrites or rejects each query.
- Several inserts in one section shifted XPaths → patch targets are resolved before any change is applied.
- Five similar Q&A drafts on one section → one draft per section.
- S7.07 counted the nav link as an existing link, so no suggestions → only body links count.
- The parser dropped `<footer>` text, where policies and registration numbers live → a false **fail** for Sterling's cancellation policy (a footer modal) → `footer_text` kept for trust checks.
- Values filled in by JavaScript (`{{cancelRulesSorted…}}`, `{{fullAddress…}}`) → masked as "[…]" and judged partial, with the reason in the evidence.
- Cloudflare email protection hid every email ("[email protected]") → the parser decodes `data-cfemail`.
- `href="#"` links (JavaScript modals) looked like policy pages → links to the page itself are ignored.
- Minified HTML glued words across elements ("loanBy Priya") → block elements are separated.
- G2 judged only the first 450 words of a page and called a page with named client testimonials "commodity content" → text is sampled from every section, top to bottom.
- G2 accepted a sub-brand tagline as the homepage's definition of the business → a definition must name the business and be a phrase (5+ words), and the prompt says a slogan is "implied".
- G2 asked for a source for the brand's own count ("65+ destinations") → own counts aren't claims (v2).
- S4 called a page "mostly template" when its text sat in `<div>`s → own text = main content minus template passages.
- S4 flagged the brand tagline on every resort card ("A Sterling Holiday Resort" ×53) and card copy ("…customers: Avail a flat…") as keyword stuffing → phrases inside the business name, and phrases repeated in identical wording, are skipped.
- S4 read card labels without full stops as one long sentence → sentence length counts prose only.
- A3 passed the booking tool because the widget's HTML existed on another page, while the entry page's link went to a page where it loads with JavaScript → a tool counts only where the link actually goes.
- A3 took a membership price on another page as this property's rates → information tools are judged on the entry page.
- A3's section list filled up with empty tab headings, so the model said rooms were missing → sections with text first; empty headings grouped on one line.
- S5 merged pet-friendly, banquet and pool-view searches into one theme through shared place words → clustering ignores place words.
- The business name "Sterling Regalia Agra" made "agra" a brand word, so every Agra search looked like a brand search (and S4 couldn't see location stuffing) → brand words exclude places from the Fact Sheet.
- S5 owners flip-flopped between runs; the model gave the property page themes it doesn't offer (budget, 5-star, private pools) → an owner must mention the theme's topic words, section hints need all of them.
- S5 called a hotel page "mixed intent" for describing what it sells → v2 defines mixed narrowly; the homepage is a hub and isn't judged.
- Brand words were computed minus address words; the (wrong-entity) schema address "Sterling Rampath" removed "sterling", and S4 flagged the brand tagline as stuffing again → addresses don't count as places.
- The lead blocker went from quick wins (titles) to a 22-page medium template issue before settling: priority (harm per effort) orders the work list; the blocker is the most severe, then most costly, issue.
- A run died silently mid-way: task setup and result recording were outside the error handling, and nothing caught failures in the runner loop → guarded, logged, retried via lease expiry.
- og:image came out as the same site-wide banner on every page (from the organisation's JSON-LD) → the page's own first content image, JSON-LD only as a fallback and never the organisation's.
- The parser dropped lazy-loaded images (`data-src` without `src`), so the Agra hero was invisible → recorded with the real URL and a `lazy` flag; tracking pixels and template images are skipped.
- A C12 part skipped for missing configuration was treated as done forever → skipped parts rerun once configured.
- C10 kept a sentence's full stop as part of printed URLs, which would mark real links broken → trailing punctuation stripped.
- G3 counted "ITC Mughal" and "ITC Mughal, A Luxury Collection Hotel" as two competitors → names merge when one starts with the other.
- S4 named a subtopic too narrowly ("rooftop or infinity pool") and missed the page's "fourth-floor swimming pool" → v2 names subtopics as the need behind them.

## Known limitations

- S10.07: a testimonial whose name follows it as a heading (`<p>quote</p><h3>Name</h3>`) is read as unattributed; the verdict (undated → partial) is still right.
- S7 works on the sample graph (25 pages): absence findings are worded "in the sample" with matching confidence.

## Not built yet

The Node renderer (rendered HTML for G1.03/G1.04); the Next.js dashboard (UI to come from the user); Vercel HTTP runner verification; patch review API; retention job; Batch 4 hardening (docs/spec/12).
