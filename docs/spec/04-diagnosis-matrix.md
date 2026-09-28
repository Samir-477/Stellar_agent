# 4. Diagnosis Matrix

## Rating system (shared by all agents)

### Check result

| Result | Meaning |
|---|---|
| `pass` | Meets the standard |
| `warn` | Partly meets it, or meets it with a risk |
| `fail` | Doesn't meet it |
| `not_applicable` | Doesn't apply to this site or archetype (e.g. local checks for an online-only lender) |
| `unverifiable` | The evidence needed is missing (e.g. no CrUX field data). Reported, never counted as pass or fail. |

### Severity (for `warn` and `fail`)

| Severity | Definition | Example |
|---|---|---|
| `critical` | Blocks crawling, indexing or AI access to key pages, or creates legal/compliance risk on a YMYL site | Homepage `noindex`; loan site with no grievance officer details |
| `high` | Significant loss of rankings, answers or citations on key pages | Duplicate titles across service pages; answers exist only in JavaScript |
| `medium` | Noticeable weakness on some pages | Missing Open Graph image; thin intro on a service page |
| `low` | Polish or best practice | Generic "read more" anchors |

Each check has a default severity. It escalates one level on **key pages** (homepage, top service/product/rate pages, booking/apply pages) and for loans checks marked YMYL.

### Confidence

| Confidence | Meaning | Rule |
|---|---|---|
| `confirmed` | Directly observed in evidence (a header, a tag, a status code) | Deterministic checks |
| `likely` | A judgment the LLM made from quoted evidence | Must quote the excerpt it relied on |
| `hypothesis` | An inference without direct evidence | Can never be `critical`; shown under "Needs attention" |

### Method codes used in the tables

`D` deterministic rule · `L` LLM judgment on quoted evidence · `S` derived from SERP captures · `M` derived from saved AI answers · `P` PageSpeed/CrUX data

### Pillar readiness score

Readiness is a transparent roll-up of the checks that count toward it. It is the platform's heuristic, not a Google signal, and the report says so.

```
readiness(pillar) = 100 × Σ (weight × value) / Σ weight      over applicable, verifiable checks
value: pass = 1, warn = 0.5, fail = 0
weight: critical-default checks 3, high 2, medium 1, low 0.5
cap: any critical fail → readiness capped at 49
coverage(pillar) = verifiable checks / applicable checks   (shown next to the score)
```

| Band | Score | Label |
|---|---|---|
| 0–49 | Blocked or poor | Fix critical issues first |
| 50–69 | Needs work | |
| 70–84 | Solid | |
| 85–100 | Strong | |

Only agents marked "Readiness: Yes" in the catalog contribute. The benchmark and observation agents (S6, A4, G3, G4, G5) are reported as **observations**, e.g. "brand mentioned in 3 of 15 Google AI Overview answers on 2026-09-27". They are never blended into a score, because they are dated samples, not properties of the site.

Page-level checks roll up per check as the share of sampled pages that pass (≥90% pass → `pass`, 60–89% → `warn`, <60% → `fail`), with any key-page failure listed individually.

---

## SEO pillar

### S1 Crawl & Index Health

| ID | Check | Pass | Warn | Fail | Sev | Method |
|---|---|---|---|---|---|---|
| S1.01 | HTTP status of sampled and linked URLs | All 200 | — | Any 4xx/5xx on a linked or sitemap URL | high (critical if homepage) | D |
| S1.02 | Soft 404s | None | — | 200 response with "not found"/empty main content | medium | D+L |
| S1.03 | Redirect chains | ≤1 hop, 301/308 | 2 hops, or 302 for a permanent move | ≥3 hops or a loop | medium | D |
| S1.04 | Indexability directives (meta robots, X-Robots-Tag) | Key pages indexable | Non-key page `noindex` while listed in sitemap | Key page `noindex` | critical on key pages | D |
| S1.05 | robots.txt for search engines | Reachable; key pages, CSS and JS allowed | Unreachable (5xx) or overly broad rules | Blocks key pages or render resources | critical | D |
| S1.06 | Canonical tags | Self-referencing or intentional, absolute, to a 200 indexable URL | Missing | Points to a non-200, redirect, noindex or unrelated page; conflicts with sitemap | high | D |
| S1.07 | XML sitemap | Exists, valid, in robots.txt, only 200 canonical URLs | Not in robots.txt; stale `lastmod` | Missing, invalid, or ≥10% non-200/non-canonical URLs | medium | D |
| S1.08 | URL variants resolve to one version | http/https, www/non-www, trailing slash all consolidate | One variant duplicates | Several variants serve duplicate 200s | high | D |
| S1.09 | Duplicate / near-duplicate pages in sample | None | Near-duplicates (>85% similar main content) | Exact duplicates without canonical | high | D |
| S1.10 | HTTPS and mixed content | HTTPS everywhere, no mixed content | Passive mixed content (images) | Active mixed content (scripts) or HTTP key pages | high | D |
| S1.11 | `html lang` attribute | Present and correct (`en`/`en-IN`) | Missing | Wrong language | low | D |

