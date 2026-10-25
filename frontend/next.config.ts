import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  output: "standalone",
  reactStrictMode: true,
  devIndicators: false,
  // The two hidden doors (lib/backstage/alias.ts): on red.<site> and blue.<site> the front page is red's / blue's raw console. The page
  // itself 404s for anyone who is not an admin (lib/backstage/gate.ts), so the rewrite reveals nothing to a stranger.
  async rewrites() {
    return {
      beforeFiles: [{ source: "/", has: [{ type: "host", value: "(?<team>red|blue)\\..+" }], destination: "/backstage/:team" }],
      afterFiles: [],
      fallback: [],
    };
  },
};
export default nextConfig;
