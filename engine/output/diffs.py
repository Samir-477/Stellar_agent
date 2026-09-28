"""Before/after code for each proposed change, taken from the captured page.

For every patch on a page: the element as captured ("before") and the same element with
the change applied ("after"), as HTML (or pretty JSON for structured data), plus word-level
segments so the UI can highlight exactly what changed. Placement uses the patcher's own
locator rules, so a change that can't be placed here can't be placed in the preview either.
Changes outside the page HTML (site files, HTTP headers) use the patch's own text.
"""

from __future__ import annotations

import copy
import difflib
import json
import re

from lxml import etree
from lxml import html as lxml_html

from engine.output.patcher import _apply_one, _fragment, _locate

MAX_CHARS = 1600  # longer elements are shortened to their opening tag, some text and a marker
_TOKENS = re.compile(r"\s+|[\w\-]+|[^\w\s]", re.UNICODE)


def _outer(element) -> str:
    # Source indentation and line breaks aren't part of the change; one space keeps diffs readable.
    return re.sub(r"\s+", " ", lxml_html.tostring(element, encoding="unicode", with_tail=False)).strip()


def _short(element) -> str:
    """The element's HTML, or for a large one its opening tag, the start of its text and the closing tag."""
    full = _outer(element)
    if len(full) <= MAX_CHARS:
        return full
    attrs = "".join(f' {k}="{v}"' for k, v in element.attrib.items())
    text = " ".join(element.text_content().split())
    return f"<{element.tag}{attrs}>{text[:240]}… </{element.tag}>"


def _opening_tag(element) -> str:
    attrs = "".join(f' {k}="{v}"' for k, v in element.attrib.items())
    return f"<{element.tag}{attrs}>"


def _pretty_json(text: str | None) -> str | None:
    if not text:
        return text
    try:
        return json.dumps(json.loads(text), indent=2, ensure_ascii=False)
    except (ValueError, TypeError):
        return text.strip()


def segments(before: str | None, after: str | None) -> tuple[list[dict], list[dict]]:
    """Word-level diff: before as [equal|delete] runs, after as [equal|insert] runs."""
    a, b = _TOKENS.findall(before or ""), _TOKENS.findall(after or "")
    left: list[dict] = []
    right: list[dict] = []

    def push(target: list[dict], kind: str, text: str) -> None:
        if not text:
            return
        if target and target[-1]["k"] == kind:
            target[-1]["t"] += text
        else:
            target.append({"k": kind, "t": text})

    for op, i1, i2, j1, j2 in difflib.SequenceMatcher(None, a, b, autojunk=False).get_opcodes():
        if op == "equal":
            push(left, "eq", "".join(a[i1:i2]))
            push(right, "eq", "".join(b[j1:j2]))
        else:
            push(left, "del", "".join(a[i1:i2]))
            push(right, "ins", "".join(b[j1:j2]))
    return _fold_spaces(left), _fold_spaces(right)


def _fold_spaces(runs: list[dict]) -> list[dict]:
    """A lone space kept 'equal' between two changes reads as noise; fold it into the change."""
    out: list[dict] = []
    for index, run in enumerate(runs):
        between = 0 < index < len(runs) - 1 and runs[index - 1]["k"] != "eq" == run["k"] and runs[index + 1]["k"] != "eq"
        if between and not run["t"].strip():
            out[-1]["t"] += run["t"]
            continue
        if out and out[-1]["k"] == run["k"]:
            out[-1]["t"] += run["t"]
        else:
            out.append(dict(run))
    return out


def snippet(page_html: str | None, patch: dict) -> dict:
    """One change as {language, before, after, placed, reason, before_segments, after_segments}."""
    kind = patch["type"]
    language = "json" if kind == "jsonld_upsert" else "text" if kind in ("file_patch", "header_recommendation") else "html"
    before, after, placed, reason = patch.get("before"), patch["after"], True, None

    if kind in ("file_patch", "header_recommendation") or not page_html:
        if not page_html and kind not in ("file_patch", "header_recommendation"):
            placed, reason = False, "The captured page isn't available in this storage."
    elif kind == "head_upsert":
        doc = lxml_html.fromstring(page_html)
        new = _fragment(after)[0]
        head = doc.find("head")
        selector = {"link": f'link[rel="{new.get("rel", "")}"]', "meta": (
            f'meta[name="{new.get("name")}"]' if new.get("name") else f'meta[property="{new.get("property")}"]'),
            "title": "title"}.get(new.tag)
        existing = head.cssselect(selector) if head is not None and selector else []
        before = _outer(existing[0]) if existing else None
        after = _outer(new)
    else:
        doc = lxml_html.fromstring(page_html)
        element, reason = _locate(doc, patch.get("locator"))
        if element is None:
            placed = False
        else:
            if kind == "jsonld_upsert":
                before = _pretty_json(element.text)
                after = _pretty_json(_fragment(after)[0].text)
            elif kind == "element_insert":
                context = _short(element)
                before = context
                after = "\n".join(_outer(n) for n in _fragment(after) if not isinstance(n, str)) + "\n" + context
            elif kind == "attribute_set":
                before = _opening_tag(element)
                name, _, value = after.partition("=")
                element.set(name.strip(), value.strip().strip('"'))
                after = _opening_tag(element)
            elif kind == "link_insert":
                anchor = _fragment(after)[0]
                phrase, href = anchor.text_content(), anchor.get("href", "")
                text = " ".join(element.text_content().split())
                at = text.lower().find(phrase.lower())
                if at < 0:
                    placed, reason = False, "anchor phrase not found in the element"
                else:
                    start, end = max(0, at - 90), min(len(text), at + len(phrase) + 90)
                    lead, tail = ("…" if start else ""), ("…" if end < len(text) else "")
                    before = f"{lead}{text[start:end]}{tail}"
                    after = f'{lead}{text[start:at]}<a href="{href}">{text[at:at + len(phrase)]}</a>{text[at + len(phrase):end]}{tail}'
            else:
                working = copy.deepcopy(doc)
                target, _ = _locate(working, patch.get("locator"))
                before = _short(element)
                error = _apply_one(working, patch, target)
                if error:
                    placed, reason = False, error
                else:
                    after = "" if kind == "element_remove" else _short(target)

    left, right = segments(before, after)
    return {"language": language, "before": before, "after": after, "placed": placed, "reason": reason,
            "before_segments": left, "after_segments": right}


def page_snippets(page_html: str | None, patches: list[dict]) -> dict[str, dict]:
    """Snippets for every patch on one page, keyed by patch key. Each is computed on a fresh parse."""
    out = {}
    for patch in patches:
        try:
            out[patch["key"]] = snippet(page_html, patch)
        except (etree.ParserError, ValueError, IndexError) as exc:  # malformed markup in a patch
            out[patch["key"]] = {"language": "html", "before": patch.get("before"), "after": patch["after"],
                                 "placed": False, "reason": f"Couldn't read the change: {exc}",
                                 "before_segments": [], "after_segments": []}
    return out
