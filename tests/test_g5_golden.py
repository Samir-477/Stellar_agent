"""Golden tests for G5 AI Brand Accuracy: the key facts it expects come from the business type, not a hotel list."""

from types import SimpleNamespace

from engine.agents.geo.g05_brand_accuracy import AIBrandAccuracy, AnswerCheck, AnswerChecks, adds_to_a_list
from engine.context import AgentContext, ClientProfile
from engine.core.blobstore import LocalBlobStore
from engine.reports import check_statuses
from engine.schemas import CheckStatus as St, EvidenceType
from engine.store import MemoryStore, SnapshotReader, SnapshotWriter
from engine.validation import validate_result

B = "https://www.goldfin.example"


class StubLLM:
    """Answers the claim check: the business is named with specifics, and no claim is quoted."""

    def complete_json(self, prompt, model, **_):
        return SimpleNamespace(data=AnswerChecks(answers=[AnswerCheck(id="A1", mentions_business=True, specific=True)]))


def run(tmp_path, archetype: str, facts: list[tuple[str, str]]):
    store, blobs = MemoryStore(), LocalBlobStore(tmp_path / "b")
    snap = SnapshotWriter(store, blobs, "s")
    snap.add_evidence("C3", EvidenceType.ARCHETYPE, {"archetype": archetype})
    snap.add_evidence("C4", EvidenceType.FACTS, {"facts": [
        {"id": f"F{i}", "key": key, "value": value, "status": "site-stated", "source_url": f"{B}/"}
        for i, (key, value) in enumerate([("business_name", "GoldFin"), *facts])]})
    snap.add_evidence("C10", EvidenceType.AI_ANSWERS, {"surface": "probe", "label": "Model knowledge", "answers": [
        {"prompt_kind": "brand", "prompt": "Tell me about GoldFin.", "text": "GoldFin is a lender based in Kerala."}]})
    agent = AIBrandAccuracy()
    ctx = AgentContext(SnapshotReader(store, blobs, "s"), ClientProfile(id="c", name="GoldFin", primary_url=f"{B}/"),
                       StubLLM(), None)
    result = agent.run_unit(ctx, agent.plan(ctx)[0])
    result, errors = validate_result(agent, result, {f"{B}/"})
    assert errors == []
    return agent, {f.check_id: f for f in result.findings}, check_statuses(agent, result.findings)


def test_a_lender_is_checked_against_loan_facts_not_hotel_facts(tmp_path):
    agent, found, statuses = run(tmp_path, "loans", [("loan_types", "gold loan; personal loan"),
                                                     ("interest_rate_range", "9.9% to 24%"),
                                                     ("room_count", "40")])  # not a key fact for a lender
    assert statuses["G5.03"] == St.WARN  # the answer states neither loan fact
    excerpt = found["G5.03"].evidence[0].excerpt
    assert "0 of 2 key facts" in excerpt and "loan_types" in excerpt and "room_count" not in excerpt
    assert "loan types" in found["G5.02"].fix and "rooms" not in found["G5.02"].fix


def test_naming_more_products_than_the_site_lists_is_not_a_wrong_fact():
    offered = "Gold Loan; Home Loan; Business Loans"
    assert adds_to_a_list("offers gold loans, microfinance, and vehicle finance", offered)  # the list may be partial
    assert not adds_to_a_list("it only offers gold loans", offered)  # exclusive: can contradict
    assert not adds_to_a_list("it does not offer home loans", offered)
    assert not adds_to_a_list("a 40-room hotel", "24")  # a single value is compared as before


def test_no_key_facts_on_the_site_is_could_not_check_not_a_pass(tmp_path):
    agent, found, statuses = run(tmp_path, "retail", [("services", "online shopping")])
    assert statuses["G5.03"] == St.UNVERIFIABLE  # was a pass with "0 of 0 key facts" before
    assert found["G5.03"].title.startswith("No key facts for this type of business")
    assert statuses["G5.04"] == St.PASS  # the other checks still run
