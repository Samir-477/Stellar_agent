"""A1 Answer Coverage & Drafts: for each real customer question, does the site contain a
complete, accurate answer?

Questions come from C7 (observed first: People Also Ask, India autocomplete; then on-site,
then framework-generated). Candidate passages are retrieved deterministically (BM25) from the
entry page and key pages; one batched LLM call judges each question and drafts answers for
partial ones, using only the retrieved passages. Drafts must pass the fact guard.
"""

from __future__ import annotations

from pydantic import BaseModel, Field

from engine.agents.base import Agent
from engine.agents.common import business_name, key_page_urls, load_pages, tally
from engine.context import AgentContext, WorkUnit
from engine.lib.content import sections, template_blocks
from engine.lib.grounding import value_supported
from engine.lib.locators import text_hash
from engine.lib.retrieval import BM25
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
    Locator,
    Patch,
    PatchType,
    Pillar,
    Severity as Sev,
)

MAX_QUESTIONS = 12
BATCH = 6
SOURCE_ORDER = {"observed-paa": 0, "observed-autocomplete": 1, "on-site": 2, "framework-generated": 3}
OBSERVED = {"observed-paa", "observed-autocomplete"}


class Answer(BaseModel):
    id: str
    verdict: str
    passage: str | None = None
    needs: str | None = None
    draft: str | None = None


class Answers(BaseModel):
    answers: list[Answer] = Field(default_factory=list)


