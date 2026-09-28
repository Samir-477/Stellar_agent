# Agent pipeline: current implementation and saved outputs

Reviewed against the current source on 28 September 2026. The examples below are from saved local artifacts, not invented sample results. The full 20-agent run is `02281b68-d724-4ea2-bf96-88278009a8ac` for Sterling Holidays – Regalia Agra. Its evidence snapshot was reused from an earlier crawl. The saved [run log](../.data/run_full20.log) records `completed`, 62 succeeded tasks, and 11,509 LLM tokens used. The saved [intelligence report](../.data/intel_full20.md) belongs to this run.

## The pipeline in plain language

```text
Client URL + permission to crawl
          ↓
12 collectors gather one dated evidence snapshot
          ↓
20 independent diagnosis agents inspect that evidence
          ↓
Validation checks their findings and proposed patches
          ↓
Intelligence merges the findings into priorities and readiness scores
          ↓
Output layer makes annotated and suggested-fixed page copies for review/sharing
```

The collectors are the research team. The agents are specialist reviewers. Intelligence is the editor who combines their reports. The output layer is the visual demonstration of proposed changes. An agent does not read another agent's result; all agents read the shared evidence snapshot through a read-only interface. This is enforced by [`AgentContext`](../engine/context.py), [`SnapshotReader`](../engine/store.py), and the task graph in [`planner.py`](../engine/orchestrator/planner.py).

### Where the rest of the code fits

The Python [`FastAPI app`](../engine/api/app.py) accepts clients and runs, exposes the agent catalog and reports, and serves the interim share viewer. [`api/index.py`](../api/index.py) is its deployment entry point. The Next.js [`src/app/`](../src/app/) currently provides the public site; [`next.config.ts`](../next.config.ts) forwards `/api/v1/*` to Python. [`supabase/migrations/`](../supabase/migrations/) defines clients, snapshots, pages, evidence, runs, queue tasks, findings, patches, reports and shares. Evidence rows live in Postgres; larger page/report artifacts use the compressed [`BlobStore`](../engine/core/blobstore.py), backed by local files or Supabase Storage. Shared parsing and check helpers are in [`engine/lib/`](../engine/lib/). The [`LLM client`](../engine/llm/client.py) supports off, fixture replay and live modes; live mode uses versioned prompts, a token budget, caching, DeepSeek with Groq fallback, and a circuit breaker. These models help selected extraction/judgment steps; the deterministic validation and scoring rules remain separate.

### What each collector contributes

| ID | Collector | Evidence saved |
|---|---|---|
| C1 | Site Crawler | Raw pages, robots/sitemap/llms.txt, URL variants, AI user-agent probes; rendered pages only if a renderer is configured. |
| C2 | Page Parser | Titles, headings, links, body text, JSON-LD, and other structured page fields. |
| C3 | Archetype Detector | Business type, such as hospitality, with a confirmation gate when needed. |
| C4 | Fact Sheet | Evidence-backed business facts used to ground later judgments and proposed copy. |
| C5 | Query Set | Target search queries and page-to-query mapping. |
| C6 | SERP Capture | Organic search results and available search features. |
| C7 | Question Library | Customer questions, their sources, and journey stages. |
| C8 | Competitor Capture | Ranking-domain types and sampled competitor pages. |
| C9 | Prompt Set | AI questions derived from the facts, archetype, and search evidence. |
| C10 | AI Answer Capture | Dated answers from configured AI surfaces and simulated search. |
| C11 | Performance Capture | PageSpeed field/lab metrics for sampled URLs. |
| C12 | Entity Footprint | Maps, listing, Knowledge Graph, and Wikimedia evidence where available. |

This list comes from the live [`registry.py`](../engine/registry.py) and collector classes, not the older build-status document. The planner selects only collectors required by the requested agents and reuses completed collectors in an existing snapshot when instructed. Each collector and agent is split into plan, short work units, and a completion barrier. Postgres tasks have leases and retries; after agent reductions, the intelligence task runs, then the run finalizes. See [`executor.py`](../engine/orchestrator/executor.py) and [`repo.py`](../engine/orchestrator/repo.py).

## The 20 agents and what they actually returned

Each “saved example” is a real line from the **full 20-agent run log**. It is one finding or observation, not a claim that the full report is stored locally. `A4`, `S6`, and `G3–G5` are dated observations and do not affect readiness scores. All other agents count toward their pillar when their checks apply.

