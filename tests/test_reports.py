"""Agent reports: what goes in issues, and what is listed apart."""

from engine.agents.seo.s06_serp_landscape import SerpLandscape
from engine.reports import build_agent_report
from engine.schemas import AgentResult, CheckStatus as St, Coverage, EvidenceRef


def test_checks_that_could_not_run_are_listed_apart_from_issues():
    """Regression (Flipkart and Navarasa runs, 2026-09-29): "not reviewed" placeholders sat in needs_attention
    beside real warnings, so every site's report read alike."""
    agent = SerpLandscape()
    findings = [
        agent.finding("S6.01", St.UNVERIFIABLE, "Only brand searches were captured"),
        agent.finding("S6.03", St.WARN, "AI Overviews appear on most searches",
                      evidence=[EvidenceRef(type="serp", excerpt="3 of 4 searches")]),
    ]
    report = build_agent_report(agent, AgentResult(findings=findings, coverage=Coverage()))
    assert [i["title"] for i in report.needs_attention] == ["AI Overviews appear on most searches"]
    assert report.could_not_check == [{"check_id": "S6.01", "title": "Only brand searches were captured", "reason": ""}]
