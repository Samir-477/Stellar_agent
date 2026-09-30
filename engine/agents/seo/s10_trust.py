"""S10 E-E-A-T & Trust: does the site show who is behind it, and does it meet the trust and
disclosure expectations of its archetype (docs/spec/07 packs, `trust_items`)?

Deterministic: finding the about/contact pages, contact details (S10.02), bylines (S10.03),
dates (S10.04), privacy/terms links (part of S10.05). LLM (one batched call, fast tier): judges
the about page and each pack trust item from passages retrieved on the sampled pages, quoting
the passage (quotes verified). An item the site doesn't state in text but does declare in
JSON-LD (C4 schema-declared facts) is "partial": machines can read it, visitors can't.

Every judgement is limited to the sampled pages and their server HTML: policies shown only
inside booking or checkout flows (JavaScript) aren't seen, and findings say so.
"""

from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass
from math import ceil
from urllib.parse import urlsplit

from pydantic import BaseModel, Field

from engine.agents.base import Agent
from engine.agents.common import PageView, archetype, business_name, entry_page, fact_sheet, load_pages, norm
from engine.context import AgentContext, WorkUnit
from engine.lib.content import MASK, mask_placeholders, sections
from engine.lib.grounding import quote_in_text
from engine.lib.jsonld import page_nodes, page_types, types_of
from engine.lib.locators import text_hash
from engine.lib.retrieval import BM25
from engine.llm import LLMError, load_prompt
from engine.rules.packs import TrustItem, pack
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

CHUNK_WORDS = 120
PASSAGES_PER_ITEM = 3
COMPLIANCE_NOTE = "Flag for your compliance team; this is not legal advice."

ABOUT_PATH = re.compile(r"/(about|about-us|aboutus|our-story|who-we-are|company|corporate-information)(/|$)", re.I)
ABOUT_TEXT = re.compile(r"^about(\s+us)?$", re.I)
CONTACT_PATH = re.compile(r"/(contact|contact-us|contactus|reach-us|get-in-touch)(/|$)", re.I)
CONTACT_TEXT = re.compile(r"^contact(\s+us)?$", re.I)
PRIVACY = re.compile(r"privacy", re.I)
PRIVACY_EXACT = re.compile(r"^privacy(\s+(policy|notice|statement))?$", re.I)
TERMS = re.compile(r"terms|conditions|\bt\s?&\s?c\b|\btnc\b", re.I)
TERMS_EXACT = re.compile(r"^(terms|terms\s*(and|&)\s*conditions|terms\s+of\s+(use|service)|t\s?&\s?cs?)$", re.I)
ABOUT_QUERY = "founded established since history owned subsidiary group limited company registered leadership team"
KIND_HINTS = {"reviews": "review reviews rated rating testimonial testimonials guests stars",
              "pricing": "price prices tariff rates charges fees taxes gst inclusive"}

ARTICLE_TYPES = {"Article", "BlogPosting", "NewsArticle", "Report", "TechArticle", "ScholarlyArticle"}
ARTICLE_PATH = re.compile(r"/(blog|news|articles?|guides?|insights|resources|learn|knowledge-cent(?:re|er))/[^/]+",
                          re.I)
BYLINE = re.compile(r"\b(?:[Bb]y|[Ww]ritten by|[Aa]uthor|[Pp]osted by|[Rr]eviewed by)\s*:?\s+"
                    r"([A-Z][a-z]+(?:\s+[A-Z][a-z.]+){1,3})")
REVIEWER = re.compile(r"\b(?:reviewed|fact[- ]checked|verified) by\b", re.I)
_MONTH = r"(?:jan|feb|mar|apr|may|jun|jul|aug|sep|sept|oct|nov|dec)[a-z]*\.?"
DATE = re.compile(rf"\b\d{{1,2}}(?:st|nd|rd|th)?\s+{_MONTH},?\s+\d{{4}}\b|\b{_MONTH}\s+\d{{1,2}}(?:st|nd|rd|th)?,?\s+"
                  r"\d{4}\b|\b\d{4}-\d{2}-\d{2}\b|\b\d{1,2}[/.-]\d{1,2}[/.-]\d{4}\b", re.I)
