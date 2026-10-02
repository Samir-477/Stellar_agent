import type { NextRequest } from "next/server";
import { engine } from "@/lib/engine";
import { currentUser } from "@/lib/session";
import { failure, guard, ok } from "@/lib/workspace-api";

/** Approve prepared changes for the run's diagnosed page; the engine applies them and rebuilds the preview. */
export async function POST(request: NextRequest, { params }: RouteContext<"/api/workspace/runs/[runId]/approvals">) {
  const denied = await guard(request, { write: true });
  if (denied) return denied;
  try {
    const body = await request.json().catch(() => ({}));
    const keys = Array.isArray(body.keys) ? body.keys.filter((k: unknown): k is string => typeof k === "string") : [];
    if (!keys.length) return Response.json({ error: "Choose at least one change to approve." }, { status: 400 });
    return ok(await engine.approveChanges((await params).runId, { keys, approved_by: (await currentUser()) ?? undefined }));
  } catch (error) {
    return failure(error);
  }
}
