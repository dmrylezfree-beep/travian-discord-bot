import html
import os
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import defence_bot as bot
from travian_bot import parse_map_data, SERVER_URL

SNAPSHOT_DIR = Path("data/snapshots")
STATE_FILE = bot.DATA_DIR / "state.json"
SERVER_TZ = ZoneInfo("Europe/London")
_snapshot_cache_path = None
_snapshot_cache = None

_original_process_text = bot.process_text
_original_callback_query = bot.callback_query


def load_state():
    return bot.load_json(STATE_FILE, {})


def save_state(state):
    bot.save_json(STATE_FILE, state)
    bot.persist_data()


def request_menu():
    return bot.kb([
        [{"text": "➕ Запросить деф", "callback_data": "request_def"}],
        [{"text": "🛡 Отправить деф", "callback_data": "send_def"}],
        [{"text": "⚙️ Мои настройки", "callback_data": "settings"}],
    ])


def latest_snapshot():
    global _snapshot_cache_path, _snapshot_cache
    paths = sorted(SNAPSHOT_DIR.glob("*/**/map_*.sql"), key=lambda p: p.name, reverse=True)
    if not paths:
        return None, None
    path = paths[0]
    if _snapshot_cache_path == path and _snapshot_cache is not None:
        return path, _snapshot_cache
    try:
        raw = path.read_text(encoding="utf-8")
        villages, _ = parse_map_data(raw)
    except Exception as exc:
        print(f"Defence snapshot parse error: {exc}", flush=True)
        return path, None
    _snapshot_cache_path = path
    _snapshot_cache = villages
    return path, villages


def find_target(coords):
    parts = coords.split()
    x, y = int(parts[0]), int(parts[1])
    path, villages = latest_snapshot()
    if villages is None:
        return None, path
    for village in villages.values():
        try:
            if int(village.get("x")) == x and int(village.get("y")) == y:
                return village, path
        except (TypeError, ValueError):
            continue
    return None, path


def parse_attack_time(text):
    try:
        return datetime.strptime(text, "%d.%m.%Y %H:%M:%S")
    except ValueError:
        return None


def parse_attack_clock(text):
    try:
        return datetime.strptime(text, "%H:%M:%S").time()
    except ValueError:
        return None


def village_link(x, y):
    url = f"{SERVER_URL}/karte.php?x={x}&y={y}"
    return f'<a href="{html.escape(url, quote=True)}">{x} {y}</a>'


def map_distance(x1, y1, x2, y2):
    size = int(bot.settings().get("map_size", 401) or 401)
    dx = min(abs(int(x2) - int(x1)), size - abs(int(x2) - int(x1)))
    dy = min(abs(int(y2) - int(y1)), size - abs(int(y2) - int(y1)))
    return (dx * dx + dy * dy) ** 0.5


def format_duration(seconds):
    total = max(0, int(round(seconds)))
    hours, rem = divmod(total, 3600)
    minutes, secs = divmod(rem, 60)
    if hours:
        return f"{hours}ч {minutes:02d}м"
    if minutes:
        return f"{minutes}м {secs:02d}с"
    return f"{secs}с"


def travel_seconds(distance, unit_speed, village, with_hero=False):
    cfg = bot.settings()
    world_speed = float(cfg.get("world_speed_multiplier", 1.0) or 1.0)
    arena = int(village.get("arena", 0) or 0)
    hero = village.get("hero", {}) or {}

    base_speed = float(unit_speed) * world_speed

    # Standard affects the whole route, but only when the hero travels with
    # the troops. The target of a defence request is assumed to be an ally.
    standard = float(hero.get("standard_bonus", 0) or 0) if with_hero and hero.get("present") else 0.0

    # Boots and Tournament Square bonuses apply only after the first 20 fields.
    boots = float(hero.get("boots_bonus", 0) or 0) if with_hero and hero.get("present") else 0.0
    after20_bonus = (arena * 0.20) + boots

    first_leg = min(distance, 20.0)
    seconds = first_leg * 3600.0 / (base_speed * (1.0 + standard))

    if distance > 20:
        second_leg = distance - 20.0
        seconds += second_leg * 3600.0 / (
            base_speed * (1.0 + standard) * (1.0 + after20_bonus)
        )
    return seconds


CAVALRY_UNITS = {
    "druidrider", "haeduan", "theutates_thunder",
    "equites_legati", "equites_imperatoris", "equites_caesaris",
    "paladin", "teutonic_knight",
}


TROOP_SLOTS = {
    "gaul": {
        "phalanx": 1, "swordsman": 2, "pathfinder": 3,
        "theutates_thunder": 4, "druidrider": 5, "haeduan": 6,
    },
    "teuton": {
        "clubswinger": 1, "spearman": 2, "axeman": 3,
        "scout": 4, "paladin": 5, "teutonic_knight": 6,
    },
    "roman": {
        "legionnaire": 1, "praetorian": 2, "imperian": 3,
        "equites_legati": 4, "equites_imperatoris": 5, "equites_caesaris": 6,
    },
}


