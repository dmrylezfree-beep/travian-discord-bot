import json
import os
import time
import subprocess
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
OWNER_TELEGRAM_ID = 317595036

INFANTRY_UNITS = {"phalanx", "spearman", "legionnaire", "praetorian"}
CAVALRY_UNITS = {"druidrider", "haeduan", "paladin", "equites_caesaris"}

RACES = {
    "gaul": {"name": "Галл", "units": ["phalanx", "druidrider", "haeduan"]},
    "teuton": {"name": "Германец", "units": ["spearman", "paladin"]},
    "roman": {"name": "Римлянин", "units": ["legionnaire", "praetorian", "equites_caesaris"]},
}


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


def save_players(value):
    save_json(PLAYERS_FILE, value)
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
    result = response.json()
    if not result.get("ok"):
        raise RuntimeError(result)
    return result.get("result")


def is_private_chat_id(chat_id):
    return any(str(p.get("private_chat_id")) == str(chat_id) for p in players().values() if isinstance(p, dict) and p.get("private_chat_id"))


def send(chat_id, text, reply_markup=None, thread_id=THREAD_ID, force_reply=False):
    args = {"chat_id": chat_id, "text": text, "parse_mode": "HTML"}
    if thread_id is not None and not is_private_chat_id(chat_id):
        args["message_thread_id"] = thread_id
    if force_reply:
        args["reply_markup"] = json.dumps({"force_reply": True, "selective": False}, ensure_ascii=False)
    elif reply_markup:
        args["reply_markup"] = json.dumps(reply_markup, ensure_ascii=False)
    return tg("sendMessage", **args)


def edit(chat_id, message_id, text, reply_markup=None):
    args = {"chat_id": chat_id, "message_id": message_id, "text": text, "parse_mode": "HTML"}
    if reply_markup is not None:
        args["reply_markup"] = json.dumps(reply_markup, ensure_ascii=False)
    return tg("editMessageText", **args)


def send_private(chat_id, text, reply_markup=None):
    args = {"chat_id": chat_id, "text": text, "parse_mode": "HTML"}
    if reply_markup:
        args["reply_markup"] = json.dumps(reply_markup, ensure_ascii=False)
    return tg("sendMessage", **args)


def answer_callback(callback_id, text=None):
    try:
        kwargs = {"callback_query_id": callback_id}
        if text:
            kwargs["text"] = text
            kwargs["show_alert"] = False
        tg("answerCallbackQuery", **kwargs)
    except Exception:
        pass


def in_def_thread(message):
    return message.get("message_thread_id") == THREAD_ID


def kb(rows):
    return {"inline_keyboard": rows}


def main_menu():
    return kb([
        [{"text": "➕ Запросить деф", "callback_data": "request_def"}],
        [{"text": "⚙️ Мои настройки", "callback_data": "settings"}],
    ])


def player_default(user):
    return {
        "telegram_id": user["id"],
        "username": user.get("username", ""),
        "first_name": user.get("first_name", ""),
        "race": None,
        "villages": [],
        "substitutes": [],
        "state": None,
        "private_chat_id": None,
        "private_notifications": True,
        "hero_inventory": {"standards": [], "boots": [], "maps": []},
    }


def get_player(user):
    data = players()
    key = str(user["id"])
    if key not in data:
        data[key] = player_default(user)
    data[key]["username"] = user.get("username", data[key].get("username", ""))
    data[key]["first_name"] = user.get("first_name", data[key].get("first_name", ""))
    data[key].setdefault("race", None)
    data[key].setdefault("villages", [])
    data[key].setdefault("substitutes", [])
    data[key].setdefault("state", None)
    data[key].setdefault("private_chat_id", None)
    data[key].setdefault("private_notifications", True)
    inv = data[key].setdefault("hero_inventory", {"standards": [], "boots": [], "maps": []})
    for kind in ("standards", "boots", "maps"):
        inv.setdefault(kind, [])
    # One-time compatibility: preserve old equipped standard/boots as owned items.
    for village in data[key].get("villages", []):
        hero = village.get("hero") or {}
        std = int(round(float(hero.get("standard_bonus", 0) or 0) * 100))
        boots = int(round(float(hero.get("boots_bonus", 0) or 0) * 100))
        if std and std not in inv["standards"]:
            inv["standards"].append(std)
        if boots and boots not in inv["boots"]:
            inv["boots"].append(boots)
    save_json(PLAYERS_FILE, data)
    return data, data[key]


