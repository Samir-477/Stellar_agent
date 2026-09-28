import type { NextRequest } from "next/server";
import { engine } from "@/lib/engine";
import { failure, guard, ok } from "@/lib/workspace-api";

const ARCHETYPES = new Set(["hospitality", "loans", "retail", "logistics"]);

export async function POST(request: NextRequest, { params }: RouteContext<"/api/workspace/runs/[runId]/archetype">) {
  const denied = await guard(request, { write: true });
  if (denied) return denied;
  try {
    const { archetype } = await request.json();
    if (!ARCHETYPES.has(archetype)) return Response.json({ error: "Choose a business type." }, { status: 422 });
    return ok(await engine.confirmArchetype((await params).runId, archetype));
  } catch (error) {
    return failure(error);
  }
}
