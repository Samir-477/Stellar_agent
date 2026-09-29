"""Intelligence layer (docs/spec/05): merges every agent's validated output for a run
into one 6-section report.

Deterministic: pillar readiness, de-duplication, cross-agent corroboration (several
agents reporting the same missing facts become one item), a priority matrix,
root-cause patterns, strengths and attention items. Dated observations and
hypotheses have separate lanes from actionable fixes. The LLM only writes the executive
summary, and each sentence must cite ids that exist in the data; sentences with
unknown ids, or numbers not present in the data, are dropped. If too little
survives, a deterministic summary is used instead.
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass, field
from typing import Any

from pydantic import BaseModel, Field

from engine.lib.topics import fact_topics
from engine.lib.urls import norm
from engine.llm import LLMClient, LLMError, load_prompt
from engine.plain import site_cases
from engine.registry import AGENTS
from engine.reports import check_statuses
from engine.schemas import SCHEMA_VERSION, CheckStatus, Finding

SEVERITY_WEIGHT = {"critical": 8, "high": 4, "medium": 2, "low": 1, "info": 0}
CONFIDENCE_WEIGHT = {"confirmed": 1.0, "likely": 0.8, "hypothesis": 0.4}
EFFORT_WEIGHT = {"S": 1, "M": 2, "L": 4, None: 2}
STATUS_WEIGHT = {CheckStatus.FAIL: 1.0, CheckStatus.WARN: 0.6}  # a failed check outranks a warning
READINESS_WEIGHT = {"critical": 3, "high": 2, "medium": 1, "low": 0.5, "info": 0}
STATUS_VALUE = {CheckStatus.PASS: 1.0, CheckStatus.WARN: 0.5, CheckStatus.FAIL: 0.0}
CORROBORATION_BOOST = 1.25  # the same gap found by several agents is more certain and one fix
# The client's entry page is what the engagement is about: an issue there outranks the same issue on two
# ordinary pages (reach grows with log2 of the page count).
ENTRY_BOOST, KEY_PAGE_BOOST = 2.5, 1.5
DIGEST_ITEMS, DIGEST_OBSERVATIONS = 12, 4

# Impact (reported severity) and evidence confidence determine the action lane.
# Effort, page reach and entry-page importance order items *within* a lane; they
# never promote a low-impact quick win above a high-impact issue. A hypothesis
# needs verification. A dated SERP/AI observation is a monitoring signal, not a
# site defect. Applicability and factual correctness must still be checked by
# the producing agent; this matrix cannot recover a finding the agent missed.
PRIORITY_MATRIX = {
    "confirmed": {"critical": "now", "high": "now", "medium": "next", "low": "later"},
    "likely": {"critical": "now", "high": "next", "medium": "next", "low": "later"},
    "hypothesis": {"critical": "investigate", "high": "investigate",
                   "medium": "investigate", "low": "investigate"},
}
LANE_ORDER = {"now": 0, "next": 1, "later": 2, "investigate": 3, "monitor": 4}

# Root-cause families: checks whose failures usually share one underlying fix.
CAUSES = {
    "client-side-rendering": ({"G1.04", "G1.05", "A2.06"},
                              "Content that only appears after JavaScript runs",
                              "Server-render (or pre-render) the affected templates so crawlers get the real text."),
    "structured-data": ({"S8.01", "S8.02", "S8.03", "S8.04", "S8.06", "S8.07"},
                        "Structured data generated from the wrong source or template",
                        "Fix the template that generates JSON-LD so each page describes its own entity."),
    "metadata-template": ({"S3.01", "S3.02", "S3.03", "S3.04", "S3.05", "S3.06", "S3.07"},
                          "Titles and descriptions written generically",
                          "Rewrite head tags per page (or fix the template) using each page's own topic."),
    "answer-structure": ({"A2.01", "A2.02", "A2.03", "A2.04", "A2.05"},
                         "Content organised as labels rather than answers",
                         "Rework key sections as question headings with direct answers first."),
    "answer-coverage": ({"A1.01", "A1.02", "A1.04"},
                        "Customer questions without answers on the site",
                        "Add short, factual answers for the questions customers search, starting with observed ones."),
    "ai-entity-knowledge": ({"G5.01", "G5.02", "G5.03", "G5.04", "G2.04", "G2.06", "G6.01", "G6.02", "G6.03",
                             "G6.04", "S9.01"},
                            "AI models don't know the business well",
                            "Make key facts explicit and identical across the site, structured data and major "
                            "listings (booking sites, Google Business Profile) that AI systems learn from."),
    "customer-journey": ({"A3.01", "A3.02", "A3.03", "A3.04"},
                         "Journey stages or the tools customers need are missing or hidden in JavaScript",
                         "Give every journey stage a section, page or tool in the server HTML, with a clear next "
                         "step from the entry page."),
    "local-presence": ({"S9.02", "S9.03", "S9.05", "S9.06"},
                       "Location details are incomplete for local search",
                       "Put the full address with PIN code, hours, a map link and a +91 phone link on each location "
                       "page, and complete the Google Maps listing."),
    "page-speed": ({"S2.01", "S2.02", "S2.03", "S2.04", "S2.06", "S2.08"},
                   "Pages load slowly: the main image arrives late and heavy scripts block the page",
                   "Load the hero image from the HTML early, defer third-party widgets and reserve space for "
                   "content that loads late."),
    "keyword-themes": ({"S5.01", "S5.02", "S5.04", "S5.05"},
                       "Search themes without one clear owner page",
                       "Map every theme customers search for to one page; merge or refocus competing pages; add "
                       "pages or sections for missing themes and places."),
    "search-intent": ({"S4.03", "S4.04", "S4.05", "S5.03"},
                      "Pages written without their target search in mind",
                      "Pick each page's target query, match the type of page that ranks for it, open with the "
                      "answer and cover what the top results cover."),
    "content-structure": ({"S4.01", "S4.02", "S4.08"},
                          "Headings and paragraphs used for layout rather than structure",
                          "Give each page one descriptive H1, a gap-free H2/H3 outline and short paragraphs."),
    "citable-facts": ({"G2.01", "G2.02", "G2.03", "G2.05"},
                      "Key pages make general claims instead of specific, first-hand facts",
                      "Rewrite key pages around facts only this business can state (numbers, names, places, "
                      "times), with sources for figures and awards."),
    "internal-linking": ({"S7.01", "S7.02", "S7.03", "S7.04", "S7.05", "S7.06", "S7.07"},
                         "Important pages get few descriptive internal links",
                         "Link key pages from relevant body text with anchors that name the destination."),
    "trust-information": ({"S10.01", "S10.02", "S10.05", "S10.06", "S10.07", "S10.08"},
                          "Trust information (who runs the business, policies, prices) isn't stated in page text",
                          "Publish the organization details, contact details, policies and prices as plain text "
                          "and link them from the footer and the booking flow."),
    "broken-links": ({"S1.01", "S1.03", "S1.07"},
                     "Links and sitemap entries pointing at missing or redirected pages",
                     "Update internal links and the sitemap to live, final URLs."),
}


@dataclass
class WorkItem:
    id: str
    title: str
    action: str
    severity: str
    confidence: str
    effort: str | None
    pillars: list[str]
    agents: list[str]
    check_ids: list[str]
    pages: list[str]
    patch_keys: list[str]
    missing_facts: list[str]
    priority: float  # harm per unit of effort: the order of the work list (quick wins first)
    harm: float = 0.0  # how much the issue costs, whatever the effort: picks the lead blocker
    wave: str = ""
    priority_reason: str = ""
    prerequisite_review: bool = False
    cause: str | None = None
    evidence: list[dict] = field(default_factory=list)
    observation: bool = False  # from an agent or check that doesn't count toward readiness
    facts: list[str] = field(default_factory=list)  # corroborated missing-fact topics (merged items only)
    impact: str = ""  # the agent's plain "why it matters", used for the client cards


def readiness(findings_by_agent: dict[str, list[Finding]]) -> dict[str, dict]:
    """Per-pillar readiness from the agents' check statuses (docs/spec/04)."""
    totals: dict[str, dict[str, float]] = {}
    critical_fail: dict[str, bool] = {}
    for agent_id, findings in findings_by_agent.items():
        agent = AGENTS[agent_id]
        pillar = agent.pillar.value
        bucket = totals.setdefault(pillar, {"score": 0.0, "weight": 0.0, "applicable": 0, "verifiable": 0})
        if not agent.counts_toward_readiness:
            continue
        statuses = check_statuses(agent, findings)
        for spec in agent.checks:
            status = statuses[spec.id]
            if not spec.counts_toward_readiness or status == CheckStatus.NOT_APPLICABLE:
                continue
            bucket["applicable"] += 1
            if status == CheckStatus.UNVERIFIABLE:
                continue
            weight = READINESS_WEIGHT[spec.default_severity.value]
            bucket["verifiable"] += 1
            bucket["weight"] += weight
            bucket["score"] += weight * STATUS_VALUE[status]
            if status == CheckStatus.FAIL and any(f.check_id == spec.id and f.severity == "critical" for f in findings):
                critical_fail[pillar] = True
    out = {}
    for pillar, b in totals.items():
        score = round(100 * b["score"] / b["weight"]) if b["weight"] else None
        if score is not None and critical_fail.get(pillar):
            score = min(score, 49)
        out[pillar] = {"score": score, "coverage": round(100 * b["verifiable"] / b["applicable"]) if b["applicable"] else 0,
                       "band": _band(score), "capped_by_critical": bool(critical_fail.get(pillar))}
    return out


