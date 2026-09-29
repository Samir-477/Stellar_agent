import type { NextRequest } from "next/server";
import { EngineError, engine } from "@/lib/engine";

const VIEWS = new Set(["fixed", "annotated"]);

// Public: the page HTML of a live microsite. It copies the client's own page, so it is sandboxed
// (opaque origin: no cookies, no access to this app) and marked noindex.
export async function GET(request: NextRequest) {
  const slug = request.nextUrl.searchParams.get("slug") ?? "";
  const view = request.nextUrl.searchParams.get("view") ?? "fixed";
  if (!VIEWS.has(view)) return new Response("Not found", { status: 404 });
  try {
    const upstream = await engine.liveMicrositeHtml(slug.split("/"), view as "fixed" | "annotated");
    return new Response(await upstream.text(), {
      headers: {
        "Content-Type": "text/html; charset=utf-8",
        "Content-Security-Policy": "sandbox allow-scripts allow-popups",
        "X-Robots-Tag": "noindex, nofollow",
        "Referrer-Policy": "no-referrer",
        "Cache-Control": "public, max-age=60",
      },
    });
  } catch (error) {
    const status = error instanceof EngineError && error.status === 404 ? 404 : 502;
    return new Response(status === 404 ? "This microsite isn't published." : "The microsite couldn't be loaded.", {
      status, headers: { "X-Robots-Tag": "noindex, nofollow" },
    });
  }
}
