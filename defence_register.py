import json
import os

import defence_bot as bot
import defence_requests  # noqa: F401 - installs the full settings/request handlers


def main():
    raw = os.environ.get("DEFENCE_REGISTER_UPDATE_JSON", "").strip()
    if not raw:
        raise RuntimeError("DEFENCE_REGISTER_UPDATE_JSON is empty")

    update = json.loads(raw)
    message = update.get("message") or {}
    callback = update.get("callback_query") or {}
    callback_message = callback.get("message") or {}
    chat = message.get("chat") or callback_message.get("chat") or {}
    user = message.get("from") or callback.get("from") or {}

    if chat.get("type") != "private" or not user.get("id") or not chat.get("id"):
        raise RuntimeError("Update is not a valid private chat update")

    data, player = bot.get_player(user)
    player["private_chat_id"] = int(chat["id"])
    player["private_notifications"] = True
    bot.save_players(data)

    if callback:
        bot.callback_query(callback)
    else:
        bot.process_text(message)

    print(f"Private defence update processed for user {user['id']}", flush=True)


if __name__ == "__main__":
    main()
