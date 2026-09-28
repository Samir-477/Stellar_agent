# Agent workspace: design sense and implementation plan

Status: design brief for the dashboard, not a claim that these screens or supporting APIs exist. Read this before designing or building the private UI. The public landing page and the client's audited website are different surfaces.

## 1. Product, audience and job

This product examines a client website with 12 evidence collectors and 20 diagnosis agents, then combines their findings into an intelligence report and a reviewable change preview. Internal analysts configure and inspect runs. Client stakeholders need a clear, defensible explanation of what was found, what was not checked, what should happen next, and what a proposed change would look like.

The main journey is **sign in → choose a client and scope → run → watch real progress → inspect and challenge evidence → review proposed edits → show an approved client view**. A successful screen helps the user make its next decision. A screen filled with data but no clear decision has failed.

Use two presentation modes over the same underlying evidence:

- **Workspace (internal):** full agent outputs, raw evidence, check status, confidence, coverage, limitations, patch review, failures, and diagnostics.
- **Client view:** plain-language synthesis, exact scope/date, approved recommendations and previews, and honest limits. Do not expose speculative drafts as verified fixes.

## 2. What the supplied references actually teach

The 15 supplied Stellar AI Retail images are **visual and interaction references, not a brand kit to copy**. They share a disciplined system:

| Observed device | What it communicates | Adaptation for this product |
|---|---|---|
| Large, left-aligned editorial headline with generous whitespace | One idea owns each section | Give each screen one clear question or decision; compress scale inside the working dashboard. |
| Near-white and very pale mint fields, deep forest sections, saturated green accents | Quiet reading surfaces; emphasis through contrast | Use neutral report surfaces; reserve deep forest for one narrative or transition moment, not a permanent dark dashboard. |
| Fine lines, rectangular adjoining panels, minimal corner radius | Relationships and boundaries are visible | Let borders group comparable data. Avoid floating card grids with repeated shadows. |
| Pale square grid behind a live workflow illustration | A system is operating | Use the grid only where a pipeline or dependency map is shown, not behind long report text. |
| Sequential, numbered stages and connector arrows | A real path with order | Use for crawl → evidence → agents → intelligence → preview. Do not number independent agents as if they run in one fixed order. |
| Split layout: choice rail at left, large explanation at right | Explore one item without losing context | Use for agent selection, report drilldown, and evidence review. |
| Bordered comparison rows and before/after toggle | Compare consequences | Use for source-vs-finding and original-vs-proposed copy; show both states clearly. |
| Sparse icons and muted supporting text | Scan without decoration | Icons only where they disambiguate status, evidence type, or action. Pair icons with labels. |

The references are spacious marketing pages. An analyst console needs higher information density. Keep their **order, typography, color restraint, and purposeful panels**, while shrinking whitespace and headlines during operational work. Do not reproduce their logo, wording, customer claims, or eight-product layout.

## 3. Design thesis and visual tokens

The distinctive motif is an **evidence route**: a visible line connecting source, agent judgment, intelligence decision, and proposed change. The line may appear in a run map, a finding detail, and a preview inspector. It must represent a real traceable relationship; it is not decoration.

Proposed tokens, subject to visual QA against the supplied references:

| Role | Token | Use |
|---|---|---|
| Canvas | `#F7FAF7` | Spacious overview and empty states |
| Paper | `#FFFFFF` | Reading and report surfaces |
| Ink | `#071B12` | Headings, primary data |
| Muted ink | `#50635A` | Explanatory text, timestamps |
| Rule | `#DCE7E0` | Dividers, table structure |
| Signal green | `#007B46` | Primary action, active stage, verified route |
| Soft green | `#E4F5EA` | Selected item, positive evidence, gentle emphasis |
| Deep forest | `#00190F` | One focused narrative/pipeline section |
| Review amber | `#9A5A00` on `#FFF2D7` | Needs review, incomplete evidence |
| Error red | `#A7332C` on `#FCECE9` | Failed task or contradicted claim |

Green means **active or verified within a stated scope**, never “all findings are correct.” Priority, confidence, severity and review state are separate fields with text labels. Never use color alone to encode them. Check text contrast at 4.5:1 or better in implementation.

Typography: use a crisp contemporary sans for UI and long reading (the existing Geist installation is a practical starting point). Use a restrained mono face only for IDs, URLs, timestamps, code and metric numerals. Reference headlines are large and sentence-case; dashboard headings should be smaller and equally direct. Body copy starts at 16px, with roughly 65–75 characters per reading line. Avoid all-caps labels except short technical acronyms such as SEO/AEO/GEO.

