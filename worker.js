
const THREAD_ID = 75984;


// ============================================================
// РАЗБОР КООРДИНАТ
// ============================================================

function parseCoordinates(text) {
  const parts = text.trim().split(/\s+/);

  console.log(
    "parseCoordinates: parts =",
    JSON.stringify(parts)
  );

  // Координаты должны идти парами:
  // 10 20
  // 10 20 30 40
  if (parts.length < 2 || parts.length % 2 !== 0) {
    console.log(
      "parseCoordinates: неправильное количество значений"
    );

    return null;
  }

  if (!parts.every(value => /^-?\d+$/.test(value))) {
    console.log(
      "parseCoordinates: найдены нечисловые значения"
    );

    return null;
  }

  const coordinates = [];

  for (let i = 0; i < parts.length; i += 2) {
    coordinates.push(
      `${parts[i]},${parts[i + 1]}`
    );
  }

  const result =
    `coords:${coordinates.join(";")}`;

  console.log(
    "parseCoordinates: результат =",
    result
  );

  return result;
}


// ============================================================
// ЗАПУСК GITHUB ACTIONS
// ============================================================

async function runGitHubWorkflow(env, inputs) {

  console.log(
    "runGitHubWorkflow: начало"
  );

  console.log(
    "runGitHubWorkflow: owner =",
    env.GITHUB_OWNER
  );

  console.log(
    "runGitHubWorkflow: repo =",
    env.GITHUB_REPO
  );

  console.log(
    "runGitHubWorkflow: workflow =",
    env.GITHUB_WORKFLOW
  );

  console.log(
    "runGitHubWorkflow: ref =",
    env.GITHUB_REF || "main"
  );

  console.log(
    "runGitHubWorkflow: action =",
    inputs.action
  );

  console.log(
    "runGitHubWorkflow: chat_id =",
    inputs.chat_id
  );

  console.log(
    "runGitHubWorkflow: message_id =",
    inputs.message_id
  );

  console.log(
    "runGitHubWorkflow: thread_id =",
    inputs.thread_id
  );

  console.log(
    "runGitHubWorkflow: origin_spec =",
    inputs.origin_spec
  );

  console.log(
    "runGitHubWorkflow: page =",
    inputs.page
  );


  // ВАЖНО:
  // Сам токен никогда не выводим в лог.
  console.log(
    "runGitHubWorkflow: GITHUB_TOKEN присутствует =",
    Boolean(env.GITHUB_TOKEN)
  );


  const url =
    `https://api.github.com/repos/` +
    `${env.GITHUB_OWNER}/` +
    `${env.GITHUB_REPO}` +
    `/actions/workflows/` +
    `${env.GITHUB_WORKFLOW}/dispatches`;


  console.log(
    "runGitHubWorkflow: GitHub URL =",
    url
  );


  const response = await fetch(url, {
    method: "POST",

    headers: {
      "Authorization":
        `Bearer ${env.GITHUB_TOKEN}`,

      "Accept":
        "application/vnd.github+json",

      "Content-Type":
        "application/json",

      "User-Agent":
        "travian-feeders"
    },

    body: JSON.stringify({
      ref:
        env.GITHUB_REF || "main",

      inputs
    })
  });


  console.log(
    "runGitHubWorkflow: GitHub HTTP status =",
    response.status
  );


  if (!response.ok) {

    const errorText =
      await response.text();

    console.error(
      "runGitHubWorkflow: GitHub API ERROR =",
      errorText
    );

    throw new Error(
      `GitHub API ${response.status}: ${errorText}`
    );
  }


  console.log(
    "runGitHubWorkflow: GitHub Actions успешно запущен"
  );
}


// ============================================================
// ОТВЕТ НА CALLBACK
// ============================================================