DATE_META = ("article:published_time", "article:modified_time", "og:updated_time", "date", "dc.date")
RATE_PAGE = re.compile(r"\d+(?:\.\d+)?\s*%\s*(?:p\.?\s?a\.?|per annum)|\binterest rates?\b", re.I)

PHONE = re.compile(r"(?:\+91[\s-]?)?\b[6-9]\d{4}[\s-]?\d{5}\b|\b1800[\s-]?\d{3}[\s-]?\d{3,4}\b"
                   r"|\b0\d{2,4}[\s-]\d{6,8}\b")
EMAIL = re.compile(r"\b[\w.+-]+@[\w-]+(?:\.[\w-]+)+\b")
PIN = re.compile(r"\b[1-9]\d{2}\s?\d{3}\b")
ADDRESS_WORDS = re.compile(r"\b(road|rd|street|nagar|marg|lane|floor|building|bldg|sector|block|plot|colony|salai|"
                           r"district|near|opp)\b", re.I)
HOURS = re.compile(r"\b\d{1,2}(?:[:.]\d{2})?\s*(?:am|pm)\b|\b24\s*[x×/]\s*7\b|round the clock|working hours|"
                   r"business hours|office hours", re.I)
JS_PLACEHOLDER = re.compile(r"\{\{[^}]*(?:address|pincode|pin_code|street)[^}]*\}\}", re.I)


class Verdict(BaseModel):
    key: str
    status: str
    passage: str | None = None
    quote: str | None = None
    note: str | None = None


class Verdicts(BaseModel):
    items: list[Verdict] = Field(default_factory=list)


@dataclass
class Passage:
    url: str
    text: str
    heading: str = ""
    site_wide: bool = False
    is_entry: bool = False
    footer: bool = False

    def label(self) -> str:
        """How the passage is introduced to the model: where it is and whether values are missing."""
        tags = [tag for tag, on in (("site-wide", self.site_wide), ("footer", self.footer),
                                    ("has values filled in by JavaScript", MASK in self.text)) if on]
        return self.url + (f", {', '.join(tags)}" if tags else "")


@dataclass
class Judged:
    key: str
    label: str
    kind: str  # about | policy | disclosure | reviews | pricing
    core: bool
    status: str  # present | partial | absent | unverified
    url: str | None = None
    quote: str | None = None
    note: str | None = None
    source: str = "page"  # page | links | jsonld
    site_wide: bool = False  # the quoted text repeats across the site (shared widget, footer)

    def evidence(self) -> EvidenceRef:
        detail = f'"{self.quote}"' if self.quote else (self.note or "not found on the sampled pages")
        if self.quote and self.note:
            detail += f" ({self.note})"
        where = " (site-wide text)" if self.site_wide else ""
        return EvidenceRef(type="html_excerpt", url=self.url,
                           excerpt=f"{self.label}: {self.status}{where}: {detail}"[:400])


def _windows(heading: str, words: list[str]) -> list[str]:
    return [f"{heading}: {' '.join(words[i:i + CHUNK_WORDS])}" if words else heading
            for i in range(0, max(len(words), 1), CHUNK_WORDS)]


def chunk_passages(pages: list[PageView], entry: PageView | None) -> list[Passage]:
    """Sections (heading + text) and footer text of every sampled page, split into ~120-word chunks.
    Client-side placeholders are masked as "[…]" (the value isn't in the HTML). Text repeated on many
    pages (a booking widget, a shared FAQ, the footer) is kept once and marked site-wide."""
    raw: list[tuple[PageView, str, str, bool]] = []
    for page in pages:
        for sec in sections(page.model, masked=True):
            words = " ".join(b["text"] for b in sec["passages"]).split()
            if words or len(sec["heading"].replace(MASK, "").split()) >= 2:
                raw += [(page, sec["heading"], text, False) for text in _windows(sec["heading"], words)]
        footer = mask_placeholders(page.model.get("footer_text") or "").split()
        if footer:  # policies, registration numbers and company details usually live here
            raw += [(page, "Footer", text, True) for text in _windows("Footer", footer)]
    counts = Counter(text_hash(text) for _, _, text, _ in raw)
    threshold = max(3, ceil(0.25 * len(pages)))
    out, seen = [], set()
    for page, heading, text, in_footer in raw:
        digest = text_hash(text)
        if digest in seen:
            continue
        seen.add(digest)
        out.append(Passage(page.url, text, heading, counts[digest] >= threshold, page is entry, in_footer))
    return out


