from engine.intelligence import _valid, Sentence, build_work_items, readiness, root_causes
from engine.schemas import CheckStatus as St, Confidence, Effort, EvidenceRef, Finding, Pillar, Scope, Severity


def f(agent, check, status, severity=None, pages=("https://x/a",), effort=Effort.S, missing=(), patches=(),
      confidence=Confidence.CONFIRMED, pillar=Pillar.SEO):
    return Finding(agent_id=agent, agent_version="1", check_id=check, pillar=pillar, title=f"{check} issue",
                   status=status, severity=severity, confidence=confidence, scope=Scope(level="page", pages=list(pages)),
                   evidence=[EvidenceRef(type="x", excerpt="e")], effort=effort, missing_facts=list(missing),
                   patch_keys=list(patches))


def test_readiness_weights_and_critical_cap():
    findings = {"S1": [f("S1", "S1.04", St.FAIL, Severity.CRITICAL)] +
                      [f("S1", c, St.PASS) for c in ("S1.01", "S1.02", "S1.03", "S1.05", "S1.06", "S1.07", "S1.08",
                                                     "S1.09", "S1.10", "S1.11")]}
    ready = readiness(findings)["seo"]
    assert ready["capped_by_critical"] and ready["score"] <= 49 and ready["coverage"] == 100


def test_same_issue_from_two_findings_becomes_one_item_and_impact_sets_the_lane():
    a = f("S8", "S8.04", St.FAIL, Severity.HIGH, patches=["p1"], missing=["address"])
    b = f("S8", "S8.04", St.FAIL, Severity.HIGH)  # same fingerprint → merged
    c = f("G1", "G1.04", St.FAIL, Severity.HIGH, effort=Effort.L, pillar=Pillar.GEO)
    d = f("S3", "S3.02", St.WARN, Severity.LOW)
    e = f("S3", "S3.03", St.WARN, Severity.MEDIUM, missing=["property name"])  # no patch → blocked
    items = build_work_items([a, b, c, d, e], {"https://x/a"})
    assert len(items) == 4
    waves = {i.check_ids[0]: i.wave for i in items}
    assert waves == {"S8.04": "now", "G1.04": "now", "S3.02": "later", "S3.03": "next"}
    assert next(i for i in items if i.check_ids == ["S3.03"]).prerequisite_review
    assert items[0].check_ids == ["S8.04"]  # highest priority first


def test_matrix_separates_likely_hypothetical_and_dated_observations():
    items = build_work_items([
        f("S1", "S1.06", St.FAIL, Severity.CRITICAL, confidence=Confidence.LIKELY),
        f("G1", "G1.04", St.WARN, Severity.HIGH, pillar=Pillar.GEO, confidence=Confidence.LIKELY),
        f("G2", "G2.02", St.WARN, Severity.HIGH, pillar=Pillar.GEO, confidence=Confidence.HYPOTHESIS),
        f("G3", "G3.01", St.WARN, Severity.HIGH, pillar=Pillar.GEO),
    ], {"https://x/a"})
    lanes = {i.check_ids[0]: i.wave for i in items}
    assert lanes == {"S1.06": "now", "G1.04": "next", "G2.02": "investigate", "G3.01": "monitor"}
    assert [i.check_ids[0] for i in items] == ["S1.06", "G1.04", "G2.02", "G3.01"]


def test_missing_facts_do_not_automatically_block_an_action():
    from engine.intelligence import build_intelligence_report

    issue = f("S5", "S5.01", St.FAIL, Severity.MEDIUM,
              missing=["a page for hotels with private pools"])
    report = build_intelligence_report({"S5": [issue]}, {"https://x/a"}, [], None)
    item = report["what_to_fix_first"]["next"][0]
    assert item["prerequisite_review"] and item["check_ids"] == ["S5.01"]
    assert report["action_plan_and_blocked_work"]["blocked"] == []
    assert report["action_plan_and_blocked_work"]["prerequisites_to_review"][0]["id"] == item["id"]


def test_observation_only_run_has_no_action_plan_or_lead_blocker():
    from engine.intelligence import build_intelligence_report

    observed = f("G3", "G3.01", St.WARN, Severity.HIGH, pillar=Pillar.GEO)
    report = build_intelligence_report({"G3": [observed]}, set(), [], None)
    assert report["what_to_fix_first"]["now"] == []
    assert report["what_to_fix_first"]["monitor"][0]["agents"] == ["G3"]
    assert report["leads"]["blocker"] is None
    assert report["action_plan_and_blocked_work"]["now"] == []
    assert "not a verified site fix" in report["executive_summary"]["client"][0]["text"]


