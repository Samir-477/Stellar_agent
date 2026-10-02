"""A2 Answer Structure & Snippet Eligibility: are answers written so a search engine can lift them?

Deterministic: question-style headings (A2.02), long answer paragraphs (A2.05),
empty Q&A answers (A2.06), snippet controls (A2.07).
LLM (one batched call, fast tier): answer-first openings (A2.01), self-containment
(A2.03), format fit (A2.04), and a grounded question + 40–60 word answer draft per
section. Drafts must pass the fact guard: every number must appear in the section,
and most of the draft's words must come from the section text.
"""

from __future__ import annotations

import html
import re

from pydantic import BaseModel, Field

from engine.agents.base import Agent
from engine.agents.common import PageView, entry_page, key_page_urls, load_pages
from engine.context import AgentContext, WorkUnit
from engine.lib.content import is_question, sections, template_blocks
from engine.lib.grounding import value_supported
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
    Finding,
    Locator,
    Patch,
    PatchType,
    Pillar,
    Severity as Sev,
)

MAX_SECTIONS = 8
MIN_SECTION_WORDS = 25


class SectionReview(BaseModel):
    id: str
    opening: str
    self_contained: bool = True
    better_format: str = "none"
    question: str | None = None
    answer: str | None = None
    items: list[str] = Field(default_factory=list)  # the section as list items, when it reads better as a list


class SectionsReview(BaseModel):
    sections: list[SectionReview] = Field(default_factory=list)


