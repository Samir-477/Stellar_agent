# SEO/AEO/GEO Site Diagnosis Platform

Crawls a client website, runs independent SEO, AEO and GEO diagnosis agents over the HTML, and (in later phases) publishes a shareable page showing the site with suggested fixes. The design is in [`docs/spec/`](docs/spec/README.md).

| Part | Where | Runtime |
|---|---|---|
| Engine (API, orchestrator, collectors, agents) | `engine/`, entry `api/index.py` | Python 3.12, FastAPI |
| Workspace (Sessions, run layers, Microsites) and the public microsite pages | `src/` | Next.js 16 |
| Database schema | `supabase/migrations/` | Postgres 17 (Supabase) |

## Engine: local development

```bash
python -m venv .venv
.venv/Scripts/python -m pip install -r requirements-dev.txt   # macOS/Linux: .venv/bin/python
python scripts/migrate.py --status                              # --apply to create tables
.venv/Scripts/python -m uvicorn engine.api.app:app --reload     # http://127.0.0.1:8000/api/v1/docs
.venv/Scripts/python -m pytest                                  # no network, DB or LLM calls
```

Settings come from `.env` (see `.env.example`). Keep `LLM_MODE=off` or `replay` during development: tests use recorded LLM responses, and live calls are only made for approved smoke tests.

`python scripts/db.py "select ..."` runs read-only SQL against the database (`--write` to allow changes).

## Engine layout

| Module | Job |
|---|---|
| `engine/collectors/` | Gather evidence (C1 crawler, C2 parser, …). Never judge. |
| `engine/agents/` | Judge evidence (S1, …). Read only the snapshot, never other agents. |
| `engine/orchestrator/` | Task graph, Postgres task queue with leases, runners (`inline` for local runs, `http` on Vercel) |
| `engine/llm/` | DeepSeek → Groq client, versioned prompts in `prompt_files/`, cache, budget |
| `engine/store.py`, `engine/core/blobstore.py` | Evidence rows + gzip'd files (Supabase Storage or local disk) |
| `engine/validation.py`, `engine/reports.py` | Validation gate; 6-section agent reports |

## Adding an agent

1. Create `engine/agents/<pillar>/<id>_<name>.py` subclassing `Agent`, with `requires` (evidence types) and `checks` from `docs/spec/04-diagnosis-matrix.md`.
2. Register it in `engine/registry.py`.
3. Add a golden test with an HTML fixture that plants each issue (see `tests/test_s1_golden.py`).

## Web (Next.js)

```bash
npm install
npm run dev   # http://localhost:3000; /api/v1/* is proxied to the engine on :8000
```

See `CLAUDE.md` for project rules.
