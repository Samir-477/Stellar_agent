"""Golden tests for S2 Page Experience: planted measurements → exact check statuses."""

import json

from engine.agents.seo.s02_page_experience import PageExperience
from engine.collectors.c02_parser import parse_page
from engine.collectors.c11_performance import summarize
from engine.context import AgentContext, ClientProfile
from engine.core.blobstore import LocalBlobStore
from engine.reports import check_statuses
from engine.schemas import CheckStatus as St, Confidence, EvidenceType
from engine.store import MemoryStore, PageRecord, SnapshotReader, SnapshotWriter
from engine.validation import validate_result
from tests.test_c11_performance import PSI

B = "https://grand.example"


def build(tmp_path, viewport, measurements):
    store, blobs = MemoryStore(), LocalBlobStore(tmp_path / "b")
    snap = SnapshotWriter(store, blobs, "s")
    head = f'<meta name="viewport" content="{viewport}">' if viewport else ""
    html = f"<!doctype html><html lang='en'><head><title>Grand Agra</title>{head}</head><body><h1>Grand</h1></body></html>"
    page = snap.add_page(PageRecord(id="p0", snapshot_id="s", url=f"{B}/agra", final_url=f"{B}/agra", status=200))
    snap.add_evidence("C2", EvidenceType.PAGES_PARSED, {}, page_id=page.id,
                      blob_key=snap.put_blob("snapshots/s/pages/p0/parsed.json", json.dumps(parse_page(html, page.url))))
    for payload in measurements:
        snap.add_evidence("C11", EvidenceType.PERFORMANCE, payload)
    return SnapshotReader(store, blobs, "s")


def run(reader):
    agent = PageExperience()
    ctx = AgentContext(reader, ClientProfile(id="c", name="G", primary_url=f"{B}/agra"), None, None)
    result = agent.run_unit(ctx, agent.plan(ctx)[0])
    result, errors = validate_result(agent, result, {f"{B}/agra"})
    assert errors == []
    return agent, result


def test_s2_grades_field_data_first_and_flags_the_late_hero_image(tmp_path):
    reader = build(tmp_path, "width=device-width, initial-scale=1.0, user-scalable=no",
                   [{"url": f"{B}/agra", **summarize(PSI)}])
    agent, result = run(reader)
    assert check_statuses(agent, result.findings) == {
        "S2.01": St.WARN,  # field LCP 2.9 s (the 37 s lab value is not used)
        "S2.02": St.WARN,  # origin INP 310 ms
        "S2.03": St.FAIL,  # field CLS 0.35
        "S2.04": St.PASS,  # no field TTFB: lab 4 ms
        "S2.05": St.PASS,  # LCP breakdown as context
        "S2.06": St.FAIL,  # LCP image not discoverable in the HTML
        "S2.07": St.WARN,  # zoom disabled
        "S2.08": St.FAIL,  # render-blocking score 0
    }
    by_check = {f.check_id: f for f in result.findings}
    assert by_check["S2.01"].confidence == Confidence.CONFIRMED and "page field data" in by_check["S2.01"].evidence[0].excerpt
    assert by_check["S2.02"].confidence == Confidence.LIKELY and "origin field data" in by_check["S2.02"].evidence[0].excerpt
    assert "load delay" in by_check["S2.05"].evidence[0].excerpt


def test_s2_without_viewport_or_measurements(tmp_path):
    agent, result = run(build(tmp_path, None, [{"url": f"{B}/agra", **summarize(PSI)}]))
    assert check_statuses(agent, result.findings)["S2.07"] == St.FAIL
    agent, result = run(build(tmp_path / "2", "width=device-width", [{"url": f"{B}/agra", "error": "HTTP 400"}]))
    assert set(check_statuses(agent, result.findings).values()) == {St.UNVERIFIABLE}
    assert any("HTTP 400" in s for s in result.coverage.skipped)


def test_s2_prepares_hints_for_a_main_image_loaded_late(tmp_path):
    from engine.output.patcher import apply

    store, blobs = MemoryStore(), LocalBlobStore(tmp_path / "b")
    snap = SnapshotWriter(store, blobs, "s")
    html = ("<!doctype html><html lang='en'><head><title>Grand Agra</title></head><body><h1>Grand</h1>"
            "<img class='hero lazy' src='data:image/gif;base64,R0lGOD' data-src='/hero-big.jpg' alt='Pool'>"
            "<img src='/gallery-9.jpg' alt='Garden'></body></html>")
    page = snap.add_page(PageRecord(id="p0", snapshot_id="s", url=f"{B}/agra", final_url=f"{B}/agra", status=200))
    snap.add_evidence("C2", EvidenceType.PAGES_PARSED, {}, page_id=page.id,
                      blob_key=snap.put_blob("snapshots/s/pages/p0/parsed.json", json.dumps(parse_page(html, page.url))))
    measured = {"url": f"{B}/agra", **summarize(PSI)}
    measured["lcp_element"] = '<img class="hero lazy" src="data:image/gif;base64,R0lGOD" data-src="/hero-big.jpg">'
    measured["lcp_checks"] = {"requestDiscoverable": False, "eagerlyLoaded": True, "priorityHinted": False}
    measured["audits"]["offscreen_images"] = {"score": 0.5, "items": [{"url": f"{B}/gallery-9.jpg"}]}
    snap.add_evidence("C11", EvidenceType.PERFORMANCE, measured)
    agent, result = run(SnapshotReader(store, blobs, "s"))
    hints = {p.key.split(":")[1]: p for p in result.patches}
    assert set(hints) == {"lcp-src", "lcp-priority", "offscreen-2"} and all(p.approval == "required" for p in hints.values())
    assert {f.check_id: f for f in result.findings}["S2.06"].patch_keys == [p.key for p in result.patches]
    fixed = apply(html, f"{B}/agra", [p.model_dump(mode="json") for p in result.patches])
    assert fixed.not_placed == [] and f'src="{B}/hero-big.jpg"' in fixed.fixed_html
    assert 'fetchpriority="high"' in fixed.fixed_html and 'loading="lazy"' in fixed.fixed_html
