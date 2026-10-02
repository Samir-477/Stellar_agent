"""S2 Page Experience: Core Web Vitals and the page-weight issues behind them, for up to five
template-representative pages measured by PageSpeed Insights (C11, mobile).

Chrome UX Report field data (75th percentile of real users) is used first, then origin-level field
data, then Lighthouse lab data; each finding says which, and anything but page-level field data is
`likely`. Image, mobile and script checks read the Lighthouse audits and the page's viewport tag.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from urllib.parse import urljoin

from engine.agents.base import Agent
from engine.agents.common import PageView, entry_page, load_pages, norm
from engine.context import AgentContext, WorkUnit
from engine.schemas import (
    AgentResult,
    CheckSpec,
    CheckStatus as St,
    Confidence,
    Coverage,
    Effort,
    EvidenceRef,
    EvidenceType,
    Locator,
    Patch,
    PatchType,
    Pillar,
    Severity as Sev,
)

# check id → (label, field metric, field scale, lab key, (good, poor) thresholds, lab thresholds, unit)
VITALS = {
    "S2.01": ("LCP", "LARGEST_CONTENTFUL_PAINT_MS", 1, "lcp_ms", (2500, 4000), (2500, 4000), "ms"),
    "S2.02": ("INP", "INTERACTION_TO_NEXT_PAINT", 1, "tbt_ms", (200, 500), (200, 600), "ms"),
    "S2.03": ("CLS", "CUMULATIVE_LAYOUT_SHIFT_SCORE", 100, "cls", (0.1, 0.25), (0.1, 0.25), ""),
    "S2.04": ("TTFB", "EXPERIMENTAL_TIME_TO_FIRST_BYTE", 1, "ttfb_ms", (800, 1800), (800, 1800), "ms"),
}
HERO_BYTES = 200_000
LCP_PARTS = {"timeToFirstByte": "server response", "resourceLoadDelay": "load delay (image found late)",
             "resourceLoadDuration": "download", "elementRenderDelay": "render delay"}


@dataclass
class Measure:
    url: str
    value: float
    source: str  # page field data | origin field data | lab
    status: St

    def text(self, label: str, unit: str) -> str:
        shown = f"{self.value / 1000:.1f} s" if unit == "ms" and self.value >= 1000 else \
            f"{self.value:.0f} ms" if unit == "ms" else f"{self.value:.2f}"
        return f"{label} {shown} ({self.source})"


def grade(value: float, good: float, poor: float) -> St:
    return St.PASS if value <= good else St.WARN if value <= poor else St.FAIL


class PageExperience(Agent):
    id = "S2"
    name = "Page Experience"
    pillar = Pillar.SEO
    requires = frozenset({EvidenceType.PERFORMANCE, EvidenceType.PAGES_PARSED})
    signature_columns = ["Page", "LCP", "INP / TBT", "CLS", "TTFB", "Data source"]
    checks = [
        CheckSpec(id="S2.01", title="LCP", default_severity=Sev.HIGH, method="P"),
        CheckSpec(id="S2.02", title="INP (field) / TBT (lab proxy)", default_severity=Sev.HIGH, method="P"),
        CheckSpec(id="S2.03", title="CLS", default_severity=Sev.MEDIUM, method="P"),
        CheckSpec(id="S2.04", title="TTFB", default_severity=Sev.MEDIUM, method="P"),
        CheckSpec(id="S2.05", title="LCP subpart diagnosis", default_severity=Sev.LOW, method="P",
                  counts_toward_readiness=False),  # context, not a pass/fail measure
        CheckSpec(id="S2.06", title="Image hygiene", default_severity=Sev.MEDIUM, method="D"),
        CheckSpec(id="S2.07", title="Mobile basics", default_severity=Sev.MEDIUM, method="D+P"),
        CheckSpec(id="S2.08", title="Render-blocking and JS weight", default_severity=Sev.LOW, method="P"),
    ]

    def run_unit(self, ctx: AgentContext, unit: WorkUnit) -> AgentResult:
        runs = [e.payload for e in ctx.snapshot.evidence(EvidenceType.PERFORMANCE)]
        measured = [r for r in runs if not r.get("error")]
        coverage = Coverage(examined={"pages_measured": len(measured)})
        coverage.skipped += [f"{r['url']}: {r['error']}" for r in runs if r.get("error")]
        coverage.limits.append("Mobile. Field data is the 75th percentile of real Chrome users over 28 days; lab "
                               "data is one simulated slow-phone load.")
        if not measured:
            return AgentResult(findings=[self.finding(c.id, St.UNVERIFIABLE, "No PageSpeed measurements")
                                         for c in self.checks], coverage=coverage)
        pages = [p for p in load_pages(ctx) if p.is_html]
        entry = entry_page(pages, ctx.client.primary_url)
        entry_url = norm(entry.url) if entry else None
        measures = {cid: [m for r in measured if (m := self._measure(cid, r))] for cid in VITALS}
        findings = [self._vital(cid, measures[cid], entry_url) for cid in VITALS]
        findings += [self._lcp_parts(measured), self._images(measured), self._mobile(measured, pages),
                     self._scripts(measured)]
        patches = self._image_hints(measured, pages, findings)
        rows = []
        for r in measured:
            cells = {cid: next((m for m in measures[cid] if m.url == r["url"]), None) for cid in VITALS}
            rows.append([r["url"]] + [m.text(VITALS[cid][0], VITALS[cid][6]).rsplit(" (", 1)[0] if m else "—"
                                      for cid, m in cells.items()]
                        + [", ".join(sorted({m.source for m in cells.values() if m}))])
        return AgentResult(findings=findings, patches=patches, coverage=coverage,
                           signature_table={"columns": self.signature_columns, "rows": rows})

    # ------------------------------------------------------------ prepared image hints

    def _image_hints(self, measured: list[dict], pages: list[PageView], findings: list) -> list[Patch]:
        """Prepared changes (approval required) on the image elements the measurements name: the main (LCP)
        image gets a real src when it is only in data-src, and fetchpriority=high; images PageSpeed reports as
        off-screen get loading=lazy. Each is attached to the finding about that page (S2.06, else S2.01)."""
        by_url = {norm(p.url): p for p in pages}
        open_findings = {f.check_id: f for f in findings if f.status in (St.FAIL, St.WARN)}
        patches: list[Patch] = []
        for run in measured:
            page = by_url.get(norm(run["url"]))
            if page is None:
                continue
            element, checks = run.get("lcp_element") or "", run.get("lcp_checks") or {}
            # A lazy image's real address is in data-src; its src is often a placeholder.
            hint = re.search(r'data-src="([^"]+)"', element) or re.search(r'\ssrc="([^"]+)"', element)
            image = _image_on(page, hint.group(1)) if "<img" in element and hint else None
            page_patches = []
            if image and image.get("locator"):
                if image.get("lazy") and image.get("src"):
                    page_patches.append(_attribute(self.id, page, image, "src", image["src"], "lcp-src",
                                                   "The main image is only in data-src, so the browser finds it late; "
                                                   "giving it a real src lets it start loading at once (also remove the "
                                                   "lazy-loading class so a script doesn't swap it back)."))
                if checks.get("priorityHinted") is False:
                    page_patches.append(_attribute(self.id, page, image, "fetchpriority", "high", "lcp-priority",
                                                   "The main image has no priority hint; fetchpriority=high tells the "
                                                   "browser to load it before other images."))
            for item in ((run.get("audits") or {}).get("offscreen_images") or {}).get("items", [])[:5]:
                offscreen = _image_on(page, item.get("url") or "")
                if offscreen and offscreen.get("locator") and not offscreen.get("lazy") and offscreen is not image:
                    page_patches.append(_attribute(self.id, page, offscreen, "loading", "lazy",
                                                   f"offscreen-{len(page_patches)}",
                                                   "PageSpeed reports this image as off-screen when the page loads; "
                                                   "loading=lazy defers it until the visitor scrolls near it."))
            if not page_patches:
                continue
            target = next((open_findings[c] for c in ("S2.06", "S2.01") if c in open_findings
                           and norm(run["url"]) in {norm(u) for u in open_findings[c].scope.pages}), None)
            if target is None:
                continue
            target.patch_keys += [patch.key for patch in page_patches]
            patches += page_patches
        return patches

    # ------------------------------------------------------------ S2.01–S2.04

    @staticmethod
    def _measure(check_id: str, run: dict) -> Measure | None:
        label, metric, scale, lab_key, field_limits, lab_limits, _ = VITALS[check_id]
        for source, data in (("page field data", run.get("field") or {}), ("origin field data",
                                                                           run.get("origin_field") or {})):
            p75 = (data.get(metric) or {}).get("p75")
            if p75 is not None:
                value = p75 / scale
                return Measure(run["url"], value, source, grade(value, *field_limits))
        lab = (run.get("lab") or {}).get(lab_key)
        if lab is None:
            return None
        return Measure(run["url"], lab, "lab" if check_id != "S2.02" else "lab TBT", grade(lab, *lab_limits))

    def _vital(self, check_id: str, measures: list[Measure], entry_url: str | None):
        label, _, _, _, (good, poor), _, unit = VITALS[check_id]
        if not measures:
            return self.finding(check_id, St.UNVERIFIABLE, f"No {label} data")
        order = {St.FAIL: 0, St.WARN: 1, St.PASS: 2}
        measures.sort(key=lambda m: order[m.status])
        worst = measures[0].status
        confidence = Confidence.CONFIRMED if all(m.source == "page field data" for m in measures) \
            else Confidence.LIKELY
        evidence = [EvidenceRef(type="metric", url=m.url, excerpt=m.text(label, unit)) for m in measures[:5]]
        if worst == St.PASS:
            return self.finding(check_id, St.PASS, f"{label} is good on all {len(measures)} measured page(s)",
                                confidence=confidence, evidence=evidence)
        bad = [m for m in measures if m.status == worst]
        limit = f"{good / 1000:g} s" if unit == "ms" and good >= 1000 else f"{good:g}{' ms' if unit else ''}"
        return self.finding(
            check_id, worst, f"{label} {'poor' if worst == St.FAIL else 'needs improvement'} on {len(bad)} of "
                             f"{len(measures)} measured page(s)", pages=[m.url for m in bad],
            confidence=confidence, key_page=any(norm(m.url) == entry_url for m in bad), evidence=evidence,
            impact=f"{label} is a Core Web Vital: slow or unstable pages lose visitors and rank lower on mobile.",
            fix={"S2.01": "Make the main image or text appear sooner: put the hero image in the HTML (not "
                          "lazy-loaded), give it fetchpriority=high, compress it and defer render-blocking scripts.",
                 "S2.02": "Cut main-thread work: defer or remove heavy third-party scripts and split long tasks.",
                 "S2.03": "Reserve space for images, banners and widgets (width/height or aspect-ratio) so the "
                          "layout doesn't jump.",
                 "S2.04": "Speed up the server response: caching, a CDN and fewer redirects."}[check_id],
            verification=f"PageSpeed Insights: {label} at or under {limit} at the 75th percentile.", effort=Effort.M)

    # ------------------------------------------------------------ S2.05–S2.08

    def _lcp_parts(self, measured: list[dict]):
        with_parts = [r for r in measured if r.get("lcp_parts")]
        if not with_parts:
            return self.finding("S2.05", St.NOT_APPLICABLE, "No LCP breakdown in the measurements")
        evidence = []
        for r in with_parts[:3]:
            parts = r["lcp_parts"]
            biggest = max(parts, key=parts.get)
            evidence.append(EvidenceRef(type="metric", url=r["url"], excerpt=(
                "; ".join(f"{LCP_PARTS.get(k, k)} {v / 1000:.1f} s" for k, v in parts.items())
                + f" — biggest: {LCP_PARTS.get(biggest, biggest)}")[:400]))
        return self.finding("S2.05", St.PASS, "LCP breakdown recorded (context for S2.01)", evidence=evidence)

    def _images(self, measured: list[dict]):
        hidden, heavy, issues = [], [], []
        for r in measured:
            checks, element = r.get("lcp_checks") or {}, r.get("lcp_element") or ""
            is_image = "<img" in element
            if is_image and (checks.get("requestDiscoverable") is False or checks.get("eagerlyLoaded") is False
                             or re.search(r'loading="lazy"', element)):
                hidden.append((r, element))
            src = re.search(r'src="([^"]+)"', element)
            for item in ((r.get("audits") or {}).get("images") or {}).get("items", []):
                if src and src.group(1).split("?")[0] in (item.get("url") or item.get("snippet") or "") \
                        and (item.get("totalBytes") or 0) > HERO_BYTES:
                    heavy.append((r, item))
            for key in ("unsized_images", "images"):
                audit = (r.get("audits") or {}).get(key) or {}
                if audit.get("score") is not None and audit["score"] < 0.9:
                    issues.append((r, audit))
        if hidden or heavy:
            evidence = [EvidenceRef(type="html_excerpt", url=r["url"],
                                    excerpt=f"LCP image found late or lazy-loaded: {el[:200]}") for r, el in hidden[:3]]
            evidence += [EvidenceRef(type="metric", url=r["url"],
                                     excerpt=f"LCP image {i['totalBytes'] // 1024} KB") for r, i in heavy[:2]]
            return self.finding(
                "S2.06", St.FAIL, f"The main (LCP) image is lazy-loaded or not in the HTML on {len(hidden)} page(s)"
                if hidden else f"The main (LCP) image is over {HERO_BYTES // 1000} KB on {len(heavy)} page(s)",
                pages=sorted({r["url"] for r, _ in hidden + heavy}), evidence=evidence,
                impact="The browser can't start downloading the biggest image until scripts run, which delays LCP.",
                fix="Put the hero image in the HTML with a real src, no lazy-loading, fetchpriority=high, and a "
                    "compressed WebP/AVIF version.", verification="PageSpeed: LCP request discoverable and eager.",
                effort=Effort.S)
        if issues:
            return self.finding(
                "S2.06", St.WARN, f"{len(issues)} image issue(s): " + ", ".join(sorted({a['title'] or '' for _, a in
                                                                                     issues}))[:200],
                pages=sorted({r["url"] for r, _ in issues}),
                evidence=[EvidenceRef(type="metric", url=r["url"], excerpt=f"{a['title']}: {a.get('display') or ''}")
                          for r, a in issues[:4]],
                impact="Unsized or oversized images shift the layout and waste mobile data.",
                fix="Set width and height on images, serve WebP/AVIF at the displayed size.",
                verification="PageSpeed image audits pass.", effort=Effort.S)
        return self.finding("S2.06", St.PASS, "Images are sized, compressed and the LCP image loads early",
                            evidence=[EvidenceRef(type="metric", excerpt=f"{len(measured)} page(s) measured")])

    def _mobile(self, measured: list[dict], pages):
        by_url = {norm(p.url): p for p in pages}
        missing, no_zoom = [], []
        for r in measured:
            page = by_url.get(norm(r["url"]))
            viewport = ((page.model.get("meta") or {}).get("viewport") if page else None)
            if page and not viewport:
                missing.append(r["url"])
            elif viewport and re.search(r"user-scalable\s*=\s*(no|0)|maximum-scale\s*=\s*1(\.0)?\b", viewport):
                no_zoom.append((r["url"], viewport))
        if missing:
            return self.finding("S2.07", St.FAIL, f"{len(missing)} measured page(s) have no viewport meta tag",
                                pages=missing, evidence=[EvidenceRef(type="html_excerpt", url=u,
                                                                     excerpt="no <meta name=\"viewport\">")
                                                         for u in missing[:3]],
                                impact="Without a viewport tag, phones render the desktop layout shrunk.",
                                fix="Add <meta name=\"viewport\" content=\"width=device-width, initial-scale=1\">.",
                                verification="Viewport tag present.", effort=Effort.S)
        if no_zoom:
            return self.finding(
                "S2.07", St.WARN, f"{len(no_zoom)} measured page(s) stop visitors zooming",
                pages=[u for u, _ in no_zoom],
                evidence=[EvidenceRef(type="html_excerpt", url=u, excerpt=f"viewport: {v}") for u, v in no_zoom[:3]],
                impact="Disabling pinch-zoom makes text unreadable for many visitors (an accessibility failure).",
                fix="Remove user-scalable=no and maximum-scale=1 from the viewport tag.",
                verification="Viewport allows zoom.", effort=Effort.S)
        return self.finding("S2.07", St.PASS, "Measured pages have a mobile viewport that allows zoom",
                            evidence=[EvidenceRef(type="html_excerpt", excerpt=f"{len(measured)} page(s) checked")])

    def _scripts(self, measured: list[dict]):
        scored = []
        for r in measured:
            for key in ("render_blocking", "unused_js"):
                audit = (r.get("audits") or {}).get(key)
                if audit and audit.get("score") is not None:
                    scored.append((r, audit))
        if not scored:
            return self.finding("S2.08", St.UNVERIFIABLE, "No script audits in the measurements")
        worst = min(a["score"] for _, a in scored)
        evidence = [EvidenceRef(type="metric", url=r["url"],
                                excerpt=f"{a['title']}: {a.get('display') or ''}"
                                        + (f" (e.g. {a['items'][0].get('url')})" if a.get("items") else ""))
                    for r, a in sorted(scored, key=lambda x: x[1]["score"])[:4]]
        if worst >= 0.9:
            return self.finding("S2.08", St.PASS, "Scripts and styles stay within Lighthouse budgets",
                                evidence=evidence)
        return self.finding(
            "S2.08", St.FAIL if worst < 0.5 else St.WARN,
            "Render-blocking and unused scripts are " + ("severe (Lighthouse: poor)" if worst < 0.5
                                                          else "above Lighthouse budgets"),
            pages=sorted({r["url"] for r, a in scored if a["score"] < 0.9}), evidence=evidence,
            impact="Scripts that block rendering or are never used delay everything the visitor sees.",
            fix="Load third-party widgets after the page renders (defer/async), and drop unused JavaScript and CSS.",
            verification="PageSpeed render-blocking and unused-JavaScript audits pass.", effort=Effort.M)


def _image_on(page: PageView, url_hint: str) -> dict | None:
    """The parsed image a measurement names. The hint can be scheme-relative or cut short ("…"), so images are
    compared by address without scheme or query, and a cut-short hint matches the start of the address."""
    def key(url: str) -> str:
        return re.sub(r"^https?:", "", urljoin(page.url, url)).split("?")[0]
    hint = key(url_hint.split("…")[0])
    if len(hint) < 12:
        return None
    return next((img for img in page.model.get("images", []) if img.get("src") and key(img["src"]).startswith(hint)), None)


def _attribute(agent_id: str, page: PageView, image: dict, name: str, value: str, slug: str, why: str) -> Patch:
    return Patch(key=f"S2:{slug}:{page.record.id}", agent_id=agent_id, page_url=page.url, type=PatchType.ATTRIBUTE_SET,
                 locator=Locator(**image["locator"]), after=f'{name}="{value}"', rationale=why, approval="required",
                 client_visible_note="Helps the page show its main content sooner.")
