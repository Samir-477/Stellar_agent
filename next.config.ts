import type { NextConfig } from "next";

// In development, forward engine requests to uvicorn. On Vercel, vercel.json rewrites
// /api/v1/* to api/index.py, and FastAPI still sees the original /api/v1 path.
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