def _band(score: int | None) -> str:
    if score is None:
        return "not measured"
    return "blocked or poor" if score < 50 else "needs work" if score < 70 else "solid" if score < 85 else "strong"


def harm(f: Finding, key_pages: set[str], entry_url: str | None = None) -> float:
    """Severity × confidence × fail/warn × reach (log2 of pages) × where (entry page, key page)."""
    reach = 1 + math.log2(max(len(f.scope.pages), 1))
    pages = {norm(p) for p in f.scope.pages}
    boost = ENTRY_BOOST if entry_url and norm(entry_url) in pages else \
        KEY_PAGE_BOOST if pages & {norm(k) for k in key_pages} else 1.0
    return round(SEVERITY_WEIGHT[f.severity.value if f.severity else "info"] * CONFIDENCE_WEIGHT[f.confidence.value]
                 * STATUS_WEIGHT.get(f.status, 1.0) * reach * boost, 2)


def priority(f: Finding, key_pages: set[str], entry_url: str | None = None) -> float:
    return round(harm(f, key_pages, entry_url) / EFFORT_WEIGHT[f.effort.value if f.effort else None], 2)


def build_work_items(findings: list[Finding], key_pages: set[str], entry_url: str | None = None) -> list[WorkItem]:
    """Work items: one per actionable finding (the same issue found twice is one item), items from
    different agents that report the same missing facts merged into one, then ranked into waves."""
    return rank(corroborate(collect(findings, key_pages, entry_url)))


