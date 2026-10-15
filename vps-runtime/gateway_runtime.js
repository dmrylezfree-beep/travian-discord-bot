import './runtime_network.js';
// Candidate runtime. No registration, endpoint changes, or local reminder consumer.
import {Client, Events, GatewayIntentBits, Routes} from 'discord.js';
import {handleDiscordInteraction} from './defence-worker.js';
import {makeGatewayBridge} from './discord_gateway_bridge.js';
import {makeCloudflareQueue} from './local_queue_binding.js';

const EXPECTED_APP = '1555623257724682402';
const env = {DISCORD_BOT_TOKEN: process.env.DISCORD_BOT_TOKEN,
  TELEGRAM_BOT_TOKEN: process.env.DEFENCE_TELEGRAM_TOKEN};
if (process.env.DISCORD_GATEWAY_ENABLE !== 'approved') throw Error('Gateway requires explicit activation');
for (const [name, value] of Object.entries(env)) if (!value) throw Error(`Missing ${name}`);
env.DEFENCE_REMINDERS = makeCloudflareQueue(env);
const client = new Client({intents: [GatewayIntentBits.Guilds]});
const tasks = new Set();
let accepting = false;
let endpointTimer;
let stopping = false;
const standbyOnly = process.env.DISCORD_GATEWAY_MODE === 'standby';
const readyDeadline = setTimeout(() => {
  console.error(); process.exitCode = 1; shutdown();
}, 45000);

// Report error categories only, never SDK request bodies or interaction URLs.
console.error = () => process.stderr.write('Discord operation failed; sensitive details suppressed.\n');
const receive = makeGatewayBridge({handleInteraction: handleDiscordInteraction, env,
  callback: (id, token, body) => client.rest.post(Routes.interactionCallback(id, token), {body, auth: false})});

async function endpointClear() {
  const response = await fetch('https://discord.com/api/v10/oauth2/applications/@me', {
    headers: {Authorization: `Bot ${env.DISCORD_BOT_TOKEN}`}, signal: AbortSignal.timeout(10000),
  });
  if (!response.ok) throw Error('Application check failed');
  const application = await response.json();
  if (application.id !== EXPECTED_APP) throw Error('Wrong application');
  return !application.interactions_endpoint_url;
}

async function shutdown() {
  if (stopping) return;
  stopping = true;
  accepting = false;
  clearTimeout(readyDeadline);
  clearInterval(endpointTimer);
  await client.destroy();
  await Promise.race([Promise.allSettled([...tasks]), new Promise(resolve => {
    const timer = setTimeout(resolve, 20000); timer.unref();
  })]);
}

client.on(Events.Raw, packet => {
  if (!accepting || packet.t !== 'INTERACTION_CREATE') return;
  const task = receive(packet.d).catch(() => console.error());
  tasks.add(task);
  task.finally(() => tasks.delete(task));
});
client.on(Events.Error, () => console.error());
client.on(Events.ShardError, () => console.error());
client.once(Events.ClientReady, async () => {
  try {
    if (client.user.id !== EXPECTED_APP || !client.guilds.cache.has('1430982178074005507')) throw Error('Unexpected identity');
    accepting = (await endpointClear()) && !standbyOnly;
    clearTimeout(readyDeadline);
    console.log(accepting ? 'Gateway ready; accepting interactions.' : 'Gateway standby; Cloudflare endpoint remains configured.');
    endpointTimer = setInterval(async () => {
      try {
        const next = (await endpointClear()) && !standbyOnly && !stopping;
        if (next !== accepting) console.log(next ? 'Gateway accepting interactions.' : 'Gateway paused; endpoint is configured.');
        accepting = next;
      }
      catch { accepting = false; console.error(); }
    }, 10000);
  } catch { process.exitCode = 1; await shutdown(); }
});
for (const signal of ['SIGTERM', 'SIGINT']) process.on(signal, shutdown);
try {
  await endpointClear(); // Validate identity before opening Gateway.
  await client.login(env.DISCORD_BOT_TOKEN);
} catch { console.error(); process.exitCode = 1; await shutdown(); }
