const THREAD_ID = 38636;
const GITHUB_OWNER = "dmrylezfree-beep";
const GITHUB_REPO = "travian-discord-bot";
const GITHUB_WORKFLOW = "defence_bot.yml";
const GITHUB_REF = "main";

const MAX_QUEUE_DELAY_SECONDS = 86400;

function londonNowText() {
  const parts = new Intl.DateTimeFormat("en-CA", {
    timeZone: "Europe/London", year: "numeric", month: "2-digit", day: "2-digit",
    hour: "2-digit", minute: "2-digit", second: "2-digit", hourCycle: "h23"
  }).formatToParts(new Date());
  const p = Object.fromEntries(parts.map(x => [x.type, x.value]));
  return `${p.year}-${p.month}-${p.day} ${p.hour}:${p.minute}:${p.second}`;
}

function secondsUntilLondon(localText) {
  // Convert a Europe/London wall-clock timestamp to a delay without assuming
  // that the Worker itself runs in the server timezone.
  const now = new Date();
  const nowParts = londonNowText();
  const target = String(localText || "");
  const parse = s => {
    const m = s.match(/^(\d{4})-(\d{2})-(\d{2}) (\d{2}):(\d{2}):(\d{2})$/);
    return m ? Date.UTC(+m[1], +m[2]-1, +m[3], +m[4], +m[5], +m[6]) : NaN;
  };
  return Math.floor((parse(target) - parse(nowParts)) / 1000);
}

async function queueReminder(env, payload) {
  const delay = secondsUntilLondon(payload.reminder_at);
  if (!Number.isFinite(delay)) throw new Error("Invalid reminder_at");
  if (delay <= 0) {
    await env.DEFENCE_REMINDERS.send(payload, { delaySeconds: 0 });
  } else {
    await env.DEFENCE_REMINDERS.send(payload, {
      delaySeconds: Math.min(delay, MAX_QUEUE_DELAY_SECONDS)
    });
  }
}

async function sendPrivateReminder(env, item) {
  const mode = item.speed_mode === "hero" ? "🦸 С героем"
    : item.speed_mode === "ram" ? "🐏 + 1 таран"
    : item.speed_mode === "catapult" ? "🪨 + 1 катапульта"
    : "⚡ Без героя";
  const warning = item.speed_mode === "ram"
    ? "\n\n❗ Не забудь добавить <b>1 таран</b>."
    : item.speed_mode === "catapult"
      ? "\n\n❗ Не забудь добавить <b>1 катапульту</b>." : "";
  const text =
    "<b>🚨 ПОРА ОТПРАВЛЯТЬ ДЕФ</b>\n\n" +
    `🏘 <b>${item.village || "?"}</b> → 🎯 <b>${item.target_x} ${item.target_y}</b>\n` +
    `🛡 <b>${item.def_points || 0}</b> очков\n` +
    `${mode}\n\n` +
    `🚨 Отправить до: <b>${item.deadline || "?"}</b>\n` +
    `⚔️ Атака: <b>${item.attack_time_display || item.attack_time || "?"}</b>\n\n` +
    "⏱ До отправки около 5 минут." +
    warning;

  const response = await fetch(
    `https://api.telegram.org/bot${env.TELEGRAM_BOT_TOKEN}/sendMessage`,
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ chat_id: item.private_chat_id, text, parse_mode: "HTML" })
    }
  );
  if (!response.ok) throw new Error(`Telegram reminder ${response.status}: ${await response.text()}`);
}


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

async function answerCallback(env, callbackQueryId) {
  const response = await fetch(
    `https://api.telegram.org/bot${env.TELEGRAM_BOT_TOKEN}/answerCallbackQuery`,
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ callback_query_id: callbackQueryId })
    }
  );

  if (!response.ok) {
    console.error(`Telegram answerCallbackQuery ${response.status}: ${await response.text()}`);
  }
}

async function loadActiveRequests(env) {
  const url = `https://api.github.com/repos/${GITHUB_OWNER}/${GITHUB_REPO}/contents/data/defence/requests.json?ref=${GITHUB_REF}`;
  const response = await fetch(url, {
    headers: {
      "Authorization": `Bearer ${env.GITHUB_TOKEN}`,
      "Accept": "application/vnd.github+json",
      "User-Agent": "travian-defence"
    }
  });
  if (!response.ok) {
    throw new Error(`GitHub requests.json ${response.status}: ${await response.text()}`);
  }

  const payload = await response.json();
  const raw = atob(String(payload.content || "").replace(/\s/g, ""));
  const requests = JSON.parse(raw);
  if (!Array.isArray(requests)) return [];

  const parts = new Intl.DateTimeFormat("en-CA", {
    timeZone: "Europe/London",
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
    hourCycle: "h23"
  }).formatToParts(new Date());
  const now = Object.fromEntries(parts.map(p => [p.type, p.value]));
  const nowText = `${now.year}-${now.month}-${now.day} ${now.hour}:${now.minute}:${now.second}`;

  return requests.filter(req =>
    req && req.status === "active" &&
    Number(req.required_def || 0) > Number(req.collected_def || 0) &&
    String(req.attack_time || "") > nowText
  );
}

