export default {
  async fetch(request, env) {

    // ============================================================
    // ПРОВЕРКА МЕТОДА
    // ============================================================

    if (request.method !== "POST") {
      return new Response("OK", { status: 200 });
    }

    // ============================================================
    // ПРОВЕРКА TELEGRAM WEBHOOK SECRET
    // ============================================================

    const secret = request.headers.get(
      "X-Telegram-Bot-Api-Secret-Token"
    );

    if (
      env.TELEGRAM_WEBHOOK_SECRET &&
      secret !== env.TELEGRAM_WEBHOOK_SECRET
    ) {
      return new Response("Unauthorized", { status: 401 });
    }

    // ============================================================
    // ЧИТАЕМ UPDATE
    // ============================================================

    let update;

    try {
      update = await request.json();
    } catch {
      return new Response("Bad Request", { status: 400 });
    }

    // ============================================================
    // CALLBACK "ПОКАЗАТЬ ЕЩЁ"
    // ============================================================

    if (update.callback_query) {

      const callback = update.callback_query;
      const data = callback.data || "";

      if (!data.startsWith("feeders|")) {
        return new Response("OK");
      }

      const parts = data.split("|");

      const page = parts[1] || "0";
      const originSpec = parts.slice(2).join("|");

      await telegramRequest(
        env,
        "answerCallbackQuery",
        {
          callback_query_id: callback.id
        }
      );

      const result = await dispatchWorkflow(env, {
        action: "feeders",
        chat_id: callback.message.chat.id,
        message_id: callback.message.message_id,
        thread_id:
          callback.message.message_thread_id || "75984",
        origin_spec: originSpec,
        page: page,
        callback_id: ""
      });

      if (!result.ok) {
        await telegramRequest(
          env,
          "sendMessage",
          {
            chat_id: callback.message.chat.id,
            message_thread_id:
              callback.message.message_thread_id,

            text:
              "❌ Ошибка запуска GitHub Actions:\n\n" +
              result.error
          }
        );
      }

      return new Response("OK");
    }

    // ============================================================
    // ОБЫЧНОЕ СООБЩЕНИЕ
    // ============================================================

    const message = update.message;

    if (!message) {
      return new Response("OK");
    }

    // ============================================================
    // ПРОВЕРКА ТЕМЫ
    // ============================================================

    if (
      String(message.message_thread_id || "") !== "75984"
    ) {
      return new Response("OK");
    }

    const text = (message.text || "").trim();

    if (!text.startsWith("/feeders")) {
      return new Response("OK");
    }

    // ============================================================
    // РАЗБИРАЕМ КОМАНДУ
    // ============================================================

    const args = text.split(/\s+/).slice(1);

    let originSpec = "";

    if (args.length === 0) {

      originSpec = "";

    } else if (args.length === 1) {

      originSpec = `player:${args[0]}`;

    } else if (args.length === 2) {

      originSpec = `coords:${args[0]},${args[1]}`;

    } else if (args.length % 2 === 0) {

      const coords = [];

      for (let i = 0; i < args.length; i += 2) {
        coords.push(
          `${args[i]},${args[i + 1]}`
        );
      }

      originSpec = `coords:${coords.join(";")}`;

    } else {

      await telegramRequest(
        env,
        "sendMessage",
        {
          chat_id: message.chat.id,
          message_thread_id:
            message.message_thread_id,

          text:
            "Неверный формат команды.\n\n" +
            "Примеры:\n" +
            "/feeders\n" +
            "/feeders 123456\n" +
            "/feeders 10 20\n" +
            "/feeders 10 20 30 40"
        }
      );

      return new Response("OK");
    }

    // ============================================================
    // ЗАПУСК GITHUB ACTIONS
    // ============================================================

    const result = await dispatchWorkflow(env, {

      action: "feeders",

      chat_id:
        message.chat.id,

      message_id:
        message.message_id,

      thread_id:
        message.message_thread_id,

      origin_spec:
        originSpec,

      page:
        "0",

      callback_id:
        ""
    });

    // ============================================================
    // ЕСЛИ GITHUB ОТВЕРГ ЗАПУСК
    // ============================================================

    if (!result.ok) {

      await telegramRequest(
        env,
        "sendMessage",
        {
          chat_id:
            message.chat.id,

          message_thread_id:
            message.message_thread_id,

          text:
            "❌ Не удалось запустить GitHub Actions.\n\n" +
            result.error
        }
      );

      return new Response("OK");
    }

    return new Response("OK");
  }
};


// ============================================================
// TELEGRAM API
// ============================================================

async function telegramRequest(env, method, body) {

  const url =
    `https://api.telegram.org/bot${env.TELEGRAM_BOT_TOKEN}/${method}`;

  const response = await fetch(url, {

    method: "POST",

    headers: {
      "Content-Type": "application/json"
    },

    body: JSON.stringify(body)
  });

  return response;
}


// ============================================================
// GITHUB ACTIONS
// ============================================================

async function dispatchWorkflow(env, inputs) {

  const url =
    `https://api.github.com/repos/` +
    `${env.GITHUB_OWNER}/` +
    `${env.GITHUB_REPO}/` +
    `actions/workflows/` +
    `${env.GITHUB_WORKFLOW}/dispatches`;

  try {

    const response = await fetch(url, {

      method: "POST",

      headers: {

        "Accept":
          "application/vnd.github+json",

        "Authorization":
          `Bearer ${env.GITHUB_TOKEN}`,

        "X-GitHub-Api-Version":
          "2022-11-28",

        "Content-Type":
          "application/json"
      },

      body: JSON.stringify({

        ref:
          env.GITHUB_REF || "main",

        inputs: {

          action:
            String(inputs.action),

          chat_id:
            String(inputs.chat_id),

          message_id:
            String(inputs.message_id || ""),

          thread_id:
            String(inputs.thread_id || "75984"),

          origin_spec:
            String(inputs.origin_spec || ""),

          page:
            String(inputs.page || "0"),

          callback_id:
            String(inputs.callback_id || "")
        }
      })
    });

    if (response.ok) {
      return {
        ok: true
      };
    }

    const errorText =
      await response.text();

    console.error(
      "GitHub workflow dispatch failed:",
      response.status,
      errorText
    );

    return {
      ok: false,
      error:
        `HTTP ${response.status}\n${errorText}`
    };

  } catch (error) {

    console.error(
      "GitHub request exception:",
      error
    );

    return {
      ok: false,
      error:
        String(error)
    };
  }
}
