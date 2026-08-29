import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  // Fully static site (no server actions / dynamic APIs) → export to `out/`
  // for static hosting on Cloudflare Pages.
  output: "export",
  images: { unoptimized: true }, // no server = no next/image optimizer
};

export default nextConfig;
