import "server-only";
import { cookies } from "next/headers";
import { redirect } from "next/navigation";
import { demoCookieName, readDemoSession } from "@/lib/demo-auth";

/** The signed-in workspace user's email, or null. Verified on the server on every call. */
export async function currentUser(): Promise<string | null> {
  return readDemoSession((await cookies()).get(demoCookieName)?.value);
}

/** For pages: send signed-out visitors to the sign-in page, then back here. */
export async function requireUser(next = "/home"): Promise<string> {
  const email = await currentUser();
  if (!email) redirect(`/login?next=${encodeURIComponent(next)}`);
  return email;
}
