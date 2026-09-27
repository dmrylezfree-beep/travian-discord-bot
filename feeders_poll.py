import json
import os
import time

import telegram_bot as bot


RUN_SECONDS = int(os.environ.get("FEEDERS_RUN_SECONDS", "510"))
POLL_TIMEOUT = int(os.environ.get("FEEDERS_TG_POLL_TIMEOUT", "20"))


def accepted(update):
    msg = update.get("message") or (update.get("callback_query") or {}).get("message") or {}
    return int(msg.get("message_thread_id") or 0) == bot.FEEDER_THREAD_ID


def parse_coordinates(text):
    parts = str(text or "").strip().split()
    if len(parts) < 2 or len(parts) % 2:
        return ""
    try:
        values = [int(v) for v in parts]
    except ValueError:
        return ""
    return "coords:" + ";".join(
        f"{values[i]},{values[i + 1]}"
        for i in range(0, len(values), 2)
    )


def process_update(update):
    callback = update.get("callback_query")

    if callback:
        msg = callback.get("message") or {}
        data = str(callback.get("data") or "")
        if not data.startswith("feeders|"):
            return

        parts = data.split("|")
        if len(parts) < 3:
            return

        values = {
            "ACTION": "callback",
            "CHAT_ID": str((msg.get("chat") or {}).get("id") or ""),
            "MESSAGE_ID": str(msg.get("message_id") or ""),
            "THREAD_ID": str(bot.FEEDER_THREAD_ID),
            "ORIGIN_SPEC": "|".join(parts[2:]),
            "PAGE": parts[1],
            "CALLBACK_ID": str(callback.get("id") or ""),
        }
    else:
        msg = update.get("message") or {}
        origin_spec = parse_coordinates(msg.get("text"))
        if not origin_spec:
            return

        values = {
            "ACTION": "command",
            "CHAT_ID": str((msg.get("chat") or {}).get("id") or ""),
            "MESSAGE_ID": str(msg.get("message_id") or ""),
            "THREAD_ID": str(bot.FEEDER_THREAD_ID),
            "ORIGIN_SPEC": origin_spec,
            "PAGE": "0",
            "CALLBACK_ID": "",
        }

    old = {key: os.environ.get(key) for key in values}
    try:
        os.environ.update(values)
        bot.process_request()
    finally:
        for key, value in old.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value


def main():
    raw = os.environ.get("FEEDERS_INITIAL_UPDATE_JSON", "").strip()
    if raw:
        try:
            update = json.loads(raw)
            if accepted(update):
                process_update(update)
        except Exception as exc:
            print("Initial update failed:", repr(exc), flush=True)

    offset = None
    deadline = time.monotonic() + RUN_SECONDS

    while time.monotonic() < deadline:
        timeout = min(POLL_TIMEOUT, max(1, int(deadline - time.monotonic())))
        payload = {
            "timeout": timeout,
            "allowed_updates": ["message", "callback_query"],
        }
        if offset is not None:
            payload["offset"] = offset

        try:
            updates = bot.telegram_request("getUpdates", payload, timeout=timeout + 10) or []
        except Exception as exc:
            print("getUpdates:", repr(exc), flush=True)
            time.sleep(2)
            continue

        for update in updates:
            update_id = update.get("update_id")
            if isinstance(update_id, int):
                offset = update_id + 1
            if accepted(update):
                try:
                    process_update(update)
                except Exception as exc:
                    print("process:", repr(exc), flush=True)


if __name__ == "__main__":
    main()
