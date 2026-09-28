"""Search providers (docs/spec/09): Serper for bulk results, SerpAPI for Google AI Overview,
People Also Ask, snippets and the knowledge graph. Every call is counted against a budget;
when a budget is exhausted the call is refused (BudgetExhausted) instead of spending more.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable

import httpx

SERPER_BASE = "https://google.serper.dev"
SERPAPI_BASE = "https://serpapi.com/search.json"


class SearchError(RuntimeError):
    pass


class BudgetExhausted(SearchError):
    pass


@dataclass
class SearchBudget:
    limits: dict[str, int]  # provider → max calls for this run
    used: dict[str, int] = field(default_factory=dict)
    on_use: Callable[[str, int], None] | None = None  # persists usage (provider_usage table)

    def spend(self, provider: str, calls: int = 1) -> None:
        if self.used.get(provider, 0) + calls > self.limits.get(provider, 0):
            raise BudgetExhausted(f"{provider} budget for this run is used up ({self.limits.get(provider, 0)} calls)")
        self.used[provider] = self.used.get(provider, 0) + calls
        if self.on_use:
            self.on_use(provider, calls)


class SearchClient:
    def __init__(self, serper_key: str, serpapi_key: str, budget: SearchBudget, http: httpx.Client | None = None):
        self.serper_key, self.serpapi_key, self.budget = serper_key, serpapi_key, budget
        self.http = http or httpx.Client(timeout=httpx.Timeout(30.0, read=120.0))

    # -------------------------------------------------------------- Serper
    def _serper(self, endpoint: str, body: dict) -> dict:
        if not self.serper_key:
            raise SearchError("SERPER_API_KEY is not set")
        self.budget.spend("serper")
        try:
            resp = self.http.post(f"{SERPER_BASE}/{endpoint}", json=body,
                                  headers={"X-API-KEY": self.serper_key, "Content-Type": "application/json"})
        except httpx.HTTPError as exc:  # a timeout must fail this call only, never the whole task
            raise SearchError(f"serper {endpoint}: {type(exc).__name__}") from exc
        if resp.status_code != 200:
            raise SearchError(f"serper {endpoint}: HTTP {resp.status_code} {resp.text[:200]}")
        return resp.json()

    def organic(self, query: str, *, num: int = 10) -> dict:
        return self._serper("search", {"q": query, "gl": "in", "hl": "en", "num": num})

    def autocomplete(self, query: str) -> list[str]:
        data = self._serper("autocomplete", {"q": query, "gl": "in", "hl": "en"})
        return [s.get("value", "") for s in data.get("suggestions", []) if s.get("value")]

    def places(self, query: str) -> list[dict]:
        return self._serper("places", {"q": query, "gl": "in", "hl": "en"}).get("places", [])

    # ------------------------------------------------------------- SerpAPI
    def google_features(self, query: str) -> dict:
        """One Google results page from SerpAPI (India), plus the AI Overview follow-up if needed."""
        if not self.serpapi_key:
            raise SearchError("SERP_API_KEY is not set")
        self.budget.spend("serpapi")
        try:
            resp = self.http.get(SERPAPI_BASE, params={"engine": "google", "q": query, "gl": "in", "hl": "en",
                                                       "google_domain": "google.co.in", "location": "India",
                                                       "api_key": self.serpapi_key})
        except httpx.HTTPError as exc:
            raise SearchError(f"serpapi: {type(exc).__name__}") from exc
        if resp.status_code != 200:
            raise SearchError(f"serpapi: HTTP {resp.status_code} {resp.text[:200]}")
        data = resp.json()
        overview = data.get("ai_overview") or {}
        if overview.get("page_token") and not overview.get("text_blocks"):
            try:
                self.budget.spend("serpapi")
                follow = self.http.get(SERPAPI_BASE, params={"engine": "google_ai_overview",
                                                             "page_token": overview["page_token"],
                                                             "api_key": self.serpapi_key}).json()
                data["ai_overview"] = follow.get("ai_overview") or overview
            except BudgetExhausted:
                data["ai_overview_note"] = "AI Overview follow-up skipped: SerpAPI budget used up"
            except httpx.HTTPError as exc:
                data["ai_overview_note"] = f"AI Overview follow-up failed: {type(exc).__name__}"
        return data


def ai_overview_text(overview: dict) -> str:
    parts = []
    for block in overview.get("text_blocks", []) or []:
        if block.get("snippet"):
            parts.append(block["snippet"])
        for item in block.get("list", []) or []:
            parts.append(" ".join(str(item.get(k, "")) for k in ("title", "snippet") if item.get(k)))
    return "\n".join(p for p in parts if p)
