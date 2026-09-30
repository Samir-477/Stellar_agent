"""G5 AI Brand Accuracy: is what AI says about the business correct, specific and about the right business?

Reads C10's answers to brand and brand-fact prompts (plus Google AI Overviews for brand queries)
and checks every claim against the Fact Sheet with one LLM call per surface. Claim quotes must
appear in the answer and cited facts must exist, or the claim is dropped. Observation agent:
reported per surface with its label, never blended into readiness.
"""

from __future__ import annotations

from pydantic import BaseModel, Field

from engine.agents.base import Agent
from engine.agents.common import archetype, fact_sheet
from engine.context import AgentContext, WorkUnit
from engine.lib.grounding import normalize, quote_in_text
from engine.llm import LLMError, load_prompt
from engine.rules.packs import pack
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


class Claim(BaseModel):
    quote: str
    verdict: str
    fact_id: str | None = None


class AnswerCheck(BaseModel):
    id: str
    mentions_business: bool = False
    specific: bool = False
    confused_with: str | None = None
    claims: list[Claim] = Field(default_factory=list)


class AnswerChecks(BaseModel):
    answers: list[AnswerCheck] = Field(default_factory=list)


class PairCheck(BaseModel):
    id: str
    contradicts: bool


class PairChecks(BaseModel):
    pairs: list[PairCheck] = Field(default_factory=list)


# Key offerings an accurate answer should state come from the business type's pack; these fit any business.
DEFAULT_KEY_FACTS = ("services", "locations_served")


def key_facts(archetype_id: str | None) -> tuple[str, ...]:
    the_pack = pack(archetype_id)
    return the_pack.key_offerings if the_pack and the_pack.key_offerings else DEFAULT_KEY_FACTS


def _words(keys) -> str:
    return ", ".join(k.replace("_", " ") for k in keys)