def test_root_causes_group_related_checks():
    items = build_work_items([f("S3", "S3.03", St.WARN, Severity.MEDIUM), f("S3", "S3.05", St.WARN, Severity.LOW,
                                                                              pages=("https://x/b",))], set())
    causes = root_causes(items)
    assert causes[0]["cause"] == "metadata-template" and set(causes[0]["items"]) == {i.id for i in items}


def test_summary_sentences_need_known_ids_and_real_numbers():
    data = "READINESS: seo=62\nW1 [high, now] Fix schema | pages: 3"
    kept = _valid([Sentence(text="SEO readiness is 62.", ids=["READINESS"]),
                   Sentence(text="Fix schema on 3 pages.", ids=["W1"]),
                   Sentence(text="Fix schema on 9 pages.", ids=["W1"]),        # 9 isn't in the data
                   Sentence(text="Traffic will double.", ids=["W99"])], {"READINESS", "W1"}, data)
    assert [k["text"] for k in kept] == ["SEO readiness is 62.", "Fix schema on 3 pages."]


def test_the_same_missing_facts_from_several_agents_become_one_item():
    a1 = f("A1", "A1.04", St.WARN, Severity.MEDIUM, missing=["price", "reviews", "check-in"], pillar=Pillar.AEO)
    s4 = f("S4", "S4.05", St.WARN, Severity.MEDIUM, missing=["prices and rates", "guest ratings and reviews"])
    s10 = f("S10", "S10.05", St.WARN, Severity.HIGH, missing=["cancellation and refund policy",
                                                             "check-in and check-out times"])
    mixed = f("A1", "A1.01", St.FAIL, Severity.HIGH, missing=["Which hotels have a Taj view?: needs view details",
                                                            "Budget hotels near the Taj: needs price range"],
              patches=["draft"], pillar=Pillar.AEO)
    other = f("S3", "S3.03", St.WARN, Severity.MEDIUM, missing=["property name"])  # a topic nobody else reports
    items = build_work_items([a1, s4, s10, mixed, other], {"https://x/a"})
    facts = [i for i in items if i.facts]
    assert len(facts) == 1 and facts[0].wave == "now"
    assert facts[0].facts[:3] == ["check-in and check-out times", "prices", "reviews"]  # shared topics first
    assert "cancellation and refunds" in facts[0].facts
    assert set(facts[0].check_ids) == {"A1.04", "S4.05", "S10.05"} and set(facts[0].agents) == {"A1", "S4", "S10"}
    # A1.01 also lists a gap outside the lexicon, so it stays its own item (it still corroborated "prices").
    assert any(i.check_ids == ["A1.01"] for i in items) and any(i.check_ids == ["S3.03"] for i in items)


def test_corroboration_keeps_the_weaker_confidence_and_observations_separate():
    a = f("A1", "A1.04", St.WARN, Severity.MEDIUM, missing=["prices"], pillar=Pillar.AEO,
          confidence=Confidence.CONFIRMED)
    b = f("S10", "S10.08", St.WARN, Severity.MEDIUM, missing=["prices"],
          confidence=Confidence.LIKELY)
    observed = f("G3", "G3.01", St.WARN, Severity.HIGH, missing=["prices"], pillar=Pillar.GEO)
    items = build_work_items([a, b, observed], set())
    merged = next(i for i in items if i.facts)
    assert merged.agents == ["A1", "S10"]
    assert merged.confidence == "likely" and merged.wave == "next"
    assert next(i for i in items if i.agents == ["G3"]).wave == "monitor"


def test_observations_get_their_own_digest_block():
    from engine.intelligence import digest
    scored = [f("S3", "S3.03", St.WARN, Severity.MEDIUM, patches=["p"]) for _ in range(1)]
    observed = f("G3", "G3.01", St.WARN, Severity.HIGH, effort=Effort.L, pillar=Pillar.GEO)
    items = build_work_items(scored + [observed], set())
    assert [i.observation for i in items if i.check_ids == ["G3.01"]] == [True]
    text = digest({"seo": {"score": 60, "coverage": 90}}, items, [], [], [])
    assert text.index("OBSERVATIONS") < text.index("G3.01 issue")


