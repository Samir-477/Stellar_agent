# Protected Vercel preview

This is a review deployment, not a production client workspace. Production still needs per-user authentication and authorization. A preview uses the configured demo account only when `VERCEL_ENV=preview` and `PREVIEW_DEMO_AUTH=enabled`; production deployments disable it.

## Project setup

1. Link this repository root to one Vercel project with the Next.js framework preset and the default root directory. Deploy with `vercel deploy`, not `--prod`.
2. In the project settings, enable **Vercel Authentication** with **Standard Protection**. Check that an unsigned browser sees the Vercel login gate before the app. Enable **Automatically expose System Environment Variables** so `VERCEL_URL` and `VERCEL_ENV` are available to both runtimes.
3. Create a **Protection Bypass for Automation** secret in Deployment Protection. Vercel exposes its value to functions as `VERCEL_AUTOMATION_BYPASS_SECRET`. The Next.js server and Python task dispatcher send it only in server-to-server requests to the same deployment.
4. Set these variables for **Preview only** in Vercel. Enter secrets in Vercel; do not commit `.env` or `.env.local`.

| Variable | Preview value / source |
|---|---|
| `PREVIEW_DEMO_AUTH` | `enabled` |
| `DEMO_LOGIN_EMAIL`, `DEMO_LOGIN_PASSWORD`, `DEMO_SESSION_SECRET` | The preview account and a long, random session secret. Use a fresh password rather than the local demo password. |
| `DATABASE_SESSION_POOL_URL`, `DATABASE_PROJECT_URL`, `DATABASE_SERVICE_ROLE_KEY` | Preview database and Supabase Storage credentials. Existing local `.env` uses a populated database; decide whether to reuse it before copying values. |
| `BLOB_STORE` | `supabase` (local disk is ephemeral on Vercel). |
| `DEPLOY_TARGET`, `RUNNER` | `vercel`, `http`. |
| `ENGINE_API_KEY`, `INTERNAL_SECRET` | Separate long, random secrets. |
| `LLM_MODE` | `off` for the first UI and routing smoke test; switch to `live` only after the full task path is verified and provider keys are added. |

`APP_BASE_URL`, `ENGINE_API_URL`, `DASHBOARD_ORIGINS`, and `NEXT_PUBLIC_SITE_URL` can use the current `VERCEL_URL` defaults. Do not set them to localhost. The deployed API is under `/api/v1/*` and is served by `api/index.py`; the production Next.js rewrite must remain disabled so FastAPI receives the original route.

## Verify the preview before sharing it

1. Confirm the Vercel Authentication gate with an unsigned browser. Then sign in to Stellar Agents and open Home, New run, Sessions, and an existing run.
2. Confirm the Python engine responds to `/api/v1/health` (or its actual health route) through the preview URL. Check Vercel function logs for Python import, database, and routing errors.
3. Confirm a report and its page preview load from Supabase Storage. If the existing run stored blobs locally, use a Supabase-backed run instead.
4. Start one approved, low-cost test run only after the dispatcher, bypass secret, queue heartbeat, and provider settings have been checked. The first preview may be used to review existing runs without starting a new crawl.

The deployment is ready to share only when its URL, protection settings, sign-in, engine API, and existing report have been verified. A production promotion requires a separate identity and authorization design.
