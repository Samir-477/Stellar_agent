"""A3 Journey Coverage: can a customer get from discovering the business to booking (applying,
buying) and managing it, using the site?

Deterministic: the archetype pack's critical tools (A3.02), found through form inputs, buttons,
links, visible text and JSON-LD; and whether the entry page offers a way on to the book stage
(A3.03). LLM (one call, fast tier): maps the entry page's sections, the key pages, tools and links
to the pack's journey stages (A3.01). A3.04 compares that coverage with the questions customers
were observed asking at each stage (C7).
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from pydantic import BaseModel, Field

from engine.agents.base import Agent
from engine.agents.common import (PageView, archetype, business_name, entry_page, key_page_urls, load_pages,
                                  norm, tally)
from engine.context import AgentContext, WorkUnit
from engine.lib.content import sections, template_blocks
from engine.lib.jsonld import page_nodes
from engine.llm import LLMError, load_prompt
from engine.rules.packs import CriticalTool, pack
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

MAX_SECTIONS = 20
MAX_PAGES = 10
MAX_LINKS = 40
BOOK = "book"


class StageVerdict(BaseModel):
    stage: str
    status: str
    ids: list[str] = Field(default_factory=list)
    note: str | None = None


class JourneyAnswer(BaseModel):
    stages: list[StageVerdict] = Field(default_factory=list)


@dataclass
class ToolState:
    tool: CriticalTool
    status: St
    detail: str
    where: list[str] = field(default_factory=list)

    def describe(self) -> str:
        return f"{self.tool.label} ({self.tool.stage}): {self.detail}"


@dataclass
class Stage:
    name: str
    meaning: str
    status: str | None = None  # covered | thin | absent | None (not judged)
    serving: list[str] = field(default_factory=list)  # descriptions of the sections/pages/tools/links
    note: str | None = None
    questions: list[dict] = field(default_factory=list)


def _search(pattern: str, value: str | None) -> bool:
    return bool(pattern and value and re.search(pattern, value, re.I))


def input_hit(page: PageView, pattern: str) -> str | None:
    """A form field whose name, id, placeholder or framework binding matches: the tool itself."""
    for field_ in (page.model.get("controls") or {}).get("inputs", []):
        label = " ".join(filter(None, (field_.get("name"), field_.get("id"), field_.get("placeholder"),
                                       field_.get("model"))))
        if _search(pattern, label):
            return f"input \"{label[:80]}\""
    return None


def cta_links(page: PageView, pattern: str, *, body_only: bool = False) -> list[dict]:
    """Links whose text or URL matches: calls to action leading to a tool."""
    return [link for link in page.model.get("links", [])
            if "{{" not in link["text"] and not (body_only and link.get("in_boilerplate"))
            and (_search(pattern, link["text"]) or _search(pattern, link["href"]))]


def cta_hit(page: PageView, pattern: str, *, body_only: bool = False) -> str | None:
    """A link or button leading to the tool (text or URL), described for evidence."""
    for link in cta_links(page, pattern, body_only=body_only):
        where = "menu" if link.get("in_boilerplate") else "page body"
        target = " (opens on the same page, a JavaScript pop-up)" if norm(link["href"]) == norm(page.url) else ""
        return f"link \"{link['text'][:60] or link['href']}\" ({where}){target}"
    for button in (page.model.get("controls") or {}).get("buttons", []):
        if body_only and button["in_boilerplate"]:
            continue
        if _search(pattern, button["text"]):
            return f"button \"{button['text']}\" ({'menu' if button['in_boilerplate'] else 'page body'})"
    return None


def text_hit(page: PageView, pattern: str) -> str | None:
    if not pattern:
        return None
    text = page.visible_text()
    match = re.search(pattern, text, re.I)
    return f"text \"{' '.join(text[max(0, match.start() - 40):match.end() + 40].split())}\"" if match else None


def jsonld_hit(page: PageView, props: tuple[str, ...]) -> str | None:
    for node in page_nodes(page.model):
        for prop in props:
            if node.get(prop) not in (None, "", []):
                return f"JSON-LD {prop}: {str(node[prop])[:60]}"
    return None


def tool_state(tool: CriticalTool, entry: PageView, pages: list[PageView]) -> ToolState:
    """Where the tool is, as a customer on the entry page meets it: on the entry page; on a page the
    entry page links to; linked, but not in the server HTML where the link goes (it likely loads with
    JavaScript); on unrelated pages only; only in JSON-LD; or nowhere. Information without a link
    pattern (e.g. room rates) is judged on the entry page only: prices elsewhere describe other offers."""
    def present(page):
        return input_hit(page, tool.controls) or text_hit(page, tool.text)

    on_entry = present(entry)
    if on_entry:
        return ToolState(tool, St.PASS, f"on the entry page: {on_entry}", [entry.url])
    declared = jsonld_hit(entry, tool.jsonld)
    if not tool.links:
        if declared:
            return ToolState(tool, St.WARN, f"on the entry page only in structured data ({declared}), not shown to "
                                            "visitors", [entry.url])
        return ToolState(tool, St.FAIL, "not on the entry page")
    elsewhere = {norm(p.url): (p, hit) for p in pages if p is not entry and (hit := present(p))}
    targets = {norm(link["href"]) for link in cta_links(entry, tool.links)}
    reached = [elsewhere[t] for t in targets if t in elsewhere]
    linked = cta_hit(entry, tool.links)
    if reached:
        page, hit = reached[0]
        return ToolState(tool, St.PASS, f"{hit} on {page.url}, which the entry page links to", [page.url])
    if linked:
        other = f"; the site has it on {next(iter(elsewhere.values()))[0].url}" if elsewhere else ""
        return ToolState(tool, St.WARN, f"the entry page links to it ({linked}) but the tool isn't in the server "
                                        f"HTML where the link goes: it likely loads with JavaScript{other}",
                         [entry.url])
    if elsewhere:
        page, hit = next(iter(elsewhere.values()))
        return ToolState(tool, St.WARN, f"on {page.url} ({hit}) but the entry page doesn't link to it", [page.url])
    if declared:
        return ToolState(tool, St.WARN, f"only in structured data ({declared}), not shown to visitors", [entry.url])
    return ToolState(tool, St.FAIL, "not found on the sampled pages")


class JourneyCoverage(Agent):
    id = "A3"
    name = "Journey Coverage"
    pillar = Pillar.AEO
    requires = frozenset({EvidenceType.PAGES_PARSED, EvidenceType.QUESTIONS, EvidenceType.ARCHETYPE})
    signature_columns = ["Stage", "Pages and tools serving it", "Observed questions", "Coverage"]
    checks = [
        CheckSpec(id="A3.01", title="Stage presence", default_severity=Sev.MEDIUM, method="D+L"),
        CheckSpec(id="A3.02", title="Critical stage tools", default_severity=Sev.HIGH, method="D"),
        CheckSpec(id="A3.03", title="Stage-to-stage paths", default_severity=Sev.MEDIUM, method="D"),
        CheckSpec(id="A3.04", title="Demand vs coverage", default_severity=Sev.HIGH, method="S+L"),
    ]

    def run_unit(self, ctx: AgentContext, unit: WorkUnit) -> AgentResult:
        pages = [p for p in load_pages(ctx) if p.is_html]
        entry = entry_page(pages, ctx.client.primary_url)
        the_pack = pack(archetype(ctx))
        coverage = Coverage(examined={"pages": len(pages)})
        if entry is None or the_pack is None:
            reason = "The entry page wasn't fetched" if entry is None else "No archetype pack (journey unknown)"
            coverage.skipped.append(reason)
            return AgentResult(findings=[self.finding(c.id, St.UNVERIFIABLE, reason) for c in self.checks],
                               coverage=coverage)
        stages = [Stage(name, meaning) for name, meaning in the_pack.journey.items()]
        tools = [tool_state(t, entry, pages) for t in the_pack.critical_tools]
        evidence = ctx.snapshot.evidence(EvidenceType.QUESTIONS)
        for question in (evidence[-1].payload.get("questions", []) if evidence else []):
            if question.get("relevant", True) and not question.get("duplicate_of") \
                    and question["source"].startswith("observed"):
                stage = next((s for s in stages if s.name == question.get("stage")), None)
                if stage is not None:
                    stage.questions.append(question)
        coverage.examined.update({"tools": len(tools), "observed_questions": sum(len(s.questions) for s in stages)})
        coverage.limits.append("Tools are found in the server HTML of the sampled pages; a tool that loads with "
                               "JavaScript shows up only through the links that lead to it.")

        self._judge(ctx, entry, pages, stages, tools, the_pack.id, coverage)
        findings = [self._presence(stages), self._tools(tools),
                    self._paths(entry, [t for t in the_pack.critical_tools if t.stage == BOOK]),
                    self._demand(stages)]
        rows = [[s.name, "; ".join(s.serving)[:200] or "—", len(s.questions), s.status or "not judged"]
                for s in stages]
        return AgentResult(findings=findings, coverage=coverage,
                           signature_table={"columns": self.signature_columns, "rows": rows})

    # ------------------------------------------------------------ LLM: stage map (A3.01)

    def _judge(self, ctx, entry, pages, stages: list[Stage], tools: list[ToolState], archetype_id: str,
               coverage: Coverage) -> None:
        if ctx.llm is None:
            coverage.skipped.append("Stage mapping needs the LLM (off in this run).")
            return
        template = template_blocks([p.model for p in pages])
        items: dict[str, str] = {}
        for i, tool in enumerate(tools, start=1):
            items[f"T{i}"] = tool.describe()
        entry_sections = [s for s in sections(entry.model, template=template) if s["heading"].strip()]
        with_text = [s for s in entry_sections if s["passages"]][:MAX_SECTIONS]
        for i, sec in enumerate(with_text, start=1):
            body = " ".join(" ".join(b["text"] for b in sec["passages"]).split()[:25])
            items[f"S{i}"] = f"(entry page) {sec['heading'][:80]}: {body}"
        # Headings without text (galleries, tabs filled by JavaScript) still show what the page offers.
        bare = list(dict.fromkeys(s["heading"][:40] for s in entry_sections if not s["passages"]))[:15]
        if bare:
            items[f"S{len(with_text) + 1}"] = "(entry page) headings with no text of their own: " + ", ".join(bare)
        keys = key_page_urls(pages, ctx.client.primary_url)
        for i, page in enumerate([p for p in pages if p.url in keys and p is not entry][:MAX_PAGES], start=1):
            h1 = next((h["text"] for h in page.model.get("headings", []) if h["level"] == 1 and h["text"]), "")
            items[f"P{i}"] = f"({page.url}) {page.model.get('title') or ''} | {h1}"
        links: dict[str, str] = {}
        for link in sorted(entry.model.get("links", []), key=lambda l: l.get("in_boilerplate", False)):
            text = link["text"].strip()
            if text and "{{" not in text and text.lower() not in links:
                where = "footer" if link.get("in_footer") else "menu" if link.get("in_nav") else "page body"
                links[text.lower()] = f"{text[:60]} ({where})"
        for i, text in enumerate(list(links.values())[:MAX_LINKS], start=1):
            items[f"L{i}"] = text
        lines = {kind: "\n".join(f"{k} {v}" for k, v in items.items() if k[0] == kind) or "none" for kind in "TSPL"}
        try:
            answer = ctx.llm.complete_json(
                load_prompt("a3.journey", 2), JourneyAnswer,
                business=f"{business_name(ctx)} ({archetype_id})",
                stages="\n".join(f"{s.name}: {s.meaning}" for s in stages),
                tools=lines["T"], sections=lines["S"], pages=lines["P"], links=lines["L"]).data
        except LLMError as exc:
            coverage.skipped.append(f"Stage mapping failed: {exc}")
            return
        by_stage = {v.stage: v for v in answer.stages}
        dropped = 0
        for stage in stages:
            verdict = by_stage.get(stage.name)
            if verdict is None or verdict.status not in ("covered", "thin", "absent"):
                continue
            serving = [items[i] for i in dict.fromkeys(verdict.ids) if i in items]
            if verdict.status != "absent" and not serving:
                dropped += 1  # a positive verdict must point at something that exists
                continue
            stage.status, stage.serving, stage.note = verdict.status, serving, verdict.note
        if dropped:
            coverage.limits.append(f"{dropped} stage verdict(s) dropped: they cited nothing on the site.")

    # ------------------------------------------------------------ checks

    def _presence(self, stages: list[Stage]):
        judged = [s for s in stages if s.status]
        if not judged:
            return self.finding("A3.01", St.UNVERIFIABLE, "Journey stages not mapped")
        absent = [s for s in judged if s.status == "absent"]
        thin = [s for s in judged if s.status == "thin"]
        if not absent and not thin:
            return self.finding("A3.01", St.PASS, "Every journey stage has a page, section or tool",
                                confidence=Confidence.LIKELY,
                                evidence=[EvidenceRef(type="html_excerpt", excerpt=f"{s.name}: {s.serving[0][:200]}")
                                          for s in judged[:5]])
        weak = absent + thin
        return self.finding(
            "A3.01", St.FAIL if absent else St.WARN,
            tally((len(absent), "journey stage(s) with nothing on the site"), (len(thin), "thin stage(s)")) + ": "
            + ", ".join(f"{s.name} ({s.status})" for s in weak), confidence=Confidence.LIKELY,
            severity=Sev.HIGH if any(s.name == BOOK for s in weak) else None,
            evidence=[EvidenceRef(type="html_excerpt", excerpt=f"{s.name} ({s.meaning}): {s.status}"
                                                               + (f"; {s.note}" if s.note else "")) for s in weak[:5]],
            impact="Customers (and AI assistants answering for them) drop off at stages the site doesn't serve.",
            fix="Add a section, page or tool for each weak stage: " + "; ".join(f"{s.name} = {s.meaning}"
                                                                              for s in weak),
            verification="Re-run A3: every stage covered.", effort=Effort.M)

    def _tools(self, tools: list[ToolState]):
        if not tools:
            return self.finding("A3.02", St.NOT_APPLICABLE, "No critical tools defined for this archetype")
        missing = [t for t in tools if t.status == St.FAIL]
        hidden = [t for t in tools if t.status == St.WARN]
        evidence = [EvidenceRef(type="html_excerpt", url=(t.where or [None])[0], excerpt=t.describe()[:400])
                    for t in missing + hidden + [t for t in tools if t.status == St.PASS]][:6]
        if not missing and not hidden:
            return self.finding("A3.02", St.PASS, "The archetype's critical tools are present and in the HTML",
                                evidence=evidence)
        return self.finding(
            "A3.02", St.FAIL if missing else St.WARN,
            tally((len(missing), "critical tool(s) missing"), (len(hidden), "hard to find or not in the HTML"))
            + ": " + ", ".join(t.tool.label for t in missing + hidden),
            pages=sorted({u for t in missing + hidden for u in t.where}), evidence=evidence,
            confidence=Confidence.LIKELY,
            impact="Customers need these tools to act; tools that only load with JavaScript, or data that exists only "
                   "in structured data, are invisible to many crawlers and AI assistants.",
            fix="Put each tool (or at least its essentials: a working form, a 'from' price) in the server-rendered "
                "HTML of the page that needs it, and link to it from the entry page.",
            verification="Re-run A3: tools present in the HTML.", effort=Effort.M)

    def _paths(self, entry: PageView, book_tools: list[CriticalTool]):
        if not book_tools:
            return self.finding("A3.03", St.NOT_APPLICABLE, "No book-stage tool defined for this archetype")
        body = next((hit for t in book_tools for hit in (input_hit(entry, t.controls),
                                                        cta_hit(entry, t.links, body_only=True)) if hit), None)
        if body:
            return self.finding("A3.03", St.PASS, "The entry page leads on to booking from its content",
                                pages=[entry.url], evidence=[EvidenceRef(type="html_excerpt", url=entry.url,
                                                                         excerpt=body)])
        menu = next((hit for t in book_tools if (hit := cta_hit(entry, t.links))), None)
        if menu:
            return self.finding(
                "A3.03", St.WARN, "The entry page's only way to book is in the menu", pages=[entry.url],
                evidence=[EvidenceRef(type="html_excerpt", url=entry.url, excerpt=menu)],
                impact="Visitors who have just read about the offer look for the next step in the content, "
                       "not the menu.", fix="Add a clear call to action (e.g. 'Book this room') next to rooms, "
                                            "prices and at the end of the page.",
                verification="A body call to action leads to the book stage.", effort=Effort.S)
        return self.finding(
            "A3.03", St.FAIL, "The entry page is a dead end: no way on to booking", pages=[entry.url], key_page=True,
            evidence=[EvidenceRef(type="html_excerpt", url=entry.url,
                                  excerpt="no " + " / ".join(t.label for t in book_tools) + " link, button or form")],
            impact="Visitors ready to act have nowhere to go.", fix="Add a booking or enquiry call to action.",
            verification="A call to action leads to the book stage.", effort=Effort.S)

    def _demand(self, stages: list[Stage]):
        asked = [s for s in stages if s.questions]
        if not asked:
            return self.finding("A3.04", St.NOT_APPLICABLE, "No observed customer questions to compare")
        if all(s.status is None for s in asked):
            return self.finding("A3.04", St.UNVERIFIABLE, "Stage coverage not judged")
        unmet = [s for s in asked if s.status == "absent"]
        thin = [s for s in asked if s.status == "thin"]
        evidence = [EvidenceRef(type="serp", excerpt=f"{s.name}: {len(s.questions)} observed question(s), e.g. "
                                                     f"\"{s.questions[0].get('question') or s.questions[0]['text']}\"; "
                                                     f"coverage {s.status or 'not judged'}") for s in asked[:5]]
        if not unmet and not thin:
            return self.finding("A3.04", St.PASS, "Stages where customers ask questions have content",
                                confidence=Confidence.LIKELY, evidence=evidence)
        return self.finding(
            "A3.04", St.FAIL if unmet else St.WARN,
            tally((len(unmet), "stage(s) with observed demand and no content"),
                  (len(thin), "stage(s) with observed demand and thin content")),
            confidence=Confidence.LIKELY, evidence=evidence,
            impact="Customers are searching at these stages; without content there, other sites answer them.",
            fix="Cover the stages customers ask about first, starting with the questions listed.",
            verification="Re-run A3.", effort=Effort.M)
