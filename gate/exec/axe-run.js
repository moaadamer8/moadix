// MOADIX gate-owned axe runner (increment 7d; docs/confinement-design.md 3.7). Runs inside the confined
// Chromium container with the gate's pinned playwright and axe-core (gate/config/locks/axe-runner),
// against the app on the run's internal network. It writes raw axe results; the gate decides.
//   node axe-run.js <base-url> <out.json> <path> [<path> ...]
//   node axe-run.js <base-url> <out.json> --paths-file <plan.json>
// The plan file is a JSON array of app-relative paths, or (0.7.6) the gate's plan:
//   {"paths": [...], "public": [...], "signin": {"steps": [{"goto": p} | {"fill": sel, "value": v} |
//                                                         {"click": sel} | {"wait_url": p}]}}
// 0.7.6 (task-tracker MF-49): axe-core is evaluated through the browser automation (a DevTools evaluation,
// which the page's Content-Security-Policy does not govern), never added as an inline <script>, which a
// strict policy (script-src 'self') blocks; the policy itself stays in force (the page is checked as served).
// MF-50: with a sign-in, the runner signs in once in its own context and visits every path that is not
// public with that session. The app's origin is treated as secure, so a Secure (__Host-) session cookie is
// kept over the internal network's plain http, as Chromium keeps it for http://localhost. Cookie values are
// never written out.
"use strict";
const fs = require("fs");
const path = require("path");
const mods = process.env.MOADIX_TOOL_MODULES || "/deps/tool/node_modules";
const { chromium } = require(path.join(mods, "playwright"));
const axeSource = fs.readFileSync(path.join(mods, "axe-core", "axe.min.js"), "utf8");
const TIMEOUT = 30000;

function loadPlan(rest) {
  if (rest[0] !== "--paths-file") return { paths: rest };
  const doc = JSON.parse(fs.readFileSync(rest[1], "utf8"));
  const plan = Array.isArray(doc) ? { paths: doc } : doc;
  const isPath = (p) => typeof p === "string" && p.startsWith("/");
  if (!Array.isArray(plan.paths) || !plan.paths.every(isPath)) {
    throw new Error("the paths file must be a JSON array of app-relative paths, or the gate's plan");
  }
  if (plan.public !== undefined && !(Array.isArray(plan.public) && plan.public.every(isPath))) {
    throw new Error("the plan's public paths must be app-relative paths");
  }
  if (plan.signin !== undefined && !(plan.signin && Array.isArray(plan.signin.steps) && plan.signin.steps.length)) {
    throw new Error("the plan's sign-in must list its steps");
  }
  return plan;
}

function inApp(base, p) {
  const url = new URL(p, base).toString();
  if (new URL(url).origin !== new URL(base).origin) {
    throw new Error("refusing a path that leaves the app: " + p);
  }
  return url;
}

function pathOf(u) {
  const x = new URL(u);
  return x.pathname + x.search;
}

async function signIn(context, base, steps) {
  const page = await context.newPage();
  const first = steps.find((s) => s.goto);
  const out = { ok: false, error: null, page: first ? first.goto : null, landed: null, cookies: 0 };
  try {
    for (const s of steps) {
      if (s.goto !== undefined) {
        await page.goto(inApp(base, s.goto), { waitUntil: "load", timeout: TIMEOUT });
      } else if (s.fill !== undefined) {
        await page.fill(s.fill, String(s.value), { timeout: TIMEOUT });
      } else if (s.click !== undefined) {
        await page.click(s.click, { timeout: TIMEOUT });
      } else if (s.wait_url !== undefined) {
        const want = s.wait_url;
        inApp(base, want);
        await page.waitForURL((u) => pathOf(u.toString()) === want || u.pathname === want, { timeout: TIMEOUT });
      } else {
        throw new Error("unknown sign-in step " + JSON.stringify(Object.keys(s)));
      }
    }
    out.landed = pathOf(page.url());
    // all of the context's cookies, matched to the app's host here: cookies(<url>) leaves a Secure cookie out
    // for an http URL that is not localhost, even though the browser keeps and sends it for this origin
    const host = "." + new URL(base).hostname;
    out.cookies = (await context.cookies()).filter((c) => host.endsWith("." + String(c.domain).replace(/^\./, ""))).length;
    if (!out.cookies) {
      out.error = "the sign-in steps ran, but the browser kept no cookie for " + new URL(base).origin;
    } else {
      out.ok = true;
    }
  } catch (e) {
    out.landed = page.url() && page.url() !== "about:blank" ? pathOf(page.url()) : null;
    out.error = String(e && e.message ? e.message : e).split("\n")[0].slice(0, 400) +
      (out.landed ? " (at " + out.landed + ")" : "");
  }
  await page.close();
  return out;
}

async function check(context, url) {
  const page = await context.newPage();
  const r = { error: null, violations: [], final: null, title: null };
  try {
    await page.goto(url, { waitUntil: "load", timeout: TIMEOUT });
    await page.evaluate(axeSource); // a DevTools evaluation: the page's CSP does not apply to it
    if ((await page.evaluate(() => typeof window.axe)) !== "object") {
      throw new Error("axe-core did not load in the page");
    }
    const res = await page.evaluate(async () => await window.axe.run());
    r.violations = res.violations;
  } catch (e) {
    r.error = String(e && e.message ? e.message : e).slice(0, 500);
  }
  try {
    r.final = page.url();
    r.title = await page.title();
  } catch (e) {
    // the page is gone; the error above says why
  }
  await page.close();
  return r;
}

async function main() {
  const [base, out, ...rest] = process.argv.slice(2);
  const plan = loadPlan(rest);
  const paths = plan.paths.length ? plan.paths : ["/"];
  const pub = new Set(plan.public || []);
  const origin = new URL(base).origin;
  const browser = await chromium.launch({ args: ["--no-sandbox", "--unsafely-treat-insecure-origin-as-secure=" + origin] });
  const results = [];
  let signin;
  try {
    let session = null;
    if (plan.signin) {
      const ctx = await browser.newContext();
      signin = await signIn(ctx, base, plan.signin.steps);
      if (signin.ok) session = ctx;
    }
    for (const p of paths) {
      const url = inApp(base, p);
      const withSession = Boolean(plan.signin) && !pub.has(p);
      if (withSession && !session) {
        results.push({ url, path: p, session: true, final: null, title: null, violations: [],
          error: "not checked: the sign-in failed, and this path is not in axe.public" });
        continue;
      }
      const ctx = withSession ? session : await browser.newContext();
      const r = await check(ctx, url);
      if (!withSession) await ctx.close();
      results.push(Object.assign({ url, path: p, session: withSession }, r));
    }
  } finally {
    await browser.close();
  }
  const doc = { tool: "axe-core", results };
  if (signin) doc.signin = signin;
  fs.writeFileSync(out, JSON.stringify(doc));
}

main().catch((e) => {
  process.stderr.write(String(e) + "\n");
  process.exit(2);
});
