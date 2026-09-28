# Implementation plan: reliable agents and simpler execution

Date: 2026-09-27
Status: proposed implementation plan; no runtime changes made
Basis: local code review, 78 passing Python tests (1 DB integration test skipped), successful Next.js production build, and isolated reproductions of failure paths.

This plan takes priority over adding agents in `12-agent-build-plan.md` until the reliability gates below pass. It does not claim that live providers or Vercel deployment have been verified during this review.

## 1. Is the codebase overbuilt?

Partly. The main problem is uneven investment: execution flexibility is relatively advanced while report correctness, budget enforcement, and the user workflow remain incomplete.

The 20-agent design is not inherently excessive. These agents are mostly independent check modules, not autonomous services. Keep their logical boundaries and IDs; do not deploy them separately or replace them with one giant LLM prompt.

| Keep | Why |
|---|---|
| Collectors separate from diagnosis agents | Evidence can be reused and findings remain inspectable. |
| Read-only agent context and shared libraries | Avoids hidden agent chains and duplicated logic. |
| Pydantic schemas and versioned prompts | Makes changes reviewable and testable. |
| Postgres, existing task table, and BlobStore | Already implemented; another queue or storage framework is unnecessary. |
| Deterministic checks and fixture-based tests | Cheap, reproducible behavior before adding model judgments. |
| Findings, patches, and human review as separate concepts | A recommendation must not silently become a published change. |

| Simplify or defer | Concrete change |
|---|---|
| Three production execution paths | Support one production runner. Keep inline execution as a test/development adapter. |
| Self-chaining HTTP dispatch | Prefer the existing long-running worker if hosting permits it. Keep HTTP execution experimental until deployment and recovery tests pass. |
| Task expansion everywhere | Keep the current task graph during repairs. Use one unit per agent unless measured runtime or retry cost justifies smaller units. Keep per-query search units because they avoid re-buying completed searches. |
| Broad framework additions | No microservices, external broker, agent framework, plugin system, or generic policy engine for this repair. |
| Building nine more agents now | Pause expansion until existing agents meet the acceptance gates. |
| Elaborate narrative synthesis | Keep deterministic scoring and priority calculation authoritative. Model-written summaries are optional presentation. |
| Premature dashboard breadth | First support create run, progress, evidence/report review, patch approval, and sharing. Defer meters and elaborate analytics. |

### Hosting choice: preserve the existing constraint explicitly

Recommended operational shape: Next.js UI + FastAPI API + one Python worker, using the existing Postgres queue and storage. The API and worker remain the same codebase. This requires a machine/service capable of keeping the worker running; it is not presented as a Vercel Hobby background process.

If Vercel-only execution is still mandatory, retain the HTTP runner and accept the extra reliability work: durable dispatcher heartbeat, expired-lease recovery, invocation status checks, per-run concurrency enforcement, and route verification including `/r/*`. Do not count fire-and-forget requests as guaranteed task delivery.

No hosting migration or deletion of the HTTP runner is authorized by this document. Reliability phases 1–4 apply to either choice.

## 2. Target contract for every agent

1. A pass requires actual evaluation of relevant evidence. Empty inputs, unavailable models, invalid responses, and skipped evaluation cannot become passes.
2. A confirmed failure can still be reported from partial evidence, but unevaluated items must remain visible in coverage.
3. Distinguish task execution status from diagnostic status: a task may finish successfully while its checks remain unverifiable. A run must disclose incomplete diagnostic coverage.
4. Each check records expected, examined, verifiable, and skipped units where that population is known. Never invent a denominator for unknown site-wide coverage.
5. Every finding resolves to stored evidence. Derived observations reference their input evidence and describe the derivation. Absence findings identify the inspected scope.
6. Every patch targets exactly one intended element or an explicitly supported file/head insertion target, uses supported facts, and survives validation before review.
7. Site-stated, team-confirmed, conflicting, inferred, and model-generated facts stay distinguishable. Schema claims alone are not confirmed truth.
8. Real search observations, model knowledge, and simulated search remain separate in reporting and measurement history.

## 3. Phase 0 — establish the repair baseline

Scope: inventory, regression cases, and development checks. Do this before refactoring.

- Record the implemented baseline from `engine/registry.py`: 11 agents, 9 collectors. Update the stale status document, which still lists S4 as unbuilt.
- Inventory each registered check as implemented, heuristic, partial, or unavailable. Agent registration alone must not imply full implementation.
- Add regression tests for the reproduced issues: zero-evaluation passes, `15%` becoming `5%`, repeated crawler execution, task-local budgets, missing-agent coverage, ambiguous patch locators, and shared bundle overwrites.
- Use isolated test databases for queue/migration tests. Do not enable write tests against the configured client database by default.
- Exclude `.data`, `.venv`, and Python-generated folders from ESLint's traversal; preserve source lint coverage.
- Establish a source-control checkpoint without including secrets, captured client data, or generated files.

