# 5. Output Templates

Three layers, three shapes of output:

| Layer | Unit | Template |
|---|---|---|
| Individual agent | Agent Report | 6 agent sections + a signature table specific to that agent |
| Intelligence (full run) | Intelligence Report | 6 intelligence sections, different from the agent sections |
| Output | Share page | See [06-output-layer.md](06-output-layer.md) |

All reports are stored as versioned JSON (`schema_version`) and rendered to Markdown/HTML for the dashboard.

## Finding schema

```json
{
  "id": "fnd_01J…",
  "run_id": "run_01J…",
  "agent_id": "S3",
  "agent_version": "1.0.0",
  "check_id": "S3.01",
  "pillar": "seo",
  "title": "Duplicate title on 4 service pages",
  "status": "fail",
  "severity": "high",
  "confidence": "confirmed",
  "scope": { "level": "page", "pages": ["https://client.in/services/a", "…"], "template_id": "tpl_service" },
  "locator": { "css": "head > title", "xpath": "/html/head/title", "text_hash": "…" },
  "evidence": [
    { "evidence_id": "ev_…", "type": "html_excerpt", "excerpt": "<title>Services | Client</title>", "captured_at": "2026-09-27T10:02:11+05:30" }
  ],
  "impact": "Search engines can't tell these pages apart, so they compete with each other and show vague results.",
  "fix": "Give each service page a unique title that leads with its service.",
  "patch_ids": ["pch_…"],
  "verification": "Re-crawl: each service page has a unique <title>.",
  "effort": "S",
  "missing_facts": [],
  "tags": ["template-head"],
  "fingerprint": "S3.01|tpl_service|head>title"
}
```

- `tags` feed root-cause clustering. Examples: `client-side-rendering`, `template-head`, `missing-fact`, `no-location-pages`.
- `fingerprint` is used for de-duplication. It is built from check, scope and locator, so the same issue found twice collapses into one.
- `missing_facts` lists facts the client must supply before the fix can be written.

## Patch schema

```json
{
  "id": "pch_01J…",
  "finding_ids": ["fnd_01J…"],
  "agent_id": "S3",
  "page_url": "https://client.in/services/a",
  "type": "text_replace",
  "locator": { "css": "head > title", "xpath": "/html/head/title", "text_hash": "…" },
  "before": "Services | Client",
  "after": "Two-Wheeler Loans in Pune at 11.5% p.a. | Client",
  "rationale": "Leads with the service and location; rate taken from fact F-012.",
  "fact_ids": ["F-012"],
  "confidence": "likely",
  "review_status": "proposed",
  "client_visible_note": "A clearer page title helps Google show this page for two-wheeler loan searches in Pune."
}
```

