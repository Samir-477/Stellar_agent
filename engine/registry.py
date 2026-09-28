"""The single list of collectors and agents, and dependency resolution between them.

Agents depend on evidence types, never on other agents. The registry maps
evidence types to the collectors that produce them.
"""

from __future__ import annotations

from engine.agents.base import Agent
from engine.agents.seo.s01_crawl_index import CrawlIndexHealth
from engine.agents.seo.s02_page_experience import PageExperience
from engine.agents.seo.s07_internal_linking import InternalLinking
from engine.agents.seo.s08_structured_data import StructuredData
from engine.agents.seo.s09_local import LocalConsistency
from engine.agents.seo.s10_trust import EEATTrust
from engine.agents.geo.g01_ai_access import AICrawlerAccess
from engine.agents.geo.g02_citable_facts import CitableFacts
from engine.agents.geo.g03_share_of_voice import AIShareOfVoice
from engine.agents.geo.g04_citation_sources import CitationSources
from engine.agents.seo.s03_metadata import SearchMetadata
from engine.agents.seo.s04_content import OnPageContent
from engine.agents.seo.s05_themes import KeywordThemes
from engine.agents.seo.s06_serp_landscape import SerpLandscape
from engine.agents.aeo.a02_answer_structure import AnswerStructure
from engine.agents.aeo.a01_answer_coverage import AnswerCoverage
from engine.agents.aeo.a03_journey import JourneyCoverage
from engine.agents.aeo.a04_snippets import SnippetOpportunities
from engine.agents.geo.g05_brand_accuracy import AIBrandAccuracy
from engine.agents.geo.g06_entity_footprint import OffsiteEntityFootprint
from engine.collectors.base import Collector
from engine.collectors.c01_crawler import SiteCrawler
from engine.collectors.c02_parser import PageParser
from engine.collectors.c03_archetype import ArchetypeDetector
from engine.collectors.c04_facts import FactSheet
from engine.collectors.search_collectors import QuestionLibrary, QuerySet, SerpCapture
from engine.collectors.ai_collectors import AIAnswerCapture, PromptSet
from engine.collectors.c08_competitors import CompetitorCapture
from engine.collectors.c11_performance import PerformanceCapture
from engine.collectors.c12_entity import EntityFootprint
from engine.schemas import EvidenceType

COLLECTORS: dict[str, Collector] = {c.id: c for c in (SiteCrawler(), PageParser(), ArchetypeDetector(),
                                                     FactSheet(), QuerySet(), SerpCapture(), QuestionLibrary(),
                                                     PromptSet(), AIAnswerCapture(), PerformanceCapture(),
                                                     EntityFootprint(), CompetitorCapture())}
AGENTS: dict[str, Agent] = {a.id: a for a in (
    CrawlIndexHealth(), PageExperience(), SearchMetadata(), OnPageContent(), KeywordThemes(), SerpLandscape(),
    InternalLinking(), StructuredData(), LocalConsistency(), EEATTrust(), AnswerCoverage(), AnswerStructure(),
    JourneyCoverage(), SnippetOpportunities(), AICrawlerAccess(), CitableFacts(), AIShareOfVoice(), CitationSources(),
    AIBrandAccuracy(), OffsiteEntityFootprint())}


def producer_of(evidence: EvidenceType) -> str:
    for collector in COLLECTORS.values():
        if evidence in collector.produces:
            return collector.id
    raise LookupError(f"no collector produces {evidence}")


def collectors_for(agent_ids: list[str]) -> list[str]:
    """Collector ids needed by these agents, in dependency order (producers first)."""
    needed: dict[str, None] = {}

    def visit(collector_id: str, trail: tuple[str, ...]) -> None:
        if collector_id in trail:
            raise ValueError(f"collector cycle: {' → '.join(trail + (collector_id,))}")
        for evidence in COLLECTORS[collector_id].requires:
            visit(producer_of(evidence), trail + (collector_id,))
        needed.setdefault(collector_id)

    for agent_id in agent_ids:
        for evidence in AGENTS[agent_id].requires:
            visit(producer_of(evidence), ())
    return list(needed)


def upstream_collectors(collector_id: str) -> list[str]:
    return sorted({producer_of(e) for e in COLLECTORS[collector_id].requires})


def agent_collectors(agent_id: str) -> list[str]:
    return sorted({producer_of(e) for e in AGENTS[agent_id].requires})
