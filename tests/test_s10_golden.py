"""Golden tests for S10 E-E-A-T & Trust: planted issues → exact check statuses."""

import json

from engine.agents.common import PageView
from engine.agents.seo.s10_trust import TERMS, TERMS_EXACT, EEATTrust, policy_link
from engine.collectors.c02_parser import parse_page
from engine.context import AgentContext, ClientProfile
from engine.core.blobstore import LocalBlobStore
from engine.reports import check_statuses
from engine.schemas import CheckStatus as St, EvidenceType, Severity
from engine.store import MemoryStore, PageRecord, SnapshotReader, SnapshotWriter
from engine.validation import validate_result
from tests.conftest import FakeLLM

B = "https://grand.example"
CF_EMAIL = "2a" + "".join(f"{b ^ 0x2a:02x}" for b in b"stay@grand.example")  # Cloudflare: key byte, then XOR


def doc(title, body, footer=""):
    return (f"<!doctype html><html lang='en'><head><title>{title}</title></head><body>"
            f"<header><nav><a href='{B}/about'>About us</a></nav></header><main>{body}</main>"
            f"<footer>{footer}</footer></body></html>")


HOTEL = {
    f"{B}/": doc("Grand Hotels", "<h1>Grand Hotels</h1><p>Loved by our guests! Rated 4.6 on Google by travellers.</p>",
                 footer=f"<a href='{B}/privacy'>Privacy Policy</a><a href='#'>Terms &amp; Conditions</a>"
                        "<div class='modal'><h4>Cancellation Policy</h4><ul><li>More than {{rule.days}} days "
                        "prior to arrival: full refund</li></ul></div>"),
    f"{B}/about": doc("About | Grand Hotels", "<h1>About us</h1><p>Grand Hotels was founded in 1985 by the Mehta "
                                              "family and is run by Grand Hospitality Pvt Ltd. We operate 12 hotels "
                                              "across India.</p>"),
    f"{B}/contact": doc("Contact | Grand Hotels",
                        "<h1>Contact us</h1><p>Call <a href='tel:+919812345678'>98123 45678</a>, 9 AM to 9 PM, "
                        f"Monday to Sunday. Email <span data-cfemail='{CF_EMAIL}'>[email&#160;protected]</span>.</p>"
                        "<p>Visit us: {{office.address}}</p>"),
    f"{B}/privacy": doc("Privacy | Grand Hotels", "<h1>Privacy policy</h1><p>We collect only the booking details "
                                                  "needed to confirm your stay and never sell them.</p>"),
    f"{B}/agra": doc("Grand Agra", "<h1>Grand Agra near the Taj</h1><p>Grand Agra is 2 km from the Taj Mahal, "
                                   "with a rooftop pool and 40 rooms.</p><h2>Cancellation Policy</h2>"
                                   "<h2>House rules</h2><p>Guests must show a photo ID at check-in. Visitors are "
                                   "allowed in the lobby only.</p>"),
    f"{B}/blog/agra-guide": doc(
        "Agra guide", "<h1>Two days in Agra</h1><p>Start at the Taj Mahal at sunrise, then walk to Agra Fort.</p>"
        '<script type="application/ld+json">{"@type": "BlogPosting", "headline": "Two days in Agra", '
        '"datePublished": "2026-03-01"}</script>'),
}
HOTEL_FACTS = [
    {"key": "check_in_time", "value": "14:00", "quote": '{"checkinTime": "14:00"}', "source_url": f"{B}/agra",
     "method": "jsonld:Hotel", "status": "schema-declared"},
    {"key": "price_from", "value": "INR 4500", "quote": '{"priceRange": "INR 4500"}', "source_url": f"{B}/agra",
     "method": "jsonld:Hotel", "status": "schema-declared"},
]