Layout: desktop workspace shell with a narrow persistent navigation rail, a content column that changes by task, and an optional right evidence inspector. A report body is not a 12-column dashboard grid. On tablet, collapse the inspector into an overlay. On mobile, stack source, judgment and action in that order; no horizontal page scroll. Tables with many columns can use a dedicated scroll region with a first-column label and an accessible row-detail alternative.

These are layout relationships, not pixel-perfect screens:

```text
OVERVIEW
┌─ nav ─┬─ client / latest run ──────────────── New diagnosis ─┐
│       │  Collect → Diagnose → Prioritize → Preview            │
│       │  SEO 10  │  AEO 4  │  GEO 6  (select a scope)         │
│       │  Recent runs: target / scope / state / next action    │
└───────┴───────────────────────────────────────────────────────┘

RUN SETUP                         LIVE RUN
┌─ context ┬─ grouped agents ─┐   ┌─ stage rail ─────────────────┐
│ URL      │ SEO / AEO / GEO   │   │ Crawl → Evidence → Agents…   │
│ consent  │ checkboxes + job  │   │ current work / real counts   │
│ cap      │ selected summary  │   │ completed reports / blockers│
└──────────┴───────────────────┘   └──────────────────────────────┘

REPORT / PREVIEW
┌─ list/queue ┬─ conclusion or captured page ┬─ evidence / diff ┐
│ filters     │ selected finding or marker    │ source and action│
│ scope       │ context kept visible           │ review state     │
└─────────────┴────────────────────────────────┴──────────────────┘
```

## 4. Component rule: every container has a job

Choose the shape from the relationship in the content:

| Content relationship | Preferred shape | Why |
|---|---|---|
| A sequence of actual processing stages | Horizontal/vertical stage rail | Shows order, current stage and completion |
| A catalog of independent selectable agents | Grouped checklist with a detail pane | Makes scope and dependencies comparable without implying a sequence |
| Comparable checks, URLs or AI surfaces | Table or matrix | Supports scanning, sorting and filtering |
| A single finding with supporting source | Reading pane + evidence inspector | Separates claim from proof while keeping them linked |
| A cross-agent conclusion | Priority ledger / action queue | Makes decision, evidence and status explicit |
| A site page change | Original/proposed preview and text diff | Shows impact in context |
| A fact conflict | Side-by-side fact reconciliation | Makes the contradiction legible |
| One metric over time | Trend plot with values and dates | Shows change, not a decorative gauge |
| An absent or unavailable result | Explicit empty/partial state | Explains why nothing is shown and what can be done |

Do not turn each agent, priority, check or page into the same generic card. A card is justified when it is one bounded selectable object with a concise summary; otherwise prefer an aligned row, panel, rail, table, diff, or full-page reading surface. Do not use circular progress rings for readiness: they hide coverage and uncertainty.

## 5. Screen architecture and interaction contracts

### A. Sign in

Purpose: establish an actual private workspace session. Use a restrained split view: one clear sign-in form on paper and a quiet, abstract evidence-route diagram on pale mint. No fake social proof or animated background. Visible labels, password manager support, inline validation, keyboard flow and a useful error state. Provide account recovery if the chosen identity provider supports it.

**Implementation dependency:** `/login` now has a local-only Steller Agents demo sign-in (`src/app/login/` and `src/app/api/demo-auth/`). It validates a configured demo account on the server and sets a signed, HttpOnly cookie, but it is deliberately disabled in production and does not authorize any client data or FastAPI call. FastAPI currently accepts a bearer API key and permits unauthenticated local access. Choose an identity provider and implement real server-side session handling before presenting this as production login. The browser must never receive `ENGINE_API_KEY`; Next.js server routes should enforce the session and call FastAPI. Client and run access must be authorized per user/organization, not merely hidden by a route.

### B. Overview / workspace home

Purpose: answer “What does this system examine, what has run, and what should I do next?” Start with current client/run context and one primary action, **New diagnosis**. Then show a compact pipeline diagram: 12 collectors gather evidence → selected SEO/AEO/GEO agents analyze independently → intelligence combines findings → reviewed edits become a preview. A separate three-column comparison explains the distinct jobs of SEO, AEO and GEO, with actual agent counts **10 / 4 / 6** and links into the selector. Display recent runs as a table with target URL, scope, snapshot date, state, verified coverage and next action. Use an empty state that leads to creating a client/run.

