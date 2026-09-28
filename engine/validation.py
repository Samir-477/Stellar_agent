"""Validation gate applied to every agent result before it's stored (docs/spec/03).

Invalid findings or patches are dropped and reported, never silently kept.
"""

from __future__ import annotations

import re

from engine.agents.base import Agent
from engine.schemas import AgentResult, CheckStatus, Confidence, Severity

TITLE_MAX, DESCRIPTION_MAX = 60, 155


def validate_result(agent: Agent, result: AgentResult, page_urls: set[str]) -> tuple[AgentResult, list[str]]:
    errors: list[str] = []
    check_ids = {c.id for c in agent.checks}
    patch_keys = {p.key for p in result.patches}

    findings = []
    for f in result.findings:
        problem = None
        if f.check_id not in check_ids:
            problem = f"unknown check {f.check_id}"
        elif f.status in (CheckStatus.WARN, CheckStatus.FAIL) and not f.evidence:
            problem = f"{f.check_id} {f.status} has no evidence"
        elif f.status in (CheckStatus.WARN, CheckStatus.FAIL) and f.severity is None:
            problem = f"{f.check_id} {f.status} has no severity"
        elif f.confidence == Confidence.HYPOTHESIS and f.severity == Severity.CRITICAL:
            problem = f"{f.check_id} hypothesis marked critical"
        elif missing := [k for k in f.patch_keys if k not in patch_keys]:
            problem = f"{f.check_id} references unknown patches {missing}"
        if problem:
            errors.append(problem)
        else:
            findings.append(f)

    referenced = {k for f in findings for k in f.patch_keys}
    patches = []
    for p in result.patches:
        problem = None
        if p.key not in referenced:
            problem = f"patch {p.key} is not referenced by any finding"
        elif p.page_url is not None and p.page_url not in page_urls:
            problem = f"patch {p.key} targets a page outside the snapshot"
        elif p.type.value not in ("file_patch", "header_recommendation") and not (
                p.locator and (p.locator.css or p.locator.xpath)):
            problem = f"patch {p.key} has no locator"
        elif p.type.value == "head_upsert" and "<title>" in p.after and len(_strip_tags(p.after)) > TITLE_MAX:
            problem = f"patch {p.key} title longer than {TITLE_MAX} chars"
        if problem:
            errors.append(problem)
        else:
            patches.append(p)

    return result.model_copy(update={"findings": findings, "patches": patches}), errors


def _strip_tags(value: str) -> str:
    return re.sub(r"<[^>]+>", "", value)