def self_link(page: PageView, href: str) -> bool:
    """`href="#"` resolves to the page itself: a JavaScript modal or toggle, not a page."""
    return norm(href) in (norm(page.url), norm(page.record.url))


def find_page(pages: list[PageView], path: re.Pattern, text: re.Pattern) -> tuple[PageView | None, str | None]:
    """(sampled page, linked URL): the sampled page whose path matches, else a link to one."""
    sampled = next((p for p in pages if path.search(urlsplit(p.url).path)), None)
    if sampled:
        return sampled, sampled.url
    for page in pages:
        for link in page.model.get("links", []):
            if not link.get("internal") or "{{" in link["text"] or self_link(page, link["href"]):
                continue
            if path.search(urlsplit(link["href"]).path) or text.match(link["text"].strip()):
                return None, link["href"]
    return None, None


def policy_link(pages: list[PageView], pattern: re.Pattern, exact: re.Pattern) -> tuple[str | None, str | None]:
    """(url, where) of a privacy/terms page: sampled, else linked (it may live on another domain).
    A link named exactly like the general policy ("Terms & Conditions") beats narrower ones
    ("Offers T&C")."""
    for page in pages:
        if pattern.search(urlsplit(page.url).path):
            return page.url, "sampled page"
    links = [(page, link) for page in pages for link in page.model.get("links", [])
             if "{{" not in link["text"] and not self_link(page, link["href"])]
    for test in (lambda link: exact.match(link["text"].strip()),
                 lambda link: pattern.search(urlsplit(link["href"]).path) or pattern.search(link["text"])):
        for page, link in links:
            if test(link):
                return link["href"], f"linked from {page.url} (\"{link['text'][:60]}\")"
    return None, None


