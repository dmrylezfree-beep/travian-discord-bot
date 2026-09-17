const THREAD_ID = 38636;

async function answerCallback(env, callbackId) {
  if (!callbackId) return;
  await fetch(`https://api.telegram.org/bot${env.TELEGRAM_BOT_TOKEN}/answerCallbackQuery`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ callback_query_id: callbackId })
  });
}

async function dispatch(env, inputs) {
  const url = `https://api.github.com/repos/${env.GITHUB_OWNER}/${env.GITHUB_REPO}/actions/workflows/${env.GITHUB_WORKFLOW}/dispatches`;
  const response = await fetch(url, {
    method: "POST",
    headers: {
      "Authorization": `Bearer ${env.GITHUB_TOKEN}`,
      "Accept": "application/vnd.github+json",
      "Content-Type": "application/json",
      "User-Agent": "travian-defence"
    },
    body: JSON.stringify({ ref: env.GITHUB_REF || "main", inputs })
  });
  if (!response.ok) {
    const text = await response.text();
    throw new Error(`GitHub API ${response.status}: ${text}`);
  }
}

function commonInputs(message) {
  return {
    chat_id: String(message.chat.id),
    message_id: String(message.message_id || ""),
    thread_id: String(message.message_thread_id || THREAD_ID),
    user_id: String(message.from?.id || ""),
    username: String(message.from?.username || ""),
    first_name: String(message.from?.first_name || "")
  };
}

export default {
  async fetch(request, env) {
    if (request.method !== "POST") return new Response("OK");

    let update;
    try {
      update = await request.json();
    } catch {
      return new Response("OK");
    }

    if (update.callback_query) {
      const callback = update.callback_query;
      const message = callback.message;
      if (!message || message.is_topic_message !== true || Number(message.message_thread_id) !== THREAD_ID) {
        return new Response("OK");
      }

      try {
        await answerCallback(env, callback.id);
        await dispatch(env, {
          action: "callback",
          ...commonInputs(message),
          callback_id: String(callback.id || ""),
          callback_data: String(callback.data || ""),
          message_text: ""
        });
      } catch (error) {
        console.error(error instanceof Error ? error.message : String(error));
      }
      return new Response("OK");
    }

    const message = update.message;
    if (!message || message.is_topic_message !== true || Number(message.message_thread_id) !== THREAD_ID) {
      return new Response("OK");
    }

    const text = String(message.text || "").trim();
    if (!text) return new Response("OK");

    try {
      await dispatch(env, {
        action: "message",
        ...commonInputs(message),
        message_text: text,
        callback_id: "",
        callback_data: ""
      });
    } catch (error) {
      console.error(error instanceof Error ? error.message : String(error));
    }

    return new Response("OK");
  }
};