def unit_value(unit_key):
    return 2 if unit_key in CAVALRY_UNITS else 1


def request_datetime(req):
    try:
        return datetime.strptime(req["attack_time"], "%Y-%m-%d %H:%M:%S")
    except (KeyError, TypeError, ValueError):
        return None


def source_village_units(player, village, req):
    target_x, target_y = int(req["target_x"]), int(req["target_y"])
    parts = str(village.get("coordinates", "")).split()
    if len(parts) != 2:
        return []
    try:
        source_x, source_y = int(parts[0]), int(parts[1])
    except ValueError:
        return []

    distance = map_distance(source_x, source_y, target_x, target_y)
    units = bot.settings().get("units", {})
    result = []
    for unit_key in bot.allowed_units(player):
        amount = int(village.get("troops", {}).get(unit_key, 0) or 0)
        if amount <= 0:
            continue
        unit = units.get(unit_key) or {}
        speed = float(unit.get("speed", 0) or 0)
        if speed <= 0:
            continue

        no_hero_seconds = travel_seconds(distance, speed, village, with_hero=False)
        hero_available = bool((village.get("hero") or {}).get("present"))
        hero_seconds = travel_seconds(distance, speed, village, with_hero=True) if hero_available else None
        result.append({
            "key": unit_key,
            "name": unit.get("name", unit_key),
            "amount": amount,
            "speed": speed,
            "distance": distance,
            "no_hero_seconds": no_hero_seconds,
            "hero_seconds": hero_seconds,
            "value": unit_value(unit_key),
        })
    return result


def source_village_status(player, village, req):
    attack = request_datetime(req)
    if attack is None:
        return "⚪", "нет времени"
    units = source_village_units(player, village, req)
    if not units:
        return "⚪", "нет указанных войск"

    now = datetime.now(SERVER_TZ).replace(tzinfo=None)
    remaining = (attack - now).total_seconds()
    best = None

    for item in units:
        for with_hero, seconds in ((False, item["no_hero_seconds"]), (True, item["hero_seconds"])):
            if seconds is None:
                continue
            if best is None or seconds < best["seconds"]:
                best = {
                    "seconds": seconds,
                    "name": item["name"],
                    "with_hero": with_hero,
                    "arrival": now + timedelta(seconds=seconds),
                }

    if best is None:
        return "⚪", "нет доступных войск"

    if best["seconds"] <= remaining:
        hero_text = " +герой" if best["with_hero"] else ""
        return "🟢", f"{best['name']}{hero_text} • {best['arrival'].strftime('%H:%M:%S')}"
    return "🔴", f"ближайшее: {best['name']} • {format_duration(best['seconds'])}"


def send_def_requests_keyboard(requests):
    rows = []
    for req in requests:
        if req.get("status") != "active":
            continue
        rows.append([{
            "text": f"#{req['id']} • {req['target_x']}|{req['target_y']} • {req['attack_time_display']}",
            "callback_data": f"send_req:{req['id']}",
        }])
    rows.append([{"text": "⬅️ Назад", "callback_data": "menu"}])
    return bot.kb(rows)


def send_def_sources_keyboard(player, req):
    rows = []
    for idx, village in enumerate(player.get("villages", [])):
        icon, status = source_village_status(player, village, req)
        rows.append([{
            "text": f"{icon} {village.get('coordinates', '?')} — {status}",
            "callback_data": f"send_village:{req['id']}:{idx}",
        }])
    if (player.get("state") or {}).get("selected"):
        rows.append([{"text": "🚀 Завершить выбор", "callback_data": f"send_finish:{req['id']}"}])
    rows.append([{"text": "⬅️ К заявкам", "callback_data": "send_def"}])
    return bot.kb(rows)


def send_def_village_text(player, req, idx):
    village = player["villages"][idx]
    attack = request_datetime(req)
    target = f"{req['target_x']}|{req['target_y']}"
    now = datetime.now(SERVER_TZ).replace(tzinfo=None)
    remaining = (attack - now).total_seconds() if attack else 0

    lines = [
        "<b>🛡 ОТПРАВКА ДЕФА</b>",
        "",
        f"📍 Откуда: <b>{html.escape(str(village.get('coordinates', '?')))}</b>",
        f"📍 Куда: <b>{target}</b>",
        f"⚔️ Атака: <b>{req.get('attack_time_display', '?')}</b>",
        f"⏳ Осталось: <b>{format_duration(remaining)}</b>",
        "",
        "Выберите войско. Время прибытия считается с учётом Арены и сохранённых бонусов героя.",
        "🟢 — успевает без героя или с героем.",
        "🔴 — не успевает.",
    ]
    if attack is None or remaining <= 0:
        lines.append("")
        lines.append("⚠️ Время атаки уже прошло.")
        return "\n".join(lines)

    units = source_village_units(player, village, req)
    settings_units = bot.settings().get("units", {})
    for item in units:
        name = item["name"]
        no_hero_arrival = now + timedelta(seconds=item["no_hero_seconds"])
        text = f"• {name}: <b>{item['amount']}</b> — без героя {no_hero_arrival.strftime('%H:%M:%S')}"
        if item["hero_seconds"] is not None:
            hero_arrival = now + timedelta(seconds=item["hero_seconds"])
            text += f" | с героем {hero_arrival.strftime('%H:%M:%S')}"
        lines.append(text)
    if not units:
        lines.append("В этой деревне не указаны войска для отправки.")

    return "\n".join(lines)