### S2 Page Experience

Uses CrUX field data (75th percentile, mobile) when available. Otherwise it uses lab data, marked `likely`.

| ID | Check | Pass | Warn | Fail | Sev | Method |
|---|---|---|---|---|---|---|
| S2.01 | LCP | ≤2.5 s | 2.5–4.0 s | >4.0 s | high | P |
| S2.02 | INP (field) / TBT (lab proxy) | INP ≤200 ms (TBT ≤200 ms) | 200–500 ms (TBT 200–600) | >500 ms (TBT >600) | high | P |
| S2.03 | CLS | ≤0.1 | 0.1–0.25 | >0.25 | medium | P |
| S2.04 | TTFB | <800 ms | 800–1800 ms | >1800 ms | medium | P |
| S2.05 | LCP subpart diagnosis | Reported as context (TTFB, load delay, load duration, render delay) | — | — | info | P |
| S2.06 | Image hygiene | width/height set, WebP/AVIF, below-fold lazy, LCP image not lazy | 1–2 issues | Oversized (>200 KB) hero or LCP image lazy-loaded | medium | D |
| S2.07 | Mobile basics | Viewport meta, readable font sizes, tap targets | Minor Lighthouse flags | No viewport meta | medium | D+P |
| S2.08 | Render-blocking and JS weight | Within Lighthouse budgets | Moderate overage | Severe (Lighthouse "poor") | low | P |

### S3 Search Metadata

| ID | Check | Pass | Warn | Fail | Sev | Method |
|---|---|---|---|---|---|---|
| S3.01 | Title present and unique | Unique on every page | — | Missing or duplicated across pages | high | D |
| S3.02 | Title length | 30–60 chars | Outside range | — | low | D |
| S3.03 | Title relevance | Leads with the page's target query/topic; brand at end | Topic present but buried; generic | Doesn't describe the page | medium | L |
| S3.04 | Title vs H1 alignment (rewrite risk) | Consistent | Divergent | Boilerplate title reused while H1 differs | low | D+L |
| S3.05 | Meta description present and unique | Present, unique, 70–155 chars | Outside range | Missing or duplicated | low | D |
| S3.06 | Meta description accuracy | Matches page content and Fact Sheet | Vague | Claims facts not on page / not in Fact Sheet | medium | L |
| S3.07 | Open Graph / Twitter | og:title, og:description, og:image (absolute, ≥1200×630), og:url = canonical | Partial | None | low | D |

Patches: 2–3 title and description options per failing page. Each passes the length and fact checks.

### S4 On-Page Content Quality

| ID | Check | Pass | Warn | Fail | Sev | Method |
|---|---|---|---|---|---|---|
| S4.01 | Single descriptive H1 | One H1 matching page intent | Generic H1 | Missing or multiple competing H1s | medium | D+L |
| S4.02 | Heading hierarchy | Logical outline | Skipped levels / headings used for styling | No structure in long content | low | D |
| S4.03 | Intro answers the page intent | Intent addressed in the first ~100 words | Partially | Intro is filler | medium | L |
| S4.04 | Intent match with the SERP | Page type matches the dominant result type for its target query | Mixed | Mismatch (e.g. product page for an informational query) | high | S+L |
| S4.05 | Subtopic coverage | Covers subtopics present in ≥2 of the top 5 results | Misses 1–2 | Misses most | medium | S+L |
| S4.06 | Thin or boilerplate content | Main content comparable to the ranking median | Well below median | Mostly template boilerplate | medium | D+S |
| S4.07 | Freshness | Rates, prices, years and offers are current | Undated time-sensitive content | Outdated rates/prices/years visible | medium (high for loans rates) | D+L |
| S4.08 | Readability | Short paragraphs and sentences | Dense sections | Wall-of-text key pages | low | D |
| S4.09 | Over-optimization | Natural language | Repetitive keyword use | Keyword stuffing | low | D+L |

