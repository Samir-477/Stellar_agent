"""Microsites published before plain words and fix steps existed get them from their run when served."""

from engine.output import microsite

FINDING = {"agent_id": "S2", "check_id": "S2.02", "status": "fail", "title": "INP poor on 3 of 5 measured page(s)",
           "scope": {"pages": ["https://x.example/gold-loan"]}, "fix": "Cut main-thread work.",
           "verification": "INP at or under 200 ms.", "effort": "M",
           "evidence": [{"url": "https://x.example/gold-loan", "excerpt": "INP 1.0 s (page field data)"}]}
OLD = {"agent_id": "S2", "check_id": "S2.02", "title": "INP poor on 3 of 5 measured page(s)", "status": "fail",
       "fix": "Cut main-thread work.", "impact": "", "fix_type": "action", "fixed": False, "changes": []}


def test_an_old_microsite_gets_plain_words_and_steps_from_its_run(monkeypatch):
    monkeypatch.setattr(microsite.repo, "run_exists", lambda run_id: True)
    monkeypatch.setattr(microsite.repo, "list_findings", lambda run_id: [FINDING])
    monkeypatch.setattr(microsite.repo, "get_intelligence_report", lambda run_id: {})
    issue = microsite.complete_issues({"run_id": "r1", "issues": [OLD]})["issues"][0]
    assert issue["plain"]["problem"] == "Pages react slowly when visitors tap or click"
    assert issue["plain"]["steps"][0].startswith("Open /gold-loan in PageSpeed Insights")
    assert "/gold-loan" in issue["plain"]["site_case"]
    assert issue["verification"] == "INP at or under 200 ms." and issue["effort"] == "M"
    assert issue["fix"] == OLD["fix"] and issue["fixed"] is False  # what was published is unchanged


def test_without_its_run_a_microsite_gets_the_library_words_but_no_site_sentence(monkeypatch):
    monkeypatch.setattr(microsite.repo, "run_exists", lambda run_id: False)
    issue = microsite.complete_issues({"run_id": "gone", "issues": [OLD]})["issues"][0]
    assert issue["plain"]["steps"] and issue["plain"]["site_case"] == ""


def test_a_current_microsite_is_served_as_published(monkeypatch):
    current = {**OLD, "plain": {"problem": "p", "steps": ["one"]}}
    monkeypatch.setattr(microsite.repo, "list_findings", lambda run_id: 1 / 0)  # never queried
    assert microsite.complete_issues({"run_id": "r1", "issues": [current]})["issues"] == [current]
