const THREAD_ID = 38636;
const WEBHOOK_URL = "https://travian-defence.dmrylezfree.workers.dev/";

async function answerCallback(env, callbackId) {
  if (!callbackId) return;
  await fetch(`https://api.telegram.org/bot${env.TELEGRAM_BOT_TOKEN}/answerCallbackQuery`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ callback_query_id: callbackId })
  });
}

async function sendStartMenu(env, message) {
  const url = `https://api.telegram.org/bot${env.TELEGRAM_BOT_TOKEN}/sendMessage`;
  const body = {
    chat_id: message.chat.id,
    message_thread_id: THREAD_ID,
    text: "<b>🛡 ЦЕНТР ДЕФА</b>\n\nЗдесь настраивается ваш теоретический резерв дефа.",
    parse_mode: "HTML",
    reply_markup: {
      inline_keyboard: [
        [{ text: "➕ Запросить деф", callback_data: "request_def" }],
        [{ text: "🛡 Отправить деф", callback_data: "send_def" }],
        [{ text: "⚙️ Мои настройки", callback_data: "settings" }]
      ]
    }
  };
  const response = await fetch(url, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body)
  });
  if (!response.ok) {
    throw new Error(`Telegram sendMessage ${response.status}: ${await response.text()}`);
  }
}

async function dispatch(env) {
  const url = `https://api.github.com/repos/${env.GITHUB_OWNER}/${env.GITHUB_REPO}/actions/workflows/${env.GITHUB_WORKFLOW}/dispatches`;
  const response = await fetch(url, {
    method: "POST",
    headers: {
      "Authorization": `Bearer ${env.GITHUB_TOKEN}`,
      "Accept": "application/vnd.github+json",
      "Content-Type": "application/json",
      "User-Agent": "travian-defence"
    },
    body: JSON.stringify({ ref: env.GITHUB_REF || "main", inputs: { action: "start" } })
  });
  if (!response.ok) {
    throw new Error(`GitHub API ${response.status}: ${await response.text()}`);
  }
}

function isDefCommand(message) {
  if (!message || message.is_topic_message !== true) return false;
  if (Number(message.message_thread_id) !== THREAD_ID) return false;
  const text = String(message.text || "").trim();
  return /^\/def(?:@[^\s]+)?(?:\s|$)/i.test(text);
}

export default {
  async fetch(request, env) {
    if (request.method !== "POST") {
      return new Response("OK");
    }

    let update;
    try {
      update = await request.json();
    } catch {
      return new Response("OK");
    }

    const message = update.message;

    // The webhook is only a launcher. Once /def starts Actions,
    // the workflow removes this webhook and switches the bot to getUpdates.
    if (message && isDefCommand(message)) {
      try {
        await sendStartMenu(env, message);
        await dispatch(env);
      } catch (error) {
        console.error(error instanceof Error ? error.message : String(error));
      }
    }

    // Ignore everything else while the webhook is active.
    // Normal messages and callbacks are processed by defence_poll.py
    // after the workflow switches Telegram to polling.
    return new Response("OK");
  }
};