def send_def_village_keyboard(player, req, idx):
    village = player["villages"][idx]
    state = player.get("state") or {}
    send_state = state.get("send_state") or {}
    selected = send_state.get("selected", {}).get(str(idx), {})
    hero = bool(selected.get("with_hero", False))

    rows = []
    units = source_village_units(player, village, req)
    now = datetime.now(SERVER_TZ).replace(tzinfo=None)
    attack = request_datetime(req)
    for item in units:
        # Selecting a unit does not yet send anything. The amount is entered next.
        seconds = item["hero_seconds"] if hero and item["hero_seconds"] is not None else item["no_hero_seconds"]
        arrival = now + timedelta(seconds=seconds)
        ok = attack is not None and arrival <= attack
        icon = "🟢" if ok else "🔴"
        rows.append([{
            "text": f"{icon} {item['name']} ({item['amount']}) → {arrival.strftime('%H:%M:%S')}",
            "callback_data": f"send_unit:{req['id']}:{idx}:{item['key']}",
        }])

    if (village.get("hero") or {}).get("present"):
        rows.append([{
            "text": f"🦸 С героем: {'ДА' if hero else 'НЕТ'}",
            "callback_data": f"send_hero:{req['id']}:{idx}",
        }])

    if selected.get("troops"):
        rows.append([{"text": "🚀 Завершить выбор", "callback_data": f"send_finish:{req['id']}"}])
    rows.append([{"text": "⬅️ К деревням", "callback_data": f"send_req:{req['id']}"}])
    return bot.kb(rows)


def send_def_state(player, req_id):
    state = player.get("state") or {}
    if state.get("type") != "send_def":
        return None
    if int(state.get("request_id", -1)) != int(req_id):
        return None
    return state


def send_def_summary(player, req):
    state = send_def_state(player, req["id"]) or {}
    selected = state.get("selected", {})
    if not selected:
        return "Пока ничего не выбрано."

    units = bot.settings().get("units", {})
    lines = ["<b>Выбранный деф:</b>"]
    total = 0
    for idx_str, item in selected.items():
        idx = int(idx_str)
        village = player["villages"][idx]
        troops = item.get("troops", {})
        parts = []
        score = 0
        for key, amount in troops.items():
            name = units.get(key, {}).get("name", key)
            parts.append(f"{name}: {amount}")
            score += int(amount) * unit_value(key)
        total += score
        lines.append(f"🏘 {village.get('coordinates', '?')}: " + ", ".join(parts) + f" — <b>{score}</b> очк.")
    lines.append("")
    lines.append(f"🛡 Всего: <b>{total}</b> / {req['required_def']} очков")
    return "\n".join(lines)


def send_def_confirm_keyboard(req_id):
    return bot.kb([
        [{"text": "🚀 Получить ссылки на отправку", "callback_data": f"send_links:{req_id}"}],
        [{"text": "⬅️ Выбрать ещё войска", "callback_data": f"send_req:{req_id}"}],
        [{"text": "❌ Отмена", "callback_data": "request_cancel"}],
    ])


def build_reinforcement_link(req, player, idx):
    from urllib.parse import urlencode

    village = player["villages"][idx]
    state = send_def_state(player, req["id"]) or {}
    item = (state.get("selected", {}) or {}).get(str(idx), {})
    troops = item.get("troops", {})
    params = [
        ("id", "39"), ("tt", "2"),
        ("x", str(req["target_x"])), ("y", str(req["target_y"])),
        ("eventType", "2"),
    ]
    race = player.get("race")
    for key, amount in troops.items():
        slot = TROOP_SLOTS.get(race, {}).get(key)
        if slot:
            params.append((f"troop[t{slot}]", str(int(amount))))
    if item.get("with_hero"):
        params.append(("troop[t11]", "1"))
    return f"{SERVER_URL}/build.php?" + urlencode(params)


def send_links_text(player, req):
    state = send_def_state(player, req["id"]) or {}
    selected = state.get("selected", {})
    if not selected:
        return "Сначала выберите хотя бы одну деревню и войска."

    lines = [
        "<b>🚀 ОТПРАВКА ДЕФА</b>",
        "",
        f"📍 Цель: {village_link(req['target_x'], req['target_y'])}",
        f"⚔️ Прибыть до: <b>{req['attack_time_display']}</b>",
        "",
        "Откройте ссылку из нужной деревни. Она откроет Пункт сбора с выбранными войсками и типом «Подкрепление». Перед подтверждением обязательно проверьте состав и время прибытия.",
    ]
    return "\n".join(lines)


