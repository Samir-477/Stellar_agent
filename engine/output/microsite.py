"""Microsites (user decision, 2026-09-28): once the Output preview of a run's diagnosed URL is
approved, the fixed page is published at /microsites/{archetype}/{client_slug}/{page_path}.

A microsite is one immutable version: the fixed page, the page with every change marked, and
the issues found on that page with their before/after code. Publishing the same
slug again supersedes the live version; history is kept. The Next.js app serves it publicly with
noindex (it copies the client's own page, so it must never compete with it in search).
"""

from __future__ import annotations

import re
import uuid
from urllib.parse import urlsplit

from lxml import html as lxml_html

from engine.core.blobstore import BlobStore
from engine.orchestrator import repo
from engine.output.page_review import ReviewError, review_entry_page
from engine.plain import explain, issue_key
from engine.store import Store

ARCHETYPES = ("hospitality", "loans", "retail", "logistics")
SLUG = re.compile(r"^[a-z0-9]+(-[a-z0-9]+)*$")


class MicrositeError(ReviewError):
    """A run that can't be published yet, with a reason a person can act on."""


def slugify(text: str, limit: int = 60) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")
    return slug[:limit].strip("-")


def page_path(url: str) -> str:
    """The URL's full path as a slug path: /resorts-hotels/Shivalik-Chail.html → resorts-hotels/shivalik-chail."""
    segments = [slugify(re.sub(r"\.(html?|php|aspx?)$", "", s, flags=re.I)) for s in urlsplit(url).path.split("/")]
    return "/".join(s for s in segments if s) or "home"


def slug_of(archetype: str, client_slug: str, path: str) -> str:
    return f"{archetype}/{client_slug}/{path}"


def build_microsite(run_id: str, store: Store, blobs: BlobStore, *, client_slug: str | None = None,
                    published_by: str | None = None) -> dict:
    review = review_entry_page(run_id, store, blobs)
    ctx, raw, patches, result = review.ctx, review.raw, review.patches, review.result
    archetype = repo.run_archetype(ctx)
    if archetype not in ARCHETYPES:
        raise MicrositeError("Confirm the business type for this client before publishing.")
    client_slug = client_slug or slugify(ctx["name"])
    if not SLUG.match(client_slug or ""):
        raise MicrositeError("The client part of the address may use only lowercase letters, numbers and hyphens.")
    url = ctx["primary_url"]
    cards = review.issues

    title = (lxml_html.fromstring(raw).findtext(".//title") or "").strip() or None
    micro_id = str(uuid.uuid4())
    prefix = f"share-bundles/microsites/{micro_id}"
    record = {
        "id": micro_id, "client_id": str(ctx["client_id"]), "run_id": run_id, "archetype": archetype,
        "client_slug": client_slug, "page_path": page_path(url), "client_name": ctx["name"], "source_url": url,
        "page_title": title,
        "fixed_key": blobs.put(f"{prefix}/fixed.html", result.fixed_html.encode("utf-8")),
        "annotated_key": blobs.put(f"{prefix}/annotated.html", result.annotated_html.encode("utf-8")),
        "issues": cards, "changes_placed": len(result.placed), "changes_total": len(patches) - len(review.waiting),
        "published_by": published_by,
    }
    return repo.insert_microsite(record)


def complete_issues(row: dict) -> dict:
    """A microsite published before plain words and fix steps existed stores its issues without them. Fill them in
    from the run's own findings when it's served, so every microsite explains its issues the same way; the
    published issues themselves (which, what was fixed, the code) are unchanged."""
    issues = row.get("issues") or []
    if all((i.get("plain") or {}).get("steps") is not None for i in issues):
        return row
    run_id = str(row["run_id"]) if row.get("run_id") else None
    findings = repo.list_findings(run_id) if run_id and repo.run_exists(run_id) else []
    cases = ((repo.get_intelligence_report(run_id) or {}).get("plain_cases") or {}) if findings else {}
    by_title = {(f["check_id"], f.get("title")): f for f in findings}
    by_check = {f["check_id"]: f for f in findings if f["status"] in ("fail", "warn")}
    completed = []
    for issue in issues:
        if (issue.get("plain") or {}).get("steps") is not None:
            completed.append(issue)
            continue
        finding = by_title.get((issue["check_id"], issue.get("title"))) or by_check.get(issue["check_id"])
        if finding:
            plain = explain(finding, cases.get(issue_key(finding)))
            extra = {"verification": finding.get("verification", ""), "effort": finding.get("effort")}
        else:  # the run is gone: the library's words, without a site sentence we can't back up
            plain = {**explain({"check_id": issue["check_id"], "title": issue.get("title", ""),
                                "fix": issue.get("fix", ""), "impact": issue.get("impact", "")}), "site_case": ""}
            extra = {}
        completed.append({**extra, **issue, "plain": plain})
    return {**row, "issues": completed}
