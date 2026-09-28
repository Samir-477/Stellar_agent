"""AI-answer collectors (docs/spec/09):

C9 Prompt Set        prompts built from facts and archetype templates plus observed PAA questions
                     (deterministic, versioned, provenance-labelled; no LLM call)
C10 AI Answer Capture answers per surface, each labelled:
                     google_ai_overview   observed (from C6's SerpAPI captures)
                     deepseek / groq      model knowledge, no live search
                     simulated_search     proxy: DeepSeek answering from Serper India results
"""

from __future__ import annotations

import asyncio
import re
from datetime import date
from urllib.parse import urlsplit

from engine.collectors.base import Collector
from engine.collectors.search_collectors import _archetype, _facts, _latest, business_name, landmark
from engine.context import CollectorContext, WorkUnit
from engine.core.net import safe_fetch
from engine.lib.retrieval import tokens
from engine.llm import LLMError, load_prompt
from engine.rules.packs import pack
from engine.schemas import EvidenceType

SURFACE_LABELS = {
    "google_ai_overview": "Observed: Google AI Overview, India",
    "deepseek": "Model knowledge (DeepSeek), no live search",
    "groq": "Model knowledge (Groq {model}), no live search",
    "simulated_search": "Proxy: DeepSeek answering from India top results. Not a measurement of Google, ChatGPT "
                        "or Perplexity.",
}
MAX_SIMULATED = 3
MAX_URL_CHECKS = 10


async def check_urls(ctx: CollectorContext, urls: list[str]) -> dict[str, dict]:
    """Whether URLs that models printed actually exist (hallucinated links are common). HEAD first;
    servers that refuse HEAD get a small GET. Every hop passes the SSRF guard."""
    async with ctx.http_client() as client:
        async def one(url: str) -> tuple[str, dict]:
            result = await safe_fetch(client, url, user_agent=ctx.settings.crawl_user_agent, method="HEAD",
                                      resolver=ctx.resolver)
            if result.status in (403, 405, 501):
                result = await safe_fetch(client, url, user_agent=ctx.settings.crawl_user_agent, max_bytes=50_000,
                                          resolver=ctx.resolver)
            return url, {"status": result.status, "resolves": bool(result.status and result.status < 400),
                         "error": result.error}
        return dict(await asyncio.gather(*(one(u) for u in urls)))


class PromptSet(Collector):
    id = "C9"
    name = "Prompt Set"
    produces = frozenset({EvidenceType.PROMPT_SET})
    requires = frozenset({EvidenceType.FACTS, EvidenceType.ARCHETYPE, EvidenceType.SERP})

    def plan(self, ctx: CollectorContext) -> list[WorkUnit]:
        return [WorkUnit("build")]

    def run_unit(self, ctx: CollectorContext, unit: WorkUnit) -> list[WorkUnit]:
        facts, name = _facts(ctx), business_name(ctx)
        city = (facts.get("city") or [""])[0]
        mark = landmark(facts) or city
        prompts = [{"text": f"Tell me about {name}.", "kind": "brand", "source": "brand"}]
        if facts.get("room_count"):
            prompts.append({"text": f"How many rooms does {name} have?", "kind": "brand-fact",
                            "source": "brand", "fact_key": "room_count"})
        if facts.get("distance_to_landmark") and mark:
            prompts.append({"text": f"How far is {name} from the {mark}?", "kind": "brand-fact",
                            "source": "brand", "fact_key": "distance_to_landmark"})
        if any("pool" in v.lower() for v in facts.get("amenities", [])):
            prompts.append({"text": f"Does {name} have a swimming pool?", "kind": "brand-fact", "source": "brand",
                            "fact_key": "amenities"})
        arch = pack(_archetype(ctx))
        if arch:
            for seed in arch.prompt_seeds:
                text = seed.format(brand=name, city=city, landmark=mark, service="")
                if "{" not in text and not text.startswith("Tell me about"):
                    prompts.append({"text": text, "kind": "category", "source": "archetype-template"})
        seen_paa = set()
        for serp in ctx.snapshot.evidence(EvidenceType.SERP):
            for paa in (serp.payload.get("features") or {}).get("paa", []) or []:
                q = paa.get("question")
                if q and q not in seen_paa and len(seen_paa) < 3:
                    seen_paa.add(q)
                    prompts.append({"text": q, "kind": "category", "source": "observed-paa"})
        for index, prompt in enumerate(prompts, start=1):
            prompt["id"] = f"P{index}"
        ctx.snapshot.add_evidence(self.id, EvidenceType.PROMPT_SET, {"version": 1, "business": name,
                                                                     "prompts": prompts}, source_label="mixed")
        return []


