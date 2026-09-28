"""Builds the 6-section Agent Report (docs/spec/05) deterministically, without an LLM."""

from __future__ import annotations

from engine.agents.base import Agent
from engine.schemas import AgentReport, AgentResult, CheckStatus, Confidence, Finding, Severity

_SEVERITY_RANK = {Severity.CRITICAL: 0, Severity.HIGH: 1, Severity.MEDIUM: 2, Severity.LOW: 3, Severity.INFO: 4}
_STATUS_RANK = {CheckStatus.FAIL: 0, CheckStatus.WARN: 1, CheckStatus.UNVERIFIABLE: 2,
                CheckStatus.NOT_APPLICABLE: 3, CheckStatus.PASS: 4}


def check_statuses(agent: Agent, findings: list[Finding]) -> dict[str, CheckStatus]:
    """Worst status per check; checks with no finding count as unverifiable."""
    worst: dict[str, CheckStatus] = {}
    for f in findings:
        if f.check_id not in worst or _STATUS_RANK[f.status] < _STATUS_RANK[worst[f.check_id]]:
            worst[f.check_id] = f.status
    return {c.id: worst.get(c.id, CheckStatus.UNVERIFIABLE) for c in agent.checks}


def _item(f: Finding) -> dict:
    return {
        "check_id": f.check_id, "title": f.title, "severity": f.severity, "confidence": f.confidence,
        "pages": f.scope.pages[:10], "page_count": len(f.scope.pages),
        "evidence": [e.model_dump(exclude_none=True) for e in f.evidence[:3]],
        "impact": f.impact, "fix": f.fix, "verification": f.verification, "effort": f.effort,
        "patch_keys": f.patch_keys,
    }


def build_agent_report(agent: Agent, result: AgentResult) -> AgentReport:
    statuses = check_statuses(agent, result.findings)
    scorecard = {s.value: 0 for s in CheckStatus}
    for status in statuses.values():
        scorecard[status.value] += 1

    fails = sorted((f for f in result.findings if f.status == CheckStatus.FAIL),
                   key=lambda f: (_SEVERITY_RANK[f.severity], -len(f.scope.pages)))
    attention = [f for f in result.findings if f.status in (CheckStatus.WARN, CheckStatus.UNVERIFIABLE)
                 or (f.status == CheckStatus.FAIL and f.confidence == Confidence.HYPOTHESIS)]
    fails = [f for f in fails if f.confidence != Confidence.HYPOTHESIS]
    passes = [f for f in result.findings if f.status == CheckStatus.PASS]

    total = len(agent.checks)
    if fails:
        top = fails[0]
        verdict = (f"{scorecard['fail']} of {total} checks fail. The most serious issue is: "
                   f"{top.title.rstrip('.')} ({top.severity}).")
    elif scorecard["warn"]:
        verdict = f"No check fails; {scorecard['warn']} of {total} need attention."
    elif scorecard["pass"]:
        verdict = f"All {scorecard['pass']} verifiable checks pass."
    elif scorecard["unverifiable"]:
        verdict = f"Nothing could be verified: {scorecard['unverifiable']} of {total} checks lack evidence."
    else:
        verdict = "Nothing to assess: no check applies to this site's evidence."

    next_checks = [f"{f.check_id}: {', '.join(f.missing_facts)}" for f in result.findings if f.missing_facts]
    next_checks += result.coverage.skipped
    next_checks += [f"{f.check_id}: {f.title} (re-run once the missing data is available)"
                    for f in result.findings if f.status == CheckStatus.UNVERIFIABLE]

    return AgentReport(
        agent_id=agent.id, agent_name=agent.name, verdict=verdict, scorecard=scorecard,
        scope_and_evidence={"coverage": result.coverage.model_dump(), "signature_table": result.signature_table,
                            "check_status": {k: v.value for k, v in statuses.items()}},
        issues_to_fix=[_item(f) for f in fails],
        needs_attention=[_item(f) for f in attention],
        whats_working=[{"check_id": f.check_id, "title": f.title,
                        "evidence": [e.model_dump(exclude_none=True) for e in f.evidence[:2]]} for f in passes],
        proposed_changes=[p.model_dump(exclude_none=True) for p in result.patches],
        missing_facts_and_next_checks=next_checks,
    )
