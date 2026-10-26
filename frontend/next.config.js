/** @type {import('next').NextConfig} */
const nextConfig = {
  reactStrictMode: true,
  async rewrites() {
    // Proxies /api/* to the backend so the browser only ever talks to one
    // origin in local dev — avoids a CORS round-trip for every request.
    const backend = process.env.BACKEND_URL || "http://localhost:8000";
    return [{ source: "/api/:path*", destination: `${backend}/api/:path*` }];
  },
};

module.exports = nextConfig;
