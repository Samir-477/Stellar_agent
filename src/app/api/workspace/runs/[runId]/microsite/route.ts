import type { NextRequest } from "next/server";
import { engine } from "@/lib/engine";
import { currentUser } from "@/lib/session";
import { failure, guard, ok } from "@/lib/workspace-api";

/** Approve the Output preview of the run's diagnosed URL and publish it as a microsite. */
export async function POST(request: NextRequest, { params }: RouteContext<"/api/workspace/runs/[runId]/microsite">) {
  const denied = await guard(request, { write: true });
  if (denied) return denied;
  try {
    const body = await request.json().catch(() => ({}));
    const clientSlug = typeof body.client_slug === "string" ? body.client_slug.trim().toLowerCase() : undefined;
    const published = await engine.publishMicrosite((await params).runId, {
      client_slug: clientSlug || undefined, published_by: (await currentUser()) ?? undefined,
    });
    return ok(published);
  } catch (error) {
    return failure(error);
  }
}
