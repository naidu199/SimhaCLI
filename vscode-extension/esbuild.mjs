// Bundles the extension (Node) and the chat panel script (browser).
// Usage: node esbuild.mjs [--watch] [--production]
import * as esbuild from "esbuild";

const watch = process.argv.includes("--watch");
const production = process.argv.includes("--production");

const shared = {
  bundle: true,
  minify: production,
  sourcemap: !production,
  logLevel: "info",
};

const builds = [
  {
    ...shared,
    entryPoints: ["src/extension.ts"],
    outfile: "dist/extension.js",
    platform: "node",
    format: "cjs",
    target: "node18",
    external: ["vscode"],
  },
  {
    ...shared,
    entryPoints: ["src/webview/chat.ts"],
    outfile: "dist/webview.js",
    platform: "browser",
    format: "iife",
    target: "es2022",
  },
];

if (watch) {
  for (const options of builds) {
    const context = await esbuild.context(options);
    await context.watch();
  }
} else {
  await Promise.all(builds.map((options) => esbuild.build(options)));
}
