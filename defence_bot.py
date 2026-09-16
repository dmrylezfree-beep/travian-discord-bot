import json
import os
import time
import subprocess
from datetime import datetime
from pathlib import Path

import requests


TELEGRAM_TOKEN = os.environ.get("DEFENCE_TELEGRAM_TOKEN") or os.environ.get("TELEGRAM_TOKEN")
THREAD_ID = 38636
POLL_TIMEOUT = 25
REQUEST_TIMEOUT = 40
DATA_DIR = Path("data/defence")
SETTINGS_FILE = DATA_DIR / "settings.json"
PLAYERS_FILE = DATA_DIR / "players.json"
REQUESTS_FILE = DATA_DIR / "requests.json"
API = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}"


def load_json(path, default):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        return default


def save_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(path)


def settings():
    return load_json(SETTINGS_FILE, {})


def players():
    return load_json(PLAYERS_FILE, {})


def requests_data():
    return load_json(REQUESTS_FILE, [])


def save_players(value):
    save_json(PLAYERS_FILE, value)
    persist_data()


def save_requests(value):
    save_json(REQUESTS_FILE, value)
    persist_data()


def persist_data():
    try:
        subprocess.run(["git", "config", "user.name", "defence-bot"], check=False, capture_output=True)
        subprocess.run(["git", "config", "user.email", "defence-bot@users.noreply.github.com"], check=False, capture_output=True)
        status = subprocess.run(["git", "status", "--porcelain", "data/defence"], text=True, capture_output=True)
        if not status.stdout.strip():
            return
        subprocess.run(["git", "add", "data/defence"], check=True)
        subprocess.run(["git", "commit", "-m", "Update defence bot data"], check=False, capture_output=True)
        subprocess.run(["git", "pull", "--rebase", "origin", "main"], check=False, capture_output=True)
        subprocess.run(["git", "push", "origin", "HEAD:main"], check=False, capture_output=True)
    except Exception as exc:
        print("Git persistence error:", exc, flush=True)


def tg(method, **kwargs):
    response = requests.post(f"{API}/{method}", data=kwargs, timeout=REQUEST_TIMEOUT)
    response.raise_for_status()
    data = response.json()
    if not data.get("ok"):
        raise RuntimeError(data)
    return data.get("result")


def send(chat_id, text, reply_markup=None, thread_id=None):
    args = {"chat_id": chat_id, "text": text, "parse_mode": "HTML"}
    if reply_markup:
        args["reply_markup"] = json.dumps(reply_markup, ensure_ascii=False)
    if thread_id is not None:
        args["message_thread_id"] = thread_id
    return tg("sendMessage", **args)


def edit(chat_id, message_id, text, reply_markup=None):
    args = {"chat_id": chat_id, "message_id": message_id, "text": text, "parse_mode": "HTML"}
    if reply_markup is not None:
        args["reply_markup"] = json.dumps(reply_markup, ensure_ascii=False)
    return tg("editMessageText", **args)


def answer_callback(callback_id):
    try:
        tg("answerCallbackQuery", callback_query_id=callback_id)
    except Exception:
        pass


def in_def_thread(message):
    return message.get("message_thread_id") == THREAD_ID


def kb(rows):
    return {"inline_keyboard": rows}


def main_menu():
    return kb([
        [{"text": "⚙️ Мои настройки", "callback_data": "settings"}],
        [{"text": "🏘 Мои деревни", "callback_data": "villages"}],
    ])


def player_default(user):
    return {
        "telegram_id": user["id"],
        "username": user.get("username", ""),
        "first_name": user.get("first_name", ""),
        "villages": [],
        "substitutes": [],
        "state": None,
    }


def get_player(user, create=True):
    data = players()
    key = str(user["id"])
    if key not in data and create:
        data[key] = player_default(user)
        save_json(PLAYERS_FILE, data)
    if key in data:
        data[key]["username"] = user.get("username", data[key].get("username", ""))
        data[key]["first_name"] = user.get("first_name", data[key].get("first_name", ""))
        save_json(PLAYERS_FILE, data)
    return data, key, data.get(key)