def is_observation(f: Finding) -> bool:
    agent = AGENTS[f.agent_id]
    return not agent.counts_toward_readiness or not agent.check(f.check_id).counts_toward_readiness


def collect(findings: list[Finding], key_pages: set[str], entry_url: str | None = None) -> list[WorkItem]:
    merged: dict[str, WorkItem] = {}
    for f in findings:
        if f.status not in (CheckStatus.FAIL, CheckStatus.WARN) or not f.severity or f.severity.value == "info":
            continue
        key = f.fingerprint
        cause = next((name for name, (checks, _, _) in CAUSES.items() if f.check_id in checks), None)
        item = merged.get(key)
        if item is None:
            merged[key] = WorkItem(
                id="", title=f.title, action=f.fix, severity=f.severity.value, confidence=f.confidence.value,
                effort=f.effort.value if f.effort else None, pillars=[f.pillar.value], agents=[f.agent_id],
                check_ids=[f.check_id], pages=list(f.scope.pages), patch_keys=list(f.patch_keys),
                missing_facts=list(f.missing_facts), priority=priority(f, key_pages, entry_url),
                harm=harm(f, key_pages, entry_url), cause=cause, impact=f.impact,
                evidence=[e.model_dump(exclude_none=True) for e in f.evidence[:2]], observation=is_observation(f))
        else:
            item.agents = sorted(set(item.agents) | {f.agent_id})
            item.check_ids = sorted(set(item.check_ids) | {f.check_id})
            item.pages = sorted(set(item.pages) | set(f.scope.pages))
            item.patch_keys += [k for k in f.patch_keys if k not in item.patch_keys]
            item.priority = max(item.priority, priority(f, key_pages, entry_url))
            item.harm = max(item.harm, harm(f, key_pages, entry_url))
            item.observation = item.observation or is_observation(f)
            certainty = ["hypothesis", "likely", "confirmed"]
            item.confidence = min((item.confidence, f.confidence.value), key=certainty.index)
    return list(merged.values())