class EEATTrust(Agent):
    id = "S10"
    name = "E-E-A-T & Trust"
    pillar = Pillar.SEO
    requires = frozenset({EvidenceType.PAGES_RAW, EvidenceType.PAGES_PARSED, EvidenceType.FACTS,
                          EvidenceType.ARCHETYPE})
    signature_columns = ["Trust item", "Status", "Where", "Evidence or note"]
    checks = [
        CheckSpec(id="S10.01", title="About page", default_severity=Sev.MEDIUM, method="D+L"),
        CheckSpec(id="S10.02", title="Contact page", default_severity=Sev.HIGH, method="D"),
        CheckSpec(id="S10.03", title="Authorship", default_severity=Sev.MEDIUM, method="D"),
        CheckSpec(id="S10.04", title="Dates", default_severity=Sev.MEDIUM, method="D"),
        CheckSpec(id="S10.05", title="Policies", default_severity=Sev.HIGH, method="D+L"),
        CheckSpec(id="S10.06", title="Archetype disclosures (compliance review)", default_severity=Sev.HIGH,
                  method="D+L"),
        CheckSpec(id="S10.07", title="Reviews and testimonials", default_severity=Sev.LOW, method="L"),
        CheckSpec(id="S10.08", title="Pricing and fee transparency", default_severity=Sev.MEDIUM, method="D+L"),
    ]

    def run_unit(self, ctx: AgentContext, unit: WorkUnit) -> AgentResult:
        pages = [p for p in load_pages(ctx) if p.is_html]
        arch = archetype(ctx)
        the_pack = pack(arch)
        ymyl = the_pack.ymyl if the_pack else "standard"
        facts = fact_sheet(ctx)
        entry = entry_page(pages, ctx.client.primary_url)
        about_page, about_url = find_page(pages, ABOUT_PATH, ABOUT_TEXT)
        contact_page, contact_url = find_page(pages, CONTACT_PATH, CONTACT_TEXT)
        coverage = Coverage(examined={"pages": len(pages)})
        coverage.limits.append(f"Judged on the {len(pages)} sampled pages and their server HTML; policies on other "
                               "pages or shown only inside booking/checkout flows (JavaScript) aren't seen.")

        judged = self._judge(ctx, pages, entry, about_page, the_pack, facts, coverage)
        privacy_url, privacy_where = policy_link(pages, PRIVACY, PRIVACY_EXACT)
        terms_url, terms_where = policy_link(pages, TERMS, TERMS_EXACT)
        basics = [Judged("privacy", "privacy policy", "policy", True, "present" if privacy_url else "absent",
                         url=privacy_url, note=privacy_where, source="links"),
                  Judged("terms", "terms and conditions", "policy", False, "present" if terms_url else "absent",
                         url=terms_url, note=terms_where, source="links")]
        by_kind = {kind: [j for j in judged if j.kind == kind] for kind in ("policy", "disclosure", "reviews",
                                                                              "pricing")}
        loans = ymyl == "high"
        findings = [
            self._about(judged, about_page, about_url, coverage),
            self._contact(ctx, contact_page, contact_url, facts, loans),
            *self._articles(pages, loans, coverage),
            self._rollup("S10.05", basics + by_kind["policy"], fail_on="core",
                         ok="Privacy, terms and the expected policies are stated",
                         bad="policies missing or incomplete",
                         impact="Customers and search engines look for clear policies before trusting a business; "
                                "missing ones cost customers and trust signals.",
                         fix="Publish each policy in plain text on its own page (or a clear section) and link it "
                             "from the footer and the checkout, booking or application steps."),
            self._rollup("S10.06", by_kind["disclosure"], fail_on="core",
                         severity=Sev.CRITICAL if loans else None, tags=["compliance-review"],
                         ok="The disclosures expected for this archetype are present",
                         bad="expected disclosures missing or incomplete",
                         impact="Regulators and customers expect these disclosures; AI assistants and search engines "
                                "treat their absence as a trust risk.",
                         fix=f"{COMPLIANCE_NOTE} Add each missing disclosure where customers make decisions."),
            self._rollup("S10.07", by_kind["reviews"], fail_on="never",
                         ok="Reviews are attributed and dated", bad="reviews not attributed or dated",
                         impact="Named, dated reviews are trust evidence for people and AI assistants; anonymous "
                                "praise isn't.",
                         fix="Show reviews with the reviewer's name (or source) and date; link to the review "
                             "platform."),
            self._rollup("S10.08", by_kind["pricing"], fail_on="any", severity=Sev.HIGH if loans else None,
                         ok="Prices, fees and charges are stated", bad="price or fee details missing or incomplete",
                         impact="Hidden fees or prices that appear only at checkout erode trust and invite "
                                "complaints; AI assistants can't quote prices they can't read.",
                         fix="State prices with taxes and fees (or a clear 'from' price and what it includes) in "
                             "the page text."),
        ]
        rows = [[j.label, j.status, (j.url or "—") + (" (site-wide)" if j.site_wide else ""),
                 (j.quote or j.note or "")[:120]] for j in basics + judged]
        return AgentResult(findings=findings, coverage=coverage,
                           signature_table={"columns": self.signature_columns, "rows": rows})

    # ------------------------------------------------------------ LLM judgement (S10.01, .05–.08)

    def _judge(self, ctx, pages, entry, about_page, the_pack, facts, coverage) -> list[Judged]:
        items: list[tuple[TrustItem, list[Passage]]] = []
        chunks = chunk_passages(pages, entry)
        # Heading words say what a section is about: weight them 3x for ranking.
        index = BM25([f"{c.heading} {c.heading} {c.text}" for c in chunks]) if chunks else None
        if about_page is not None:
            own = [c for c in chunks if c.url == about_page.url and not c.site_wide]
            ranked = [own[i] for i, _ in BM25([c.text for c in own]).top(ABOUT_QUERY, 4)] if own else []
            items.append((TrustItem("about", "real organization details (history or founding, owners or leaders, "
                                             "legal entity or registration, scale)", "about"), ranked or own[:4]))
        for item in the_pack.trust_items if the_pack else ():
            picked: list[Passage] = []
            if index is not None:
                ranked = [chunks[i] for i, _ in index.top(f"{item.label} {KIND_HINTS.get(item.kind, '')}",
                                                          len(chunks))]
                picked = ranked[:PASSAGES_PER_ITEM]
                entry_best = next((c for c in ranked if c.is_entry), None)
                if entry_best is not None and entry_best not in picked:
                    picked.append(entry_best)  # the client's own page always gets a say
            for fact in facts:  # C4 facts quote page text verbatim: extra recall for the same item
                if fact["key"] in item.facts and fact["status"] == "site-stated" \
                        and not any(quote_in_text(fact["quote"], p.text) for p in picked):
                    picked.append(Passage(fact["source_url"], fact["quote"]))
            items.append((item, picked))
        if the_pack is None:
            coverage.skipped.append("No archetype pack: only about, contact, authorship, dates, privacy and terms "
                                    "are checked.")

        verdicts: dict[str, Verdict] = {}
        to_ask = [(item, passages) for item, passages in items if passages]
        coverage.examined["trust_items"] = len(items)
        if to_ask and ctx.llm is None:
            coverage.skipped.append("Trust items need the LLM to judge them (off in this run).")
        elif to_ask:
            lines = []
            for item, passages in to_ask:
                lines.append(f"ITEM {item.key}: {item.label}")
                lines += [f"{item.key}.P{n} ({p.label()}): {p.text}" for n, p in enumerate(passages, start=1)]
            business = f"{business_name(ctx)} ({the_pack.id if the_pack else 'archetype unknown'})"
            try:
                answer = ctx.llm.complete_json(load_prompt("s10.trust", 2), Verdicts, business=business,
                                               items="\n".join(lines)).data
                verdicts = {v.key: v for v in answer.items}
            except LLMError as exc:
                coverage.skipped.append(f"Trust item review failed: {exc}")

        judged, rejected = [], 0
        for item, passages in items:
            j = Judged(item.key, item.label, item.kind, item.core, "absent" if not passages else "unverified",
                       note="nothing on the sampled pages mentions it" if not passages else None)
            v = verdicts.get(item.key)
            if v is not None and v.status == "absent":
                j.status, j.note = "absent", v.note
            elif v is not None and v.status in ("present", "partial"):
                n = v.passage.rsplit(".P", 1)[-1] if v.passage and v.passage.startswith(f"{item.key}.P") else ""
                passage = passages[int(n) - 1] if n.isdigit() and 0 < int(n) <= len(passages) else None
                if passage and v.quote and quote_in_text(v.quote, passage.text):
                    j.status, j.url, j.quote, j.note = v.status, passage.url, v.quote.strip(), v.note
                    j.site_wide = passage.site_wide
                else:
                    rejected += 1  # the quote isn't on the page: don't trust the verdict
            if j.status in ("absent", "unverified"):
                declared = [f for f in facts if f["key"] in item.facts and f["status"] == "schema-declared"]
                if declared:
                    j.status, j.url, j.source = "partial", declared[0]["source_url"], "jsonld"
                    j.quote = "; ".join(f"{f['key']}: {f['value']}" for f in declared[:2])
                    j.note = "only in structured data (JSON-LD), not shown to visitors"
            judged.append(j)
        if rejected:
            coverage.limits.append(f"{rejected} verdict(s) dropped because the quoted text isn't on the page.")
        return judged

    # ------------------------------------------------------------ S10.01

    def _about(self, judged, about_page, about_url, coverage):
        if about_page is None and about_url:
            coverage.limits.append(f"The about page ({about_url}) wasn't in the sample.")
            return self.finding("S10.01", St.UNVERIFIABLE, "About page is linked but wasn't in the sample",
                                evidence=[EvidenceRef(type="html_excerpt", url=about_url,
                                                      excerpt="linked, not sampled")])
        if about_page is None:
            return self.finding(
                "S10.01", St.FAIL, "No about page found", confidence=Confidence.LIKELY,
                evidence=[EvidenceRef(type="html_excerpt", excerpt="no /about page or 'About us' link on the sampled "
                                                                   "pages")],
                impact="People, search engines and AI assistants look for who runs a business before trusting it.",
                fix="Add an about page with the legal entity, history, owners or leadership and scale; link it "
                    "from the footer.", verification="About page present and linked.", effort=Effort.S)
        j = next(x for x in judged if x.key == "about")
        if j.status == "unverified":
            return self.finding("S10.01", St.UNVERIFIABLE, "About page content not reviewed",
                                pages=[about_page.url])
        if j.status == "present":
            return self.finding("S10.01", St.PASS, "About page gives real organization details",
                                pages=[about_page.url], confidence=Confidence.LIKELY, evidence=[j.evidence()])
        return self.finding(
            "S10.01", St.WARN, "About page is generic: few checkable details about who runs the business",
            pages=[about_page.url], confidence=Confidence.LIKELY, evidence=[j.evidence()],
            impact="Vague about pages don't establish who is accountable for the business.",
            fix="Add the legal entity name, founding year, owners or leadership, registration and scale.",
            verification="About page states specific organization details.", effort=Effort.S)

    # ------------------------------------------------------------ S10.02

    def _contact(self, ctx, page, url, facts, loans):
        if page is None and url:
            return self.finding("S10.02", St.UNVERIFIABLE, "Contact page is linked but wasn't in the sample",
                                evidence=[EvidenceRef(type="html_excerpt", url=url, excerpt="linked, not sampled")])
        if page is None:
            return self.finding(
                "S10.02", St.FAIL, "No contact page found", confidence=Confidence.LIKELY,
                severity=Sev.CRITICAL if loans else None,
                evidence=[EvidenceRef(type="html_excerpt", excerpt="no /contact page or 'Contact us' link on the "
                                                                   "sampled pages")],
                impact="Customers can't reach the business, and search engines and AI assistants read that as a "
                       "trust risk.", fix="Add a contact page with address, phone, email and support hours.",
                verification="Contact page present with all four.", effort=Effort.S)
        text = page.visible_text()
        contacts = page.model.get("contacts", [])
        found: dict[str, str] = {}
        tel = next((c for c in contacts if c["type"] == "tel" and c["value"]), None)
        if tel:
            found["phone"] = f"{tel['value']} (tel: link)"
        elif PHONE.search(text):
            found["phone"] = PHONE.search(text).group(0)
        mail = next((c for c in contacts if c["type"] == "mailto" and c["value"]), None)
        if mail:
            found["email"] = mail["value"] + (" (Cloudflare-protected: tools that don't run JavaScript see "
                                              "'[email protected]')" if mail.get("obfuscated") else "")
        elif EMAIL.search(text):
            found["email"] = EMAIL.search(text).group(0)
        address = next((p["text"] for p in page.model.get("passages", [])
                        if PIN.search(p["text"]) and ADDRESS_WORDS.search(p["text"])), None) \
            or next((f["value"] for f in facts if f["key"] == "address" and f["status"] == "site-stated"
                     and norm(f["source_url"]) == norm(page.url)), None)
        if address:
            found["address"] = address[:120]
        if HOURS.search(text):
            found["hours"] = HOURS.search(text).group(0)
        missing = [k for k in ("address", "phone", "email", "hours") if k not in found]
        evidence = [EvidenceRef(type="html_excerpt", url=page.url, excerpt=f"{k}: {v}"[:300]) for k, v in found.items()]
        if not missing:
            return self.finding("S10.02", St.PASS, "Contact page lists address, phone, email and hours",
                                pages=[page.url], evidence=evidence)
        note = ""
        raw = ctx.snapshot.blob_text(page.record.raw_html_key) if page.record.raw_html_key else ""
        if "address" in missing and raw and JS_PLACEHOLDER.search(raw):
            note = " The address is filled in by JavaScript, so it isn't in the page HTML."
            evidence.insert(0, EvidenceRef(type="html_excerpt", url=page.url,  # why it's missing comes first
                                           excerpt=f"address is a template placeholder: "
                                                   f"{JS_PLACEHOLDER.search(raw).group(0)}"))
        return self.finding(
            "S10.02", St.WARN, f"Contact page is missing: {', '.join(missing)}", pages=[page.url],
            evidence=evidence or [EvidenceRef(type="html_excerpt", url=page.url, excerpt="no contact details found")],
            impact="Incomplete contact details make the business harder to reach and to verify." + note,
            fix=f"Add the {', '.join(missing)} to the contact page as plain text.",
            verification="Contact page lists address, phone, email and hours.", effort=Effort.S)

    # ------------------------------------------------------------ S10.03 / S10.04

    def _articles(self, pages, loans, coverage):
        articles = [p for p in pages if page_types(p.model) & ARTICLE_TYPES
                    or (p.model.get("meta") or {}).get("og:type") == "article"
                    or ARTICLE_PATH.search(urlsplit(p.url).path)]
        rate_pages = [p for p in pages if RATE_PAGE.search(p.visible_text())] if loans else []
        coverage.examined["articles"] = len(articles)
        if not articles:
            coverage.limits.append("No articles or guides in the sample, so authorship and dates weren't checked.")
            authorship = self.finding("S10.03", St.NOT_APPLICABLE, "No articles or guides in the sample")
        else:
            authorship = self._authorship(articles, loans)
        return [authorship, self._dates(articles, rate_pages)]

    def _authorship(self, articles, loans):
        named = {p.url: byline(p) for p in articles}
        anonymous = [u for u, b in named.items() if not b]
        unreviewed = [p.url for p in articles if not REVIEWER.search(p.visible_text())] if loans else []
        if not anonymous and unreviewed:
            return self.finding(
                "S10.03", St.WARN, f"{len(unreviewed)} financial article(s) name no reviewer", pages=unreviewed,
                severity=Sev.HIGH, evidence=[EvidenceRef(type="html_excerpt", url=u, excerpt="no 'Reviewed by'")
                                             for u in unreviewed[:5]],
                impact="Financial guides are held to a higher standard: a named, qualified reviewer shows expertise.",
                fix="Add 'Reviewed by <name>, <credential>' to each financial guide.",
                verification="Every financial guide names a reviewer.", effort=Effort.S)
        if not anonymous:
            return self.finding("S10.03", St.PASS, "Articles name their authors",
                                evidence=[EvidenceRef(type="html_excerpt", url=u, excerpt=b)
                                          for u, b in list(named.items())[:3]])
        status = St.FAIL if loans and len(anonymous) == len(articles) else St.WARN
        return self.finding(
            "S10.03", status, f"{len(anonymous)} of {len(articles)} article(s) have no named author",
            pages=anonymous, severity=Sev.HIGH if loans else None,
            evidence=[EvidenceRef(type="html_excerpt", url=u, excerpt="no byline, JSON-LD author or meta author")
                      for u in anonymous[:5]],
            impact="Anonymous content is weaker evidence of expertise for search engines and AI assistants"
                   + (", and financial guides need a named, qualified author or reviewer." if loans else "."),
            fix="Add a byline with the author's name and a short bio (and a named reviewer on financial content); "
                "mirror it in the Article JSON-LD `author`.", verification="Every article names its author.",
            effort=Effort.S)

    def _dates(self, articles, rate_pages):
        if not articles and not rate_pages:
            return self.finding("S10.04", St.NOT_APPLICABLE, "No articles or rate pages in the sample")
        undated = [p.url for p in articles + rate_pages if not date_signal(p)]
        undated_rates = [p.url for p in rate_pages if p.url in undated]
        if not undated:
            return self.finding("S10.04", St.PASS, "Articles and rate pages show dates",
                                evidence=[EvidenceRef(type="html_excerpt", url=p.url, excerpt=date_signal(p))
                                          for p in (articles + rate_pages)[:3]])
        return self.finding(
            "S10.04", St.FAIL if undated_rates else St.WARN,
            f"{len(undated)} article or rate page(s) show no published or updated date", pages=undated,
            evidence=[EvidenceRef(type="html_excerpt", url=u, excerpt="no visible date, JSON-LD date or date meta")
                      for u in undated[:5]],
            impact="Undated content looks stale; rates and prices without a date can't be trusted.",
            fix="Show 'Published' and 'Last updated' dates and add datePublished/dateModified to the JSON-LD.",
            verification="Dates visible on every article and rate page.", effort=Effort.S)

    # ------------------------------------------------------------ S10.05–S10.08 roll-up

    def _rollup(self, check_id, items: list[Judged], *, fail_on: str, ok: str, bad: str, impact: str, fix: str,
                severity: Sev | None = None, tags: list[str] | None = None):
        if not items:
            return self.finding(check_id, St.NOT_APPLICABLE, "Not expected for this archetype")
        known = [j for j in items if j.status != "unverified"]
        if not known:
            return self.finding(check_id, St.UNVERIFIABLE, "Not reviewed (LLM unavailable or its quotes didn't "
                                                           "match the page)")
        weak = [j for j in known if j.status in ("partial", "absent")]
        confidence = Confidence.CONFIRMED if all(j.source != "page" for j in items) else Confidence.LIKELY
        if not weak and len(known) < len(items):
            return self.finding(check_id, St.UNVERIFIABLE, f"{len(items) - len(known)} of {len(items)} item(s) "
                                                           "not reviewed", evidence=[j.evidence() for j in known[:6]])
        if not weak:
            return self.finding(check_id, St.PASS, ok, confidence=confidence, tags=tags or [],
                                evidence=[j.evidence() for j in known[:6]])
        failing = [j for j in weak if j.status == "absent" and (fail_on == "any" or (fail_on == "core" and j.core))]
        return self.finding(
            check_id, St.FAIL if failing else St.WARN, f"{len(weak)} of {len(items)} {bad}: "
            + ", ".join(f"{j.label} ({j.status})" for j in weak),
            pages=sorted({j.url for j in weak if j.url and j.source != "links"}), confidence=confidence,
            severity=severity, tags=tags or [], evidence=[j.evidence() for j in weak[:6]],
            missing_facts=[j.label for j in weak], impact=impact, fix=fix,
            verification="Re-run S10: each item present with specifics.", effort=Effort.M)


