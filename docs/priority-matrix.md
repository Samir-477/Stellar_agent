# Intelligence priority matrix

The intelligence layer assigns an **action lane** before ordering findings. This keeps a low-impact quick fix from outranking a high-impact issue, and keeps uncertain or dated observations out of the fix queue. The implementation is in [`engine/intelligence.py`](../engine/intelligence.py). This matrix ranks findings that agents actually reported; it cannot discover an issue an agent missed or prove an agent's premise is correct.

| Evidence confidence | Critical impact | High impact | Medium impact | Low impact |
|---|---|---|---|---|
| Confirmed | Now | Now | Next | Later |
| Likely | Now, verify while acting | Next | Next | Later |
| Hypothesis | Investigate | Investigate | Investigate | Investigate |

An agent/check that does not count toward readiness is a **dated observation**. It goes to **Monitor** regardless of reported severity or confidence. Examples include sampled SERP positions, AI mention rates and AI citations. `unverifiable` and `not_applicable` findings do not enter the priority queue; they remain in coverage and attention notes.

Severity sets the impact column. Both severity and confidence are **reported by the agent**, not independently certified by the matrix. Within each lane, the existing harm-per-effort score orders work by reported confidence, fail versus warning, page reach, entry/key-page importance and effort. That score cannot move an item to a higher lane. Ties break by check, page and title for reproducible output.

The executive summary's **lead blocker** follows the same rule. It comes from the first lane that has fixes (Now, then Next, then Later). Within that lane it is the most severe item, then the one with the highest harm regardless of effort. A widespread Next item therefore cannot headline the report while Now has items. In the Shivalik Chail run, the lead blocker was a likely JavaScript-content issue in Next (W16); under this rule it is the confirmed Now item W1.

`missing_facts` means **prerequisites to review**, not proof that the whole issue is blocked. The report displays them separately and keeps the issue in its impact lane. A future typed dependency field can distinguish an actual client-fact blocker from an access grant, external-platform task or editorial decision. The automatic 30/60/90-day claim is removed from the Markdown report: lanes suggest order, while dates need a human estimate.

The report now has five lanes:

| Lane | Reader action |
|---|---|
| Now | Assess and address verified high/critical issues first. |
| Next | Plan important but less certain or medium-impact fixes. |
| Later | Tackle low-impact improvements after higher-value work. |
| Investigate | Gather enough evidence before recommending a fix. |
| Monitor | Track dated search/AI observations without calling them site defects. |

The structured report preserves the existing `now`, `next` and `later` priority keys and adds `investigate` and `monitor`. Each work item includes `priority_reason` and `prerequisite_review`. The action plan uses `now`, `next` and `later` instead of automatic `30_days`, `60_days` and `90_days` promises; it also adds `prerequisites_to_review`, `investigate` and `monitor`. `blocked` remains for compatibility but is not inferred from missing facts. `priority_matrix_version` marks reports produced with these rules. The Markdown report shows confidence and the matrix reason for each item.

Examples from the previous Regalia Agra report, conditional on the agent finding being sound:

| Finding | Matrix route | Reason |
|---|---|---|
| Confirmed wrong-hotel structured data (S8.04, high) | Now | Direct page/schema mismatch with high reported impact. |
| Likely missing raw-HTML content (G1.04, high) | Next | A renderer was not configured, so raw-versus-rendered parity remains uncertain. |
| Hypothesized cause of a content gap | Investigate | A proposed explanation is not yet a verified fix. |
| AI share-of-voice sample (G3.01, high) | Monitor | One dated sample is a measurement, not a persistent site defect. |
| Missing query-theme page with prerequisites (S5.01, medium) | Next + prerequisite review | Confirm the business actually offers and wants to target the theme before making a page. |

The wrong canonical on the Regalia Agra page was **not reported by S1** in that run, so this matrix cannot promote it. S1 needs a separate same-entity canonical check. Likewise, the matrix cannot certify S8's schema requirements or G6's Knowledge Panel expectation; those checks require their own rule corrections before the overall output can reach the quality target.

Validation: focused tests cover lane routing, effort not overriding impact, hypothesis/observation isolation, conservative corroboration and prerequisite handling. Run `python -m pytest tests/test_intelligence.py -q -p no:cacheprovider`, then the full suite. No live crawler, database or LLM call is required for these tests.
