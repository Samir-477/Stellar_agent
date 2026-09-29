"""Why a run "finished with gaps", and which checks it couldn't run, each with a suggested fix and who acts on it
(user decision, 2026-09-29). Read from the run's own tasks and findings, so it works for every run, old or new.

`who` is "rerun" (running the diagnosis again closes it), "us" (a platform fix or a feature not built yet) or
"you" (the business supplies or publishes something first).
"""

from __future__ import annotations

import re

from engine.plain import entry
from engine.registry import AGENTS, COLLECTORS

# Validation errors from bugs fixed since: re-running the agent gives its full result.
FIXED = (re.compile(r"S6\.01 warn has no evidence"), re.compile(r"^patch A2:lead:.* is not referenced by any finding"))

COLLECTOR_FIX = {
    "C1": "Check that the site is online and doesn't block our crawler, then run the diagnosis again.",
    "C2": "Run the diagnosis again; if it fails again, our team looks into the page that broke it.",
    "C11": "Google's page-speed service didn't answer in time. Run the diagnosis again later.",
}
SEARCH_COLLECTORS = {"C6", "C7", "C8", "C12"}  # outside search-data services with quotas
AI_COLLECTORS = {"C3", "C4", "C5", "C9", "C10"}  # steps that need the AI model


def _name(ref: str | None) -> str:
    if ref in AGENTS:
        return AGENTS[ref].name
    if ref in COLLECTORS:
        return COLLECTORS[ref].name
    return ref or "A step"


def _first_line(text: str | None) -> str:
    return (text or "").strip().splitlines()[0][:200] if text else ""


def step_gaps(tasks: list[dict]) -> list[dict]:
    """Each run step that didn't fully succeed: what happened, the suggested fix, and who acts."""
    out = []
    for t in tasks:
        kind, ref, status = t["kind"], t.get("ref"), t["status"]
        if status == "succeeded" or kind in ("run.finalize", "collector.unit", "agent.unit"):
            continue
        name = _name(ref)
        if kind == "agent.reduce" and status == "partial":
            errors = t.get("validation_errors") or [e for e in (t.get("error") or "").split("; ") if e]
            fixed = bool(errors) and all(any(p.search(e) for p in FIXED) for e in errors)
            out.append({
                "step": ref, "name": name, "status": status,
                "title": f"Part of {name}'s results were set aside",
                "what_happened": f"Our quality checks set aside {len(errors) or 'some'} incomplete "
                                 f"item{'s' if len(errors) != 1 else ''} from this agent's results. The rest of "
                                 "its report is complete and can be used as it is.",
                "fix": ("This was a platform issue that is now fixed. Run this agent again to get its full result."
                        if fixed else "Our team reviews why these items were incomplete. Nothing is needed from you."),
                "who": "rerun" if fixed else "us", "detail": errors[:3],
            })
        elif status == "skipped":
            out.append({"step": ref, "name": name, "status": status, "title": f"{name} was skipped",
                        "what_happened": "An earlier step it depends on didn't finish, so it couldn't start.",
                        "fix": "It runs once the earlier step succeeds: run the diagnosis again.", "who": "rerun",
                        "detail": [_first_line(t.get("error"))] if t.get("error") else []})
        elif status in ("failed", "partial"):
            if kind == "run.intelligence":
                title, fix, who = ("The summary wasn't built",
                                   "Our team can rebuild the summary from this run's results without a new crawl.", "us")
            elif kind.startswith("collector."):
                fix = COLLECTOR_FIX.get(ref) or (
                    "A search-data service failed or hit its limit. Run the diagnosis again later."
                    if ref in SEARCH_COLLECTORS else
                    "The AI review step didn't finish. Run the diagnosis again." if ref in AI_COLLECTORS else
                    "Run the diagnosis again.")
                title, who = f"{name} didn't finish", "rerun"
            else:
                title, fix, who = (f"{name} didn't finish",
                                   "Run this agent again. If it fails again, our team looks into it.", "rerun")
            out.append({"step": ref, "name": name, "status": status, "title": title,
                        "what_happened": _first_line(t.get("error")) or "The step stopped before it finished.",
                        "fix": fix, "who": who, "detail": []})
    return out