Acceptance: baseline defects fail focused tests; existing tests retain their meaning; normal lint scans only intended files.

## 4. Phase 1 — fix diagnosis honesty first

Primary files: `engine/agents/`, `engine/schemas.py`, `engine/reports.py`, `engine/intelligence.py`, `engine/registry.py`.

### Shared result and scoring changes

- Add a small shared helper for unavailable checks and explicit coverage bookkeeping. Avoid a new agent abstraction.
- Validate judgment labels with enums and require outputs for the requested question/page IDs. Missing or invalid items become unverifiable, not implicitly complete.
- Pass the requested agent IDs and task outcomes into report synthesis. Failed agents remain in coverage even when they returned no findings.
- Calculate coverage from the requested applicable checks, including failed/unavailable checks. Exclude genuinely not-applicable checks with a recorded reason. Where applicability is unknown, report it as unknown rather than dropping it silently.
- For a selected-agent run, label readiness as selected-check readiness; never imply that it covers the full pillar.
- Reconcile page aggregation with the matrix: track page outcomes before computing the specified percentage bands. Preserve individual critical key-page failures even when most pages pass.
- Include scoring/check versions so scores generated under different rules are not silently compared.
- If there are zero verifiable checks, return no score and a plain explanation.

### Repair checklist for all 11 registered agents

| Agent | Required work |
|---|---|
| S1 Crawl & Index Health | Distinguish fetch failures from valid non-HTML pages; prevent empty HTML samples from passing content checks. Keep sampled scope explicit. Validate canonical/robots recommendations before patches are accepted. |
| S3 Search Metadata | Replace substring number matching. Record the unreviewed portion of pages beyond the LLM limit. Require supported facts for every generated option; represent alternatives so conflicting title options cannot all be published together. |
| S4 On-Page Content | Do not treat missing content or missing judgments as passes. Keep SERP-snippet comparisons visibly provisional. Fixed word counts may be descriptive heuristics, not claims of required content length or competitor-relative quality. |
| S7 Internal Linking | Keep absence conclusions limited to the sampled graph. Validate source text and destination for each link suggestion. Test redirect aliases, query-bearing URLs, and incomplete crawl coverage. |
| S8 Structured Data | Parse proposed JSON-LD, verify facts against the correct page/entity, and handle new-block insertion separately from replacement. Test conflicting entities and missing facts. |
| S10 Trust | Keep sector requirements in rule packs; mark unavailable model review as unverifiable. Separate visible disclosure checks from legal-compliance conclusions. Exercise all four archetypes. |
| A1 Answer Coverage | Fix empty/failed/partial model responses producing passes. Implement A1.03 accuracy against relevant fact-sheet entries, or leave it explicitly unavailable. Record per-question outcomes and safely parse passage references. Missing answers without facts produce fact requests. |
| A2 Answer Structure | Separate observable formatting checks from subjective judgments. Use the shared fact and patch validation paths. Test conflicting edits to the same section and unavailable model output. |
| G1 AI Access | Without rendered evidence, raw/rendered parity is unverifiable; raw-HTML warning signs may be reported separately as likely observations. Replace G1.05's current presence-of-rendered-file shortcut with an actual fact comparison. |
| G2 Citable Facts | Validate claim-to-source relationships and conflicting values in context. Keep original-data judgments distinct from objective facts. Record the actual provider/model used for second opinions and disclose when it is not independent. |
| G5 Brand Accuracy | Fix zero-evaluation passes. Count analyzed answers per surface. Preserve uncertainty when facts are missing. Move hospitality-specific offering keys into archetype packs. Verify second-opinion provenance and never interpret absence of a contradiction judgment as proof of correctness. |

Acceptance: every registered agent has empty-input, missing-evidence, and unavailable-LLM cases where relevant. Zero evaluation produces zero unsupported passes. Failed agents visibly reduce run coverage.

## 5. Phase 2 — centralize evidence and patch validation

Primary files: `engine/validation.py`, `engine/lib/grounding.py`, `engine/lib/locators.py`, `engine/output/patcher.py`, agent patch builders.

