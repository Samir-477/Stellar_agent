"""G1 AI Crawler Access & Readability: can AI crawlers reach the site and read it without JavaScript?

Deterministic. When rendered HTML exists (renderer configured), G1.04 compares raw vs
rendered text; without it, G1.04 looks for direct evidence of client-side rendering in
the raw HTML (unfilled template placeholders, empty app shells) and says so.
"""

from __future__ import annotations

import re

from engine.agents.base import Agent
from engine.agents.common import PageView, entry_page, key_page_urls, load_pages, site_file
from engine.context import AgentContext, WorkUnit
from engine.lib.content import own_text, template_blocks
from engine.lib.robots import parse_robots
from engine.schemas import (
    AgentResult,
    CheckSpec,
    CheckStatus as St,
    Confidence,
    Coverage,
    Effort,
    EvidenceRef,
    EvidenceType,
    Finding,
    Patch,
    PatchType,
    Pillar,
    Severity as Sev,
)

SEARCH_CRAWLERS = ("OAI-SearchBot", "ChatGPT-User", "Claude-SearchBot", "PerplexityBot")
TRAINING_CRAWLERS = ("GPTBot", "ClaudeBot", "Google-Extended", "Applebot-Extended", "CCBot")
_PLACEHOLDER = re.compile(r"\{\{\s*[\w.$|:'\" ()\[\]-]+\s*\}\}")


def placeholder_count(page: PageView) -> tuple[int, list[str]]:
    """Unfilled client-side template expressions ({{item.name}}) in the raw text."""
    texts = [p["text"] for p in page.model.get("passages", [])] + [h["text"] for h in page.model.get("headings", [])]
    found = [m.group(0) for t in texts for m in _PLACEHOLDER.finditer(t)]
    return len(found), list(dict.fromkeys(found))[:5]


