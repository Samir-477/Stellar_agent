import type { NextRequest } from "next/server";
import { engine } from "@/lib/engine";
import { failure, guard, ok } from "@/lib/workspace-api";

export async function GET(request: NextRequest, { params }: RouteContext<"/api/workspace/runs/[runId]/progress">) {
  const denied = await guard(request);
  if (denied) return denied;
  try {
    return ok(await engine.progress((await params).runId));
  } catch (error) {
    return failure(error);
  }
}
