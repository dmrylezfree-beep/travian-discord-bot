
export default {
  async fetch(request, env) {

    // ------------------------------------------------------------
    // Принимаем только POST от Telegram
    // ------------------------------------------------------------

    if (request.method !== "POST") {
      return new Response("OK", { status: 200 });
    }

    // ------------------------------------------------------------
    // Проверка секретного токена Telegram webhook
    // ------------------------------------------------------------

    const secret = request.headers.get(
      "X-Telegram-Bot-Api-Secret-Token"
    );

    if (
      env.TELEGRAM_WEBHOOK_SECRET &&
      secret !== env.TELEGRAM_WEBHOOK_SECRET
    ) {
      return new Response("Unauthorized", { status: 401 });
    }

    // ------------------------------------------------------------
    // Читаем Telegram update
    // ------------------------------------------------------------

    let update;

    try {
      update = await request.json();
    } catch {
      return new Response("Bad Request", { status: 400 });
    }

    // ============================================================
    // CALLBACK — кнопка "Показать ещё" / "Назад"
    // ============================================================

    if (update.callback_query) {

      const callback = update.callback_query;
      const data = callback.data || "";

      // Нас интересуют только callback нашего бота
      if (!data.startsWith("feeders|")) {
        return new Response("OK");
      }

      const parts = data.split("|");

      const page = parts[1] || "0";

      // Всё после номера страницы — исходные координаты
      const originSpec = parts.slice(2).join("|");

      // Убираем "часики" с кнопки Telegram
      await telegramRequest(
        env,
        "answerCallbackQuery",
        {
          callback_query_id: callback.id
        }
      );

      const result = await dispatchWorkflow(env, {
        action: "callback",

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
    // Обычное сообщение
    // ============================================================

    const message = update.message;

    if (!message) {
      return new Response("OK");
    }

    // DEBUG: показываем, что именно Telegram прислал Worker
    await telegramRequest(
      env,
      "sendMessage",
      {
        chat_id: message.chat.id,
        text:
          "🔧 DEBUG\n" +
          "chat_id: " + String(message.chat.id) + "\n" +
          "thread_id: " + String(message.message_thread_id || "нет") + "\n" +
          "text: " + String(message.text || "")
      }
    );

    if (!message.message_thread_id) {
      return new Response("OK");
    }

    // ------------------------------------------------------------
    // Работаем только в теме 75984
    // ------------------------------------------------------------

    if (
      String(message.message_thread_id || "") !== "75984"
    ) {
      return new Response("OK");
    }

    const text = (message.text || "").trim();

    if (!text) {
      return new Response("OK");
    }

    // ============================================================
    // Определяем координаты
    // ============================================================

    let originSpec = "";

    // ------------------------------------------------------------
    // Вариант 1:
    //
    // /feeders 10 20
    //
    // ------------------------------------------------------------

    if (text.startsWith("/feeders")) {

      const args = text.split(/\s+/).slice(1);

      if (args.length === 0) {

        await telegramRequest(
          env,
          "sendMessage",
          {
            chat_id: message.chat.id,

            message_thread_id:
              message.message_thread_id,

            text:
              "🌾 Введите координаты деревни.\n\n" +
              "Например:\n" +
              "<code>10 20</code>\n\n" +
              "Или несколько деревень:\n" +
              "<code>10 20 30 40</code>"
          }
        );

        return new Response("OK");
      }

      if (args.length % 2 !== 0) {

        await telegramRequest(
          env,
          "sendMessage",
          {
            chat_id: message.chat.id,

            message_thread_id:
              message.message_thread_id,

            text:
              "❌ Неверный формат координат.\n\n" +
              "Используйте:\n" +
              "<code>10 20</code>\n" +
              "или\n" +
              "<code>10 20 30 40</code>"
          }
        );

        return new Response("OK");
      }

      const coords = [];

      for (let i = 0; i < args.length; i += 2) {

        const x = args[i];
        const y = args[i + 1];

        if (
          !/^-?\d+$/.test(x) ||
          !/^-?\d+$/.test(y)
        ) {

          await telegramRequest(
            env,
            "sendMessage",
            {
              chat_id: message.chat.id,

              message_thread_id:
                message.message_thread_id,

              text:
                "❌ Координаты должны быть числами.\n\n" +
                "Например:\n" +
                "<code>10 20</code>"
            }
          );

          return new Response("OK");
        }

        coords.push(
          x + "," + y
        );
      }

      originSpec =
        "coords:" + coords.join(";");

    }

    // ============================================================
    // Вариант 2:
    //
    // Просто:
    //
    // 10 20
    //
    // ============================================================

    else {

      const args = text.split(/\s+/);

      // Только чётное количество чисел.
      // 2 = одна деревня
      // 4 = две деревни
      // 6 = три деревни и т.д.
      if (
        args.length >= 2 &&
        args.length % 2 === 0
      ) {

        let valid = true;

        for (const value of args) {

          if (!/^-?\d+$/.test(value)) {
            valid = false;
            break;
          }
        }

        if (valid) {

          const coords = [];

          for (
            let i = 0;
            i < args.length;
            i += 2
          ) {

            coords.push(
              args[i] + "," + args[i + 1]
            );
          }

          originSpec =
            "coords:" + coords.join(";");

        } else {

          // Обычный текст — игнорируем
          return new Response("OK");
        }

      } else {

        // Обычный текст или неправильное количество аргументов
        return new Response("OK");
      }
    }

    // ============================================================
    // Запускаем GitHub Actions
    // ============================================================

    const result = await dispatchWorkflow(env, {

      action: "command",

      chat_id: message.chat.id,

      message_id: message.message_id,

      thread_id:
        message.message_thread_id,

      origin_spec: originSpec,

      page: "0",

      callback_id: ""
    });

    // ------------------------------------------------------------
    // Если GitHub Actions не удалось запустить
    // ------------------------------------------------------------

    if (!result.ok) {

      await telegramRequest(
        env,
        "sendMessage",
        {
          chat_id: message.chat.id,

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


// ==================================================================
// TELEGRAM API
// ==================================================================

async function telegramRequest(env, method, body) {

  const url =
    "https://api.telegram.org/bot" +
    env.TELEGRAM_BOT_TOKEN +
    "/" +
    method;

  const response = await fetch(url, {

    method: "POST",

    headers: {
      "Content-Type": "application/json"
    },

    body: JSON.stringify(body)
  });

  return response;
}


// ==================================================================
// GITHUB ACTIONS
// ==================================================================

async function dispatchWorkflow(env, inputs) {

  const url =
    "https://api.github.com/repos/" +
    env.GITHUB_OWNER +
    "/" +
    env.GITHUB_REPO +
    "/actions/workflows/" +
    env.GITHUB_WORKFLOW +
    "/dispatches";

  try {

    const response = await fetch(url, {

      method: "POST",

      headers: {

        "Accept":
          "application/vnd.github+json",

        "Authorization":
          "Bearer " + env.GITHUB_TOKEN,

        "X-GitHub-Api-Version":
          "2022-11-28",

        "Content-Type":
          "application/json",

        "User-Agent":
          "travian-feeders"
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
            String(
              inputs.thread_id || "75984"
            ),

          origin_spec:
            String(
              inputs.origin_spec || ""
            ),

          page:
            String(inputs.page || "0"),

          callback_id:
            String(
              inputs.callback_id || ""
            )
        }
      })
    });

    // GitHub отвечает 204 No Content при успешном dispatch
    if (response.ok) {
      return { ok: true };
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
        "HTTP " +
        response.status +
        "\n" +
        errorText
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