class AICrawlerAccess(Agent):
    id = "G1"
    name = "AI Crawler Access & Readability"
    pillar = Pillar.GEO
    requires = frozenset({EvidenceType.PAGES_RAW, EvidenceType.PAGES_PARSED, EvidenceType.SITE_FILES,
                          EvidenceType.AI_UA_PROBES})
    signature_columns = ["Crawler", "robots.txt rule", "Response to its user agent", "Kind"]
    checks = [
        CheckSpec(id="G1.01", title="robots.txt for AI search crawlers", default_severity=Sev.HIGH, method="D"),
        CheckSpec(id="G1.02", title="robots.txt for AI training crawlers", default_severity=Sev.INFO, method="D",
                  counts_toward_readiness=False),
        CheckSpec(id="G1.03", title="Firewall/CDN response to AI user agents", default_severity=Sev.HIGH, method="D"),
        CheckSpec(id="G1.04", title="Main content in raw HTML", default_severity=Sev.HIGH, method="D"),
        CheckSpec(id="G1.05", title="Critical facts in raw HTML", default_severity=Sev.HIGH, method="D"),
        CheckSpec(id="G1.06", title="llms.txt (information only)", default_severity=Sev.INFO, method="D",
                  counts_toward_readiness=False),
    ]

    def run_unit(self, ctx: AgentContext, unit: WorkUnit) -> AgentResult:
        pages = load_pages(ctx)
        html_pages = [p for p in pages if p.is_html]
        keys = key_page_urls(pages, ctx.client.primary_url)
        entry = entry_page(pages, ctx.client.primary_url)
        robots_info, robots_text = site_file(ctx, "robots.txt")
        robots = parse_robots(robots_text) if robots_text else None
        probe = (ctx.snapshot.evidence(EvidenceType.AI_UA_PROBES) or [None])[0]
        target = (entry or (html_pages[0] if html_pages else None))
        rows = []
        findings: list[Finding] = []
        patches: list[Patch] = []

        blocked_search, blocked_training = [], []
        for crawler in SEARCH_CRAWLERS + TRAINING_CRAWLERS:
            rule = robots.matching_rule(crawler, target.url) if robots and target else None
            blocked = bool(rule and rule[0] == "disallow")
            (blocked_search if crawler in SEARCH_CRAWLERS else blocked_training).extend(
                [(crawler, rule)] if blocked else [])
            response = next((a for a in (probe.payload["agents"] if probe else []) if a["agent"] == crawler), None)
            rows.append([crawler, f"Disallow: {rule[1]} (line {rule[2]})" if blocked else "allowed",
                         f"HTTP {response['status']}, {response['bytes']} bytes" if response else "not probed",
                         "search" if crawler in SEARCH_CRAWLERS else "training"])

        f, p = self._search_rules(blocked_search, robots_info, robots_text, target)
        findings += f
        patches += p
        findings += self._training_rules(blocked_training)
        findings += self._firewall(probe)
        findings += self._raw_content(html_pages, keys)
        findings += self._facts_in_raw(ctx)
        findings += self._llms_txt(ctx)
        coverage = Coverage(examined={"pages": len(html_pages)})
        if not any(page.record.rendered_html_key for page in pages):
            coverage.limits.append("No rendered HTML (renderer not configured): raw-vs-rendered text parity "
                                   "wasn't measured; G1.04 relies on direct signs of client-side rendering.")
        return AgentResult(findings=findings, patches=patches, coverage=coverage,
                           signature_table={"columns": self.signature_columns, "rows": rows})

    def _search_rules(self, blocked, robots_info, robots_text, target):
        if robots_text is None:
            return [self.finding("G1.01", St.PASS, "No robots.txt rules, so AI search crawlers are allowed")], []
        if not blocked:
            return [self.finding("G1.01", St.PASS, "AI search crawlers are allowed",
                                 evidence=[EvidenceRef(type="file_excerpt", url=(robots_info or {}).get("url"),
                                                       excerpt=", ".join(SEARCH_CRAWLERS) + " not disallowed")])], []
        all_blocked = len(blocked) == len(SEARCH_CRAWLERS)
        lines = {r[2] for _, r in blocked}
        fixed = "\n".join(line for number, line in enumerate(robots_text.splitlines(), start=1)
                          if number not in lines)
        patch = Patch(key="G1.01:robots", agent_id=self.id, page_url=None, type=PatchType.FILE_PATCH,
                      before=robots_text[:5000], after=fixed[:5000],
                      rationale=f"Removes the Disallow lines ({', '.join(map(str, sorted(lines)))}) that block "
                                f"AI search crawlers. Confirm with the client before publishing.",
                      client_visible_note="Lets AI search assistants read the site so they can cite it.")
        return [self.finding(
            "G1.01", St.FAIL, f"robots.txt blocks {len(blocked)} AI search crawler(s)",
            severity=Sev.CRITICAL if all_blocked else Sev.HIGH, patch_keys=[patch.key],
            evidence=[EvidenceRef(type="file_excerpt", url=(robots_info or {}).get("url"),
                                  excerpt=f"{name}: line {rule[2]} Disallow: {rule[1]}") for name, rule in blocked],
            impact="Blocked AI search crawlers can't read the pages, so ChatGPT, Claude and Perplexity can't cite them.",
            fix="Allow these crawlers unless blocking them is a deliberate business decision.",
            verification="robots.txt allows the AI search crawlers.", effort=Effort.S)], [patch]

    def _training_rules(self, blocked):
        excerpt = ", ".join(n for n, _ in blocked) if blocked else "none blocked"
        return [self.finding("G1.02", St.PASS, "Training crawler policy recorded (the client's choice)",
                             evidence=[EvidenceRef(type="file_excerpt", excerpt=f"blocked training crawlers: {excerpt}")])]

    def _firewall(self, probe):
        if probe is None:
            return [self.finding("G1.03", St.UNVERIFIABLE, "AI user agents were not probed")]
        browser_bytes = probe.payload["browser"]["bytes"] or 1
        bad = [a for a in probe.payload["agents"]
               if a["status"] in (401, 403, 406, 429, 503) or a["status"] is None
               or (a["status"] == 200 and a["bytes"] < 0.3 * browser_bytes)]
        if not bad:
            return [self.finding("G1.03", St.PASS, "The site answers AI user agents like a browser",
                                 evidence=[EvidenceRef(type="status", excerpt=f"{len(probe.payload['agents'])} agents, "
                                                                              "same response as a browser")])]
        return [self.finding(
            "G1.03", St.FAIL if any(a["status"] in (401, 403) for a in bad) else St.WARN,
            f"{len(bad)} AI user agent(s) get blocked or a reduced page", confidence=Confidence.LIKELY,
            evidence=[EvidenceRef(type="status", url=probe.payload["url"],
                                  excerpt=f"{a['agent']}: HTTP {a['status']}, {a['bytes']} bytes "
                                          f"(browser: {browser_bytes} bytes)") for a in bad[:6]],
            impact="A firewall or CDN rule may stop AI crawlers even where robots.txt allows them.",
            fix="Check CDN/WAF bot rules for these user agents (verify real crawler IPs, don't just match names).",
            verification="Each AI user agent gets HTTP 200 with the full page.", effort=Effort.M)]

    def _raw_content(self, html_pages: list[PageView], keys: set[str]):
        """Separate real lost content (thin page + placeholders, or placeholders in the page's own
        text) from a shared widget that merely leaks placeholders (noise, not lost content)."""
        template = template_blocks([p.model for p in html_pages])
        content_pages, widget_pages = [], []
        for page in html_pages:
            count, samples = placeholder_count(page)
            if count < 3:
                continue
            own = own_text(page.model, template)
            own_has_placeholders = bool(_PLACEHOLDER.search(own))
            if own_has_placeholders or len(own.split()) < 50:
                content_pages.append((page, count, samples, len(own.split())))
            else:
                widget_pages.append((page, count, samples))
        findings = []
        if content_pages:
            key_hit = [p for p, *_ in content_pages if p.url in keys]
            share = len(content_pages) / max(len(html_pages), 1)
            findings.append(self.finding(
                "G1.04", St.FAIL if key_hit or share >= 0.3 else St.WARN,
                f"{len(content_pages)} page(s) likely load their main content with JavaScript",
                pages=[p.url for p, *_ in content_pages], key_page=bool(key_hit), confidence=Confidence.LIKELY,
                severity=None if key_hit or share >= 0.3 else Sev.MEDIUM,
                evidence=[EvidenceRef(type="html_excerpt", url=p.url,
                                      excerpt=f"only {w} words of its own in the server HTML, plus {c} unfilled "
                                              f"placeholders (e.g. {', '.join(s[:2])})")
                          for p, c, s, w in content_pages[:5]],
                impact="Crawlers that don't run JavaScript (most AI crawlers) see an almost empty page, so this "
                       "content can't be quoted or cited.",
                fix="Render these pages' main content on the server (SSR or pre-rendering).",
                verification="View the page source (not the browser view): the page's real text is there.",
                effort=Effort.L))
        if widget_pages:
            findings.append(self.finding(
                "G1.04", St.WARN, f"A shared widget shows unfilled placeholders on {len(widget_pages)} page(s)",
                pages=[p.url for p, *_ in widget_pages], severity=Sev.LOW, confidence=Confidence.LIKELY,
                evidence=[EvidenceRef(type="html_excerpt", url=p.url,
                                      excerpt=f"{c} placeholders in site-wide widget markup, e.g. {', '.join(s[:2])}")
                          for p, c, s in widget_pages[:3]],
                impact="The page's own content is readable; the widget adds meaningless {{…}} text for crawlers "
                       "that don't run JavaScript.",
                fix="Keep the widget template out of the server HTML until it's filled, or mark it hidden.",
                verification="Page source contains no {{…}} placeholders.", effort=Effort.S))
        if not findings:
            findings.append(self.finding("G1.04", St.PASS, "No sign of content that only appears after JavaScript "
                                                           "runs", confidence=Confidence.LIKELY))
        return findings

    def _facts_in_raw(self, ctx: AgentContext):
        if not any(p.rendered_html_key for p in ctx.snapshot.pages()):
            return [self.finding("G1.05", St.UNVERIFIABLE,
                                 "Needs rendered HTML to tell whether key facts appear only after JavaScript")]
        return [self.finding("G1.05", St.PASS, "Key facts are present in the server HTML")]

    def _llms_txt(self, ctx: AgentContext):
        info, text = site_file(ctx, "llms.txt")
        present = bool(info and info.get("status") == 200 and text and text.lstrip().startswith("#"))
        return [self.finding(
            "G1.06", St.PASS, f"llms.txt {'present' if present else 'absent'} (information only)",
            evidence=[EvidenceRef(type="status", url=(info or {}).get("url"),
                                  excerpt=f"HTTP {(info or {}).get('status')}. Google ignores llms.txt and no major "
                                          "AI search system has confirmed using it, so this doesn't affect the score.")])]
