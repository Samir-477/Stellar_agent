"""Grounding checks: is a quoted string really present in the source text?

Used to reject LLM output that cites text which isn't on the page (the main
defence against hallucinated facts and evidence).
"""

from __future__ import annotations

import re
import unicodedata

_QUOTES = str.maketrans({"‘": "'", "’": "'", "“": '"', "”": '"', "–": "-", "—": "-", " ": " "})
_WS = re.compile(r"\s+")


def normalize(text: str) -> str:
    text = unicodedata.normalize("NFKC", text or "").translate(_QUOTES).lower()
    return _WS.sub(" ", text).strip()


def quote_in_text(quote: str, text: str) -> bool:
    """True if the quote appears verbatim (after whitespace/quote/case normalisation)."""
    q = normalize(quote).strip(" .,;:\"'")
    return len(q) >= 3 and q in normalize(text)


_NUMBER = re.compile(r"\d+(?:[.,]\d+)?")
_STOP = {"the", "a", "an", "and", "or", "of", "to", "in", "on", "at", "for", "with", "from", "by", "is", "are",
         "be", "as", "its", "it", "this", "that", "per", "plus", "only", "approximately", "about", "away", "all"}


def value_supported(value: str, quote: str, *, min_word_share: float = 0.5) -> bool:
    """True if the quote actually backs the value: every number in the value appears in
    the quote, and at least `min_word_share` of the value's meaningful words do too."""
    v, q = normalize(value), normalize(quote)
    if any(num not in q for num in _NUMBER.findall(v)):
        return False
    words = [w for w in re.findall(r"[a-z\u00c0-\u024f]+", v) if w not in _STOP and len(w) > 2]
    if not words:
        return True
    q_words = set(re.findall(r"[a-z\u00c0-\u024f]+", q))
    stems = {w[:5] for w in q_words}
    hits = sum(1 for w in words if w in q_words or w[:5] in stems)
    return hits / len(words) >= min_word_share