def send_links_keyboard(player, req):
    state = send_def_state(player, req["id"]) or {}
    rows = []
    for idx_str in state.get("selected", {}):
        idx = int(idx_str)
        village = player["villages"][idx]
        rows.append([{
            "text": f"🚀 {village.get('coordinates', '?')}",
            "url": build_reinforcement_link(req, player, idx),
        }])
    rows.append([{"text": "⬅️ К выбору войск", "callback_data": f"send_req:{req['id']}"}])
    return bot.kb(rows)


def request_text(req):
    return (
        f"<b>🛡 ЗАПРОС НА ДЕФ #{req['id']}</b>\n\n"
        f"📍 Деревня: {village_link(req['target_x'], req['target_y'])}\n"
        f"👤 Игрок: <b>{html.escape(req['target_player'])}</b>\n"
        f"⚔️ Атака: <b>{req['attack_time_display']}</b>\n"
        f"🛡 Требуется: <b>{req['required_def']}</b> очков дефа\n\n"
        "Деф должен прибыть <b>ДО</b> указанного времени."
    )


def confirm_keyboard():
    return bot.kb([
        [{"text": "✅ Создать заявку", "callback_data": "request_confirm"}],
        [{"text": "❌ Отмена", "callback_data": "request_cancel"}],
    ])


def date_keyboard():
    now = datetime.now(SERVER_TZ)
    today = now.strftime("%d.%m")
    tomorrow = (now + timedelta(days=1)).strftime("%d.%m")
    return bot.kb([
        [{"text": f"📅 Сегодня — {today}", "callback_data": "request_date_today"}],
        [{"text": f"📅 Завтра — {tomorrow}", "callback_data": "request_date_tomorrow"}],
        [{"text": "❌ Отмена", "callback_data": "request_cancel"}],
    ])


def request_summary(player):
    state = player.get("state", {})
    return (
        "<b>🛡 ЗАПРОС НА ДЕФ</b>\n\n"
        f"📍 Деревня: {village_link(state['target_x'], state['target_y'])}\n"
        f"👤 Игрок: <b>{html.escape(state['target_player'])}</b>\n"
        f"⚔️ Атака: <b>{state['attack_time_display']}</b>\n"
        f"🛡 Требуется: <b>{state['required_def']}</b> очков дефа\n\n"
        "Пехота = 1\n"
        "Конница = 2\n\n"
        "Деф должен прибыть <b>ДО</b> указанного времени.\n\n"
        "Всё верно?"
    )


def next_request_id(requests):
    ids = [int(r.get("id", 0)) for r in requests if str(r.get("id", "")).isdigit()]
    return max(ids, default=0) + 1


def save_request(request):
    requests = bot.load_json(bot.REQUESTS_FILE, [])
    if not isinstance(requests, list):
        requests = []
    requests.append(request)
    bot.save_json(bot.REQUESTS_FILE, requests)
    bot.persist_data()
    return request


def start_request(chat_id, player, data):
    player["state"] = {"type": "request_target_coords"}
    bot.save_players(data)
    bot.send(
        chat_id,
        "<b>🛡 Запросить деф</b>\n\nВведите координаты деревни назначения.\nНапример: <code>45 -62</code>",
        force_reply=True,
    )


def active_requests_text(requests):
    now = datetime.now(SERVER_TZ).replace(tzinfo=None)
    active = []
    changed = False

    for req in requests:
        if req.get("status") != "active":
            continue
        try:
            attack = datetime.strptime(req["attack_time"], "%Y-%m-%d %H:%M:%S")
        except (KeyError, TypeError, ValueError):
            attack = None
        if attack is not None and attack <= now:
            req["status"] = "expired"
            changed = True
            continue
        active.append(req)

    active.sort(key=lambda r: r.get("attack_time", ""))

    lines = ["<b>🛡 ЦЕНТР ДЕФА</b>", "", "<b>📋 АКТИВНЫЕ ЗАЯВКИ</b>", ""]
    if not active:
        lines.append("Активных заявок нет.")
    else:
        for req in active:
            try:
                attack = datetime.strptime(req["attack_time"], "%Y-%m-%d %H:%M:%S")
                urgent = (attack - now).total_seconds() <= 30 * 60
            except (KeyError, TypeError, ValueError):
                urgent = False
            icon = "🔴" if urgent else "🟡"
            lines.extend([
                f"{icon} <b>#{req['id']}</b>",
                f"📍 {village_link(req['target_x'], req['target_y'])} — <b>{html.escape(req['target_player'])}</b>",
                f"⚔️ Атака: <b>{req['attack_time_display']}</b>",
                f"🛡 Требуется: <b>{req['required_def']}</b> очков",
                "",
            ])

    lines.append("Деф должен прибыть <b>ДО</b> времени атаки.")
    return "\n".join(lines), changed