The overview is not a wall of 20 agent cards. An “Explore agents” control opens the grouped catalog. Selecting a pillar or “All 20” goes to the Run page with that selection prefilled. Explain that collectors are automatically planned from selected agent evidence needs; they are not separately selectable in the initial UI.

### C. Run setup

Purpose: make scope and consequences clear before starting paid or time-consuming work. The left side holds client URL/name, archetype, crawl cap and the recorded crawl authorization. The main area holds three grouped agent lists with checkboxes, short one-line jobs, and a focused detail pane with checks, evidence needed, and limitations. Provide pillar shortcuts, **Select all 20**, and a clear summary of selected agents and automatic collectors. Keep selection editable until Start.

One agent is a valid run. Two or more agents can produce intelligence; one agent does not. A “Together run” means `type=full` with all registered agents; a custom mix means `type=agent` with explicit IDs. Do not imply that SEO/AEO/GEO run as three opaque mega-agents. Show estimated stages and provider usage as estimates only when derived from configuration or historical data. A required authorization field must be phrased accurately: who authorized this crawl; do not silently assert site ownership. Clicking **Start diagnosis** creates the run once, disables duplicate submission, and navigates to `/dashboard/runs/[runId]`.

The run page must handle an archetype-confirmation pause: explain what was inferred, show the evidence, allow the user to confirm/correct, then resume via the existing endpoint.

### D. Live run / loading experience

Purpose: answer “Is it progressing, what is happening, can I leave, and what needs me?” Use a **live route board**, not a spinner theater. Show a stable stage rail (crawl, parse/facts, external captures, selected agents, intelligence). Within the active stage, show real completed/running/pending/partial/failed task counts and named work when exposed by an API. Agent rows move to completed as reports become available; completed reports can be opened before the whole run ends. A small evidence-reveal area can show truthful, non-sensitive facts as they arrive (e.g., pages fetched, query captures, reports saved), with captured time and scope.

Keep a modest animated line/pulse only on the active stage. It stops on completion, failure, tab backgrounding and reduced-motion preference. Let the user leave and return to the run URL; no fake “82%” when task expansion makes the denominator variable. If using a progress fraction, label it `completed / currently planned tasks` and show that more tasks may be added. Long waits display the current stage, last update, and next expected handoff. Partial/failure states preserve completed outputs and explain what could not be verified.

**Implementation dependency:** `GET /api/v1/runs/{run_id}` currently returns aggregate `task_counts`, status and note. It does not expose a structured per-stage event stream. Build a safe progress endpoint or projection from task rows before promising named live steps, retries or timestamps. Polling is acceptable initially; do not infer completion from elapsed time.

### E. Intelligence report, internal and client modes

Purpose: turn many findings into decisions without hiding uncertainty. Start with a plain-language executive conclusion, then a three-column SEO/AEO/GEO readiness comparison showing **score, band and percentage of checks verifiable together**. An adjacent “What was sampled” line states pages, date, search/AI surfaces and missing measurements. Keep dated observations separate from site defects.

The main object is a **priority ledger**, grouped by Now / Next / Later / Investigate / Monitor. Each row states the problem, affected scope, severity, confidence, evidence status, source agents, prerequisite and proposed next action. Row expansion traces back to agent check and source excerpt. Support filters for target page vs sampled site, pillar, status, confidence and review state; show active filters and counts. Root-cause patterns can be a connected list showing which findings they group, not a speculative causal diagram. Client mode uses approved wording and actions only, yet keeps an accessible “Why we say this” evidence drawer and the coverage limits.

Scores never stand alone and never masquerade as “agent accuracy.” A `confirmed` label is the agent's reported confidence until independent validation exists. The Shivalik Chail live run demonstrated why: an agent said the page lacked a PIN while the captured HTML contained `171012`. The UI must allow analysts to mark a finding **confirmed / disputed / needs verification / dismissed** before it becomes client-visible; it must not visually endorse every generated claim. The 5 priority lanes are suggestions, not deadlines.

### F. Individual agent report