class AnswerCoverage(Agent):
    id = "A1"
    name = "Answer Coverage & Drafts"
    pillar = Pillar.AEO
    requires = frozenset({EvidenceType.QUESTIONS, EvidenceType.PAGES_PARSED, EvidenceType.FACTS})
    signature_columns = ["Question", "Source", "Stage", "Verdict", "Best passage", "Draft ready"]
    checks = [
        CheckSpec(id="A1.01", title="Observed questions answered", default_severity=Sev.HIGH, method="L"),
        CheckSpec(id="A1.02", title="Framework-generated questions answered", default_severity=Sev.MEDIUM, method="L"),
        CheckSpec(id="A1.03", title="Answer accuracy vs Fact Sheet", default_severity=Sev.HIGH, method="D+L"),
        CheckSpec(id="A1.04", title="Topic coverage", default_severity=Sev.MEDIUM, method="L"),
    ]

    def run_unit(self, ctx: AgentContext, unit: WorkUnit) -> AgentResult:
        evidence = ctx.snapshot.evidence(EvidenceType.QUESTIONS)
        library = evidence[-1].payload.get("questions", []) if evidence else []
        questions = sorted([q for q in library if q.get("relevant", True) and not q.get("duplicate_of")],
                           key=lambda q: SOURCE_ORDER.get(q["source"], 9))[:MAX_QUESTIONS]
        pages = [p for p in load_pages(ctx) if p.is_html]
        keys = key_page_urls(pages, ctx.client.primary_url)
        template = template_blocks([p.model for p in pages])
        # Retrieval units are sections (heading + its text), so a heading like "How to get there" helps
        # find its own answer; the unit's locator is its first passage (where drafts get inserted).
        passages = []
        for p in pages:
            if p.url not in keys:
                continue
            for sec in sections(p.model, template=template):
                body = " ".join(b["text"] for b in sec["passages"])
                if len(body.split()) >= 8:
                    passages.append((p, {"text": f"{sec['heading']}: {body}"[:1500], "heading": sec["heading"],
                                         "locator": sec["passages"][0]["locator"]}))
        # Heading words are the strongest signal of what a section answers: weight them 3x for ranking.
        index = BM25([f"{b['heading']} {b['heading']} {b['text']}" for _, b in passages]) if passages else None
        name = business_name(ctx)
        coverage = Coverage(examined={"questions": len(questions), "passages": len(passages)})
        if not questions:
            coverage.skipped.append("No question library (C7) for this snapshot.")
            return AgentResult(findings=[self.finding(c, St.UNVERIFIABLE, "No questions to check")
                                         for c in ("A1.01", "A1.02", "A1.03", "A1.04")], coverage=coverage)

        retrieved = {q["id"]: (index.top(q["text"], 3) if index else []) for q in questions}
        verdicts: dict[str, Answer] = {}
        if ctx.llm is None:
            coverage.skipped.append("Answer verdicts need the LLM (off in this run).")
        else:
            for start in range(0, len(questions), BATCH):
                batch = questions[start:start + BATCH]
                blocks = []
                for q in batch:
                    blocks.append(f"QUESTION {q['id']}: {q.get('question') or q['text']}")
                    for rank, (i, _) in enumerate(retrieved[q["id"]], start=1):
                        page, block = passages[i]
                        blocks.append(f"{q['id']}P{rank} ({page.url}): {block['text'][:700]}")
                try:
                    answer = ctx.llm.complete_json(load_prompt("a1.coverage", 2), Answers,
                                                   business=name, questions="\n".join(blocks)).data
                    verdicts.update({a.id: a for a in answer.answers})
                except LLMError as exc:
                    coverage.skipped.append(f"LLM batch failed: {exc}")

        findings, patches, rows, rejected = [], [], [], 0
        buckets = {True: {"missing": [], "partial": [], "needs": [], "patches": []},
                   False: {"missing": [], "partial": [], "needs": [], "patches": []}}
        topics: dict[str, list[str]] = {}
        drafted_sections: set[str] = set()  # one draft per section: repeated near-identical Q&As read as spam
        for q in questions:
            a = verdicts.get(q["id"])
            if a is None:
                continue
            best = None
            if a.passage and a.passage.startswith(q["id"] + "P"):
                rank = int(a.passage.split("P")[-1]) - 1
                if 0 <= rank < len(retrieved[q["id"]]):
                    best = passages[retrieved[q["id"]][rank][0]]
            bucket = buckets[q["source"] in OBSERVED]
            if a.verdict in ("missing", "partial"):
                bucket[a.verdict].append((q, a))
                if a.needs:
                    bucket["needs"].append(f"{q['text']}: {a.needs}")
            topics.setdefault(q.get("topic") or "general", []).append(a.verdict)
            draft_ok = False
            section_key = f"{best[0].url}|{best[1]['locator'].get('xpath')}" if best else None
            if a.verdict == "partial" and a.draft and best and section_key not in drafted_sections:
                source = " ".join(passages[i][1]["text"] for i, _ in retrieved[q["id"]]) + " " + name
                draft_ok = 20 <= len(a.draft.split()) <= 75 and value_supported(a.draft, source, min_word_share=0.6)
                if draft_ok:
                    key = f"A1:answer:{text_hash(q['text'])}"
                    patches.append(Patch(
                        key=key, agent_id=self.id, page_url=best[0].url, type=PatchType.ELEMENT_INSERT,
                        locator=Locator(**best[1]["locator"]), before=None, confidence=Confidence.LIKELY,
                        after=f"<h3>{q.get('question') or q['text']}</h3>\n<p>{a.draft}</p>",
                        rationale=f"Customers ask \"{q['text']}\" ({q['source']}); the page only answers it partly. "
                                  "Draft built from the page's own text.",
                        client_visible_note="Answers a question customers search for, directly on the page."))
                    bucket["patches"].append(key)
                    drafted_sections.add(section_key)
                else:
                    rejected += 1
            rows.append([q.get("question") or q["text"], q["source"], q.get("stage", "—"), a.verdict,
                         (best[1]["text"][:90] + "…") if best else "—", "yes" if draft_ok else "no"])

        findings.append(self._rollup("A1.01", buckets[True], observed=True))
        findings.append(self._rollup("A1.02", buckets[False], observed=False))
        findings.append(self.finding("A1.03", St.UNVERIFIABLE,
                                     "Accuracy against the Fact Sheet is not checked in this version"))
        absent = [t for t, v in topics.items() if v and all(x == "missing" for x in v)]
        findings.append(self.finding(
            "A1.04", St.WARN if absent else St.PASS,
            f"{len(absent)} customer topic(s) have no answer anywhere: {', '.join(absent)}" if absent
            else "Every customer topic is at least partly covered", confidence=Confidence.LIKELY,
            evidence=[EvidenceRef(type="ai_answer", excerpt=f"topic '{t}': {len(topics[t])} question(s), none answered")
                      for t in absent[:5]] or [EvidenceRef(type="ai_answer", excerpt=f"{len(topics)} topics checked")],
            impact="Whole topics customers ask about are absent, so neither search engines nor AI assistants can "
                   "use this site to answer them.",
            missing_facts=absent, fix="Add a short, factual section for each missing topic.",
            verification="Re-run A1."))
        if rejected:
            coverage.limits.append(f"{rejected} draft answer(s) were discarded by the fact guard.")
        return AgentResult(findings=findings, patches=patches, coverage=coverage,
                           signature_table={"columns": self.signature_columns, "rows": rows})

    def _rollup(self, check_id, bucket: dict, *, observed: bool):
        missing, partial = bucket["missing"], bucket["partial"]
        label = "observed" if observed else "framework-generated"
        if not missing and not partial:
            return self.finding(check_id, St.PASS, f"All reviewed {label} questions are answered completely",
                                confidence=Confidence.LIKELY)
        status = St.FAIL if observed and len(missing) >= 2 else St.WARN
        return self.finding(
            check_id, status, tally((len(missing), f"{label} question(s) unanswered"),
                                    (len(partial), f"{label} question(s) answered only partly")),
            confidence=Confidence.LIKELY,
            evidence=[EvidenceRef(type="ai_answer", excerpt=f"missing: \"{q['text']}\" ({q['source']})")
                      for q, _ in missing[:4]]
            + [EvidenceRef(type="ai_answer", excerpt=f"partial: \"{q['text']}\"") for q, _ in partial[:3]],
            missing_facts=bucket["needs"][:8], patch_keys=bucket["patches"],
            impact="When the site doesn't answer what customers search for, Google and AI assistants quote other "
                   "sites instead.",
            fix="Add direct answers (drafts proposed for partial answers; missing ones need the facts listed).",
            verification="Re-run A1: questions answered completely.", effort=Effort.M)