- Give the validator a read-only snapshot resolver, not just a list of page URLs.
- Resolve evidence IDs and reject references outside the snapshot. Update existing agents that currently supply only free-form excerpts.
- Verify quoted text against its referenced passage. Treat excerpt matching as necessary evidence, not proof that the conclusion follows from it.
- Parse numbers as complete values with units and meaning: percentage, currency, date, count, distance. Normalize safe formatting variants without permitting `5` to match `15`.
- Bind facts to their subject and field: a room count must not justify a price; an old rate must not justify a current one. Reject contradictory or unsupported generated claims. For high-risk drafts, use constrained facts/templates and require human review; word overlap is not factual proof.
- Escape generated text before inserting it into HTML and allow only the intended markup for each patch type.
- Require exactly one locator match, verify the expected original value/hash, and reject ambiguous targets. Define explicit rules for legitimate insertions into the head or missing JSON-LD blocks.
- Detect overlapping patches, alternative drafts, and remove/edit conflicts before building a bundle.
- Validate JSON-LD, supported file formats, title/description constraints, and agent ownership.
- After rejecting patches, remove or invalidate dangling patch references in findings and reports. Retain a reason for rejection.
- Keep the patcher as a second defensive check; it should not be the first place a bad patch is discovered.

Acceptance: invented evidence, mismatched facts, ambiguous targets, invalid markup, and conflicting edits are rejected with specific reasons. A supported edit is applied only to the intended element.

## 6. Phase 3 — make execution repeatable and spending bounded

Primary files: `engine/store.py`, `engine/orchestrator/{repo,executor,runner}.py`, `engine/llm/client.py`, `engine/integrations/search.py`, collectors, new SQL migrations.

### Retry and lease safety

- Give pages a stable identity within a snapshot and evidence a stable collector/work-unit/output identity. Preserve meaningful URL variants; do not merge URLs using an overbroad normalization rule.
- Stage task output, then commit it under the current lease token. A worker whose lease was replaced cannot publish evidence, reports, children, or run status.
- Use unique constraints and upserts for logical outputs. Keep attempt history separate from accepted evidence.
- Make barrier expansion and task completion atomic. Test a crash before and after every durable write boundary.
- Enforce actual remaining concurrency slots per run rather than checking the same pre-claim count for every selected task.
- Preserve partial evidence explicitly; do not mark incomplete collectors as fully reusable.

### Shared budgets

- Give runs explicit, validated budget defaults and configurable API limits.
- Reserve provider calls and token allowances atomically in Postgres before dispatch; all tasks and retries use the same run allowance.
- For tokens, reserve a conservative input/output bound, limit output to the available allowance, and reconcile against provider usage. Count repair and fallback calls too.
- If a request times out after it may have reached a provider, retain a conservative charge/reservation until reconciled. Do not assume failure means zero cost.
- Enforce provider account-period quotas separately from per-run budgets. Counters alone are not enforcement.
- Budget exhaustion stops new paid work and marks dependent checks unavailable/partial while retaining valid completed work.

### Implementation approach

Keep the existing queue and task graph while repairing these guarantees. Choose one supported production runner, add its recovery tests, and only then consider removing unnecessary adapters. Do not combine correctness repairs with a wholesale queue rewrite.

Acceptance: replaying a task leaves accepted pages/evidence/results unchanged; stale workers cannot overwrite output; concurrent requests cannot exceed reserved budget limits; a restarted worker resumes the run without duplicated accepted work. External providers may still charge an ambiguous timeout; disclose that limit.

## 7. Phase 4 — truthful measurements and immutable sharing

Primary files: `engine/llm/client.py`, `engine/collectors/ai_collectors.py`, `engine/output/{bundle,share,viewer}.py`, `engine/api/app.py`.

### AI observations

- Separate analytical LLM caching from measurement probes. A fresh measurement must execute a new probe; reuse is an explicit choice.
- Preserve original capture time, model/provider, prompt version, measurement ID, and cache provenance. Never relabel an old response as newly captured.
- Include provider/model configuration and effective prompt content in analytical cache keys; invalidate incompatible entries.
- If repeated samples are enabled, give each sample an identity and prevent the cache from collapsing them into one answer.
- Show surface-specific denominators. Do not blend simulated search, model knowledge, and real retrieval into a single visibility claim.

### Published shares

- Store each bundle under a new immutable bundle ID, not only the run ID. Each share token references one exact bundle.
- Separate internal preview and client publication records. Internal previews may include proposed patches; client publications include only explicitly reviewed patches.
- Build and validate the complete bundle before creating an active share record. Failed publishing must not mutate an existing share.
- Add minimal patch approve/edit/reject and share create/revoke endpoints with authorization and reviewer attribution.
- Persist edits in one authoritative patch representation so the reviewed content is exactly what gets published.
- Preserve expiry, revocation, noindex, and sandbox protections; verify production routing and origin isolation. Test untrusted markup against the allowed preview behavior.
- Make annotation controls keyboard-operable and provide focus/close behavior; clicking arbitrary highlighted elements cannot be the only access method.

