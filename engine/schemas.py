"""Shared data shapes: findings, patches, evidence references and reports.

These mirror docs/spec/05-output-templates.md. Reports are stored as JSON with
SCHEMA_VERSION so integrations can rely on the shape.
"""

from __future__ import annotations

import hashlib
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field

SCHEMA_VERSION = "1.0"


class Pillar(StrEnum):
    SEO = "seo"
    AEO = "aeo"
    GEO = "geo"


class CheckStatus(StrEnum):
    PASS = "pass"
    WARN = "warn"
    FAIL = "fail"
    NOT_APPLICABLE = "not_applicable"
    UNVERIFIABLE = "unverifiable"


class Severity(StrEnum):
    CRITICAL = "critical"
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"
    INFO = "info"


class Confidence(StrEnum):
    CONFIRMED = "confirmed"
    LIKELY = "likely"
    HYPOTHESIS = "hypothesis"


class Effort(StrEnum):
    S = "S"
    M = "M"
    L = "L"


class EvidenceType(StrEnum):
    """What collectors produce and agents declare in `requires`."""

    PAGES_RAW = "pages_raw"  # C1: raw HTML + fetch metadata per page
    PAGES_RENDERED = "pages_rendered"  # C1: browser-rendered HTML per page
    SITE_FILES = "site_files"  # C1: robots.txt, sitemaps, llms.txt
    URL_VARIANTS = "url_variants"  # C1: http/https/www probes
    AI_UA_PROBES = "ai_ua_probes"  # C1: responses to AI crawler user agents
    PAGES_PARSED = "pages_parsed"  # C2: structured page models
    ARCHETYPE = "archetype"  # C3: archetype + confidence + source
    FACTS = "facts"  # C4: business fact sheet with quotes
    QUERY_SET = "query_set"  # C5: search queries with provenance + page→query map
    SERP = "serp"  # C6: search results per query (Serper organic; SerpAPI features)
    QUESTIONS = "questions"  # C7: question library with source labels and journey stages
    PROMPT_SET = "prompt_set"  # C9: AI prompts with provenance
    AI_ANSWERS = "ai_answers"  # C10: answers from AI surfaces, labelled per surface
    PERFORMANCE = "performance"  # C11: PageSpeed Insights field + lab data per measured URL
    ENTITY_FOOTPRINT = "entity_footprint"  # C12: Wikidata/Wikipedia, listing platforms, Maps, Knowledge Graph
    COMPETITORS = "competitors"  # C8: ranking domains typed (direct, aggregator, directory, publisher, social)
    COMPETITOR_PAGES = "competitor_pages"  # C8: direct competitors' ranking pages, fetched and parsed


class Locator(BaseModel):
    css: str | None = None
    xpath: str | None = None
    text_hash: str | None = None


class EvidenceRef(BaseModel):
    evidence_id: str | None = None
    type: str  # html_excerpt, header, status, file_excerpt, metric, serp, ai_answer
    excerpt: str
    url: str | None = None
    captured_at: str | None = None


class Scope(BaseModel):
    level: str  # site | template | page | element
    pages: list[str] = Field(default_factory=list)
    template_id: str | None = None


class CheckSpec(BaseModel):
    id: str  # "S1.04"
    title: str
    default_severity: Severity
    method: str  # D, L, S, M, P combinations
    counts_toward_readiness: bool = True


class Finding(BaseModel):
    agent_id: str
    agent_version: str
    check_id: str
    pillar: Pillar
    title: str
    status: CheckStatus
    severity: Severity | None = None
    confidence: Confidence = Confidence.CONFIRMED
    scope: Scope
    locator: Locator | None = None
    evidence: list[EvidenceRef] = Field(default_factory=list)
    impact: str = ""
    fix: str = ""
    verification: str = ""
    effort: Effort | None = None
    # Information only the client can provide for the fix (prices, a policy, the current figure) — never
    # actions ("add a page for X"). Intelligence groups items that report the same facts and lists them as
    # facts to supply; an item with missing facts and no proposed change is "blocked".
    missing_facts: list[str] = Field(default_factory=list)
    tags: list[str] = Field(default_factory=list)
    patch_keys: list[str] = Field(default_factory=list)

    @property
    def fingerprint(self) -> str:
        pages = ",".join(sorted(self.scope.pages))
        target = self.locator.css if self.locator and self.locator.css else ""
        raw = f"{self.check_id}|{self.scope.template_id or pages}|{target}"
        return hashlib.sha1(raw.encode()).hexdigest()[:16]


class PatchType(StrEnum):
    TEXT_REPLACE = "text_replace"
    ATTRIBUTE_SET = "attribute_set"
    ELEMENT_INSERT = "element_insert"
    LINK_INSERT = "link_insert"  # wrap an exact phrase inside the located element in <a href>
    ELEMENT_REMOVE = "element_remove"
    HEAD_UPSERT = "head_upsert"
    JSONLD_UPSERT = "jsonld_upsert"
    FILE_PATCH = "file_patch"
    HEADER_RECOMMENDATION = "header_recommendation"


class Patch(BaseModel):
    key: str  # unique within the agent result; findings reference it
    agent_id: str
    page_url: str | None
    type: PatchType
    locator: Locator | None = None
    before: str | None = None
    after: str
    rationale: str
    fact_ids: list[str] = Field(default_factory=list)
    confidence: Confidence = Confidence.CONFIRMED
    client_visible_note: str = ""


class Coverage(BaseModel):
    examined: dict[str, Any] = Field(default_factory=dict)  # e.g. {"pages": 25}
    skipped: list[str] = Field(default_factory=list)  # human-readable reasons
    limits: list[str] = Field(default_factory=list)


class AgentReport(BaseModel):
    """The 6-section agent template (docs/spec/05-output-templates.md)."""

    schema_version: str = SCHEMA_VERSION
    agent_id: str
    agent_name: str
    verdict: str
    scorecard: dict[str, int]
    scope_and_evidence: dict[str, Any]  # coverage + signature table
    issues_to_fix: list[dict[str, Any]]
    needs_attention: list[dict[str, Any]]
    whats_working: list[dict[str, Any]]
    could_not_check: list[dict[str, Any]] = []  # checks without enough evidence: not issues, listed apart
    proposed_changes: list[dict[str, Any]]
    missing_facts_and_next_checks: list[str]


class AgentResult(BaseModel):
    findings: list[Finding]
    patches: list[Patch] = Field(default_factory=list)
    coverage: Coverage = Field(default_factory=Coverage)
    signature_table: dict[str, Any] = Field(default_factory=dict)  # {"columns": [...], "rows": [...]}
