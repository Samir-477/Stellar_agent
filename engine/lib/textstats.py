"""Deterministic text measures shared by agents: sentence length, repeated phrases (keyword
stuffing) and time-sensitive mentions (outdated offers and years)."""

from __future__ import annotations

import re
from collections import Counter

_SENTENCE = re.compile(r"(?<=[.!?])\s+(?=[A-Z0-9“\"'(])")
_WORD = re.compile(r"[a-z0-9]+(?:[-'][a-z0-9]+)*")
_STOP = {"the", "a", "an", "and", "or", "of", "to", "in", "on", "at", "for", "with", "from", "by", "is", "are", "be",
         "as", "it", "this", "that", "our", "your", "you", "we", "us", "its", "their", "all", "more", "any", "can",
         "will", "has", "have", "was", "were", "not", "no", "so", "if", "into", "up", "out", "per", "also", "just"}
TIME_SENSITIVE = re.compile(r"\b(valid|offer|offers|till|until|upto|up to|ends?|expir\w*|last date|book by|stay by|"
                            r"travel by|deadline|sale|discount|season|diwali|christmas|new year|summer|winter|"
                            r"monsoon|holi|puja|festive|rates?|prices?)\b", re.I)
YEAR = re.compile(r"\b(20\d\d)\b")
MONTH = re.compile(r"\b(jan|feb|mar|apr|may|jun|jul|aug|sep|sept|oct|nov|dec)[a-z]*\b", re.I)
PRICE = re.compile(r"(₹|\brs\.?|\binr)\s?\d|\d+\s?%\s?off\b", re.I)
OFFER = re.compile(r"\b(offer|discount|deal|save|% off|flat)\b", re.I)


def sentences(text: str) -> list[str]:
    return [s for s in _SENTENCE.split(text.strip()) if s.strip()]


def words(text: str) -> list[str]:
    return _WORD.findall(text.lower())


def repeated_phrases(text: str, *, exclude: set[str] = frozenset(), sizes=(2, 3)) -> list[tuple[str, int]]:
    """2–3 word phrases by frequency, counted within sentences, ignoring phrases that start or end
    with a stop word and phrases containing an excluded word (the business's own name repeats
    naturally)."""
    counts: Counter[str] = Counter()
    for sentence in sentences(text):
        tokens = words(sentence)
        for size in sizes:
            for i in range(len(tokens) - size + 1):
                gram = tokens[i:i + size]
                skip = (gram[0] in _STOP or gram[-1] in _STOP or any(w in exclude for w in gram)
                        or all(w.isdigit() for w in gram))
                if not skip:
                    counts[" ".join(gram)] += 1
    return counts.most_common()


def outdated_mentions(text: str, current_year: int) -> list[str]:
    """Sentences that are time-sensitive ("offer valid till March 2024", "Diwali 2023 rates") and
    name a past year. History ("Founded in 2014") isn't time-sensitive and isn't reported."""
    found = []
    for sentence in sentences(text):
        past = [y for y in YEAR.findall(sentence) if int(y) < current_year]
        if past and TIME_SENSITIVE.search(sentence):
            found.append(" ".join(sentence.split())[:240])
    return list(dict.fromkeys(found))


def undated_offer(text: str) -> bool:
    """An offer with a price or discount but no year or month anywhere in the passage."""
    return bool(OFFER.search(text) and PRICE.search(text) and not YEAR.search(text) and not MONTH.search(text))
