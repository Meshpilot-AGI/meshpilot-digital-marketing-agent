import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  // Fully static site (no server actions / dynamic APIs) → export to `out/`
  // for static hosting on Cloudflare Pages.
  output: "export",
  images: { unoptimized: true }, // no server = no next/image optimizer
  experimental: {
    optimizePackageImports: ["lucide-react"], // tree-shake icon imports → smaller JS
  },
};

export default nextConfig;