def corroborate(items: list[WorkItem]) -> list[WorkItem]:
    """Merge items whose missing facts are the same topics (prices, reviews, check-in times) reported
    by at least two agents: one gap found three ways is one fix, and more certain. Only items made
    entirely of such facts are merged; an item that also lists other gaps (e.g. unrelated unanswered
    questions) stays on its own but still counts as a corroborating agent."""
    topics = {id(i): [fact_topics(m) for m in i.missing_facts] for i in items}
    agents_by_topic: dict[str, set[str]] = {}
    for item in items:
        if item.observation:
            continue
        for found in topics[id(item)]:
            for topic in found:
                agents_by_topic.setdefault(topic, set()).update(item.agents)
    shared = {t for t, agents in agents_by_topic.items() if len(agents) >= 2}
    members = [i for i in items if not i.observation and topics[id(i)] and all(topics[id(i)])
               and set().union(*topics[id(i)]) & shared]
    if len({a for i in members for a in i.agents}) < 2:
        return items
    facts = sorted(set().union(*(set().union(*topics[id(i)]) for i in members)), key=lambda t: (t not in shared, t))
    agents = sorted(set().union(*(agents_by_topic[t] for t in facts)))
    order = ["low", "medium", "high", "critical"]
    certainty = ["hypothesis", "likely", "confirmed"]
    merged = WorkItem(
        id="", title=f"Customers can't find key facts on the site: {', '.join(facts)}",
        action="Publish these facts in the page text where customers decide (the entry page first): "
               + ", ".join(facts) + ". The agents' details are in the evidence.",
        severity=max((i.severity for i in members), key=order.index),
        confidence=min((i.confidence for i in members), key=certainty.index), effort="M",
        pillars=sorted({p for i in members for p in i.pillars}), agents=agents,
        check_ids=sorted({c for i in members for c in i.check_ids}),
        pages=sorted({p for i in members for p in i.pages}),
        patch_keys=[k for i in members for k in i.patch_keys], missing_facts=facts,
        priority=round(max(i.priority for i in members) * CORROBORATION_BOOST, 2),
        harm=round(max(i.harm for i in members) * CORROBORATION_BOOST, 2),
        evidence=[i.evidence[0] for i in members if i.evidence][:4],
        impact=next((i.impact for i in members if i.impact), ""),
        observation=all(i.observation for i in members), facts=facts)
    return [i for i in items if i not in members] + [merged]


def rank(items: list[WorkItem]) -> list[WorkItem]:
    for item in items:
        item.prerequisite_review = bool(item.missing_facts)
        if item.observation:
            item.wave = "monitor"
            item.priority_reason = "Dated search or AI observation; monitor separately from site fixes."
        else:
            item.wave = PRIORITY_MATRIX[item.confidence][item.severity]
            item.priority_reason = (f"Reported {item.severity} impact; agent-rated {item.confidence} confidence. "
                                    + ("Verify before recommending a fix." if item.wave == "investigate"
                                       else "Ranked within this lane by reach, key-page impact and effort."))
        if item.prerequisite_review:
            item.priority_reason += " Review the listed prerequisites before implementation."
    # Stable check/page tie-breaks make reports reproducible when findings arrive in a different order.
    items.sort(key=lambda i: (LANE_ORDER[i.wave], -i.priority, -i.harm, i.check_ids, i.pages, i.title))
    for index, item in enumerate(items, start=1):
        item.id = f"W{index}"
    return items


def root_causes(items: list[WorkItem]) -> list[dict]:
    out = []
    for name, (checks, label, fix) in CAUSES.items():
        members = [i for i in items if i.cause == name and i.wave in ("now", "next", "later")]
        pages = sorted({p for i in members for p in i.pages})
        if len(members) >= 2 or len(pages) >= 3:
            out.append({"id": "", "cause": name, "title": label, "fix": fix, "items": [i.id for i in members],
                        "pages": len(pages), "pillars": sorted({p for i in members for p in i.pillars}),
                        "agents": sorted({a for i in members for a in i.agents})})
    out.sort(key=lambda r: -len(r["items"]))
    for index, cause in enumerate(out, start=1):
        cause["id"] = f"R{index}"
    return out


