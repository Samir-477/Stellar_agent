# 3. Architecture, Pipeline and Orchestrator (hosted on Vercel)

## Requirements

**Functional**
- Accept a client URL and run either chosen agents (agent run) or everything (full run).
- Crawl up to N pages (default 25), keeping raw and rendered HTML.
- Produce agent reports, an intelligence report (full runs) and a shareable client page.
- Expose everything through a REST API and webhooks so other systems can plug in.

**Non-functional (hosted product)**
- Runs on Vercel; everything fits inside serverless function limits.
- Several team members use it at once; each run takes minutes and shows live progress.
- A failed step never fails the whole run; the report states what's missing.
- Every finding is reproducible from stored evidence.
- Safe to expose publicly: users authenticated, the crawler can't be abused, share pages isolated.
- Costs visible and capped per run and per day.

## Shape: one repo, one Vercel project, one deploy

The monolith is one repository deployed as one Vercel project. It holds three kinds of code that share one database, one set of environment variables and one release:

| Part | Runtime | Handles |
|---|---|---|
| **Engine API** | Vercel Python functions (FastAPI) | REST API, orchestrator, collectors, agents, intelligence, patching, share bundling |
| **Web** | Next.js on Vercel | Dashboard, share viewer, auth screens |
| **Renderer** | One Vercel Node function (`playwright-core` + `@sparticuz/chromium`) | Renders a single page in headless Chromium: DOM HTML, screenshot, asset list |

The renderer is Node because Python's Playwright + Chromium doesn't fit Vercel's function size limit, while `@sparticuz/chromium` is built for it. It's one small function called over HTTP by the Python crawler, so there's no paid browser service.

```
repo/
├─ src/app/                     # Next.js: dashboard routes, /r/[token] share viewer, auth
├─ src/app/api/render/route.ts  # Node renderer function (one page per call)
├─ api/index.py                 # Vercel Python entry → FastAPI app (/api/v1/*)
├─ engine/                      # Python package (not named app/ to avoid clashing with Next.js)
│  ├─ core/                     # config, logging, auth, Supabase clients, SSRF guard, errors
│  ├─ api/                      # routers: clients, runs, agents, findings, patches, shares, webhooks, internal
│  ├─ orchestrator/             # planner, task graph, dispatcher, state machine, budgets, rate limits
│  ├─ collectors/               # c01_crawler … c12_entity_footprint
│  ├─ agents/  base.py  seo/ aeo/ geo/ action/
│  ├─ intelligence/             # merge, dedupe, priority, root causes, narrative
│  ├─ output/                   # freeze, archive assets, patch, annotate, bundle
│  ├─ llm/                      # provider chain: DeepSeek → Groq; prompt templates (versioned); cache
│  ├─ integrations/             # serper.py, pagespeed.py, wikidata.py, renderer_client.py
│  ├─ lib/                      # entity matching, passage retrieval, locators, text utils
│  ├─ rules/                    # archetype packs (YAML)
│  └─ schemas/                  # Pydantic: Finding, Patch, AgentReport, IntelligenceReport
├─ supabase/migrations/         # SQL: tables, RLS, pgmq queues, pg_cron jobs
├─ vercel.json                  # regions (bom1), per-function maxDuration and memory, rewrites
└─ tests/                       # golden tests per agent on saved HTML fixtures
```

Exact routing between the Next.js routes and the Python functions is confirmed during the build against current Vercel docs. The design only needs `/api/v1/*` → FastAPI and `/api/render` → Node.

## Agent interface

```python
class Agent(Protocol):
    id: str                      # "S1"
    name: str
    pillar: Literal["seo", "aeo", "geo"]
    version: str                 # stored on every finding
    requires: set[EvidenceType]  # drives which collectors the planner schedules
    checks: list[CheckSpec]      # from the diagnosis matrix
    counts_toward_readiness: bool

    def plan(self, ctx: AgentContext) -> list[WorkUnit]: ...        # split into short units (e.g. per page batch)
    async def run_unit(self, ctx: AgentContext, unit: WorkUnit) -> UnitResult: ...
    async def reduce(self, ctx: AgentContext, units: list[UnitResult]) -> AgentResult: ...

class AgentContext:
    snapshot: SnapshotReader     # read-only evidence; no access to other agents' findings
    client: ClientProfile
    rules: ArchetypePack
    llm: LLMClient               # budgeted, rate-limited, with fallback
    lib: SharedLibraries
```

