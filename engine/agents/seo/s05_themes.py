"""S5 Keyword Themes & Cannibalization: does each theme customers search for have one page that owns
it, and do pages compete for the same theme?

Deterministic: demand signals (C5 queries, C7 questions, SerpAPI related searches and People Also
Ask) are clustered by shared words; candidate owner pages come from title, H1 and URL matches;
competition is backed by the SERP (two client URLs ranking for one theme's query) or by both pages
matching the theme's head words. LLM (one call, fast tier): names the themes, picks each owner,
flags competing pages and says what each page is for (S5.01–S5.03). S5.04 (local themes) and S5.05
(recurring themes absent from the site) are deterministic on top of that map.

These are demand signals, not search volumes; findings say so.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
from urllib.parse import urlsplit

from pydantic import BaseModel, Field

from engine.agents.base import Agent
from engine.agents.common import (PageView, archetype, brand_tokens, business_name, entry_page, key_page_urls,
                                  load_pages, norm, place_words, tally)
from engine.context import AgentContext, WorkUnit
from engine.lib.content import sections, template_headings
from engine.lib.grounding import normalize
from engine.lib.retrieval import tokens
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

MAX_CLUSTERS = 15
MAX_PAGES = 25
JOIN = 0.5  # word overlap (Jaccard) for a signal to join a theme
HEAD_SHARE = 0.5  # share of a theme's head words a page's title/H1/URL must contain to be a candidate
OBSERVED = ("paa", "related", "question:observed")
_GENERIC = {"hotel", "resort", "room", "stay", "service", "company", "online", "india", "price", "cost", "close",
            "closest", "nearby", "located", "location", "area", "around", "place", "km"}


def stems(text: str, exclude: set[str] = frozenset()) -> set[str]:
    return {w[:-1] if w.endswith("s") and len(w) > 3 else w for w in tokens(text) if w not in exclude}


class ThemeVerdict(BaseModel):
    id: str
    name: str | None = None
    relevant: bool = True
    owner: str | None = None
    competing: list[str] = Field(default_factory=list)
    core: bool = False


class PageRole(BaseModel):
    id: str
    intent: str | None = None
    secondary: str | None = None


class ThemesAnswer(BaseModel):
    clusters: list[ThemeVerdict] = Field(default_factory=list)
    pages: list[PageRole] = Field(default_factory=list)


@dataclass
class Signal:
    text: str
    source: str  # query:<intent> | question:<source> | paa | related


@dataclass
class Theme:
    id: str
    signals: list[Signal]
    brand: bool = False
    topic: frozenset[str] = frozenset()  # what the theme is about ("private", "pool"); empty for place themes
    name: str | None = None
    owner: PageView | None = None
    competing: list[PageView] = field(default_factory=list)
    core: bool = False
    relevant: bool = True  # False: about another business, or outside what this business offers
    candidates: list[PageView] = field(default_factory=list)  # pages targeting the theme in title/H1/URL
    sections: dict[str, str] = field(default_factory=dict)  # page URL → heading of a section covering it
    ranking: set[str] = field(default_factory=set)  # client URLs ranking for the theme's queries

    def head(self, exclude: set[str]) -> set[str]:
        counts = Counter(s for sig in self.signals for s in stems(sig.text, exclude))
        need = max(1, len(self.signals) / 2)
        head = {s for s, n in counts.items() if n >= need}
        return head or {s for s, _ in counts.most_common(2)}

    @property
    def observed(self) -> int:
        return sum(1 for s in self.signals if s.source.startswith(OBSERVED))

    def examples(self, n: int = 3) -> str:
        return "; ".join(list(dict.fromkeys(s.text for s in self.signals))[:n])


def demand(ctx: AgentContext) -> tuple[list[Signal], dict[str, set[str]]]:
    """Demand signals, and the client URLs ranking for each captured query."""
    signals: list[Signal] = []
    sets = ctx.snapshot.evidence(EvidenceType.QUERY_SET)
    for q in (sets[-1].payload.get("queries", []) if sets else []):
        signals.append(Signal(q["q"], f"query:{q['intent']}"))
    library = ctx.snapshot.evidence(EvidenceType.QUESTIONS)
    for q in (library[-1].payload.get("questions", []) if library else []):
        if q.get("relevant", True) and not q.get("duplicate_of"):
            signals.append(Signal(q.get("question") or q["text"], f"question:{q['source']}"))
    client = (urlsplit(ctx.client.primary_url).hostname or "").removeprefix("www.")
    latest = {}
    for ev in ctx.snapshot.evidence(EvidenceType.SERP):
        latest[ev.payload["query"]] = ev
    ranking: dict[str, set[str]] = {}
    for query, ev in latest.items():
        ranking[query] = {norm(r["link"]) for r in (ev.payload.get("organic") or []) if r.get("domain") == client}
        for q in ((ev.payload.get("features") or {}).get("paa") or []):
            if q.get("question"):
                signals.append(Signal(q["question"], "paa"))
        raw = ctx.snapshot.blob_json(ev.blob_key) if ev.blob_key and ev.payload.get("features") else {}
        for rel in ((raw or {}).get("serpapi") or {}).get("related_searches", []) or []:
            if rel.get("query"):
                signals.append(Signal(rel["query"], "related"))
    unique: dict[str, Signal] = {}
    for sig in signals:
        unique.setdefault(normalize(sig.text), sig)
    return list(unique.values()), ranking


def theme_words(text: str, brand: set[str], places: set[str]) -> tuple[str, frozenset[str]]:
    """What a search is about: its topic words ("pet friendly"), or, when it names only a place
    ("hotels near taj mahal"), its place words. Shared place words must not merge different topics."""
    words = stems(text) - brand
    topic = words - places - _GENERIC
    return ("topic", frozenset(topic)) if topic else ("place", frozenset(words & places))


def cluster(signals: list[Signal], brand: set[str], places: set[str] = frozenset()) -> list[Theme]:
    """Greedy clustering: a signal joins the theme holding its closest member of the same kind
    (topic or place) when they share at least half their words."""
    themes: list[Theme] = []
    keys: list[list[tuple[str, frozenset[str]]]] = []
    brand_theme = Theme("brand", [], brand=True)
    for sig in signals:
        if brand and stems(sig.text) & brand:
            brand_theme.signals.append(sig)
            continue
        kind, words = theme_words(sig.text, brand, places)
        if not words:
            continue  # nothing but generic words ("hotels near me")
        best, score = None, 0.0
        for i, members in enumerate(keys):
            for member_kind, other in members:
                jaccard = len(words & other) / len(words | other) if member_kind == kind else 0
                if jaccard > score:
                    best, score = i, jaccard
        if best is not None and score >= JOIN:
            themes[best].signals.append(sig)
            keys[best].append((kind, words))
        else:
            themes.append(Theme("", [sig], topic=words if kind == "topic" else frozenset()))
            keys.append([(kind, words)])
    themes.sort(key=lambda t: -len(t.signals))
    out = ([brand_theme] if brand_theme.signals else []) + themes
    for i, theme in enumerate(out[:MAX_CLUSTERS], start=1):
        theme.id = f"C{i}"
    return out[:MAX_CLUSTERS]


def section_covering(page: PageView, words: set[str]) -> str | None:
    """The heading of the page's first section whose heading and text hold every one of the words."""
    for sec in sections(page.model):
        text = sec["heading"] + " " + " ".join(b["text"] for b in sec["passages"])
        if words and words <= stems(text) and sec["heading"].strip():
            return sec["heading"][:60]
    return None


