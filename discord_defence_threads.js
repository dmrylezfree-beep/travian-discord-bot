// VPS defence thread synchronizer. Disabled until the migration cutover.
// The active Cloudflare Worker remains the sole Discord publisher meanwhile.
import { readFile } from "node:fs/promises";

const CHANNEL_ID = "1430982180401578153";
const PREFIX = "🛡 DEF #";

export function activeDefenceRequests(requests, now = new Date()) {
  const utc = now.toISOString().replace("T", " ").slice(0, 19);
  return requests.filter(q => q?.status === "active"
    && Number(q.required_def || 0) > Number(q.collected_def || 0)
    && String(q.attack_time || "") > utc);
}

export async function readDefenceState(path = "data/defence/requests.json") {
  const data = JSON.parse(await readFile(path, "utf8"));
  if (!Array.isArray(data)) throw new Error("Defence requests state must be an array");
  return data;
}

function threadName(q) {
  return (`${PREFIX}${q.id} — ${q.target_x}|${q.target_y}`).slice(0, 100);
}

function cardText(q) {
  const needed = Number(q.required_def || 0);
  const sent = Number(q.collected_def || 0);
  const missing = Math.max(0, needed - sent);
  const status = q.status === "active" && missing > 0
    ? ""
    : sent >= needed ? "\n\n✅ COVERED / 防衛完了"
    : q.status === "expired" ? "\n\n⌛ EXPIRED / 期限切れ"
    : "\n\n⛔ CLOSED / 終了";
  return [
    `🛡 **DEFENCE REQUEST #${q.id} / 防衛要請 #${q.id}**`,
    "",
    `🎯 **${q.target_x}|${q.target_y}**`,
    `⚔️ **Attack / 攻撃:** ${q.attack_time_display || q.attack_time}`,
    "",
    `🛡 **REQUEST / 必要:** ${needed.toLocaleString()}`,
    `✅ **SENT / 送信済み:** ${sent.toLocaleString()}`,
    `🔴 **STILL NEED / 不足:** ${missing.toLocaleString()}`,
  ].join("\n") + status;
}

async function findThread(channel, q) {
  const name = threadName(q);
  const active = await channel.guild.channels.fetchActiveThreads();
  const found = active.threads.find(t => t.parentId === channel.id && (t.name === name || t.name.includes(`#${q.id} `) || t.name.includes(`#${q.id} —`)));
  if (found) return found;
  const archived = await channel.threads.fetchArchived({ type: "public", limit: 100 });
  return archived.threads.find(t => t.name === name || t.name.includes(`#${q.id} `) || t.name.includes(`#${q.id} —`)) || null;
}

async function syncCard(thread, q, botId) {
  if (thread.archived) await thread.setArchived(false);
  const messages = await thread.messages.fetch({ limit: 50 });
  const marker = `🛡 **DEFENCE REQUEST #${q.id}`;
  const cards = [...messages.values()].filter(m => m.author.id === botId && m.content.startsWith(marker));
  const body = cardText(q);
  if (cards.length) {
    if (cards[0].content !== body) await cards[0].edit({ content: body, components: [], allowedMentions: { parse: [] } });
  } else {
    await thread.send({ content: body, allowedMentions: { parse: [] } });
  }
  for (const duplicate of cards.slice(1)) await duplicate.delete().catch(err => console.error("Duplicate card cleanup:", err));
}

export async function syncDefenceThreadsVps(client, requests, { publish = false } = {}) {
  // Explicit opt-in prevents two concurrent publishers during migration.
  if (!publish) throw new Error("Discord VPS publishing is disabled until cutover");
  const channel = await client.channels.fetch(CHANNEL_ID);
  if (!channel?.threads || !channel?.send) throw new Error("Defence channel is not a text channel");
  if (!Array.isArray(requests)) throw new Error("Invalid requests state");
  const active = activeDefenceRequests(requests);
  const activeIds = new Set(active.map(q => Number(q.id)));
  const failures = [];

  // Only create threads for currently actionable requests. Close older ones.
  for (const q of requests) {
    try {
      let thread = await findThread(channel, q);
      if (!thread && !activeIds.has(Number(q.id))) continue;
      if (!thread) {
        const starter = await channel.send({
          content: `🛡 **New defence request / 新しい防衛要請**\n🎯 **${q.target_x}|${q.target_y}**`,
          allowedMentions: { parse: [] },
        });
        thread = await starter.startThread({ name: threadName(q), autoArchiveDuration: 1440 });
      }
      await syncCard(thread, q, client.user.id);
      if (!activeIds.has(Number(q.id)) && !thread.archived) await thread.setArchived(true);
    } catch (error) {
      failures.push({ id: q.id, error: String(error) });
      console.error(`Discord VPS request #${q.id} sync failed:`, error);
    }
  }
  if (failures.length) throw new AggregateError(failures.map(f => new Error(`#${f.id}: ${f.error}`)), "Discord request sync incomplete");
  return { active: active.length, checked: requests.length };
}
