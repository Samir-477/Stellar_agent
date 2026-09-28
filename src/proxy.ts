import { NextResponse, type NextRequest } from "next/server";
import { demoCookieName } from "@/lib/demo-auth";

// Optimistic check only: without a session cookie, go to sign-in and come back afterwards.
// The workspace layout and every route handler verify the signed session on the server.
export function proxy(request: NextRequest) {
  if (request.cookies.has(demoCookieName)) return NextResponse.next();
  const login = new URL("/login", request.url);
  login.searchParams.set("next", request.nextUrl.pathname + request.nextUrl.search);
  return NextResponse.redirect(login);
}

export const config = {
  // "/microsites" is the private index only; published microsites below it are public.
  matcher: ["/home", "/runs/:path*", "/sessions/:path*", "/microsites"],
};
