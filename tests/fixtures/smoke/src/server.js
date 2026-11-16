"use strict";
const http = require("http");

const page = "<!doctype html><html lang=\"en\"><head><meta charset=\"utf-8\"><title>Smoke</title>" +
  "<meta name=\"viewport\" content=\"width=device-width, initial-scale=1\"></head>" +
  "<body><main><h1>Smoke fixture</h1><p>A page for axe and Lighthouse.</p></main></body></html>";

http.createServer((req, res) => {
  if (req.url === "/health") {
    res.writeHead(200, { "content-type": "application/json" });
    res.end(JSON.stringify({ status: "ok" }));
    return;
  }
  if (req.url === "/" || req.url === "/index.html") {
    res.writeHead(200, { "content-type": "text/html; charset=utf-8" });
    res.end(page);
    return;
  }
  res.writeHead(404, { "content-type": "application/json" });
  res.end(JSON.stringify({ error: "not found" }));
}).listen(3000);
