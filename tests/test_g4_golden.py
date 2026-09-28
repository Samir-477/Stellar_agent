"""Golden tests for G4 Citation Sources (observation): planted citations → statuses."""

from engine.agents.geo.g04_citation_sources import CitationSources
from engine.context import AgentContext, ClientProfile
from engine.core.blobstore import LocalBlobStore
from engine.reports import check_statuses
from engine.schemas import CheckStatus as St, EvidenceType
from engine.store import MemoryStore, SnapshotReader, SnapshotWriter
from engine.validation import validate_result

B = "https://www.grand.example"


def cite(url, **extra):
    return {"url": url, "domain": url.split("/")[2].removeprefix("www."), **extra}


def build(tmp_path):
    store, blobs = MemoryStore(), LocalBlobStore(tmp_path / "b")
    snap = SnapshotWriter(store, blobs, "s")
    snap.add_evidence("C10", EvidenceType.AI_ANSWERS, {"surface": "google_ai_overview", "answers": [
        {"surface": "google_ai_overview", "prompt": "grand agra", "prompt_kind": "brand", "text": "…",
         "citations": [cite(f"{B}/agra"), cite("https://www.google.com/searchviewer/10?x=1")]},
        {"surface": "google_ai_overview", "prompt": "hotels near taj mahal", "prompt_kind": "local", "text": "…",
         "citations": [cite("https://www.tripadvisor.in/Hotels-g297683"), cite("https://in.tripadvisor.com/x"),
                       cite("https://www.tajhotels.com/agra")]}]})
    snap.add_evidence("C10", EvidenceType.AI_ANSWERS, {"surface": "simulated_search", "answers": [
        {"surface": "simulated_search", "prompt": "best hotels near taj mahal", "prompt_kind": "category",
         "text": "…", "citations": [cite("https://www.booking.com/agra")]}]})
    snap.add_evidence("C10", EvidenceType.AI_ANSWERS, {"surface": "deepseek", "answers": [
        {"surface": "deepseek", "prompt": "Tell me about Grand Agra", "prompt_kind": "brand", "text": "…",
         "citations": [cite(f"{B}/old-page", printed=True, resolves=False),
                       cite(f"{B}/agra", printed=True, resolves=True)]}]})
    return SnapshotReader(store, blobs, "s")


def test_g4_classifies_citations_and_flags_invented_links(tmp_path):
    agent = CitationSources()
    ctx = AgentContext(build(tmp_path), ClientProfile(id="c", name="Grand", primary_url=f"{B}/agra"), None, None)
    result = agent.run_unit(ctx, agent.plan(ctx)[0])
    result, errors = validate_result(agent, result, set())
    assert errors == []
    assert check_statuses(agent, result.findings) == {
        "G4.01": St.WARN,          # cited only for the brand search
        "G4.02": St.WARN,          # non-brand citations all go elsewhere (3 to listing sites)
        "G4.03": St.WARN,          # one printed URL doesn't exist
        "G4.04": St.UNVERIFIABLE,  # needs the cited pages (C8)
    }
    domains = {row[0]: row for row in result.signature_table["rows"]}
    assert "google.com" not in domains  # Google's viewer links aren't sources
    assert domains["in.tripadvisor.com"][1] == "listing or social site"
    assert domains["booking.com"][4] == "proxy only"
    assert "3 to listing or social sites" in next(f for f in result.findings if f.check_id == "G4.02").title