def unpin_center(chat_id, message_id):
    if not chat_id or not message_id:
        return
    try:
        bot.tg(
            "unpinChatMessage",
            chat_id=chat_id,
            message_id=message_id,
        )
        print(f"Previous centre unpinned: {message_id}", flush=True)
    except Exception as exc:
        print(f"Previous centre unpin failed for {message_id}: {exc}", flush=True)


def refresh_center(chat_id=None, create_if_missing=False):
    state = load_state()
    center_chat_id = state.get("center_chat_id") or chat_id
    center_message_id = state.get("center_message_id")
    if center_chat_id is None:
        return False

    requests = bot.load_json(bot.REQUESTS_FILE, [])
    if not isinstance(requests, list):
        requests = []

    text, changed = active_requests_text(requests)
    if changed:
        bot.save_json(bot.REQUESTS_FILE, requests)
        bot.persist_data()

    if center_message_id:
        try:
            bot.edit(center_chat_id, center_message_id, text, request_menu())
            return True
        except Exception as exc:
            print(f"Centre edit failed, will recreate: {exc}", flush=True)
            # If the old centre cannot be edited, it must be unpinned before
            # creating a replacement, otherwise /def can accumulate pins.
            unpin_center(center_chat_id, center_message_id)

    if not create_if_missing:
        return False

    message = bot.send(center_chat_id, text, request_menu())
    center_message_id = message.get("message_id") if isinstance(message, dict) else None
    if not center_message_id:
        return False

    state["center_chat_id"] = int(center_chat_id)
    state["center_message_id"] = int(center_message_id)
    save_state(state)
    try:
        bot.tg("pinChatMessage", chat_id=center_chat_id, message_id=center_message_id, disable_notification=True)
    except Exception as exc:
        print(f"Pin centre failed: {exc}", flush=True)
    return True