def byline(page: PageView) -> str | None:
    for node in page_nodes(page.model):
        if not types_of(node) & ARTICLE_TYPES:
            continue
        authors = node.get("author")
        for author in authors if isinstance(authors, list) else [authors]:
            if isinstance(author, dict) and "Organization" not in types_of(author) and author.get("name"):
                return f"JSON-LD author: {author['name']}"
            if isinstance(author, str) and author.strip():
                return f"JSON-LD author: {author.strip()}"
    meta_author = (page.model.get("meta") or {}).get("author")
    if meta_author:
        return f"meta author: {meta_author}"
    match = BYLINE.search(page.visible_text() + " " + (page.model.get("main_text_sample") or ""))
    return f"byline: {match.group(0)}" if match else None


def date_signal(page: PageView) -> str | None:
    for node in page_nodes(page.model):
        for key in ("dateModified", "datePublished"):
            if isinstance(node.get(key), str) and node[key].strip():
                return f"JSON-LD {key}: {node[key]}"
    meta = page.model.get("meta") or {}
    for key in DATE_META:
        if meta.get(key):
            return f"meta {key}: {meta[key]}"
    match = DATE.search(page.visible_text() + " " + (page.model.get("main_text_sample") or ""))
    return f"visible date: {match.group(0)}" if match else None
