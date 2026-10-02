import json

from engine.agents.aeo.a02_answer_structure import AnswerStructure
from engine.agents.seo.s03_metadata import SearchMetadata
from engine.collectors.c02_parser import parse_page
from engine.context import AgentContext, ClientProfile
from engine.core.blobstore import LocalBlobStore
from engine.reports import check_statuses
from engine.schemas import CheckStatus as St, EvidenceType
from engine.store import MemoryStore, PageRecord, SnapshotReader, SnapshotWriter
from tests.conftest import FakeLLM

URL = "https://hotel.example/agra"
DOC = """<!doctype html><html lang="en"><head><title>Home</title>
<meta name="description" content="Best hotel in the world with the lowest prices!"></head><body>
<h1>Grand Agra Hotel</h1>
<h2>Rooms</h2><p>Guests enjoy our warm hospitality. Grand Agra Hotel has 40 rooms in three categories, each with a
view of the Taj Mahal and a private balcony.</p>
<h2>Dining</h2><p>The rooftop restaurant serves Mughlai and continental food from 7 am to 11 pm for all guests,
with seating for sixty people and views across the city at sunset.</p>
</body></html>"""


def ctx_for(tmp_path, llm):
    store, blobs = MemoryStore(), LocalBlobStore(tmp_path / "b")
    snap = SnapshotWriter(store, blobs, "s")
    page = snap.add_page(PageRecord(id="p", snapshot_id="s", url=URL, final_url=URL, status=200))
    key = snap.put_blob("snapshots/s/pages/p/parsed.json", json.dumps(parse_page(DOC, URL)))
    snap.add_evidence("C2", EvidenceType.PAGES_PARSED, {}, page_id=page.id, blob_key=key)
    snap.add_evidence("C4", EvidenceType.FACTS, {"facts": [
        {"id": "F-001", "key": "room_count", "value": "40", "status": "site-stated", "source_url": URL}]})
    return AgentContext(SnapshotReader(store, blobs, "s"), ClientProfile(id="c", name="x", primary_url=URL), None, llm)


def test_s3_uses_llm_review_but_drops_ungrounded_or_overlong_drafts(tmp_path):
    llm = FakeLLM({"s3.metadata": {"pages": [{
        "url": URL, "title_verdict": "poor", "title_reason": "Says nothing about the hotel.",
        "description_verdict": "poor", "description_reason": "Overclaims.",
        "unsupported_claims": ["Best hotel in the world", "not in the description at all"],
        "titles": ["Grand Agra Hotel with 45 Taj-View Rooms | Grand",  # 45 isn't on the page → dropped
                   "Grand Agra Hotel: 40 Rooms with Taj Mahal Views"],
        "descriptions": ["Grand Agra Hotel has 40 rooms with Taj Mahal views and a rooftop restaurant serving "
                         "Mughlai food.", "x" * 200]}]}})
    ctx = ctx_for(tmp_path, llm)
    agent = SearchMetadata()
    result = agent.run_unit(ctx, agent.plan(ctx)[0])
    statuses = check_statuses(agent, result.findings)
    assert statuses["S3.03"] == St.FAIL and statuses["S3.06"] == St.FAIL
    title_patch = next(p for p in result.patches if p.key.startswith("S3:title"))
    assert title_patch.after == "Grand Agra Hotel: 40 Rooms with Taj Mahal Views"
    s306 = next(f for f in result.findings if f.check_id == "S3.06")
    assert "Best hotel in the world" in s306.evidence[0].excerpt and "not in the description" not in s306.evidence[0].excerpt


def test_s3_without_llm_marks_judgment_checks_unverifiable(tmp_path):
    ctx = ctx_for(tmp_path, None)
    result = SearchMetadata().run_unit(ctx, SearchMetadata().plan(ctx)[0])
    statuses = check_statuses(SearchMetadata(), result.findings)
    assert statuses["S3.03"] == St.UNVERIFIABLE and statuses["S3.02"] == St.WARN  # "Home" is too short