Purpose: let an analyst understand what one agent examined and challenge its conclusion. A common report frame preserves the six existing sections: verdict and scorecard; scope/evidence; issues to fix; needs attention; what's working; proposed changes; missing facts/next checks. The first viewport shows agent name, job, run/snapshot, checked vs unverifiable counts and the strongest finding. A left list navigates checks; the center explains the selected finding; a right inspector holds exact excerpt, URL, capture time and locator, then the suggested fix and verification method. Make pass/warn/fail/unverifiable/not-applicable visibly distinct in text.

Use the agent's **signature table** as its native visual format, not a uniform row of cards:

| Agent | Primary evidence presentation |
|---|---|
| S1 Crawl & Index | URL-by-check matrix with redirect/canonical drilldown |
| S2 Page Experience | Measured pages table with field vs lab metrics and dates |
| S3 Metadata | URL, existing title/description, proposed text and length comparison |
| S4 Content | Page outline with target query and missing subtopics |
| S5 Themes | Theme-to-owner-page map with unowned and competing themes |
| S6 SERP | Query-by-ranking table with dated competitor rows |
| S7 Links | Source → destination list with anchor text and redirect state |
| S8 Schema | Page entity tree and field-level JSON-LD diff/validation |
| S9 Local | Side-by-side name/address/phone facts by source |
| S10 Trust | Disclosure checklist with where each fact is visible |
| A1 Coverage | Question → retrieved passage → answer-state ledger |
| A2 Structure | Heading and answer anatomy, with source text beside draft |
| A3 Journey | Plan/compare/book/use journey rail with content and tool gaps |
| A4 Snippets & PAA | Query/feature/holder/opportunity table; explicit no-op state |
| G1 AI Access | Crawler rules and raw/rendered text comparison when available |
| G2 Facts | Claim/source ledger with first-hand detail and attribution |
| G3 AI Voice | Prompt × surface mention matrix with capture date |
| G4 Citations | Source-domain table, verified/proxy distinction and counts |
| G5 Brand Accuracy | Site fact vs AI-stated fact reconciliation |
| G6 Entity Footprint | Platform/profile consistency table and conflicts |

The common frame provides familiarity; the primary evidence view differs because the agents ask different questions. Never render an absent A4 opportunity as an empty broken dashboard. Explain “No eligible snippet/PAA opportunity in this capture” with scope and date.

### G. Proposed-change review and output preview

Purpose: decide whether a suggested edit is accurate, useful and safe before showing it to a client. Review has two connected surfaces: a **patch queue** (status, source finding, affected page, fact prerequisites, placement) and a **page preview** (original / proposed / under the hood). On a selected patch, keep the source claim and supporting evidence visible next to the before/after. Support edit, approve, reject, and “needs facts” with a recorded reviewer and reason once backend endpoints exist. A patch that cannot be placed gets an explicit unresolved state; it is not silently dropped or counted as a success.

The preview top bar shows page URL, capture date, review state and controls for Original, Annotated, Proposed, and Under the hood. The page selector lists only affected pages with counts. The annotation marker opens a concise inspector with issue, before/after, impact, source agent and confidence. Head tags, JSON-LD, robots and other invisible changes belong in a readable code/text diff, not a website screenshot. A split view is useful for a specific change; a full-width single view is better for inspecting layout. Let the user switch, preserving scroll position where practical.

The current output viewer is an interim FastAPI page with annotated/fixed HTML and an under-the-hood pane. It builds from captured raw HTML because the renderer is not configured, and interactive parts are frozen. `include_proposed=True` makes an **internal preview**, not an approved client share. The dashboard must keep review and publication separate. Do not promise download bundles, asset archiving, password protection, or patch editing until implemented and tested. Keep untrusted client HTML isolated in the existing sandboxed viewer/origin model; never inject it into the authenticated dashboard DOM.

## 6. Responsive, accessible and motion behavior

- Keyboard access for every selection, tab, disclosure, sort and review action; clear visible focus. Tabs retain meaningful headings and state. Touch targets at least 44 × 44px.
- Status changes use one contextual live announcement, e.g. “S3 report completed; 14 of 20 agents finished,” rather than announcing every count independently. No forced focus movement during polling.
- Motion has only three jobs: show the active run stage, preserve spatial continuity when opening a detail pane, and confirm an action. Suggested range: about 150–250ms for local state changes. Pause decorative motion when unfocused and render the final state under `prefers-reduced-motion`.
- Framer Motion/Motion for React is optional for later implementation. First use CSS for small transitions; add a motion library only if it materially improves continuity. No animated percentage without measured progress, no looping confetti, no automatic carousels on an operational screen.
- Every visualized count or score has a readable text equivalent. URLs, IDs and code wrap safely. Do not disable browser zoom.

