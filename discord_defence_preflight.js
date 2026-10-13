// Read-only preflight. Run before enabling VPS Discord publishing.
// Does not connect to Discord or mutate any bot state.
import { readFile } from "node:fs/promises";
import { activeDefenceRequests } from "./discord_defence_threads.js";

const statePath = process.env.DISCORD_DEFENCE_STATE_PATH || "data/defence/requests.json";
const playersPath = process.env.DISCORD_PLAYERS_PATH || "data/defence/discord_players.json";

async function inspectJson(path) {
  try {
    return JSON.parse(await readFile(path, "utf8"));
  } catch (error) {
    return { _readError: `${error.code || error.name}: ${error.message}` };
  }
}

const requests = await inspectJson(statePath);
const players = await inspectJson(playersPath);
const problems = [];
if (!Array.isArray(requests)) problems.push(`Requests not readable as array: ${requests?._readError || "wrong format"}`);
if (!players || Array.isArray(players) || typeof players !== "object" || players._readError) {
  problems.push(`Discord players not readable as object: ${players?._readError || "wrong format"}`);
}
if (Array.isArray(requests)) {
  const seen = new Set();
  for (const q of requests) {
    if (!Number.isInteger(Number(q.id)) || Number(q.id) <= 0) problems.push("Request has invalid ID");
    if (seen.has(String(q.id))) problems.push(`Duplicate request ID: ${q.id}`);
    seen.add(String(q.id));
    if (q.status === "active" && (!q.attack_time || !Number.isFinite(Number(q.required_def)))) {
      problems.push(`Invalid active request #${q.id}`);
    }
  }
}
const report = {
  mode: "read_only",
  requests_file: statePath,
  players_file: playersPath,
  requests_total: Array.isArray(requests) ? requests.length : null,
  active_requests: Array.isArray(requests) ? activeDefenceRequests(requests).map(q => q.id) : null,
  registered_discord_players: players && !players._readError && !Array.isArray(players) ? Object.keys(players).length : null,
  problems,
  ready_for_live_cutover: false,
};
console.log(JSON.stringify(report, null, 2));
if (problems.length) process.exitCode = 1;