Acceptance: creating a later internal preview cannot change an existing approved client link. A newly dated measurement cannot silently contain an older cached answer. Unauthorized/unreviewed patches cannot enter client publications.

## 8. Phase 5 — render real pages and finish the minimum user workflow

- Implement one rendering path for the selected deployment. With a worker host, prefer running a browser from the worker rather than introducing a renderer service solely for abstraction. If Vercel-only requires a separate renderer, keep the contract narrow and test it independently.
- Apply crawl URL protections to browser navigation, redirects, and subresources; browser rendering must not bypass outbound-network restrictions.
- Bound pages, runtime, response sizes, and browser concurrency. Store raw and rendered content with explicit status and capture provenance.
- Compute G1 comparisons from those captures. Build previews from rendered HTML where available and label raw-only fallbacks.
- Build only the operational screens: client/run creation, progress, report with evidence, patch review, and shares.
- Provide visible missing-data and failed-task states. Avoid a green completed screen when large parts of diagnosis were unavailable.
- Keep publication manual during stabilization. No automated live-site edits.

Acceptance: an analyst can run an audit, inspect its evidence and limitations, review changes, and publish a stable preview without CLI or direct database edits.

## 9. Testing and release gates

| Layer | Required verification |
|---|---|
| Agent correctness | Existing golden fixtures plus empty, partial, contradictory, malformed, and unavailable-input cases. |
| Cross-sector behavior | Hospitality, loans, retail, and logistics fixtures; include multiple entities/locations and a JavaScript-heavy page. |
| Evidence and patches | Forged IDs, contradictory facts, numeric boundaries, duplicate selectors, stale hashes, overlapping edits, safe markup, missing insertion targets. |
| Database integration | Retry/crash recovery, concurrent claims, lease replacement, budget reservations, barriers, and immutable publication using an isolated DB. |
| Whole workflow | Create run through review and share, including partial completion and restart recovery. |
| Frontend | Source lint, production build, and browser tests for the implemented workflow, keyboard access, and narrow screens. |
| Live calibration | After offline gates, use approved bounded provider calls on more than one sector and review findings against saved evidence. Record false positives and missing diagnoses, not just successful API responses. |

Do not add tests that merely repeat constants or assert a helper was called. Each new test must capture a meaningful failure or acceptance condition.

Release gates:

1. No known zero-evaluation pass paths in registered checks.
2. Scores disclose missing requested agents and sampled scope.
3. Unsupported facts and ambiguous/conflicting patches cannot pass publication validation.
4. Task replay, restart, and concurrent budget tests pass against Postgres.
5. Shared bundles remain unchanged after later builds.
6. The supported deployment's execution and share routes are verified end to end.
7. Update build status to distinguish implemented, tested locally, and verified live.

## 10. Migration and delivery sequence

Suggested implementation batches, each independently reviewable:

1. Baseline regressions and check inventory.
2. Agent unavailable/partial handling, with A1 and G5 first.
3. Coverage and scoring corrections.
4. Shared factual/evidence/patch validation and agent migration.
5. Stable evidence identities, transactional task publication, and lease fencing.
6. Shared provider budgets and usage accounting.
7. Measurement cache provenance and immutable share bundles.
8. Supported-runner recovery and deployment verification.
9. Rendering, patch-review API, and minimum analyst workflow.
10. Cross-sector calibration, documentation, then remaining agents.

Use additive schema migrations first. Inspect and reconcile existing duplicate data before adding uniqueness constraints; preserve historical captures and do not silently rewrite old reports. Version changed report/scoring contracts. Roll out the repaired path behind configuration where useful, and remove legacy execution paths only after equivalent recovery tests pass.

Old reports should be marked as generated by the earlier engine version and offered a rerun. Do not retroactively label them validated by the new rules.

The nine missing agents are S2, S5, S6, S9, A3, A4, G3, G4, and G6. C8, C11, C12, and X1 remain separate scope. Resume that work after the reliability gates, prioritizing measured customer needs rather than reaching an agent count.

## 11. Completion definition

The repair is complete when the existing engine can fail honestly, retry safely, stay within reserved spending limits, and publish only validated reviewed changes through one supported deployment path.

Success is not more agents or more infrastructure. It is an audit whose findings, coverage, proposed fixes, and capture dates can be trusted and reproduced.