### S5 Keyword Themes & Cannibalization

Demand signals come from India autocomplete, SerpAPI PAA and organic results. Neither provider gives search volumes, so clusters show observed demand, not traffic.

| ID | Check | Pass | Warn | Fail | Sev | Method |
|---|---|---|---|---|---|---|
| S5.01 | Every observed theme has one owner page | All mapped | Some themes unmapped (proposed new page needs inventory review) | Core archetype themes unmapped | medium | S+L |
| S5.02 | Cannibalization | No overlap | Two pages partly overlap | ≥2 pages target the same cluster (titles/H1s + SERP) | high | D+S+L |
| S5.03 | Page role clarity | One primary intent per page | Secondary intent diluting | Mixed informational + transactional intent | medium | L |
| S5.04 | Local modifiers | City/area themes covered where the business has locations | Partial | Missing for key locations | medium | S |
| S5.05 | Recurring unaddressed themes | None | Themes seen ≥2 times in SERP data but absent sitewide | — | medium | S |

### S6 SERP Landscape & Competitors (benchmark, not scored)

| ID | Observation | What's reported | Method |
|---|---|---|---|
| S6.01 | Client visibility | Position in top 10 / local pack / absent, per query, location and date | S |
| S6.02 | Competitor classification | Direct competitors vs aggregators, directories and publishers | S+L |
| S6.03 | SERP feature map | AI Overview, PAA, snippet and local results (present, and who holds them) on the SerpAPI-covered queries; organic and local for the rest (see §9) | S |
| S6.04 | Structural gaps | Schema types, page types and trust elements present on ≥2 of the top 3 competitor pages but missing from the client's mapped page | D+S |
| S6.05 | Depth comparison | Main-content size and section count vs competitor median | D |

S6.04 gaps are emitted as `warn` findings (medium) so they reach the work queue, but they don't count toward readiness.

### S7 Internal Linking (sample graph)

| ID | Check | Pass | Warn | Fail | Sev | Method |
|---|---|---|---|---|---|---|
| S7.01 | Pages without inlinks in the sample | None | Sampled page with 0 inlinks from other sampled pages (sample-based: may be linked from unsampled pages) | — | medium | D |
| S7.02 | Click depth | Key pages ≤3 clicks from home | 4 clicks | ≥5 clicks | medium | D |
| S7.03 | Contextual inlinks to key pages | Key pages not in the nav have body links from other pages | — | A key page not in the nav has no body links in the sample | medium | D |
| S7.04 | Anchor text | Descriptive | >30% generic ("click here", "read more") | Key pages only reached via generic anchors | low | D |
| S7.05 | Internal links to redirects | None | Links point at URLs that redirect | — | medium | D (links to 4xx/5xx are reported by S1.01 with their source pages) |
| S7.06 | Contextual linking | Body copy links related pages | Nav/footer-only linking | — | low | D |
| S7.07 | Link opportunities | — | Passages mention another page's topic without linking (patch: source, target, anchor, placement) | — | low | D+L |

### S8 Structured Data