def race_name(player):
    return RACES.get(player.get("race"), {}).get("name", "не выбрана")


def allowed_units(player):
    return RACES.get(player.get("race"), {}).get("units", [])


def race_keyboard():
    return kb([
        [{"text": "🇫🇷 Галл", "callback_data": "race:gaul"}],
        [{"text": "🇩🇪 Германец", "callback_data": "race:teuton"}],
        [{"text": "🇮🇹 Римлянин", "callback_data": "race:roman"}],
        [{"text": "⬅️ Назад", "callback_data": "settings"}],
    ])


def hero_inventory(player):
    inv = player.setdefault("hero_inventory", {"standards": [], "boots": [], "maps": []})
    for kind in ("standards", "boots", "maps"):
        inv.setdefault(kind, [])
        inv[kind] = sorted({int(x) for x in inv[kind] if int(x) > 0})
    return inv


def hero_village_index(player):
    for i, village in enumerate(player.get("villages", [])):
        if (village.get("hero") or {}).get("present"):
            return i
    return None


def settings_text(player):
    units = settings().get("units", {})
    inv = hero_inventory(player)
    lines = ["<b>🛡 Мои настройки дефа</b>", "", f"🧬 Раса: <b>{race_name(player)}</b>"]
    villages = player.get("villages", [])
    if not villages:
        lines.append("Деревни пока не добавлены.")
    for i, v in enumerate(villages, 1):
        lines.append(f"<b>{i}. {v.get('coordinates', '?')}</b> — Арена {v.get('arena', 0)}")
        active = [f"{units.get(k, {}).get('name', k)}: {n}" for k, n in v.get("troops", {}).items() if int(n or 0) > 0]
        lines.append("  " + (", ".join(active) if active else "войска не указаны"))
        if (v.get("hero") or {}).get("present"):
            lines.append("  🦸 Герой находится здесь")
    if any(inv.values()):
        lines += ["", "<b>🎒 Инвентарь героя:</b>"]
        lines.append("🚩 Штандарты: " + (", ".join(f"+{x}%" for x in inv["standards"]) or "нет"))
        lines.append("🥾 Сапоги: " + (", ".join(f"+{x}%" for x in inv["boots"]) or "нет"))
        lines.append("🗺 Карты: " + (", ".join(f"+{x}%" for x in inv["maps"]) or "нет"))
    notification_status = "подключены" if player.get("private_chat_id") and player.get("private_notifications", True) else "не подключены"
    lines += ["", f"🔔 Личные уведомления: <b>{notification_status}</b>", f"👥 Заместители: {len(player.get('substitutes', []))}/2"]
    return "\n".join(lines)


def is_owner(user):
    return int(user.get("id", 0) or 0) == OWNER_TELEGRAM_ID


def settings_kb(owner=False):
    rows = [
        [{"text": "🏘 Мои деревни", "callback_data": "villages"}],
        [{"text": "🆔 Узнать мой Telegram ID", "callback_data": "my_id"}],
        [{"text": "➕ Добавить деревню", "callback_data": "add_village"}],
        [{"text": "✏️ Изменить деревню", "callback_data": "edit_village"}],
        [{"text": "🗑 Удалить деревню", "callback_data": "delete_village"}],
        [{"text": "👥 Заместители", "callback_data": "subs"}],
        [{"text": "🔔 Личные уведомления", "callback_data": "private_notify"}],
        [{"text": "⬅️ Назад", "callback_data": "menu"}],
    ]
    if owner:
        rows.insert(0, [{"text": "📊 Оборона альянса", "callback_data": "alliance_def"}])
    return kb(rows)


def fmt_num(value):
    return f"{int(value):,}".replace(",", " ")


def player_name(p):
    return p.get("first_name") or (("@" + p.get("username")) if p.get("username") else str(p.get("telegram_id", "?")))


