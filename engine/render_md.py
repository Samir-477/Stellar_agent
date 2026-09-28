"""Render agent and intelligence reports (stored JSON) as Markdown."""

from __future__ import annotations


def _pages(pages: list[str], limit: int = 3) -> str:
    shown = ", ".join(pages[:limit])
    return shown + (f" (+{len(pages) - limit} more)" if len(pages) > limit else "")


def agent_report_md(r: dict) -> str:
    lines = [f"# {r['agent_id']} {r['agent_name']}", "", f"**Verdict:** {r['verdict']}", "",
             "Scorecard: " + " · ".join(f"{v} {k}" for k, v in r["scorecard"].items() if v), ""]
    cov = r["scope_and_evidence"]["coverage"]
    lines += ["## 1. Scope & evidence", f"Examined: {cov.get('examined')}"]
    lines += [f"- Limit: {x}" for x in cov.get("limits", [])]
    table = r["scope_and_evidence"].get("signature_table") or {}
    if table.get("rows"):
        cols = table["columns"]
        lines += ["", "| " + " | ".join(cols) + " |", "|" + "---|" * len(cols)]
        lines += ["| " + " | ".join(str(c).replace("|", "/")[:80] for c in row) + " |" for row in table["rows"][:25]]
    lines += ["", "## 2. Issues to fix"]
    for i in r["issues_to_fix"] or [{"title": "None"}]:
        if "check_id" not in i:
            lines.append("None.")
            continue
        lines += [f"### [{i['severity']}] {i['check_id']} {i['title']}",
                  f"Pages: {_pages(i['pages'])}" if i["pages"] else "",
                  *[f"> {e['url'] + ': ' if e.get('url') and e['url'] not in e['excerpt'] else ''}{e['excerpt']}"
                    for e in i["evidence"][:2]],
                  f"**Why it matters:** {i['impact']}", f"**Fix:** {i['fix']}", ""]
    lines += ["## 3. Needs attention"]
    lines += [f"- [{i['severity'] or '—'}] {i['check_id']} {i['title']}" for i in r["needs_attention"]] or ["None."]
    lines += ["", "## 4. What's working"]
    lines += [f"- {i['check_id']} {i['title']}" for i in r["whats_working"]] or ["None."]
    lines += ["", "## 5. Proposed changes"]
    for p in r["proposed_changes"] or []:
        lines += [f"- **{p['type']}** on {p.get('page_url') or 'site files'}: {p['rationale']}",
                  f"  - before: `{str(p.get('before') or '—')[:120]}`", f"  - after: `{p['after'][:200]}`"]
    if not r["proposed_changes"]:
        lines.append("None.")
    lines += ["", "## 6. Missing facts & next checks"]
    lines += [f"- {x}" for x in r["missing_facts_and_next_checks"]] or ["None."]
    return "\n".join(lines)


def intelligence_md(r: dict, *, audience: str = "internal") -> str:
    ready = r["readiness"]
    lines = ["# Diagnosis summary", "",
             " · ".join(f"**{p.upper()}** {v['score'] if v['score'] is not None else '—'} ({v['band']}, "
                        f"{v['coverage']}% of checks verifiable)" for p, v in sorted(ready.items())), "",
             "## 1. Executive summary"]
    summary = r["executive_summary"].get(audience) or []
    lines += [" ".join(s["text"] + ("" if audience == "client" else f" [{', '.join(s['ids'])}]") for s in summary), ""]
    lines += ["## 2. Priorities"]
    for wave, label in (("now", "Now"), ("next", "Next"), ("later", "Later"),
                        ("investigate", "Investigate before recommending a fix"),
                        ("monitor", "Monitor: dated search and AI observations")):
        items = r["what_to_fix_first"].get(wave, [])
        if items:
            lines.append(f"### {label}")
            for i in items:
                lines.append(f"- **{i['id']}** [{i['severity']}, {i['confidence']}] {i['title']} — "
                             f"{str(len(i['pages'])) + ' page(s)' if i['pages'] else 'site-wide'}, "
                             f"agents {', '.join(i['agents'])}"
                             + (f", {len(i['patch_keys'])} proposed change(s)" if i["patch_keys"] else ""))
                if i.get("priority_reason"):
                    lines.append(f"  - Priority: {i['priority_reason']}")
    lines += ["", "## 3. What's working"] + [f"- {s['title']} ({s['agent']})" for s in r["whats_working"]]
    lines += ["", "## 4. What needs attention"] + [f"- ({a['kind']}) {a['title']} ({a['agent']})"
                                                     for a in r["what_needs_attention"]]
    lines += ["", "## 5. Possible shared patterns"]
    lines += [f"- **{c['id']} {c['title']}**: {len(c['items'])} items ({', '.join(c['items'])}) "
              + (f"across {c['pages']} page(s)" if c["pages"] else "site-wide")
              + f". Investigate whether one change addresses them: {c['fix']}"
              for c in r["root_causes_and_patterns"]] or ["None found."]
    plan = r["action_plan_and_blocked_work"]
    lines += ["", "## 6. Suggested action sequence (timing needs an estimate)",
              f"- Now: {', '.join(plan['now']) or '—'}",
              f"- Next: {', '.join(plan['next']) or '—'}",
              f"- Later: {', '.join(plan['later']) or '—'}"]
    lines += [f"- Facts to supply ({f['id']}, found by {', '.join(f['agents'])}): {', '.join(f['facts'])}"
              for f in plan.get("facts_to_supply", [])]
    lines += [f"- Blocked {b['id']}: {b['title']} (needs {', '.join(b['needs'])})" for b in plan["blocked"]]
    lines += [f"- Review prerequisites for {b['id']}: {', '.join(b['needs'])}"
              for b in plan.get("prerequisites_to_review", [])]
    if plan.get("investigate"):
        lines.append(f"- Verify before recommending: {', '.join(plan['investigate'])}")
    if plan.get("monitor"):
        lines.append(f"- Monitor separately: {', '.join(plan['monitor'])}")
    if r["coverage"]["notes"]:
        lines += ["", "### Coverage notes"] + [f"- {n}" for n in r["coverage"]["notes"][:12]]
    return "\n".join(lines)
