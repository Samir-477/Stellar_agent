import type { NextRequest } from "next/server";
import { engine } from "@/lib/engine";
import { failure, guard, ok } from "@/lib/workspace-api";

/** Delete a finished run for good: its reports, previews and microsites. */
export async function DELETE(request: NextRequest, { params }: RouteContext<"/api/workspace/runs/[runId]">) {
  const denied = await guard(request, { write: true });
  if (denied) return denied;
  try {
    return ok(await engine.deleteRun((await params).runId));
  } catch (error) {
    return failure(error);
  }
}