def defence_stats():
    units_cfg = settings().get("units", {})
    totals = {key: 0 for key in INFANTRY_UNITS | CAVALRY_UNITS}
    rows = []
    village_count = 0
    for p in players().values():
        if not isinstance(p, dict):
            continue
        inf = cav = 0
        per_unit = {key: 0 for key in totals}
        player_villages = []
        for v in p.get("villages", []):
            v_inf = v_cav = 0
            for key, raw in (v.get("troops") or {}).items():
                if key not in totals:
                    continue
                try:
                    amount = max(0, int(raw or 0))
                except (TypeError, ValueError):
                    amount = 0
                totals[key] += amount
                per_unit[key] += amount
                if key in INFANTRY_UNITS:
                    inf += amount; v_inf += amount
                else:
                    cav += amount; v_cav += amount
            if v_inf or v_cav:
                village_count += 1
                player_villages.append((v.get("coordinates", "?"), v_inf, v_cav))
        if inf or cav:
            rows.append({"id": int(p.get("telegram_id", 0) or 0), "name": player_name(p), "inf": inf, "cav": cav, "score": inf + cav * 2, "units": per_unit, "villages": player_villages})
    rows.sort(key=lambda x: (-x["score"], x["name"].lower()))
    return totals, rows, village_count, units_cfg


def alliance_def_text():
    totals, rows, village_count, units_cfg = defence_stats()
    inf = sum(totals.get(k, 0) for k in INFANTRY_UNITS)
    cav = sum(totals.get(k, 0) for k in CAVALRY_UNITS)
    score = inf + cav * 2
    total_troops = inf + cav
    lines = ["<b>🛡 ОБОРОНА АЛЬЯНСА</b>", "", f"👥 Игроков с дефом: <b>{len(rows)}</b>", f"🏘 Деф-деревень: <b>{village_count}</b>", "", f"🛡 Рейтинг дефа: <b>{fmt_num(score)}</b>", f"🚶 Пехота: <b>{fmt_num(inf)}</b> ({inf * 100 / total_troops:.1f}%)" if total_troops else "🚶 Пехота: <b>0</b>", f"🐎 Конница: <b>{fmt_num(cav)}</b> ({cav * 100 / total_troops:.1f}%)" if total_troops else "🐎 Конница: <b>0</b>", "", "<b>По юнитам:</b>"]
    for key in ("phalanx", "druidrider", "haeduan", "spearman", "paladin", "legionnaire", "praetorian", "equites_caesaris"):
        lines.append(f"{units_cfg.get(key, {}).get('name', key)} — <b>{fmt_num(totals.get(key, 0))}</b>")
    lines += ["", "ℹ️ Рейтинг: пехота ×1, конница ×2.", "⚠️ Расчёт по войскам, указанным игроками в настройках."]
    return "\n".join(lines)


def alliance_def_kb():
    return kb([[{"text": "🏆 Рейтинг деферов", "callback_data": "def_rank"}], [{"text": "⬅️ Мои настройки", "callback_data": "settings"}]])


def defence_rank_text():
    _, rows, _, _ = defence_stats()
    lines = ["<b>🏆 РЕЙТИНГ ДЕФЕРОВ</b>", "", "Рейтинг = пехота ×1 + конница ×2", ""]
    if not rows:
        lines.append("Пока никто не указал деф.")
    for i, row in enumerate(rows, 1):
        lines.append(f"{i}. <b>{row['name']}</b> — {fmt_num(row['score'])} 🛡")
    return "\n".join(lines)


def defence_rank_kb():
    _, rows, _, _ = defence_stats()
    buttons = [[{"text": f"{i}. {row['name']} — {fmt_num(row['score'])}", "callback_data": f"def_player:{row['id']}"}] for i, row in enumerate(rows, 1)]
    buttons.append([{"text": "⬅️ Общая армия", "callback_data": "alliance_def"}])
    return kb(buttons)


