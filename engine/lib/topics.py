"""Fact topics: a small, archetype-agnostic lexicon that maps the "missing facts" different agents
report ("prices and rates", "taxes and fees shown with prices", "price") to one topic, so the
intelligence layer can see when several agents found the same gap."""

from __future__ import annotations

import re

TOPICS: dict[str, re.Pattern] = {name: re.compile(pattern, re.I) for name, pattern in {
    "prices": r"\b(prices?|pricing|tariffs?|rates?|fees?|charges?|costs?|taxes)\b",
    "reviews": r"\b(reviews?|ratings?|testimonials?)\b",
    "check-in and check-out times": r"\bcheck[- ]?(in|out)\b",
    "cancellation and refunds": r"\b(cancell?ations?|refunds?)\b",
    "address": r"\b(address|pin ?code)\b",
    "opening hours": r"\b(opening hours|business hours|working hours)\b",
    "eligibility": r"\beligib\w*",
    "documents required": r"\bdocuments?\b",
    "shipping and delivery": r"\b(shipping|delivery)\b",
    "returns": r"\breturns?\b",
    "amenities": r"\b(amenit\w+|facilit\w+)\b",
    "pet policy": r"\bpets?\b",
    "parking": r"\bparking\b",
}.items()}


def fact_topics(text: str) -> set[str]:
    return {name for name, pattern in TOPICS.items() if pattern.search(text or "")}
