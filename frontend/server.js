/**
 * Production static server for the frontend.
 * Serves the built app and proxies /api requests to the backend.
 *
 * Usage: node server.js
 * Environment: BACKEND_URL (default: http://backend:8000), PORT (default: 3000)
 */

import http from "node:http";
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const PORT = parseInt(process.env.PORT || "3000", 10);
const BACKEND_URL = process.env.BACKEND_URL || "http://backend:8000";
const DIST_DIR = path.join(__dirname, "dist");

const MIME_TYPES = {
  ".html": "text/html; charset=utf-8",
  ".js": "application/javascript",
  ".css": "text/css",
  ".json": "application/json",
  ".png": "image/png",
  ".jpg": "image/jpeg",
  ".svg": "image/svg+xml",
  ".ico": "image/x-icon",
  ".woff2": "font/woff2",
};

const SECURITY_HEADERS = {
  "Content-Security-Policy":
    "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; " +
    "img-src 'self' blob: data:; media-src 'self' blob:; connect-src 'self'; " +
    "object-src 'none'; base-uri 'self'; frame-ancestors 'none'",
  "X-Content-Type-Options": "nosniff",
  "Referrer-Policy": "no-referrer",
};

function safePath(urlPath) {
  // Remove query string first
  const pathOnly = urlPath.split("?")[0];
  let decoded;
  try {
    decoded = decodeURIComponent(pathOnly);
  } catch {
    return null;
  }
  // Reject NUL bytes after decoding (catches encoded NUL)
  if (decoded.includes("\0")) return null;
  // Normalize: strip leading slash, resolve, check boundary
  const normalized = decoded.startsWith("/") ? decoded.slice(1) : decoded;
  const resolved = path.resolve(DIST_DIR, normalized);
  // Must stay strictly within DIST_DIR (not a sibling like DIST_DIR-secret)
  const rel = path.relative(DIST_DIR, resolved);
  // Allow exact root (rel === "") and subdirectories (rel does not start with "..")
  if (rel.startsWith("..") || path.isAbsolute(rel)) return null;
  return resolved;
}

function serveStatic(req, res) {
  let filePath = safePath(req.url);
  if (!filePath) {
    res.writeHead(400, { "Content-Type": "text/plain" });
    res.end("Bad Request");
    return;
  }

  // SPA fallback: serve index.html for non-file routes
  if (!path.extname(filePath) || !fs.existsSync(filePath)) {
    filePath = path.join(DIST_DIR, "index.html");
  }

  const ext = path.extname(filePath).toLowerCase();
  const contentType = MIME_TYPES[ext] || "application/octet-stream";

  fs.readFile(filePath, (err, data) => {
    if (err) {
      fs.readFile(path.join(DIST_DIR, "index.html"), (err2, data2) => {
        if (err2) {
          res.writeHead(500, { "Content-Type": "text/plain" });
          res.end("Internal Server Error");
          return;
        }
        res.writeHead(200, { "Content-Type": "text/html; charset=utf-8" });
        res.end(data2);
      });
      return;
    }
    res.writeHead(200, { "Content-Type": contentType });
    res.end(data);
  });
}

function proxyRequest(req, res) {
  const options = {
    hostname: new URL(BACKEND_URL).hostname,
    port: new URL(BACKEND_URL).port || 80,
    path: req.url,
    method: req.method,
    headers: { ...req.headers, host: new URL(BACKEND_URL).host },
  };

  const proxyReq = http.request(options, (proxyRes) => {
    res.writeHead(proxyRes.statusCode, proxyRes.headers);
    proxyRes.pipe(res);
  });

  proxyReq.on("error", () => {
    res.writeHead(502, { "Content-Type": "application/json" });
    res.end(JSON.stringify({ code: "PROXY_ERROR", detail: "后端服务不可用" }));
  });

  req.pipe(proxyReq);
}

const server = http.createServer((req, res) => {
  // Add security headers
  for (const [key, value] of Object.entries(SECURITY_HEADERS)) {
    res.setHeader(key, value);
  }

  if (req.url.startsWith("/api/")) {
    proxyRequest(req, res);
    return;
  }

  serveStatic(req, res);
});

process.on("SIGTERM", () => {
  server.close(() => process.exit(0));
});

server.listen(PORT, () => {
  console.log(`Frontend server listening on port ${PORT}, proxying /api to ${BACKEND_URL}`);
});