def process_text(message):
    user = message.get("from", {})
    text = (message.get("text") or "").strip()
    if not text or not bot.in_def_thread(message):
        return

    data, player = bot.get_player(user)
    chat_id = message["chat"]["id"]
    state = player.get("state")

    if text.startswith("/start"):
        return
    if text.startswith("/def"):
        player["state"] = None
        bot.save_players(data)
        refresh_center(chat_id=chat_id, create_if_missing=True)
        return

    if not isinstance(state, dict):
        return _original_process_text(message)

    typ = state.get("type")
    if typ == "send_def_amount":
        required = bot.to_int(text)
        req_id = int(state.get("request_id", 0) or 0)
        idx = int(state.get("index", -1) or -1)
        unit_key = state.get("unit")
        if required is None or required <= 0:
            bot.send(chat_id, "Введите положительное количество войск.", force_reply=True)
            return

        requests = bot.load_json(bot.REQUESTS_FILE, [])
        req = next((r for r in requests if int(r.get("id", -1)) == req_id and r.get("status") == "active"), None)
        if req is None or idx < 0 or idx >= len(player.get("villages", [])):
            player["state"] = None
            bot.save_players(data)
            bot.send(chat_id, "❌ Заявка или деревня больше недоступна.", request_menu())
            return

        village = player["villages"][idx]
        available = int(village.get("troops", {}).get(unit_key, 0) or 0)
        if required > available:
            bot.send(chat_id, f"В этой деревне указано только <b>{available}</b> таких войск.", force_reply=True)
            return

        send_state = player.setdefault("state", {})
        selected = send_state.setdefault("selected", {})
        entry = selected.setdefault(str(idx), {"troops": {}, "with_hero": bool(send_state.get("with_hero", False))})
        entry["troops"][unit_key] = required

        # Recalculate the whole selected army from this village: mixed troops
        # travel at the speed of the slowest selected unit.
        attack = request_datetime(req)
        if attack is not None:
            distance = map_distance(*[int(x) for x in str(village.get("coordinates")).split()], req["target_x"], req["target_y"])
            speeds = []
            for key, amount in entry["troops"].items():
                if int(amount or 0) <= 0:
                    continue
                unit = bot.settings().get("units", {}).get(key, {})
                speeds.append(float(unit.get("speed", 0) or 0))
            if speeds:
                slowest = min(speeds)
                seconds = travel_seconds(distance, slowest, village, with_hero=bool(entry.get("with_hero")))
                arrival = datetime.now(SERVER_TZ).replace(tzinfo=None) + timedelta(seconds=seconds)
                if arrival > attack:
                    entry["troops"].pop(unit_key, None)
                    if not entry["troops"]:
                        selected.pop(str(idx), None)
                    bot.save_players(data)
                    bot.send(
                        chat_id,
                        f"❌ С таким составом деф из этой деревни прибывает <b>{arrival.strftime('%H:%M:%S')}</b>, "
                        f"а нужно до <b>{req['attack_time_display']}</b>. Выберите более быстрый состав.",
                        force_reply=False,
                    )
                    return

        player["state"]["type"] = "send_def"
        player["state"].pop("index", None)
        player["state"].pop("unit", None)
        bot.save_players(data)
        bot.send(chat_id, send_def_village_text(player, req, idx), send_def_village_keyboard(player, req, idx))
        return

    if not isinstance(state, dict):
        return _original_process_text(message)

    typ = state.get("type")
    if typ == "request_target_coords":
        coords = bot.parse_coords(text)
        if coords is None:
            bot.send(chat_id, "Неверный формат. Введите координаты через пробел, например: <code>45 -62</code>", force_reply=True)
            return
        village, path = find_target(coords)
        if village is None:
            if path is None:
                bot.send(chat_id, "❌ В репозитории не найден ни одного сохранённого слепка карты.", force_reply=True)
            else:
                bot.send(chat_id, f"❌ Деревня с координатами <code>{coords}</code> не найдена в последнем слепке карты (<code>{path.name}</code>).\n\nПроверьте координаты и попробуйте ещё раз.", force_reply=True)
            return
        player_name = str(village.get("player") or "Неизвестно")
        player["state"] = {
            "type": "request_attack_date",
            "target_coords": coords,
            "target_x": int(village["x"]),
            "target_y": int(village["y"]),
            "target_player": player_name,
        }
        bot.save_players(data)
        bot.send(
            chat_id,
            f"📍 Деревня: {village_link(village['x'], village['y'])}\n👤 Игрок: <b>{html.escape(player_name)}</b>\n\n📅 Выберите дату атаки:",
            date_keyboard(),
        )
        return

    if typ == "request_attack_time":
        # Backward compatibility for an unfinished old request.
        attack_time = parse_attack_time(text)
        if attack_time is None:
            bot.send(chat_id, "Неверный формат. Используйте: <code>17.09.2026 21:30:45</code>", force_reply=True)
            return
        player["state"]["attack_time"] = attack_time.strftime("%Y-%m-%d %H:%M:%S")
        player["state"]["attack_time_display"] = attack_time.strftime("%d.%m.%Y %H:%M:%S")
        player["state"]["type"] = "request_def_amount"
        bot.save_players(data)
        bot.send(
            chat_id,
            "Введите требуемое количество дефа.\n\n<b>Пехота = 1\nКонница = 2</b>\n\nНапример:\n5000 пехоты = 5000\n2500 конницы = 5000\n1000 пехоты + 2000 конницы = 5000",
            force_reply=True,
        )
        return

    if typ == "request_def_amount":
        required = bot.to_int(text)
        if required is None or required <= 0:
            bot.send(chat_id, "Введите целое положительное число, например <code>5000</code>.", force_reply=True)
            return
        player["state"]["required_def"] = required
        player["state"]["type"] = "request_confirm"
        bot.save_players(data)
        bot.send(chat_id, request_summary(player), confirm_keyboard())
        return

    return _original_process_text(message)


