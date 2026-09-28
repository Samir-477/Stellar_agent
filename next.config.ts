import type { NextConfig } from "next";

// In development, forward engine requests to uvicorn. On Vercel, api/index.py
// receives /api/v1/* directly; rewriting to /api/index would lose the API path.
const engineDev = process.env.ENGINE_DEV_URL ?? "http://127.0.0.1:8000";

const nextConfig: NextConfig = {
  async rewrites() {
    return process.env.NODE_ENV === "development" ? [
      {
        source: "/api/v1/:path*",
        destination: `${engineDev}/api/v1/:path*`,
      },
    ] : [];
  },
};

export default nextConfig;
