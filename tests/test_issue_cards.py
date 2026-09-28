"""Issue cards: before/after snippets from the captured page, and the join of findings to changes."""

from __future__ import annotations

from engine.issues import build_issue_cards, fix_type
from engine.lib.locators import text_hash
from engine.output.diffs import page_snippets, segments

PAGE = """<!DOCTYPE html><html><head><title>Best Resorts</title>
<meta name="description" content="Book now">
<script type="application/ld+json">{"@type": "Hotel", "name": "Other Hotel"}</script></head>
<body><h1>Welcome</h1>
<p id="intro">Stay close to the Taj Mahal with rooms for families and a rooftop pool.</p>
<a href="/old" class="cta">Deals</a></body></html>"""


def loc(xpath: str, text: str | None = None) -> dict:
    return {"xpath": xpath, "css": None, "text_hash": text_hash(text) if text else None}


def test_snippets_show_the_captured_element_before_and_after_each_change():
    patches = [
        {"key": "t", "type": "text_replace", "locator": loc("/html/head/title", "Best Resorts"),
         "before": "Best Resorts", "after": "Regalia Agra | Hotel near the Taj"},
        {"key": "d", "type": "head_upsert", "after": '<meta name="description" content="Rooms 1.4 km from the Taj.">'},
        {"key": "og", "type": "head_upsert", "after": '<meta property="og:title" content="Regalia Agra">'},
        {"key": "j", "type": "jsonld_upsert", "locator": loc("/html/head/script"),
         "after": '<script type="application/ld+json">{"@type": "Hotel", "name": "Regalia Agra"}</script>'},
        {"key": "a", "type": "attribute_set", "locator": loc("/html/body/a"), "after": 'href="/deals"'},
        {"key": "l", "type": "link_insert", "locator": loc("/html/body/p"), "after": '<a href="/pool">rooftop pool</a>'},
        {"key": "i", "type": "element_insert", "locator": loc("/html/body/p"),
         "after": "<h2>Is there parking?</h2><p>Yes, free parking.</p>"},
        {"key": "gone", "type": "text_replace", "locator": loc("/html/body/h1", "Changed since the crawl"),
         "after": "New heading"},
    ]
    s = page_snippets(PAGE, patches)
    assert s["t"]["before"] == "<title>Best Resorts</title>" and s["t"]["after"] == "<title>Regalia Agra | Hotel near the Taj</title>"
    assert s["d"]["before"] == '<meta name="description" content="Book now">'
    assert s["og"]["before"] is None and "og:title" in s["og"]["after"]  # a new tag: nothing there before
    assert s["j"]["language"] == "json" and '"name": "Other Hotel"' in s["j"]["before"] and "Regalia Agra" in s["j"]["after"]
    assert s["a"]["before"] == '<a href="/old" class="cta">' and s["a"]["after"] == '<a href="/deals" class="cta">'
    assert '<a href="/pool">rooftop pool</a>' in s["l"]["after"] and "<a" not in s["l"]["before"]
    assert s["i"]["after"].startswith("<h2>Is there parking?</h2>") and s["i"]["before"] in s["i"]["after"]
    assert s["gone"]["placed"] is False and s["gone"]["reason"] == "element text changed since the crawl"


def test_microsite_address_mirrors_the_full_page_path():
    from engine.output.microsite import page_path, slugify
    assert page_path("https://www.sterlingholidays.com/resorts-hotels/shivalik-chail") == "resorts-hotels/shivalik-chail"
    assert page_path("https://x.com/Resorts/Sterling-Mussoorie.html?utm=1") == "resorts/sterling-mussoorie"
    assert page_path("https://x.com/") == "home"
    assert slugify("Sterling Holidays - Regalia Agra") == "sterling-holidays-regalia-agra"
    assert slugify("  Sterling hotels!! ") == "sterling-hotels"


