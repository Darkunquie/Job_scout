import type { NextConfig } from "next";

const API = process.env.JOBSCOUT_API ?? "http://127.0.0.1:8010";

const nextConfig: NextConfig = {
  // Proxy the FastAPI backend so the browser sees one origin. The session cookie is SameSite=Lax,
  // which a cross-origin fetch would drop — this keeps auth working without loosening the cookie.
  async rewrites() {
    return [{ source: "/api/:path*", destination: `${API}/api/:path*` }];
  },
};

export default nextConfig;
