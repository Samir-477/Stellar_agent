"""G3 AI Share of Voice (observation, not scored): when customers ask AI assistants category
questions ("best hotels near the Taj Mahal"), is the business named, how prominently, next to whom,
and how is it presented?

Deterministic: brand mentions per surface (the business's own name words, not its city), prominence
from where the name first appears among the businesses an answer lists, and agreement across
surfaces for the same prompt. LLM (one call, fast tier): lists the businesses each category answer
names (every name verified in the text) and how the client is presented (quote verified).
"""

from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass, field

from pydantic import BaseModel, Field

from engine.agents.base import Agent
from engine.agents.common import brand_tokens, business_name
from engine.context import AgentContext, WorkUnit
from engine.lib.grounding import normalize, quote_in_text
from engine.llm import LLMError, load_prompt
from engine.schemas import (
    AgentResult,
    CheckSpec,
    CheckStatus as St,
    Confidence,
    Coverage,
    Effort,
    EvidenceRef,
    EvidenceType,
    Pillar,
    Severity as Sev,
)

ANSWER_CHARS = 700
MAX_ANSWERS = 20


class Mentions(BaseModel):
    id: str
    businesses: list[str] = Field(default_factory=list)
    framing: str | None = None
    quote: str | None = None


class MentionsAnswer(BaseModel):
    answers: list[Mentions] = Field(default_factory=list)


@dataclass
class Answer:
    surface: str
    label: str
    prompt: str
    kind: str
    text: str
    captured_at: str | None
    mentioned: bool = False
    businesses: list[str] = field(default_factory=list)  # verified names, client excluded, in order
    prominence: str | None = None  # first | listed | passing
    framing: str | None = None
    quote: str | None = None


def mentions(text: str, brand: set[str]) -> int | None:
    """Offset of the first brand word in the text, or None."""
    hits = [m.start() for w in brand for m in re.finditer(rf"\b{re.escape(w)}\b", text, re.I)]
    return min(hits) if hits else None


def canonical_names(names: list[str]) -> dict[str, str]:
    """Map each name to one display name per business: "ITC Mughal, A Luxury Collection Hotel" and
    "The ITC Mughal" both become "ITC Mughal" (the shortest name the others start with)."""
    def key(name: str) -> str:
        return normalize(name).removeprefix("the ").strip(" .,")

    shortest: dict[str, str] = {}
    for name in sorted(set(names), key=lambda n: len(key(n))):
        k = key(name)
        base = next((b for b in shortest if k == b or k.startswith(b + " ") or k.startswith(b + ",")), None)
        if base is None:
            shortest[k] = name.strip()
    return {name: shortest[next(b for b in shortest if key(name) == b or key(name).startswith(b + " ")
                                     or key(name).startswith(b + ","))] for name in names}


def load_answers(ctx: AgentContext) -> list[Answer]:
    out = []
    for ev in ctx.snapshot.evidence(EvidenceType.AI_ANSWERS):
        for a in ev.payload.get("answers", []):
            if a.get("text"):
                out.append(Answer(a.get("surface") or ev.payload.get("surface"), a.get("label") or "",
                                  a.get("prompt") or "", a.get("prompt_kind") or "", a["text"], a.get("captured_at")))
    return out


def is_category(answer: Answer) -> bool:
    """A category question names no business: "best hotels near X" (C9 kind "category"; AI Overviews
    for local or service searches)."""
    return answer.kind in ("category", "local", "service", "question")


