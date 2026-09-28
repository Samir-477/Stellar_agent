"""Golden tests for G3 AI Share of Voice (observation): planted answers → statuses."""

from engine.agents.geo.g03_share_of_voice import AIShareOfVoice
from engine.context import AgentContext, ClientProfile
from engine.core.blobstore import LocalBlobStore
from engine.reports import check_statuses
from engine.schemas import CheckStatus as St, EvidenceType
from engine.store import MemoryStore, SnapshotReader, SnapshotWriter
from engine.validation import validate_result
from tests.conftest import FakeLLM

Q1 = "What are the best hotels near the Taj Mahal in Agra?"
Q2 = "Which Agra hotels have a pool with a Taj view?"
ANSWERS = {
    "deepseek": [(Q1, "Top picks: **The Oberoi Amarvilas** (every room faces the Taj) and **ITC Mughal**. "
                      "**Grand Agra** is a budget-friendly option 1.4 km away."),
                 (Q2, "The Oberoi Amarvilas has an infinity pool; Taj Agra has a rooftop pool.")],
    "groq": [(Q1, "The Oberoi Amarvilas and Taj Agra lead most lists."),
             (Q2, "Try Taj Agra for its rooftop infinity pool facing the monument.")],
}


def build(tmp_path):
    store, blobs = MemoryStore(), LocalBlobStore(tmp_path / "b")
    snap = SnapshotWriter(store, blobs, "s")
    snap.add_evidence("C4", EvidenceType.FACTS, {"facts": [
        {"key": "city", "value": "Agra", "quote": "Agra", "source_url": "https://grand.example/", "status": "site-stated"}]})
    for surface, pairs in ANSWERS.items():
        snap.add_evidence("C10", EvidenceType.AI_ANSWERS, {"surface": surface, "answers": [
            {"surface": surface, "prompt": q, "prompt_kind": "category", "text": t, "captured_at": "2026-09-28"}
            for q, t in pairs]})
        snap.add_evidence("C10", EvidenceType.AI_ANSWERS, {"surface": surface, "answers": [
            {"surface": surface, "prompt": "Tell me about Grand Agra.", "prompt_kind": "brand",
             "text": "Grand Agra is a hotel in Agra."}]})  # brand prompts don't count
    return SnapshotReader(store, blobs, "s")


def answer(v):
    out = []
    for line in v["answers"].splitlines():
        aid, text = line.split(" ", 1)[0], line
        names = [n for n in ("The Oberoi Amarvilas", "ITC Mughal", "Grand Agra", "Taj Agra") if n in text]
        names += ["Hotel Imaginary"] if aid == "A1" else []  # not in the answer: must be dropped
        framing = "neutral" if "Grand Agra" in text else "none"
        out.append({"id": aid, "businesses": names, "framing": framing,
                    "quote": "Grand Agra** is a budget-friendly option 1.4 km away" if framing != "none" else None})
    return {"answers": out}


def test_g3_share_of_voice_from_planted_answers(tmp_path):
    agent = AIShareOfVoice()
    ctx = AgentContext(build(tmp_path), ClientProfile(id="c", name="Grand Agra", primary_url="https://grand.example/"),
                       None, FakeLLM({"g3.mentions": answer}))
    result = agent.run_unit(ctx, agent.plan(ctx)[0])
    result, errors = validate_result(agent, result, set())
    assert errors == []
    assert check_statuses(agent, result.findings) == {
        "G3.01": St.PASS,  # named once (DeepSeek, Q1)
        "G3.02": St.WARN,  # competitors named in 3 answers without the client
        "G3.03": St.WARN,  # listed after the Oberoi and ITC Mughal
        "G3.04": St.PASS,  # neutral
        "G3.05": St.WARN,  # DeepSeek names the client for Q1, Groq doesn't
    }
    competitors = next(f for f in result.findings if f.check_id == "G3.02")
    assert "The Oberoi Amarvilas" in competitors.title and "Imaginary" not in competitors.title
    assert any("weren't in the answer text" in limit for limit in result.coverage.limits)
    rows = {(r[0][:20], r[1]): r for r in result.signature_table["rows"]}
    assert rows[(Q1[:20], "deepseek")][4] == "listed" and "Grand Agra" not in rows[(Q1[:20], "deepseek")][3]


def test_one_business_written_two_ways_counts_once():
    from engine.agents.geo.g03_share_of_voice import canonical_names
    keys = canonical_names(["ITC Mughal, A Luxury Collection Hotel", "ITC Mughal", "The Oberoi Amarvilas",
                            "Oberoi Amarvilas"])
    assert keys["ITC Mughal, A Luxury Collection Hotel"] == keys["ITC Mughal"] == "ITC Mughal"
    assert keys["The Oberoi Amarvilas"] == keys["Oberoi Amarvilas"]