`plan → run_unit → reduce` is a map/reduce **inside** one agent, so its work fits serverless time limits. It never creates a dependency on another agent.

## Execution model: short steps, queued in Postgres

A run becomes a graph of **tasks**. Each task is sized to finish in **≤120 seconds**, well under the function limit (configured at 300 s), leaving headroom for slow sites and LLM latency.

| Step | Unit of work |
|---|---|
| C1 raw crawl | 5 pages per task (plus robots.txt, sitemap, AI user-agent probes) |
| C1 render | 1 page per call to the Node renderer; the crawl task fans out calls |
| C2 parse | 5 pages per task |
| C6/C7/C12 Serper + SerpAPI | ≤10 queries per task |
| C10 AI answers | ≤5 prompts × 1 surface per task |
| Agents | `plan` splits by page batch or question batch; one `reduce` task per agent |
| Intelligence | merge/rank task + narrative task |
| Output | 1 page per render-patch task + 1 bundle task |

### Queue and dispatch

> **Build note (2026-09-27):** the `tasks` table itself is the queue: workers claim ready rows with `FOR UPDATE SKIP LOCKED` and a lease token. This removes the `pgmq` dependency and runs unchanged on plain Postgres. `pg_cron` + `pg_net` still provide the Vercel heartbeat.

```
                   ┌──────────────── Supabase Postgres ───────────────┐
 POST /runs ──►    │ tasks table (state)   pgmq queue "tasks" (work)  │
                   │ pg_cron every 10 s ──► pg_net POST /internal/dispatch
                   └───────────────────────────────┬──────────────────┘
                                                   ▼
             /api/v1/internal/dispatch  (claims up to K ready tasks, honours concurrency caps)
                                                   │  one HTTP call per task
                                                   ▼
             /api/v1/internal/execute/{task_id}  (separate function invocation → real parallelism)
                                                   │ on finish: write results, enqueue children,
                                                   ▼ then call /internal/dispatch again (self-chaining)
```

- **Two triggers.** Every finished task immediately calls dispatch, so runs flow without waiting. `pg_cron` + `pg_net` also call dispatch every 10 seconds from inside Supabase, **but only while tasks are pending or running**, so an idle system uses no invocations. Stalled or retried tasks are always picked up, and neither trigger depends on Vercel Cron.
- **Leases.** pgmq's visibility timeout (function limit + 60 s) hides a claimed task. If the function dies, the task reappears and is retried (max 3 attempts, then dead-lettered and marked `failed`).
- **Idempotency.** Task outputs are keyed by `task_id`, so a retry overwrites its own output and never duplicates.
- **Internal endpoints** (`/internal/*`) require an HMAC signature with a server-only secret.
- **Concurrency caps:** per run (default 6 tasks), global (default 30), and per provider (token buckets in Postgres for DeepSeek, Groq, Serper and SerpAPI), so one big run can't starve the others or trip provider rate limits.

### Pipeline

```
 intake ─► plan ─► collect ─► [archetype gate] ─► analyze ─► validate ─► synthesize* ─► render ─► done
                                                   (fan-out)                 (*full run only)
```

1. **Intake:** URL (SSRF-checked), run type, agents, crawl cap, optional archetype, locations, competitors, team facts.
2. **Plan:** combine the selected agents' `requires`, map that to collectors, order by the collector graph, and reuse fresh evidence from the latest snapshot.
3. **Collect:** collector tasks run in order, in parallel where the graph allows.
4. **Archetype gate:** below 0.8 confidence (and no `auto_confirm`), the run pauses in `awaiting_confirmation` and a webhook fires.
5. **Analyze:** every selected agent's units run in parallel under the caps, then each agent's `reduce`.
6. **Validate:** schema, evidence references, locator resolution, fact guard, severity rules (below).
7. **Synthesize (full run):** intelligence layer.
8. **Render:** share bundle from approved patches (output layer).

