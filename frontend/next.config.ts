import os from "os";
import path from "path";
import type { NextConfig } from "next";

// This project lives under ~/Documents, which macOS syncs to iCloud when
// "Desktop & Documents Folders" is enabled. Next rewrites thousands of small
// files in its build directory, and iCloud grabs them mid-rename — producing
// `ENOENT: rename '0.pack.gz_' -> '0.pack.gz'`, duplicate "... 2.json"
// artifacts, CSS chunks that 404, and intermittent 500s.
//
// Pointing distDir outside the synced tree fixes it durably: unlike a symlink
// at frontend/.next, this survives `rm -rf .next`. Override with NEXT_DIST_DIR
// if the project moves somewhere iCloud does not touch.
const distDir = process.env.NEXT_DIST_DIR ?? path.join(os.homedir(), ".hrms-build", "next");

const nextConfig: NextConfig = {
  reactStrictMode: true,
  distDir,
};

export default nextConfig;
