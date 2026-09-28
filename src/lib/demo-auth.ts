import { createHmac, createHash, timingSafeEqual } from "node:crypto";

export const demoCookieName = "stellar_demo_session";

function matches(actual: string, expected: string): boolean {
  const actualHash = createHash("sha256").update(actual).digest();
  const expectedHash = createHash("sha256").update(expected).digest();
  return timingSafeEqual(actualHash, expectedHash);
}

function sessionSecret(): string | undefined {
  return process.env.DEMO_SESSION_SECRET;
}

export function demoConfigured(): boolean {
  const previewAccess = process.env.VERCEL_ENV === "preview" && process.env.PREVIEW_DEMO_AUTH === "enabled";
  return (process.env.NODE_ENV !== "production" || previewAccess) &&
    Boolean(process.env.DEMO_LOGIN_EMAIL && process.env.DEMO_LOGIN_PASSWORD && sessionSecret());
}

export function validDemoCredentials(email: string, password: string): boolean {
  if (!demoConfigured()) return false;
  return matches(email.trim().toLowerCase(), process.env.DEMO_LOGIN_EMAIL!.toLowerCase()) &&
    matches(password, process.env.DEMO_LOGIN_PASSWORD!);
}

export function createDemoSession(): string {
  const payload = Buffer.from(JSON.stringify({
    email: process.env.DEMO_LOGIN_EMAIL,
    expiresAt: Date.now() + 8 * 60 * 60 * 1000,
  })).toString("base64url");
  const signature = createHmac("sha256", sessionSecret()!).update(payload).digest("base64url");
  return `${payload}.${signature}`;
}

export function readDemoSession(value: string | undefined): string | null {
  const secret = sessionSecret();
  if (!demoConfigured() || !secret || !value) return null;
  const [payload, signature, extra] = value.split(".");
  if (!payload || !signature || extra) return null;
  const expected = createHmac("sha256", secret).update(payload).digest("base64url");
  if (!matches(signature, expected)) return null;
  try {
    const data = JSON.parse(Buffer.from(payload, "base64url").toString("utf8"));
    return data.email === process.env.DEMO_LOGIN_EMAIL && data.expiresAt > Date.now() ? data.email : null;
  } catch {
    return null;
  }
}
