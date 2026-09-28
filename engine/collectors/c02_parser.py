"""C2 Page Parser: turns raw HTML into a structured page model.

`parse_page` is a pure function (HTML in, dict out) so it's easy to test.
The model is stored gzip'd in blob storage; the evidence row keeps a small summary.
"""

from __future__ import annotations

import hashlib
import json
from urllib.parse import urljoin, urlsplit

from lxml import etree
from lxml import html as lxml_html

from engine.collectors.base import Collector
from engine.context import CollectorContext, WorkUnit
from engine.lib.locators import locate, normalize_text
from engine.schemas import EvidenceType

PARSE_BATCH = 5
MAX_PASSAGES = 300
MAX_FOOTER_CHARS = 20000
MAX_CONTROLS = 150
_BOILERPLATE = ("nav", "header", "footer", "aside", "script", "style", "noscript", "template", "form")
_PASSAGE_TAGS = ("p", "li", "td", "dd", "blockquote")
_BLOCK_TAGS = ("p", "div", "li", "ul", "ol", "td", "th", "tr", "dd", "dt", "blockquote", "section", "article",
               "main", "h1", "h2", "h3", "h4", "h5", "h6", "br", "table", "figure", "figcaption")


def _controls(doc) -> dict[str, list[dict]]:
    """Forms, inputs and buttons: evidence of tools such as booking engines, calculators and trackers.
    Framework bindings (ng-model, v-model, formcontrolname) are kept because JavaScript widgets often
    have no name attribute."""
    def menu(el) -> bool:
        return bool(el.xpath("ancestor::header|ancestor::nav|ancestor::footer"))

    inputs = [{"tag": el.tag, "type": (el.get("type") or "").lower(), "name": el.get("name"), "id": el.get("id"),
               "placeholder": el.get("placeholder"),
               "model": el.get("ng-model") or el.get("v-model") or el.get("formcontrolname"),
               "in_form": bool(el.xpath("ancestor::form")), "in_boilerplate": menu(el)}
              for el in doc.xpath("//input[not(@type='hidden')]|//select|//textarea")[:MAX_CONTROLS]]
    buttons = []
    for el in doc.xpath("//button|//input[@type='submit' or @type='button']")[:MAX_CONTROLS]:
        text = normalize_text(el.text_content() or el.get("value") or el.get("aria-label") or "")
        if text:
            buttons.append({"text": text[:80], "in_boilerplate": menu(el)})
    forms = [{"action": f.get("action"), "method": (f.get("method") or "get").lower(),
              "inputs": len(f.xpath(".//input[not(@type='hidden')]|.//select|.//textarea")), "in_boilerplate": menu(f)}
             for f in doc.xpath("//form")[:30]]
    return {"forms": forms, "inputs": inputs, "buttons": buttons}


def _meta(doc) -> dict[str, str]:
    meta: dict[str, str] = {}
    for el in doc.xpath("//head//meta[@content]"):
        key = (el.get("name") or el.get("property") or el.get("http-equiv") or "").strip().lower()
        if key and key not in meta:
            meta[key] = el.get("content", "").strip()
    return meta


def _cf_email(encoded: str) -> str | None:
    """Decode a Cloudflare-protected email: hex bytes, each XOR-ed with the first byte."""
    try:
        data = bytes.fromhex(encoded)
    except ValueError:
        return None
    email = bytes(b ^ data[0] for b in data[1:]).decode("utf-8", "replace") if len(data) > 1 else ""
    return email if "@" in email else None


def _template_id(doc) -> str:
    """Hash of the body's structural skeleton (tags + classes, 3 levels deep)."""
    body = doc.find("body")
    if body is None:
        return "no-body"

    def skeleton(el, depth: int) -> str:
        if depth == 0 or not isinstance(el.tag, str):
            return ""
        cls = ".".join(sorted((el.get("class") or "").split()[:3]))
        return f"{el.tag}{'.' + cls if cls else ''}(" + ",".join(
            skeleton(child, depth - 1) for child in el if isinstance(child.tag, str)) + ")"

    return hashlib.sha1(skeleton(body, 3).encode()).hexdigest()[:10]


def _simhash(text: str) -> str:
    """64-bit simhash over word 3-shingles, for near-duplicate detection."""
    words = text.lower().split()
    shingles = [" ".join(words[i:i + 3]) for i in range(max(1, len(words) - 2))]
    weights = [0] * 64
    for shingle in shingles:
        h = int(hashlib.md5(shingle.encode()).hexdigest()[:16], 16)
        for bit in range(64):
            weights[bit] += 1 if h >> bit & 1 else -1
    return f"{sum(1 << bit for bit in range(64) if weights[bit] > 0):016x}"


