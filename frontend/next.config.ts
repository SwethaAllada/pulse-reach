import type { NextConfig } from "next";

// Accepting a backend without authentication is a local-development escape hatch (lib/auth/mode.ts).
// Refuse to build or serve a production bundle with it, so it can never be enabled silently.
if (process.env.NODE_ENV === "production" && process.env.NEXT_PUBLIC_ALLOW_LEGACY_BACKEND === "true") {
  throw new Error(
    "NEXT_PUBLIC_ALLOW_LEGACY_BACKEND=true is a local-development setting and cannot be used for production builds or `next start`."
  );
}

const nextConfig: NextConfig = {
  /* config options here */
  cacheComponents: true,
  partialPrefetching: true,
  turbopack: {
    rules: {
      "*.css": {
        loaders: ["@tailwindcss/turbopack"],
        as: "*.css",
      },
    },
  },
};

export default nextConfig;
