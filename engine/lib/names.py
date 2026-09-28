"""Business-name matching shared by collectors and agents: does a listing title, a schema name or an
AI answer refer to this business?"""

from __future__ import annotations

import re

_GENERIC = {"the", "hotel", "hotels", "resort", "resorts", "limited", "ltd", "pvt", "private", "india", "and", "of",
            "holiday", "holidays", "group", "company", "services"}


def name_words(name: str) -> set[str]:
    return {w for w in re.findall(r"[a-z0-9]+", name.lower()) if w not in _GENERIC and len(w) > 2}


def names_match(name: str, text: str | None, share: float = 0.6) -> bool:
    """Most of the name's distinctive words appear in the text ("Sterling Regalia Agra" in a listing title)."""
    words = name_words(name)
    found = set(re.findall(r"[a-z0-9]+", (text or "").lower()))
    return bool(words) and len(words & found) / len(words) >= share
