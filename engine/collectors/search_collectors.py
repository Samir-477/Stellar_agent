"""Search-evidence collectors:

C5 Query Set       queries customers type (templates from facts + one LLM call), with provenance
C6 SERP Capture    Serper organic results for every query; SerpAPI (AI Overview, PAA, snippet,
                   knowledge graph) for the top priority queries only
C7 Question Library observed questions (SerpAPI PAA, Serper India autocomplete), on-site
                   questions and archetype questions, classified by one LLM call
"""

from __future__ import annotations

import json
import re
from urllib.parse import urlsplit

from pydantic import BaseModel, Field

from engine.collectors.base import Collector
from engine.collectors.common import parsed_models
from engine.context import CollectorContext, WorkUnit
from engine.integrations.search import BudgetExhausted, SearchError, ai_overview_text
from engine.lib.content import is_question
from engine.lib.grounding import normalize
from engine.llm import LLMError, load_prompt
from engine.rules.packs import pack
from engine.schemas import EvidenceType

MAX_QUERIES = 10
AUTOCOMPLETE_PREFIXES = ("what", "how", "is", "can", "best")


def _latest(ctx: CollectorContext, evidence_type: EvidenceType) -> dict:
    items = ctx.snapshot.evidence(evidence_type)
    return items[-1].payload if items else {}


def _facts(ctx: CollectorContext) -> dict[str, list[str]]:
    by_key: dict[str, list[str]] = {}
    for fact in _latest(ctx, EvidenceType.FACTS).get("facts", []):
        if fact["status"] in ("site-stated", "team-confirmed"):
            by_key.setdefault(fact["key"], []).append(fact["value"])
    return by_key


def business_name(ctx: CollectorContext) -> str:
    facts = _facts(ctx)
    return (facts.get("property_name") or facts.get("business_name") or [ctx.client.name])[0]


def landmark(facts: dict[str, list[str]]) -> str | None:
    for value in facts.get("distance_to_landmark", []):
        match = re.search(r"from (?:the )?([A-Z][\w’' -]+?)(?:\s+in\b|,|$)", value)
        if match:
            return match.group(1).strip()
    return None


def _domain(url: str) -> str:
    return (urlsplit(url).hostname or "").removeprefix("www.")


# ---------------------------------------------------------------- C5 Query Set

class QueryIdea(BaseModel):
    q: str = Field(min_length=2, max_length=120)
    intent: str


class QueryIdeas(BaseModel):
    queries: list[QueryIdea] = Field(default_factory=list, max_length=12)


class QuerySet(Collector):
    id = "C5"
    name = "Query Set"
    produces = frozenset({EvidenceType.QUERY_SET})
    requires = frozenset({EvidenceType.PAGES_PARSED, EvidenceType.FACTS, EvidenceType.ARCHETYPE})

    def plan(self, ctx: CollectorContext) -> list[WorkUnit]:
        return [WorkUnit("build")]

    def run_unit(self, ctx: CollectorContext, unit: WorkUnit) -> list[WorkUnit]:
        facts, name = _facts(ctx), business_name(ctx)
        city = (facts.get("city") or [None])[0]
        mark = landmark(facts)
        queries: list[dict] = [{"q": name.lower(), "intent": "brand", "source": "site-derived"}]
        if city and normalize(city) not in normalize(name):
            queries.append({"q": f"{name} {city}".lower(), "intent": "brand", "source": "site-derived"})
        if mark:
            text = f"hotels near {mark}" if _archetype(ctx) == "hospitality" else f"{name} near {mark}"
            queries.append({"q": text.lower(), "intent": "local", "source": "archetype-template"})
        models = parsed_models(ctx)
        entry = models[0] if models else None
        note = None
        if ctx.llm is not None and entry:
            h1 = next((h["text"] for h in entry.get("headings", []) if h["level"] == 1), "")
            opening = " ".join(p["text"] for p in entry.get("passages", [])[:4] if "{{" not in p["text"])
            page = (f"PAGE: {entry['url']}\nH1: {h1}\nOPENING: {' '.join(opening.split()[:120])}\n"
                    f"FACTS: {'; '.join(f'{k}={v[0]}' for k, v in list(facts.items())[:12])}")
            try:
                ideas = ctx.llm.complete_json(load_prompt("c5.queries", 1), QueryIdeas, business=name, page=page).data
                queries += [{"q": i.q.lower().strip(), "intent": i.intent, "source": "llm-suggested"}
                            for i in ideas.queries]
            except LLMError as exc:
                note = f"LLM query ideas unavailable: {exc}"
        unique, seen = [], set()
        order = {"brand": 0, "service": 1, "local": 2, "question": 3}
        for query in sorted(queries, key=lambda q: (order.get(q["intent"], 4), q["source"] != "site-derived")):
            key = normalize(query["q"])
            if key and key not in seen:
                seen.add(key)
                unique.append(query)
        unique = unique[:MAX_QUERIES]
        # Priority for SerpAPI (scarce): the first query of each intent (brand, service, local,
        # question), then everything else in order.
        firsts = [next(q for q in unique if q["intent"] == intent) for intent in order
                  if any(q["intent"] == intent for q in unique)]
        priority = firsts + [q for q in unique if q not in firsts]
        for rank, query in enumerate(priority, start=1):
            query["priority"] = rank
        ctx.snapshot.add_evidence(self.id, EvidenceType.QUERY_SET,
                                  {"version": 1, "queries": priority, "business": name, "note": note,
                                   "page_query_map": {ctx.client.primary_url: priority[0]["q"]}},
                                  source_label="mixed")
        return []