def strengths(findings: list[Finding]) -> list[dict]:
    notable = []
    for f in findings:
        if f.status != CheckStatus.PASS:
            continue
        spec = next((c for c in AGENTS[f.agent_id].checks if c.id == f.check_id), None)
        if spec and spec.default_severity.value in ("critical", "high"):
            notable.append({"id": "", "check_id": f.check_id, "agent": f.agent_id, "pillar": f.pillar.value,
                            "title": f.title})
    for index, s in enumerate(notable, start=1):
        s["id"] = f"K{index}"
    return notable


def attention(findings: list[Finding], items: list[WorkItem]) -> list[dict]:
    out = []
    for f in findings:
        if f.status == CheckStatus.UNVERIFIABLE:
            out.append({"kind": "unverifiable", "check_id": f.check_id, "agent": f.agent_id, "title": f.title})
    out += [{"kind": "low", "check_id": ",".join(i.check_ids), "agent": ",".join(i.agents), "title": i.title}
            for i in items if i.wave == "later"]
    for index, a in enumerate(out, start=1):
        a["id"] = f"A{index}"
    return out


# --------------------------------------------------------------- summary

class Sentence(BaseModel):
    text: str
    ids: list[str] = Field(default_factory=list)


class PriorityCard(BaseModel):
    id: str
    headline: str = ""
    why: str = ""
    action: str = ""


class Summary(BaseModel):
    internal: list[Sentence] = Field(default_factory=list)
    client: list[Sentence] = Field(default_factory=list)
    client_priorities: list[PriorityCard] = Field(default_factory=list)


CLIENT_CARDS = 5
_NUMBER = re.compile(r"\d+(?:\.\d+)?")


def client_candidates(items: list[WorkItem], lead: dict[str, str | None] | None) -> list[WorkItem]:
    """The fixes a client sees first: the lead blocker and opportunity, then the rest in priority order."""
    fixes = [i for i in items if i.wave in ("now", "next", "later")]
    leading = [i for i in fixes if lead and i.id in (lead.get("blocker"), lead.get("opportunity"))]
    return (leading + [i for i in fixes if i not in leading])[:CLIENT_CARDS]


def _card_line(i: WorkItem) -> str:
    return (f"{i.id} | severity {i.severity} | pages {len(i.pages)} | problem: {i.title} | "
            f"why it matters: {i.impact or '-'} | fix: {i.action}")


def _valid_cards(cards: list[PriorityCard], candidates: list[WorkItem], data: str) -> dict[str, dict]:
    """Model-worded cards survive only for known candidate ids, with every number present in the data."""
    allowed = {i.id for i in candidates}
    numbers_in_data = set(_NUMBER.findall(data))
    kept: dict[str, dict] = {}
    for card in cards:
        numbers = [n for text in (card.headline, card.why, card.action) for n in _NUMBER.findall(text)]
        if card.id in allowed and card.id not in kept and card.headline.strip() and card.action.strip() \
                and all(n in numbers_in_data for n in numbers):
            kept[card.id] = {"headline": card.headline.strip(), "why": card.why.strip(),
                             "action": card.action.strip(), "source": "model"}
    return kept


def client_cards(candidates: list[WorkItem], worded: dict[str, dict] | None = None) -> list[dict]:
    """One plain card per top fix: the model's wording where it passed validation, else the agents' own text."""
    out = []
    for item in candidates:
        words = (worded or {}).get(item.id) or {"headline": item.title, "why": item.impact, "action": item.action,
                                                 "source": "rules"}
        out.append({"id": item.id, **words, "severity": item.severity, "effort": item.effort,
                    "pages": len(item.pages), "agents": item.agents, "check_ids": item.check_ids, "wave": item.wave})
    return out