## 7. Content and trust rules

Use UI words users understand: **Evidence collected**, **Agents analysing**, **Needs verification**, **Proposed change**, **Approved for client**, **Could not check**. Use SEO/AEO/GEO as named disciplines, and expand each on first exposure. Never say “all checks passed” when checks were not applicable or unverifiable. Show the run date on search and AI observations. Separate the target page from site-wide sample findings. Carry source URL, excerpt, agent/check ID, confidence and evidence date to every client recommendation. Show any model/proxy limitation in context, not buried in a footer.

The 2026-09-28 Shivalik Chail run is a design fixture: 25 sampled pages, 20 agent reports, readiness SEO 72/AEO 59/GEO 69, 2 Now/31 Next/14 Later/0 Investigate/7 Monitor. Its known false positive about the resort PIN code, off-target Now priorities, and 51/52 placed preview edits must appear in review-state mockups. This prevents a polished UI from disguising an incorrect report.

## 8. Build sequence and acceptance gates

1. **Foundation:** choose private product brand, lock tokens, define authenticated shell and responsive navigation. Implement real auth/session and API proxy before using production client data.
2. **Overview + run setup:** ship pillar explanation, actual agent registry selection, dependency summary, client/authorization form and create-run navigation. Verify full vs custom vs single-agent behavior and archetype confirmation.
3. **Run progress:** expose safe task-stage data, build the live route board, handle retries, partial completion, failure, resume and back navigation. Test against a recorded run with expanding task count.
4. **Reports:** build intelligence ledger and common agent frame from real JSON. Implement the 20 evidence-specific renderers incrementally, beginning with one from each pillar and the Shivalik fixture.
5. **Review + preview:** add persisted patch/finding review endpoints and permissions; then connect annotated/fixed preview and under-the-hood diff. Only approved/edited patches can enter a client share.
6. **Client mode and QA:** verify traceability, coverage language, false-positive disputes, keyboard/mobile states, contrast and reduced motion. Review screenshots at 375, 768, 1024 and 1440px. Test empty, single-agent, full, partial, failed and no-preview runs.

Acceptance is not “all content appears.” A first-time user can start a correctly scoped run; a returning user can tell what is happening; an analyst can find evidence behind any recommendation and dispute it; a client can see only reviewed conclusions and understand a proposed page change. The UI must not imply more certainty or backend capability than the run provides.

## 9. Current implementation map for the next builder

| Concern | Existing source / contract | Gap to close |
|---|---|---|
| Public Next.js frontend | `src/app/page.tsx`, `src/app/layout.tsx`, `src/app/globals.css`; Next 16.3.6 and React 19.2.8 | No private dashboard screens. Read `node_modules/next/dist/docs/` before coding due project-specific Next rules. |
| Agent catalog | `GET /api/v1/agents`, `engine/registry.py` | Render actual IDs, names, checks and dependencies; avoid hard-coded agent metadata. |
| Client and run creation | `POST /api/v1/clients`, `POST /api/v1/runs`, `engine/orchestrator/planner.py` | Build session-protected UI and clear consent/scope flow. |
| Run state | `GET /api/v1/runs/{run_id}`, archetype confirmation endpoint | Add safe stage projection for richer progress; aggregate `task_counts` already exists. |
| Reports | `/runs/{id}/report`, `/runs/{id}/agents/{agent_id}`, `/runs/{id}/findings` | Build evidence-linked internal and client views. Intelligence exists only for 2+ agents. |
| Preview | `engine/output/bundle.py`, `engine/output/viewer.py`, `docs/spec/06-output-layer.md` | Internal preview exists; patch-review API and complete product viewer do not. Keep sandbox boundary. |
| Identity and permissions | Local-only demo login in `src/app/login/`, `src/app/api/demo-auth/`; FastAPI `require_api_key` in `engine/api/app.py` | Production identity, org scoping and patch-review authorization do not exist yet. |

Sources for design decisions: supplied reference images, `docs/spec/05-output-templates.md`, `docs/spec/06-output-layer.md`, `docs/priority-matrix.md`, current API/source, and the local UI/UX Pro Max guidance for progressive feedback, accessibility, readable lines and comparison tables. The skill's generic blue/amber enterprise palette and spinner suggestion were intentionally replaced because they conflict with the supplied visual direction and the need for truthful run progress.
