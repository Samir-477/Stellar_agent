# 1. Review of the 24 Agents

## Verdict

The 24 agents are strong on intent. They insist on evidence, dates, and honest limits ("not a measure of actual recommendations", "printed links alone do not establish citations"), and that discipline is kept everywhere. There are four structural problems:

1. **Hidden chains.** Nine agents cannot run unless another agent ran first. That breaks individual runs and means one failure cascades.
2. **Data gathering mixed with diagnosis.** Question Discovery (10) and AI Query Discovery (17) collect data rather than diagnose anything, and AI Mention (18) both collects AI answers and analyses them.
3. **Aggregators disguised as agents.** AEO Opportunity (16), GEO Opportunity (24) and FAQ Intelligence (13) only merge other agents' results. Merging is the intelligence layer's job.
4. **Gaps.** Nothing covers Core Web Vitals, E-E-A-T and trust (critical for loans, a YMYL category), featured snippets and People Also Ask, citable facts, or the brand's presence on third-party sites that AI systems rely on.

## The independence contract

Every agent in the new design follows these rules. They are enforced in code, not left to convention.

1. An agent reads only the **evidence snapshot**, the **client profile**, and its **archetype rule pack**.
2. An agent never reads another agent's findings. The `AgentContext` object passed to an agent has no method that returns findings.
3. Shared data gathering happens in **collectors**, which run before agents and produce data, never judgments.
4. Merging, de-duplicating and ranking across agents happens only in the **intelligence layer**.
5. Shared logic, such as matching brand names in text or retrieving the passage most relevant to a question, lives in **shared libraries** that any agent can call. A library is code, not an agent, so it creates no run-order dependency.
6. Every check has **exactly one owner agent** (see the matrix), so two agents never report the same issue. The intelligence layer still de-duplicates as a safety net.

In practice, instead of "Answer Gap waits for Question Discovery", Answer Coverage reads the Question Library from the snapshot. The orchestrator makes sure that data exists, collecting it if needed, before the agent starts.

## Dependency chains removed

| Chain in the original set | Why it's a problem | New design |
|---|---|---|
| 10 → 11, 12, 13, 14, 16 | Five agents can't run without Question Discovery | Question Discovery becomes the **Question Library collector** (C7). 11 + 12 merge into **A1 Answer Coverage & Drafts**. 14 becomes **A3 Journey Coverage**, with intent labels added by the collector. 13 and 16 move to the intelligence layer. |
| 17 → 18 → 20, 21 | A three-deep chain; a failed probe kills three agents | Prompt generation becomes the **Prompt Set collector** (C9). Sending prompts and saving answers becomes the **AI Answer Capture collector** (C10). 18 + 21 merge into **G3 AI Share of Voice**, and 20 becomes **G4 Citation Sources**. All read saved answers from the snapshot. |
| 22, 23 → 17/18 | Needed the prompt set and the saved answers | 22 becomes **G5 AI Brand Accuracy** and reads C10. 23's topic coverage folds into **A1**, which treats prompt-set topics as one of its question sources. |
| 5 → 7, 8, 12 ("confirmed facts") | Metadata, briefs and rewrites needed Local & Entity's extracted facts | Fact extraction becomes the **Fact Sheet collector** (C4). Every agent that writes copy uses only facts from it. |
| 3 → 2 ("target topic") | On-Page Content needed Keyword Themes' page roles | The **Query Set collector** (C5) stores a page-to-target-query map that the team can edit. S5 Keyword Themes may *recommend* changing that map; it never feeds S4. |
| 16, 24 | Pure mergers of other agents' output | Intelligence layer: sections "What to fix first", "Root causes & patterns" and "Action plan & blocked work". |
| 8 → 3, 4, 5, 10 | A brief needs a chosen topic plus research | **X1 Content Brief** becomes an on-demand action agent. You trigger it from an item in the intelligence report's work queue, and it reads evidence directly. It is not part of diagnosis runs. |

## Agent-by-agent decisions