class AnswerStructure(Agent):
    id = "A2"
    name = "Answer Structure & Snippet Eligibility"
    pillar = Pillar.AEO
    requires = frozenset({EvidenceType.PAGES_PARSED})
    signature_columns = ["Page", "Section", "Opening", "Self-contained", "Better format", "Proposed question"]
    checks = [
        CheckSpec(id="A2.01", title="Answer-first openings", default_severity=Sev.MEDIUM, method="D+L"),
        CheckSpec(id="A2.02", title="Question-style headings", default_severity=Sev.LOW, method="D"),
        CheckSpec(id="A2.03", title="Self-contained passages", default_severity=Sev.MEDIUM, method="L"),
        CheckSpec(id="A2.04", title="Format fit (lists, tables, steps)", default_severity=Sev.MEDIUM, method="L"),
        CheckSpec(id="A2.05", title="Paragraph length in answers", default_severity=Sev.LOW, method="D"),
        CheckSpec(id="A2.06", title="Q&A sections well formed", default_severity=Sev.LOW, method="D"),
        CheckSpec(id="A2.07", title="Snippet controls", default_severity=Sev.HIGH, method="D"),
    ]

    def run_unit(self, ctx: AgentContext, unit: WorkUnit) -> AgentResult:
        pages = [p for p in load_pages(ctx) if p.is_html]
        keys = key_page_urls(pages, ctx.client.primary_url)
        entry = entry_page(pages, ctx.client.primary_url)
        template = template_blocks([p.model for p in pages])
        page_sections = {p.url: [s for s in sections(p.model, template=template)
                                 if sum(len(b["text"].split()) for b in s["passages"]) >= MIN_SECTION_WORDS]
                         for p in pages}
        findings: list[Finding] = []
        findings += self._question_headings(pages, page_sections, keys)
        findings += self._paragraph_length(pages, page_sections, keys)
        findings += self._qa_formed(pages)
        findings += self._snippet_controls(pages, keys)

        targets = self._targets(entry, pages, keys, page_sections)
        reviews, note = self._review(ctx, entry, targets)
        llm_findings, patches, rows, rejected = self._from_reviews(targets, reviews, keys)
        findings += llm_findings
        # Drafts not already tied to A2.01 support the question-headings finding.
        referenced = {k for f in findings for k in f.patch_keys}
        spare = [p.key for p in patches if p.key not in referenced]
        holder = next((f for f in findings if f.check_id == "A2.02" and f.status in (St.WARN, St.FAIL)), None)
        if spare and holder:
            holder.patch_keys.extend(spare)
        elif spare:
            # No reported issue asks for these drafts (the headings check passed), so they aren't proposed;
            # left in, validation dropped them and the run finished "with gaps" (Flipkart run, 2026-09-29).
            patches = [p for p in patches if p.key not in set(spare)]
        coverage = Coverage(examined={"pages": len(pages), "sections_reviewed": len(reviews)})
        if note:
            coverage.skipped.append(note)
        if rejected:
            coverage.limits.append(f"{rejected} draft answer(s) were discarded because they used words or numbers "
                                   "not found in the section (fact guard).")
        return AgentResult(findings=findings, patches=patches, coverage=coverage,
                           signature_table={"columns": self.signature_columns, "rows": rows})

    # ------------------------------------------------------- deterministic

    def _question_headings(self, pages, page_sections, keys):
        key_pages = [p for p in pages if p.url in keys and page_sections[p.url]]
        without = [p for p in key_pages if not any(is_question(s["heading"]) for s in page_sections[p.url])]
        if not key_pages:
            return [self.finding("A2.02", St.NOT_APPLICABLE, "No substantial sections on key pages")]
        if not without:
            return [self.finding("A2.02", St.PASS, "Key pages use question-style headings where they answer questions")]
        return [self.finding(
            "A2.02", St.WARN, f"{len(without)} key page(s) have no question-style headings",
            pages=[p.url for p in without], key_page=True,
            evidence=[EvidenceRef(type="html_excerpt", url=p.url,
                                  excerpt="headings: " + ", ".join(s["heading"] for s in page_sections[p.url][:6]))
                      for p in without[:3]],
            impact="Label headings (\"Overview\", \"Features\") don't match how people search or ask assistants, so "
                   "answer engines find it harder to lift a direct answer.",
            fix="Rephrase key section headings as the questions customers ask, with the answer right below.",
            verification="Key sections have question-style headings followed by a direct answer.", effort=Effort.S)]

    def _paragraph_length(self, pages, page_sections, keys):
        long = [(p, b) for p in pages if p.url in keys for s in page_sections[p.url] for b in s["passages"]
                if len(b["text"].split()) > 120]
        if not long:
            return [self.finding("A2.05", St.PASS, "Answer paragraphs on key pages are short enough to quote")]
        return [self.finding(
            "A2.05", St.WARN, f"{len(long)} paragraph(s) on key pages run over 120 words",
            pages=sorted({p.url for p, _ in long}),
            evidence=[EvidenceRef(type="html_excerpt", url=p.url,
                                  excerpt=f"{len(b['text'].split())} words: {b['text'][:100]}…") for p, b in long[:3]],
            impact="Long paragraphs are hard to scan and rarely quoted whole.", fix="Split into 2–4 sentence paragraphs.",
            verification="Paragraphs under ~120 words.", effort=Effort.S)]

    def _qa_formed(self, pages):
        empty = []
        for p in pages:
            outline = p.model.get("outline", [])
            for i, block in enumerate(outline):
                if block["type"] == "heading" and is_question(block["text"]):
                    nxt = outline[i + 1] if i + 1 < len(outline) else None
                    if nxt is None or nxt["type"] == "heading":
                        empty.append((p, block["text"]))
        if not empty:
            return [self.finding("A2.06", St.PASS, "Every question heading is followed by an answer in the HTML")]
        return [self.finding(
            "A2.06", St.WARN, f"{len(empty)} question heading(s) have no answer text in the server HTML",
            pages=sorted({p.url for p, _ in empty}), confidence=Confidence.LIKELY,
            evidence=[EvidenceRef(type="html_excerpt", url=p.url, excerpt=q[:150]) for p, q in empty[:5]],
            impact="Answers loaded only on click or by JavaScript may not be read by crawlers.",
            fix="Include the answer text in the HTML (accordions can hide it visually).",
            verification="Each question has its answer in the page source.", effort=Effort.S)]

    def _snippet_controls(self, pages, keys):
        blocked = []
        for p in pages:
            robots = (p.model.get("meta_robots") or "").lower() + " " + p.headers.get("x-robots-tag", "").lower()
            if "nosnippet" in robots or "max-snippet:0" in robots.replace(" ", ""):
                blocked.append((p, "meta robots / X-Robots-Tag: " + robots.strip()))
            elif p.model.get("nosnippet_elements"):
                blocked.append((p, f"{p.model['nosnippet_elements']} element(s) with data-nosnippet"))
        if not blocked:
            return [self.finding("A2.07", St.PASS, "No snippet controls block answers from being shown")]
        return [self.finding(
            "A2.07", St.FAIL, f"Snippet controls restrict {len(blocked)} page(s)", pages=[p.url for p, _ in blocked],
            key_page=any(p.url in keys for p, _ in blocked),
            evidence=[EvidenceRef(type="html_excerpt", url=p.url, excerpt=why) for p, why in blocked[:5]],
            impact="nosnippet/max-snippet:0 stop Google showing the text as a snippet or in AI Overviews.",
            fix="Remove snippet restrictions from content you want quoted.", verification="No nosnippet on answers.",
            effort=Effort.S)]

    # ----------------------------------------------------------------- LLM

    @staticmethod
    def _targets(entry, pages, keys, page_sections) -> list[tuple[PageView, dict]]:
        ordered = ([entry] if entry else []) + [p for p in pages if p.url in keys and p is not entry]
        targets = [(p, s) for p in ordered for s in page_sections.get(p.url, [])]
        return targets[:MAX_SECTIONS]

    def _review(self, ctx, entry, targets) -> tuple[dict[str, SectionReview], str | None]:
        if ctx.llm is None or not targets:
            return {}, "Answer-first, self-containment and format checks need the LLM (off in this run)."
        subject = next((h["text"] for h in (entry or targets[0][0]).model.get("headings", []) if h["level"] == 1), "")
        blocks = "\n\n".join(
            f"SECTION S{i + 1}\nPAGE: {page.url}\nHEADING: {sec['heading']}\n"
            f"TEXT: {' '.join(' '.join(b['text'] for b in sec['passages']).split()[:220])}"
            for i, (page, sec) in enumerate(targets))
        try:
            answer = ctx.llm.complete_json(load_prompt("a2.sections", 2), SectionsReview,
                                           subject=subject, sections=blocks).data
        except LLMError as exc:
            return {}, f"LLM review failed: {exc}"
        return {r.id: r for r in answer.sections}, None

    def _as_list(self, page, sec, review: SectionReview, text: str, index: int) -> Patch | None:
        """A prepared change (approval required): a one-paragraph section rewritten as the list or steps the model
        proposed. Kept only when every item comes from the section's own words and numbers."""
        items = [" ".join(item.split()) for item in review.items]
        passages = sec.get("passages") or []
        if review.better_format not in ("list", "steps") or not 2 <= len(items) <= 8 or len(passages) != 1                 or not passages[0].get("locator"):
            return None
        if not all(1 <= len(item.split()) <= 30 and value_supported(item, text, min_word_share=0.8) for item in items):
            return None
        tag = "ol" if review.better_format == "steps" else "ul"
        body = "".join(f"<li>{html.escape(item, quote=False)}</li>" for item in items)
        return Patch(key=f"A2:format:{page.record.id}:{index}", agent_id=self.id, page_url=page.url,
                     type=PatchType.ELEMENT_REPLACE, locator=Locator(**passages[0]["locator"]),
                     before=passages[0]["text"][:4000], after=f"<{tag}>{body}</{tag}>", confidence=Confidence.LIKELY,
                     approval="required",
                     rationale=f"The \"{sec['heading']}\" section as {'steps' if tag == 'ol' else 'a list'}, using only "
                               "the section's own words. Review it before publishing.",
                     client_visible_note="Turns a dense paragraph into a list that's easy to scan and to quote.")

    def _from_reviews(self, targets, reviews, keys):
        findings, patches, rows = [], [], []
        buried, not_contained, reformat, drafts, rejected = [], [], [], [], 0
        formats: dict[tuple[str, str], str] = {}
        for i, (page, sec) in enumerate(targets):
            review = reviews.get(f"S{i + 1}")
            if review is None:
                continue
            text = " ".join(b["text"] for b in sec["passages"])
            source = text + " " + sec["heading"] + " " + " ".join(h["text"] for h in page.model.get("headings", [])
                                                                   if h["level"] == 1)
            if review.opening in ("buried", "none"):
                buried.append((page, sec, review))
            if not review.self_contained:
                not_contained.append((page, sec))
            if review.better_format in ("list", "table", "steps"):
                reformat.append((page, sec, review.better_format))
                listed = self._as_list(page, sec, review, text, i)
                if listed:
                    patches.append(listed)
                    formats[(page.url, sec["heading"])] = listed.key
            draft_ok = bool(review.answer and review.question and 30 <= len(review.answer.split()) <= 75
                            and value_supported(review.answer, source, min_word_share=0.6))
            if review.answer and not draft_ok:
                rejected += 1
            if draft_ok and (review.opening != "direct" or not is_question(sec["heading"])):
                first = sec["passages"][0] if sec["passages"] else None
                key = f"A2:lead:{page.record.id}:{i}"
                patches.append(Patch(
                    key=key, agent_id=self.id, page_url=page.url, type=PatchType.ELEMENT_INSERT,
                    locator=Locator(**first["locator"]) if first else Locator(**sec["locator"]),
                    before=None, confidence=Confidence.LIKELY,
                    after=f"<h2>{review.question}</h2>\n<p>{review.answer}</p>",
                    rationale=f"Question-style heading and answer-first paragraph for the \"{sec['heading']}\" "
                              "section, written only from that section's text.",
                    client_visible_note="Puts a direct answer first so search engines and AI assistants can quote it."))
                drafts.append((page, sec, key))
            rows.append([page.url, sec["heading"], review.opening, "yes" if review.self_contained else "no",
                         review.better_format, review.question or "—"])

        if not reviews:
            return [self.finding(c, St.UNVERIFIABLE, "Not judged (LLM unavailable or no sections)")
                    for c in ("A2.01", "A2.03", "A2.04")], patches, rows, rejected
        draft_keys = {(p.url, s["heading"]): k for p, s, k in drafts}
        if buried:
            findings.append(self.finding(
                "A2.01", St.FAIL if len(buried) >= len(reviews) / 2 else St.WARN,
                f"{len(buried)} of {len(reviews)} reviewed sections don't open with a direct answer",
                pages=sorted({p.url for p, _, _ in buried}), confidence=Confidence.LIKELY,
                key_page=any(p.url in keys for p, _, _ in buried),
                patch_keys=[draft_keys[(p.url, s["heading"])] for p, s, _ in buried if (p.url, s["heading"]) in draft_keys],
                evidence=[EvidenceRef(type="html_excerpt", url=p.url,
                                      excerpt=f"\"{s['heading']}\" ({r.opening}): "
                                              f"{(s['passages'][0]['text'] if s['passages'] else '')[:110]}…")
                          for p, s, r in buried[:5]],
                impact="Answer engines prefer passages that answer in the first sentence; these sections make "
                       "readers and crawlers dig for it.",
                fix="Open each section with a direct 40–60 word answer (drafts proposed).",
                verification="Each section's first sentences answer its heading.", effort=Effort.S))
        else:
            findings.append(self.finding("A2.01", St.PASS, "Reviewed sections open with a direct answer",
                                         confidence=Confidence.LIKELY))
        findings.append(self.finding(
            "A2.03", St.WARN, f"{len(not_contained)} section(s) rely on context from elsewhere on the page",
            pages=sorted({p.url for p, _ in not_contained}), confidence=Confidence.LIKELY,
            evidence=[EvidenceRef(type="html_excerpt", url=p.url, excerpt=f"\"{s['heading']}\"") for p, s in not_contained[:5]],
            impact="Quoted alone, these passages don't say what they're about, so they're less useful as answers.",
            fix="Name the subject (the business, product or service) inside each section.",
            verification="Each section makes sense when quoted alone.") if not_contained
            else self.finding("A2.03", St.PASS, "Reviewed sections make sense when quoted alone",
                              confidence=Confidence.LIKELY))
        findings.append(self.finding(
            "A2.04", St.WARN, f"{len(reformat)} section(s) would read better as a list, table or steps",
            pages=sorted({p.url for p, _, _ in reformat}), confidence=Confidence.LIKELY,
            evidence=[EvidenceRef(type="html_excerpt", url=p.url, excerpt=f"\"{s['heading']}\" → {fmt}")
                      for p, s, fmt in reformat[:5]],
            patch_keys=[formats[(p.url, s["heading"])] for p, s, _ in reformat if (p.url, s["heading"]) in formats],
            impact="List- and table-shaped answers are what featured snippets and AI Overviews lift.",
            fix="Present these as lists or tables.", verification="Sections use the suggested format.",
            effort=Effort.S) if reformat
            else self.finding("A2.04", St.PASS, "Content formats fit the answers", confidence=Confidence.LIKELY))
        return findings, patches, rows, rejected