def _archetype(ctx: CollectorContext) -> str | None:
    return _latest(ctx, EvidenceType.ARCHETYPE).get("archetype") or ctx.client.archetype


# ------------------------------------------------------------- C6 SERP Capture

class SerpCapture(Collector):
    id = "C6"
    name = "SERP Capture"
    produces = frozenset({EvidenceType.SERP})
    requires = frozenset({EvidenceType.QUERY_SET})

    def plan(self, ctx: CollectorContext) -> list[WorkUnit]:
        """One unit per query, so a failure or retry never repeats searches that already succeeded."""
        queries = _latest(ctx, EvidenceType.QUERY_SET).get("queries", [])
        return [WorkUnit("capture", {"priority": q["priority"]}) for q in queries]

    def run_unit(self, ctx: CollectorContext, unit: WorkUnit) -> list[WorkUnit]:
        if ctx.search is None:
            raise RuntimeError("no search client configured")
        queries = _latest(ctx, EvidenceType.QUERY_SET).get("queries", [])
        client_domain = _domain(ctx.client.primary_url)
        feature_slots = max(1, ctx.settings.serpapi_calls_per_run // 2)  # leave room for AI Overview follow-ups
        captured = {e.payload["query"] for e in ctx.snapshot.evidence(EvidenceType.SERP)
                    if e.payload.get("organic") is not None}
        for query in [q for q in queries if q["priority"] == unit.params["priority"]]:
            if query["q"] in captured:
                continue  # already captured in an earlier attempt: don't pay for it twice
            record: dict = {"query": query["q"], "intent": query["intent"], "priority": query["priority"]}
            raw: dict = {}
            try:
                organic = ctx.search.organic(query["q"])
                raw["serper"] = organic
                results = [{"position": r.get("position"), "link": r.get("link"), "title": r.get("title"),
                            "snippet": r.get("snippet"), "domain": _domain(r.get("link", ""))}
                           for r in organic.get("organic", [])[:10]]
                record["organic"] = results
                record["client_position"] = next((r["position"] for r in results if r["domain"] == client_domain), None)
            except (SearchError, BudgetExhausted) as exc:
                record["organic_error"] = str(exc)
            if query["priority"] <= feature_slots:
                try:
                    data = ctx.search.google_features(query["q"])
                    raw["serpapi"] = data
                    overview = data.get("ai_overview") or {}
                    record["features"] = {
                        "ai_overview": bool(overview.get("text_blocks")),
                        "ai_overview_text": ai_overview_text(overview)[:4000],
                        "ai_overview_references": [{"title": r.get("title"), "link": r.get("link"),
                                                    "source": r.get("source")} for r in overview.get("references", [])],
                        "paa": [{"question": q.get("question"), "snippet": q.get("snippet"), "link": q.get("link")}
                                for q in data.get("related_questions", [])],
                        "answer_box": (data.get("answer_box") or {}).get("snippet") or (data.get("answer_box") or {}).get("answer"),
                        "knowledge_graph": (data.get("knowledge_graph") or {}).get("title"),
                        "local_results": len((data.get("local_results") or {}).get("places", []) or []),
                        "note": data.get("ai_overview_note"),
                    }
                except (SearchError, BudgetExhausted) as exc:
                    record["features_error"] = str(exc)
            else:
                record["features"] = None  # not captured (SerpAPI budget reserved for priority queries)
            key = ctx.snapshot.put_blob(f"snapshots/{ctx.snapshot.snapshot_id}/serp/{query['priority']:02d}.json",
                                        json.dumps(raw))
            ctx.snapshot.add_evidence(self.id, EvidenceType.SERP, record, blob_key=key, source_label="observed")
        return []


# --------------------------------------------------------- C7 Question Library

class QuestionLabel(BaseModel):
    id: str
    relevant: bool
    question: str | None = None
    stage: str
    topic: str = ""
    duplicate_of: str | None = None


class QuestionLabels(BaseModel):
    questions: list[QuestionLabel] = Field(default_factory=list)


class QuestionLibrary(Collector):
    id = "C7"
    name = "Question Library"
    produces = frozenset({EvidenceType.QUESTIONS})
    requires = frozenset({EvidenceType.SERP, EvidenceType.PAGES_PARSED, EvidenceType.FACTS})

    def plan(self, ctx: CollectorContext) -> list[WorkUnit]:
        return [WorkUnit("build")]

    def run_unit(self, ctx: CollectorContext, unit: WorkUnit) -> list[WorkUnit]:
        facts, name = _facts(ctx), business_name(ctx)
        candidates: list[dict] = []
        for serp in ctx.snapshot.evidence(EvidenceType.SERP):
            for paa in (serp.payload.get("features") or {}).get("paa", []) or []:
                if paa.get("question"):
                    candidates.append({"text": paa["question"], "source": "observed-paa",
                                       "found_for": serp.payload["query"]})
        note = None
        if ctx.search is not None:
            mark = landmark(facts)
            # Brand names get few searches, so question prefixes only produce junk for them:
            # the brand is expanded plainly, the category seed with question words.
            seeds = [(name.lower(), ("",))] + ([(f"hotels near {mark}".lower(), ("",) + AUTOCOMPLETE_PREFIXES)]
                                                 if mark else [])
            try:
                for seed, prefixes in seeds:
                    seed_words = set(seed.split())
                    for prefix in prefixes:
                        typed = f"{prefix} {seed} ".lstrip()  # trailing space: complete the next word, not "agra"→"agrabah"
                        for suggestion in ctx.search.autocomplete(typed):
                            words = suggestion.lower().split()
                            if seed_words <= set(words) and len(words) >= len(seed_words) + 2:
                                candidates.append({"text": suggestion, "source": "observed-autocomplete",
                                                   "found_for": typed.strip()})
            except (SearchError, BudgetExhausted) as exc:
                note = f"autocomplete stopped: {exc}"
        for model in parsed_models(ctx)[:10]:
            for heading in model.get("headings", []):
                if is_question(heading["text"]):
                    candidates.append({"text": heading["text"], "source": "on-site", "found_for": model["url"]})
        arch = pack(_archetype(ctx))
        if arch:
            city = (facts.get("city") or [""])[0]
            for seed in arch.question_seeds:
                text = seed.format(brand=name, city=city, landmark=landmark(facts) or city, service="", amenity="pool")
                if "{" not in text:
                    candidates.append({"text": text.strip(), "source": "framework-generated", "found_for": "pack"})

        unique, seen = [], set()
        for c in candidates:
            key = normalize(c["text"]).rstrip("?")
            if key and key not in seen:
                seen.add(key)
                unique.append(c)
        unique = unique[:60]
        for index, c in enumerate(unique, start=1):
            c["id"] = f"Q{index}"
        if ctx.llm is not None and unique:
            data = "\n".join(f"{c['id']}: {c['text']}" for c in unique)
            try:
                labels = ctx.llm.complete_json(load_prompt("c7.questions", 2), QuestionLabels,
                                               business=f"{name}, a {(_archetype(ctx) or 'business')} business",
                                               questions=data).data
                by_id = {label.id: label for label in labels.questions}
                for c in unique:
                    label = by_id.get(c["id"])
                    if label:
                        clean = label.question if label.question and label.question.strip().endswith("?") else None
                        c.update(relevant=label.relevant and clean is not None, question=clean or c["text"],
                                 stage=label.stage, topic=label.topic,
                                 duplicate_of=label.duplicate_of if label.duplicate_of in {u["id"] for u in unique}
                                 else None)
            except LLMError as exc:
                note = (note + "; " if note else "") + f"LLM labelling unavailable: {exc}"
        ctx.snapshot.add_evidence(self.id, EvidenceType.QUESTIONS, {"questions": unique, "note": note},
                                  source_label="mixed")
        return []