class AIShareOfVoice(Agent):
    id = "G3"
    name = "AI Share of Voice"
    pillar = Pillar.GEO
    counts_toward_readiness = False  # dated, sampled observations (docs/spec/04)
    requires = frozenset({EvidenceType.AI_ANSWERS, EvidenceType.FACTS})
    signature_columns = ["Prompt", "Surface", "Brand mentioned?", "Competitors mentioned", "Prominence", "Date"]
    checks = [
        CheckSpec(id="G3.01", title="Brand mention rate", default_severity=Sev.HIGH, method="M",
                  counts_toward_readiness=False),
        CheckSpec(id="G3.02", title="Competitor mention rate", default_severity=Sev.MEDIUM, method="M",
                  counts_toward_readiness=False),
        CheckSpec(id="G3.03", title="Prominence", default_severity=Sev.MEDIUM, method="M+L",
                  counts_toward_readiness=False),
        CheckSpec(id="G3.04", title="Framing", default_severity=Sev.MEDIUM, method="M+L",
                  counts_toward_readiness=False),
        CheckSpec(id="G3.05", title="Stability", default_severity=Sev.LOW, method="M",
                  counts_toward_readiness=False),
    ]

    def run_unit(self, ctx: AgentContext, unit: WorkUnit) -> AgentResult:
        brand = brand_tokens(ctx)
        answers = [a for a in load_answers(ctx) if is_category(a)]
        coverage = Coverage(examined={"category_answers": len(answers),
                                      "surfaces": len({a.surface for a in answers})})
        coverage.limits.append("AI answers are samples from one day; model-knowledge probes reflect training data, "
                               "and the simulated search is a proxy, not a measurement of any AI product.")
        if not answers or not brand:
            reason = "No category answers captured" if not answers else "No brand name to look for"
            coverage.skipped.append(reason)
            return AgentResult(findings=[self.finding(c.id, St.UNVERIFIABLE, reason) for c in self.checks],
                               coverage=coverage)
        for a in answers:
            a.mentioned = mentions(a.text, brand) is not None
        self._judge(ctx, answers, brand, coverage)
        findings = [self._rate(answers), self._competitors(answers), self._prominence(answers),
                    self._framing(answers), self._stability(answers)]
        rows = [[a.prompt[:80], a.surface, "yes" if a.mentioned else "no", ", ".join(a.businesses[:4]) or "—",
                 a.prominence or "—", a.captured_at or "—"] for a in answers]
        return AgentResult(findings=findings, coverage=coverage,
                           signature_table={"columns": self.signature_columns, "rows": rows})

    # ------------------------------------------------------------ LLM

    def _judge(self, ctx, answers: list[Answer], brand: set[str], coverage: Coverage) -> None:
        if ctx.llm is None:
            coverage.skipped.append("Competitor names and framing need the LLM (off in this run).")
            return
        batch = answers[:MAX_ANSWERS]
        lines = "\n".join(f"A{i} [{a.surface}]: {' '.join(a.text.split())[:ANSWER_CHARS]}"
                          for i, a in enumerate(batch, start=1))
        try:
            result = ctx.llm.complete_json(load_prompt("g3.mentions", 1), MentionsAnswer,
                                           client=business_name(ctx), answers=lines).data
        except LLMError as exc:
            coverage.skipped.append(f"Mention review failed: {exc}")
            return
        by_id = {m.id: m for m in result.answers}
        dropped = 0
        for i, a in enumerate(batch, start=1):
            m = by_id.get(f"A{i}")
            if m is None:
                continue
            shown = " ".join(a.text.split())[:ANSWER_CHARS]
            names = [n.strip() for n in m.businesses if n.strip()]
            real = [n for n in names if quote_in_text(n, shown)]
            dropped += len(names) - len(real)
            a.businesses = [n for n in real if mentions(n, brand) is None]  # competitors only
            if a.mentioned:
                text = normalize(a.text)  # one coordinate system for every offset
                first = mentions(text, brand)
                listed = any(mentions(n, brand) is not None for n in real)
                earlier = [n for n in a.businesses if 0 <= text.find(normalize(n)) < first]
                a.prominence = "first" if listed and not earlier else "listed" if listed else "passing"
                if m.framing in ("positive", "neutral", "negative") and m.quote and quote_in_text(m.quote, shown):
                    a.framing, a.quote = m.framing, m.quote.strip()
        if dropped:
            coverage.limits.append(f"{dropped} business name(s) from the model weren't in the answer text and were "
                                   "dropped.")

    # ------------------------------------------------------------ checks

    def _rate(self, answers: list[Answer]):
        by_surface: dict[str, list[Answer]] = {}
        for a in answers:
            by_surface.setdefault(a.surface, []).append(a)
        rates = {s: (sum(a.mentioned for a in group), len(group)) for s, group in by_surface.items()}
        evidence = [EvidenceRef(type="ai_answer", excerpt=f"{s}: named in {n} of {total} category answer(s)")
                    for s, (n, total) in rates.items()]
        named = sum(n for n, _ in rates.values())
        if named:
            return self.finding("G3.01", St.PASS, f"The brand is named in {named} of {len(answers)} category answers",
                                evidence=evidence)
        return self.finding(
            "G3.01", St.WARN, f"The brand isn't named in any of {len(answers)} category answers across "
                              f"{len(rates)} AI surface(s)", evidence=evidence,
            impact="When customers ask AI assistants for recommendations in your category, you aren't in the answer.",
            fix="Earn mentions where AI answers draw from: listings and reviews on the platforms they cite (see G4), "
                "and pages that answer category questions with specific, quotable facts.",
            verification="Recapture the AI answers.", effort=Effort.L)

    def _competitors(self, answers: list[Answer]):
        judged = [a for a in answers if a.businesses or a.mentioned]
        if not any(a.businesses for a in answers):
            return self.finding("G3.02", St.UNVERIFIABLE, "Competitor names not extracted")
        keys = canonical_names([b for a in answers for b in a.businesses])
        counts: Counter[str] = Counter()
        for a in answers:
            counts.update({keys[b] for b in a.businesses})  # once per answer
        names = {key: key for key in counts}
        top = counts.most_common(6)
        without_client = [a for a in answers if a.businesses and not a.mentioned]
        evidence = [EvidenceRef(type="ai_answer", excerpt=f"{names[n]}: named in {c} of {len(answers)} answers")
                    for n, c in top[:5]]
        if without_client:
            return self.finding(
                "G3.02", St.WARN,
                f"Competitors are named in {len(without_client)} answer(s) that leave the client out; "
                f"most named: {'; '.join(names[n] for n, _ in top[:3])}", evidence=evidence,
                confidence=Confidence.LIKELY,
                impact="These businesses take the recommendations your customers see.",
                fix="Compare what these competitors publish and where they are listed (G4) with your own pages.",
                verification="Recapture the AI answers.", effort=Effort.M)
        return self.finding("G3.02", St.PASS, "The client is named wherever competitors are",
                            confidence=Confidence.LIKELY, evidence=evidence or [
                                EvidenceRef(type="ai_answer", excerpt=f"{len(judged)} answers reviewed")])

    def _prominence(self, answers: list[Answer]):
        mentioned = [a for a in answers if a.mentioned and a.prominence]
        if not mentioned:
            return self.finding("G3.03", St.NOT_APPLICABLE, "The client isn't named in category answers")
        places = Counter(a.prominence for a in mentioned)
        evidence = [EvidenceRef(type="ai_answer", excerpt=f"{a.surface}: {a.prominence} in \"{a.prompt[:80]}\"")
                    for a in mentioned[:5]]
        if places["first"] >= len(mentioned) / 2:
            return self.finding("G3.03", St.PASS, f"The client is the first recommendation in {places['first']} of "
                                                  f"{len(mentioned)} answers that name it", evidence=evidence)
        return self.finding(
            "G3.03", St.WARN, f"When named, the client is mostly listed after others ({places['listed']}) or mentioned "
                              f"in passing ({places['passing']})", evidence=evidence, confidence=Confidence.LIKELY,
            impact="Readers act on the first recommendation.",
            fix="Strengthen the facts that make you the obvious pick for these questions.",
            verification="Recapture the AI answers.", effort=Effort.M)

    def _framing(self, answers: list[Answer]):
        framed = [a for a in answers if a.framing]
        if not framed:
            return self.finding("G3.04", St.NOT_APPLICABLE, "No category answer names the client")
        negative = [a for a in framed if a.framing == "negative"]
        evidence = [EvidenceRef(type="ai_answer", excerpt=f"{a.surface} ({a.framing}): \"{a.quote}\"")
                    for a in (negative + [a for a in framed if a not in negative])[:5]]
        if negative:
            return self.finding(
                "G3.04", St.WARN, f"{len(negative)} answer(s) present the client negatively", evidence=evidence,
                confidence=Confidence.LIKELY,
                impact="Negative framing in AI answers steers customers away.",
                fix="Find the source of the claim (reviews, outdated listings) and address it there.",
                verification="Recapture the AI answers.", effort=Effort.M)
        return self.finding("G3.04", St.PASS, "Answers present the client positively or neutrally",
                            confidence=Confidence.LIKELY, evidence=evidence)

    def _stability(self, answers: list[Answer]):
        by_prompt: dict[str, list[Answer]] = {}
        for a in answers:
            by_prompt.setdefault(normalize(a.prompt), []).append(a)
        shared = {p: group for p, group in by_prompt.items() if len({a.surface for a in group}) >= 2}
        if not shared:
            return self.finding("G3.05", St.NOT_APPLICABLE, "No prompt was answered on two or more surfaces")
        agree = [p for p, group in shared.items() if len({a.mentioned for a in group}) == 1]
        tops = {p: {normalize(a.businesses[0]) for a in group if a.businesses} for p, group in shared.items()}
        same_top = [p for p, t in tops.items() if len(t) == 1]
        evidence = [EvidenceRef(type="ai_answer", excerpt=f"\"{group[0].prompt[:70]}\": " + ", ".join(
            f"{a.surface}={'named' if a.mentioned else 'not named'}"
            + (f" (top: {a.businesses[0]})" if a.businesses else "") for a in group)[:400])
            for p, group in list(shared.items())[:4]]
        if len(agree) == len(shared):
            return self.finding(
                "G3.05", St.PASS, f"Surfaces agree on whether to name the client for all {len(shared)} shared prompts "
                                  f"(same top pick on {len(same_top)})", evidence=evidence)
        return self.finding(
            "G3.05", St.WARN, f"Surfaces disagree on naming the client for {len(shared) - len(agree)} of {len(shared)} "
                              "prompts", evidence=evidence, confidence=Confidence.LIKELY,
            impact="Unstable mentions mean the brand's AI visibility depends on which assistant a customer uses.",
            fix="Make the facts that earn mentions consistent everywhere AI systems read.",
            verification="Recapture the AI answers.", effort=Effort.M)