| # | Original agent | Decision | New ID | Refinement |
|---|---|---|---|---|
| 1 | Technical SEO Auditor | Keep, narrowed | S1 Crawl & Index Health | Titles move to S3 and headings to S4, so each check has one owner. Adds soft-404, duplicate URL variants and HTTPS checks. |
| 2 | On-Page Content | Keep | S4 On-Page Content Quality | Target query comes from the C5 page map. Thin content is judged against the pages that rank, not a fixed word count (Google: there is no target word count). |
| 3 | Keyword & Search Theme | Keep | S5 Keyword Themes & Cannibalization | Adds cannibalization detection. States clearly that the providers give demand *signals* (India autocomplete, PAA, organic results), not search volumes. |
| 4 | SERP Competitor | Keep | S6 SERP Landscape & Competitors | Separates direct competitors from aggregators and directories (MakeMyTrip, BankBazaar, JustDial), which need a different response. |
| 5 | Local & Entity | Keep, split | S9 Local & Entity Consistency | Fact extraction moves to C4. Adds the Google Maps listing via Serper Places and doorway-page risk on location pages. |
| 6 | Internal Link Architect | Keep | S7 Internal Linking | Results are labelled as a *sample graph* (25 pages by default), not the full site. |
| 7 | Search Metadata | Keep | S3 Search Metadata | Owns title, meta description, Open Graph and title-rewrite risk. Drafts must pass length and fact checks. |
| 8 | Content Brief | Move | X1 Content Brief (on-demand) | Triggered from a work-queue item; not a diagnosis agent. |
| 9 | Schema & Structured Answers | Keep | S8 Structured Data | Adds archetype schema types, deprecated/retired types, the review-markup policy and `@id`/`sameAs` linking. Never recommends FAQPage for search benefit (retired May 2026). |
| 10 | Question Discovery | Becomes a collector | C7 Question Library | Keeps observed and framework-generated questions separate, as you specified. |
| 11 | Answer Gap | Merge with 12 | A1 Answer Coverage & Drafts | One agent finds the verdict and, where supported, drafts the fix. The pair never splits. |
| 12 | Answer Optimization | Merge with 11 | A1 | As above. For missing answers it produces a fact-gathering checklist, as you specified. |
| 13 | FAQ Intelligence | Move | Intelligence layer | Becomes the "topic coverage" view inside root causes. FAQ section formatting moves to A2. |
| 14 | Question Intent | Reshape | A3 Journey Coverage + intent labels in C7 | Intent labelling is data preparation. The diagnosis question becomes: does the site serve each stage of the journey? |
| 15 | Answer Structure | Keep | A2 Answer Structure & Snippet Eligibility | Adds snippet controls (`nosnippet`, `max-snippet`, `data-nosnippet`), which block both featured snippets and AI Overviews. |
| 16 | AEO Opportunity | Move | Intelligence layer | The AEO work queue is built there. |
| 17 | AI Query Discovery | Becomes a collector | C9 Prompt Set | Versioned per client so AI results stay comparable over time; speculative prompts stay labelled. |
| 18 | AI Mention | Split | C10 (capture) + G3 (analysis) | Capture is data; mention analysis is diagnosis. |
| 19 | AI Visibility | Keep | G1 AI Crawler Access & Readability | Adds fetching pages with AI crawler user agents to detect firewall blocks. llms.txt is reported for information only. |
| 20 | Citation Intelligence | Keep | G4 Citation Sources | Real citations come from Google AI Overview references (SerpAPI); simulated-search picks are reported separately as proxy. URLs printed by the DeepSeek/Groq knowledge probes are labelled "printed, unverified" and checked for whether they resolve. |
| 21 | Citation Gap | Merge with 18 | G3 AI Share of Voice | Brand and competitor mentions come from one pass over the same answers, with mentions and links kept separate as you specified. |
| 22 | Entity Authority | Keep | G5 AI Brand Accuracy | Compares AI-stated facts with the Fact Sheet: correct, outdated, wrong or unverifiable. Also checks specificity and entity confusion. |
| 23 | Content Authority | Merge | A1 (topic coverage) | Prompt topics become a question source for A1. The "covered / thin / absent" verdicts are kept. |
| 24 | GEO Opportunity | Move | Intelligence layer | The GEO work queue is built there. |

## New agents added

| New ID | Agent | Why |
|---|---|---|
| S2 | Page Experience | Core Web Vitals (LCP, INP, CLS), images and mobile basics. Nothing in the original set measured speed. |
| S10 | E-E-A-T & Trust | Authorship, policies and archetype disclosures. Essential for loans (YMYL) and for retail's e-commerce rules. |
| A4 | Snippet & PAA Opportunities | Uses the captured SERP to show which featured snippets and People Also Ask boxes exist, who holds them, and whether the client can win them. |
| G2 | Citable Facts & Evidence | Checks whether pages contain specific, first-hand, verifiable facts that AI systems can quote. Google says unique, non-commodity content is what matters. |
| G6 | Off-site Entity Footprint | Knowledge Graph, Wikidata and the India platforms each archetype depends on (for example MakeMyTrip for hotels, BankBazaar for loans). AI answers draw heavily on third-party sources. |

## Result

24 agents become **20 independent diagnosis agents**, **12 collectors**, **1 on-demand action agent**, and an **intelligence layer** that absorbs the three aggregators. Every agent can run alone, in any order, and one agent's failure never blocks another.
