"""Interim share viewer, served by the engine until the Next.js UI replaces it.

Security (docs/spec/06): client HTML is served with `Content-Security-Policy: sandbox allow-scripts`,
which gives it an opaque origin (it can't read cookies or call our API), and every
share response carries `X-Robots-Tag: noindex, nofollow`.
"""

from __future__ import annotations

import html
import json

from fastapi import APIRouter, HTTPException, Response
from fastapi.responses import HTMLResponse, JSONResponse

from engine.core.blobstore import make_blob_store
from engine.core.config import get_settings
from engine.output.share import resolve_share

router = APIRouter()
NOINDEX = {"X-Robots-Tag": "noindex, nofollow", "Referrer-Policy": "no-referrer", "Cache-Control": "private, max-age=300"}


def _manifest(token: str, count_view: bool = False) -> dict:
    share = resolve_share(token, count_view=count_view)
    if share is None:
        raise HTTPException(404, "This link is invalid or has expired.")
    blobs = make_blob_store(get_settings())
    return json.loads(blobs.get(f"{share['bundle_prefix']}/manifest.json"))


@router.get("/r/{token}/manifest.json")
def manifest(token: str) -> JSONResponse:
    return JSONResponse(_manifest(token), headers=NOINDEX)


@router.get("/r/{token}/p/{index}/{variant}")
def page_variant(token: str, index: int, variant: str) -> Response:
    if variant not in ("original", "annotated", "fixed"):
        raise HTTPException(404)
    data = _manifest(token)
    page = next((p for p in data["pages"] if p["index"] == index), None)
    if page is None or not page.get(f"{variant}_key"):
        raise HTTPException(404)
    body = make_blob_store(get_settings()).get(page[f"{variant}_key"])
    headers = {**NOINDEX, "Content-Security-Policy": "sandbox allow-scripts allow-popups; frame-ancestors 'self'"}
    return Response(body, media_type="text/html; charset=utf-8", headers=headers)


@router.get("/r/{token}", response_class=HTMLResponse)
def viewer(token: str) -> HTMLResponse:
    data = _manifest(token, count_view=True)
    return HTMLResponse(_shell(token, data), headers={**NOINDEX,
                        "Content-Security-Policy": "default-src 'self'; style-src 'self' 'unsafe-inline'; "
                                                   "script-src 'unsafe-inline'; frame-src 'self'"})


def _esc(value) -> str:
    return html.escape(str(value or ""))


def _shell(token: str, data: dict) -> str:
    ready = " ".join(f'<span class="pill">{_esc(k.upper())} <b>{_esc(v.get("score"))}</b></span>'
                     for k, v in sorted(data.get("readiness", {}).items()))
    options = "".join(f'<option value="{p["index"]}">{_esc(p["url"])} ({len(p["changes"])} change'
                      f'{"s" if len(p["changes"]) != 1 else ""})</option>' for p in data["pages"])
    summary = " ".join(_esc(s) for s in data.get("client_summary", []))
    captured = _esc(data["captured_at"][:10])
    preview = '<div class="warn">Internal preview: includes changes not yet approved.</div>' \
        if data.get("include_proposed") else ""
    return f"""<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1"><meta name="robots" content="noindex, nofollow">
<title>Suggested changes · {_esc(data['client'])}</title>
<style>
:root{{--bg:#f7f7f8;--fg:#18181b;--muted:#6b7280;--card:#fff;--line:#e4e4e7;--accent:#e8590c}}
@media (prefers-color-scheme:dark){{:root{{--bg:#111113;--fg:#f4f4f5;--muted:#a1a1aa;--card:#1c1c1f;--line:#2e2e33}}}}
*{{box-sizing:border-box}}body{{margin:0;font:15px/1.5 system-ui,sans-serif;background:var(--bg);color:var(--fg)}}
header{{padding:16px;border-bottom:1px solid var(--line);background:var(--card)}}
h1{{font-size:18px;margin:0 0 4px}}.muted{{color:var(--muted);font-size:13px}}
.pill{{display:inline-block;border:1px solid var(--line);border-radius:999px;padding:2px 10px;margin:6px 6px 0 0;font-size:13px}}
.summary{{margin:10px 0 0;max-width:900px}}.warn{{margin-top:8px;color:var(--accent);font-weight:600;font-size:13px}}
.bar{{display:flex;flex-wrap:wrap;gap:8px;align-items:center;padding:10px 16px;border-bottom:1px solid var(--line)}}
select,button{{font:inherit;padding:6px 10px;border-radius:8px;border:1px solid var(--line);background:var(--card);color:var(--fg)}}
select{{max-width:100%}}button[aria-pressed=true]{{background:var(--accent);color:#fff;border-color:var(--accent)}}
iframe{{width:100%;height:calc(100vh - 230px);min-height:420px;border:0;background:#fff}}
#hood{{display:none;padding:16px;max-width:1000px}}#hood pre{{white-space:pre-wrap;background:var(--card);border:1px solid var(--line);
padding:10px;border-radius:8px;font-size:12px;overflow:auto;max-height:340px}}
.change{{border-bottom:1px solid var(--line);padding:12px 0}}
</style></head><body>
<header><h1>Suggested changes for {_esc(data['client'])}</h1>
<div class="muted">Captured {captured} from the live site. Interactive parts (booking forms, sliders) are frozen.</div>
<div>{ready}</div><p class="summary">{summary}</p>{preview}</header>
<div class="bar"><label for="page" class="muted">Page</label><select id="page">{options}</select>
<button data-view="annotated" aria-pressed="true">Annotated</button><button data-view="fixed" aria-pressed="false">Fixed version</button>
<button data-view="hood" aria-pressed="false">Under the hood</button></div>
<iframe id="frame" title="Page preview" sandbox="allow-scripts allow-popups"></iframe><div id="hood"></div>
<script id="manifest" type="application/json">{json.dumps(data).replace("</", "<\\/")}</script>
<script>
(function(){{var data=JSON.parse(document.getElementById('manifest').textContent),view='annotated';
var sel=document.getElementById('page'),frame=document.getElementById('frame'),hood=document.getElementById('hood');
function esc(s){{return String(s==null?'':s).replace(/[&<>"]/g,function(c){{return {{'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}}[c]}})}}
function page(){{return data.pages.filter(function(p){{return String(p.index)===sel.value}})[0]}}
function render(){{var p=page();if(!p)return;
 if(view==='hood'){{frame.style.display='none';hood.style.display='block';
  var items=p.under_the_hood.concat(data.site_files);
  hood.innerHTML=(items.length?items.map(function(i){{return '<div class="change"><b>'+esc(i.title||i.type)+'</b><div class="muted">'+esc(i.note)+'</div>'+
  (i.before?'<div class="muted">Now</div><pre>'+esc(i.before)+'</pre>':'')+'<div class="muted">Suggested</div><pre>'+esc(i.after)+'</pre></div>'}}).join(''):'<p>No behind-the-scenes changes for this page.</p>')+
  (p.not_placed.length?'<p class="muted">'+p.not_placed.length+' change(s) could not be placed on the captured page.</p>':'');}}
 else{{hood.style.display='none';frame.style.display='block';frame.src='/r/{_esc(token)}/p/'+p.index+'/'+view;}}}}
sel.onchange=render;document.querySelectorAll('[data-view]').forEach(function(b){{b.onclick=function(){{view=b.dataset.view;
 document.querySelectorAll('[data-view]').forEach(function(x){{x.setAttribute('aria-pressed',String(x===b))}});render();}}}});
render();}})();
</script></body></html>"""
