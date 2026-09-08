
const THREAD_ID = "75984";

function parseCoordinates(text) {
  const parts = text.trim().split(/\s+/);

  // Только целые числа
  if (parts.length < 2 || parts.length % 2 !== 0) {
    return null;
  }

  if (!parts.every(x => /^-?\d+$/.test(x))) {
    return null;
  }

  const coordinates = [];

  for (let i = 0; i < parts.length; i += 2) {
    coordinates.push(`${parts[i]},${parts[i + 1]}`);
  }

  return `coords:${coordinates.join(";")}`;
}


async function runGitHubWorkflow(env, inputs) {
  const url =
    `https://api.github.com/repos/${env.GITHUB_OWNER}/${env.GITHUB_REPO}` +
    `/actions/workflows/${env.GITHUB_WORKFLOW}/dispatches`;

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
      inputs
    })
  });

  if (!response.ok) {
    const error = await response.text();
    throw new Error(`GitHub API ${response.status}: ${error}`);
  }
}


async function sendTelegram(env, chatId, text, threadId) {
  await fetch(
    `https://api.telegram.org/bot${env.TELEGRAM_BOT_TOKEN}/sendMessage`,
    {
      method: "POST",

      headers: {
        "Content-Type": "application/json"
      },

      body: JSON.stringify({
        chat_id: chatId,
        message_thread_id: threadId,
        text
      })
    }
  );
}


export default {
  async fetch(request, env) {
    if (request.method !== "POST") {
      return new Response("OK");
    }

    try {
      const update = await request.json();

      /*
       * =====================================================
       * КНОПКА «ПОКАЗАТЬ ЕЩЁ»
       * =====================================================
       */

      if (update.callback_query) {
        const callback = update.callback_query;
        const message = callback.message;

        if (
          !message ||
          String(message.message_thread_id || "") !== THREAD_ID
        ) {
          return new Response("OK");
        }

        const data = String(callback.data || "");

        if (!data.startsWith("feeders|")) {
          return new Response("OK");
        }

        const parts = data.split("|");

        const page = parts[1];
        const originSpec = parts.slice(2).join("|");

        await runGitHubWorkflow(env, {
          action: "callback",
          chat_id: String(message.chat.id),
          message_id: String(message.message_id),
          thread_id: THREAD_ID,
          origin_spec: originSpec,
          page: page,
          callback_id: String(callback.id)
        });

        return new Response("OK");
      }


      /*
       * =====================================================
       * ОБЫЧНОЕ СООБЩЕНИЕ
       * =====================================================
       */

      const message = update.message;

      if (!message) {
        return new Response("OK");
      }

      // Работаем только в теме 75984
      if (
        String(message.message_thread_id || "") !== THREAD_ID
      ) {
        return new Response("OK");
      }

      const text = String(message.text || "").trim();

      if (!text) {
        return new Response("OK");
      }

      /*
       * Теперь нам вообще не важно, написано ли /feeders.
       *
       * Единственное условие:
       * сообщение должно состоять из пар координат.
       *
       * Например:
       *
       * 10 20
       * 10 20 30 40
       * -150 80 100 -50
       */

      const originSpec = parseCoordinates(text);

      // Обычный текст просто игнорируем
      if (!originSpec) {
        return new Response("OK");
      }

      await runGitHubWorkflow(env, {
        action: "command",
        chat_id: String(message.chat.id),
        message_id: String(message.message_id),
        thread_id: THREAD_ID,
        origin_spec: originSpec,
        page: "0",
        callback_id: ""
      });

      return new Response("OK");

    } catch (error) {
      console.error("Worker error:", error);

      return new Response("OK");
    }
  }
};
