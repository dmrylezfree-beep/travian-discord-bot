import json
import os
import time

import attacks_bot as bot


RUN_SECONDS = int(os.environ.get("ATTACKS_RUN_SECONDS", "510"))
TG_POLL_TIMEOUT = int(os.environ.get("ATTACKS_TG_POLL_TIMEOUT", "20"))


def tg(method, **kwargs):
    return bot.telegram(method, **kwargs)


def delete_webhook():
    result = tg("deleteWebhook", drop_pending_updates=False)
    print(f"Telegram webhook disabled: {result}", flush=True)


def update_chat(update):
    message = update.get("message") or {}
    if message:
        return message.get("chat") or {}
    callback = update.get("callback_query") or {}
    return (callback.get("message") or {}).get("chat") or {}


def update_thread_id(update):
    message = update.get("message") or {}
    if message:
        return message.get("message_thread_id")
    callback = update.get("callback_query") or {}
    return (callback.get("message") or {}).get("message_thread_id")


def accepted(update):
    chat = update_chat(update)
    if chat.get("type") == "private":
        return True
    return update_thread_id(update) == bot.TELEGRAM_THREAD_ID


def process(update):
    if not accepted(update):
        return False
    bot.process_update(update)
    return True


def poll():
    if not bot.TELEGRAM_TOKEN:
        raise RuntimeError("Не задан TELEGRAM_TOKEN.")

    bot.ensure_data()
    bot.offer_owners = bot.load_offer_owners()
    delete_webhook()

    initial_raw = os.environ.get("ATTACKS_INITIAL_UPDATE_JSON", "").strip()
    if initial_raw:
        try:
            initial = json.loads(initial_raw)
            if process(initial):
                print(
                    f"Processed initial Telegram update {initial.get('update_id')}",
                    flush=True,
                )
        except Exception as exc:
            print(f"Initial Telegram update failed: {exc}", flush=True)

    offset = None
    deadline = time.monotonic() + RUN_SECONDS
    processed = 0

    print(f"Attacks bot polling started for {RUN_SECONDS} seconds", flush=True)

    while time.monotonic() < deadline:
        remaining = max(1, int(deadline - time.monotonic()))
        timeout = min(TG_POLL_TIMEOUT, remaining)
        try:
            kwargs = {
                "timeout": timeout,
                "allowed_updates": ["message", "callback_query"],
            }
            if offset is not None:
                kwargs["offset"] = offset
            updates = tg("getUpdates", **kwargs) or []
        except Exception as exc:
            print(f"getUpdates error: {exc}", flush=True)
            time.sleep(2)
            continue

        bot.close_expired_operations()

        for update in updates:
            update_id = update.get("update_id")
            if isinstance(update_id, int):
                offset = update_id + 1
            try:
                if process(update):
                    processed += 1
                    print(
                        f"Processed Telegram update {update_id} (processed={processed})",
                        flush=True,
                    )
            except Exception as exc:
                print(f"Telegram update {update_id} failed: {exc}", flush=True)

    print(f"Attacks bot polling finished; processed {processed} updates", flush=True)


if __name__ == "__main__":
    poll()
