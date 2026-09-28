"""C3 Archetype Detector.

Order of precedence (cheapest first):
  1. archetype set by the team on the client → used as-is
  2. deterministic signals (terms + schema types) when they are clear-cut
  3. one LLM call (fast tier) on page titles/H1s/descriptions
Below the confidence threshold the run pauses for the team to confirm (docs/spec/03 step 4).
"""

from __future__ import annotations

from pydantic import BaseModel, Field

from engine.collectors.base import Collector
from engine.collectors.common import parsed_models
from engine.context import CollectorContext, WorkUnit
from engine.lib.jsonld import page_types
from engine.lib.grounding import quote_in_text
from engine.llm import LLMError, load_prompt
from engine.rules.packs import ARCHETYPES, PACKS
from engine.schemas import EvidenceType

CONFIRM_THRESHOLD = 0.8
MAX_PAGES_FOR_LLM = 10


class AwaitingConfirmation(Exception):
    """Raised when the archetype needs a human decision before agents run."""

    def __init__(self, proposal: dict):
        super().__init__(f"archetype needs confirmation: {proposal}")
        self.proposal = proposal


class ArchetypeAnswer(BaseModel):
    archetype: str
    secondary: str | None = None
    confidence: float = Field(ge=0, le=1)
    evidence: list[str] = Field(default_factory=list, max_length=5)


def rule_scores(models: list[dict]) -> dict[str, tuple[float, list[str]]]:
    """Deterministic archetype scores from visible headline text and schema types."""
    scores: dict[str, tuple[float, list[str]]] = {}
    for name, pack in PACKS.items():
        score, signals = 0.0, []
        for model in models:
            headline = " ".join([model.get("title") or "", model.get("meta", {}).get("description", "")]
                                + [h["text"] for h in model.get("headings", []) if h["level"] <= 2]).lower()
            for term in pack.detection_terms:
                if term in headline:
                    score += 1
                    signals.append(f"'{term}' in {model['url']}")
            for schema_type in page_types(model) & set(pack.detection_schema_types):
                score += 3
                signals.append(f"schema {schema_type} on {model['url']}")
        scores[name] = (score, signals[:8])
    return scores


def page_digest(models: list[dict]) -> str:
    lines = []
    for model in models[:MAX_PAGES_FOR_LLM]:
        h1 = " / ".join(h["text"] for h in model.get("headings", []) if h["level"] == 1)[:150]
        lines.append(f"URL: {model['url']} | Title: {model.get('title') or ''} | H1: {h1} | "
                     f"Description: {model.get('meta', {}).get('description', '')[:200]} | "
                     f"Schema: {', '.join(sorted(page_types(model))) or 'none'}")
    return "\n".join(lines)


class ArchetypeDetector(Collector):
    id = "C3"
    name = "Archetype Detector"
    produces = frozenset({EvidenceType.ARCHETYPE})
    requires = frozenset({EvidenceType.PAGES_PARSED})

    def plan(self, ctx: CollectorContext) -> list[WorkUnit]:
        return [WorkUnit("detect")]

    def run_unit(self, ctx: CollectorContext, unit: WorkUnit) -> list[WorkUnit]:
        result = self.detect(ctx)
        ctx.snapshot.add_evidence(self.id, EvidenceType.ARCHETYPE, result, source_label=result["source"])
        if result["confidence"] < CONFIRM_THRESHOLD:
            raise AwaitingConfirmation(result)
        return []

    def detect(self, ctx: CollectorContext) -> dict:
        if ctx.client.archetype:
            return {"archetype": ctx.client.archetype, "secondary": None, "confidence": 1.0, "source": "team",
                    "evidence": ["set by the team on the client record"]}
        models = parsed_models(ctx)
        llm_error = None
        scores = rule_scores(models)
        ranked = sorted(scores.items(), key=lambda kv: kv[1][0], reverse=True)
        (top, (top_score, top_signals)), (second, (second_score, _)) = ranked[0], ranked[1]
        if top_score >= 6 and top_score >= 2 * max(second_score, 1):
            return {"archetype": top, "secondary": None, "confidence": 0.9, "source": "rules",
                    "evidence": top_signals, "scores": {k: v[0] for k, v in scores.items()}}
        if ctx.llm is not None:
            digest = page_digest(models)
            try:
                answer = ctx.llm.complete_json(load_prompt("c3.archetype", 1), ArchetypeAnswer, pages=digest).data
            except LLMError as exc:
                answer = None
                llm_error = str(exc)
            if answer is not None:
                grounded = [q for q in answer.evidence if quote_in_text(q, digest)]
                confidence = answer.confidence if grounded else min(answer.confidence, 0.5)
                archetype = answer.archetype if answer.archetype in ARCHETYPES else "other"
                return {"archetype": archetype, "secondary": answer.secondary, "confidence": round(confidence, 2),
                        "source": "llm", "evidence": grounded,
                        "ungrounded_evidence": [q for q in answer.evidence if q not in grounded],
                        "scores": {k: v[0] for k, v in scores.items()}}
        else:
            llm_error = "LLM off"
        return {"archetype": top if top_score else "other", "secondary": second if second_score else None,
                "confidence": 0.5 if top_score else 0.2, "source": "rules", "evidence": top_signals,
                "scores": {k: v[0] for k, v in scores.items()}, "note": llm_error}