def leads(items: list[WorkItem], causes: list[dict]) -> dict[str, str | None]:
    """The summary's headline items, chosen by rule so the model only phrases them:
    blocker = an item from the first lane with fixes (Now, then Next, then Later), so the headline
    never contradicts the priority list; within that lane the most severe item, then the one that
    costs the most (harm, whatever the effort; one template issue repeated on many pages must not
    outrank a failure on the entry page); opportunity = the corroborated facts item, else the root
    cause behind the most items; observation = the most severe observation."""
    scored = [i for i in items if i.wave in ("now", "next", "later")]
    rank_of = {"critical": 3, "high": 2, "medium": 1, "low": 0}
    blocker = max(scored, key=lambda i: (-LANE_ORDER[i.wave], rank_of.get(i.severity, 0), i.harm)).id \
        if scored else None
    opportunity = next((i.id for i in scored if i.facts and i.id != blocker), None) or \
        next((c["id"] for c in causes if blocker not in c["items"]), None)
    order = {"critical": 0, "high": 1, "medium": 2, "low": 3}
    observed = sorted((i for i in items if i.wave == "monitor"),
                      key=lambda i: (order.get(i.severity, 4), -i.priority))
    return {"blocker": blocker, "opportunity": opportunity, "observation": observed[0].id if observed else None}


def _item_line(i: WorkItem) -> str:
    line = f"{i.id} [{i.severity}, {i.wave}] {i.title} | pages: {len(i.pages)} | agents: {', '.join(i.agents)}"
    return line + (f" | corroborated by {len(i.agents)} agents" if i.facts else "")


def digest(ready: dict, items: list[WorkItem], causes: list[dict], strong: list[dict], attn: list[dict],
           lead: dict[str, str | None] | None = None, candidates: list[WorkItem] | None = None) -> str:
    """What the summary may use. Observations get their own block: ranked with everything else they
    often fall outside the top items, yet they are some of the most telling findings (AI visibility)."""
    lines = ["READINESS: " + ", ".join(f"{p}={v['score']} (coverage {v['coverage']}%)" for p, v in sorted(ready.items()))]
    lines += [f"LEAD {role.upper()}: {ref}" for role, ref in (lead or {}).items() if ref]
    shown = [i for i in items if i.wave in ("now", "next", "later")][:DIGEST_ITEMS]
    shown += [i for i in items if i.wave in ("now", "next", "later")
              and i.id in (lead or {}).values() and i not in shown]
    lines += [_item_line(i) for i in shown]
    observed = [i for i in items if i.wave == "monitor"][:DIGEST_OBSERVATIONS]
    observed += [i for i in items if i.wave == "monitor" and i.id in (lead or {}).values() and i not in observed]
    if observed:
        lines.append("OBSERVATIONS (dated samples of search results and AI answers; not scored):")
        lines += [_item_line(i) for i in observed]
    lines += [f"{c['id']} root cause: {c['title']} | items: {', '.join(c['items'])} | pages: {c['pages']}"
              for c in causes]
    lines += [f"{s['id']} strength: {s['title']}" for s in strong[:8]]
    lines += [f"{a['id']} attention ({a['kind']}): {a['title']}" for a in attn[:6]]
    lines += [f"INVESTIGATE {i.id}: {i.title}" for i in items if i.wave == "investigate"][:4]
    if candidates:
        lines.append("TOP FIXES (write one client card for each, in this order):")
        lines += [_card_line(i) for i in candidates]
    return "\n".join(lines)


def _valid(sentences: list[Sentence], ids: set[str], data: str) -> list[dict]:
    numbers_in_data = set(re.findall(r"\d+(?:\.\d+)?", data))
    kept = []
    for s in sentences:
        cited = [i for i in s.ids if i in ids]
        numbers = re.findall(r"\d+(?:\.\d+)?", s.text)
        if cited and all(n in numbers_in_data for n in numbers):
            kept.append({"text": s.text.strip(), "ids": cited})
    return kept


def fallback_summary(ready: dict, items: list[WorkItem], strong: list[dict],
                     candidates: list[WorkItem] | None = None) -> dict:
    scores = ", ".join(f"{p.upper()} {v['score']}" for p, v in sorted(ready.items()) if v["score"] is not None)
    internal = [{"text": f"Readiness: {scores}." if scores else "Readiness was not measured from these checks.",
                 "ids": ["READINESS"]}]
    client = []
    actionable = next((i for i in items if i.wave in ("now", "next", "later")), None)
    observed = next((i for i in items if i.wave == "monitor"), None)
    if actionable:
        internal.append({"text": f"First actionable priority: {actionable.title}.", "ids": [actionable.id]})
        client.append({"text": f"First proposed fix: {actionable.title.lower()}.", "ids": [actionable.id]})
    elif observed:
        internal.append({"text": f"Dated observation to monitor: {observed.title}.", "ids": [observed.id]})
        client.append({"text": "This run produced a dated search or AI observation, not a verified site fix.",
                       "ids": [observed.id]})
    if strong:
        client.insert(0, {"text": f"Already working well: {strong[0]['title'].lower()}.", "ids": [strong[0]["id"]]})
    return {"internal": internal, "client": client, "client_priorities": client_cards(candidates or []),
            "source": "deterministic"}