def _domain(url: str) -> str:
    return (urlsplit(url or "").hostname or "").removeprefix("www.")


class AIAnswerCapture(Collector):
    id = "C10"
    name = "AI Answer Capture"
    produces = frozenset({EvidenceType.AI_ANSWERS})
    requires = frozenset({EvidenceType.PROMPT_SET, EvidenceType.SERP})

    def plan(self, ctx: CollectorContext) -> list[WorkUnit]:
        # One unit per surface keeps each task short and failures independent.
        return [WorkUnit("capture", {"surface": s})
                for s in ("google_ai_overview", "deepseek", "groq", "simulated_search")]

    def run_unit(self, ctx: CollectorContext, unit: WorkUnit) -> list[WorkUnit]:
        surface = unit.params["surface"]
        prompts = _latest(ctx, EvidenceType.PROMPT_SET).get("prompts", [])
        answers, note = [], None
        if surface == "google_ai_overview":
            seen = set()
            for serp in ctx.snapshot.evidence(EvidenceType.SERP):
                f = serp.payload.get("features") or {}
                if f.get("ai_overview") and serp.payload["query"] not in seen:
                    seen.add(serp.payload["query"])
                    answers.append({"prompt": serp.payload["query"], "prompt_kind": serp.payload.get("intent"),
                                    "text": f.get("ai_overview_text", ""), "model": "google-ai-overview",
                                    "citations": [{"n": i + 1, "url": r.get("link"), "domain": _domain(r.get("link")),
                                                   "title": r.get("title")}
                                                  for i, r in enumerate(f.get("ai_overview_references", []))]})
        elif ctx.llm is None:
            note = "LLM off: no model answers captured"
        elif surface in ("deepseek", "groq"):
            spec = load_prompt("c10.probe", 1)
            for p in prompts:
                try:
                    result = ctx.llm.probe_text(surface, spec, question=p["text"])
                except LLMError as exc:
                    note = f"{surface}: {exc}"
                    continue
                # Sentence punctuation after a URL isn't part of it ("see https://x.com/a.").
                urls = [u.rstrip(".,;:!?'\"") for u in re.findall(r"https?://[^\s)\]>*]+", result.data)]
                answers.append({"prompt_id": p["id"], "prompt": p["text"], "prompt_kind": p["kind"],
                                "text": result.data, "model": result.model,
                                "citations": [{"n": i + 1, "url": u, "domain": _domain(u), "printed": True}
                                              for i, u in enumerate(urls)]})
            printed = list(dict.fromkeys(c["url"] for a in answers for c in a["citations"]))[:MAX_URL_CHECKS]
            if printed:
                checks = asyncio.run(check_urls(ctx, printed))
                for a in answers:
                    for c in a["citations"]:
                        c.update(checks.get(c["url"], {"resolves": None, "error": "not checked (limit)"}))
        elif surface == "simulated_search":
            serps = {s.payload["query"]: s.payload for s in ctx.snapshot.evidence(EvidenceType.SERP)
                     if s.payload.get("organic")}
            spec = load_prompt("c10.simulated_search", 1)
            for p in [p for p in prompts if p["kind"] == "category"][:MAX_SIMULATED]:
                query = max(serps, key=lambda q: len(set(tokens(q)) & set(tokens(p["text"]))), default=None)
                if query is None:
                    continue
                results = serps[query]["organic"][:6]
                listing = "\n".join(f"[{i + 1}] {r['title']} ({r['domain']}): {r.get('snippet') or ''}"
                                    for i, r in enumerate(results))
                try:
                    result = ctx.llm.probe_text("deepseek", spec, question=p["text"], results=listing,
                                                date=date.today().isoformat())
                except LLMError as exc:
                    note = f"simulated search: {exc}"
                    continue
                cited = sorted({int(n) for n in re.findall(r"\[(\d+)\]", result.data) if 0 < int(n) <= len(results)})
                answers.append({"prompt_id": p["id"], "prompt": p["text"], "prompt_kind": p["kind"],
                                "text": result.data, "model": result.model, "grounded_on_query": query,
                                "citations": [{"n": n, "url": results[n - 1]["link"], "domain": results[n - 1]["domain"],
                                               "title": results[n - 1]["title"]} for n in cited]})
        label = SURFACE_LABELS[surface].format(model=ctx.settings.groq_model)
        for a in answers:
            a.update(surface=surface, label=label, captured_at=date.today().isoformat())
        ctx.snapshot.add_evidence(self.id, EvidenceType.AI_ANSWERS, {"surface": surface, "answers": answers,
                                                                     "label": label, "note": note},
                                  source_label="observed" if surface == "google_ai_overview" else "model")
        return []