def test_a2_grounded_drafts_become_patches_and_invented_ones_dont(tmp_path):
    llm = FakeLLM({"a2.sections": {"sections": [
        {"id": "S1", "opening": "buried", "self_contained": True, "better_format": "none",
         "question": "What rooms does Grand Agra Hotel have?",
         "answer": "Grand Agra Hotel has 40 rooms in three categories. Each room has a view of the Taj Mahal and a "
                   "private balcony, and guests enjoy the hotel's warm hospitality throughout their stay in the rooms."},
        {"id": "S2", "opening": "direct", "self_contained": False, "better_format": "list",
         "question": "Where can I eat at Grand Agra Hotel?",
         "answer": "Grand Agra Hotel has a rooftop restaurant with a live band, a spa menu and 24-hour room service "
                   "offering Italian and Thai cuisine, plus a poolside bar open until 2 am every single night."}]}})
    ctx = ctx_for(tmp_path, llm)
    agent = AnswerStructure()
    result = agent.run_unit(ctx, agent.plan(ctx)[0])
    statuses = check_statuses(agent, result.findings)
    assert statuses["A2.01"] == St.FAIL and statuses["A2.03"] == St.WARN and statuses["A2.04"] == St.WARN
    assert [p.key.split(":")[1] for p in result.patches] == ["lead"]  # only the grounded Rooms draft
    assert "40 rooms" in result.patches[0].after
    assert any("fact guard" in limit for limit in result.coverage.limits)


def test_a2_drafts_no_issue_asks_for_are_not_proposed(tmp_path):
    """Regression (Flipkart run, 2026-09-29): a grounded draft for a section that already opens with its answer
    was attached to the question-headings finding; when that check passed there was nothing to attach it to,
    validation dropped the patch and the run finished "with gaps"."""
    from engine.validation import validate_result

    doc = DOC.replace("<h2>Rooms</h2>", "<h2>What rooms does Grand Agra Hotel have?</h2>")
    llm = FakeLLM({"a2.sections": {"sections": [
        {"id": "S1", "opening": "direct", "self_contained": True, "better_format": "none", "question": "", "answer": ""},
        {"id": "S2", "opening": "direct", "self_contained": True, "better_format": "none",
         "question": "Where can guests eat at Grand Agra Hotel?",
         "answer": "The rooftop restaurant at Grand Agra Hotel serves Mughlai and continental food from 7 am to 11 pm "
                   "for all guests, with seating for sixty people and views across the city at sunset."}]}})
    store, blobs = MemoryStore(), LocalBlobStore(tmp_path / "b")
    snap = SnapshotWriter(store, blobs, "s")
    page = snap.add_page(PageRecord(id="p", snapshot_id="s", url=URL, final_url=URL, status=200))
    snap.add_evidence("C2", EvidenceType.PAGES_PARSED, {}, page_id=page.id,
                      blob_key=snap.put_blob("snapshots/s/pages/p/parsed.json", json.dumps(parse_page(doc, URL))))
    ctx = AgentContext(SnapshotReader(store, blobs, "s"), ClientProfile(id="c", name="x", primary_url=URL), None, llm)
    agent = AnswerStructure()
    result, errors = validate_result(agent, agent.run_unit(ctx, agent.plan(ctx)[0]), {URL})
    assert check_statuses(agent, result.findings)["A2.02"] == St.PASS
    assert errors == [] and result.patches == []


def test_a2_rewrites_a_section_as_a_list_only_from_its_own_words(tmp_path):
    from engine.output.patcher import apply
    from engine.validation import validate_result

    def review(items):
        return FakeLLM({"a2.sections": {"sections": [
            {"id": "S1", "opening": "direct", "self_contained": True, "better_format": "none", "question": None, "answer": None},
            {"id": "S2", "opening": "direct", "self_contained": True, "better_format": "list", "question": None,
             "answer": None, "items": items}]}})

    agent = AnswerStructure()
    grounded = ["Rooftop restaurant serves Mughlai and continental food", "Serves food from 7 am to 11 pm for all guests",
                "Seating for sixty people, with views across the city at sunset"]
    ctx = ctx_for(tmp_path, review(grounded))
    result, errors = validate_result(agent, agent.run_unit(ctx, agent.plan(ctx)[0]), {URL})
    assert errors == []
    [listed] = result.patches
    assert listed.type.value == "element_replace" and listed.approval == "required" and listed.after.startswith("<ul><li>")
    assert {f.check_id: f for f in result.findings}["A2.04"].patch_keys == [listed.key]
    fixed = apply(DOC, URL, [listed.model_dump(mode="json")]).fixed_html
    assert "<li>Serves food from 7 am to 11 pm for all guests</li>" in fixed and "seating for sixty people and views" not in fixed

    invented = grounded[:2] + ["Live jazz band every Friday night"]  # not in the section
    ctx = ctx_for(tmp_path / "2", review(invented))
    assert agent.run_unit(ctx, agent.plan(ctx)[0]).patches == []
