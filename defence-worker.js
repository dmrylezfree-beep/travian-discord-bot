const THREAD_ID = 38636;
const GITHUB_OWNER = "dmrylezfree-beep";
const GITHUB_REPO = "travian-discord-bot";
const GITHUB_WORKFLOW = "defence_bot.yml";
const GITHUB_REF = "main";

async function sendTelegram(env, chatId, text) {
  const response = await fetch(
    `https://api.telegram.org/bot${env.TELEGRAM_BOT_TOKEN}/sendMessage`,
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        chat_id: chatId,
        message_thread_id: THREAD_ID,
        text,
        parse_mode: "HTML"
      })
    }
  );

  if (!response.ok) {
    throw new Error(`Telegram sendMessage ${response.status}: ${await response.text()}`);
  }
}

async function sendStartMenu(env, message) {
  const url = `https://api.telegram.org/bot${env.TELEGRAM_BOT_TOKEN}/sendMessage`;
  const body = {
    chat_id: message.chat.id,
    message_thread_id: THREAD_ID,
    text: "<b>🛡 ЦЕНТР ДЕФА</b>\\n\\nЗдесь настраивается ваш теоретический резерв дефа.",
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
  if (!env.GITHUB_TOKEN) {
    throw new Error("Cloudflare: не задан GITHUB_TOKEN");
  }
  if (!env.TELEGRAM_BOT_TOKEN) {
    throw new Error("Cloudflare: не задан TELEGRAM_BOT_TOKEN");
  }

  const url =
    `https://api.github.com/repos/${GITHUB_OWNER}/${GITHUB_REPO}/actions/workflows/${GITHUB_WORKFLOW}/dispatches`;

  const response = await fetch(url, {
    method: "POST",
    headers: {
      "Authorization": `Bearer ${env.GITHUB_TOKEN}`,
      "Accept": "application/vnd.github+json",
      "Content-Type": "application/json",
      "User-Agent": "travian-defence"
    },
    body: JSON.stringify({
      ref: GITHUB_REF,
      inputs: { action: "start" }
    })
  });

  if (!response.ok) {
    const details = await response.text();
    throw new Error(`GitHub API ${response.status}: ${details.slice(0, 1500)}`);
  }
}

function isDefCommand(message) {
  if (!message || message.is_topic_message !== true) return false;
  if (Number(message.message_thread_id) !== THREAD_ID) return false;

  const text = String(message.text || "").trim();
  return /^\\/def(?:@[^\\s]+)?(?:\\s|$)/i.test(text);
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

    if (message && isDefCommand(message)) {
      try {
        await dispatch(env);
        await sendStartMenu(env, message);
      } catch (error) {
        const details = error instanceof Error ? error.message : String(error);
        console.error(details);

        try {
          await sendTelegram(
            env,
            message.chat.id,
            `❌ <b>Не удалось запустить Defence Bot</b>\\n\\n<code>${details.slice(0, 2000)}</code>`
          );
        } catch (telegramError) {
          console.error(
            telegramError instanceof Error ? telegramError.message : String(telegramError)
          );
        }
      }
    }

    return new Response("OK");
  }
};