def test_entry_page_issues_outrank_equal_issues_elsewhere_and_leads_are_rule_based():
    from engine.intelligence import leads
    entry = f("S8", "S8.04", St.FAIL, Severity.HIGH, pages=("https://x/agra",), patches=["p"])
    elsewhere = f("S1", "S1.01", St.FAIL, Severity.HIGH, pages=("https://x/old-1", "https://x/old-2"))
    facts_a = f("A1", "A1.04", St.WARN, Severity.MEDIUM, missing=["prices"], pillar=Pillar.AEO)
    facts_b = f("S10", "S10.08", St.WARN, Severity.MEDIUM, missing=["taxes and fees shown with prices"])
    seen = f("G3", "G3.01", St.WARN, Severity.HIGH, effort=Effort.L, pillar=Pillar.GEO)
    items = build_work_items([elsewhere, entry, facts_a, facts_b, seen], set(), entry_url="https://x/agra")
    assert items[0].check_ids == ["S8.04"]  # the entry page first, although the other issue spans 2 pages
    lead = leads(items, [])
    by_id = {i.id: i for i in items}
    assert by_id[lead["blocker"]].check_ids == ["S8.04"]
    assert by_id[lead["opportunity"]].facts == ["prices"]
    assert by_id[lead["observation"]].check_ids == ["G3.01"]


def test_the_lead_blocker_is_the_costliest_issue_not_the_quickest_win():
    from engine.intelligence import leads
    quick = f("S3", "S3.03", St.WARN, Severity.HIGH, pages=tuple(f"https://x/{n}" for n in "abcd"), effort=Effort.S)
    template = f("S8", "S8.06", St.WARN, Severity.MEDIUM, pages=tuple(f"https://x/p{n}" for n in range(22)))
    costly = f("S2", "S2.03", St.FAIL, Severity.HIGH, pages=("https://x/agra",), effort=Effort.M)
    items = build_work_items([quick, costly, template], set(), entry_url="https://x/agra")
    assert items[0].check_ids == ["S3.03"]  # the work list puts the quick win first
    blocker = next(i for i in items if i.id == leads(items, [])["blocker"])
    assert blocker.check_ids == ["S2.03"]  # a failure on the entry page costs the most


def test_the_lead_blocker_comes_from_the_first_lane_with_fixes():
    # Shivalik Chail: a likely JavaScript-content issue on 6 pages (Next) costs more than a confirmed
    # schema issue on 1 page (Now), yet the headline must not tell the reader to start outside Now.
    from engine.intelligence import leads
    widespread = f("G1", "G1.04", St.FAIL, Severity.HIGH, pages=tuple(f"https://x/{n}" for n in range(6)),
                   pillar=Pillar.GEO, confidence=Confidence.LIKELY)
    confirmed = f("S8", "S8.01", St.FAIL, Severity.HIGH, pages=("https://x/contact",))
    items = build_work_items([widespread, confirmed], set())
    by_check = {i.check_ids[0]: i for i in items}
    assert by_check["G1.04"].wave == "next" and by_check["G1.04"].harm > by_check["S8.01"].harm
    assert leads(items, [])["blocker"] == by_check["S8.01"].id
    # With nothing in Now, the costliest Next item leads.
    only_next = build_work_items([widespread], set())
    assert leads(only_next, [])["blocker"] == only_next[0].id


def test_client_cards_lead_with_the_blocker_and_fall_back_to_the_agents_words():
    from engine.intelligence import build_intelligence_report
    blocker = f("S8", "S8.04", St.FAIL, Severity.HIGH, pages=("https://x/agra",))
    blocker.impact = "Search engines read another hotel's details."
    other = f("S3", "S3.03", St.WARN, Severity.MEDIUM)
    report = build_intelligence_report({"S8": [blocker], "S3": [other]}, set(), [], None, entry_url="https://x/agra")
    cards = report["executive_summary"]["client_priorities"]
    assert cards[0]["check_ids"] == ["S8.04"] and cards[0]["id"] == report["leads"]["blocker"]
    assert cards[0]["why"] == "Search engines read another hotel's details." and cards[0]["source"] == "rules"


def test_model_cards_are_kept_only_for_known_ids_and_real_numbers():
    from engine.intelligence import PriorityCard, _valid_cards, client_cards
    items = build_work_items([f("S3", "S3.03", St.FAIL, Severity.HIGH, pages=("https://x/a", "https://x/b"))], set())
    data = "TOP FIXES\nW1 | severity high | pages 2 | problem: titles"
    worded = _valid_cards([PriorityCard(id="W1", headline="2 page titles are unclear", why="Fewer clicks.", action="Rewrite them."),
                           PriorityCard(id="W9", headline="Invented", action="Do it."),
                           PriorityCard(id="W1", headline="Duplicate", action="Ignore.")], items, data)
    assert list(worded) == ["W1"] and worded["W1"]["headline"] == "2 page titles are unclear"
    assert not _valid_cards([PriorityCard(id="W1", headline="7 titles are unclear", action="Fix.")], items, data)
    assert client_cards(items, worded)[0]["source"] == "model" and client_cards(items)[0]["source"] == "rules"
