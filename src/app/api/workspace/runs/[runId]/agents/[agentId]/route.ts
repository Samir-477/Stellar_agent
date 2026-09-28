import type { NextRequest } from "next/server";
import { engine } from "@/lib/engine";
import { failure, guard, ok } from "@/lib/workspace-api";

/** One agent's saved report, so it can be opened while the rest of the run is still working. */
export async function GET(request: NextRequest, { params }: RouteContext<"/api/workspace/runs/[runId]/agents/[agentId]">) {
  const denied = await guard(request);
  if (denied) return denied;
  try {
    const { runId, agentId } = await params;
    const report = await engine.agentReport(runId, agentId);
    return report ? ok(report) : Response.json({ error: "This agent hasn't saved its report yet." }, { status: 404 });
  } catch (error) {
    return failure(error);
  }
}
