"""The diagnosed page, reviewed: its captured HTML with every proposed change applied, and the issues
found on it (fixed first). The workspace preview and a published microsite both come from this one
computation, so they never disagree."""

from __future__ import annotations

from dataclasses import dataclass

from engine.core.blobstore import BlobStore
from engine.issues import build_issue_cards
from engine.lib.urls import norm
from engine.orchestrator import repo
from engine.output.diffs import page_snippets
from engine.output.patcher import PlacementResult, apply
from engine.store import Store

MAX_ISSUES = 40


class ReviewError(ValueError):
    """The page can't be reviewed yet, with a reason a person can act on."""


@dataclass
class PageReview:
    ctx: dict
    url: str  # the page as captured (after redirects)
    raw: str
    patches: list[dict]  # the changes proposed for this page, each with the title of the issue it fixes
    result: PlacementResult
    issues: list[dict]  # fixed first; observations left out; at most MAX_ISSUES


def _page_for(store: Store, snapshot_id: str, url: str):
    target = norm(url)
    return next((p for p in store.list_pages(snapshot_id) if target in (norm(p.url), norm(p.final_url or p.url))), None)


def review_entry_page(run_id: str, store: Store, blobs: BlobStore) -> PageReview:
    run = repo.get_run(run_id)
    if run is None:
        raise ReviewError("This run no longer exists; it may have been deleted. Open the run again from Sessions.")
    if run["status"] not in ("completed", "completed_partial"):
        raise ReviewError("The run hasn't finished yet.")
    ctx = repo.run_context(run_id)
    page = _page_for(store, str(run["snapshot_id"]), ctx["primary_url"])
    if page is None or not page.raw_html_key:
        raise ReviewError("The diagnosed page wasn't captured in this run.")
    try:
        raw = blobs.get(page.raw_html_key).decode("utf-8", errors="replace")
    except Exception as exc:  # noqa: BLE001 - storage errors differ by backend
        raise ReviewError("The captured page isn't in this engine's storage.") from exc

    page_urls = {norm(page.url), norm(page.final_url or page.url)}
    patches = [p for p in repo.list_patches(run_id) if p.get("page_url") and norm(p["page_url"]) in page_urls]
    findings = repo.list_findings(run_id)
    titles = {key: f["title"] for f in findings for key in f.get("patch_keys", [])}
    for patch in patches:
        patch["title"] = titles.get(patch["key"], "Suggested change")
    result = apply(raw, page.final_url or page.url, patches)

    issues = []
    for card in build_issue_cards(findings, patches, page_snippets(raw, patches)):
        on_page = any(norm(p) in page_urls for p in card["pages"]) or bool(card["changes"])
        if not on_page or card["fix_type"] == "observation":
            continue
        changes = [c for c in card["changes"] if c["page_url"] and norm(c["page_url"]) in page_urls]
        issues.append({k: card[k] for k in ("agent_id", "agent_name", "check_id", "status", "severity", "title",
                                            "impact", "fix", "fix_type")}
                      | {"fixed": any(c["key"] in result.placed for c in changes),
                         "changes": [{k: c[k] for k in ("type", "language", "before", "after", "before_segments",
                                                        "after_segments", "note")} for c in changes]})
    issues.sort(key=lambda i: not i["fixed"])
    return PageReview(ctx=ctx, url=page.final_url or page.url, raw=raw, patches=patches, result=result,
                      issues=issues[:MAX_ISSUES])
