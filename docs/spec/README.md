# Website Diagnosis Platform: Design Spec

Status: draft for review · Date: 2026-09-27 · Market: India (English)

The platform takes a client URL, crawls the site, runs independent SEO, AEO and GEO diagnosis agents over the crawled HTML, merges their results into one intelligence report, and publishes a shareable page that shows the client's own site with the suggested changes applied.

## Decisions so far

| Area | Decision |
|---|---|
| Architecture | Monolith: one repo, one Vercel project, one deploy. FastAPI (Python functions) + Next.js (dashboard, share pages) + one Node function for page rendering. |
| Hosting | **Phase 1:** free tiers only: Vercel Hobby (functions in Mumbai, `bom1`) + Supabase Free. **Phase 2:** self-hosted on your own machine with Docker, same code. See [10](10-free-tier-and-portability.md). |
| Execution | Runs split into short steps (each well under the function time limit), queued in Supabase `pgmq`, dispatched by `pg_cron` + `pg_net` and by self-chaining |
| Dashboard UI | Next.js on Vercel |
| Database and files | Supabase in Mumbai (`ap-south-1`): Postgres for data, Storage for HTML snapshots and archived assets, Auth for dashboard users |
| Reasoning LLM | DeepSeek (`deepseek-v4-pro` for reasoning, `deepseek-flash` for simple steps); Groq (`openai/gpt-oss-120b`) as automatic fallback |
| Search data | Hybrid: Serper for bulk (organic, Places, autocomplete); SerpAPI (free plan, 250/month) for Google AI Overview, PAA and snippets on the top 8 queries per full run |
| AI answers analysed | Google AI Overview via SerpAPI (real, India), DeepSeek + Groq knowledge probes (model knowledge), simulated AI search (proxy) |
| Client archetypes | Hospitality, loans, retail, logistics. Auto-detected, and the team can override. |
| Rating | Severity + confidence per finding; transparent readiness score per pillar |
| Crawl size | Configurable, default 25 pages |
| Share page | Annotated original + "fixed version" toggle + "Under the hood" panel for technical changes |

## System at a glance

```
 Client URL (+ optional archetype, locations, competitors, facts)
        │
        ▼
┌──────────────── EVIDENCE LAYER: collectors gather data, make no judgments ────────────────┐
│ Crawler → Parser → Fact Sheet · Archetype Detector (team confirms)                        │
│ Query Set → SERP Capture → Question Library · Competitor Capture                          │
│ Prompt Set → AI Answer Capture · Performance Capture · Entity Footprint                   │
└───────────────────────────── immutable evidence snapshot ──────────────────────────────────┘
        │   agents read evidence only, never each other's output
        ▼
┌──── DIAGNOSIS LAYER: 20 independent agents (SEO 10 · AEO 4 · GEO 6) ───┐
│ each agent → Agent Report (6 sections) + Findings + Patches                               │
└────────────────────────────────────────────────────────────────────────────────────────────┘
        │   full run only
        ▼
 INTELLIGENCE LAYER: merge, de-duplicate, rank, find root causes → Intelligence Report (6 sections)
        │
        ▼
 OUTPUT LAYER: apply approved patches to the snapshot → shareable annotated / fixed page
```

## Two run types

- **Agent run:** one or more chosen agents. The orchestrator collects only the evidence those agents need, reusing fresh evidence from an earlier snapshot, then produces agent reports. It can optionally publish a share page with those agents' patches.
- **Full run:** all collectors, all 20 agents, then the intelligence layer and the output layer.

## Documents

| # | File | Covers |
|---|---|---|
| 1 | [01-agent-review.md](01-agent-review.md) | Review of your 24 agents, dependency removal, refinements |
| 2 | [02-agent-catalog.md](02-agent-catalog.md) | Final collectors, 20 diagnosis agents, 1 on-demand action agent |
| 3 | [03-architecture.md](03-architecture.md) | Monolith structure, orchestrator, pipeline, Supabase data model, API |
| 4 | [04-diagnosis-matrix.md](04-diagnosis-matrix.md) | Rating system and every check per agent |
| 5 | [05-output-templates.md](05-output-templates.md) | Finding and patch schemas, agent report template, intelligence report template |
| 6 | [06-output-layer.md](06-output-layer.md) | How the shareable client page is built |
| 7 | [07-archetype-packs.md](07-archetype-packs.md) | Hospitality, loans, retail and logistics rules for India |
| 8 | [08-open-decisions.md](08-open-decisions.md) | Credentials and decisions still needed from you |
| 9 | [09-provider-findings.md](09-provider-findings.md) | Live API test results and the Serper + SerpAPI split |
| 10 | [10-free-tier-and-portability.md](10-free-tier-and-portability.md) | Running inside free-tier limits now; moving to self-hosting later |
| 11 | [11-build-status.md](11-build-status.md) | What's built, how it was verified, and where the build differs from this design |
| 12 | [12-agent-build-plan.md](12-agent-build-plan.md) | Plan and definition of done for the remaining 13 agents and 3 collectors |
| 13 | [13-reliability-and-simplification-plan.md](13-reliability-and-simplification-plan.md) | Proposed repair sequence for existing agents, evidence validation, scoring, retries, budgets and sharing; architecture simplification and release gates |

## Glossary

- **Snapshot:** one dated capture of a client site and all its external evidence. It is never modified; a re-crawl creates a new snapshot.
- **Collector:** a step that gathers or prepares data (crawl, parse, SERP, AI answers). Collectors never produce findings.
- **Agent:** reads a snapshot, runs its checks, and returns findings and patches. Agents never read other agents' results.
- **Finding:** one checked issue or strength, with evidence, severity and confidence.
- **Patch:** a concrete proposed change (text, tag, attribute, JSON-LD or file) tied to one or more findings, with a locator that pins it to an element in the snapshot HTML.
- **Pillar:** SEO, AEO or GEO.

## Grounding

The checks follow the installed claude-seo and geo skill references (CWV thresholds, schema status, AI crawler list, citability research) and Google's own guidance. Where Google says something doesn't help (llms.txt, chunking content for AI, FAQPage rich results), the matrix gives it no weight. Scores are the platform's heuristics, not Google ranking signals; reports say so.
