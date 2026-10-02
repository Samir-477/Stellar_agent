"""Approvals: a change marked approval="required" is shown but only applied once the team approves it."""

import pytest
from fastapi import HTTPException

import engine.api.app as app_module
from engine.api.app import ApprovalIn, approve_changes
from engine.output import page_review
from engine.output.page_review import review_entry_page
from engine.store import MemoryStore, PageRecord

URL = "https://x.example/"
RAW = "<html><head><title>T</title></head><body><h1>Gold</h1><p id='intro'>Intro.</p></body></html>"
AUTO = {"key": "S3:title", "agent_id": "S3", "page_url": URL, "type": "text_replace",
        "locator": {"css": "title"}, "before": "T", "after": "Gold loans | X", "rationale": "r"}
WAITING = {"key": "S8:entity", "agent_id": "S8", "page_url": URL, "type": "element_insert", "approval": "required",
           "locator": {"css": "#intro"}, "after": "<p>Prepared answer.</p>", "rationale": "r"}
FINDINGS = [{"agent_id": "S3", "agent_version": "1", "check_id": "S3.01", "pillar": "seo", "status": "fail",
             "severity": "high", "confidence": "confirmed", "title": "Title", "scope": {"pages": [URL]},
             "evidence": [{"type": "html_excerpt", "excerpt": "T"}], "patch_keys": ["S3:title"]},
            {"agent_id": "S8", "agent_version": "1", "check_id": "S8.03", "pillar": "seo", "status": "fail",
             "severity": "medium", "confidence": "confirmed", "title": "Types missing", "scope": {"pages": [URL]},
             "evidence": [{"type": "html_excerpt", "excerpt": "none"}], "patch_keys": ["S8:entity"]}]


class Blobs:
    def get(self, key):
        return RAW.encode()


def review(monkeypatch, approved):
    store = MemoryStore()
    store.add_page(PageRecord(id="p", snapshot_id="s", url=URL, final_url=URL, status=200, raw_html_key="raw"))
    repo = page_review.repo
    monkeypatch.setattr(repo, "get_run", lambda r: {"status": "completed", "snapshot_id": "s"})
    monkeypatch.setattr(repo, "run_context", lambda r: {"primary_url": URL, "name": "X"})
    monkeypatch.setattr(repo, "list_patches", lambda r: [dict(AUTO), dict(WAITING)])
    monkeypatch.setattr(repo, "list_findings", lambda r: [dict(f) for f in FINDINGS])
    monkeypatch.setattr(repo, "get_intelligence_report", lambda r: {})
    monkeypatch.setattr(repo, "approved_keys", lambda r: set(approved))
    return review_entry_page("r", store, Blobs())


def test_a_change_waiting_for_approval_is_shown_but_not_applied(monkeypatch):
    result = review(monkeypatch, approved=[])
    assert result.waiting == {"S8:entity"} and result.result.placed == ["S3:title"]
    assert "Prepared answer." not in result.result.fixed_html
    by_check = {i["check_id"]: i for i in result.issues}
    assert by_check["S8.03"]["fixed"] is False and by_check["S8.03"]["awaiting_approval"] == ["S8:entity"]
    assert "Prepared answer." in by_check["S8.03"]["changes"][0]["after"]  # its code is still shown
    assert by_check["S3.01"]["fixed"] is True and by_check["S3.01"]["awaiting_approval"] == []


def test_once_approved_the_change_is_applied_and_the_issue_is_fixed(monkeypatch):
    result = review(monkeypatch, approved=["S8:entity"])
    assert result.waiting == set() and "Prepared answer." in result.result.fixed_html
    assert {i["check_id"]: i["fixed"] for i in result.issues}["S8.03"] is True


def test_only_changes_that_need_approval_can_be_approved(monkeypatch):
    approved = []
    monkeypatch.setattr(app_module.repo, "get_run", lambda r: {"status": "completed"})
    monkeypatch.setattr(app_module.repo, "list_patches", lambda r: [AUTO, WAITING])
    monkeypatch.setattr(app_module.repo, "approve", lambda r, keys, by: approved.extend(keys))
    monkeypatch.setattr(app_module, "build_preview_bundle", lambda *a: {"pages": [], "issues": []})
    monkeypatch.setattr(app_module.preview, "for_workspace", lambda settings, manifest: manifest)
    with pytest.raises(HTTPException) as refused:
        approve_changes("r", ApprovalIn(keys=["S3:title"]))  # applied already; nothing to approve
    assert refused.value.status_code == 422 and approved == []
    approve_changes("r", ApprovalIn(keys=["S8:entity", "S8:entity"], approved_by="demo@stellar.ai"))
    assert approved == ["S8:entity"]
