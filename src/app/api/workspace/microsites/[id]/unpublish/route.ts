import type { NextRequest } from "next/server";
import { engine } from "@/lib/engine";
import { failure, guard, ok } from "@/lib/workspace-api";

/** Take a live microsite offline. Its versions stay listed. */
export async function POST(request: NextRequest, { params }: RouteContext<"/api/workspace/microsites/[id]/unpublish">) {
  const denied = await guard(request, { write: true });
  if (denied) return denied;
  try {
    return ok(await engine.unpublishMicrosite((await params).id));
  } catch (error) {
    return failure(error);
  }
}