def settings_text(player):
    villages = player.get("villages", [])
    lines = ["<b>🛡 Мои настройки дефа</b>", ""]
    if not villages:
        lines.append("Деревни пока не добавлены.")
    else:
        for i, v in enumerate(villages, 1):
            lines.append(f"<b>{i}. {v.get('coordinates', '?')}</b> — Арена {v.get('arena', 0)}")
            troops = v.get("troops", {})
            names = settings().get("units", {})
            active = [f"{names.get(k, {}).get('name', k)}: {n}" for k, n in troops.items() if int(n or 0) > 0]
            lines.append("  " + (", ".join(active) if active else "войска не указаны"))
            hero = v.get("hero", {})
            if hero.get("present"):
                st = int(hero.get("standard_bonus", 0) * 100)
                boots = int(hero.get("boots_bonus", 0) * 100)
                lines.append(f"  🦸 Герой: да | 🚩 {st}% | 🥾 {boots}%")
            else:
                lines.append("  🦸 Герой: нет")
    subs = player.get("substitutes", [])
    lines += ["", f"👥 Заместители: {len(subs)}/2"]
    return "\n".join(lines)


def settings_kb():
    return kb([
        [{"text": "➕ Добавить деревню", "callback_data": "add_village"}],
        [{"text": "✏️ Изменить деревню", "callback_data": "edit_village"}],
        [{"text": "🗑 Удалить деревню", "callback_data": "delete_village"}],
        [{"text": "👥 Заместители", "callback_data": "subs"}],
        [{"text": "⬅️ Назад", "callback_data": "menu"}],
    ])


def villages_kb(player):
    rows = []
    for i, v in enumerate(player.get("villages", [])):
        rows.append([{"text": f"{i + 1}. {v.get('coordinates', '?')}", "callback_data": f"village:{i}"}])
    rows.append([{"text": "➕ Добавить деревню", "callback_data": "add_village"}])
    rows.append([{"text": "⬅️ Назад", "callback_data": "settings"}])
    return kb(rows)


def unit_keyboard(index):
    units = settings().get("units", {})
    rows = []
    for key, unit in units.items():
        rows.append([{"text": unit["name"], "callback_data": f"unit:{index}:{key}"}])
    rows.append([{"text": "🦸 Герой и предметы", "callback_data": f"hero:{index}"}])
    rows.append([{"text": "⬅️ Назад", "callback_data": "villages"}])
    return kb(rows)


def unit_text(v):
    units = settings().get("units", {})
    lines = [f"<b>🏘 Деревня {v.get('coordinates')}</b>", f"Арена: {v.get('arena', 0)}", "", "<b>Войска:</b>"]
    for key, unit in units.items():
        amount = int(v.get("troops", {}).get(key, 0) or 0)
        if amount:
            lines.append(f"{unit['name']}: <b>{amount}</b> (скорость {unit['speed']} полей/ч)")
    lines.append("\nВыберите юнит, чтобы изменить его количество:")
    return "\n".join(lines)


