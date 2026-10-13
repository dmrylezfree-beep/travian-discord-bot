// Staging-only Discord Gateway transport. Do not run concurrently with the
// Cloudflare interaction endpoint until the Discord application is switched.
// Requires: npm install (discord.js v14).
import { Client, GatewayIntentBits, Events, MessageFlags } from "discord.js";
import { readFile } from "node:fs/promises";

const GUILD_ID = "1430982178074005507";
const CHANNEL_ID = "1430982180401578153";
const STATE_PATH = process.env.DISCORD_DEFENCE_STATE_PATH || "data/defence/requests.json";
const token = process.env.DISCORD_BOT_TOKEN;
if (!token) throw new Error("DISCORD_BOT_TOKEN is missing");

const client = new Client({ intents: [GatewayIntentBits.Guilds] });

async function activeRequests() {
  const requests = JSON.parse(await readFile(STATE_PATH, "utf8"));
  const now = new Date().toISOString().replace("T", " ").slice(0, 19);
  return requests.filter(q =>
    q.status === "active" &&
    Number(q.required_def || 0) > Number(q.collected_def || 0) &&
    String(q.attack_time || "") > now
  );
}

client.once(Events.ClientReady, bot => {
  console.log(`Discord VPS gateway connected: ${bot.user.id}`);
});

client.on(Events.InteractionCreate, async interaction => {
  try {
    if (!interaction.isChatInputCommand() || interaction.commandName !== "def") return;
    if (interaction.guildId !== GUILD_ID || interaction.channelId !== CHANNEL_ID) {
      await interaction.reply({ content: "Use the designated WORLD defence channel.", flags: MessageFlags.Ephemeral });
      return;
    }
    await interaction.deferReply({ flags: MessageFlags.Ephemeral });
    const requests = await activeRequests();
    const text = requests.length
      ? requests.map(q => `🟢 #${q.id} — ${q.target_x}|${q.target_y} — 🛡 ${q.collected_def || 0}/${q.required_def} — ⚔️ ${q.attack_time_display || q.attack_time}`).join("\n")
      : "No active defence requests / 現在、防衛要請はありません。";
    await interaction.editReply("🛡 **WORLD Defence**\n\n" + text);
  } catch (error) {
    console.error("Discord interaction error:", error);
    if (interaction.deferred || interaction.replied) {
      await interaction.editReply("❌ Temporary defence service error.").catch(console.error);
    } else {
      await interaction.reply({ content: "❌ Temporary defence service error.", flags: MessageFlags.Ephemeral }).catch(console.error);
    }
  }
});

process.on("SIGTERM", () => client.destroy());
process.on("SIGINT", () => client.destroy());
await client.login(token);
