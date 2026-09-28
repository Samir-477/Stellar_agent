import "server-only";
import { NextResponse, type NextRequest } from "next/server";
import { EngineError } from "@/lib/engine";
import { currentUser } from "@/lib/session";

/** Browsers send Origin on POST; a request from another site is refused. */
export function sameOrigin(request: NextRequest): boolean {
  const origin = request.headers.get("origin");
  if (!origin) return true;
  try {
    return new URL(origin).host === request.headers.get("host");
  } catch {
    return false;
  }
}

/** Every workspace route handler: a signed-in user, and same-origin for writes. Returns a response to send, or null to continue. */
export async function guard(request: NextRequest, { write = false } = {}): Promise<NextResponse | null> {
  if (write && !sameOrigin(request)) return NextResponse.json({ error: "Request origin is not allowed." }, { status: 403 });
  if (!(await currentUser())) return NextResponse.json({ error: "Sign in again to continue." }, { status: 401 });
  return null;
}

export function failure(error: unknown): NextResponse {
  const status = error instanceof EngineError ? error.status : 500;
  const message = error instanceof Error ? error.message : "Unexpected error.";
  return NextResponse.json({ error: message }, { status: status >= 400 && status < 600 ? status : 500, headers: { "Cache-Control": "no-store" } });
}

export function ok(data: unknown): NextResponse {
  return NextResponse.json(data, { headers: { "Cache-Control": "no-store" } });
}
