import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  // the compare page reads reports/insights.md at runtime; make sure it ships with the serverless bundle
  outputFileTracingIncludes: { "/dashboard/compare": ["./reports/insights.md"] },
  /* config options here */
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
