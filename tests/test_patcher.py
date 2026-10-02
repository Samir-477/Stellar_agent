from lxml import html as H

from engine.lib.locators import locate
from engine.output.patcher import apply

PAGE = """<!doctype html><html lang="en"><head><title>Old title</title>
<script>trackEverything()</script>
<script type="application/ld+json">{"@type": "LodgingBusiness", "name": "Wrong Hotel"}</script></head>
<body onload="evil()"><div><p>Intro paragraph about the hotel.</p><p>Rooms paragraph.</p><p>Dining paragraph.</p>
<p>Pool paragraph.</p></div><a href="javascript:alert(1)">x</a></body></html>"""


def loc(xpath):
    doc = H.fromstring(PAGE)
    return locate(doc.getroottree().xpath(xpath)[0]).model_dump()


def test_several_inserts_in_one_section_all_land_before_their_own_targets():
    patches = [
        {"key": "a", "type": "element_insert", "locator": loc("/html/body/div/p[2]"), "after": "<h3>Q rooms?</h3><p>A rooms.</p>"},
        {"key": "b", "type": "element_insert", "locator": loc("/html/body/div/p[3]"), "after": "<h3>Q dining?</h3><p>A dining.</p>"},
        {"key": "c", "type": "element_insert", "locator": loc("/html/body/div/p[4]"), "after": "<h3>Q pool?</h3><p>A pool.</p>"},
    ]
    result = apply(PAGE, "https://h.example/agra", patches)
    assert result.placed == ["a", "b", "c"] and result.not_placed == []
    fixed = H.fromstring(result.fixed_html)
    texts = [el.text_content() for el in fixed.xpath("//div/*")]
    assert texts.index("Q rooms?") < texts.index("Rooms paragraph.") < texts.index("Q dining?") \
        < texts.index("Dining paragraph.") < texts.index("Q pool?") < texts.index("Pool paragraph.")
    assert result.annotated_html.count('class="dx-insert"') == 3


def test_head_title_jsonld_and_freezing():
    patches = [
        {"key": "t", "type": "text_replace", "locator": loc("/html/head/title"), "before": "Old title", "after": "New title"},
        {"key": "j", "type": "jsonld_upsert", "locator": loc("/html/head/script[2]"),
         "after": '<script type="application/ld+json">{"@type": "Hotel", "name": "Right Hotel"}</script>'},
    ]
    result = apply(PAGE, "https://h.example/agra", patches)
    assert result.not_placed == [] and {u["key"] for u in result.under_the_hood} == {"t", "j"}
    assert "<title>New title</title>" in result.fixed_html and "Right Hotel" in result.fixed_html
    assert "Wrong Hotel" not in result.fixed_html and "Wrong Hotel" in result.annotated_html  # annotated = original
    for html in (result.fixed_html, result.annotated_html):
        assert "trackEverything" not in html and "onload" not in html and "javascript:alert" not in html
        assert '<base href="https://h.example/agra">' in html and 'content="noindex, nofollow"' in html


def test_changed_page_is_reported_not_forced():
    stale = loc("/html/body/div/p[2]")
    stale["text_hash"] = "000000000000"
    result = apply(PAGE, "https://h.example/agra", [{"key": "x", "type": "element_insert", "locator": stale,
                                                      "after": "<p>new</p>"}])
    assert result.placed == [] and result.not_placed[0]["reason"] == "element text changed since the crawl"


def test_link_insert_wraps_the_exact_phrase_and_refuses_when_missing():
    patches = [
        {"key": "l1", "type": "link_insert", "locator": loc("/html/body/div/p[3]"),
         "after": '<a href="https://h.example/dining">Dining paragraph</a>'},
        {"key": "l2", "type": "link_insert", "locator": loc("/html/body/div/p[4]"),
         "after": '<a href="https://h.example/spa">rooftop spa</a>'},  # phrase not in that paragraph
    ]
    result = apply(PAGE, "https://h.example/agra", patches)
    assert result.placed == ["l1"] and result.not_placed == [{"key": "l2",
                                                              "reason": "anchor phrase not found in the element"}]
    assert '<p><a href="https://h.example/dining">Dining paragraph</a>.</p>' in result.fixed_html


OLD_OVERLAY_PAGE = """<!DOCTYPE html><html><head></head><body><p data-fix-id="fix-0" class="dx-changed">Rooms</p>
<style>[data-fix-id]{outline:3px solid #e8590c}</style><div id="dx-card"></div>
<script id="dx-data" type="application/json">{"fix-0": {"title": "2 of 8 sections lack answers", "after": "x"}}</script>
<script>(function(){var data=JSON.parse(document.getElementById('dx-data').textContent);})();</script></body></html>"""


def test_annotated_page_carries_the_hover_tooltip_and_change_stepper():
    patches = [{"key": "a", "type": "element_insert", "locator": loc("/html/body/div/p[2]"), "title": "Plain name",
                "after": "<h3>Q rooms?</h3><p>A rooms.</p>"}]
    html = apply(PAGE, "https://h.example/agra", patches).annotated_html
    for part in ('id="dx-tip"', 'id="dx-nav"', 'id="dx-card"', 'data-version="2"', "Click for before and after"):
        assert part in html
    doc = H.fromstring(html)
    assert '"Plain name"' in doc.get_element_by_id("dx-data").text


def test_pages_built_with_the_old_overlay_are_upgraded_once_with_plain_titles():
    from engine.output.patcher import upgrade_annotated
    html = upgrade_annotated(OLD_OVERLAY_PAGE, {"2 of 8 sections lack answers": "Sections don't start with an answer"})
    assert html.count('id="dx-data"') == 1 and html.count('id="dx-script"') == 1 and html.count("<style") == 1
    assert "#e8590c}" not in html and "Sections don't start with an answer" in html
    assert 'data-fix-id="fix-0"' in html  # the page's own marks are kept
    assert upgrade_annotated(html) == upgrade_annotated(upgrade_annotated(html))  # idempotent
    assert upgrade_annotated("<html><body><p>No overlay</p></body></html>") == "<html><body><p>No overlay</p></body></html>"