def callback_query(q):
    message = q.get("message", {})
    if message.get("message_thread_id") != bot.THREAD_ID:
        return
    action = q.get("data", "")
    user = q.get("from", {})
    data, player = bot.get_player(user)
    chat_id, msg_id = message["chat"]["id"], message["message_id"]
    bot.answer_callback(q.get("id"))

    if action == "menu":
        refresh_center(chat_id=chat_id, create_if_missing=True)
        return

    if action == "settings":
        bot.send(chat_id, bot.settings_text(player), bot.settings_kb())
        return

    if action == "request_def":
        start_request(chat_id, player, data)
        return

    if action == "send_def":
        requests = bot.load_json(bot.REQUESTS_FILE, [])
        if not isinstance(requests, list):
            requests = []
        now = datetime.now(SERVER_TZ).replace(tzinfo=None)
        active = []
        changed = False
        for req in requests:
            if req.get("status") != "active":
                continue
            attack = request_datetime(req)
            if attack is not None and attack <= now:
                req["status"] = "expired"
                changed = True
            else:
                active.append(req)
        if changed:
            bot.save_json(bot.REQUESTS_FILE, requests)
            bot.persist_data()
        if not active:
            bot.edit(chat_id, msg_id, "<b>🛡 ОТПРАВИТЬ ДЕФ</b>\n\nАктивных заявок нет.", request_menu())
            return
        bot.edit(chat_id, msg_id, "<b>🛡 ОТПРАВИТЬ ДЕФ</b>\n\nВыберите заявку:", send_def_requests_keyboard(active))
        return

    if action.startswith("send_req:"):
        req_id = int(action.split(":", 1)[1])
        requests = bot.load_json(bot.REQUESTS_FILE, [])
        req = next((r for r in requests if int(r.get("id", -1)) == req_id and r.get("status") == "active"), None)
        if req is None:
            bot.edit(chat_id, msg_id, "❌ Эта заявка больше не активна.", request_menu())
            return

        state = player.get("state") or {}
        if state.get("type") != "send_def" or int(state.get("request_id", -1)) != req_id:
            player["state"] = {"type": "send_def", "request_id": req_id, "selected": {}}
            bot.save_players(data)

        summary = send_def_summary(player, req)
        text = (
            f"<b>🛡 ОТПРАВИТЬ ДЕФ → #{req_id}</b>\n\n"
            f"📍 Цель: {village_link(req['target_x'], req['target_y'])}\n"
            f"⚔️ Прибыть до: <b>{req['attack_time_display']}</b>\n"
            f"🛡 Требуется: <b>{req['required_def']}</b> очков\n\n"
            "Выберите деревню, из которой хотите отправить деф.\n"
            "🟢 = есть вариант, который успевает. 🔴 = нет.\n\n"
            + summary
        )
        bot.edit(chat_id, msg_id, text, send_def_sources_keyboard(player, req))
        return

    if action.startswith("send_village:"):
        _, req_id_s, idx_s = action.split(":")
        req_id, idx = int(req_id_s), int(idx_s)
        requests = bot.load_json(bot.REQUESTS_FILE, [])
        req = next((r for r in requests if int(r.get("id", -1)) == req_id and r.get("status") == "active"), None)
        if req is None or idx < 0 or idx >= len(player.get("villages", [])):
            bot.edit(chat_id, msg_id, "❌ Заявка или деревня недоступна.", request_menu())
            return

        state = player.get("state") or {}
        if state.get("type") != "send_def" or int(state.get("request_id", -1)) != req_id:
            player["state"] = {"type": "send_def", "request_id": req_id, "selected": {}}

        bot.save_players(data)
        bot.edit(chat_id, msg_id, send_def_village_text(player, req, idx), send_def_village_keyboard(player, req, idx))
        return

    if action.startswith("send_hero:"):
        _, req_id_s, idx_s = action.split(":")
        req_id, idx = int(req_id_s), int(idx_s)
        state = player.get("state") or {}
        if state.get("type") != "send_def" or int(state.get("request_id", -1)) != req_id:
            return
        selected = state.setdefault("selected", {})
        entry = selected.setdefault(str(idx), {"troops": {}, "with_hero": False})
        entry["with_hero"] = not bool(entry.get("with_hero", False))
        bot.save_players(data)
        requests = bot.load_json(bot.REQUESTS_FILE, [])
        req = next((r for r in requests if int(r.get("id", -1)) == req_id and r.get("status") == "active"), None)
        if req:
            bot.edit(chat_id, msg_id, send_def_village_text(player, req, idx), send_def_village_keyboard(player, req, idx))
        return

    if action.startswith("send_unit:"):
        _, req_id_s, idx_s, unit_key = action.split(":", 3)
        req_id, idx = int(req_id_s), int(idx_s)
        requests = bot.load_json(bot.REQUESTS_FILE, [])
        req = next((r for r in requests if int(r.get("id", -1)) == req_id and r.get("status") == "active"), None)
        if req is None or idx < 0 or idx >= len(player.get("villages", [])):
            bot.edit(chat_id, msg_id, "❌ Заявка или деревня недоступна.", request_menu())
            return
        state = player.setdefault("state", {"type": "send_def", "request_id": req_id, "selected": {}})
        state["type"] = "send_def_amount"
        state["request_id"] = req_id
        state["index"] = idx
        state["unit"] = unit_key
        bot.save_players(data)
        village = player["villages"][idx]
        available = int(village.get("troops", {}).get(unit_key, 0) or 0)
        unit_name = bot.settings().get("units", {}).get(unit_key, {}).get("name", unit_key)
        bot.send(
            chat_id,
            f"Введите количество <b>{unit_name}</b> из деревни <b>{village.get('coordinates')}</b>.\n"
            f"Доступно по вашему резерву: <b>{available}</b>.",
            force_reply=True,
        )
        return

    if action.startswith("send_finish:"):
        req_id = int(action.split(":", 1)[1])
        requests = bot.load_json(bot.REQUESTS_FILE, [])
        req = next((r for r in requests if int(r.get("id", -1)) == req_id and r.get("status") == "active"), None)
        if req is None:
            bot.edit(chat_id, msg_id, "❌ Заявка больше не активна.", request_menu())
            return
        state = send_def_state(player, req_id)
        if not state or not state.get("selected"):
            bot.edit(chat_id, msg_id, "❌ Сначала выберите хотя бы одну деревню и войска.", request_menu())
            return
        bot.edit(chat_id, msg_id, send_links_text(player, req), send_links_keyboard(player, req))
        return

    if action.startswith("send_links:"):
        req_id = int(action.split(":", 1)[1])
        requests = bot.load_json(bot.REQUESTS_FILE, [])
        req = next((r for r in requests if int(r.get("id", -1)) == req_id and r.get("status") == "active"), None)
        if req is None:
            bot.edit(chat_id, msg_id, "❌ Заявка больше не активна.", request_menu())
            return
        bot.edit(chat_id, msg_id, send_links_text(player, req), send_links_keyboard(player, req))
        return

    if action == "request_cancel":
        player["state"] = None
        bot.save_players(data)
        bot.edit(chat_id, msg_id, "<b>🛡 ЗАПРОС НА ДЕФ</b>\n\nЗаявка отменена.", request_menu())
        return

    if action in ("request_date_today", "request_date_tomorrow"):
        now = datetime.now(SERVER_TZ)
        selected = now if action == "request_date_today" else now + timedelta(days=1)
        selected_date = selected.date()
        player["state"]["attack_date"] = selected_date.strftime("%Y-%m-%d")
        player["state"]["attack_date_display"] = selected_date.strftime("%d.%m.%Y")
        player["state"]["type"] = "request_attack_time"
        bot.save_players(data)
        try:
            bot.edit(
                chat_id,
                msg_id,
                f"📅 Дата атаки: <b>{selected_date.strftime('%d.%m.%Y')}</b>",
            )
        except Exception:
            pass
        bot.send(
            chat_id,
            f"📅 Дата атаки: <b>{selected_date.strftime('%d.%m.%Y')}</b>\n\n⏰ Введите время атаки по времени сервера Travian.\nФормат: <code>22:30:45</code>",
            force_reply=True,
        )
        return

    if action == "request_confirm":
        state = player.get("state") or {}
        if state.get("type") != "request_confirm":
            bot.edit(chat_id, msg_id, "❌ Данные заявки устарели. Создайте заявку заново.", request_menu())
            return
        requests = bot.load_json(bot.REQUESTS_FILE, [])
        if not isinstance(requests, list):
            requests = []
        req_id = next_request_id(requests)
        req = {
            "id": req_id,
            "requester_id": int(user["id"]),
            "requester_username": user.get("username", ""),
            "requester_first_name": user.get("first_name", ""),
            "target_x": state["target_x"],
            "target_y": state["target_y"],
            "target_player": state["target_player"],
            "attack_time": state["attack_time"],
            "attack_time_display": state["attack_time_display"],
            "required_def": state["required_def"],
            "status": "active",
            "created_at": datetime.now(SERVER_TZ).strftime("%Y-%m-%d %H:%M:%S"),
        }
        save_request(req)
        player["state"] = None
        bot.save_players(data)
        bot.edit(chat_id, msg_id, "<b>✅ Заявка создана.</b>\n\nОна добавлена в закреплённый Центр дефа.", request_menu())
        refresh_center(chat_id=chat_id, create_if_missing=True)
        return

    return _original_callback_query(q)


