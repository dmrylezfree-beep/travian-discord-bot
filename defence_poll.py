import os
import time
import traceback
from datetime import datetime

import defence_bot as bot
import defence_requests as defence


# Positive value = a short polling session (used by the legacy GitHub Action).
# 0 or a negative value = run continuously (used by the VPS systemd service).
RUN_SECONDS = int(os.environ.get("DEFENCE_RUN_SECONDS", "540"))
TG_POLL_TIMEOUT = int(os.environ.get("DEFENCE_TG_POLL_TIMEOUT", "20"))


def delete_webhook():
    # Keep pending updates when switching from webhook delivery to polling.
    result = bot.tg("deleteWebhook", drop_pending_updates=False)
    print(f"Telegram webhook disabled: {result}", flush=True)


def update_thread_id(update):
    message = update.get("message") or update.get("edited_message") or {}
    if message:
        return message.get("message_thread_id")
    callback = update.get("callback_query") or {}
    message = callback.get("message") or {}
    return message.get("message_thread_id")


def update_chat_id(update):
    message = update.get("message") or update.get("edited_message") or {}
    if message:
        return message.get("chat", {}).get("id")
    callback = update.get("callback_query") or {}
    message = callback.get("message") or {}
    return message.get("chat", {}).get("id")


def process_private_start(update):
    message = update.get("message") or update.get("edited_message")
    if not message:
        return False
    chat = message.get("chat") or {}
    text = (message.get("text") or "").strip()
    if chat.get("type") != "private" or not text.startswith("/start"):
        return False

    user = message.get("from") or {}
    if not user.get("id") or not chat.get("id"):
        return False

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
    return True


def normalize_date_time_message(message):
    """Combine the date selected by the user with the entered time."""
    text = (message.get("text") or "").strip()
    if not text:
        return message

    user = message.get("from", {})
    if not user:
        return message

    try:
        _data, player = bot.get_player(user)
    except Exception:
        return message

    state = player.get("state")
    if not isinstance(state, dict) or state.get("type") != "request_attack_time":
        return message

    try:
        attack_date = datetime.strptime(
            state["attack_date"], "%Y-%m-%d"
        ).date()
    except (KeyError, TypeError, ValueError):
        return message

    try:
        attack_clock = datetime.strptime(text, "%H:%M:%S").time()
    except ValueError:
        return message

    normalized = dict(message)
    normalized["text"] = datetime.combine(attack_date, attack_clock).strftime(
        "%d.%m.%Y %H:%M:%S"
    )
    print(
        f"Normalized defence attack time: {text} -> {normalized['text']}",
        flush=True,
    )
    return normalized


def process_update(update):
    if "callback_query" in update:
        defence.handle_update(callback=update["callback_query"])
        return True

    message = update.get("message")
    if message is not None:
        message = normalize_date_time_message(message)
        defence.handle_update(message=message)
        return True

    return False


def poll():
    delete_webhook()

    # When the legacy webhook starts a short GitHub Actions session, it may pass
    # the triggering update here because Telegram has already delivered it to
    # the Worker. The VPS normally leaves this empty.
    initial_update_json = os.environ.get("DEFENCE_INITIAL_UPDATE_JSON", "").strip()
    if initial_update_json:
        try:
            initial_update = __import__("json").loads(initial_update_json)
            initial_message = initial_update.get("message") or initial_update.get("edited_message") or {}
            initial_callback_message = (initial_update.get("callback_query") or {}).get("message") or {}
            initial_chat = initial_message.get("chat") or initial_callback_message.get("chat") or {}
            thread_id = update_thread_id(initial_update)
            if initial_chat.get("type") == "private" or thread_id == bot.THREAD_ID:
                if process_update(initial_update):
                    print(
                        f"Processed initial Telegram update "
                        f"{initial_update.get('update_id')}",
                        flush=True,
                    )
        except Exception as exc:
            print(f"Initial Telegram update failed: {exc}", flush=True)
            traceback.print_exc()

    offset = None
    continuous = RUN_SECONDS <= 0
    deadline = None if continuous else time.monotonic() + RUN_SECONDS
    processed = 0

    if continuous:
        print("Defence bot polling started in continuous VPS mode", flush=True)
    else:
        print(f"Defence bot polling started for {RUN_SECONDS} seconds", flush=True)

    while continuous or time.monotonic() < deadline:
        if continuous:
            timeout = TG_POLL_TIMEOUT
        else:
            remaining = max(1, int(deadline - time.monotonic()))
            timeout = min(TG_POLL_TIMEOUT, remaining)

        try:
            updates = bot.tg(
                "getUpdates",
                offset=offset if offset is not None else "",
                timeout=timeout,
                allowed_updates='["message","callback_query"]',
            ) or []
        except Exception as exc:
            print(f"getUpdates error: {exc}", flush=True)
            time.sleep(2)
            continue

        for update in updates:
            update_id = update.get("update_id")
            if isinstance(update_id, int):
                offset = update_id + 1

            message = update.get("message") or update.get("edited_message") or {}
            callback_message = (update.get("callback_query") or {}).get("message") or {}
            update_chat = message.get("chat") or callback_message.get("chat") or {}
            private_update = update_chat.get("type") == "private"

            thread_id = update_thread_id(update)
            if not private_update and thread_id != bot.THREAD_ID:
                continue

            try:
                if process_update(update):
                    processed += 1
                    print(
                        f"Processed Telegram update {update.get('update_id')} "
                        f"(processed={processed})",
                        flush=True,
                    )
            except Exception as exc:
                # Advance offset even if one malformed update fails, otherwise
                # the same update could block the bot indefinitely.
                print(
                    f"Telegram update {update.get('update_id')} failed: {exc}",
                    flush=True,
                )
                traceback.print_exc()

    print(f"Defence bot polling finished; processed {processed} updates", flush=True)


if __name__ == "__main__":
    poll()
