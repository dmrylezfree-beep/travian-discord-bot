import json
import os
import time
import requests

TOKEN = os.environ.get("DEFENCE_TELEGRAM_TOKEN") or os.environ.get("TELEGRAM_TOKEN")
API = f"https://api.telegram.org/bot{TOKEN}"

if not TOKEN:
    raise RuntimeError("DEFENCE_TELEGRAM_TOKEN is not set")

print("DEFENCE DEBUG STARTED", flush=True)
print("Waiting for one Telegram update for up to 90 seconds...", flush=True)

r = requests.post(
    f"{API}/getUpdates",
    data={
        "timeout": 80,
        "allowed_updates": json.dumps(["message", "callback_query"]),
    },
    timeout=90,
)
r.raise_for_status()
result = r.json()
print("Telegram response ok:", result.get("ok"), flush=True)

updates = result.get("result", [])
print("Updates received:", len(updates), flush=True)

for update in updates:
    print("RAW UPDATE:", json.dumps(update, ensure_ascii=False, indent=2), flush=True)
    message = update.get("message") or {}
    if message:
        print("MESSAGE CHAT_ID:", message.get("chat", {}).get("id"), flush=True)
        print("MESSAGE THREAD_ID:", message.get("message_thread_id"), flush=True)
        print("MESSAGE IS_TOPIC:", message.get("is_topic_message"), flush=True)
        print("MESSAGE TEXT:", message.get("text"), flush=True)

print("DEFENCE DEBUG FINISHED", flush=True)
