"""Run gaps: why a run finished with gaps and which checks it couldn't run, with a suggested fix for each."""

from engine.gaps import check_gaps, step_gaps


def finding(check_id, title, agent="S3"):
    return {"check_id": check_id, "agent_id": agent, "status": "unverifiable", "title": title}


def test_a_partial_agent_from_a_fixed_bug_says_to_run_it_again():
    steps = step_gaps([
        {"kind": "agent.reduce", "ref": "A2", "status": "partial", "error": None,
         "validation_errors": ["patch A2:lead:abc:0 is not referenced by any finding"]},
        {"kind": "agent.reduce", "ref": "S8", "status": "partial", "validation_errors": ["S8.02 fail has no severity"]},
        {"kind": "collector.done", "ref": "C11", "status": "failed", "error": "ReadTimeout: pagespeed\ntrace"},
        {"kind": "agent.plan", "ref": "S5", "status": "skipped", "error": "an upstream step failed"},
        {"kind": "run.finalize", "ref": None, "status": "failed"},
    ])
    a2, s8, c11, s5 = steps
    assert a2["who"] == "rerun" and "now fixed" in a2["fix"] and a2["title"].startswith("Part of")
    assert s8["who"] == "us"  # not a known, fixed bug
    assert c11["who"] == "rerun" and "page-speed" in c11["fix"] and c11["what_happened"] == "ReadTimeout: pagespeed"
    assert s5["title"].endswith("was skipped")
    assert len(steps) == 4  # the finalize step is bookkeeping, not a gap


def test_checks_are_grouped_by_cause_with_a_fix_that_fits_the_run():
    found = [finding("G1.05", "Needs rendered HTML to tell whether key facts appear only after JavaScript", "G1"),
             finding("S6.04", "No competitor pages fetched (C8)", "S6"),
             finding("G4.04", "What cited pages have in common needs the pages themselves (competitor and "
                              "cited-page capture, C8)", "G4"),
             finding("S10.01", "About page is linked but wasn't in the sample", "S10"),
             finding("A1.03", "Accuracy against the Fact Sheet is not checked in this version", "A1"),
             finding("S3.03", "Title relevance not judged (LLM unavailable)"),
             finding("G3.01", "No category answers captured", "G3")]
    groups = {g["cause"]: g for g in check_gaps(found, model_calls=0)}
    assert list(groups) == ["renderer", "cited", "competitors", "sample", "version", "ai"]
    assert groups["cited"]["who"] == "us" and len(groups["competitors"]["items"]) == 1
    assert "AI review on" in groups["competitors"]["fix"]
    assert groups["ai"]["fix"] == "Run the diagnosis again: AI review is on now." and len(groups["ai"]["items"]) == 2
    assert groups["ai"]["items"][0]["name"] == "Titles describe their page"  # the plain name
    with_ai = {g["cause"]: g for g in check_gaps(found, 12)}
    assert "didn't give a usable answer" in with_ai["ai"]["explanation"]
    assert "even with AI review on" in with_ai["competitors"]["fix"]