class AIBrandAccuracy(Agent):
    id = "G5"
    name = "AI Brand Accuracy"
    pillar = Pillar.GEO
    counts_toward_readiness = False  # dated, sampled observations (docs/spec/04)
    requires = frozenset({EvidenceType.AI_ANSWERS, EvidenceType.FACTS})
    signature_columns = ["Surface", "Prompt", "Claim (quoted)", "Verdict", "Fact"]
    checks = [
        CheckSpec(id="G5.01", title="Accuracy of AI-stated facts", default_severity=Sev.HIGH, method="M+L",
                  counts_toward_readiness=False),
        CheckSpec(id="G5.02", title="Specificity of AI descriptions", default_severity=Sev.MEDIUM, method="M+L",
                  counts_toward_readiness=False),
        CheckSpec(id="G5.03", title="Key offerings missing from AI answers", default_severity=Sev.MEDIUM,
                  method="M+L", counts_toward_readiness=False),
        CheckSpec(id="G5.04", title="Entity confusion", default_severity=Sev.HIGH, method="M+L",
                  counts_toward_readiness=False),
    ]

    def run_unit(self, ctx: AgentContext, unit: WorkUnit) -> AgentResult:
        facts = [f for f in fact_sheet(ctx) if f["status"] in ("site-stated", "team-confirmed")]
        fact_ids = {f["id"]: f for f in facts}
        name = next((f["value"] for f in facts if f["key"] in ("property_name", "business_name")), ctx.client.name)
        coverage = Coverage()
        by_surface: dict[str, list[dict]] = {}
        labels = {}
        for ev in ctx.snapshot.evidence(EvidenceType.AI_ANSWERS):
            surface = ev.payload["surface"]
            labels[surface] = ev.payload.get("label", surface)
            for answer in ev.payload.get("answers", []):
                brand_prompt = answer.get("prompt_kind") in ("brand", "brand-fact")
                if brand_prompt or normalize(name) in normalize(answer.get("text", "")):
                    by_surface.setdefault(surface, []).append(answer)
        if not by_surface:
            coverage.skipped.append("No AI answers about the business were captured (C10).")
            return AgentResult(findings=[self.finding(c.id, St.UNVERIFIABLE, "No AI answers to check")
                                         for c in self.checks], coverage=coverage)

        results: list[tuple[str, dict, AnswerCheck]] = []
        wanted = key_facts(archetype(ctx))
        # Key offerings first, so the 40 facts the model sees always include them.
        ordered = sorted(facts, key=lambda f: f["key"] not in wanted)
        fact_lines = "\n".join(f"{f['id']} {f['key']} = {f['value']}" for f in ordered[:40])
        for surface, answers in by_surface.items():
            if ctx.llm is None:
                coverage.skipped.append("Claim checks need the LLM (off in this run).")
                break
            blocks = "\n".join(f"ANSWER A{i + 1} ({surface}): {a['text'][:1500]}" for i, a in enumerate(answers))
            try:
                checked = ctx.llm.complete_json(load_prompt("g5.claims", 2), AnswerChecks, business=name,
                                                facts=fact_lines, answers=blocks).data
            except LLMError as exc:
                coverage.skipped.append(f"{surface}: {exc}")
                continue
            by_id = {c.id: c for c in checked.answers}
            for i, answer in enumerate(answers):
                check = by_id.get(f"A{i + 1}")
                if check is None:
                    continue
                # Keep only claims quoted from the answer; "wrong" must cite a real fact.
                check.claims = [c for c in check.claims if quote_in_text(c.quote, answer["text"])
                                and (c.verdict != "wrong" or c.fact_id in fact_ids)]
                results.append((surface, answer, check))
        overturned = self._second_opinion(ctx, results, fact_ids, coverage)
        coverage.examined = {"answers": len(results), "surfaces": len(by_surface),
                             "wrong_claims_overturned_by_second_opinion": overturned}
        coverage.limits.append("Model answers are samples from a given day; knowledge probes reflect training "
                               "data, not live search.")

        rows, wrong, generic, confused = [], [], [], []
        mentioned_keys: dict[str, set[str]] = {}
        for surface, answer, check in results:
            for claim in check.claims:
                rows.append([labels[surface], answer["prompt"][:60], claim.quote[:90], claim.verdict,
                             claim.fact_id or "—"])
                if claim.verdict == "wrong":
                    wrong.append((surface, answer, claim))
                if claim.fact_id in fact_ids and claim.verdict == "correct":
                    mentioned_keys.setdefault(surface, set()).add(fact_ids[claim.fact_id]["key"])
            if check.mentions_business and not check.specific:
                generic.append((surface, answer))
            if check.confused_with:
                confused.append((surface, answer, check.confused_with))

        findings = []
        findings.append(self.finding(
            "G5.01", St.FAIL if wrong else St.PASS,
            f"{len(wrong)} wrong fact(s) about the business in AI answers" if wrong
            else "No AI answer contradicts the business's facts", confidence=Confidence.LIKELY,
            evidence=[EvidenceRef(type="ai_answer", excerpt=f"{labels[s]}: \"{c.quote}\" vs {c.fact_id} "
                                                            f"({fact_ids[c.fact_id]['key']} = {fact_ids[c.fact_id]['value']})")
                      for s, _, c in wrong[:5]] or [EvidenceRef(type="ai_answer", excerpt=f"{len(results)} answers "
                                                                                        "checked")],
            impact="Customers asking AI assistants get wrong details about the business and may choose another.",
            fix="Make the correct facts explicit and consistent on the site, in structured data and on the "
                "third-party listings AI systems read.",
            verification="Re-run C10 + G5 after the next model/index refresh.", effort=Effort.M))
        findings.append(self.finding(
            "G5.02", St.WARN if generic else St.PASS,
            f"{len(generic)} AI answer(s) mention the business only in generic terms" if generic
            else "AI answers describe the business with specific details", confidence=Confidence.LIKELY,
            evidence=[EvidenceRef(type="ai_answer", excerpt=f"{labels[s]}: {a['text'][:150]}") for s, a in generic[:3]]
            or [EvidenceRef(type="ai_answer", excerpt="specific answers")],
            impact="Generic descriptions give customers no reason to choose this business.",
            fix=f"Publish distinctive, quotable facts (such as {_words(wanted[:3])}) on key pages and listings.",
            verification="AI answers repeat specific facts.", effort=Effort.M))
        known = [k for k in wanted if any(f["key"] == k for f in facts)]
        if not known:
            findings.append(self.finding(
                "G5.03", St.UNVERIFIABLE,
                f"No key facts for this type of business found on the site to compare (such as {_words(wanted[:3])})",
                evidence=[EvidenceRef(type="html_excerpt", excerpt=f"key facts looked for: {_words(wanted)}")]))
            findings.append(self._confusion(confused, labels))
            return AgentResult(findings=findings, coverage=coverage,
                               signature_table={"columns": self.signature_columns, "rows": rows})
        per_surface = {s: [k for k in known if k not in mentioned_keys.get(s, set())] for s in by_surface}
        lacking = {s: m for s, m in per_surface.items() if len(m) > len(known) / 2}
        findings.append(self.finding(
            "G5.03", St.WARN if lacking else St.PASS,
            f"{len(lacking)} AI source(s) state fewer than half of the key facts correctly" if lacking
            else "Every AI source states most key facts correctly", confidence=Confidence.LIKELY,
            evidence=[EvidenceRef(type="ai_answer", excerpt=f"{labels[s]}: {len(known) - len(m)} of {len(known)} key "
                                                            f"facts stated correctly (missing: {', '.join(m)})")
                      for s, m in per_surface.items()],
            impact="What the AI doesn't know, it can't recommend.",
            fix="Repeat these facts in clear, self-contained sentences on the site and on major listings.",
            verification="Re-run C10 + G5.", effort=Effort.M))
        findings.append(self._confusion(confused, labels))
        return AgentResult(findings=findings, coverage=coverage,
                           signature_table={"columns": self.signature_columns, "rows": rows})

    def _confusion(self, confused, labels):
        return self.finding(
            "G5.04", St.FAIL if confused else St.PASS,
            f"{len(confused)} AI answer(s) mix the business up with another" if confused
            else "No entity confusion found", confidence=Confidence.LIKELY,
            evidence=[EvidenceRef(type="ai_answer", excerpt=f"{labels[s]}: confused with {other}")
                      for s, _, other in confused[:3]] or [EvidenceRef(type="ai_answer", excerpt="none")],
            impact="Customers get another business's details or reviews.",
            fix="Strengthen entity signals: consistent name, address and sameAs links across site and profiles.",
            verification="Re-run C10 + G5.", effort=Effort.M)

    @staticmethod
    def _second_opinion(ctx: AgentContext, results, fact_ids: dict, coverage: Coverage) -> int:
        """Re-check every "wrong" claim with a different model family; keep it wrong only if both agree."""
        pairs = [(surface, check, claim) for surface, _, check in results for claim in check.claims
                 if claim.verdict == "wrong"]
        if not pairs or ctx.llm is None:
            return 0
        text = "\n".join(f"PAIR C{i + 1}: CLAIM \"{c.quote}\" | FACT {fact_ids[c.fact_id]['key']} = "
                         f"{fact_ids[c.fact_id]['value']}" for i, (_, _, c) in enumerate(pairs))
        try:
            verdicts = ctx.llm.complete_json(load_prompt("g5.verify", 1), PairChecks, prefer="groq", pairs=text).data
        except LLMError as exc:
            coverage.limits.append(f"Second-opinion check unavailable ({exc}); 'wrong' verdicts are single-model.")
            return 0
        agreed = {p.id: p.contradicts for p in verdicts.pairs}
        overturned = 0
        for i, (_, _, claim) in enumerate(pairs):
            if agreed.get(f"C{i + 1}") is False:
                claim.verdict = "unverifiable"
                overturned += 1
        return overturned