| Patch type | Used for |
|---|---|
| `text_replace` | Titles, headings, answer rewrites |
| `attribute_set` | `alt`, `rel`, `hreflang`, meta `content` |
| `element_insert` | New answer section, table, author box, internal link |
| `element_remove` | Duplicate H1, retired markup |
| `head_upsert` | Meta, canonical, Open Graph |
| `jsonld_upsert` | New or corrected JSON-LD block |
| `file_patch` | robots.txt, sitemap.xml, llms.txt (shown in "Under the hood") |
| `header_recommendation` | HTTP headers such as X-Robots-Tag (instructions, since they can't be applied to HTML) |

---

## Agent Report template (individual agent)

Every agent fills the same 6 sections, but section contents and the signature table are agent-specific. The agent's own checks are the only thing it can talk about.

```
# {Agent ID} {Agent name}: {client} · {date} · snapshot {id}

Verdict: {1–2 plain sentences: the state of this agent's area}
Scorecard: {pass} pass · {warn} warn · {fail} fail · {n/a} n/a · {unverifiable} unverifiable
```

| # | Section | What goes in it | Rules |
|---|---|---|---|
| 1 | **Scope & Evidence** | What this agent examined: pages, queries, prompts, surfaces, dates, crawl cap. What it skipped and why. Followed by the **signature table**. | Must state sample limits (e.g. "25 of ~140 pages") |
| 2 | **Issues to Fix** | `fail` findings sorted by severity, then pages affected. Each has: title, where, evidence excerpt, why it matters, fix, verification. | Every item cites evidence |
| 3 | **Needs Attention** | `warn` findings, `hypothesis` findings, and `unverifiable` checks, with what would settle each one | Never mixed into section 2 |
| 4 | **What's Working** | `pass` checks worth protecting, with evidence, so fixes don't break them | Only notable passes, not every trivial one |
| 5 | **Proposed Changes** | This agent's patches as before → after, grouped by page, with review status | Only patches that passed validation |
| 6 | **Missing Facts & Next Checks** | Facts the client must supply, data this agent lacked (e.g. no CrUX data), and what re-running would confirm | Phrased as a checklist |

### Signature table per agent

This is what makes each report specific to its agent. It sits at the end of section 1.

| Agent | Signature table |
|---|---|
| S1 | URL · status · final URL · indexable? · canonical target · in sitemap? |
| S2 | Template · LCP · INP/TBT · CLS · TTFB · data source (field/lab) |
| S3 | Page · current title (length) · proposed title · current description · proposed description |
| S4 | Page · target query · SERP-dominant intent · page intent · subtopics missing |
| S5 | Cluster · example queries · demand signals · owner page · conflict/gap |
| S6 | Query · date · client position · top 3 results (type) · SERP features · who holds them |
| S7 | Page · inlinks · click depth · generic anchor % · suggested links |
| S8 | Page · types found · valid? · missing required · truthfulness mismatches |
| S9 | Source (footer/contact/schema/Maps/location page) · name · address · phone · match? |
| S10 | Trust item (from archetype pack) · present? · where · note |
| A1 | Question · source label · journey stage · verdict · best passage (excerpt) · draft ready? |
| A2 | Page · passage · issue (opening/heading/format/length/snippet control) · proposed structure |
| A3 | Stage · pages/tools serving it · observed questions at this stage · coverage |
| A4 | Query · feature (snippet/PAA) · holder · format · client rank · eligible? |
| G1 | Crawler · robots.txt rule · response to its user agent · raw-HTML content % |
| G2 | Page · distinctive facts found · generic claims · entity definition present? |
| G3 | Prompt · surface · brand mentioned? · competitors mentioned · prominence · date |
| G4 | Domain · type (client/competitor/third party) · times cited · surfaces · verified retrieval? |
| G5 | Fact · Fact Sheet value · AI-stated value · surface · verdict |
| G6 | Platform · present? · profile URL · consistent with site? |

---

## Full run output

A full run produces one **Run Report**:

1. **Run header:** client, archetype (detected/confirmed), snapshot date, pages crawled, surfaces probed, agents succeeded/partial/failed.
2. **Pillar panel:** SEO / AEO / GEO readiness with coverage %, plus the observation strip (AI mentions, AI citations, snippet holdings) kept separate from scores.
3. **Intelligence Report:** the 6 sections below.
4. **Agent Reports:** all 20, each in the agent template (linked, not repeated inline).
5. **Coverage & limitations:** what wasn't checked and why (missing keys, failed agents, sample size, surfaces not probed).

## Intelligence Report template

The intelligence layer reads **all** validated findings, patches and coverage data from a full run. Its sections are deliberately different from the agent sections: it synthesizes across agents rather than listing checks.

| # | Section | What goes in it | How it's built |
|---|---|---|---|
| 1 | **Executive Summary** | 3–5 plain sentences: overall state, the biggest blocker, the biggest opportunity. Pillar readiness + observation strip. | LLM narrative, restricted to finding IDs; each sentence cites ≥1 finding |
| 2 | **What to Fix First** | De-duplicated priority queue in 3 waves: **Now** (critical/high, unblocked, S–M effort), **Next**, **Later**. Each item: action, pages, pillars helped, contributing agents, linked patches. | Deterministic: merge by fingerprint, then rank by priority score |
| 3 | **What's Working** | Cross-agent strengths to protect, grouped by pillar | Notable passes + observations where the client leads competitors |
| 4 | **What Needs Attention** | Risks and watch items: compliance flags (loans/retail), unverifiable areas, hypotheses, unstable AI observations, dated SERP positions to re-check | `warn` + `hypothesis` + `unverifiable` + compliance tags |
| 5 | **Root Causes & Patterns** | Findings grouped by shared cause (one template, one rendering method, one missing fact), with the insight that one fix clears many findings. Includes the **topic coverage view** (from the old FAQ Intelligence agent): each question topic × covered/partial/missing, and the **SEO ↔ AEO ↔ GEO links** (e.g. content rendered by JavaScript hurts indexing, snippets and AI citations at once). | Cluster by `tags` + template_id + fact IDs, then LLM names each cluster |
| 6 | **Action Plan & Blocked Work** | 30/60/90-day sequence; the **AEO work queue** and **GEO work queue** (replacing old agents 16 and 24), each split into *actionable* vs *research*; **blocked items** with what unblocks them (a missing fact, an access grant, an API key); X1 brief candidates | Dependency ordering + `missing_facts` + effort |

### Priority score (section 2)

```
priority = severity_weight × confidence_weight × reach × key_page_boost ÷ effort_weight

severity_weight:    critical 8 · high 4 · medium 2 · low 1
confidence_weight:  confirmed 1.0 · likely 0.8 · hypothesis 0.4
reach:              1 + log2(pages affected)           (site-wide issues count all sampled pages)
key_page_boost:     1.5 if any key page is affected, else 1
effort_weight:      S 1 · M 2 · L 4
```

Items with `missing_facts` go to "Blocked" in section 6 instead of section 2, however high they score.

### De-duplication rules

1. Same fingerprint → one item; keep the highest severity and list every contributing agent.
2. Different checks on the same element with the same cause tag → grouped under one action (e.g. S3 title issue + S4 H1 issue on the same template becomes "fix the service-page template head").
3. An observation that conflicts with a check (e.g. G4 shows the page is cited while G2 rates it weak on facts) is reported in section 4 as a tension, not silently dropped.

### Narrative guardrails

- The LLM only sees structured findings, never raw HTML, so it can't introduce new claims.
- Every generated sentence must cite finding IDs. The validator drops any sentence that doesn't.
- Two versions are produced: **internal** (full detail, IDs, confidence) and **client** (plain language, no IDs; used on the share page).

---

## Agent run vs full run

| | Agent run | Full run |
|---|---|---|
| Output | Agent Report(s) | Run Report = pillar panel + Intelligence Report + all Agent Reports |
| Intelligence layer | Not run: one agent can't be synthesized across pillars | Runs |
| Readiness | That agent's own scorecard only | All three pillars |
| Share page | Optional: that agent's approved patches only | All approved patches + client-version intelligence summary |
