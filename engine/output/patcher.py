"""Apply patches to a page snapshot (docs/spec/06).

apply()   → parses the original HTML twice and places patches on the ORIGINAL structure
            (locators were recorded on it; removing scripts first would shift XPath positions),
            then freezes both copies:
freeze()  → static copy: client scripts and event handlers removed, <base> added so the
            client's own CSS/images load (asset archiving is off on the free tier)
Result:
            fixed      every placeable patch applied
            annotated  the original, with each visible change marked (data-fix-id) so the
                       viewer's overlay can show the issue and before/after on click
Each patch is placed by XPath, then CSS, and only if the element's text hash still
matches; otherwise it's reported as "could not place", never forced.
"""

from __future__ import annotations

import html as html_lib
import json
from dataclasses import dataclass, field

from lxml import etree
from lxml import html as lxml_html

from engine.lib.locators import text_hash

INVISIBLE = {"head_upsert", "jsonld_upsert", "file_patch", "header_recommendation"}


def is_invisible(patch: dict) -> bool:
    """Changes a visitor can't see on the page (head tags, JSON-LD, files) go under the hood."""
    locator = patch.get("locator") or {}
    in_head = (locator.get("xpath") or "").startswith("/html/head") or (locator.get("css") or "").startswith("head")
    return patch["type"] in INVISIBLE or in_head


@dataclass
class PlacementResult:
    fixed_html: str
    annotated_html: str
    placed: list[str] = field(default_factory=list)
    not_placed: list[dict] = field(default_factory=list)  # {key, reason}
    under_the_hood: list[dict] = field(default_factory=list)


def freeze_doc(doc, page_url: str):
    for el in doc.xpath("//script[not(@type='application/ld+json')]|//noscript|//iframe"):
        el.drop_tree()
    for el in doc.iter():
        if not isinstance(el.tag, str):
            continue
        for attr in list(el.attrib):
            if attr.lower().startswith("on"):
                del el.attrib[attr]
        if el.tag == "a" and el.get("href", "").lower().startswith("javascript:"):
            el.set("href", "#")
        if el.tag == "form":
            el.set("action", "#")
    head = doc.find("head")
    if head is None:
        head = etree.SubElement(doc, "head")
        doc.insert(0, head)
    for existing in head.findall("base"):
        existing.drop_tree()
    head.insert(0, etree.fromstring(f'<base href="{html_lib.escape(page_url, quote=True)}"/>'))
    head.insert(1, etree.fromstring('<meta name="robots" content="noindex, nofollow"/>'))
    return doc


def _locate(doc, locator: dict | None):
    if not locator:
        return None, "no locator"
    candidates = []
    if locator.get("xpath"):
        try:
            candidates = doc.getroottree().xpath(locator["xpath"])
        except etree.XPathError:
            candidates = []
    if not candidates and locator.get("css"):
        try:
            candidates = doc.cssselect(locator["css"])
        except Exception:  # noqa: BLE001 - invalid selector
            candidates = []
    if not candidates:
        return None, "element not found"
    element = candidates[0]
    expected = locator.get("text_hash")
    if expected and text_hash(element.text_content()) != expected:
        return None, "element text changed since the crawl"
    return element, None


def _fragment(markup: str):
    return lxml_html.fragments_fromstring(markup)


def _apply_one(doc, patch: dict, element) -> str | None:
    """Apply one patch to `doc` in place, using its pre-resolved target element.
    Returns an error reason or None."""
    kind = patch["type"]
    if kind in ("file_patch", "header_recommendation"):
        return None  # not part of the page HTML; shown under the hood
    head = doc.find("head")
    if kind == "head_upsert":
        new = _fragment(patch["after"])[0]
        selector = {"link": f'link[rel="{new.get("rel", "")}"]', "meta": (
            f'meta[name="{new.get("name")}"]' if new.get("name") else f'meta[property="{new.get("property")}"]'),
            "title": "title"}.get(new.tag)
        existing = head.cssselect(selector) if selector else []
        if existing:
            existing[0].addprevious(new)
            existing[0].drop_tree()
        else:
            head.append(new)
        return None
    if element is None:
        return "element not found"
    if kind == "text_replace":
        for child in list(element):
            element.remove(child)
        element.text = patch["after"]
    elif kind == "attribute_set":
        name, _, value = patch["after"].partition("=")
        element.set(name.strip(), value.strip().strip('"'))
    elif kind == "element_insert":
        for node in _fragment(patch["after"]):
            if isinstance(node, str):
                continue
            element.addprevious(node)
    elif kind == "link_insert":
        anchor = _fragment(patch["after"])[0]  # <a href="...">exact phrase</a>
        if not _wrap_phrase(element, anchor.text_content(), anchor.get("href")):
            return "anchor phrase not found in the element"
    elif kind == "element_remove":
        element.drop_tree()
    elif kind == "jsonld_upsert":
        new = _fragment(patch["after"])[0]
        element.addprevious(new)
        element.drop_tree()
    else:
        return f"unknown patch type {kind}"
    return None


def _wrap_phrase(element, phrase: str, href: str) -> bool:
    """Wrap the first occurrence of `phrase` in the element's own text or a child's tail in <a href>.
    Text split across inline tags isn't matched (the patch is then reported as not placed)."""
    slots = [(element, "text")] + [(child, "tail") for child in element.iter() if child is not element]
    for node, attr in slots:
        value = getattr(node, attr) or ""
        at = value.lower().find(phrase.lower())
        if at < 0:
            continue
        link = etree.Element("a", {"href": href})
        link.text = value[at:at + len(phrase)]
        link.tail = value[at + len(phrase):]
        setattr(node, attr, value[:at])
        if attr == "text":
            node.insert(0, link)
        else:
            node.addnext(link)
        return True
    return False


