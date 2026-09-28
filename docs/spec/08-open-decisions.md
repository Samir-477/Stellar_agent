# 8. Open Decisions and Inputs Needed

## Credentials and accounts

| Item | Status | Notes |
|---|---|---|
| Supabase (URL, service-role key, session-pooler connection string) | Tested and working in Mumbai (`ap-south-1`) | Done |
| Supabase plan | Free (Phase 1) | 500 MB DB, 1 GB storage, pauses after 1 week idle, no backups. See [10](10-free-tier-and-portability.md). |
| Supabase staging project | Optional | Supabase Free's second project can serve as staging |
| DeepSeek | Tested and working | Set `DEEPSEEK_MODEL=deepseek-v4-pro` (reasoning) and `DEEPSEEK_FAST_MODEL=deepseek-flash`; both currently point at flash |
| Groq | Tested and working | Fallback + second knowledge-probe surface (`openai/gpt-oss-120b`) |
| Serper | Tested and working | Bulk: organic, Places, autocomplete, `site:` checks |
| SerpAPI | Tested and working | Free plan, 250 searches/month: AI Overview, PAA, snippets, knowledge graph on the top 8 queries per full run |
| Google PageSpeed Insights API key | Tested and working | Returns lab + CrUX field data |
| Vercel | Hobby (free) for Phase 1, your choice | One project, two free `*.vercel.app` hostnames. Fits Hobby technically (tasks ≤120 s vs 300 s; no Vercel Cron); watch the 4 CPU-hours/month. Vercel's terms limit Hobby to non-commercial use. Phase 2 moves to self-hosting. |
| Domains | Not needed in Phase 1 | Free `*.vercel.app` hostnames |
| Internal secrets | Generated at build | HMAC secret for internal endpoints and webhooks |

## Decisions for you

| # | Question | Options | My recommendation |
|---|---|---|---|
| 1 | Where does the platform code live? | (a) New repo; (b) inside this repo alongside the marketing site | (a) New repo. Different deploys and audiences. |
| 2 | Patch approval before sharing | Always manual / auto-approve confirmed deterministic patches | Auto-approve deterministic only; copy rewrites always manual |
| 3 | Share link defaults | Expiry? Password on by default? | 30 days, password optional |
| 4 | Snapshot retention | Keep all / last N per client / delete after X days | Last 5 snapshots per client |
| 5 | Dashboard users | Supabase Auth email login + roles (admin, analyst, viewer)? SSO later? | Yes, SSO later |
| 6 | Client consent to crawl | Captured at client creation (who + when)? | Yes |
| 7 | Search Console integration | Add as a query source for C5/S5 and real India question data? | Phase 2. Real India queries at no search-credit cost. |
| 8 | Compliance review | Who signs off the loans and retail disclosure lists? | A named reviewer per pack |
| 9 | SerpAPI plan | Stay on free (about 30 full runs/month) or upgrade? | Stay free until client volume is known |
| 10 | Budgets | Per-run and daily caps for Serper credits and LLM spend | Per run: 60 Serper credits + 8 SerpAPI searches; daily LLM cap set by you |

## Suggested build order (after sign-off)

1. **Foundation:** repo, Vercel project (bom1), Supabase Mumbai schema + RLS, pgmq queue, pg_cron dispatch, orchestrator state machine, agent interface, LLM provider chain, SSRF guard, dashboard shell with auth.
2. **Evidence core:** C1 Crawler (raw + Node renderer), C2 Parser, C3 Archetype, C4 Fact Sheet.
3. **Deterministic agents first:** S1, S3, S7, S8, G1, A2 (no search credits, fast to validate).
4. **Output layer:** freeze, archive, patch, annotate, share viewer on the share domain.
5. **Search-based:** C5, C6, C7, C8 → S4, S5, S6, S9, A1, A3.
6. **AI answers:** C9, C10, C12 → G2, G3, G4, G5, G6; then S2 (C11) and S10.
7. **Intelligence layer**, then X1 Content Brief.

Each agent ships with golden tests: saved HTML fixtures from each archetype, with expected findings.