def parse_page(page_html: str, url: str) -> dict:
    try:
        doc = lxml_html.fromstring(page_html)
    except (ValueError, etree.ParserError):
        return {"url": url, "parse_error": "unparseable HTML"}
    doc.make_links_absolute(url, resolve_base_href=True)
    host = (urlsplit(url).hostname or "").removeprefix("www.")

    title_el = doc.find(".//head/title")
    canonical_el = next(iter(doc.xpath("//head/link[translate(@rel,'CANONICAL','canonical')='canonical']")), None)
    html_el = doc if doc.tag == "html" else doc.getroottree().getroot()

    headings = [{"level": int(el.tag[1]), "text": normalize_text(el.text_content())[:300],
                 "locator": locate(el).model_dump()} for el in doc.xpath("//h1|//h2|//h3|//h4|//h5|//h6")]

    links = []
    for el in doc.xpath("//a[@href]"):
        href = el.get("href", "")
        if not href.startswith(("http://", "https://")):
            continue
        rel = (el.get("rel") or "").lower().split()
        link_host = (urlsplit(href).hostname or "").removeprefix("www.")
        in_nav = bool(el.xpath("ancestor::nav|ancestor::header"))
        in_footer = bool(el.xpath("ancestor::footer"))
        text = normalize_text(el.text_content())
        images = el.xpath(".//img")
        if not text and images:  # an image link's anchor text is its alt text
            text = normalize_text(" ".join(img.get("alt") or "" for img in images))
        link = {"href": href.split("#")[0], "text": text[:200], "image": bool(images),
                "internal": link_host == host, "nofollow": "nofollow" in rel,
                "in_nav": in_nav, "in_footer": in_footer, "in_boilerplate": in_nav or in_footer}
        if not (in_nav or in_footer):  # body links get a locator so a patch can change their href
            link["locator"] = locate(el).model_dump()
        links.append(link)

    contacts = [{"type": el.get("href", "").split(":", 1)[0].lower(),
                 "value": el.get("href", "").split(":", 1)[1].split("?")[0].strip(),
                 "text": normalize_text(el.text_content())[:100]}
                for el in doc.xpath("//a[starts-with(@href,'tel:') or starts-with(@href,'mailto:')]")]
    # Cloudflare email protection shows "[email protected]" until a script decodes it in the browser.
    for el in doc.xpath("//*[@data-cfemail]|//a[contains(@href,'/cdn-cgi/l/email-protection#')]"):
        email = _cf_email(el.get("data-cfemail") or el.get("href", "").rsplit("#", 1)[-1])
        if email and all(c["value"] != email for c in contacts):
            contacts.append({"type": "mailto", "value": email, "text": normalize_text(el.text_content())[:100],
                             "obfuscated": "cloudflare"})

    images = []
    # Lazy-loading libraries keep the real URL in data-src (or similar) and add src only with JavaScript.
    for el in doc.xpath("//img[@src or @data-src or @data-lazy-src or @data-original]"):
        lazy = el.get("data-src") or el.get("data-lazy-src") or el.get("data-original")
        src = el.get("src")
        real = urljoin(url, lazy) if lazy and (not src or src.startswith("data:") or "placeholder" in src) else src
        images.append({"src": real, "alt": el.get("alt"), "width": el.get("width"), "height": el.get("height"),
                       "loading": el.get("loading"), "lazy": bool(lazy) or el.get("loading") == "lazy",
                       "in_boilerplate": bool(el.xpath("ancestor::header|ancestor::nav|ancestor::footer")),
                       "locator": locate(el).model_dump()})

    jsonld = []
    for el in doc.xpath("//script[@type='application/ld+json']"):
        raw = el.text or ""
        entry = {"raw": raw[:20000], "locator": locate(el).model_dump()}
        try:
            entry["parsed"] = json.loads(raw)
        except json.JSONDecodeError as exc:
            try:  # raw line breaks/tabs inside strings: invalid strict JSON, but many parsers accept it
                entry["parsed"] = json.loads(raw, strict=False)
                entry["warning"] = f"not strict JSON ({exc.msg} at line {exc.lineno})"
            except json.JSONDecodeError:
                entry["error"] = f"{exc.msg} at line {exc.lineno}"
        jsonld.append(entry)

    resources = [{"tag": el.tag, "src": el.get("src") or el.get("href")}
                 for el in doc.xpath("//script[@src]|//iframe[@src]|//link[@rel='stylesheet'][@href]|"
                                     "//img[@src]|//video[@src]|//audio[@src]|//source[@src]")]

    main = doc.find(".//body")
    main_text, passages = "", []
    if main is not None:
        clone = lxml_html.fromstring(etree.tostring(main))
        for el in clone.xpath("|".join(f"//{tag}" for tag in _BOILERPLATE)):
            el.drop_tree()
        for el in clone.iter(*_BLOCK_TAGS):  # minified HTML: "<h1>Title</h1><p>By…" must not read "TitleBy…"
            el.tail = " " + (el.tail or "")
        main_text = normalize_text(clone.text_content())
        for el in main.xpath("|".join(f".//{tag}" for tag in _PASSAGE_TAGS)):
            if el.xpath("|".join(f"ancestor::{tag}" for tag in _BOILERPLATE)):
                continue
            text = normalize_text(el.text_content())
            if len(text) >= 40:
                passages.append({"tag": el.tag, "text": text[:2000], "locator": locate(el).model_dump()})
            if len(passages) >= MAX_PASSAGES:
                break

    # Footers are boilerplate for content analysis, but they are where policies, registration numbers and
    # company details live. Kept as plain text (template placeholders included) for trust checks.
    footer_parts = []
    for footer in (main.xpath(".//footer[not(ancestor::footer)]") if main is not None else []):
        clone = lxml_html.fromstring(etree.tostring(footer, with_tail=False))
        for el in clone.xpath(".//script|.//style|.//noscript|.//template"):
            el.drop_tree()
        for el in clone.iter(*_BLOCK_TAGS):
            el.tail = " " + (el.tail or "")
        footer_parts.append(normalize_text(clone.text_content()))
    footer_text = " ".join(footer_parts)[:MAX_FOOTER_CHARS]

    outline = []
    if main is not None:
        for el in main.iter(*[f"h{i}" for i in range(1, 7)], *_PASSAGE_TAGS, "summary", "dt"):
            if el.xpath("|".join(f"ancestor::{tag}" for tag in _BOILERPLATE)):
                continue
            text = normalize_text(el.text_content())
            if el.tag.startswith("h") and len(el.tag) == 2:
                if text:
                    outline.append({"type": "heading", "level": int(el.tag[1]), "text": text[:300],
                                    "locator": locate(el).model_dump()})
            elif len(text) >= 20:
                outline.append({"type": "passage", "tag": el.tag, "text": text[:2000],
                                "locator": locate(el).model_dump()})
            if len(outline) >= 500:
                break

    meta = _meta(doc)
    return {
        "url": url,
        "lang": html_el.get("lang"),
        "title": normalize_text(title_el.text_content()) if title_el is not None else None,
        "title_locator": locate(title_el).model_dump() if title_el is not None else None,
        "meta": meta,
        "meta_robots": meta.get("robots"),
        "canonical": canonical_el.get("href") if canonical_el is not None else None,
        "hreflang": [{"lang": el.get("hreflang"), "href": el.get("href")}
                     for el in doc.xpath("//head/link[@rel='alternate'][@hreflang]")],
        "headings": headings,
        "links": links,
        "contacts": contacts,
        "images": images,
        "jsonld": jsonld,
        "resources": resources,
        "main_text_words": len(main_text.split()),
        "main_text_sample": main_text[:1000],
        "content_hash": hashlib.sha1(main_text.lower().encode()).hexdigest()[:16],
        "simhash": _simhash(main_text) if main_text else None,
        "passages": passages,
        "outline": outline,
        "footer_text": footer_text,
        "nosnippet_elements": len(doc.xpath("//*[@data-nosnippet]")),
        "controls": _controls(doc),
        "template_id": _template_id(doc),
    }


