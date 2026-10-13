// VPS HTTP adapter for the existing Cloudflare Worker.
// Preserves the entire /discord command, button, modal and background logic.
// STAGING: bind loopback only; do not change Discord Interactions Endpoint yet.
import http from "node:http";
import worker from "./defence-worker.js";

const host = "127.0.0.1";
const port = Number(process.env.DISCORD_HTTP_PORT || 8787);
if (!Number.isInteger(port) || port < 1 || port > 65535) throw new Error("Invalid DISCORD_HTTP_PORT");
const required = ["DISCORD_BOT_TOKEN", "GITHUB_TOKEN", "TELEGRAM_BOT_TOKEN"];
const missing = required.filter(k => !process.env[k]);
if (missing.length) throw new Error("Missing environment variables: " + missing.join(", "));

const env = Object.freeze(Object.fromEntries(Object.entries(process.env)));
const MAX_BYTES = 1024 * 1024;
const pending = new Set();

function background(promise) {
  const task = Promise.resolve(promise);
  pending.add(task);
  task.catch(err => console.error("Worker background task failed:", err))
    .finally(() => pending.delete(task));
}

const server = http.createServer(async (req, res) => {
  if (req.method === "GET" && req.url === "/healthz") {
    res.writeHead(200, { "Content-Type": "application/json" });
    res.end(JSON.stringify({ status: "ok", mode: "staging", pending: pending.size }));
    return;
  }
  // Only the Discord interactions route is exposed by this adapter.
  // Telegram webhooks, queues, and admin endpoints stay on their current owners.
  if (req.method !== "POST" || req.url !== "/discord") {
    res.writeHead(404);
    res.end("Not found");
    return;
  }
  let bytes = 0;
  const chunks = [];
  try {
    for await (const chunk of req) {
      bytes += chunk.length;
      if (bytes > MAX_BYTES) {
        res.writeHead(413);
        res.end("Payload too large");
        return;
      }
      chunks.push(chunk);
    }
    const body = Buffer.concat(chunks);
    // Keep Discord signature headers unchanged: the Worker verifies Ed25519.
    const headers = new Headers();
    for (const [key, value] of Object.entries(req.headers)) {
      if (value !== undefined) headers.set(key, Array.isArray(value) ? value.join(", ") : value);
    }
    const request = new Request("http://localhost/discord", {
      method: "POST", headers, body,
    });
    const ctx = { waitUntil: background, passThroughOnException() {} };
    const response = await worker.fetch(request, env, ctx);
    res.writeHead(response.status, Object.fromEntries(response.headers.entries()));
    res.end(Buffer.from(await response.arrayBuffer()));
  } catch (err) {
    console.error("VPS Discord HTTP handler failed:", err);
    if (!res.headersSent) res.writeHead(500);
    res.end("Internal server error");
  }
});
server.listen(port, host, () => console.log(`Discord Worker compatibility adapter listening on ${host}:${port}`));
process.on("SIGTERM", () => server.close());
process.on("SIGINT", () => server.close());
