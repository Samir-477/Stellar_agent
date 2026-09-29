"""Issue cards for the Agents layer: every issue an agent reported, with its evidence, the
proposed fix and, where a code change exists, the before/after code from the captured page.

Pure functions over stored findings, patches and snippets (engine/output/diffs.py), so they
are tested without a database. Every card states what kind of fix it has, so an issue
without a code change is never shown as if it had one:
  code         a change to the page's HTML, with a before/after diff
  content      new text drafted for the page (needs review before publishing)
  facts        the fix needs facts only the client can supply
  observation  a dated search or AI sample to monitor, not a site defect
  action       steps to take outside the page's HTML (speed, off-site profiles, new pages)
"""

from __future__ import annotations

from engine.plain import explain, issue_key
from engine.registry import AGENTS

SEVERITY_ORDER = {"critical": 0, "high": 1, "medium": 2, "low": 3, "info": 4, None: 5}
CONTENT_AGENTS = {"A1", "A2", "A3", "G2", "S4", "S5"}  # their inserts are drafted copy, not markup fixes


def fix_type(finding: dict, changes: list[dict]) -> str:
    agent = AGENTS.get(finding["agent_id"])
    check = agent.check(finding["check_id"]) if agent else None
    if agent and (not agent.counts_toward_readiness or (check and not check.counts_toward_readiness)):
        return "observation"
    if changes:
        drafted = finding["agent_id"] in CONTENT_AGENTS and all(c["type"] == "element_insert" for c in changes)
        return "content" if drafted else "code"
    if finding.get("missing_facts"):
        return "facts"
    return "action"


def build_issue_cards(findings: list[dict], patches: list[dict], snippets: dict[str, dict],
                      cases: dict[str, str] | None = None) -> list[dict]:
    """findings: stored finding payloads; patches: stored patch payloads; snippets: by patch key;
    cases: plain sentences about this site by issue key (engine/plain.py), where the model wrote one."""
    by_key = {p["key"]: p for p in patches}
    cards = []
    for f in findings:
        if f["status"] not in ("fail", "warn"):
            continue
        changes = []
        for key in f.get("patch_keys") or []:
            patch = by_key.get(key)
            if patch is None:
                continue
            snip = snippets.get(key) or {}
            changes.append({
                "key": key, "type": patch["type"], "page_url": patch.get("page_url"),
                "rationale": patch.get("rationale", ""), "note": patch.get("client_visible_note", ""),
                "confidence": patch.get("confidence"), "language": snip.get("language", "html"),
                "before": snip.get("before", patch.get("before")), "after": snip.get("after", patch["after"]),
                "before_segments": snip.get("before_segments", []), "after_segments": snip.get("after_segments", []),
                "placed": snip.get("placed"), "reason": snip.get("reason"),
            })
        agent = AGENTS.get(f["agent_id"])
        cards.append({
            "id": f"{f['agent_id']}:{f['check_id']}:{len(cards)}",
            "agent_id": f["agent_id"], "agent_name": agent.name if agent else f["agent_id"],
            "pillar": f.get("pillar"), "check_id": f["check_id"], "status": f["status"],
            "severity": f.get("severity"), "confidence": f.get("confidence"), "title": f["title"],
            "impact": f.get("impact", ""), "fix": f.get("fix", ""), "verification": f.get("verification", ""),
            "effort": f.get("effort"), "pages": (f.get("scope") or {}).get("pages", []),
            "evidence": f.get("evidence", []), "missing_facts": f.get("missing_facts", []),
            "fix_type": fix_type(f, changes), "changes": changes,
            "plain": explain(f, (cases or {}).get(issue_key(f))),
        })
    cards.sort(key=lambda c: (c["status"] != "fail", SEVERITY_ORDER.get(c["severity"], 5), -len(c["pages"]), c["check_id"]))
    for index, card in enumerate(cards):
        card["id"] = f"{card['agent_id']}:{card['check_id']}:{index}"
    return cards