def process_text(message):
    user = message.get("from", {})
    text = (message.get("text") or "").strip()
    if not text:
        return
    data, key, player = get_player(user)
    state = player.get("state")
    chat_id = message["chat"]["id"]

    if text.startswith("/start") or text.startswith("/def"):
        player["state"] = None
        save_players(data)
        send(chat_id, "<b>🛡 ЦЕНТР ДЕФА</b>\n\nЗдесь можно настроить свои деревни и доступный теоретический резерв дефа.", main_menu(), THREAD_ID if in_def_thread(message) else None)
        return

    if not state:
        return

    if state == "add_village_coords":
        if not valid_coords(text):
            send(chat_id, "Неверный формат. Введите координаты так: <code>45|-62</code>")
            return
        player["state"] = {"type": "add_village_arena", "coordinates": text}
        save_players(data)
        send(chat_id, "Введите уровень Арены (0–20):")
        return

    if state.get("type") == "add_village_arena":
        arena = to_int(text)
        if arena is None or not 0 <= arena <= 20:
            send(chat_id, "Введите целое число от 0 до 20.")
            return
        v = {"coordinates": state["coordinates"], "arena": arena, "troops": {}, "hero": {"present": False, "standard_bonus": 0, "boots_bonus": 0}}
        player["villages"].append(v)
        player["state"] = None
        save_players(data)
        send(chat_id, unit_text(v), unit_keyboard(len(player["villages"]) - 1))
        return

    if state.get("type") == "unit_amount":
        amount = to_int(text)
        if amount is None or amount < 0:
            send(chat_id, "Введите целое число 0 или больше.")
            return
        idx, unit = state["index"], state["unit"]
        player["villages"][idx].setdefault("troops", {})[unit] = amount
        player["state"] = None
        save_players(data)
        send(chat_id, unit_text(player["villages"][idx]), unit_keyboard(idx))
        return

    if state.get("type") == "subs":
        ids = [x.strip() for x in text.split(",") if x.strip()]
        if len(ids) > 2 or any(to_int(x) is None or to_int(x) <= 0 for x in ids):
            send(chat_id, "Введите до двух Telegram ID через запятую, например: <code>111111111,222222222</code>")
            return
        player["substitutes"] = [int(x) for x in ids]
        player["state"] = None
        save_players(data)
        send(chat_id, settings_text(player), settings_kb())
        return

    if state.get("type") == "edit_coords":
        idx = state["index"]
        if not valid_coords(text):
            send(chat_id, "Неверный формат. Например: <code>45|-62</code>")
            return
        player["villages"][idx]["coordinates"] = text
        player["state"] = None
        save_players(data)
        send(chat_id, unit_text(player["villages"][idx]), unit_keyboard(idx))
        return

    if state.get("type") == "edit_arena":
        idx = state["index"]
        arena = to_int(text)
        if arena is None or not 0 <= arena <= 20:
            send(chat_id, "Введите целое число от 0 до 20.")
            return
        player["villages"][idx]["arena"] = arena
        player["state"] = None
        save_players(data)
        send(chat_id, unit_text(player["villages"][idx]), unit_keyboard(idx))


def valid_coords(value):
    try:
        x, y = value.split("|", 1)
        return -200 <= int(x) <= 200 and -200 <= int(y) <= 200
    except ValueError:
        return False


def to_int(value):
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def callback_query(q):
    answer_callback(q["id"])
    user = q.get("from", {})
    data, key, player = get_player(user)
    chat_id = q["message"]["chat"]["id"]
    msg_id = q["message"]["message_id"]
    action = q.get("data", "")

    if action == "menu":
        edit(chat_id, msg_id, "<b>🛡 ЦЕНТР ДЕФА</b>\n\nВыберите раздел:", main_menu())
    elif action == "settings":
        edit(chat_id, msg_id, settings_text(player), settings_kb())
    elif action == "villages":
        edit(chat_id, msg_id, "<b>🏘 Мои деревни</b>\n\nВыберите деревню:", villages_kb(player))
    elif action == "add_village":
        player["state"] = "add_village_coords"
        save_players(data)
        send(chat_id, "Введите координаты новой деревни, например <code>45|-62</code>:")
    elif action.startswith("village:"):
        idx = int(action.split(":", 1)[1])
        if idx < len(player.get("villages", [])):
            edit(chat_id, msg_id, unit_text(player["villages"][idx]), unit_keyboard(idx))
    elif action.startswith("unit:"):
        _, idx, unit = action.split(":", 2)
        idx = int(idx)
        player["state"] = {"type": "unit_amount", "index": idx, "unit": unit}
        save_players(data)
        name = settings()["units"][unit]["name"]
        current = player["villages"][idx].get("troops", {}).get(unit, 0)
        send(chat_id, f"Введите количество <b>{name}</b>. Сейчас: <b>{current}</b>")
    elif action.startswith("hero:"):
        idx = int(action.split(":", 1)[1])
        v = player["villages"][idx]
        hero = v.setdefault("hero", {"present": False, "standard_bonus": 0, "boots_bonus": 0})
        edit(chat_id, msg_id, hero_text(v), hero_keyboard(idx))
    elif action.startswith("hero_present:"):
        idx = int(action.split(":", 1)[1])
        v = player["villages"][idx]
        v.setdefault("hero", {})["present"] = not v.setdefault("hero", {}).get("present", False)
        save_players(data)
        edit(chat_id, msg_id, hero_text(v), hero_keyboard(idx))
    elif action.startswith("std:"):
        _, idx, value = action.split(":")
        idx = int(idx)
        player["villages"][idx].setdefault("hero", {})["standard_bonus"] = int(value) / 100
        save_players(data)
        edit(chat_id, msg_id, hero_text(player["villages"][idx]), hero_keyboard(idx))
    elif action.startswith("boots:"):
        _, idx, value = action.split(":")
        idx = int(idx)
        player["villages"][idx].setdefault("hero", {})["boots_bonus"] = int(value) / 100
        save_players(data)
        edit(chat_id, msg_id, hero_text(player["villages"][idx]), hero_keyboard(idx))
    elif action == "subs":
        player["state"] = {"type": "subs"}
        save_players(data)
        send(chat_id, "Введите Telegram ID до двух заместителей через запятую.\n\nПример: <code>111111111,222222222</code>")
    elif action == "edit_village":
        edit(chat_id, msg_id, "Выберите деревню для изменения:", villages_kb(player))
    elif action == "delete_village":
        rows = []
        for i, v in enumerate(player.get("villages", [])):
            rows.append([{"text": f"🗑 {v.get('coordinates')}", "callback_data": f"delv:{i}"}])
        rows.append([{"text": "⬅️ Назад", "callback_data": "settings"}])
        edit(chat_id, msg_id, "Выберите деревню для удаления:", kb(rows))
    elif action.startswith("delv:"):
        idx = int(action.split(":", 1)[1])
        if 0 <= idx < len(player["villages"]):
            player["villages"].pop(idx)
            save_players(data)
        edit(chat_id, msg_id, settings_text(player), settings_kb())