def handle_update(message=None, callback=None):
    if callback is not None:
        callback_query(callback)
    elif message is not None:
        process_text(message)


def env_message():
    text = os.environ.get("MESSAGE_TEXT", "")
    if not text:
        return None
    return {
        "message_id": int(os.environ.get("MESSAGE_ID", "0") or 0),
        "chat": {"id": int(os.environ.get("CHAT_ID", "0") or 0)},
        "from": {
            "id": int(os.environ.get("USER_ID", "0") or 0),
            "username": os.environ.get("USERNAME", ""),
            "first_name": os.environ.get("FIRST_NAME", ""),
        },
        "text": text,
        "message_thread_id": int(os.environ.get("THREAD_ID", str(bot.THREAD_ID)) or bot.THREAD_ID),
    }


def env_callback():
    data = os.environ.get("CALLBACK_DATA", "")
    if not data:
        return None
    return {
        "id": os.environ.get("CALLBACK_ID", ""),
        "data": data,
        "from": {
            "id": int(os.environ.get("USER_ID", "0") or 0),
            "username": os.environ.get("USERNAME", ""),
            "first_name": os.environ.get("FIRST_NAME", ""),
        },
        "message": {
            "message_id": int(os.environ.get("MESSAGE_ID", "0") or 0),
            "chat": {"id": int(os.environ.get("CHAT_ID", "0") or 0)},
            "message_thread_id": int(os.environ.get("THREAD_ID", str(bot.THREAD_ID)) or bot.THREAD_ID),
        },
    }


bot.main_menu = request_menu
bot.process_text = process_text
bot.callback_query = callback_query

if __name__ == "__main__":
    action = os.environ.get("ACTION", "refresh_center")
    if action == "refresh_center":
        refresh_center(chat_id=os.environ.get("CHAT_ID") or None, create_if_missing=False)
    elif action == "callback":
        callback = env_callback()
        if callback:
            handle_update(callback=callback)
        refresh_center(chat_id=os.environ.get("CHAT_ID") or None, create_if_missing=False)
    elif action == "message":
        message = env_message()
        if message:
            handle_update(message=message)
        refresh_center(chat_id=os.environ.get("CHAT_ID") or None, create_if_missing=False)