| Agent | What it checks | Saved example from the full run |
|---|---|---|
| **S1 Crawl & Index Health** | HTTP errors, redirects, indexability, robots, canonicals, sitemap, HTTPS, language. | **Fail S1.01:** 2 sampled URLs return an error status. |
| **S2 Page Experience** | LCP, INP, CLS, TTFB, LCP image, zoom, scripts. | **Fail S2.03:** CLS was poor on 1 of 5 measured pages. |
| **S3 Search Metadata** | Unique and relevant titles/descriptions, title–H1 match, Open Graph. | **Fail S3.06:** 5 meta descriptions were vague, missing, or overclaimed. |
| **S4 On-Page Content Quality** | H1/heading structure, search intent, depth, readability, claims. | **Fail S4.01:** 1 key page had no H1. |
| **S5 Keyword Themes & Cannibalization** | Theme coverage, page ownership, competing pages, local demand. | **Fail S5.01:** 1 core theme and 6 other themes lacked a page. |
| **S6 SERP Landscape & Competitors** | Ranking position, competitor types/pages, search features, intent gaps. | **Attention S6.01:** absent from the top 10 for 7 non-brand searches. |
| **S7 Internal Linking** | Orphans, click depth, contextual links, anchors, redirected links. | **Attention S7.04:** 1 generic and 5 empty anchors among 28 body links. |
| **S8 Structured Data** | JSON-LD validity, appropriate schema, required properties, entity consistency. | **Fail S8.04:** structured data described a different business from the page. |
| **S9 Local & Entity Consistency** | On-site business identity and location details against outside evidence. | **Fail S9.01:** conflicting names and addresses in `LodgingBusiness` schema. |
| **S10 E-E-A-T & Trust** | Organization/contact details, policies, reviews, prices and fees. | **Attention S10.02:** contact page lacked an address. |
| **A1 Answer Coverage & Drafts** | Whether observed customer questions are answered and where gaps remain. | **Fail A1.01:** 4 observed questions unanswered and 5 only partly answered. |
| **A2 Answer Structure & Snippet Eligibility** | Question headings, direct answer openings, quotable sections, snippet controls. | **Attention A2.02:** 7 key pages lacked question-style headings. |
| **A3 Journey Coverage** | Content and tools across customer decision stages. | **Attention A3.02:** booking/enquiry tool and room rates were hard to find or absent from HTML. |
| **A4 Snippet & PAA Opportunities** | Dated search-feature opportunities, including People Also Ask. | **Not applicable:** no check applied to this site's captured evidence. |
| **G1 AI Crawler Access & Readability** | AI bot access, response parity, server-visible text, `llms.txt`. | **Fail G1.04:** 4 pages likely loaded main content with JavaScript. |
| **G2 Citable Facts & Evidence** | Specific first-hand facts, source support, quotable passages, current figures. | **Attention G2.02:** 3 key pages had little first-hand detail. |
| **G3 AI Share of Voice** | Brand versus competitor mentions across sampled AI answers. | **Attention G3.01:** brand absent from 14 category answers across 4 AI surfaces. |
| **G4 Citation Sources** | Which pages and domains AI answers cite. | **Attention G4.01:** AI Overviews cited the client only for brand searches. |
| **G5 AI Brand Accuracy** | Wrong, generic, or confused business facts in sampled AI answers. | **Fail G5.01:** 4 wrong business facts appeared in AI answers. |
| **G6 Off-site Entity Footprint** | Knowledge panel, listings, linked profiles, contradictory identities. | **Fail G6.04:** schema linked to a conflicting Facebook profile. |

The exact agent IDs, names, dependencies and check catalogs are registered in [`registry.py`](../engine/registry.py). The implementation files are in [`engine/agents/seo/`](../engine/agents/seo/), [`engine/agents/aeo/`](../engine/agents/aeo/), and [`engine/agents/geo/`](../engine/agents/geo/). For all 20 verdicts, statuses and remaining findings, read the [full run log](../.data/run_full20.log). It records, for example, S1's 10 passes as well as its 1 failure, and A4's three `not_applicable` checks.

### What an individual agent output contains

An agent returns typed **findings**, **patches**, **coverage**, and a signature table. A finding includes check ID, status (`pass`, `warn`, `fail`, `unverifiable`, or `not_applicable`), severity, confidence, affected pages, evidence excerpts, impact, fix, verification, effort, missing facts and patch links. A patch carries its target page/element, before/after text, reason and confidence. The validator drops unsupported or malformed findings and patches before storage; see [`schemas.py`](../engine/schemas.py) and [`validation.py`](../engine/validation.py).

The system then builds a six-section report without another LLM call: **Scope & evidence; Issues to fix; Needs attention; What's working; Proposed changes; Missing facts & next checks**. See [`reports.py`](../engine/reports.py) and [`render_md.py`](../engine/render_md.py). A saved **earlier-run** [S3 report](../.data/agent_S3.md) demonstrates all six sections: it shows the current and proposed page titles/descriptions, the evidence behind `S3.06`, and a `text_replace` patch changing the Regalia Agra title to “Sterling Regalia Agra – Hotel Near Taj Mahal, Agra.” Eight other earlier full reports are also saved locally: [S1](../.data/agent_S1.md), [S8](../.data/agent_S8.md), [S10](../.data/agent_S10.md), [A1](../.data/agent_A1.md), [A2](../.data/agent_A2.md), [G1](../.data/agent_G1.md), [G2](../.data/agent_G2.md), and [G5](../.data/agent_G5.md). These are examples of the report shape, not exports of the new 20-agent run.

