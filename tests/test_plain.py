"""Plain-language explanations (engine/plain.py): complete, jargon-free and never made up."""

from types import SimpleNamespace

from engine.llm import LLMError
from engine.plain import LIBRARY, Case, Cases, explain, issue_key, site_cases, terms_in, valid_case
from engine.fix_steps import STEPS, pages_phrase
from engine.registry import AGENTS

INP = {"agent_id": "S2", "agent_version": "1", "check_id": "S2.02", "pillar": "seo", "status": "fail",
       "severity": "high", "title": "INP poor on 3 of 5 measured page(s)",
       "scope": {"level": "site", "pages": ["https://x.example/gold-loan", "https://x.example/top-up",
                                            "https://x.example/"]},
       "evidence": [{"type": "metric", "url": "https://x.example/gold-loan", "excerpt": "INP 1.0 s (page field data)"}],
       "impact": "INP is a Core Web Vital.", "fix": "Cut main-thread work."}


def test_every_check_has_a_complete_plain_entry():
    checks = {c.id for agent in AGENTS.values() for c in agent.checks}
    assert checks == set(LIBRARY)
    for check_id, entry in LIBRARY.items():
        for field in ("name", "problem", "meaning", "why", "analogy", "action"):
            assert getattr(entry, field).strip(), (check_id, field)
        # The plain problem heading never uses the metric shorthand the technical title does.
        assert not any(term in entry.problem for term in ("INP", "LCP", "CLS", "TTFB", "JSON-LD", "SERP")), check_id


def test_every_check_has_fix_steps_with_an_owner():
    assert set(STEPS) == set(LIBRARY)
    for check_id, fix in STEPS.items():
        assert fix.owner and 2 <= len(fix.steps) <= 4, check_id
        assert all(s.strip().endswith((".", ")")) for s in fix.steps), check_id


def test_fix_steps_name_the_issue_s_own_pages():
    plain = explain(INP)
    assert plain["owner"] == "Developer"
    assert plain["steps"][0].startswith("Open /gold-loan, /top-up and 1 more in PageSpeed Insights")
    assert pages_phrase([]) == "the affected pages" and pages_phrase(["https://x.example/"]) == "x.example"
    assert explain({**INP, "check_id": "Z9.99"})["steps"] == []  # an unknown check gets no invented steps


def test_explanation_carries_the_library_the_site_case_and_the_terms():
    plain = explain(INP)
    assert plain["problem"] == "Pages react slowly when visitors tap or click"
    assert "lift" in plain["analogy"]
    assert plain["case_source"] == "rules" and "/gold-loan" in plain["site_case"]
    assert {t["term"] for t in plain["terms"]} >= {"INP", "Core Web Vitals", "Field data"}
    assert "HTTPS" not in {t["term"] for t in terms_in("see https://x.example/a")}  # web addresses aren't the term
    assert explain(INP, "Your /gold-loan page takes 1.0 s to react.")["case_source"] == "model"


def test_a_site_case_may_only_use_this_issue_s_numbers_and_pages_and_no_shorthand():
    line = "I1 | finding: INP poor on 3 of 5 measured page(s) | pages: /gold-loan, /top-up | evidence: INP 1.0 s"
    assert valid_case("On 3 of the 5 pages we measured, including /gold-loan, a tap takes about 1.0 s to answer.", line)
    assert not valid_case("Your /gold-loan page takes 1.0 s; Google wants under 0.2 s.", line)  # invented number
    assert not valid_case("Your /pricing page reacts slowly.", line)  # a page that isn't in the data
    assert not valid_case("Your pages have poor INP on 3 of 5 pages.", line)  # shorthand
    assert valid_case("3 of 5 pages react slowly to taps (a measure Google calls INP).", line)  # explained in brackets


def test_site_cases_keep_valid_sentences_and_drop_the_rest():
    key = issue_key(INP)

    class FakeLLM:
        def complete_json(self, prompt, model, **variables):
            assert "I1 |" in variables["issues"] and "/gold-loan" in variables["issues"]
            return SimpleNamespace(data=Cases(cases=[
                Case(id="I1", text="On 3 of the 5 pages we measured, such as /gold-loan, a tap takes about 1.0 s to answer."),
                Case(id="I9", text="An issue that doesn't exist.")]))

    assert site_cases(FakeLLM(), [INP]) == {key: "On 3 of the 5 pages we measured, such as /gold-loan, a tap takes about 1.0 s to answer."}

    class Invented(FakeLLM):
        def complete_json(self, prompt, model, **variables):
            return SimpleNamespace(data=Cases(cases=[Case(id="I1", text="Your site is 7 times slower than rivals.")]))

    assert site_cases(Invented(), [INP]) == {}  # rejected; the template sentence is used instead

    class Down(FakeLLM):
        def complete_json(self, prompt, model, **variables):
            raise LLMError("provider unavailable")

    assert site_cases(Down(), [INP]) == {} and site_cases(None, [INP]) == {}