def build(tmp_path, pages, facts, archetype, entry):
    store, blobs = MemoryStore(), LocalBlobStore(tmp_path / "b")
    snap = SnapshotWriter(store, blobs, "s")
    for i, (url, html) in enumerate(pages.items()):
        raw = snap.put_blob(f"snapshots/s/pages/p{i}/raw.html", html)
        page = snap.add_page(PageRecord(id=f"p{i}", snapshot_id="s", url=url, final_url=url, status=200,
                                        raw_html_key=raw))
        key = snap.put_blob(f"snapshots/s/pages/p{i}/parsed.json", json.dumps(parse_page(html, url)))
        snap.add_evidence("C2", EvidenceType.PAGES_PARSED, {}, page_id=page.id, blob_key=key)
    snap.add_evidence("C4", EvidenceType.FACTS, {"facts": facts})
    snap.add_evidence("C3", EvidenceType.ARCHETYPE, {"archetype": archetype})
    return SnapshotReader(store, blobs, "s"), ClientProfile(id="c", name="Grand", primary_url=entry), store


def passage_id(items: str, key: str, phrase: str) -> str:
    return next(line.split(" ", 1)[0] for line in items.splitlines()
                if line.startswith(f"{key}.P") and phrase in line)


def run(reader, client, store, llm):
    agent = EEATTrust()
    ctx = AgentContext(reader, client, None, llm)
    result = agent.run_unit(ctx, agent.plan(ctx)[0])
    result, errors = validate_result(agent, result, {p.final_url for p in store.pages.values()})
    assert errors == []
    return agent, result


def test_s10_hotel_trust_checklist(tmp_path):
    reader, client, store = build(tmp_path, HOTEL, HOTEL_FACTS, "hospitality", f"{B}/agra")

    def answer(v):
        items = v["items"]
        return {"items": [
            {"key": "about", "status": "present", "passage": passage_id(items, "about", "1985"),
             "quote": "Grand Hotels was founded in 1985 by the Mehta family"},
            {"key": "cancellation", "status": "partial", "passage": passage_id(items, "cancellation", "prior"),
             "quote": "More than […] days prior to arrival", "note": "Values filled in by JavaScript."},
            {"key": "check_in_out", "status": "absent"},
            {"key": "house_rules", "status": "present", "passage": passage_id(items, "house_rules", "photo ID"),
             "quote": "Pets are welcome in every room"},  # not on the page: must be dropped
            {"key": "taxes_fees", "status": "absent"},
            {"key": "guest_reviews", "status": "partial", "passage": passage_id(items, "guest_reviews", "Rated"),
             "quote": "Rated 4.6 on Google by travellers", "note": "No named, dated reviews."},
        ]}

    llm = FakeLLM({"s10.trust": answer})
    agent, result = run(reader, client, store, llm)
    sent = llm.calls[0][1]["items"]
    assert "footer, has values filled in by JavaScript): Footer:" in sent and "{{" not in sent
    assert check_statuses(agent, result.findings) == {
        "S10.01": St.PASS,           # founding year, owners, legal entity, scale
        "S10.02": St.WARN,           # phone, hours, Cloudflare email found; address only a JS placeholder
        "S10.03": St.WARN,           # the blog post names no author
        "S10.04": St.PASS,           # datePublished in JSON-LD
        "S10.05": St.WARN,           # terms only a '#' modal link; cancellation JS-filled; check-in only in JSON-LD
        "S10.06": St.NOT_APPLICABLE,  # no disclosure items for hotels
        "S10.07": St.WARN,           # aggregate rating only
        "S10.08": St.WARN,           # price only in JSON-LD
    }
    by_check = {f.check_id: f for f in result.findings}
    contact = by_check["S10.02"]
    assert contact.title == "Contact page is missing: address" and "filled in by JavaScript" in contact.impact
    assert contact.evidence[0].excerpt == "address is a template placeholder: {{office.address}}"  # shown first
    assert any("stay@grand.example" in e.excerpt for e in contact.evidence)
    policies = by_check["S10.05"].title
    assert "terms and conditions (absent)" in policies and "check-in and check-out times (partial)" in policies
    assert "house rules" not in policies  # dropped verdict → unverified, not counted either way
    assert any("dropped because the quoted text isn't on the page" in limit for limit in result.coverage.limits)
    assert "only in structured data" in by_check["S10.08"].evidence[0].excerpt


