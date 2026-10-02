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

from engine.lib.jsonld import merge3, script_tag
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


# The annotated view's overlay (v2). Hovering a marked change shows its name beside the cursor (also while
# scrolling under a still cursor); a stepper walks through every change; a click opens before and after.
# It is attached when the page is built and re-attached when it is served, so pages built earlier get the
# current overlay too (see upgrade_annotated).
OVERLAY_VERSION = "2"
OVERLAY = """
<style id="dx-style" data-version="__VERSION__">
[data-fix-id],[data-dx-host]{outline:3px solid #0b8a50!important;outline-offset:3px;cursor:pointer;
  box-shadow:0 0 0 7px rgba(11,138,80,.16)!important;scroll-margin:120px}
[data-fix-id].dx-active,[data-dx-host].dx-active{outline-color:#e8590c!important;box-shadow:0 0 0 9px rgba(232,89,12,.22)!important}
.dx-insert{display:block;margin:8px 0;padding:10px 14px;border:2px dashed #0b8a50;border-radius:8px;
  background:#e9f7ef;color:#064d2e;font:600 14px/1.4 system-ui,sans-serif}
#dx-tip{position:fixed;z-index:2147483646;pointer-events:none;max-width:290px;padding:9px 12px;border-radius:8px;
  background:#03160d;color:#fff;font:13px/1.4 system-ui,sans-serif;box-shadow:0 8px 24px rgba(0,0,0,.28);
  opacity:0;transform:translateY(4px);transition:opacity .12s ease,transform .12s ease}
#dx-tip.dx-on{opacity:1;transform:none}
#dx-tip b{display:block;font-size:13.5px;margin:2px 0 3px}#dx-tip small{display:block;color:#9fd8b9;font-size:11.5px}
#dx-nav{position:fixed;z-index:2147483646;left:50%;bottom:16px;transform:translateX(-50%);display:flex;align-items:center;
  gap:4px;padding:5px;border-radius:999px;background:#03160d;color:#fff;font:600 13px/1 system-ui,sans-serif;
  box-shadow:0 8px 24px rgba(0,0,0,.28)}
#dx-nav button{all:unset;cursor:pointer;width:34px;height:34px;border-radius:999px;display:grid;place-items:center;
  font-size:15px;color:#fff}
#dx-nav button:hover{background:rgba(255,255,255,.14)}#dx-nav button:focus-visible{outline:2px solid #5fd69a}
#dx-nav span{padding:0 8px;white-space:nowrap;font-variant-numeric:tabular-nums}
#dx-card{position:fixed;z-index:2147483647;right:16px;bottom:70px;width:min(420px,calc(100vw - 32px));
  max-height:min(70vh,calc(100vh - 100px));overflow:auto;background:#fff;color:#1a1a1a;border-radius:12px;
  box-shadow:0 10px 40px rgba(0,0,0,.25);padding:16px;font:14px/1.5 system-ui,sans-serif;display:none}
#dx-card .dx-n{font-size:12px;color:#0b8a50;font-weight:600}
#dx-card h4{margin:2px 28px 6px 0;font-size:15px}#dx-card .dx-label{font-weight:600;margin-top:10px;color:#555}
#dx-card pre{white-space:pre-wrap;word-break:break-word;background:#f4f4f5;padding:8px;border-radius:6px;font-size:12px;margin:4px 0}
#dx-card .dx-x{position:absolute;right:10px;top:8px;border:0;background:none;font-size:20px;cursor:pointer;color:#555}
@media (prefers-reduced-motion:reduce){#dx-tip{transition:none}}
</style>
<div id="dx-tip" role="tooltip" aria-hidden="true"></div>
<div id="dx-nav" role="group" aria-label="Changes on this page"><button type="button" data-dx="prev" aria-label="Previous change">&#9664;</button><span aria-live="polite"></span><button type="button" data-dx="next" aria-label="Next change">&#9654;</button></div>
<div id="dx-card" role="dialog" aria-live="polite"></div>
<script id="dx-data" type="application/json">__DATA__</script>
<script id="dx-script">
(function(){
var data=JSON.parse(document.getElementById('dx-data').textContent||'{}');
var tip=document.getElementById('dx-tip'),nav=document.getElementById('dx-nav'),card=document.getElementById('dx-card');
var label=nav.querySelector('span');
var reduce=window.matchMedia&&matchMedia('(prefers-reduced-motion: reduce)').matches;
var hover=!window.matchMedia||matchMedia('(hover: hover)').matches;
// Changes that weren't placed stay unmarked; the rest in page order.
var marks=[].slice.call(document.querySelectorAll('[data-fix-id]')).filter(function(el){
  if(data[el.getAttribute('data-fix-id')])return true;
  if(el.classList.contains('dx-insert'))el.remove();else{el.removeAttribute('data-fix-id');el.classList.remove('dx-changed');}
  return false;});
var hosts=marks.map(function(el){var r=el.getBoundingClientRect();
  if(el.getClientRects().length&&(r.width<16||r.height<16)&&el.parentElement&&el.parentElement!==document.body){
    el.parentElement.setAttribute('data-dx-host','');return el.parentElement;}
  return el;});
var total=marks.length,current=-1,lastX=-1,lastY=-1;
if(!total){nav.remove();return;}
function esc(s){return String(s==null?'':s).replace(/[&<>"]/g,function(c){return {'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]})}
function info(el){return data[el.getAttribute('data-fix-id')]||{};}
function count(i){return 'Change '+(i+1)+' of '+total;}
function setLabel(i){label.textContent=i<0?total+(total===1?' change':' changes'):count(i);}
setLabel(-1);
function showTip(el,x,y){
  var i=marks.indexOf(el);
  tip.innerHTML='<small>'+esc(count(i))+'</small><b>'+esc(info(el).title)+'</b><small>Click for before and after</small>';
  tip.classList.add('dx-on');
  var w=tip.offsetWidth,h=tip.offsetHeight,vw=innerWidth,vh=innerHeight;
  var left=x+16,top=y+18;
  if(left+w>vw-8)left=Math.max(8,x-w-16);
  if(top+h>vh-70)top=Math.max(8,y-h-14);
  tip.style.left=left+'px';tip.style.top=top+'px';
}
function hideTip(){tip.classList.remove('dx-on');}
function markOf(node){var el=node&&node.closest?node.closest('[data-fix-id],[data-dx-host]'):null;if(!el)return null;
  var i=marks.indexOf(el);if(i<0)i=hosts.indexOf(el);return i<0?null:marks[i];}
function markAt(x,y){return markOf(document.elementFromPoint(x,y));}
function active(i){hosts.forEach(function(h,n){h.classList.toggle('dx-active',n===i)});}
if(hover){
  document.addEventListener('mousemove',function(e){lastX=e.clientX;lastY=e.clientY;
    var el=markOf(e.target);
    if(el){showTip(el,e.clientX,e.clientY);active(marks.indexOf(el));}else{hideTip();active(current);}
  },{passive:true});
  document.addEventListener('mouseleave',hideTip);
}
var ticking=false;
addEventListener('scroll',function(){if(ticking)return;ticking=true;requestAnimationFrame(function(){ticking=false;
  // Under a still cursor, scrolling brings changes to the pointer: point them out there too.
  if(hover&&lastX>=0){var el=markAt(lastX,lastY);if(el)showTip(el,lastX,lastY);else hideTip();}
  // The stepper follows the change nearest the middle of the screen.
  var mid=innerHeight/2,best=-1,gap=Infinity;
  hosts.forEach(function(m,n){var r=m.getBoundingClientRect();if(!r.height||r.bottom<0||r.top>innerHeight)return;
    var d=Math.abs(r.top+r.height/2-mid);if(d<gap){gap=d;best=n;}});
  if(best>=0&&card.style.display!=='block'){current=best;setLabel(best);}
});},{passive:true});
function openCard(el){
  var p=info(el),i=marks.indexOf(el);current=i;setLabel(i);active(i);hideTip();
  card.innerHTML='<button class="dx-x" aria-label="Close">&times;</button><div class="dx-n">'+esc(count(i))+'</div><h4>'+esc(p.title)+'</h4>'+
    (p.note?'<div>'+esc(p.note)+'</div>':'')+
    (p.before?'<div class="dx-label">Now</div><pre>'+esc(p.before)+'</pre>':'')+
    '<div class="dx-label">Suggested</div><pre>'+esc(p.after)+'</pre>'+
    (p.why?'<div class="dx-label">Why</div><div>'+esc(p.why)+'</div>':'');
  card.style.display='block';card.querySelector('.dx-x').onclick=closeCard;
}
function closeCard(){card.style.display='none';}
function go(i){
  current=(i+total)%total;var el=marks[current],box=hosts[current];setLabel(current);active(current);
  var r=box.getBoundingClientRect();
  if(!r.width&&!r.height){openCard(el);return;}  // hidden on this screen size: show its card instead
  box.scrollIntoView({block:'center',behavior:reduce?'auto':'smooth'});
  setTimeout(function(){var b=box.getBoundingClientRect();showTip(el,Math.min(b.right,innerWidth-40)-24,Math.max(b.top,60));},reduce?0:420);
}
nav.addEventListener('click',function(e){var b=e.target.closest('button');if(!b)return;
  closeCard();go(b.getAttribute('data-dx')==='next'?current+1:current-1);});
document.addEventListener('click',function(e){if(e.target.closest('#dx-card,#dx-nav'))return;
  var el=markOf(e.target);if(!el)return;e.preventDefault();openCard(el);},true);
document.addEventListener('keydown',function(e){if(e.key==='Escape'){closeCard();hideTip();}});
})();
</script>
"""