def defence_player_text(telegram_id):
    _, rows, _, units_cfg = defence_stats()
    row = next((r for r in rows if r["id"] == telegram_id), None)
    if not row:
        return "Данные игрока не найдены."
    place = rows.index(row) + 1
    lines = [f"<b>👤 {row['name']}</b>", "", f"🏆 Место: <b>{place} из {len(rows)}</b>", f"🛡 Рейтинг: <b>{fmt_num(row['score'])}</b>", f"🚶 Пехота: <b>{fmt_num(row['inf'])}</b>", f"🐎 Конница: <b>{fmt_num(row['cav'])}</b>", "", "<b>По юнитам:</b>"]
    for key in ("phalanx", "druidrider", "haeduan", "spearman", "paladin", "legionnaire", "praetorian", "equites_caesaris"):
        amount = row["units"].get(key, 0)
        if amount:
            lines.append(f"{units_cfg.get(key, {}).get('name', key)} — <b>{fmt_num(amount)}</b>")
    lines += ["", "<b>По деревням:</b>"]
    for coords, inf, cav in row["villages"]:
        lines.append(f"🏘 <b>{coords}</b> — 🚶 {fmt_num(inf)} · 🐎 {fmt_num(cav)}")
    return "\n".join(lines)


def villages_kb(player, prefix="village"):
    rows = [[{"text": f"{i+1}. {v.get('coordinates', '?')}", "callback_data": f"{prefix}:{i}"}] for i, v in enumerate(player.get("villages", []))]
    rows.append([{"text": "➕ Добавить деревню", "callback_data": "add_village"}])
    rows.append([{"text": "⬅️ Назад", "callback_data": "settings"}])
    return kb(rows)


def unit_text(v, player):
    units = settings().get("units", {})
    lines = [f"<b>🏘 Деревня {v.get('coordinates')}</b>", f"Арена: {v.get('arena', 0)}", "", "<b>Войска:</b>"]
    for key in allowed_units(player):
        unit = units.get(key)
        if not unit:
            continue
        amount = int(v.get("troops", {}).get(key, 0) or 0)
        if amount:
            lines.append(f"{unit['name']}: <b>{amount}</b> — {unit['speed']} полей/ч")
    if len(lines) == 4:
        lines.append("пока не указаны")
    if (v.get("hero") or {}).get("present"):
        lines += ["", "🦸 <b>Герой находится в этой деревне</b>"]
    return "\n".join(lines)


def unit_keyboard(index, player):
    rows = []
    units = settings().get("units", {})
    for key in allowed_units(player):
        unit = units.get(key)
        if unit:
            rows.append([{"text": unit["name"], "callback_data": f"unit:{index}:{key}"}])
    rows += [
        [{"text": "✏️ Координаты", "callback_data": f"coords:{index}"}, {"text": "✏️ Арена", "callback_data": f"arena:{index}"}],
        [{"text": "🦸 Герой и инвентарь", "callback_data": f"hero:{index}"}],
        [{"text": "⬅️ Назад", "callback_data": "villages"}],
    ]
    return kb(rows)


def hero_text(v, player):
    inv = hero_inventory(player)
    return (
        f"<b>🦸 Герой — {v.get('coordinates')}</b>\n\n"
        f"Герой находится здесь: <b>{'да' if (v.get('hero') or {}).get('present') else 'нет'}</b>\n\n"
        "<b>🎒 Доступно в инвентаре:</b>\n"
        f"🚩 Штандарты: <b>{', '.join('+'+str(x)+'%' for x in inv['standards']) or 'нет'}</b>\n"
        f"🥾 Сапоги: <b>{', '.join('+'+str(x)+'%' for x in inv['boots']) or 'нет'}</b>\n"
        f"🗺 Карты: <b>{', '.join('+'+str(x)+'%' for x in inv['maps']) or 'нет'}</b>\n\n"
        "Нажатие на предмет добавляет или убирает его из инвентаря."
    )


