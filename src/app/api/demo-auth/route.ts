import { NextRequest, NextResponse } from "next/server";
import { createDemoSession, demoConfigured, demoCookieName, validDemoCredentials } from "@/lib/demo-auth";
import { sameOrigin } from "@/lib/workspace-api";

export async function POST(request: NextRequest) {
  if (!sameOrigin(request)) return NextResponse.json({ error: "Request origin is not allowed." }, { status: 403 });
  if (!demoConfigured()) return NextResponse.json({ error: "Demo access is not configured." }, { status: 503 });

  let body: { email?: unknown; password?: unknown };
  try {
    body = await request.json();
  } catch {
    return NextResponse.json({ error: "Enter your email and password." }, { status: 400 });
  }
  const email = typeof body.email === "string" ? body.email : "";
  const password = typeof body.password === "string" ? body.password : "";
  if (email.length > 200 || password.length > 200 || !validDemoCredentials(email, password)) {
    return NextResponse.json({ error: "Email or password is incorrect." }, { status: 401, headers: { "Cache-Control": "no-store" } });
  }

  const response = NextResponse.json({ email: process.env.DEMO_LOGIN_EMAIL }, { headers: { "Cache-Control": "no-store" } });
  response.cookies.set(demoCookieName, createDemoSession(), {
    httpOnly: true,
    secure: process.env.NODE_ENV === "production",
    sameSite: "strict",
    path: "/",
    maxAge: 8 * 60 * 60,
  });
  return response;
}

export async function DELETE(request: NextRequest) {
  if (!sameOrigin(request)) return NextResponse.json({ error: "Request origin is not allowed." }, { status: 403 });
  const response = NextResponse.json({ signedOut: true }, { headers: { "Cache-Control": "no-store" } });
  response.cookies.delete(demoCookieName);
  return response;
}
