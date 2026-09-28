# 9. Provider Findings (tested 2026-09-27)

Live tests against the keys in `.env`. They drive sections 2–4.

## Results

| Provider | Test | Result |
|---|---|---|
| Supabase Postgres (Mumbai, `ap-south-1`) | Connect via session pooler | Works (PostgreSQL 17.6). URL, service-role key and connection string are all for the same project. |
| Supabase Storage / REST | Service-role key | Works |
| Supabase extensions | Availability | `pgmq`, `pg_cron`, `pg_net`, `vector` available, not yet enabled |
| DeepSeek | Model list + completions | Works: `deepseek-v4-pro`, `deepseek-flash` (`deepseek-v4-flash` alias accepted) |
| Groq | Model list | Works: fallback `openai/gpt-oss-120b` |
| Google PageSpeed Insights | Mobile run on an India site | Works: lab score + CrUX field data (LCP, INP, CLS, FCP, TTFB) |
| Serper, India (`gl=in`) | 5 queries | Organic results only: no PAA, related searches, knowledge graph or AI Overview |
| Serper Places / Autocomplete, India | 1 each | Work |
| **SerpAPI, India** (Mumbai, google.co.in) | 1 query | **AI Overview with text and 4 cited references, 4 PAA questions**, organic results. Free plan: 250 searches/month. |

## Search provider split (hybrid)

| Job | Provider | Why |
|---|---|---|
| Organic top 10 for the query set | Serper | Cheap bulk |
| Autocomplete question expansion (C7) | Serper | Real India suggestions |
| Places / local results (S9) | Serper | Works for India |
| `site:` platform checks (C12) | Serper | Bulk |
| **AI Overview + references, PAA, featured snippet** | **SerpAPI** | Only provider that returns them for India |

**SerpAPI budget:** the top 8 queries per full run (ranked by C5: brand + core service queries first). About 30 full runs/month on the free plan; agent runs that need SerpAPI data reuse the latest snapshot's capture. A daily and monthly counter in `provider_usage` stops SerpAPI calls at the plan limit. When the limit is reached, runs continue on Serper data and mark SerpAPI-dependent checks `unverifiable`.

## What this changes in the design

| Area | Effect |
|---|---|
| C6 SERP Capture | Serper for organic/Places; SerpAPI for AI Overview, PAA and snippets on the top 8 queries |
| C7 Question Library | India autocomplete expansion (`observed-autocomplete`) **plus** SerpAPI PAA (`observed-paa`) |
| C10 AI Answer Capture | Four surfaces: **Google AI Overview** (SerpAPI, real), DeepSeek knowledge probe, Groq knowledge probe, simulated AI search (proxy) |
| A4 Snippet & PAA Opportunities | **Active** on the SerpAPI-covered queries |
| G4 Citation Sources | **Real citations** from Google AI Overview references; proxy and printed-URL data kept separate and labelled |
| C12 / G6.01 Knowledge Graph | Checked via SerpAPI on the brand query (1 search) |

## Labels used on GEO observations

| Surface | Label shown in every report |
|---|---|
| Google AI Overview (SerpAPI) | Observed: Google AI Overview, India, {date}, {n} queries sampled |
| DeepSeek knowledge probe | Model knowledge (DeepSeek), no live search |
| Groq knowledge probe | Model knowledge ({model}), no live search |
| Simulated AI search | Proxy: DeepSeek answering from India top results on {date}. Not a measurement of Google, ChatGPT or Perplexity. |

## Re-test

The SERP adapter runs a weekly capability check (1 Serper query) and records which features came back. If Serper starts returning AI Overviews or PAA for India, SerpAPI calls can be reduced without code changes.