def test_s10_lender_missing_grievance_officer_and_contact_page_is_critical(tmp_path):
    pages = {
        f"{B}/": doc("Grand Loans", "<h1>Grand Loans</h1><p>Home loans for salaried and self-employed "
                                    "customers across Maharashtra.</p><p>Grand Finance Ltd is an NBFC registered "
                                    "with the RBI, CoR No. N-13.01234.</p>",
                     footer=f"<a href='{B}/privacy'>Privacy</a><a href='{B}/terms'>Terms of use</a>"),
        f"{B}/about": doc("About | Grand Loans", "<h1>About</h1><p>We make home loans simple for every family in "
                                                 "India, with quick approvals.</p>"),
        f"{B}/home-loan-rates": doc("Home loan rates", "<h1>Home loan interest rates</h1><p>Home loan interest "
                                                       "rates start from 8.5% p.a. for salaried applicants.</p>"),
        f"{B}/blog/home-loan-guide": doc("Home loan guide", "<h1>How to get a home loan</h1><p>By Priya Sharma</p>"
                                                            "<p>Check your credit score and gather documents "
                                                            "before you apply.</p>"),
    }

    def answer(v):
        return {"items": [
            {"key": "about", "status": "partial", "passage": passage_id(v["items"], "about", "simple"),
             "quote": "We make home loans simple for every family in India", "note": "Marketing only."},
            {"key": "rbi_registration", "status": "present",
             "passage": passage_id(v["items"], "rbi_registration", "CoR"),
             "quote": "Grand Finance Ltd is an NBFC registered with the RBI, CoR No. N-13.01234"},
        ] + [{"key": k, "status": "absent"} for k in ("grievance_officer", "fair_practices", "kfs",
                                                     "rbi_complaints", "rates_fees")]}

    reader, client, store = build(tmp_path, pages, [], "loans", f"{B}/home-loan-rates")
    agent, result = run(reader, client, store, FakeLLM({"s10.trust": answer}))
    assert check_statuses(agent, result.findings) == {
        "S10.01": St.WARN,   # generic about page
        "S10.02": St.FAIL,   # no contact page at all
        "S10.03": St.WARN,   # author named, but no reviewer on financial content
        "S10.04": St.FAIL,   # rate page without a date
        "S10.05": St.PASS,   # privacy and terms linked; loans have no extra policy items
        "S10.06": St.FAIL,   # grievance officer absent
        "S10.07": St.NOT_APPLICABLE,
        "S10.08": St.FAIL,   # rates and fees absent
    }
    by_check = {f.check_id: f for f in result.findings}
    assert by_check["S10.02"].severity == Severity.CRITICAL and by_check["S10.06"].severity == Severity.CRITICAL
    assert by_check["S10.06"].fix.startswith("Flag for your compliance team; this is not legal advice.")
    assert by_check["S10.08"].severity == Severity.HIGH


def test_s10_without_llm_reports_unverifiable_not_pass(tmp_path):
    reader, client, store = build(tmp_path, HOTEL, [], "hospitality", f"{B}/agra")
    agent, result = run(reader, client, store, None)
    statuses = check_statuses(agent, result.findings)
    assert statuses["S10.01"] == St.UNVERIFIABLE and statuses["S10.07"] == St.UNVERIFIABLE
    assert statuses["S10.05"] == St.WARN  # terms missing is known without the LLM
    assert any("need the LLM" in s for s in result.coverage.skipped)


def test_terms_link_prefers_the_general_policy_over_narrow_ones():
    html = doc("Home", "<h1>Home</h1>", footer=f"<a href='{B}/offers-tc'>Offers T&amp;C</a>"
                                               f"<a href='#'>Terms &amp; Conditions</a>"
                                               f"<a href='{B}/terms-and-conditions'>Terms &amp; Conditions</a>")
    page = PageView(PageRecord(id="p", snapshot_id="s", url=f"{B}/", final_url=f"{B}/", status=200),
                    parse_page(html, f"{B}/"))
    url, where = policy_link([page], TERMS, TERMS_EXACT)
    assert url == f"{B}/terms-and-conditions" and "Terms & Conditions" in where