_OVERLAY_IDS = ("dx-style", "dx-tip", "dx-nav", "dx-card", "dx-data", "dx-script")


def attach_overlay(doc, card_data: dict) -> None:
    """Append the current overlay, with each placed change's card, to an annotated page's body."""
    body = doc.find("body")
    if body is None:
        return
    overlay = OVERLAY.replace("__VERSION__", OVERLAY_VERSION).replace(
        "__DATA__", json.dumps(card_data).replace("</", "<\\/"))
    for node in lxml_html.fragments_fromstring(overlay):
        if not isinstance(node, str):
            body.append(node)


def _remove(node) -> None:
    """Remove an overlay node; its trailing text is only the whitespace between overlay nodes."""
    if node.getparent() is None:
        return
    if (node.tail or "").strip() == "":
        node.getparent().remove(node)
    else:
        node.drop_tree()


def upgrade_annotated(page_html: bytes | str, titles: dict[str, str] | None = None) -> str:
    """An annotated page with the current overlay, keeping its change data. Pages built before an overlay
    change (stored previews, published microsites) get the new behaviour without being rebuilt. `titles`
    maps a stored card title (the agent's technical title) to its plain name."""
    text = page_html.decode("utf-8", errors="replace") if isinstance(page_html, bytes) else page_html
    doc = lxml_html.fromstring(text)
    data_node = doc.get_element_by_id("dx-data", None)
    if data_node is None:
        return text
    try:
        card_data = json.loads(data_node.text or "{}")
    except ValueError:
        return text
    for card in card_data.values():
        card["title"] = (titles or {}).get(card.get("title"), card.get("title"))
    old = doc.xpath("//body/style[contains(., '[data-fix-id]')] | //body/script[not(@type)][contains(., 'dx-data')]")
    old += [n for n in (doc.get_element_by_id(i, None) for i in _OVERLAY_IDS) if n is not None]
    for node in dict.fromkeys(old):  # a node can match both ways
        _remove(node)
    attach_overlay(doc, card_data)
    return lxml_html.tostring(doc, doctype="<!DOCTYPE html>", encoding="unicode")


