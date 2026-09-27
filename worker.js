const THREAD_ID = 75984;

function parseCoordinates(text) {
  const parts = String(text || "").trim().split(/\s+/);
  if (parts.length < 2 || parts.length % 2 !== 0) return null;
  if (!parts.every(value => /^-?\d+$/.test(value))) return null;
  return "coords:" + Array.from(
    { length: parts.length / 2 },
    (_, i) => `${parts[i * 2]},${parts[i * 2 + 1]}`
  ).join(";");
}

async function answerCallback(env, callbackId) {
  if (!callbackId) return;
  try {
    await fetch(
      `https://api.telegram.org/bot${env.TELEGRAM_BOT_TOKEN}/answerCallbackQuery`,
      {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ callback_query_id: callbackId })
      }
    );
  } catch (_) {}
}

async function runGitHubWorkflow(env, update) {
  const url =
    `https://api.github.com/repos/${env.GITHUB_OWNER}/` +
    `${env.GITHUB_REPO}/actions/workflows/` +
    `${env.GITHUB_WORKFLOW}/dispatches`;

  const response = await fetch(url, {
    method: "POST",
    headers: {
      "Authorization": `Bearer ${env.GITHUB_TOKEN}`,
      "Accept": "application/vnd.github+json",
      "Content-Type": "application/json",
      "User-Agent": "travian-feeders"
    },
    body: JSON.stringify({
      ref: env.GITHUB_REF || "main",
      inputs: {
        action: "message",
        update_json: JSON.stringify(update)
      }
    })
  });

  if (!response.ok) {
    const body = await response.text();
    console.error("GitHub dispatch failed:", response.status, body);
    throw new Error(`GitHub API ${response.status}`);
  }
}

export default {
  async fetch(request, env) {
    if (request.method !== "POST") return new Response("OK");

    let update;
    try {
      update = await request.json();
    } catch (_) {
      return new Response("OK");
    }

    const callback = update.callback_query;
    const message = update.message || callback?.message;

    if (!message) return new Response("OK");
    if (Number(message.message_thread_id) !== THREAD_ID) {
      return new Response("OK");
    }

    if (callback) {
      const data = String(callback.data || "");
      if (!data.startsWith("feeders|")) return new Response("OK");
      await answerCallback(env, callback.id);
    } else {
      if (!parseCoordinates(message.text)) return new Response("OK");
    }

    try {
      await runGitHubWorkflow(env, update);
    } catch (error) {
      console.error(
        "Feeders workflow start failed:",
        error instanceof Error ? error.message : String(error)
      );
    }

    return new Response("OK");
  }
};