def hero_keyboard(idx, player):
    inv = hero_inventory(player)
    def mark(kind, value, icon):
        return f"{'✅' if value in inv[kind] else '▫️'} {icon} +{value}%"
    return kb([
        [{"text": "📍 Герой здесь / убрать", "callback_data": f"hero_present:{idx}"}],
        [{"text": mark("standards", 15, "🚩"), "callback_data": f"hinv:{idx}:standards:15"},
         {"text": mark("standards", 20, "🚩"), "callback_data": f"hinv:{idx}:standards:20"},
         {"text": mark("standards", 25, "🚩"), "callback_data": f"hinv:{idx}:standards:25"}],
        [{"text": mark("boots", 25, "🥾"), "callback_data": f"hinv:{idx}:boots:25"},
         {"text": mark("boots", 50, "🥾"), "callback_data": f"hinv:{idx}:boots:50"},
         {"text": mark("boots", 75, "🥾"), "callback_data": f"hinv:{idx}:boots:75"}],
        [{"text": mark("maps", 30, "🗺"), "callback_data": f"hinv:{idx}:maps:30"},
         {"text": mark("maps", 40, "🗺"), "callback_data": f"hinv:{idx}:maps:40"},
         {"text": mark("maps", 50, "🗺"), "callback_data": f"hinv:{idx}:maps:50"}],
        [{"text": "⬅️ Назад", "callback_data": f"village:{idx}"}],
    ])

def parse_coords(value):
    try:
        parts = value.split()
        if len(parts) != 2:
            return None
        x, y = int(parts[0]), int(parts[1])
        if -200 <= x <= 200 and -200 <= y <= 200:
            return f"{x} {y}"
    except (ValueError, TypeError):
        pass
    return None


def to_int(value):
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def process_text(message):
    user = message.get("from", {})
    text = (message.get("text") or "").strip()
    is_private = message.get("chat", {}).get("type") == "private"
    if not text or (not is_private and not in_def_thread(message)):
        return
    data, player = get_player(user)
    state = player.get("state")
    chat_id = message["chat"]["id"]
    if text.startswith("/start") and is_private:
        player["state"] = None
        player["private_chat_id"] = chat_id
        player["private_notifications"] = True
        save_players(data)
        send(chat_id, settings_text(player), settings_kb(is_owner(user)), thread_id=None)
        return
    if text.startswith("/def") and not is_private:
        player["state"] = None
        save_players(data)
        send(chat_id, "<b>🛡 ЦЕНТР ДЕФА</b>\n\nВыберите раздел:", main_menu())
        return
    if not state:
        return
    if state == "add_village_coords":
        coords = parse_coords(text)
        if coords is None:
            send(chat_id, "Неверный формат. Введите координаты через пробел, например: <code>45 -62</code>", force_reply=True)
            return
        try:
            from defence_requests import find_target, race_from_village
            village, _ = find_target(coords)
            detected_race = race_from_village(village) if village else None
        except Exception:
            detected_race = None
        if detected_race is None:
            send(chat_id, "❌ Не удалось определить расу по этой деревне в последнем слепке map.sql. Проверьте координаты.", force_reply=True)
            return
        current_race = player.get("race")
        if current_race and current_race != detected_race:
            send(chat_id, "❌ Координаты этой деревни принадлежат другой расе. Проверьте координаты.", force_reply=True)
            return
        player["race"] = detected_race
        player["state"] = {"type": "add_village_arena", "coordinates": coords}
        save_players(data)
        send(chat_id, "Введите уровень Арены (0–20):", force_reply=True)
        return
    typ = state.get("type") if isinstance(state, dict) else None
    if typ == "add_village_arena":
        arena = to_int(text)
        if arena is None or not 0 <= arena <= 20:
            send(chat_id, "Введите целое число от 0 до 20.", force_reply=True)
            return
        player["villages"].append({"coordinates": state["coordinates"], "arena": arena, "troops": {}, "hero": {"present": False}})
        idx = len(player["villages"]) - 1
        player["state"] = None
        save_players(data)
        send(chat_id, unit_text(player["villages"][idx], player), unit_keyboard(idx, player))
    elif typ == "unit_amount":
        amount = to_int(text)
        if amount is None or amount < 0:
            send(chat_id, "Введите целое число 0 или больше.", force_reply=True)
            return
        idx, unit = state["index"], state["unit"]
        if idx >= len(player["villages"]):
            return
        if unit not in allowed_units(player):
            player["state"] = None
            save_players(data)
            send(chat_id, "Этот юнит не доступен для выбранной расы.", unit_keyboard(idx, player))
            return
        player["villages"][idx].setdefault("troops", {})[unit] = amount
        player["state"] = None
        save_players(data)
        send(chat_id, unit_text(player["villages"][idx], player), unit_keyboard(idx, player))
    elif typ == "subs":
        ids = [x.strip() for x in text.split(",") if x.strip()]
        if len(ids) > 2 or any(to_int(x) is None or to_int(x) <= 0 for x in ids):
            send(chat_id, "Введите до двух Telegram ID через запятую. Например: <code>111111111,222222222</code>", force_reply=True)
            return
        player["substitutes"] = [int(x) for x in ids]
        player["state"] = None
        save_players(data)
        send(chat_id, settings_text(player), settings_kb(is_owner(user)))
    elif typ in ("coords", "arena"):
        idx = state["index"]
        if idx >= len(player["villages"]):
            return
        if typ == "coords":
            coords = parse_coords(text)
            if coords is None:
                send(chat_id, "Неверный формат. Введите координаты через пробел, например: <code>45 -62</code>", force_reply=True)
                return
            player["villages"][idx]["coordinates"] = coords
        else:
            value = to_int(text)
            if value is None or not 0 <= value <= 20:
                send(chat_id, "Введите целое число от 0 до 20.", force_reply=True)
                return
            player["villages"][idx]["arena"] = value
        player["state"] = None
        save_players(data)
        send(chat_id, unit_text(player["villages"][idx], player), unit_keyboard(idx, player))


