"""PageSpeed Insights API v5 (free with an API key): Lighthouse lab data plus Chrome UX Report
field data for one URL. Mobile strategy by default: Google indexes mobile-first."""

from __future__ import annotations

import httpx

PSI_URL = "https://www.googleapis.com/pagespeedonline/v5/runPagespeed"


class PageSpeedError(RuntimeError):
    pass


class PageSpeedClient:
    def __init__(self, api_key: str, http: httpx.Client | None = None):
        self.api_key = api_key
        # Lighthouse runs take 10–40 s on Google's side.
        self.http = http or httpx.Client(timeout=httpx.Timeout(30.0, read=120.0))

    def run(self, url: str, *, strategy: str = "mobile") -> dict:
        if not self.api_key:
            raise PageSpeedError("PAGE_SPEED_API_KEY is not set")
        try:
            resp = self.http.get(PSI_URL, params={"url": url, "strategy": strategy, "category": "performance",
                                                  "key": self.api_key})
        except httpx.HTTPError as exc:
            raise PageSpeedError(f"pagespeed: {type(exc).__name__}") from exc
        if resp.status_code != 200:
            # Google's error text names the problem (quota, unreachable URL); it never echoes the key.
            raise PageSpeedError(f"pagespeed: HTTP {resp.status_code} {resp.text[:200]}")
        return resp.json()
