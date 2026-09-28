"""Page-content helpers shared by agents: separating a page's own content from
template text that repeats across the site (booking widgets, promo banners,
shared modals), and comparing pages by their own content only."""

from __future__ import annotations

import re
from collections import Counter
from math import ceil

from engine.lib.locators import text_hash


def template_blocks(models: list[dict], *, min_pages: int = 3, min_share: float = 0.25) -> set[str]:
    """Hashes of passages repeated verbatim on many sampled pages: site template, not page content.

    Widgets often appear on only some page types (e.g. a booking widget on 11 of 25
    pages), so the share threshold is a quarter of the sample. City-swapped doorway
    pages are still compared because swapping the city changes each passage's text.
    """
    counts: Counter[str] = Counter()
    for model in models:
        counts.update({text_hash(p["text"]) for p in model.get("passages", [])})
    threshold = max(min_pages, ceil(min_share * len(models)))
    return {h for h, count in counts.items() if count >= threshold}


def template_headings(models: list[dict], *, min_pages: int = 3, min_share: float = 0.25) -> set[str]:
    """Normalised heading texts repeated across many sampled pages (widget and menu headings)."""
    from engine.lib.grounding import normalize
    counts: Counter[str] = Counter()
    for model in models:
        counts.update({normalize(b["text"]) for b in model.get("outline", []) if b["type"] == "heading"})
    threshold = max(min_pages, ceil(min_share * len(models)))
    return {h for h, count in counts.items() if count >= threshold}


def own_text(model: dict, template: set[str]) -> str:
    """The page's own passages, with site-template passages removed."""
    return " ".join(p["text"] for p in model.get("passages", []) if text_hash(p["text"]) not in template)


def shingles(text: str, size: int = 3) -> set[str]:
    words = text.lower().split()
    return {" ".join(words[i:i + size]) for i in range(max(1, len(words) - size + 1))} if words else set()


def jaccard(a: set[str], b: set[str]) -> float:
    return len(a & b) / len(a | b) if a and b else 0.0


_INTERROGATIVES = {"what", "how", "why", "when", "where", "which", "who", "is", "are", "can", "do", "does",
                   "should", "will"}
_SECOND = {"is", "are", "do", "does", "can", "should", "will", "to", "much", "many", "long", "far", "old", "the",
           "a", "an", "i", "we", "you", "it"}


def is_question(text: str) -> bool:
    """A heading phrased as a question: ends with '?', or reads like one ("How to book a room",
    "What is the check-in time"). Labels such as "What's New" are not questions."""
    t = text.strip().lower()
    if t.endswith("?"):
        return True
    words = t.replace("'", " ").split()
    return len(words) >= 4 and words[0] in _INTERROGATIVES and words[1] in _SECOND


PLACEHOLDER = re.compile(r"\{\{.*?\}\}")
MASK = "[…]"


def mask_placeholders(text: str) -> str:
    """Client-side template placeholders ({{price}}) → "[…]": the value isn't in the page HTML."""
    return PLACEHOLDER.sub(MASK, text)


def sections(model: dict, *, template: set[str] | None = None, masked: bool = False) -> list[dict]:
    """Heading + the passages under it, in page order (from the parser's outline).
    Template passages (site-wide widgets) are left out. Passages with client-side placeholders
    ({{...}}) are dropped, or kept with the placeholders masked as "[…]" when `masked`."""
    out: list[dict] = []
    current = None
    for block in model.get("outline", []):
        if block["type"] == "heading":
            heading = mask_placeholders(block["text"]) if masked else block["text"]
            current = {"heading": heading, "level": block["level"], "locator": block["locator"], "passages": []}
            out.append(current)
        elif current is not None and ("{{" not in block["text"] or masked):
            if template and text_hash(block["text"]) in template:
                continue
            current["passages"].append({**block, "text": mask_placeholders(block["text"])} if masked else block)
    # Pages often repeat a section (e.g. separate mobile and desktop markup): keep the first copy.
    unique, seen = [], set()
    for section in out:
        signature = text_hash(section["heading"] + " " + " ".join(b["text"] for b in section["passages"]))
        body_signature = text_hash(" ".join(b["text"] for b in section["passages"]))
        if signature in seen or (section["passages"] and body_signature in seen):
            continue
        seen.update({signature, body_signature} if section["passages"] else {signature})
        unique.append(section)
    return unique


def sampled_text(model: dict, template: set[str], words: int = 450, min_section_words: int = 30) -> str:
    """The page's own sections ("heading: text"), template text removed, about `words` words sampled
    from the top of the page to the bottom (testimonials and FAQs often sit last): each kept section
    gives its opening words; on long pages, sections are picked at even intervals."""
    secs = [(s["heading"], " ".join(b["text"] for b in s["passages"]).split())
            for s in sections(model, template=template) if s["passages"]]
    if not secs:
        return ""
    keep = max(1, min(len(secs), words // min_section_words))
    if keep < len(secs):
        step = (len(secs) - 1) / max(keep - 1, 1)
        secs = [secs[round(i * step)] for i in range(keep)]
    share = words // len(secs)
    return " ".join(f"{heading}: {' '.join(body[:share])}" for heading, body in secs)