def callback_query(q):
    message = q.get("message", {})
    is_private = message.get("chat", {}).get("type") == "private"
    if not is_private and message.get("message_thread_id") != THREAD_ID:
        return
    user = q.get("from", {})
    data, player = get_player(user)
    chat_id, msg_id = message["chat"]["id"], message["message_id"]
    action = q.get("data", "")
    answer_callback(q["id"])

    if action == "menu":
        edit(chat_id, msg_id, "<b>🛡 ЦЕНТР ДЕФА</b>\n\nВыберите раздел:", main_menu())
    elif action == "my_id":
        send(chat_id, f"🆔 Ваш Telegram ID: <code>{user.get('id')}</code>")
    elif action == "settings":
        if not is_private:
            private_chat_id = player.get("private_chat_id")
            if private_chat_id:
                send_private(private_chat_id, settings_text(player), settings_kb())
                answer_callback(q["id"], "Настройки отправлены вам в личные сообщения")
            else:
                answer_callback(q["id"], "Сначала откройте личный чат с ботом и нажмите /start")
            return
        edit(chat_id, msg_id, settings_text(player), settings_kb(is_owner(user)))
    elif not is_private and action not in ("menu", "request_def"):
        answer_callback(q["id"], "Личные настройки изменяются только в личном чате")
        return
    elif action in ("alliance_def", "def_rank") or action.startswith("def_player:"):
        if not is_private or not is_owner(user):
            answer_callback(q["id"], "Доступ запрещён")
            return
        if action == "alliance_def":
            edit(chat_id, msg_id, alliance_def_text(), alliance_def_kb())
        elif action == "def_rank":
            edit(chat_id, msg_id, defence_rank_text(), defence_rank_kb())
        else:
            telegram_id = int(action.split(":", 1)[1])
            edit(chat_id, msg_id, defence_player_text(telegram_id), kb([[{"text": "⬅️ Рейтинг", "callback_data": "def_rank"}]]))
    elif action == "race_menu":
        edit(chat_id, msg_id, "<b>🧬 Выбор расы</b>\n\nВыберите вашу расу. После смены расы список доступных юнитов во всех ваших деревнях будет автоматически отфильтрован.", race_keyboard())
    elif action.startswith("race:"):
        race = action.split(":", 1)[1]
        if race not in RACES:
            return
        player["race"] = race
        allowed = set(allowed_units(player))
        for village in player.get("villages", []):
            troops = village.setdefault("troops", {})
            village["troops"] = {key: value for key, value in troops.items() if key in allowed}
        player["state"] = None
        save_players(data)
        edit(chat_id, msg_id, settings_text(player), settings_kb())
    elif action == "villages":
        edit(chat_id, msg_id, "<b>🏘 Мои деревни</b>\n\nВыберите деревню:", villages_kb(player))
    elif action == "add_village":
        player["state"] = "add_village_coords"
        save_players(data)
        send(chat_id, "Введите координаты новой деревни через пробел, например <code>45 -62</code>:", force_reply=True)
    elif action == "edit_village":
        edit(chat_id, msg_id, "Выберите деревню:", villages_kb(player))
    elif action == "delete_village":
        rows = [[{"text": f"🗑 {v.get('coordinates')}", "callback_data": f"delv:{i}"}] for i, v in enumerate(player.get("villages", []))]
        rows.append([{"text": "⬅️ Назад", "callback_data": "settings"}])
        edit(chat_id, msg_id, "Выберите деревню для удаления:", kb(rows))
    elif action.startswith("delv:"):
        idx = int(action.split(":", 1)[1])
        if 0 <= idx < len(player["villages"]):
            player["villages"].pop(idx)
            save_players(data)
        edit(chat_id, msg_id, settings_text(player), settings_kb())
    elif action.startswith("village:"):
        idx = int(action.split(":", 1)[1])
        if 0 <= idx < len(player.get("villages", [])):
            edit(chat_id, msg_id, unit_text(player["villages"][idx], player), unit_keyboard(idx, player))
    elif action.startswith("unit:"):
        _, idx, unit = action.split(":", 2)
        idx = int(idx)
        if idx < len(player["villages"]):
            if unit not in allowed_units(player) or unit not in settings().get("units", {}):
                edit(chat_id, msg_id, unit_text(player["villages"][idx], player), unit_keyboard(idx, player))
                return
            player["state"] = {"type": "unit_amount", "index": idx, "unit": unit}
            save_players(data)
            name = settings()["units"][unit]["name"]
            current = player["villages"][idx].get("troops", {}).get(unit, 0)
            send(chat_id, f"Введите количество <b>{name}</b>. Сейчас: <b>{current}</b>", force_reply=True)
    elif action.startswith("coords:"):
        idx = int(action.split(":", 1)[1])
        if idx < len(player["villages"]):
            player["state"] = {"type": "coords", "index": idx}
            save_players(data)
            send(chat_id, "Введите новые координаты через пробел, например <code>45 -62</code>:", force_reply=True)
    elif action.startswith("arena:"):
        idx = int(action.split(":", 1)[1])
        if idx < len(player["villages"]):
            player["state"] = {"type": "arena", "index": idx}
            save_players(data)
            send(chat_id, "Введите уровень Арены (0–20):", force_reply=True)
    elif action.startswith("hero:"):
        idx = int(action.split(":", 1)[1])
        if idx < len(player["villages"]):
            player["villages"][idx].setdefault("hero", {"present": False})
            edit(chat_id, msg_id, hero_text(player["villages"][idx], player), hero_keyboard(idx, player))
    elif action.startswith("hero_present:"):
        idx = int(action.split(":", 1)[1])
        if idx < len(player["villages"]):
            currently_here = bool((player["villages"][idx].get("hero") or {}).get("present"))
            # There is only one hero per account.
            for village in player.get("villages", []):
                village.setdefault("hero", {})["present"] = False
            if not currently_here:
                player["villages"][idx]["hero"]["present"] = True
            save_players(data)
            edit(chat_id, msg_id, hero_text(player["villages"][idx], player), hero_keyboard(idx, player))
    elif action.startswith("hinv:"):
        _, idx_s, kind, value_s = action.split(":")
        idx, value = int(idx_s), int(value_s)
        if kind not in ("standards", "boots", "maps") or idx >= len(player["villages"]):
            return
        inv = hero_inventory(player)
        if value in inv[kind]:
            inv[kind].remove(value)
        else:
            inv[kind].append(value)
            inv[kind].sort()
        save_players(data)
        edit(chat_id, msg_id, hero_text(player["villages"][idx], player), hero_keyboard(idx, player))
    elif action == "subs":
        player["state"] = {"type": "subs"}
        save_players(data)
        send(chat_id, "Введите Telegram ID до двух заместителей через запятую.\nПример: <code>111111111,222222222</code>", force_reply=True)


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
                    callback_query(update["callback_query"])
                elif "message" in update:
                    process_text(update["message"])
        except Exception as exc:
            print("Polling error:", exc, flush=True)
            time.sleep(5)


if __name__ == "__main__":
    run()