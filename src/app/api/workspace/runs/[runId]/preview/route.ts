import type { NextRequest } from "next/server";
import { engine } from "@/lib/engine";
import { failure, guard, ok } from "@/lib/workspace-api";

/** Build (or rebuild) the internal preview: every proposed change applied to the captured pages. */
export async function POST(request: NextRequest, { params }: RouteContext<"/api/workspace/runs/[runId]/preview">) {
  const denied = await guard(request, { write: true });
  if (denied) return denied;
  try {
    return ok(await engine.buildPreview((await params).runId));
  } catch (error) {
    return failure(error);
  }
}
