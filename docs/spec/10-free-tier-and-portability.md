# 10. Free-Tier Operation and Portability

**Phase 1 (now):** run entirely on free tiers: Vercel Hobby + Supabase Free.
**Phase 2 (later):** host on your own machine with Docker, using the same code.

The design has to satisfy both: stay inside free-tier limits now, and move to self-hosting without a rewrite.

## Free-tier limits that shape the design

| Platform | Limit (free) | Source |
|---|---|---|
| Vercel Hobby | Functions time out at 300 s | vercel.com/docs/plans/hobby |
| | **4 CPU-hours** Active CPU per month; 360 GB-hrs memory; 1M invocations | same |
| | Runtime logs kept 1 hour; no log drains | same |
| | Over a limit → that feature stops until 30 days pass | same |
| Supabase Free | **500 MB database**, **1 GB file storage**, 5 GB egress | supabase.com/pricing |
| | **Paused after 1 week of inactivity**; resume from the dashboard (data is kept) | same |
| | No automatic backups | same |
| | 2 free projects | Supabase billing docs |
| SerpAPI Free | 250 searches/month | tested |

## How the design stays inside them

### Vercel CPU (4 hours/month)

- Active CPU counts only compute time. Waiting on DeepSeek, Serper or the database is free, so the expensive part is **Chromium rendering** and HTML parsing.
- The renderer blocks images, fonts and media while rendering (the DOM is what matters) and returns only the HTML, a small viewport screenshot and the asset list.
- A **render budget per run** (default: render 10 of the 25 pages, one per template first; raw HTML for all 25). G1's raw-vs-rendered check runs on the rendered subset.
- The platform records each task's duration and shows a monthly "free-tier meter" in the dashboard. Rough estimate: 3–5 CPU-minutes per full run, which is tens of full runs per month. It will be measured, not assumed.

### Vercel invocations (1M/month)

- The `pg_cron` heartbeat calls the dispatcher **only when tasks are pending or running** (a SQL check before `pg_net` fires). An idle system makes zero calls.

### Supabase storage (1 GB) and database (500 MB)

| Measure | Effect |
|---|---|
| All HTML, SERP and AI-answer payloads stored **gzip-compressed** in Storage, not in Postgres | DB holds only structured rows (findings, patches, tasks) |
| Screenshots: one 1280×800 WebP per rendered page, no full-page captures | ~50 KB each |
| **Asset archiving off on free tier** (`ARCHIVE_ASSETS=false`): share pages load the client's live CSS/images through a `<base href>` | Avoids 5–15 MB per page; trade-off: a share page can drift if the client changes their CSS |
| Retention: keep the **last 2 snapshots per client**; nightly `pg_cron` cleanup | Estimated 10–15 MB per full run |
| Storage meter in the dashboard, warning at 80% | No surprises |

### Supabase pausing (1 week idle)

A week without use pauses the project. Resume it from the Supabase dashboard; nothing is lost. The app shows a clear "database paused" error instead of failing silently.

### Logs (1 hour on Vercel)

Task errors and warnings are written to the `tasks` table (and a small `task_logs` table), so run history survives beyond Vercel's 1-hour log window.

### Domains (free)

One Vercel project with **two free `*.vercel.app` hostnames**, e.g. `yourapp.vercel.app` (dashboard + API) and `yourapp-share.vercel.app` (share viewer). The share viewer still gets its own origin for security, and no custom domain is needed.

### LLM spend

Hosting is free, but DeepSeek bills per use (cheap, not free). Groq has a free tier with rate limits. If you want zero spend during testing, the provider chain can run Groq-first with a config switch (`LLM_PRIMARY=groq`), at some cost in reasoning quality.

## Portability rules (followed from day one)

These keep the Phase 2 move to your own machine to a config change:

| Rule | Why |
|---|---|
| The engine is a plain FastAPI (ASGI) app. Vercel-specific code is limited to `api/index.py` (a few lines) and `vercel.json`. | Runs unchanged under `uvicorn` |
| One function executes any task: `execute_task(task_id)`. Two **runners** call it: `http` (Vercel: dispatcher invokes a function per task) and `worker` (self-hosted: a long-running loop pulls from the same pgmq queue). Selected with `RUNNER=http|worker`. | Same orchestration code in both worlds |
| The renderer is an HTTP contract: `POST /render {url} → {html, screenshot, assets}`. Vercel implementation: Node + `@sparticuz/chromium`. Self-hosted: the same Node code in a container with full Chromium. | Swap by URL (`RENDERER_URL`) |
| File storage behind a `BlobStore` interface: `SupabaseStorage` now; `LocalDisk` or `S3Compatible` (MinIO) later. Selected with `BLOB_STORE=`. | No Supabase lock-in for files |
| Core data path uses only standard Postgres + `pgmq` + `pg_cron`. | Works on Supabase cloud, self-hosted Supabase, or plain Postgres 17 with those extensions |
| Auth: the API verifies JWTs against a configurable JWKS URL (Supabase Auth now). | Self-hosted Supabase Auth or any OIDC provider later |
| Realtime progress is optional; the dashboard falls back to polling every 3 s. | Nothing breaks without Supabase Realtime |
| No Vercel-only services (KV, Blob, Queues, Cron, Edge Config). | Nothing to replace later |
| All configuration through environment variables (`DEPLOY_TARGET=vercel|local`). | One `.env` per environment |

## Phase 2: self-hosted layout (for later)

```
docker compose up
├─ web        Next.js (dashboard + share viewer)
├─ api        FastAPI (uvicorn)                      RUNNER=worker
├─ worker     same Python image, task loop           pulls from pgmq
├─ renderer   Node + full Chromium                   RENDERER_URL=http://renderer:3001
└─ database   choose one: keep Supabase cloud · self-hosted Supabase (Docker) · Postgres 17 + pgmq + pg_cron
   storage    choose one: keep Supabase Storage · MinIO · local disk
```

Self-hosting removes the function time limit and CPU cap, so larger crawls and full-page rendering become possible. Asset archiving can be switched on (`ARCHIVE_ASSETS=true`).

**Share links from a local machine** must still be reachable by clients over the internet. Two free options, decided later:
1. Expose only the share viewer through **Cloudflare Tunnel** (no open ports on your network).
2. Keep the share viewer on Vercel Hobby, reading published bundles from storage, while everything else runs locally.

## Migration checklist (Phase 1 → 2)

1. Choose the database and storage options above; if leaving Supabase cloud, `pg_dump` the database and copy the Storage buckets.
2. Set `DEPLOY_TARGET=local`, `RUNNER=worker`, `RENDERER_URL`, `BLOB_STORE`, and the JWKS URL.
3. `docker compose up`, run migrations, and run the golden tests.
4. Point the share hostname at the tunnel (or keep it on Vercel).