async function answerCallback(env, callbackId) {

  if (!callbackId) {
    console.log(
      "answerCallback: callbackId отсутствует"
    );

    return;
  }


  console.log(
    "answerCallback: отвечаем на callback"
  );


  const response =
    await fetch(
      `https://api.telegram.org/` +
      `bot${env.TELEGRAM_BOT_TOKEN}/` +
      `answerCallbackQuery`,
      {
        method: "POST",

        headers: {
          "Content-Type":
            "application/json"
        },

        body: JSON.stringify({
          callback_query_id:
            callbackId
        })
      }
    );


  console.log(
    "answerCallback: Telegram HTTP status =",
    response.status
  );
}


// ============================================================
// ОСНОВНОЙ WORKER
// ============================================================

export default {

  async fetch(request, env) {

    console.log(
      "=================================================="
    );

    console.log(
      "WORKER START"
    );

    console.log(
      "Method =",
      request.method
    );

    console.log(
      "URL =",
      request.url
    );

    console.log(
      "=================================================="
    );


    // ========================================================
    // GET
    // ========================================================

    if (request.method !== "POST") {

      console.log(
        "Получен не-POST запрос."
      );

      console.log(
        "Запрос игнорируется."
      );

      return new Response("OK");
    }


    // ========================================================
    // ЧТЕНИЕ TELEGRAM UPDATE
    // ========================================================

    let update;

    try {

      update =
        await request.json();

      console.log(
        "Telegram update успешно прочитан."
      );

    } catch (error) {

      console.error(
        "ОШИБКА: не удалось прочитать JSON Telegram update:",
        error instanceof Error
          ? error.message
          : String(error)
      );

      return new Response("OK");
    }


    // ========================================================
    // ДИАГНОСТИКА ТИПА UPDATE
    // ========================================================

    console.log(
      "Типы update:"
    );

    console.log(
      "update.message =",
      Boolean(update.message)
    );

    console.log(
      "update.callback_query =",
      Boolean(update.callback_query)
    );


    // ========================================================
    // CALLBACK — КНОПКА «ПОКАЗАТЬ ЕЩЁ»
    // ========================================================

    if (update.callback_query) {

      console.log(
        "Получен callback_query."
      );


      const callback =
        update.callback_query;

      const message =
        callback.message;


      if (!message) {

        console.log(
          "Callback без message. Игнорируем."
        );

        return new Response("OK");
      }


      console.log(
        "Callback message:"
      );

      console.log(
        "chat.id =",
        message.chat?.id
      );

      console.log(
        "message_id =",
        message.message_id
      );

      console.log(
        "is_topic_message =",
        message.is_topic_message
      );

      console.log(
        "message_thread_id =",
        message.message_thread_id
      );

      console.log(
        "callback.data =",
        callback.data
      );


      // Проверяем тему.

      if (
        message.is_topic_message !== true
      ) {

        console.log(
          "CALLBACK ОТФИЛЬТРОВАН: " +
          "это не topic message."
        );

        return new Response("OK");
      }


      if (
        Number(message.message_thread_id)
        !== THREAD_ID
      ) {

        console.log(
          "CALLBACK ОТФИЛЬТРОВАН: " +
          `thread_id ${message.message_thread_id} ` +
          `не равен ${THREAD_ID}.`
        );

        return new Response("OK");
      }


      const data =
        String(callback.data || "");


      if (
        !data.startsWith("feeders|")
      ) {

        console.log(
          "CALLBACK ОТФИЛЬТРОВАН: " +
          "callback.data не начинается с feeders|."
        );

        return new Response("OK");
      }


      const parts =
        data.split("|");


      const page =
        parts[1];


      const originSpec =
        parts.slice(2).join("|");


      console.log(
        "Callback page =",
        page
      );

      console.log(
        "Callback originSpec =",
        originSpec
      );


      await answerCallback(
        env,
        callback.id
      );


      console.log(
        "Запускаем GitHub Actions для callback."
      );


      await runGitHubWorkflow(
        env,
        {
          action:
            "callback",

          chat_id:
            String(message.chat.id),

          message_id:
            String(message.message_id),

          thread_id:
            String(THREAD_ID),

          origin_spec:
            originSpec,

          page:
            page,

          callback_id:
            String(callback.id)
        }
      );


      console.log(
        "CALLBACK ОБРАБОТАН УСПЕШНО."
      );


      return new Response("OK");
    }


    // ========================================================
    // ОБЫЧНОЕ СООБЩЕНИЕ
    // ========================================================

    const message =
      update.message;


    if (!message) {

      console.log(
        "UPDATE НЕ СОДЕРЖИТ message."
      );

      console.log(
        "Это не callback_query и не обычное сообщение."
      );

      return new Response("OK");
    }


    // ========================================================
    // ДИАГНОСТИКА TELEGRAM MESSAGE
    // ========================================================

    console.log(
      "Telegram message получен."
    );

    console.log(
      "chat.id =",
      message.chat?.id
    );

    console.log(
      "chat.type =",
      message.chat?.type
    );

    console.log(
      "chat.title =",
      message.chat?.title
    );

    console.log(
      "message_id =",
      message.message_id
    );

    console.log(
      "from.id =",
      message.from?.id
    );

    console.log(
      "from.username =",
      message.from?.username
    );

    console.log(
      "is_topic_message =",
      message.is_topic_message
    );

    console.log(
      "message_thread_id =",
      message.message_thread_id
    );

    console.log(
      "text =",
      JSON.stringify(message.text)
    );


    // ========================================================
    // ПРОВЕРКА ТЕМЫ
    // ========================================================

    if (
      message.is_topic_message !== true
    ) {

      console.log(
        "СООБЩЕНИЕ ОТФИЛЬТРОВАНО: " +
        "message.is_topic_message !== true"
      );

      return new Response("OK");
    }


    console.log(
      "Проверка is_topic_message: OK"
    );


    if (
      Number(message.message_thread_id)
      !== THREAD_ID
    ) {

      console.log(
        "СООБЩЕНИЕ ОТФИЛЬТРОВАНО: " +
        `thread_id = ${message.message_thread_id}, ` +
        `ожидался ${THREAD_ID}`
      );

      return new Response("OK");
    }


    console.log(
      "Проверка THREAD_ID: OK"
    );


    // ========================================================
    // ПОЛУЧАЕМ ТЕКСТ
    // ========================================================

    const text =
      String(message.text || "").trim();


    console.log(
      "Очищенный text =",
      JSON.stringify(text)
    );


    if (!text) {

      console.log(
        "СООБЩЕНИЕ ОТФИЛЬТРОВАНО: " +
        "пустой text"
      );

      return new Response("OK");
    }


    // ========================================================
    // РАЗБОР КООРДИНАТ
    // ========================================================

    const originSpec =
      parseCoordinates(text);


    console.log(
      "originSpec =",
      originSpec
    );


    if (!originSpec) {

      console.log(
        "СООБЩЕНИЕ ОТФИЛЬТРОВАНО: " +
        "текст не распознан как координаты."
      );

      return new Response("OK");
    }


    // ========================================================
    // ЗАПУСК GITHUB ACTIONS
    // ========================================================

    console.log(
      "=================================================="
    );

    console.log(
      "ВСЕ ПРОВЕРКИ ПРОЙДЕНЫ."
    );

    console.log(
      "Запускаем GitHub Actions..."
    );

    console.log(
      "=================================================="
    );


    try {

      await runGitHubWorkflow(
        env,
        {
          action:
            "command",

          chat_id:
            String(message.chat.id),

          message_id:
            String(message.message_id),

          thread_id:
            String(THREAD_ID),

          origin_spec:
            originSpec,

          page:
            "0",

          callback_id:
            ""
        }
      );


      console.log(
        "GitHub Actions успешно запущен."
      );

    } catch (error) {

      console.error(
        "ОШИБКА ПРИ ЗАПУСКЕ GITHUB ACTIONS:",
        error instanceof Error
          ? error.message
          : String(error)
      );

      return new Response("OK");
    }


    // ========================================================
    // ГОТОВО
    // ========================================================

    console.log(
      "WORKER FINISH: SUCCESS"
    );

    console.log(
      "=================================================="
    );


    return new Response("OK");
  }
};

