"""C11 Performance Capture: PageSpeed Insights (mobile) for up to five template-representative pages:
Chrome UX Report field data (75th percentile, real users) and Lighthouse lab data, the LCP element
and its breakdown, and the audits S2 needs (images, render-blocking, JavaScript, viewport).

The full response is stored as a blob; the evidence payload is a compact summary. Lighthouse 13
renamed many audits to "insights"; the summary reads both names.
"""

from __future__ import annotations

import json
from urllib.parse import urlsplit

from engine.collectors.base import Collector
from engine.collectors.common import parsed_models
from engine.context import CollectorContext, WorkUnit
from engine.integrations.pagespeed import PageSpeedError
from engine.lib.locators import text_hash
from engine.schemas import EvidenceType

LAB = {"lcp_ms": "largest-contentful-paint", "cls": "cumulative-layout-shift", "tbt_ms": "total-blocking-time",
       "fcp_ms": "first-contentful-paint", "si_ms": "speed-index", "ttfb_ms": "server-response-time"}
# Summary key → Lighthouse audit ids (newest first).
AUDITS = {
    "images": ("image-delivery-insight", "uses-optimized-images", "modern-image-formats", "uses-responsive-images"),
    "offscreen_images": ("offscreen-images",),
    "unsized_images": ("unsized-images",),
    "render_blocking": ("render-blocking-insight", "render-blocking-resources"),
    "unused_js": ("unused-javascript",),
    "unused_css": ("unused-css-rules",),
    "third_parties": ("third-parties-insight", "third-party-summary"),
    "viewport": ("viewport-insight", "viewport"),
    "font_display": ("font-display-insight", "font-display"),
    "dom_size": ("dom-size-insight", "dom-size"),
    "layout_shifts": ("cls-culprits-insight", "layout-shifts", "layout-shift-elements"),
}


def _items(audit: dict, limit: int = 4) -> list[dict]:
    """The first rows of an audit's table, reduced to what a finding can show."""
    rows = []
    for item in ((audit.get("details") or {}).get("items") or [])[:limit]:
        if not isinstance(item, dict):
            continue
        node = item.get("node") or {}
        row = {k: item[k] for k in ("url", "wastedBytes", "wastedMs", "totalBytes", "entity", "transferSize")
               if item.get(k) is not None}
        if node.get("snippet") or item.get("snippet"):
            row["snippet"] = (node.get("snippet") or item.get("snippet"))[:240]
        if row:
            rows.append(row)
    return rows


def summarize(data: dict) -> dict:
    lh = data.get("lighthouseResult") or {}
    audits = lh.get("audits") or {}

    def field(experience: dict) -> dict:
        return {name: {"p75": m.get("percentile"), "category": m.get("category")}
                for name, m in (experience.get("metrics") or {}).items()}

    page_exp = data.get("loadingExperience") or {}
    summary = {
        "lighthouse_version": lh.get("lighthouseVersion"),
        "score": ((lh.get("categories") or {}).get("performance") or {}).get("score"),
        "lab": {k: (audits.get(a) or {}).get("numericValue") for k, a in LAB.items()},
        # PageSpeed falls back to origin data when the page has too little traffic.
        "field": {} if page_exp.get("origin_fallback") else field(page_exp),
        "origin_field": field(data.get("originLoadingExperience") or {}),
        "audits": {},
    }
    for key, ids in AUDITS.items():
        audit = next((audits[i] for i in ids if i in audits), None)
        if audit is not None:
            summary["audits"][key] = {"id": next(i for i in ids if i in audits), "title": audit.get("title"),
                                      "score": audit.get("score"), "display": audit.get("displayValue"),
                                      "savings": audit.get("metricSavings"), "items": _items(audit)}
    breakdown = (audits.get("lcp-breakdown-insight") or {}).get("details") or {}
    for part in breakdown.get("items") or []:
        if isinstance(part, dict) and part.get("type") == "node":
            summary["lcp_element"] = (part.get("snippet") or "")[:300]
        elif isinstance(part, dict) and isinstance(part.get("items"), list):
            summary["lcp_parts"] = {p["subpart"]: round(p.get("duration") or 0) for p in part["items"]
                                    if isinstance(p, dict) and p.get("subpart")}
    discovery = (audits.get("lcp-discovery-insight") or {}).get("details") or {}
    for part in discovery.get("items") or []:
        if isinstance(part, dict) and part.get("type") == "checklist":
            summary["lcp_checks"] = {k: v.get("value") for k, v in (part.get("items") or {}).items()}
        elif isinstance(part, dict) and part.get("snippet") and "lcp_element" not in summary:
            summary["lcp_element"] = part["snippet"][:300]
    return summary


def pick_urls(models: list[dict], cap: int) -> list[str]:
    """The entry page, the homepage, then one page per other template linked from the homepage menu."""
    if not models:
        return []
    chosen, templates = [models[0]["url"]], {models[0].get("template_id")}
    home = next((m for m in models if urlsplit(m["url"]).path in ("", "/")), None)
    by_url = {m["url"]: m for m in models}
    candidates = [home] if home else []
    if home:
        candidates += [by_url[l["href"]] for l in home.get("links", []) if l.get("in_nav") and l["href"] in by_url]
    candidates += models
    for model in candidates:
        if len(chosen) >= cap:
            break
        if model["url"] not in chosen and (model is home or model.get("template_id") not in templates):
            chosen.append(model["url"])
            templates.add(model.get("template_id"))
    return chosen


class PerformanceCapture(Collector):
    id = "C11"
    name = "Performance Capture"
    produces = frozenset({EvidenceType.PERFORMANCE})
    requires = frozenset({EvidenceType.PAGES_PARSED})

    def plan(self, ctx: CollectorContext) -> list[WorkUnit]:
        # One unit per URL: a Lighthouse run can take 40 s, and a retry mustn't repeat finished ones.
        return [WorkUnit("measure", {"url": u})
                for u in pick_urls(parsed_models(ctx), ctx.settings.pagespeed_urls_per_run)]

    def run_unit(self, ctx: CollectorContext, unit: WorkUnit) -> list[WorkUnit]:
        url = unit.params["url"]
        if any(e.payload.get("url") == url for e in ctx.snapshot.evidence(EvidenceType.PERFORMANCE)):
            return []  # already measured in an earlier attempt
        if ctx.pagespeed is None:
            ctx.snapshot.add_evidence(self.id, EvidenceType.PERFORMANCE, {"url": url, "error": "no PageSpeed key"})
            return []
        try:
            data = ctx.pagespeed.run(url)
        except PageSpeedError as exc:
            if "HTTP 4" not in str(exc):
                raise  # timeouts and server errors: let the task queue retry
            ctx.snapshot.add_evidence(self.id, EvidenceType.PERFORMANCE, {"url": url, "error": str(exc)})
            return []
        key = ctx.snapshot.put_blob(f"snapshots/{ctx.snapshot.snapshot_id}/performance/{text_hash(url)}.json",
                                    json.dumps(data))
        ctx.snapshot.add_evidence(self.id, EvidenceType.PERFORMANCE,
                                  {"url": url, "strategy": "mobile", **summarize(data)}, blob_key=key,
                                  source_label="observed")
        return []
