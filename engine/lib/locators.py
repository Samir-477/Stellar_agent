"""Stable element locators: CSS path + XPath + short text hash.

Patches target elements by CSS path first, XPath as fallback, and the text hash
confirms the right element before a change is applied (docs/spec/06).
"""

from __future__ import annotations

import hashlib
import re

from lxml.html import HtmlElement

from engine.schemas import Locator

_WS = re.compile(r"\s+")


def normalize_text(text: str) -> str:
    return _WS.sub(" ", text or "").strip()


def text_hash(text: str) -> str:
    return hashlib.sha1(normalize_text(text).lower().encode("utf-8")).hexdigest()[:12]


def css_path(el: HtmlElement) -> str:
    parts = []
    node = el
    while node is not None and isinstance(node.tag, str):
        parent = node.getparent()
        if node.get("id") and re.fullmatch(r"[A-Za-z][\w-]*", node.get("id")):
            parts.append(f"{node.tag}#{node.get('id')}")
            break
        if parent is None:
            parts.append(node.tag)
            break
        same = [sib for sib in parent if sib.tag == node.tag]
        parts.append(node.tag if len(same) == 1 else f"{node.tag}:nth-of-type({same.index(node) + 1})")
        node = parent
    return " > ".join(reversed(parts))


def locate(el: HtmlElement) -> Locator:
    return Locator(css=css_path(el), xpath=el.getroottree().getpath(el), text_hash=text_hash(el.text_content()))