# Why a check couldn't run, most specific first: (cause, pattern over its title, title, explanation, fix, who).
CAUSES = (
    ("renderer", re.compile(r"rendered html|after javascript|javascript runs", re.I),
     "Needs the page as a browser shows it",
     "These checks need the page after its code has run, and the platform doesn't render pages yet.",
     "A page renderer is planned. Until it's added, these checks stay open.", "us"),
    ("cited", re.compile(r"cited pages|cited-page", re.I),
     "Needs the pages AI answers cite",
     "These checks look at the pages AI assistants cite in their answers, and the platform doesn't collect those "
     "pages yet.",
     "Nothing to do now: collecting cited pages is on our roadmap.", "us"),
    ("competitors", re.compile(r"competitor|\(C8\)|ranking domains", re.I),
     "Needs competitors' pages",
     "These checks compare your pages with competitors' pages, and none were collected in this run.",
     "Run the diagnosis again with AI review on: the competitors come from the customer searches it builds.",
     "rerun"),
    ("sample", re.compile(r"(wasn't|was not|not) in the sample", re.I),
     "The page wasn't among the pages we read",
     "The page these checks need is linked from the site, but it wasn't in the sample of pages this run read.",
     "Run the diagnosis again with a higher Pages number (up to 100) so the page is more likely to be read.",
     "rerun"),
    ("version", re.compile(r"in this version", re.I),
     "Not available yet",
     "This check isn't built in the current version of the platform.",
     "Nothing to do now: it's on our roadmap.", "us"),
    ("offsite", re.compile(r"only the site's own details", re.I),
     "Not enough outside information to compare",
     "The business's details were found only on its own site, not in its structured data, on Google Maps or in "
     "Google's knowledge panel, so there was nothing to compare them with.",
     "Add the business details to the site's structured data and complete the Google Business Profile, then run "
     "the diagnosis again.", "you"),
    ("ai", re.compile(r"llm|not reviewed|not judged|not mapped|no category answers|not compared|not classified|"
                      r"no search results|only brand searches", re.I),
     "AI review didn't cover these checks", "", "", "rerun"),
)
OTHER = ("other", None, "Too little evidence", "These checks didn't have enough evidence in this run.",
         "Run the diagnosis again.", "rerun")


def check_gaps(findings: list[dict], model_calls: int) -> list[dict]:
    """Checks the run couldn't complete, grouped by cause, each group with its explanation and suggested fix."""
    groups: dict[str, dict] = {}
    for f in findings:
        if f["status"] != "unverifiable":
            continue
        cause, _, title, explanation, fix, who = next((c for c in CAUSES if c[1].search(f["title"])), OTHER)
        if cause == "competitors" and model_calls:
            fix = "Competitors' pages weren't collected even with AI review on. Run the diagnosis again; if it "                   "repeats, our team checks the search data."
        if cause == "ai":
            explanation = ("AI review was switched off when this run ran, so the checks that need judgment weren't done."
                           if model_calls == 0 else
                           "The AI review didn't give a usable answer for these checks in this run.")
            fix = ("Run the diagnosis again: AI review is on now." if model_calls == 0 else
                   "Run the agents involved again. If it repeats, our team reviews it.")
        group = groups.setdefault(cause, {"cause": cause, "title": title, "explanation": explanation, "fix": fix,
                                          "who": who, "items": []})
        plain = entry(f["check_id"])
        group["items"].append({"check_id": f["check_id"], "agent": f["agent_id"], "title": f["title"],
                               "name": plain.name if plain else f["title"]})
    order = [c[0] for c in CAUSES] + ["other"]
    return sorted(groups.values(), key=lambda g: order.index(g["cause"]))


def run_gaps(status: str, tasks: list[dict], findings: list[dict], model_calls: int) -> dict:
    return {"status": status, "model_calls": model_calls, "steps": step_gaps(tasks),
            "checks": check_gaps(findings, model_calls)}
