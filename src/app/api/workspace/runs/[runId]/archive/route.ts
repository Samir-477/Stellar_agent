import type { NextRequest } from "next/server";
import { engine } from "@/lib/engine";
import { failure, guard, ok } from "@/lib/workspace-api";

export async function PATCH(request: NextRequest, context: { params: Promise<{ runId: string }> }) {
  const denied = await guard(request, { write: true });
  if (denied) return denied;
  try {
    const body = await request.json();
    if (typeof body.archived !== "boolean") return Response.json({ error: "archived must be true or false" }, { status: 422 });
    const { runId } = await context.params;
    return ok(await engine.archiveRun(runId, body.archived));
  } catch (error) {
    return failure(error);
  }
}