def hero_text(v):
    h = v.get("hero", {})
    st = int(h.get("standard_bonus", 0) * 100)
    boots = int(h.get("boots_bonus", 0) * 100)
    return f"<b>🦸 Герой — {v.get('coordinates')}</b>\n\nГерой в этой деревне: <b>{'да' if h.get('present') else 'нет'}</b>\n🚩 Штандарт: <b>+{st}%</b>\n🥾 Сапоги: <b>+{boots}%</b>"


def hero_keyboard(idx):
    return kb([
        [{"text": "🔄 Герой: переключить", "callback_data": f"hero_present:{idx}"}],
        [{"text": "🚩 Штандарт +15%", "callback_data": f"std:{idx}:15"}, {"text": "+20%", "callback_data": f"std:{idx}:20"}, {"text": "+25%", "callback_data": f"std:{idx}:25"}],
        [{"text": "🥾 Сапоги +25%", "callback_data": f"boots:{idx}:25"}, {"text": "+50%", "callback_data": f"boots:{idx}:50"}, {"text": "+75%", "callback_data": f"boots:{idx}:75"}],
        [{"text": "🚫 Без штандарта", "callback_data": f"std:{idx}:0"}, {"text": "🚫 Без сапог", "callback_data": f"boots:{idx}:0"}],
        [{"text": "⬅️ Назад", "callback_data": f"village:{idx}"}],
    ])


def run():
    if not TELEGRAM_TOKEN:
        raise RuntimeError("DEFENCE_TELEGRAM_TOKEN is not set")
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    offset = None
    print(f"DEFENCE BOT STARTED, THREAD_ID={THREAD_ID}", flush=True)
    while True:
        try:
            updates = tg("getUpdates", offset=offset, timeout=POLL_TIMEOUT, allowed_updates=json.dumps(["message", "callback_query"]))
            for update in updates:
                offset = update["update_id"] + 1
                if "callback_query" in update:
                    q = update["callback_query"]
                    if q.get("message", {}).get("message_thread_id") == THREAD_ID:
                        callback_query(q)
                elif "message" in update:
                    message = update["message"]
                    if in_def_thread(message):
                        process_text(message)
        except Exception as exc:
            print("Polling error:", exc, flush=True)
            time.sleep(5)


if __name__ == "__main__":
    run()
