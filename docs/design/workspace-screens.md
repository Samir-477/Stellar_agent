# Workspace screens: what each part shows and why

Built on 2026-09-28 from the user's UI instructions and `agent-workspace-design-sense.md`. This file records the screens as they exist, the job of each component, and where its data comes from. Change it when a screen changes.

## Shared system

- **Type:** Space Grotesk for headings, DM Sans for reading and controls, Space Mono only for IDs, URLs, timestamps and figures. The fonts are self-hosted in `src/app/fonts/`. Every size comes from the named scale in `globals.css` (`text-2xs` to `text-7xl`); there are no one-off pixel sizes. The scale was set one step smaller after the user's review (2026-09-28), and the spacing loosened.
- **Density:** content is kept loose. Use generous padding inside cells and gaps between tiles. Report sections are closer together than marketing sections. Long lists are paginated (`pager.tsx`): priority items 8 at a time, check outcomes 8, agent changes 5, and sessions 10.
- **Colour:** tokens are in `src/app/globals.css` (`@theme`). One signal green means "active or done"; amber means "needs review"; red means "failed". Every state also has a word, so colour is never the only signal.
- **Structure:** cells that touch show peers (disciplines, agents, readiness). A rail with a detail pane lets you explore one item without losing context (priority lanes, agents, preview pages). Tables hold comparable rows (sessions, signature tables). Numbered steps appear only where the order is real (run stages).
- **Motion:** it marks the running stage (moving route line, pulsing node), slides the active tab indicator, and opens details. It is off under reduced motion.
- **Status words:** `src/components/workspace/status.tsx` holds the shared vocabulary: severity on a four-step scale, confidence (the agent's own rating), check status, and component state.
- **Brand and navigation:** the Stellar Agents mark shows three evidence paths joining into one finding and one output. The shared header uses a compact Home/Sessions switcher, a distinct New run action, and a separate sign-out control. On smaller screens the navigation moves to a second row.

## Sign in (`/login`)

`/` sends signed-out people here and signed-in people to Home. The page uses the local demo session only (see `AGENT_HANDOFF.md`).

## Home (`/home`)

| Part | Job | Data |
|---|---|---|
| Hero and focus chooser | States the product outcome and lets the user start an SEO, AEO, GEO, or all-agent run directly. Each focus row names its outcome and actual agent/check count. | `GET /agents`, links to `/runs/new?agents=…` |
| Four-stage journey | A deep-green connected sequence shows the real order of a run. Numbered stages explain the work and point to the screen where its result appears. | Static copy |
| Collector tiles | Twelve equal tiles in a 3 by 4 desktop grid, grouped by source: what each collector captures, its paid services, and how many agents read it | `engine/catalog.py` through `GET /collectors` |
| Agent bands | One band per discipline. Each agent card shows its question and its number of checks. Hovering or focusing a card opens its detail: how it works, an illustrative example finding, what you get, what it reads, and a link to run it alone. | `GET /agents` (`question`, `how`, `example`, `outcome`, `reads`) |
| Pick up where you left off | The three latest runs | `GET /runs` |

## New run (`/runs/new`)

- **Site form:** page URL, client name, who authorized the crawl (required and recorded), business type (or detect), and page cap. The form stays beside the agent picker while scrolling on desktop, clearing the sticky header; it scrolls inside only when the viewport is too short to show every field. On smaller screens it remains in the normal page flow.
- **Agent picker:** agents grouped by discipline with tri-state group checkboxes, plus quick picks (All 20, a single discipline, Clear).
- **Top action and plan:** Start diagnosis sits above the form. The fixed bottom bar is gone. A short top summary shows agent and collector counts; the full run plan sits below the agent picker without covering it.
- **Start:** creates or reuses a client (only when the URL, name and authorization all match), then the run, then opens the run page. It triggers paid calls, so it is used only with approval.

## Run page (`/runs/[runId]`)

**While running: the live route board** (`live-run.tsx`). It polls `/progress` every 2.5 seconds.

- **Top row, stage route:** collect, diagnose, synthesize, report; the line into the active stage moves. Beneath the route: totals for collectors done, agents done, findings saved and failed steps.
- **Top row, live activity:** sits beside the route, so progress is visible without scrolling. It has one bar per finished step and the latest steps in plain words.
- **Task counter:** labelled as planned tasks, because the plan grows while the run works.
- **Evidence tiles:** the collectors as a 4-column grid, with their real step counts and retries.
- **Agent tiles:** a 5-column grid ordered SEO, AEO, then GEO. A finished agent's report opens in a side sheet before the run ends.
- **Archetype confirmation panel:** appears when the run pauses.

**When finished: three layers.** A run log link reopens the board, frozen, for audit.

- **Intelligence:**
  - Readiness cells show each score on its band scale, plus the share of checks that could be verified.
  - The executive summary switches between team wording and client wording. It reads in one column; three leads sit below it. In team wording, item codes link into the priority list.
  - Three leads are chosen by rule: fix first, biggest opportunity, watch. A note appears if the report predates the current lead rule.
  - The priority list has five compact lanes as tabs across the top, each with its count and accessible meaning. It has a filter by discipline, rows that expand to show the action, lane reason, prerequisites and evidence, and paging.
  - Shared causes appear as tiles showing the six largest by default; the chosen cause opens below with its items and the one change to try first.
  - One table with two tabs covers what's working and what couldn't be checked. It is paginated and filterable by agent.
  - The limits of the run sit in a collapsed section.
- **Agents:** discipline buttons and a horizontal agent picker replace the long rail. Previous/next buttons move through a discipline. The verdict and scorecard stay visible; section buttons separate findings, evidence and scope, changes, and passed checks to shorten the reading path. Agent changes still page five at a time.
- **Output:** a page selector and previous/next buttons sit above a full-width page preview. The changes on that page (placed or not, with the reason) open below the preview; views remain original, annotated, fixed, and under the hood as code diffs.
  - The page is loaded from the engine through a signed, expiring link, in a sandboxed frame.
  - The preview is internal: it includes changes nobody has reviewed.

## Sessions (`/sessions`)

A table of runs: client and page, agents, start time and duration, status, readiness per discipline, and the Now and Next counts. You can search by client or URL, filter by status, and page through ten rows with controls above and below the table. Finished runs have a Hide action with confirmation; Hidden lists retained runs with a Restore action. Archive state is persisted in `runs.archived_at` after migration `0005_run_archive.sql` is applied.

## Not built yet

- Review states for findings and changes, such as confirmed, disputed or dismissed.
- A client-facing share view.
- Production sign-in.
- The per-agent bespoke visualisations listed in the design brief: signature tables use one shared, typed renderer for now.
- Archiving of page assets, so captured pages may render without their stylesheets.