### Collector dependency graph

```
C1 Crawler ─► C2 Parser ─┬─► C3 Archetype ─┬─► C5 Query Set ─► C6 SERP ─► C8 Competitors
                         │                 │                └─► C7 Question Library (autocomplete)
                         ├─► C4 Fact Sheet ┴─► C9 Prompt Set ─► C10 AI Answers
                         ├─► C11 Performance
                         └─► C12 Entity Footprint (needs C3, C4)
```

### Run and task states

```
run:   queued → planning → collecting → awaiting_confirmation → analyzing → synthesizing → rendering
             → completed | completed_partial | failed | cancelled
task:  pending → queued → running → succeeded | partial | failed | skipped | timed_out | dead_lettered
```

The dashboard shows live progress through **Supabase Realtime** subscriptions on `runs` and `tasks` (filtered by the user's organization through RLS).

### Validation rules

- Output matches the Pydantic schema.
- Every finding references at least one existing evidence ID.
- A `hypothesis` finding can't be `critical`.
- Every patch locator resolves to exactly one element in the snapshot HTML. JSON-LD and robots.txt patches must parse.
- **Fact guard:** every number, price, rate, date, phone, address or licence ID in generated copy must exist in the Fact Sheet or the source passage. Otherwise the draft becomes a "missing fact" item.
- Title and description patches respect length limits.

## LLM layer: DeepSeek with Groq fallback

| Tier | Primary | Fallback | Used for |
|---|---|---|---|
| Reasoning | `deepseek-v4-pro` | Groq `openai/gpt-oss-120b` | Content judgments, answer drafts, intelligence narrative, briefs |
| Fast | `deepseek-flash` | Groq `openai/gpt-oss-120b` | Classification (archetype, intent, journey stage), extraction, dedupe checks |
| Knowledge probes (C10) | DeepSeek **and** Groq, both deliberately | — | Two model families as two separate surfaces (not a fallback) |

- **When fallback happens:** timeout (60 s), HTTP 429 or 5xx, or invalid JSON after one repair attempt.
- **Circuit breaker:** 5 DeepSeek failures within 2 minutes routes all calls to Groq for 5 minutes, then tries DeepSeek again.
- **Recorded:** every call stores provider, model, prompt version, tokens and whether it was a fallback. Findings made with fallback output say so, so quality differences can be traced.
- **Structured output:** JSON mode + Pydantic validation; one repair retry.
- **Cache:** results cached in Postgres by hash of (prompt template version, model tier, inputs), so re-running an agent on the same snapshot costs nothing.
- Both providers speak the OpenAI-compatible API, so one client class handles both.

## Supabase (Mumbai, `ap-south-1`)

| Feature | Use |
|---|---|
| Postgres | All structured data (tables below) |
| `pgmq` | Task queue |
| `pg_cron` + `pg_net` | 10-second dispatch heartbeat; nightly retention cleanup |
| Storage | Buckets: `snapshots` (raw/rendered HTML, screenshots), `assets` (archived CSS, images and fonts), `ai-answers`, `share-bundles`. All private; served through the app. |
| Auth | Dashboard users (email; SSO later). Roles: admin, analyst, viewer. |
| Realtime | Live run progress in the dashboard |
| Edge Functions | Optional: `gte-small` embeddings for semantic question de-duplication (free, built in) |
| `pgvector` | Stores those embeddings |

**Row-level security is on for every table.** Dashboard users read only their organization's rows through RLS policies. The engine uses the service-role key server-side only. The key is never exposed to the browser, and never in a `NEXT_PUBLIC_*` variable.

### Data model (core tables)

All tables carry `org_id`, so more teams or client logins can be added later without migration pain.

| Table | Key columns |
|---|---|
| `orgs`, `memberships` | org, user, role |
| `api_keys` | org_id, hashed key, scopes, last_used_at |
| `clients` | id, name, primary_url, archetype, archetype_source, locations, competitors, crawl_consent_by, crawl_consent_at |
| `snapshots` | id, client_id, started_at, crawl_cap, status, evidence_manifest |
| `pages` | id, snapshot_id, url, final_url, status, template_id, raw_html_path, rendered_html_path, screenshot_path, render_status |
| `evidence` | id, snapshot_id, collector_id, type, page_id?, payload (JSONB), storage_path?, captured_at, source_label |
| `facts` | id, client_id, key, value, source_url, status, confirmed_by? |
| `query_sets` / `prompt_sets` | id, client_id, version, items (JSONB with provenance labels), page_query_map |
| `runs` | id, client_id, snapshot_id, type, agents[], status, budgets, spend, created_by, timings |
| `tasks` | id, run_id, kind, ref_id, unit, status, attempts, lease_until, error, started_at, finished_at |
| `findings` | id, run_id, agent_id, agent_version, check_id, pillar, status, severity, confidence, scope, page_id?, locator?, evidence_ids[], fingerprint, llm_fallback_used, payload |
| `patches` | id, run_id, agent_id, finding_ids[], page_id?, type, locator, before, after, rationale, review_status, reviewed_by |
| `reports` | id, run_id, kind, agent_id?, body (JSONB), rendered_md |
| `shares` | id, run_id, token_hash, expires_at, password_hash?, revoked_at, view_count |
| `llm_calls`, `llm_cache` | provider, model, prompt_version, tokens, cost estimate, fallback flag / cache key, response |
| `provider_usage` | provider, day, units used (Serper credits, SerpAPI searches vs 250/month, tokens), budget |
| `provider_capabilities` | provider, checked_at, features returned (weekly Serper check) |
| `webhooks` | org_id, url, events[], secret |

## REST API (v1)

| Method | Path | Purpose |
|---|---|---|
| POST | `/api/v1/clients` | Create a client (records crawl consent) |
| POST | `/api/v1/runs` | Start a run: `{client_id, type: "full"|"agent", agents?, crawl_cap?, reuse_evidence?, auto_confirm?}` |
| GET | `/api/v1/runs/{id}` | Status, task progress, spend, coverage |
| POST | `/api/v1/runs/{id}/archetype` | Confirm or override the archetype |
| POST | `/api/v1/runs/{id}/cancel` | Cancel a run |
| GET | `/api/v1/runs/{id}/report` | Intelligence report (full runs) |
| GET | `/api/v1/runs/{id}/agents/{agent_id}` | One agent's report, findings and patches |
| GET | `/api/v1/runs/{id}/findings` | Filter by pillar, agent, severity, page, status |
| PATCH | `/api/v1/patches/{id}` | Approve, edit or reject a patch |
| POST | `/api/v1/runs/{id}/shares` | Create a share link |
| DELETE | `/api/v1/shares/{id}` | Revoke a share link |
| GET | `/api/v1/agents` | Agent registry: checks, required evidence, versions, parked status |
| POST | `/api/v1/actions/content-brief` | Run X1 for a chosen work item |
| POST | `/api/v1/internal/dispatch`, `/internal/execute/{task_id}` | Internal only (HMAC) |

Auth: Supabase JWT for dashboard users, or `Authorization: Bearer <api key>` for systems. Webhook events: `run.awaiting_confirmation`, `run.completed`, `run.failed`, `share.created`, all HMAC-signed. FastAPI publishes the OpenAPI spec for client generation. Report bodies carry `schema_version`.

## Hosting concerns

### Vercel configuration (Phase 1: Hobby, free)

| Setting | Value | Why |
|---|---|---|
| Plan | **Hobby (free)** for Phase 1 | Free-tier limits and how the design stays inside them: [10](10-free-tier-and-portability.md) |
| Function region | `bom1` (Mumbai) | Next to Supabase `ap-south-1` |
| Engine functions | maxDuration 300 s (Hobby maximum) | Tasks target ≤120 s |
| Renderer function | maxDuration 60 s, highest memory the plan allows | Chromium needs memory; one page per call; images/fonts blocked while rendering to save CPU |
| Domains | Two free hostnames on one project: `<app>.vercel.app` (dashboard + API) and `<app>-share.vercel.app` (share viewer only) | Separate origin for untrusted client HTML, no custom domain needed |
| Environment variables | Set in Vercel project settings | `.env` stays local and git-ignored |

Next.js middleware routes by host: the share hostname serves only `/r/*` and static share assets, and everything else there returns 404. Auth cookies are host-only on the app hostname, so share pages can never read them.

### Security

| Threat | Protection |
|---|---|
| **SSRF:** someone submits `http://169.254.169.254/` or an internal host to the crawler | URL guard: http/https only; resolve DNS and block private, loopback, link-local and metadata ranges; re-check after every redirect (prevents DNS rebinding); cap redirects and response size |
| Crawler abuse (pointing it at sites you don't own) | Crawl consent recorded per client; per-org run quotas; polite rate limits |
| Client HTML running code | Share viewer on its own origin, sandboxed iframe, client scripts stripped, strict CSP |
| Share copy being indexed | `X-Robots-Tag: noindex, nofollow` and `Disallow: /` on the share host |
| Leaked share links | 128-bit tokens stored hashed, expiry, revoke, optional password, view counts |
| Key leakage | Service-role, DeepSeek, Groq, Serper, SerpAPI and PageSpeed keys server-only; API keys stored hashed; internal endpoints HMAC-signed |
| Prompt injection from crawled pages | Page text is passed to LLMs as quoted data inside delimiters, never as instructions; LLM outputs are validated against schemas; LLMs have no tools that act |

### Operating it

- **Observability:** structured JSON logs with `run_id` and `task_id`. Hobby keeps runtime logs for only 1 hour and has no log drains, so task errors and warnings are also written to `tasks` / `task_logs` in Postgres; the dashboard shows them per run.
- **Cost control:** per-run budgets (Serper credits, SerpAPI searches, LLM tokens) and a daily org-wide cap in `provider_usage`. A run that hits its budget finishes `completed_partial` with the reason stated.
- **Crawler IPs:** requests come from Vercel's shared datacenter IPs. Some client firewalls block those; G1 reports it, and the client can allow-list the crawler user agent.
- **Supabase Free:** 500 MB database, 1 GB storage, pauses after 1 week idle, no backups. Payloads are stored gzip-compressed in Storage, retention keeps the last 2 snapshots per client, and the dashboard shows storage and CPU meters ([10](10-free-tier-and-portability.md)).
- **Retention:** nightly `pg_cron` job deletes snapshots and Storage objects past the retention policy (open decision).
- **Environments:** Supabase Free allows two projects, so the second one serves as staging for Vercel Preview deployments.

## Trade-offs

| Decision | Upside | Cost | Revisit when |
|---|---|---|---|
| Free tiers now, self-hosted later | Zero hosting cost; portability rules keep the move to Docker a config change | Tight CPU and storage limits; asset archiving off; smaller render budget | Monthly CPU or storage meters approach their limits → move to Phase 2 |
| Node renderer beside Python | No paid browser service | Two languages in one repo; Chromium cold starts (a few seconds per page) | Rendering becomes the bottleneck; then consider a hosted browser |
| Queue in Postgres (pgmq) + pg_cron dispatch | No extra services; works on any Vercel plan | Dispatch latency of up to ~10 s when self-chaining misses | High volume; move to a dedicated queue |
| Immutable snapshots | Reproducible findings; run comparisons | Storage growth | Set retention |
| Deterministic checks first, LLM second | Cheaper, testable, stable across providers | More code per agent | — |
