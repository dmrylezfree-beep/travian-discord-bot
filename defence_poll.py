import os
import time
from datetime import datetime

import defence_bot as bot
import defence_requests as defence


RUN_SECONDS = int(os.environ.get("DEFENCE_RUN_SECONDS", "540"))
TG_POLL_TIMEOUT = int(os.environ.get("DEFENCE_TG_POLL_TIMEOUT", "20"))


def delete_webhook():
    # Keep pending updates. We are deliberately switching this bot from
    # webhook delivery to long polling so one GitHub Actions run can serve
    # several Telegram interactions without starting a new workflow each time.
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


def normalize_date_time_message(message):
    """Combine the date selected by the user with the entered time.

    defence_requests.py still contains the old full-date parser for
    request_attack_time. The new UI deliberately asks for the date first
    and then only HH:MM:SS, so normalize the message before dispatching it.
    """
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

    state = player.get("state") or {}
    if state.get("type") != "request_attack_time":
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

    # Refresh once when the worker starts, which also expires old requests.
    defence.refresh_center(create_if_missing=False)

    offset = None
    deadline = time.monotonic() + RUN_SECONDS
    processed = 0

    print(f"Defence bot polling started for {RUN_SECONDS} seconds", flush=True)

    while time.monotonic() < deadline:
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

            thread_id = update_thread_id(update)
            if thread_id != bot.THREAD_ID:
                continue

            try:
                if process_update(update):
                    processed += 1
                    chat_id = update_chat_id(update)
                    defence.refresh_center(chat_id=chat_id, create_if_missing=False)
                    print(
                        f"Processed Telegram update {update.get('update_id')} "
                        f"(processed={processed})",
                        flush=True,
                    )
            except Exception as exc:
                # Advance offset even if one malformed update fails, otherwise
                # the same update could block the entire bot on the next poll.
                print(
                    f"Telegram update {update.get('update_id')} failed: {exc}",
                    flush=True,
                )

    print(f"Defence bot polling finished; processed {processed} updates", flush=True)


if __name__ == "__main__":
    poll()