def covers(page: PageView, topic: frozenset[str]) -> bool:
    """The page uses at least half of a topic theme's words (an owner that never mentions the topic
    isn't one). Place-only themes have no topic words and always pass."""
    if not topic:
        return True
    return len(topic & stems(f"{page.model.get('title') or ''} {page.visible_text()}")) / len(topic) >= HEAD_SHARE


def page_words(page: PageView) -> set[str]:
    h1 = " ".join(h["text"] for h in page.model.get("headings", []) if h["level"] == 1)
    slug = urlsplit(page.url).path.replace("-", " ").replace("/", " ")
    return stems(f"{page.model.get('title') or ''} {h1} {slug}")


class KeywordThemes(Agent):
    id = "S5"
    name = "Keyword Themes & Cannibalization"
    pillar = Pillar.SEO
    requires = frozenset({EvidenceType.PAGES_PARSED, EvidenceType.QUERY_SET, EvidenceType.QUESTIONS,
                          EvidenceType.SERP, EvidenceType.FACTS})
    signature_columns = ["Theme", "Example searches", "Demand signals", "Owner page", "Conflict or gap"]
    checks = [
        CheckSpec(id="S5.01", title="Every observed theme has one owner page", default_severity=Sev.MEDIUM,
                  method="S+L"),
        CheckSpec(id="S5.02", title="Cannibalization", default_severity=Sev.HIGH, method="D+S+L"),
        CheckSpec(id="S5.03", title="Page role clarity", default_severity=Sev.MEDIUM, method="L"),
        CheckSpec(id="S5.04", title="Local modifiers", default_severity=Sev.MEDIUM, method="S"),
        CheckSpec(id="S5.05", title="Recurring unaddressed themes", default_severity=Sev.MEDIUM, method="S"),
    ]

    def run_unit(self, ctx: AgentContext, unit: WorkUnit) -> AgentResult:
        pages = [p for p in load_pages(ctx) if p.is_html][:MAX_PAGES]
        brand, places = brand_tokens(ctx), place_words(ctx)
        signals, ranking = demand(ctx)
        entry = entry_page(pages, ctx.client.primary_url)
        themes = cluster(signals, brand, places)
        exclude = brand | _GENERIC
        for theme in themes:
            head = theme.head(exclude)
            theme.candidates = [p for p in pages if head and len(head & page_words(p)) / len(head) >= HEAD_SHARE]
            by_relevance = sorted(pages, key=lambda p: p is not entry)  # the client's own page first
            theme.sections = {p.url: hit for p in by_relevance if p not in theme.candidates
                              and (hit := section_covering(p, set(theme.topic) or head))}
            theme.ranking = {u for s in theme.signals if s.source.startswith("query:")
                             for u in ranking.get(s.text, ())}
        coverage = Coverage(examined={"demand_signals": len(signals), "themes": len(themes), "pages": len(pages)})
        coverage.limits.append("Demand signals (queries, questions, related searches), not search volumes.")
        if not signals:
            coverage.skipped.append("No query set, questions or SERP captures in this snapshot.")
            return AgentResult(findings=[self.finding(c.id, St.UNVERIFIABLE, "No demand signals")
                                         for c in self.checks], coverage=coverage)

        roles = self._judge(ctx, themes, pages, coverage)
        keys = key_page_urls(pages, ctx.client.primary_url) | ({entry.url} if entry else set())
        findings = [self._owners(themes), self._cannibalization(themes),
                    self._roles([p for p in pages if p.url in keys and not p.is_home], roles),  # home: a hub
                    self._local(themes, places), self._recurring(themes, pages, exclude)]
        rows = [[t.name or ("brand" if t.brand else "(not named)"), t.examples(), f"{len(t.signals)} "
                 f"({t.observed} observed)", t.owner.url if t.owner else "—",
                 ("competes with " + ", ".join(p.url for p in t.competing)) if t.competing
                 else ("no page" if t.name and not t.owner else "—")] for t in themes]
        return AgentResult(findings=findings, coverage=coverage,
                           signature_table={"columns": self.signature_columns, "rows": rows})

    # ------------------------------------------------------------ LLM

    def _judge(self, ctx, themes: list[Theme], pages: list[PageView], coverage: Coverage) -> dict[str, PageRole]:
        if ctx.llm is None:
            coverage.skipped.append("Theme names, owners and page roles need the LLM (off in this run).")
            return {}
        template = template_headings([p.model for p in pages])
        ids = {page.url: f"P{i}" for i, page in enumerate(pages, start=1)}
        by_id = {ids[p.url]: p for p in pages}
        page_lines = []
        for page in pages:
            h1 = next((h["text"] for h in page.model.get("headings", []) if h["level"] == 1 and h["text"]), "")
            heads = [b["text"][:40] for b in page.model.get("outline", [])
                     if b["type"] == "heading" and b["level"] >= 2 and normalize(b["text"]) not in template][:4]
            page_lines.append(f"{ids[page.url]} ({page.url}) {page.model.get('title') or ''} | H1: {h1} | "
                              + "; ".join(heads))
        cluster_lines = [f"{t.id} ({len(t.signals)} signals): {t.examples(5)} | candidates: "
                         + (", ".join([ids[p.url] for p in t.candidates]
                                      + [f"{ids[u]} (section: {h})" for u, h in list(t.sections.items())[:3]])
                            or "none") for t in themes]
        try:
            answer = ctx.llm.complete_json(
                load_prompt("s5.themes", 3), ThemesAnswer,
                business=f"{business_name(ctx)} ({archetype(ctx) or 'archetype unknown'})",
                clusters="\n".join(cluster_lines), pages="\n".join(page_lines)).data
        except LLMError as exc:
            coverage.skipped.append(f"Theme mapping failed: {exc}")
            return {}
        verdicts = {v.id: v for v in answer.clusters}
        rejected: list[str] = []
        for theme in themes:
            v = verdicts.get(theme.id)
            if v is None or not v.name:
                continue
            theme.name, theme.core, theme.relevant = v.name.strip()[:60], v.core, v.relevant
            owner = by_id.get(v.owner) if v.owner else None
            if owner is not None and not covers(owner, theme.topic):
                rejected.append(f"{theme.name} → {owner.url}")
                owner = None
            theme.owner = owner
            theme.competing = [by_id[i] for i in dict.fromkeys(v.competing)
                               if i in by_id and by_id[i] is not theme.owner]
        if rejected:
            coverage.limits.append(f"{len(rejected)} owner page(s) proposed by the model don't mention the theme and "
                                   "were not accepted: " + "; ".join(rejected[:5]))
        return {by_id[r.id].url: r for r in answer.pages if r.id in by_id}

    # ------------------------------------------------------------ checks

    def _owners(self, themes: list[Theme]):
        named = [t for t in themes if t.name and t.relevant]
        if not named:
            return self.finding("S5.01", St.UNVERIFIABLE, "Themes not mapped to pages")
        orphans = [t for t in named if t.owner is None]
        core = [t for t in orphans if t.core]
        if not orphans:
            return self.finding("S5.01", St.PASS, f"All {len(named)} search themes have an owner page",
                                confidence=Confidence.LIKELY,
                                evidence=[EvidenceRef(type="serp", url=t.owner.url, excerpt=f"{t.name}: {t.owner.url}")
                                          for t in named[:4]])
        return self.finding(
            "S5.01", St.FAIL if core else St.WARN,
            tally((len(core), "core theme(s)"), (len(orphans) - len(core), "other theme(s)")) + " without a page: "
            + ", ".join(t.name for t in orphans[:6]), confidence=Confidence.LIKELY,
            evidence=[EvidenceRef(type="serp", excerpt=f"{t.name} ({len(t.signals)} signal(s)): {t.examples()}")
                      for t in (core + [t for t in orphans if not t.core])[:5]],
            impact="Searches with no page that owns them go to competitors and aggregators.",
            fix="Give each core theme a page or a clear section; check the site inventory first (the page may exist "
                "outside the sample).", verification="Re-run S5: every core theme has an owner.", effort=Effort.M)

    def _cannibalization(self, themes: list[Theme]):
        named = [t for t in themes if t.name]
        if not named:
            return self.finding("S5.02", St.UNVERIFIABLE, "Themes not mapped to pages")
        confirmed, possible = [], []
        for theme in named:
            if theme.owner is None:
                continue
            for page in theme.competing:
                both_rank = {norm(theme.owner.url), norm(page.url)} <= theme.ranking
                both_match = theme.owner in theme.candidates and page in theme.candidates
                reason = ("both rank for the same search" if both_rank
                          else "both target its head words in title/H1/URL" if both_match else None)
                (confirmed if reason else possible).append((theme, page, reason or "similar main topic"))
        evidence = [EvidenceRef(type="html_excerpt", url=p.url,
                                excerpt=f"\"{t.name}\": {t.owner.url} and {p.url} ({why})")
                    for t, p, why in (confirmed + possible)[:5]]
        if confirmed:
            return self.finding(
                "S5.02", St.FAIL, f"{len(confirmed)} theme(s) targeted by two pages with the same purpose",
                pages=sorted({u for t, p, _ in confirmed for u in (t.owner.url, p.url)}), confidence=Confidence.LIKELY,
                evidence=evidence,
                impact="Pages competing for one search split its signals; often neither ranks well.",
                fix="Keep one page per theme: merge or redirect the weaker one, or refocus it on a different theme, "
                    "and link the pages to each other.", verification="Re-run S5.", effort=Effort.M)
        if possible:
            return self.finding(
                "S5.02", St.WARN, f"{len(possible)} theme(s) where two pages partly overlap",
                pages=sorted({u for t, p, _ in possible for u in (t.owner.url, p.url)}),
                confidence=Confidence.HYPOTHESIS,
                evidence=evidence, impact="Overlapping pages can compete for the same searches.",
                fix="Make each page's main topic distinct in its title, H1 and opening.", verification="Re-run S5.",
                effort=Effort.S)
        return self.finding("S5.02", St.PASS, "No two pages compete for the same theme", confidence=Confidence.LIKELY,
                            evidence=[EvidenceRef(type="serp", excerpt=f"{len(named)} themes checked")])

    def _roles(self, key_pages: list[PageView], roles: dict[str, PageRole]):
        judged = [(p, roles[p.url]) for p in key_pages if p.url in roles and roles[p.url].intent]
        if not judged:
            return self.finding("S5.03", St.UNVERIFIABLE, "Page roles not judged")
        mixed = [(p, r) for p, r in judged if r.intent == "mixed"]
        diluted = [(p, r) for p, r in judged if r.intent != "mixed" and r.secondary]
        if not mixed and not diluted:
            return self.finding("S5.03", St.PASS, "Key pages each have one clear purpose", confidence=Confidence.LIKELY,
                                evidence=[EvidenceRef(type="html_excerpt", url=p.url, excerpt=f"intent: {r.intent}")
                                          for p, r in judged[:4]])
        bad = mixed + diluted
        return self.finding(
            "S5.03", St.FAIL if mixed else St.WARN,
            tally((len(mixed), "key page(s) mix informing and selling"),
                  (len(diluted), "key page(s) diluted by a secondary purpose")),
            pages=[p.url for p, _ in bad], confidence=Confidence.LIKELY,
            evidence=[EvidenceRef(type="html_excerpt", url=p.url,
                                  excerpt=f"intent: {r.intent}"
                                  + (f"; secondary: {r.secondary}" if r.secondary else ""))
                      for p, r in bad[:5]],
            impact="A page that tries to do two jobs ranks for neither as well as a focused page.",
            fix="Give each page one job; move the secondary content to its own page and link to it.",
            verification="Re-run S5.", effort=Effort.M)

    def _local(self, themes: list[Theme], places: set[str]):
        local = [t for t in themes if t.name and t.relevant and not t.brand and (
            any(s.source == "query:local" for s in t.signals)
            or any(stems(s.text) & places for s in t.signals))]
        if not local:
            return self.finding("S5.04", St.NOT_APPLICABLE, "No local search themes in the demand signals")
        missing = [t for t in local if t.owner is None]
        evidence = [EvidenceRef(type="serp", url=t.owner.url if t.owner else None,
                                excerpt=f"{t.name}: {t.owner.url if t.owner else 'no page'}") for t in local[:5]]
        if not missing:
            return self.finding("S5.04", St.PASS, f"All {len(local)} local theme(s) have a page",
                                confidence=Confidence.LIKELY, evidence=evidence)
        return self.finding(
            "S5.04", St.FAIL if len(missing) == len(local) else St.WARN,
            f"{len(missing)} of {len(local)} local theme(s) have no page: " + ", ".join(t.name for t in missing[:5]),
            confidence=Confidence.LIKELY, evidence=evidence,
            impact="Local searches (a city, an area, a landmark) go to pages that name the place.",
            fix="Cover each place customers search with a page or section that names it.",
            verification="Re-run S5.", effort=Effort.M)

    def _recurring(self, themes: list[Theme], pages: list[PageView], exclude: set[str]):
        observed = [t for t in themes if t.observed >= 2 and not t.brand and t.relevant]
        if not observed:
            return self.finding("S5.05", St.NOT_APPLICABLE, "No theme seen twice or more in search data")
        site = set().union(*(stems(p.visible_text()) for p in pages)) if pages else set()
        absent = [t for t in observed if t.owner is None and not t.head(exclude) <= site]
        if not absent:
            return self.finding("S5.05", St.PASS, "Themes that recur in search data appear on the site",
                                confidence=Confidence.LIKELY,
                                evidence=[EvidenceRef(type="serp", excerpt=f"{t.name or t.examples(1)}: "
                                                                           f"{t.observed} observed signal(s)")
                                          for t in observed[:4]])
        return self.finding(
            "S5.05", St.WARN, f"{len(absent)} theme(s) recur in search data but appear nowhere on the site",
            confidence=Confidence.LIKELY,
            evidence=[EvidenceRef(type="serp", excerpt=f"{t.name or t.examples(1)} ({t.observed} observed): "
                                                       f"{t.examples()}") for t in absent[:5]],
            impact="Customers keep searching for these; the site gives search engines and AI assistants nothing "
                   "to match.", fix="Decide which themes fit the business and cover them.",
            verification="Re-run S5.", effort=Effort.M)