def summarize(llm: LLMClient | None, ready, items, causes, strong, attn, lead=None) -> dict:
    candidates = client_candidates(items, lead)
    data = digest(ready, items, causes, strong, attn, lead, candidates)
    ids = {"READINESS"} | {i.id for i in items} | {c["id"] for c in causes} | {s["id"] for s in strong} | \
          {a["id"] for a in attn}
    if llm is None:
        return fallback_summary(ready, items, strong, candidates)
    try:
        result = llm.complete_json(load_prompt("intel.summary", 4), Summary, digest=data)
    except LLMError as exc:
        out = fallback_summary(ready, items, strong, candidates)
        out["note"] = f"LLM summary unavailable: {exc}"
        return out
    internal, client = _valid(result.data.internal, ids, data), _valid(result.data.client, ids, data)
    worded = _valid_cards(result.data.client_priorities, candidates, data)
    dropped = len(result.data.internal) + len(result.data.client) - len(internal) - len(client)
    if len(internal) < 2 or len(client) < 2:
        out = fallback_summary(ready, items, strong, candidates)
        out["client_priorities"] = client_cards(candidates, worded)
        out["note"] = f"LLM summary rejected by validation ({dropped} sentence(s) dropped)"
        return out
    return {"internal": internal, "client": client, "client_priorities": client_cards(candidates, worded),
            "source": f"{result.provider}:{result.model}", "dropped_sentences": dropped,
            "dropped_cards": len(candidates) - len(worded)}


# ----------------------------------------------------------------- report

def build_intelligence_report(findings_by_agent: dict[str, list[Finding]], key_pages: set[str],
                              coverage_notes: list[str], llm: LLMClient | None,
                              entry_url: str | None = None) -> dict[str, Any]:
    all_findings = [f for fs in findings_by_agent.values() for f in fs]
    ready = readiness(findings_by_agent)
    items = build_work_items(all_findings, key_pages, entry_url)
    causes = root_causes(items)
    for cause in causes:
        for item in items:
            if item.id in cause["items"]:
                item.cause = cause["id"]
    strong = strengths(all_findings)
    attn = attention(all_findings, items)
    lead = leads(items, causes)
    summary = summarize(llm, ready, items, causes, strong, attn, lead)
    cases = site_cases(llm, all_findings)

    def as_dict(i: WorkItem) -> dict:
        return {k: v for k, v in i.__dict__.items()}

    return {
        "schema_version": SCHEMA_VERSION,
        "priority_matrix_version": "1.0",
        "readiness": ready,
        "executive_summary": summary,
        "leads": lead,
        "what_to_fix_first": {w: [as_dict(i) for i in items if i.wave == w]
                              for w in ("now", "next", "later", "investigate", "monitor")},
        "whats_working": strong,
        "what_needs_attention": attn,
        "root_causes_and_patterns": causes,
        "action_plan_and_blocked_work": {
            "now": [i.id for i in items if i.wave == "now"],
            "next": [i.id for i in items if i.wave == "next"],
            "later": [i.id for i in items if i.wave == "later"],
            # A missing fact does not prove the whole recommendation is blocked; some legacy
            # findings even put actions in missing_facts. Surface them for review, not as a gate.
            "blocked": [],
            "prerequisites_to_review": [{"id": i.id, "title": i.title, "needs": i.missing_facts}
                                        for i in items if i.prerequisite_review],
            "investigate": [i.id for i in items if i.wave == "investigate"],
            "monitor": [i.id for i in items if i.wave == "monitor"],
            "facts_to_supply": [{"id": i.id, "facts": i.facts, "agents": i.agents} for i in items if i.facts],
        },
        "coverage": {"agents": sorted(findings_by_agent), "notes": coverage_notes},
        # A plain sentence per issue about this site, by issue key (engine/plain.py); missing ones use a template.
        "plain_cases": cases,
    }
