# 6. Output Layer: the Shareable Client Page

## What the client sees

A link like `https://share.<your-domain>/r/{token}` opens a page that looks like their own website, captured at crawl time, with three views:

| View | What it shows |
|---|---|
| **Annotated** (default) | The original page, with every changed spot outlined. Clicking a highlight opens a card: the issue in plain language, before → after, why it matters, and which pillar (SEO/AEO/GEO) it helps. |
| **Fixed** | The same page with all approved changes applied, as it would look after the fixes. |
| **Under the hood** | Changes that aren't visible on the page: `<head>` tags, JSON-LD, robots.txt, sitemap, llms.txt and HTTP header recommendations, each shown as a before/after diff with a copy button. |

A top bar holds the page switcher (every crawled page with changes), the view toggle, the client-version summary from the intelligence report, and a download button.

## How a share page is built

```
snapshot rendered HTML ──► 1 freeze ──► 2 archive assets ──► 3 apply patches ──► 4 annotate ──► 5 package ──► 6 publish
```

1. **Freeze.** Start from the rendered HTML (the DOM after JavaScript ran, captured by C1), so the page looks like what visitors see. Strip all scripts (no client tracking, chat widgets or popups can run) and cookie/consent overlays, and keep the `<head>`.
2. **Archive assets.** Download the page's CSS, images and fonts into Supabase Storage (`assets` bucket) and rewrite the URLs to point there. The share page then keeps working even if the client changes or removes those files, and it doesn't hotlink the client's servers. Per-page cap (default 15 MB); anything over the cap stays hotlinked and is marked.
3. **Apply patches.** Apply approved patches to a copy of the frozen DOM using each patch's locator: CSS selector first, XPath as fallback, and a text-hash check to confirm the right element. A patch whose element no longer matches is skipped and listed in the report ("could not place"), never forced.
4. **Annotate.** For the Annotated view, wrap each patched element in a marker (`data-fix-id`) and inject the share page's own small overlay script. Visible text patches show the original text with the change on hover or click; inserted elements (new answer sections, author boxes) appear with a "new" badge.
5. **Package.** Produce two HTML documents per page (`original+annotations`, `fixed`), the "Under the hood" diff data (JSON), and a download bundle:
   - `fixed/<page>.html`: complete fixed HTML with the head changes (meta, canonical, JSON-LD) included in the files, as you asked.
   - `files/robots.txt`, `files/sitemap.xml`, `files/llms.txt`: proposed versions.
   - `patches.json`: every patch in machine-readable form, so the client's developers or another system can apply them.
   - `README.md`: plain-language summary of the changes.
6. **Publish.** Store the bundle in the `share-bundles` bucket and create the share record (token, expiry, optional password).

## Review before sharing

Patches start as `proposed`. The team approves, edits or rejects them in the dashboard's patch review screen, and only approved (or edited) patches go on the share page. A run-level switch can auto-approve `confirmed`, deterministic patches (e.g. missing canonical, broken JSON-LD syntax). Copy rewrites and new content always need a human approval.

## Security and SEO safety

| Risk | Protection |
|---|---|
| Client HTML running code on our domain | Snapshots are served from a **separate, cookie-less origin** (`share.<your-domain>`), inside a sandboxed iframe with scripts disabled except our overlay. The dashboard's session cookies can't be reached from it. |
| The share copy getting indexed as duplicate content of the client's site | `X-Robots-Tag: noindex, nofollow`, `robots.txt` disallowing everything on the share origin, and no sitemap. The client's canonical tags point to the client's own URLs. |
| Leaked links | Tokens are 128-bit random, stored hashed. Links expire (default 30 days), can be revoked, and can require a password. Views are counted. |
| Stale rendering | Every share page shows the snapshot date: "Captured 27 Sep 2026". |

## Limits to state honestly

- **Interactive parts are frozen.** Booking engines, calculators, sliders and menus appear as captured but don't work. The share page says so.
- **Content behind logins or forms** isn't crawled, so it isn't shown.
- **Personalised or geo-varied pages** show what the crawler (in India) saw.
- **Heavy single-page apps** can shift between renders. Patches that can't be placed are listed rather than guessed.

## Agent-run shares

An agent run can publish a share page with only that agent's approved patches (for example, just S3's title fixes). The intelligence summary is omitted, and the top bar names the agent.
