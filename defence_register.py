import json
import os

import defence_bot as bot


def main():
    raw = os.environ.get("DEFENCE_REGISTER_UPDATE_JSON", "").strip()
    if not raw:
        raise RuntimeError("DEFENCE_REGISTER_UPDATE_JSON is empty")

    update = json.loads(raw)
    message = update.get("message") or {}
    chat = message.get("chat") or {}
    user = message.get("from") or {}

    if chat.get("type") != "private" or not user.get("id") or not chat.get("id"):
        raise RuntimeError("Update is not a valid private chat registration")

    data, player = bot.get_player(user)
    player["private_chat_id"] = int(chat["id"])
    player["private_notifications"] = True
    bot.save_players(data)

    bot.send_private(
        chat["id"],
        "<b>🔔 Личные уведомления подключены.</b>\n\n"
        "Теперь бот будет писать вам в личку, когда появляется новая заявка на деф "
        "и хотя бы одна из ваших настроенных деревень теоретически успевает прибыть до атаки.\n\n"
        "Количество доступного дефа не используется как условие для уведомления.",
    )

    print(f"Private defence notifications registered for user {user['id']}", flush=True)


if __name__ == "__main__":
    main()
