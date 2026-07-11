// api-server.mjs — the REAL production topology, locally, with no wrangler.
//
// workers/learn-api/src/index.js is a Web-standard `{ fetch(request, env, ctx) }`
// handler. This module wraps that exact default export with the SAME in-memory
// stubs the Worker's own unit tests use (KVStub / D1Stub / makeEnv / mintToken,
// imported straight from workers/learn-api/test/helpers.js) and serves it over a
// real TCP port. It also stands up a second, loopback-only static file server
// for the built site and points the Worker's PAGES_ORIGIN at it — so the
// Worker's /learn/* zone-mount proxy (proxyToPages in index.js) is exercised for
// real, and the browser sees ONE origin:
//
//   http://127.0.0.1:<apiPort>/learn/          -> proxied to the static site
//   http://127.0.0.1:<apiPort>/learn/api/*      -> the Worker's API routes
//
// No cloud, no wrangler, no miniflare: node's global fetch/Request/Response/
// crypto.subtle are all the Worker needs (workers/learn-api/src/util.js says as
// much), so this runs the identical code path production will.

import { createServer } from "node:http";
import { readFile, stat } from "node:fs/promises";
import { extname, join, normalize } from "node:path";
import { fileURLToPath } from "node:url";
import { dirname, resolve } from "node:path";

const here = dirname(fileURLToPath(import.meta.url));
const repoRoot = resolve(here, "..", "..");

// The Worker's default export + its own test doubles — cited, not reimplemented.
const workerMod = await import(
  resolve(repoRoot, "workers/learn-api/src/index.js")
);
const helpers = await import(
  resolve(repoRoot, "workers/learn-api/test/helpers.js")
);

const worker = workerMod.default;
export const { KVStub, D1Stub, makeEnv, mintToken } = helpers;

const CONTENT_TYPES = {
  ".html": "text/html; charset=utf-8",
  ".js": "text/javascript; charset=utf-8",
  ".mjs": "text/javascript; charset=utf-8",
  ".css": "text/css; charset=utf-8",
  ".json": "application/json; charset=utf-8",
  ".svg": "image/svg+xml",
  ".ico": "image/x-icon",
  ".png": "image/png",
  ".jpg": "image/jpeg",
  ".webp": "image/webp",
  ".woff": "font/woff",
  ".woff2": "font/woff2",
  ".txt": "text/plain; charset=utf-8",
  ".xml": "application/xml; charset=utf-8",
  ".webmanifest": "application/manifest+json",
};

// --- static file server (loopback only, the "Cloudflare Pages" stand-in) ------

function startStaticServer(rootDir) {
  const server = createServer(async (req, res) => {
    try {
      const url = new URL(req.url, "http://localhost");
      let pathname = decodeURIComponent(url.pathname);
      // Resolve within rootDir; never escape it.
      let filePath = normalize(join(rootDir, pathname));
      if (!filePath.startsWith(normalize(rootDir))) {
        res.writeHead(403).end("forbidden");
        return;
      }
      let info = await stat(filePath).catch(() => null);
      if (info && info.isDirectory()) {
        filePath = join(filePath, "index.html");
        info = await stat(filePath).catch(() => null);
      }
      if (!info) {
        // SPA-less static site: a missing path is a genuine 404.
        res.writeHead(404, { "Content-Type": "text/plain" }).end("not found");
        return;
      }
      const body = await readFile(filePath);
      const type = CONTENT_TYPES[extname(filePath)] || "application/octet-stream";
      res.writeHead(200, { "Content-Type": type }).end(body);
    } catch (err) {
      res.writeHead(500, { "Content-Type": "text/plain" }).end(String(err));
    }
  });
  return listen(server);
}

// --- worker-wrapping server (the single public origin) ------------------------

async function nodeReqToWebRequest(req) {
  const host = req.headers.host || "127.0.0.1";
  const url = `http://${host}${req.url}`;
  const headers = new Headers();
  for (const [k, v] of Object.entries(req.headers)) {
    if (Array.isArray(v)) v.forEach((one) => headers.append(k, one));
    else if (v != null) headers.set(k, v);
  }
  const init = { method: req.method, headers };
  if (req.method !== "GET" && req.method !== "HEAD") {
    const chunks = [];
    for await (const chunk of req) chunks.push(chunk);
    init.body = Buffer.concat(chunks);
  }
  return new Request(url, init);
}

async function webResponseToNodeRes(webRes, res) {
  const headers = {};
  // getSetCookie() (node 18.14+) keeps multiple Set-Cookie headers distinct.
  const setCookies =
    typeof webRes.headers.getSetCookie === "function"
      ? webRes.headers.getSetCookie()
      : [];
  webRes.headers.forEach((value, key) => {
    if (key.toLowerCase() === "set-cookie") return;
    headers[key] = value;
  });
  // Multiple Set-Cookie headers go in as an ARRAY value on the writeHead
  // headers object — setHeader() AFTER writeHead throws ERR_HTTP_HEADERS_SENT,
  // which corrupts every Set-Cookie-bearing response (login, consent accept,
  // logout, delete). Keep them together in the single writeHead call.
  if (setCookies.length) headers["Set-Cookie"] = setCookies;
  res.writeHead(webRes.status, headers);
  const buf = Buffer.from(await webRes.arrayBuffer());
  res.end(buf);
}

function startWorkerServer(env) {
  const server = createServer(async (req, res) => {
    try {
      const request = await nodeReqToWebRequest(req);
      const webRes = await worker.fetch(request, env, {
        waitUntil() {},
        passThroughOnException() {},
      });
      await webResponseToNodeRes(webRes, res);
    } catch (err) {
      res.writeHead(500, { "Content-Type": "application/json" });
      res.end(JSON.stringify({ error: "gate_server_error", message: String(err) }));
    }
  });
  return listen(server);
}

function listen(server) {
  return new Promise((resolvePromise) => {
    server.listen(0, "127.0.0.1", () => {
      const { port } = server.address();
      resolvePromise({ server, port, origin: `http://127.0.0.1:${port}` });
    });
  });
}

/**
 * Start the full local topology.
 * @param {object} opts
 * @param {string} opts.distDeployDir  the dir that contains `learn/` (deploy shape)
 * @param {string} [opts.sessionSecret]
 * @returns {Promise<{origin, env, db, sessions, sessionSecret, mintToken, close}>}
 */
export async function startTopology({ distDeployDir, sessionSecret } = {}) {
  const secret = sessionSecret || "launch-gate-secret-" + Math.random().toString(36).slice(2);
  const staticSrv = await startStaticServer(distDeployDir);

  const db = new D1Stub();
  const sessions = new KVStub();
  const env = makeEnv({
    SESSION_SECRET: secret,
    DB: db,
    SESSIONS: sessions,
    PAGES_ORIGIN: staticSrv.origin,
  });

  const workerSrv = await startWorkerServer(env);
  // The worker builds absolute redirect/callback URLs from url.origin; give it
  // the real one now that we know the port.
  env.PUBLIC_URL = workerSrv.origin;

  return {
    origin: workerSrv.origin,
    staticOrigin: staticSrv.origin,
    env,
    db,
    sessions,
    sessionSecret: secret,
    mintToken: (learner, ttl) => mintToken(env, learner, ttl),
    async close() {
      await new Promise((r) => staticSrv.server.close(r));
      await new Promise((r) => workerSrv.server.close(r));
    },
  };
}