def test_word_segments_mark_only_what_changed():
    left, right = segments('<meta content="Book now">', '<meta content="Rooms near the Taj">')
    assert [seg["t"] for seg in left if seg["k"] == "del"] == ["Book now"]
    assert [seg["t"] for seg in right if seg["k"] == "ins"] == ["Rooms near the Taj"]
    assert "".join(seg["t"] for seg in right) == '<meta content="Rooms near the Taj">'


def test_missing_page_is_reported_not_guessed():
    s = page_snippets(None, [{"key": "t", "type": "text_replace", "locator": loc("/html/head/title"),
                               "before": "Old", "after": "New"},
                              {"key": "f", "type": "file_patch", "before": "User-agent: *", "after": "Sitemap: /s.xml"}])
    assert s["t"]["placed"] is False and s["t"]["before"] == "Old"
    assert s["f"]["placed"] is True and s["f"]["language"] == "text"


def finding(agent, check, status="fail", severity="high", patch_keys=(), missing=(), pages=("https://x/",)):
    return {"agent_id": agent, "check_id": check, "pillar": "seo", "status": status, "severity": severity,
            "confidence": "confirmed", "title": f"{check} issue", "impact": "Why it matters", "fix": "Do this",
            "verification": "Check that", "scope": {"pages": list(pages)}, "evidence": [{"excerpt": "seen"}],
            "patch_keys": list(patch_keys), "missing_facts": list(missing)}


def test_cards_join_changes_and_say_what_kind_of_fix_each_issue_has():
    patches = [{"key": "S3:t", "type": "text_replace", "page_url": "https://x/", "after": "New", "rationale": "r"},
               {"key": "A1:a", "type": "element_insert", "page_url": "https://x/", "after": "<p>Answer</p>"}]
    snippets = {"S3:t": {"language": "html", "before": "<title>Old</title>", "after": "<title>New</title>",
                         "placed": True, "before_segments": [], "after_segments": []}}
    findings = [
        finding("S3", "S3.03", patch_keys=["S3:t"]),
        finding("A1", "A1.01", severity="medium", patch_keys=["A1:a"]),
        finding("S10", "S10.08", status="warn", severity="medium", missing=["taxes and fees"]),
        finding("S2", "S2.02", severity="high"),
        finding("G3", "G3.01", severity="high"),
        finding("S1", "S1.01", status="pass"),
    ]
    cards = build_issue_cards(findings, patches, snippets)
    kinds = {c["check_id"]: c["fix_type"] for c in cards}
    assert kinds == {"S3.03": "code", "A1.01": "content", "S10.08": "facts", "S2.02": "action", "G3.01": "observation"}
    s3 = next(c for c in cards if c["check_id"] == "S3.03")
    assert s3["changes"][0]["before"] == "<title>Old</title>" and s3["evidence"] == [{"excerpt": "seen"}]
    assert [c["status"] for c in cards][-1] == "warn"  # failures first
    assert fix_type(finding("S3", "S3.03"), []) == "action"


def test_run_archetype_uses_the_detection_the_agents_used(monkeypatch):
    """A confident C3 detection is only evidence; the run page and microsites must still see it."""
    from contextlib import contextmanager

    from engine.orchestrator import repo

    def with_evidence(payload):
        class Conn:
            def execute(self, *_):
                return self

            def fetchone(self):
                return {"payload": payload} if payload else None

        @contextmanager
        def connection():
            yield Conn()
        monkeypatch.setattr(repo, "connection", connection)

    ctx = {"snapshot_id": "s1", "archetype": None}
    with_evidence({"archetype": "hospitality", "confidence": 0.9, "source": "rules"})
    assert repo.run_archetype(ctx) == "hospitality"
    with_evidence({"archetype": "loans", "confidence": 0.5, "source": "rules"})  # a guess the team never confirmed
    assert repo.run_archetype(ctx) is None
    with_evidence({"archetype": "retail", "confidence": 1.0, "source": "team"})
    assert repo.run_archetype({"snapshot_id": "s1", "archetype": "retail"}) == "retail"
    with_evidence(None)
    assert repo.run_archetype({"snapshot_id": "s1", "archetype": "logistics"}) == "logistics"
