import type { NextConfig } from "next";

// The browser talks only to this app; /v1/* is forwarded to the backend so the
// session cookie stays same-origin (docs/03). Server components call the backend
// directly at API_INTERNAL_URL.
const apiInternalUrl = process.env.API_INTERNAL_URL ?? "http://localhost:8000";

const nextConfig: NextConfig = {
  output: "standalone",
  poweredByHeader: false,
  async rewrites() {
    return [{ source: "/v1/:path*", destination: `${apiInternalUrl}/v1/:path*` }];
  },
};

export default nextConfig;