def _mark(patch: dict, index: int, element) -> str | None:
    """Annotated view: mark the element a visible patch changes (or the insertion point)."""
    if element is None:
        return "element not found"
    fix_id = f"fix-{index}"
    if patch["type"] == "element_insert":
        marker = etree.Element("div", {"class": "dx-insert", "data-fix-id": fix_id})
        marker.text = "＋ Suggested addition here (click to see it)"
        element.addprevious(marker)
    else:
        element.set("data-fix-id", fix_id)
        element.set("class", (element.get("class", "") + " dx-changed").strip())
    return None


OVERLAY = """
<style>
[data-fix-id]{outline:3px solid #e8590c!important;outline-offset:2px;cursor:pointer;position:relative}
.dx-insert{display:block;margin:8px 0;padding:10px 14px;border:2px dashed #e8590c;border-radius:8px;
  background:#fff4e6;color:#8a3a00;font:600 14px/1.4 system-ui,sans-serif}
#dx-card{position:fixed;z-index:2147483647;right:16px;bottom:16px;width:min(420px,calc(100vw - 32px));
  max-height:70vh;overflow:auto;background:#fff;color:#1a1a1a;border-radius:12px;box-shadow:0 10px 40px rgba(0,0,0,.25);
  padding:16px;font:14px/1.5 system-ui,sans-serif;display:none}
#dx-card h4{margin:0 0 6px;font-size:15px}#dx-card .dx-label{font-weight:600;margin-top:10px;color:#555}
#dx-card pre{white-space:pre-wrap;background:#f4f4f5;padding:8px;border-radius:6px;font-size:12px;margin:4px 0}
#dx-card button{float:right;border:0;background:none;font-size:18px;cursor:pointer}
</style>
<div id="dx-card" role="dialog" aria-live="polite"></div>
<script id="dx-data" type="application/json">__DATA__</script>
<script>
(function(){var data=JSON.parse(document.getElementById('dx-data').textContent);
var card=document.getElementById('dx-card');
function esc(s){return String(s==null?'':s).replace(/[&<>"]/g,function(c){return {'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]})}
document.addEventListener('click',function(e){var el=e.target.closest('[data-fix-id]');if(!el)return;
e.preventDefault();var p=data[el.getAttribute('data-fix-id')];if(!p)return;
card.innerHTML='<button aria-label="Close">×</button><h4>'+esc(p.title)+'</h4><div>'+esc(p.note)+'</div>'+
(p.before?'<div class="dx-label">Now</div><pre>'+esc(p.before)+'</pre>':'')+
'<div class="dx-label">Suggested</div><pre>'+esc(p.after)+'</pre>'+
'<div class="dx-label">Why</div><div>'+esc(p.why)+'</div>';card.style.display='block';
card.querySelector('button').onclick=function(){card.style.display='none'};},true);})();
</script>
"""


def apply(page_html: str, page_url: str, patches: list[dict]) -> PlacementResult:
    fixed = lxml_html.fromstring(page_html)
    annotated = lxml_html.fromstring(page_html)
    result = PlacementResult("", "")
    card_data = {}
    # Resolve every target BEFORE changing anything: an insert shifts the XPath positions of later
    # siblings, so locating patch-by-patch would send later patches to the wrong element.
    needs_target = [p for p in patches if p["type"] not in ("head_upsert", "file_patch", "header_recommendation")]
    fixed_targets = {p["key"]: _locate(fixed, p.get("locator")) for p in needs_target}
    marked_targets = {p["key"]: _locate(annotated, p.get("locator")) for p in needs_target if not is_invisible(p)}
    for index, patch in enumerate(patches):
        if is_invisible(patch):
            result.under_the_hood.append({"key": patch["key"], "type": patch["type"], "before": patch.get("before"),
                                          "after": patch["after"], "why": patch.get("rationale", ""),
                                          "note": patch.get("client_visible_note", "")})
        # Mark before applying, so the annotation locator still matches the original element.
        mark_error = None
        if not is_invisible(patch):
            element, reason = marked_targets[patch["key"]]
            mark_error = reason or _mark(patch, index, element)
        element, reason = fixed_targets.get(patch["key"], (None, None))
        error = reason or _apply_one(fixed, patch, element)
        if error or mark_error:
            result.not_placed.append({"key": patch["key"], "reason": error or mark_error})
            continue
        result.placed.append(patch["key"])
        card_data[f"fix-{index}"] = {"title": patch.get("title") or "Suggested change",
                                     "note": patch.get("client_visible_note", ""), "before": patch.get("before"),
                                     "after": patch["after"], "why": patch.get("rationale", "")}
    fixed = freeze_doc(fixed, page_url)
    annotated = freeze_doc(annotated, page_url)
    body = annotated.find("body")
    if body is not None:
        overlay = OVERLAY.replace("__DATA__", json.dumps(card_data).replace("</", "<\\/"))
        for node in lxml_html.fragments_fromstring(overlay):
            if not isinstance(node, str):
                body.append(node)
    result.fixed_html = lxml_html.tostring(fixed, doctype="<!DOCTYPE html>", encoding="unicode")
    result.annotated_html = lxml_html.tostring(annotated, doctype="<!DOCTYPE html>", encoding="unicode")
    return result
