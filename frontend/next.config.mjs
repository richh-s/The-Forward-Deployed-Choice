/**
 * Two modes:
 * - `next build` (NODE_ENV=production): static export to frontend/out,
 *   which FastAPI mounts same-origin at /app — sessions and CSRF work
 *   unchanged, no second deploy service.
 * - `next dev`: rewrites proxy the JSON API and the existing form (write)
 *   routes to the FastAPI dev server on :8000, so cookies stay same-origin
 *   during development too.
 */
const isProd = process.env.NODE_ENV === "production";

const API = process.env.ENGINE_API_URL || "http://localhost:8000";

// Root-level backend paths the dev server must proxy (the SPA itself lives
// under /app, so there is no collision).
const proxied = [
  "api",
  "login",
  "logout",
  "campaigns",
  "approvals",
  "prospects",
  "prospects.csv",
  "jobs",
  "settings",
];

/** @type {import('next').NextConfig} */
const nextConfig = {
  basePath: "/app",
  trailingSlash: true,
  ...(isProd
    ? { output: "export" }
    : {
        async rewrites() {
          return proxied.flatMap((p) => [
            { source: `/${p}`, destination: `${API}/${p}`, basePath: false },
            {
              source: `/${p}/:path*`,
              destination: `${API}/${p}/:path*`,
              basePath: false,
            },
          ]);
        },
      }),
};

export default nextConfig;
