// The fixture app for the live gates. Every HTML page sends a strict Content-Security-Policy (no inline
// script; task-tracker MF-49) and carries an inline script that would retitle the page if the policy were
// not enforced, so a run can show the scan kept it. /tasks needs a session: POST /signin sets a
// __Host- Secure cookie (MF-50), which Chromium keeps over http only for an origin it treats as secure.
import http from "node:http";
import { randomBytes } from "node:crypto";

const CSP = "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self'; object-src 'none'; " +
  "base-uri 'none'; form-action 'self'; frame-ancestors 'none'";
const USER = { email: "axe@example.test", word: "not-a-secret-fixture" };
const sessions = new Set();

function page(title, body) {
  return "<!doctype html><html lang=\"en\"><head><meta charset=\"utf-8\"><title>" + title + "</title>" +
    "<meta name=\"viewport\" content=\"width=device-width, initial-scale=1\"></head><body><main><h1>" + title +
    "</h1>" + body + "</main><script>document.title = \"CSP-BYPASSED\";</script></body></html>";
}

function html(res, status, title, body) {
  res.writeHead(status, { "content-type": "text/html; charset=utf-8", "content-security-policy": CSP });
  res.end(page(title, body));
}

function session(req) {
  const m = /(?:^|;\s*)__Host-session=([0-9a-f]{32})(?:;|$)/.exec(req.headers.cookie || "");
  return m && sessions.has(m[1]);
}

const SIGNIN = "<form method=\"post\" action=\"/signin\"><p><label for=\"email\">Email</label> " +
  "<input id=\"email\" name=\"email\" type=\"email\" autocomplete=\"username\"></p><p><label for=\"password\">" +
  "Password</label> <input id=\"password\" name=\"password\" type=\"password\" autocomplete=\"current-password\">" +
  "</p><p><button type=\"submit\">Sign in</button></p></form>";

http.createServer((req, res) => {
  const url = new URL(req.url, "http://placeholder");
  if (req.method === "POST" && url.pathname === "/signin") {
    let body = "";
    req.on("data", (c) => { body += c; if (body.length > 4096) req.destroy(); });
    req.on("end", () => {
      const f = new URLSearchParams(body);
      if (f.get("email") === USER.email && f.get("password") === USER.word) {
        const id = randomBytes(16).toString("hex");
        sessions.add(id);
        res.writeHead(303, { location: "/tasks",
          "set-cookie": "__Host-session=" + id + "; Path=/; Secure; HttpOnly; SameSite=Lax" });
        res.end();
      } else {
        html(res, 401, "Sign in", "<p role=\"alert\">Wrong email or password.</p>" + SIGNIN);
      }
    });
    return;
  }
  if (req.method !== "GET" && req.method !== "HEAD") {
    res.writeHead(405, { allow: "GET, HEAD", "content-type": "application/json" });
    res.end(JSON.stringify({ error: "method not allowed" }));
    return;
  }
  if (url.pathname === "/health") {
    res.writeHead(200, { "content-type": "application/json" });
    res.end(JSON.stringify({ status: "ok" }));
  } else if (url.pathname === "/") {
    html(res, 200, "Home", "<p>A fixture product. <a href=\"/signin\">Sign in</a></p>");
  } else if (url.pathname === "/signin") {
    html(res, 200, "Sign in", SIGNIN);
  } else if (url.pathname === "/tasks") {
    if (!session(req)) {
      res.writeHead(303, { location: "/signin" });
      res.end();
      return;
    }
    html(res, 200, "Tasks", "<ul><li>Write the release notes</li></ul>");
  } else {
    res.writeHead(404, { "content-type": "application/json" });
    res.end(JSON.stringify({ error: "not found" }));
  }
}).listen(3000);