def _merge_shared_blocks(page_html: str, patches: list[dict]) -> tuple[list[dict], dict[str, list[str]]]:
    """Agents work apart, so two of them can rewrite the same JSON-LD block (one fills the name, another adds
    sameAs). Applied one after the other, the second would overwrite the first; instead they become one change
    with both edits merged against the block as captured. Returns the patches and {lead key: merged keys}."""
    groups: dict[str, list[dict]] = {}
    for patch in patches:
        locator = patch.get("locator") or {}
        ident = locator.get("xpath") or locator.get("css")
        if patch["type"] == "jsonld_upsert" and ident:
            groups.setdefault(ident, []).append(patch)
    doc = lxml_html.fromstring(page_html)
    merged, aliases = {}, {}
    for group in (g for g in groups.values() if len(g) > 1):
        element, _ = _locate(doc, group[0]["locator"])
        try:
            base = json.loads(element.text or "") if element is not None else None
            edits = [json.loads(_fragment(p["after"])[0].text or "") for p in group]
        except (ValueError, TypeError, IndexError):
            continue
        if base is None:
            continue
        result = edits[0]
        for edit in edits[1:]:
            result = merge3(base, result, edit)
        lead = group[0]
        merged[lead["key"]] = {**lead, "after": script_tag(result),
                               "rationale": " ".join(p.get("rationale", "") for p in group).strip()}
        aliases[lead["key"]] = [p["key"] for p in group[1:]]
    folded = {k for keys in aliases.values() for k in keys}
    return [merged.get(p["key"], p) for p in patches if p["key"] not in folded], aliases


def apply(page_html: str, page_url: str, patches: list[dict]) -> PlacementResult:
    patches, aliases = _merge_shared_blocks(page_html, patches)
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
    for lead, keys in aliases.items():  # merged changes share the fate of the change they were folded into
        if lead in result.placed:
            result.placed += keys
        else:
            reason = next((n["reason"] for n in result.not_placed if n["key"] == lead), "not placed")
            result.not_placed += [{"key": k, "reason": reason} for k in keys]
    fixed = freeze_doc(fixed, page_url)
    annotated = freeze_doc(annotated, page_url)
    attach_overlay(annotated, card_data)
    result.fixed_html = lxml_html.tostring(fixed, doctype="<!DOCTYPE html>", encoding="unicode")
    result.annotated_html = lxml_html.tostring(annotated, doctype="<!DOCTYPE html>", encoding="unicode")
    return result
