"""Agent interface.

An agent reads one evidence snapshot and returns findings, patches and a
signature table. It never reads another agent's output: `AgentContext` has no
way to do that. Work splits into `plan` → `run_unit` × N → `reduce` so each
piece fits a serverless time limit (docs/spec/03).
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, ClassVar

from engine.context import AgentContext, WorkUnit
from engine.schemas import (
    AgentResult,
    CheckSpec,
    CheckStatus,
    Confidence,
    Coverage,
    EvidenceRef,
    EvidenceType,
    Finding,
    Locator,
    Pillar,
    Scope,
    Severity,
)

_SEVERITY_ORDER = [Severity.LOW, Severity.MEDIUM, Severity.HIGH, Severity.CRITICAL]


def escalate(severity: Severity) -> Severity:
    """One level up for key pages (docs/spec/04), capped at HIGH.

    CRITICAL is reserved for conditions that block crawling, indexing or AI access,
    or create legal risk; checks set it explicitly, it never comes from escalation.
    """
    if severity not in _SEVERITY_ORDER or severity == Severity.CRITICAL:
        return severity
    return _SEVERITY_ORDER[min(_SEVERITY_ORDER.index(severity) + 1, _SEVERITY_ORDER.index(Severity.HIGH))]


class Agent(ABC):
    id: ClassVar[str]
    name: ClassVar[str]
    pillar: ClassVar[Pillar]
    version: ClassVar[str] = "1.0.0"
    requires: ClassVar[frozenset[EvidenceType]]
    checks: ClassVar[list[CheckSpec]]
    counts_toward_readiness: ClassVar[bool] = True
    signature_columns: ClassVar[list[str]] = []

    def plan(self, ctx: AgentContext) -> list[WorkUnit]:
        return [WorkUnit("all")]

    @abstractmethod
    def run_unit(self, ctx: AgentContext, unit: WorkUnit) -> AgentResult: ...

    def reduce(self, ctx: AgentContext, results: list[AgentResult]) -> AgentResult:
        merged = AgentResult(findings=[], patches=[], coverage=Coverage(),
                             signature_table={"columns": self.signature_columns, "rows": []})
        for result in results:
            merged.findings.extend(result.findings)
            merged.patches.extend(result.patches)
            merged.coverage.skipped.extend(result.coverage.skipped)
            merged.coverage.limits.extend(result.coverage.limits)
            for key, value in result.coverage.examined.items():
                merged.coverage.examined[key] = merged.coverage.examined.get(key, 0) + value \
                    if isinstance(value, int) else value
            merged.signature_table["rows"].extend(result.signature_table.get("rows", []))
        return merged

    # ------------------------------------------------------------ helpers

    def check(self, check_id: str) -> CheckSpec:
        for spec in self.checks:
            if spec.id == check_id:
                return spec
        raise KeyError(f"{self.id} has no check {check_id}")

    def finding(self, check_id: str, status: CheckStatus, title: str, *, pages: list[str] | None = None,
                evidence: list[EvidenceRef] | None = None, severity: Severity | None = None,
                confidence: Confidence = Confidence.CONFIRMED, key_page: bool = False,
                locator: Locator | None = None, **fields: Any) -> Finding:
        spec = self.check(check_id)
        if status in (CheckStatus.WARN, CheckStatus.FAIL):
            severity = severity or spec.default_severity
            if key_page:
                severity = escalate(severity)
            if status == CheckStatus.WARN and severity == Severity.CRITICAL:
                severity = Severity.HIGH
            if confidence == Confidence.HYPOTHESIS and severity == Severity.CRITICAL:
                severity = Severity.HIGH
        else:
            severity = None
        pages = pages or []
        return Finding(agent_id=self.id, agent_version=self.version, check_id=check_id, pillar=self.pillar,
                       title=title, status=status, severity=severity, confidence=confidence,
                       scope=Scope(level="site" if not pages or len(pages) > 1 else "page", pages=pages),
                       locator=locator, evidence=evidence or [], **fields)
