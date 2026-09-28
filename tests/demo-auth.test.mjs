import assert from "node:assert/strict";
import { after, test } from "node:test";
import { demoConfigured } from "../src/lib/demo-auth.ts";

const keys = ["NODE_ENV", "VERCEL_ENV", "PREVIEW_DEMO_AUTH", "DEMO_AUTH", "DEMO_LOGIN_EMAIL", "DEMO_LOGIN_PASSWORD",
  "DEMO_SESSION_SECRET"];
const original = Object.fromEntries(keys.map((key) => [key, process.env[key]]));

after(() => {
  for (const key of keys) {
    if (original[key] === undefined) delete process.env[key];
    else process.env[key] = original[key];
  }
});

test("demo credentials are enabled only for local use or an explicitly opted-in deployment", () => {
  process.env.DEMO_LOGIN_EMAIL = "example@example.com";
  process.env.DEMO_LOGIN_PASSWORD = "test-password";
  process.env.DEMO_SESSION_SECRET = "test-secret";

  process.env.NODE_ENV = "development";
  delete process.env.VERCEL_ENV;
  delete process.env.PREVIEW_DEMO_AUTH;
  delete process.env.DEMO_AUTH;
  assert.equal(demoConfigured(), true);

  process.env.NODE_ENV = "production";
  process.env.VERCEL_ENV = "preview";
  assert.equal(demoConfigured(), false);
  process.env.PREVIEW_DEMO_AUTH = "enabled";
  assert.equal(demoConfigured(), true);

  process.env.VERCEL_ENV = "production";
  assert.equal(demoConfigured(), false);
  process.env.DEMO_AUTH = "enabled";
  assert.equal(demoConfigured(), true);
});
