// TEST DOUBLE of Playwright for gate/exec/axe-run.js (tests/rel076, tests/rel077). No browser: a site is described by
// $FAKEPW_SITE (JSON): {"<path>": {"title", "csp": true|false, "session": true|false, "violations": []}}.
// It models what the 0.7.5 runner met on the real engine (task-tracker MF-49, MF-50):
//   * page.addScriptTag({content}) on a page whose policy forbids inline script throws, as Chromium does;
//   * page.evaluate(<string>) is a DevTools evaluation, which the page's policy does not govern;
//   * a context opened with bypassCSP runs the page's own inline script, which retitles it "CSP-BYPASSED";
//   * POST of the sign-in form sets a __Host- Secure cookie, which Chromium keeps over http only for a
//     localhost or *.localhost name (0.7.7, measured on the real engine with the pinned Chromium: on
//     sut.moadix.test it is refused as InvalidPrefix, with or without --unsafely-treat-insecure-origin-as-secure);
//   * a *.localhost name always resolves to loopback (nothing listens there: connection refused) unless the
//     browser was launched with --host-resolver-rules=MAP <that name> <the app's alias>;
//   * a session page visited without the cookie redirects to /signin.
// Every call is appended to $FAKEPW_LOG (one JSON line) so a test can see what the runner did.
"use strict";
const fs = require("fs");

const SITE = JSON.parse(process.env.FAKEPW_SITE || "{}");
const USER = { "#email": "axe@example.test", "#password": "not-a-secret-fixture" };
const CSP_ERR = "Executing inline script violates the following Content Security Policy directive 'script-src 'self''.";

function log(what, data) {
  if (process.env.FAKEPW_LOG) fs.appendFileSync(process.env.FAKEPW_LOG, JSON.stringify(Object.assign({ what }, data || {})) + "\n");
}

class Context {
  constructor(browser, opts) { this.browser = browser; this.opts = opts || {}; this.jar = []; this.init = []; log("newContext", { opts: this.opts }); }
  async newPage() { return new Page(this); }
  // As Playwright's filterCookies: given URLs, a Secure cookie is left out for an http URL that is not localhost
  // (even when the browser itself keeps and sends it, as for an origin it treats as secure).
  async cookies(urls) {
    const list = urls === undefined ? [] : [].concat(urls).map((u) => new URL(u));
    return this.jar.filter((c) => !list.length || list.some((u) => ("." + u.hostname).endsWith("." + c.domain.replace(/^\./, "")) &&
      (u.protocol === "https:" || /^(localhost|127\.)/.test(u.hostname) || !c.secure))).map((c) => Object.assign({}, c));
  }
  async addInitScript(s) { this.init.push(s); log("context.addInitScript"); }
  async close() { log("context.close"); }
}

class Page {
  constructor(ctx) { this.ctx = ctx; this.u = "about:blank"; this.axe = false; this.t = ""; this.form = {}; this.init = []; }
  _load(url) {
    const u = new URL(url);
    if (/(^|\.)localhost$/.test(u.hostname) &&
        !this.ctx.browser.args.some((a) => a.startsWith("--host-resolver-rules=MAP " + u.hostname + " "))) {
      throw new Error("page.goto: net::ERR_CONNECTION_REFUSED at " + url);
    }
    let spec = SITE[u.pathname];
    if (spec && spec.session && !this.ctx.jar.some((c) => c.name === "__Host-session")) {
      u.pathname = "/signin";
      spec = SITE["/signin"];
    }
    if (!spec) throw new Error("net::ERR_HTTP_RESPONSE_CODE_FAILURE at " + url);
    this.u = u.toString();
    this.spec = spec;
    this.axe = false;
    this.t = this.ctx.opts.bypassCSP || !spec.csp ? "CSP-BYPASSED" : spec.title; // the page's inline script
    if (this.ctx.init.length || this.init.length) this.axe = true; // an init script runs before the page's own
  }
  async goto(url) { log("goto", { url }); this._load(url); return { status: () => 200 }; }
  url() { return this.u; }
  async title() { return this.t; }
  async addScriptTag(o) {
    log("addScriptTag");
    if (this.spec && this.spec.csp && !this.ctx.opts.bypassCSP && o && o.content) throw new Error("page.addScriptTag: " + CSP_ERR);
    this.axe = true;
  }
  async addInitScript(s) { this.init.push(s); log("page.addInitScript"); }
  async evaluate(fn, arg) {
    if (typeof fn === "string") {
      log("evaluate-string", { axe: fn.indexOf("window.axe") >= 0 });
      if (fn.indexOf("window.axe") >= 0) this.axe = true;
      return undefined;
    }
    const src = String(fn);
    if (src.indexOf("axe.run") >= 0) {
      if (!this.axe) throw new Error("page.evaluate: TypeError: Cannot read properties of undefined (reading 'run')");
      log("axe.run", { url: this.u });
      return { violations: (this.spec && this.spec.violations) || [] };
    }
    if (src.indexOf("typeof") >= 0 && src.indexOf("axe") >= 0) return this.axe ? "object" : "undefined";
    throw new Error("fake playwright: unexpected evaluate " + src.slice(0, 80) + JSON.stringify(arg || null));
  }
  async fill(sel, value) { log("fill", { sel }); if (!this.spec || !this.spec.form) throw new Error("page.fill: no element " + sel); this.form[sel] = value; }
  async click(sel) {
    log("click", { sel });
    if (!this.spec || !this.spec.form || sel !== "button[type=submit]") throw new Error("page.click: Timeout 30000ms exceeded waiting for " + sel);
    const ok = Object.keys(USER).every((k) => this.form[k] === USER[k]);
    if (!ok) return;
    const host = new URL(this.u).hostname;
    const kept = new URL(this.u).protocol === "https:" || /(^|\.)localhost$/.test(host);
    log("set-cookie", { kept, reason: kept ? null : "InvalidPrefix" });
    if (kept) this.ctx.jar.push({ name: "__Host-session", value: "x", domain: new URL(this.u).hostname, secure: true });
    this._load(new URL("/tasks", this.u).toString());
  }
  async waitForURL(want, opts) {
    const u = new URL(this.u);
    const ok = typeof want === "function" ? want(u) : (want instanceof RegExp ? want.test(this.u) : this.u === String(want));
    log("waitForURL", { url: this.u, ok });
    if (!ok) throw new Error("page.waitForURL: Timeout " + ((opts && opts.timeout) || 30000) + "ms exceeded (at " + this.u + ")");
  }
  async waitForLoadState() {}
  async close() {}
}

class Browser {
  constructor(args) { this.args = args || []; }
  async newContext(opts) { return new Context(this, opts); }
  async newPage() { return (await this.newContext()).newPage(); }
  async close() { log("browser.close"); }
}

module.exports = {
  chromium: {
    async launch(o) { log("launch", { args: (o && o.args) || [] }); return new Browser((o && o.args) || []); },
  },
};