async function sendStartMenu(env, message) {
  const url = `https://api.telegram.org/bot${env.TELEGRAM_BOT_TOKEN}/sendMessage`;

  let requests = [];
  try {
    requests = await loadActiveRequests(env);
  } catch (error) {
    console.error("Failed to load active defence requests:", error);
  }

  const lines = ["<b>🛡 ЦЕНТР ДЕФА</b>", ""];
  if (requests.length) {
    lines.push("<b>Активные заявки:</b>", "");
    for (const req of requests) {
      const collected = Number(req.collected_def || 0);
      const required = Number(req.required_def || 0);
      lines.push(
        `🟢 <b>#${req.id}</b> — ${req.target_x}|${req.target_y}`,
        `⚔️ Атака: <b>${req.attack_time_display || req.attack_time}</b>`,
        `🛡 Деф: <b>${collected}</b> / <b>${required}</b> очков`,
        ""
      );
    }
  } else {
    lines.push("Активных заявок сейчас нет.", "");
  }

  lines.push(
    "Деф должен прибыть <b>ДО</b> времени атаки.",
    "",
    "Выберите действие:"
  );

  const body = {
    chat_id: message.chat.id,
    message_thread_id: THREAD_ID,
    text: lines.join("\n"),
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

async function dispatch(env, update = null, workflow = GITHUB_WORKFLOW) {
  if (!env.GITHUB_TOKEN) {
    throw new Error("Cloudflare: не задан GITHUB_TOKEN");
  }
  if (!env.TELEGRAM_BOT_TOKEN) {
    throw new Error("Cloudflare: не задан TELEGRAM_BOT_TOKEN");
  }

  const url =
    `https://api.github.com/repos/${GITHUB_OWNER}/${GITHUB_REPO}/actions/workflows/${workflow}/dispatches`;

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
      inputs: {
        action: update?.callback_query ? "callback" : "message",
        thread_id: String(THREAD_ID),
        update_json: update ? JSON.stringify(update) : ""
      }
    })
  });

  if (!response.ok) {
    const details = await response.text();
    throw new Error(`GitHub API ${response.status}: ${details.slice(0, 1500)}`);
  }
}

function getUpdateThreadId(update) {
  const message = update?.message || update?.edited_message;
  if (message) return Number(message.message_thread_id);
  const callback = update?.callback_query;
  if (callback?.message) return Number(callback.message.message_thread_id);
  return null;
}

function isDefCommand(message) {
  if (!message) return false;
  if (Number(message.message_thread_id) !== THREAD_ID) return false;

  const text = String(message.text || "").trim();
  return /^\/def(?:@[^\s]+)?(?:\s|$)/i.test(text);
}

export default {
  async fetch(request, env) {
    const url = new URL(request.url);

    if (request.method === "POST" && url.pathname === "/schedule-reminders") {
      const auth = request.headers.get("Authorization") || "";
      if (auth !== `Bearer ${env.TELEGRAM_BOT_TOKEN}`) {
        return new Response("Unauthorized", { status: 401 });
      }
      try {
        const body = await request.json();
        const reminders = Array.isArray(body?.reminders) ? body.reminders : [];
        for (const reminder of reminders) await queueReminder(env, reminder);
        return Response.json({ ok: true, scheduled: reminders.length });
      } catch (error) {
        return Response.json({ ok: false, error: String(error) }, { status: 400 });
      }
    }

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
    const callback = update.callback_query;

    if (
      message &&
      message.chat?.type === "private" &&
      /^\/start(?:@[^\s]+)?(?:\s|$)/i.test(String(message.text || "").trim())
    ) {
      try {
        // Private registration uses a separate short workflow so it never
        // cancels an active 510-second Defence Bot session.
        await dispatch(env, update, "defence_register.yml");
      } catch (error) {
        console.error(error instanceof Error ? error.message : String(error));
      }
      return new Response("OK");
    }

    if (getUpdateThreadId(update) !== THREAD_ID) {
      return new Response("OK");
    }

    // /def only starts the workflow. The Python bot owns the single
    // authoritative Defence Centre message, including status colours,
    // buttons and pinning. Do not create a temporary duplicate menu here.
    if (message && isDefCommand(message)) {
      try {
        await dispatch(env, update);
      } catch (error) {
        const details = error instanceof Error ? error.message : String(error);
        console.error(details);

        try {
          await sendTelegram(
            env,
            message.chat.id,
            `❌ <b>Не удалось запустить Defence Bot</b>\n\n<code>${details.slice(0, 2000)}</code>`
          );
        } catch (telegramError) {
          console.error(
            telegramError instanceof Error ? telegramError.message : String(telegramError)
          );
        }
      }
      return new Response("OK");
    }

    // When the 510-second polling window has ended, Telegram is back on this
    // webhook. Old inline keyboards must still work. Forward the exact update
    // into a new workflow run; otherwise the update would be consumed by the
    // webhook and never reach getUpdates.
    if (callback || message) {
      if (callback?.id) {
        await answerCallback(env, callback.id);
      }

      try {
        await dispatch(env, update);
      } catch (error) {
        console.error(error instanceof Error ? error.message : String(error));
      }
    }

    return new Response("OK");
  },

  async queue(batch, env) {
    for (const message of batch.messages) {
      try {
        const item = message.body || {};
        const remaining = secondsUntilLondon(item.reminder_at);
        if (Number.isFinite(remaining) && remaining > 2) {
          message.retry({ delaySeconds: Math.min(remaining, MAX_QUEUE_DELAY_SECONDS) });
          continue;
        }
        await sendPrivateReminder(env, item);
        message.ack();
      } catch (error) {
        console.error("Defence reminder failed:", error instanceof Error ? error.message : String(error));
        message.retry({ delaySeconds: 60 });
      }
    }
  }
};
