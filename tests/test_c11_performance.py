"""C11 Performance Capture: URL choice, the PageSpeed summary, retries and errors."""

import pytest

from engine.collectors.c11_performance import PerformanceCapture, pick_urls, summarize
from engine.context import ClientProfile, CollectorContext, WorkUnit
from engine.core.blobstore import LocalBlobStore
from engine.integrations.pagespeed import PageSpeedError
from engine.schemas import EvidenceType
from engine.store import MemoryStore, SnapshotWriter

B = "https://grand.example"
PSI = {
    "loadingExperience": {"metrics": {"LARGEST_CONTENTFUL_PAINT_MS": {"percentile": 2909, "category": "AVERAGE"},
                                      "CUMULATIVE_LAYOUT_SHIFT_SCORE": {"percentile": 35, "category": "SLOW"}}},
    "originLoadingExperience": {"metrics": {"INTERACTION_TO_NEXT_PAINT": {"percentile": 310, "category": "AVERAGE"}}},
    "lighthouseResult": {
        "lighthouseVersion": "13.5.0", "categories": {"performance": {"score": 0.18}},
        "audits": {
            "largest-contentful-paint": {"numericValue": 37001.1}, "total-blocking-time": {"numericValue": 2776},
            "cumulative-layout-shift": {"numericValue": 0.17}, "server-response-time": {"numericValue": 4},
            "lcp-breakdown-insight": {"details": {"items": [
                {"items": [{"subpart": "timeToFirstByte", "duration": 4.2},
                           {"subpart": "resourceLoadDelay", "duration": 6715.4}]},
                {"type": "node", "snippet": "<img class=\"hero lazy\" src=\"/hero.jpg\">"}]}},
            "lcp-discovery-insight": {"details": {"items": [{"type": "checklist", "items": {
                "requestDiscoverable": {"value": False}, "eagerlyLoaded": {"value": True}}}]}},
            "render-blocking-insight": {"title": "Render-blocking requests", "score": 0,
                                        "displayValue": "Est savings of 3,940 ms",
                                        "details": {"items": [{"url": "https://widget.example/b.js", "wastedMs": 5522,
                                                               "totalBytes": 739723}]}},
            "viewport-insight": {"score": 1, "details": {"items": [{"node": {
                "snippet": "<meta name=\"viewport\" content=\"width=device-width, user-scalable=no\">"}}]}}}}}


def test_summary_reads_field_lab_lcp_and_audits():
    s = summarize(PSI)
    assert s["field"]["CUMULATIVE_LAYOUT_SHIFT_SCORE"] == {"p75": 35, "category": "SLOW"}
    assert s["origin_field"]["INTERACTION_TO_NEXT_PAINT"]["p75"] == 310
    assert s["lab"]["lcp_ms"] == 37001.1 and s["score"] == 0.18
    assert s["lcp_parts"] == {"timeToFirstByte": 4, "resourceLoadDelay": 6715}
    assert "hero lazy" in s["lcp_element"] and s["lcp_checks"] == {"requestDiscoverable": False, "eagerlyLoaded": True}
    assert s["audits"]["render_blocking"]["items"][0]["wastedMs"] == 5522
    assert "user-scalable=no" in s["audits"]["viewport"]["items"][0]["snippet"]


def test_origin_fallback_is_not_reported_as_page_data():
    data = dict(PSI, loadingExperience={**PSI["loadingExperience"], "origin_fallback": True})
    assert summarize(data)["field"] == {}


def test_pick_urls_entry_home_then_one_page_per_template():
    models = [{"url": f"{B}/agra", "template_id": "resort", "links": []},
              {"url": f"{B}/", "template_id": "home", "links": [
                  {"href": f"{B}/jaipur", "in_nav": True}, {"href": f"{B}/offers", "in_nav": True}]},
              {"url": f"{B}/jaipur", "template_id": "resort", "links": []},
              {"url": f"{B}/offers", "template_id": "offers", "links": []}]
    assert pick_urls(models, 5) == [f"{B}/agra", f"{B}/", f"{B}/offers"]  # /jaipur shares the resort template


class FakePageSpeed:
    def __init__(self, error=None):
        self.calls, self.error = [], error

    def run(self, url, strategy="mobile"):
        self.calls.append(url)
        if self.error:
            raise PageSpeedError(self.error)
        return PSI


def ctx_with(settings, tmp_path, client):
    snap = SnapshotWriter(MemoryStore(), LocalBlobStore(tmp_path / "b"), "s")
    return CollectorContext(snap, ClientProfile(id="c", name="G", primary_url=f"{B}/agra"), settings,
                            pagespeed=client), snap


def test_measured_urls_are_not_measured_again(settings, tmp_path):
    client = FakePageSpeed()
    ctx, snap = ctx_with(settings, tmp_path, client)
    unit = WorkUnit("measure", {"url": f"{B}/agra"})
    PerformanceCapture().run_unit(ctx, unit)
    PerformanceCapture().run_unit(ctx, unit)  # a retry of the same unit
    assert client.calls == [f"{B}/agra"] and snap.evidence(EvidenceType.PERFORMANCE)[0].blob_key


def test_client_errors_are_recorded_and_server_errors_retried(settings, tmp_path):
    ctx, snap = ctx_with(settings, tmp_path, FakePageSpeed("pagespeed: HTTP 400 Lighthouse returned error"))
    PerformanceCapture().run_unit(ctx, WorkUnit("measure", {"url": f"{B}/agra"}))
    assert "HTTP 400" in snap.evidence(EvidenceType.PERFORMANCE)[0].payload["error"]
    ctx, _ = ctx_with(settings, tmp_path / "2", FakePageSpeed("pagespeed: ReadTimeout"))
    with pytest.raises(PageSpeedError):
        PerformanceCapture().run_unit(ctx, WorkUnit("measure", {"url": f"{B}/agra"}))