## Intelligence layer: output from the 20-agent run

The saved [intelligence report](../.data/intel_full20.md) gives **AEO 64** (93% verifiable), **GEO 62** (86% verifiable), and **SEO 64** (100% verifiable). Its six sections are: executive summary; prioritized fixes; what's working; what needs attention; root causes and patterns; and action plan/blocked work. It contains 16 “Now,” 22 “Next,” and 13 “Later” work items, plus blocked items needing facts or external action. These scores describe the sampled evidence from that run, not current live rankings or a whole-site census.

Examples of the combined output:

- **W5 (Now):** 2 sampled URLs returned errors, from S1.
- **W18 (Now):** structured data described a different business, from S8, with one proposed change.
- **W37 (Now):** observed questions were unanswered or only partly answered, from A1, with one proposed change.
- **W38/W39 (Now):** wrong or mixed-up facts in sampled AI answers, from G5.
- **Root-cause group:** structured data problems are grouped as one template/source issue, so the client can fix the cause rather than treating every affected page as an unrelated job.
- **Blocked work:** current policies, rates, exact brand facts, or off-site presence may need the client or an outside platform before a safe patch can be written.

The intelligence code computes check-weighted readiness, removes repeated findings, corroborates shared missing facts, ranks harm against effort/reach/key-page importance, assigns waves, and groups common root causes. Only its executive summary may use an LLM; sentence IDs and numbers are checked against the structured data, with deterministic fallback. [`intelligence.py`](../engine/intelligence.py) is the source of these rules. Dated SERP and AI answer observations remain visible in the work list but do not change readiness.

## Output layer: what it produces now

The current implementation takes reviewed patches (or proposed patches for an **internal preview**) and creates an annotated copy and a suggested-fixed HTML copy for each affected page. It records placed/unplaced changes, hidden `<head>`/JSON-LD changes, readiness and a short client summary in a manifest. A tokenized, expiring share link opens a three-view viewer: **Annotated**, **Fixed version**, **Under the hood**. The page copy is frozen: scripts, iframes, event handlers and form submissions are removed or disabled. HTML copies and the viewer carry noindex controls. See [`bundle.py`](../engine/output/bundle.py), [`patcher.py`](../engine/output/patcher.py), [`viewer.py`](../engine/output/viewer.py), and [`share.py`](../engine/output/share.py).

The saved [share manifest](../.data/manifest.json) is a concrete **earlier-run internal preview**, run `57edf7c3-2209-42c7-a737-556afcdeca22`. It contains **7 pages, 22 proposed changes, 0 unplaced changes, and 0 site-file changes**. On the Regalia Agra page alone it lists 11 changes, including the S3 title rewrite and an S8 JSON-LD replacement that removes details copied from a different hotel. Its readiness figures, **AEO 57 / GEO 69 / SEO 71**, belong to that earlier run and must not be presented as the latest 20-agent scores. Saved [annotated HTML](../.data/p0_annotated.html), [fixed HTML](../.data/p0_fixed.html), and [viewer HTML](../.data/viewer.html) show the output format; the live share link may have expired or been revoked.

The current output is a static preview and change manifest. The broader [output-layer specification](spec/06-output-layer.md) also describes asset archiving, a download bundle and dashboard review controls, but those are not present in the current [`bundle.py`](../engine/output/bundle.py) or [`viewer.py`](../engine/output/viewer.py). In particular, the free-tier patcher leaves CSS/images on the client's origin via a `<base>` tag. The Next.js [`page.tsx`](../src/app/page.tsx) is currently a public explanation/landing page, not the diagnosis dashboard; the interim share viewer is served by FastAPI.

## Where to get complete results, and the present limit

The API has `GET /api/v1/runs/{run_id}/report`, `/findings`, and `/agents/{agent_id}` for the stored intelligence JSON, findings, and complete per-agent JSON reports. The run CLI prints only a summary, which is what the saved 20-agent log contains. The complete reports for all 20 agents were saved by the run to Postgres, but they were **not exported to local files**. A read-only database lookup from this workspace failed with `Permission denied` on the Supabase pooler connection. Therefore the table above uses the authentic saved log; it cannot show the full signature tables, evidence excerpts, and patches for all 20 from this run without database access or a prior export.

The existing project [handoff](../AGENT_HANDOFF.md) and [build status](spec/11-build-status.md) predate this 20-agent run. Use current source and the saved run artifacts for today's implementation and outputs.
