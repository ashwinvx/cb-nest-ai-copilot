import os from "os";
import path from "path";
import { fileURLToPath } from "url";
import type { NextConfig } from "next";

// This project sits under ~/Documents, which macOS syncs to iCloud when
// "Desktop & Documents Folders" is enabled. Next rewrites thousands of small
// files in its build directory and iCloud grabs them mid-rename, producing
// `ENOENT: rename '0.pack.gz_' -> '0.pack.gz'`, duplicate "... 2" artifacts,
// CSS chunks that 404, and routes that flip between 200 and 500.
//
// Next resolves distDir RELATIVE to the project directory — an absolute path
// is joined onto it, creating frontend/Users/... inside the synced tree. So
// compute the relative path that escapes to an unsynced location. This also
// survives `rm -rf .next`, which a symlink at frontend/.next does not.
// Set NEXT_DIST_DIR to override (a relative value is used as-is).
const projectDir = path.dirname(fileURLToPath(import.meta.url));
const target = process.env.NEXT_DIST_DIR ?? path.join(os.homedir(), ".hrms-build", "next");
const distDir = path.isAbsolute(target) ? path.relative(projectDir, target) : target;

const nextConfig: NextConfig = {
  reactStrictMode: true,
  distDir,
};

export default nextConfig;