class PageParser(Collector):
    id = "C2"
    name = "Page Parser"
    produces = frozenset({EvidenceType.PAGES_PARSED})
    requires = frozenset({EvidenceType.PAGES_RAW})

    def plan(self, ctx: CollectorContext) -> list[WorkUnit]:
        ids = [p.id for p in ctx.snapshot.pages() if p.raw_html_key]
        return [WorkUnit("parse", {"page_ids": ids[i:i + PARSE_BATCH]}) for i in range(0, len(ids), PARSE_BATCH)]

    def run_unit(self, ctx: CollectorContext, unit: WorkUnit) -> list[WorkUnit]:
        wanted = set(unit.params["page_ids"])
        for page in ctx.snapshot.pages():
            if page.id not in wanted or not page.raw_html_key:
                continue
            model = parse_page(ctx.snapshot.blob_text(page.raw_html_key), page.final_url or page.url)
            key = ctx.snapshot.put_blob(f"snapshots/{ctx.snapshot.snapshot_id}/pages/{page.id}/parsed.json",
                                        json.dumps(model))
            page.template_id = model.get("template_id")
            ctx.snapshot.update_page(page)
            summary = {k: model.get(k) for k in ("title", "lang", "canonical", "meta_robots", "main_text_words",
                                                 "template_id", "parse_error")}
            summary["h1_count"] = sum(1 for h in model.get("headings", []) if h["level"] == 1)
            ctx.snapshot.add_evidence(self.id, EvidenceType.PAGES_PARSED, summary, page_id=page.id,
                                      blob_key=key, source_label="derived")
        return []