| ID | Check | Pass | Warn | Fail | Sev | Method |
|---|---|---|---|---|---|---|
| S8.01 | JSON-LD syntax | Parses | — | Parse error | high | D |
| S8.02 | Required and recommended properties | All required + most recommended | Recommended missing | Required missing | medium (high if required) | D |
| S8.03 | Archetype-appropriate types | Present on the right pages (see archetype packs) | Partial | Missing Organization/WebSite, or missing the core archetype type | medium | D |
| S8.04 | Truthfulness: schema facts match visible content and Fact Sheet | Match | Minor drift | Name, address, phone, price or rating contradicts the page | high | D+L |
| S8.05 | Retired or deprecated types | None | FAQPage present (info only; don't remove just for this) | HowTo, SpecialAnnouncement or other retired types | low | D |
| S8.06 | Entity graph | `@id` links, `sameAs` to official profiles | Partial | Conflicting entities (two Organizations with different names) | medium | D |
| S8.07 | Review markup policy | Compliant | — | Self-serving review/rating markup on own Organization/LocalBusiness | medium | D |

Patches: corrected or new JSON-LD blocks. Never FAQPage or HowTo.

### S9 Local & Entity Consistency

`not_applicable` when the business has no physical locations or service areas.

| ID | Check | Pass | Warn | Fail | Sev | Method |
|---|---|---|---|---|---|---|
| S9.01 | NAP consistency | Name, address and phone identical across footer, contact, location pages, schema and the Maps listing | Formatting differences | Conflicting addresses or phones | high | D+S |
| S9.02 | Location pages | One unique page per location, with address, hours, map and local detail | Thin pages | City-swap doorway pattern | high | D+L |
| S9.03 | Google Maps listing | Found; category matches archetype; hours set; website links to the right page | Partial | Not found / wrong category | medium | S |
| S9.04 | Local pack presence | Observation per local-intent query | — | — | info | S |
| S9.05 | India contact formats | +91 numbers, `tel:` links, PIN code in addresses | Partial | Missing phone or PIN code on location pages | low | D |
| S9.06 | Service area stated | Cities, PIN codes or regions clearly listed | Vague | Absent (logistics, loans with branches) | medium | D+L |

### S10 E-E-A-T & Trust

| ID | Check | Pass | Warn | Fail | Sev | Method |
|---|---|---|---|---|---|---|
| S10.01 | About page | Real organization details (founding, leadership, registration) | Generic | Missing | medium | D+L |
| S10.02 | Contact page | Address, phone, email, support hours | Partial | Missing | high (YMYL: critical) | D |
| S10.03 | Authorship | Named authors with bios on guides and articles; reviewer credentials on financial content | Partial | Anonymous YMYL content | high on loans | D+L |
| S10.04 | Dates | Published/updated dates on articles and rate pages | Partial | Missing on rate/price pages | medium | D |
| S10.05 | Policies | Privacy and terms, plus archetype policies (see packs) | Some missing | Core policy missing (e.g. returns for retail, cancellation for hotels) | high | D+L |
| S10.06 | Archetype disclosures (compliance review) | All pack disclosures present | Some missing | Registration or grievance details absent | critical on loans; high elsewhere | D+L |
| S10.07 | Reviews and testimonials | Attributed and dated | Unattributed | — | low | L |
| S10.08 | Pricing and fee transparency | Fees and charges stated where the archetype expects them | Partial | Hidden or absent | high on loans | D+L |

S10.06 findings always say: "Flag for your compliance team; this is not legal advice."

---

## AEO pillar

### A1 Answer Coverage & Drafts

Question sources (from C7): `observed-autocomplete`, `observed-paa`, `on-site`, `framework-generated`, plus prompt-set topics. Verdicts are per question.

| ID | Check | Pass | Warn | Fail | Sev | Method |
|---|---|---|---|---|---|---|
| A1.01 | Observed questions answered | Complete answer in one passage | Partial | Missing | high | L (retrieval + judgment) |
| A1.02 | Framework-generated questions answered | Complete | Partial / missing | — | medium | L |
| A1.03 | Answer accuracy | Matches Fact Sheet | Unverifiable (fact not on file) | Contradicts Fact Sheet or is outdated | high | D+L |
| A1.04 | Topic coverage (prompt-set topics) | Covered | Thin | Absent | medium | L |

Verdict definitions: **complete** = direct, specific answer in one passage; **partial** = relevant but vague, incomplete or scattered; **missing** = no relevant passage; **unverifiable** = answering needs facts the site and Fact Sheet don't contain.

Outputs: a draft rewrite for each partial answer (passes the fact guard), and a fact-gathering checklist for missing and unverifiable answers.

### A2 Answer Structure & Snippet Eligibility

Google says not to chunk content artificially for AI, so these checks aim at clarity for readers, which is also what makes answers extractable.

| ID | Check | Pass | Warn | Fail | Sev | Method |
|---|---|---|---|---|---|---|
| A2.01 | Answer-first openings | Question-style sections open with a direct 40–60 word answer | Answer in the 2nd–3rd sentence | Answer buried or absent at the start | medium | D+L |
| A2.02 | Question-style headings | Used where content answers questions | Some | None on Q&A-shaped content | low | D+L |
| A2.03 | Self-contained passages | Subject named; no "as mentioned above" | Some dangling references | Most passages depend on context | medium | L |
| A2.04 | Format fit | Lists/steps/tables where the answer is list- or table-shaped (fees, eligibility, amenities, rates) | Partial | Tabular data in prose | medium | L |
| A2.05 | Paragraph length in answers | ≤4 sentences | Some long paragraphs | Walls of text | low | D |
| A2.06 | Q&A sections well formed | One question per heading, full answers present in HTML | Answers truncated | — | low | D |
| A2.07 | Snippet controls | No `nosnippet`/`max-snippet:0`/`data-nosnippet` on answer content | Restrictive `max-snippet` | Key answers blocked from snippets (also blocks AI Overviews) | high | D |

### A3 Journey Coverage

Journey stages: discover → evaluate → plan → book/apply/buy/ship → manage (labels per archetype pack).

| ID | Check | Pass | Warn | Fail | Sev | Method |
|---|---|---|---|---|---|---|
| A3.01 | Stage presence | Every stage has a page, section or tool | A stage is thin | A stage is absent | high (book/apply stage), medium otherwise | D+L |
| A3.02 | Critical stage tools (pack-defined, e.g. EMI calculator, booking engine, tracking) | Present and in HTML | Present but hard to find | Missing | high | D |
| A3.03 | Stage-to-stage paths | Clear CTAs from evaluate → book/apply | Weak CTAs | Dead ends | medium | D |
| A3.04 | Demand vs coverage | Stages with observed questions have content | — | Observed demand at a stage with no content | high | S+L |

### A4 Snippet & PAA Opportunities (opportunity, not scored; top 8 SerpAPI queries per full run)

| ID | Observation | What's reported | Method |
|---|---|---|---|
| A4.01 | Featured snippets | Per query: holder, format (paragraph/list/table), whether the client ranks top 10 and has a format-matched passage | S+D |
| A4.02 | People Also Ask | Which PAA questions the client answers vs who holds them | S+L |
| A4.03 | Format mismatch | Snippet format differs from the client's answer format → patch suggestion | S+D |

A4 opportunities where the client ranks top 10 are emitted as `warn` (medium) findings so they reach the work queue.

---

## GEO pillar

### G1 AI Crawler Access & Readability

| ID | Check | Pass | Warn | Fail | Sev | Method |
|---|---|---|---|---|---|---|
| G1.01 | robots.txt for AI search crawlers (OAI-SearchBot, ChatGPT-User, Claude-SearchBot, PerplexityBot) | Allowed | Partially blocked | All blocked | critical if all blocked, else high | D |
| G1.02 | robots.txt for training crawlers (GPTBot, ClaudeBot, Google-Extended, Applebot-Extended, CCBot) | Reported as the client's policy choice | — | — | info | D |
| G1.03 | Firewall/CDN response to AI user agents | Same response as a browser | Rate-limited / challenge page | 403 / block | high | D (confidence `likely`: some firewalls verify crawler IPs, which a user-agent test can't reproduce) |
| G1.04 | Main content in raw HTML | ≥90% of rendered main text present in server HTML | 50–89% | <50% | critical on key pages | D |
| G1.05 | Critical facts in raw HTML | Prices, rates, addresses, phones present server-side | Some only after JavaScript | Key facts only after JavaScript | high | D |
| G1.06 | llms.txt | Reported present/absent and well-formed. **Info only, zero weight**: Google ignores it and no major AI system has confirmed using it. | — | — | info | D |

### G2 Citable Facts & Evidence

| ID | Check | Pass | Warn | Fail | Sev | Method |
|---|---|---|---|---|---|---|
| G2.01 | Distinctive facts on key pages | Specific, verifiable facts (rates, amenities, coverage, timelines, counts) | Some | Generic marketing only | medium | L |
| G2.02 | First-hand, non-commodity content | Original data, local specifics, real examples | Some | Commodity content that could be about any competitor | medium | L |
| G2.03 | Source attribution | Stats and claims cite sources | Some unsourced | Key claims unsourced | low | L |
| G2.04 | Entity clarity | Brand and offerings explicitly named and defined on key pages | Implied | Brand never clearly defined | medium | L |
| G2.05 | Quotable passages (research heuristic, low weight) | Key pages have self-contained, fact-bearing passages (~50–200 words) | Few | None | low | D+L |
| G2.06 | Brand fact consistency | Same claims everywhere (founding year, counts, figures) | Minor drift | Contradictory figures | high | D+L |

### G3 AI Share of Voice (observation, not scored)

Each observation is labelled with surface, date and prompt-set version. Google AI Overview is labelled "observed"; the DeepSeek and Groq surfaces "model knowledge, no live search"; the simulated search surface "proxy". Results are always reported per surface, never pooled.

| ID | Observation | What's reported | Method |
|---|---|---|---|
| G3.01 | Brand mention rate | Prompts where the brand is named / total, per surface | M |
| G3.02 | Competitor mention rate | Same, per competitor; co-mentions | M |
| G3.03 | Prominence | First recommendation vs listed vs passing mention | M+L |
| G3.04 | Framing | Positive / neutral / negative context, with quote | M+L |
| G3.05 | Stability | Agreement across the 2 samples per prompt | M |

Emits `warn` findings (medium) where competitors are mentioned and the brand isn't, on observed or brand prompts.

### G4 Citation Sources (observation, not scored)

| ID | Observation | What's reported | Method |
|---|---|---|---|
| G4.01 | Client pages cited | Google AI Overview references pointing to the client, by page (real); simulated-search picks reported separately (proxy) | M |
| G4.02 | Cited domains | Competitor and third-party domains in AI Overview references, ranked by frequency (aggregators, news, forums) → listing/PR targets | M |
| G4.03 | Printed URLs (knowledge probes) | Labelled "printed, unverified"; each checked for whether it resolves (hallucinated-link flag) | M+D |
| G4.04 | Traits of cited pages | What cited pages share (format, schema, freshness) vs the client's mapped pages | M+L (`likely`) |

### G5 AI Brand Accuracy (observation, not scored)

| ID | Observation | What's reported | Method |
|---|---|---|---|
| G5.01 | Fact accuracy | Each AI-stated brand fact vs Fact Sheet: correct / outdated / wrong / unverifiable | M+L |
| G5.02 | Specificity | Distinctive facts vs generic description | M+L |
| G5.03 | Missing offerings | Services or locations the AI doesn't know about | M+L |
| G5.04 | Entity confusion | Brand mixed up with a similarly named company | M+L |

Emits `fail` findings (high) for wrong key facts or entity confusion, since those need action (fix site facts, profiles and third-party listings).

### G6 Off-site Entity Footprint

| ID | Check | Pass | Warn | Fail | Sev | Method |
|---|---|---|---|---|---|---|
| G6.01 | Knowledge Graph panel for brand query | Present and accurate | Present with errors | Absent | medium | S (SerpAPI) |
| G6.02 | Wikidata / Wikipedia | Wikidata entry exists and matches | Absent (info: don't create Wikipedia pages artificially) | Exists with wrong facts | low | D |
| G6.03 | Presence on archetype platforms (see packs) | Listed on the pack's core platforms | Some | None | medium | S |
| G6.04 | `sameAs` ↔ profiles | Schema `sameAs` matches profiles found; descriptions consistent | Partial | Conflicting profiles | medium | D+S |
| G6.05 | Brand query results | Reported: review sites and complaint threads in the top results | — | — | info | S |

Recommendations stay genuine: real listings and profiles, never manufactured mentions (Google explicitly warns against chasing inauthentic mentions).
