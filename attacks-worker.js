const THREAD_ID = 76303;
const GITHUB_OWNER = "dmrylezfree-beep";
const GITHUB_REPO = "travian-discord-bot";
const GITHUB_WORKFLOW = "attacks_bot.yml";
const GITHUB_REF = "main";

async function answerCallback(env, callbackId) {
  if (!callbackId) return;
  try {
    await fetch(`https://api.telegram.org/bot${env.TELEGRAM_BOT_TOKEN}/answerCallbackQuery`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ callback_query_id: callbackId })
    });
  } catch (error) {
    console.error("answerCallback failed:", error);
  }
}

function updateChat(update) {
  return update?.message?.chat || update?.callback_query?.message?.chat || null;
}

function updateThreadId(update) {
  return update?.message?.message_thread_id ??
    update?.callback_query?.message?.message_thread_id ?? null;
}

async function dispatch(env, update) {
  if (!env.GITHUB_TOKEN) throw new Error("Cloudflare: не задан GITHUB_TOKEN");
  if (!env.TELEGRAM_BOT_TOKEN) throw new Error("Cloudflare: не задан TELEGRAM_BOT_TOKEN");

  const response = await fetch(
    `https://api.github.com/repos/${GITHUB_OWNER}/${GITHUB_REPO}/actions/workflows/${GITHUB_WORKFLOW}/dispatches`,
    {
      method: "POST",
      headers: {
        "Authorization": `Bearer ${env.GITHUB_TOKEN}`,
        "Accept": "application/vnd.github+json",
        "Content-Type": "application/json",
        "User-Agent": "travian-attacks"
      },
      body: JSON.stringify({
        ref: GITHUB_REF,
        inputs: {
          action: update?.callback_query ? "callback" : "message",
          thread_id: String(THREAD_ID),
          update_json: JSON.stringify(update)
        }
      })
    }
  );

  if (!response.ok) {
    throw new Error(`GitHub API ${response.status}: ${(await response.text()).slice(0, 1500)}`);
  }
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

    const chat = updateChat(update);
    if (!chat) return new Response("OK");

    const privateChat = chat.type === "private";
    const correctThread = Number(updateThreadId(update)) === THREAD_ID;

    // В группе принимаем только сообщения из темы атак.
    // Личные сообщения нужны для owner-only настроек Арены и разведки.
    if (!privateChat && !correctThread) return new Response("OK");

    if (update.callback_query?.id) {
      await answerCallback(env, update.callback_query.id);
    }

    try {
      await dispatch(env, update);
    } catch (error) {
      console.error(error instanceof Error ? error.message : String(error));
    }

    return new Response("OK");
  }
};
