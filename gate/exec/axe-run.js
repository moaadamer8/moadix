// MOADIX gate-owned axe runner (increment 7d; docs/confinement-design.md 3.7). Runs inside the confined
// Chromium container with the gate's pinned playwright and axe-core (gate/config/locks/axe-runner),
// against the app on the run's internal network. It writes raw axe results; the gate decides.
//   node axe-run.js <base-url> <out.json> <path> [<path> ...]
"use strict";
const fs = require("fs");
const path = require("path");
const mods = process.env.MOADIX_TOOL_MODULES || "/deps/tool/node_modules";
const { chromium } = require(path.join(mods, "playwright"));
const axeSource = fs.readFileSync(path.join(mods, "axe-core", "axe.min.js"), "utf8");

async function main() {
  const [base, out, ...paths] = process.argv.slice(2);
  const browser = await chromium.launch({ args: ["--no-sandbox"] });
  const results = [];
  try {
    for (const p of paths.length ? paths : ["/"]) {
      const page = await browser.newPage();
      const url = new URL(p, base).toString();
      let error = null;
      let violations = [];
      try {
        await page.goto(url, { waitUntil: "load", timeout: 30000 });
        await page.addScriptTag({ content: axeSource });
        const r = await page.evaluate(async () => await window.axe.run());
        violations = r.violations;
      } catch (e) {
        error = String(e && e.message ? e.message : e).slice(0, 500);
      }
      results.push({ url, error, violations });
      await page.close();
    }
  } finally {
    await browser.close();
  }
  fs.writeFileSync(out, JSON.stringify({ tool: "axe-core", results }));
}

main().catch((e) => {
  process.stderr.write(String(e) + "\n");
  process.exit(2);
});
