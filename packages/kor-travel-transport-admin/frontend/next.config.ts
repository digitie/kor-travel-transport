import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  reactStrictMode: true,
  agentRules: false,
  transpilePackages: ["@kor-travel/parking-ui"],
};

export default nextConfig;
