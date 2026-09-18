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


RACE_BY_TRIBE = {1: "roman", 2: "teuton", 3: "gaul"}

def race_from_village(village):
    try:
        return RACE_BY_TRIBE.get(int(village.get("tribe_id")))
    except (TypeError, ValueError):
        return None

def sync_player_race(player):
    _, villages = latest_snapshot()
    if villages is None:
        return player.get("race")
    for owned in player.get("villages", []):
        parts = str(owned.get("coordinates", "")).split()
        if len(parts) != 2:
            continue
        try:
            x, y = int(parts[0]), int(parts[1])
        except ValueError:
            continue
        for village in villages.values():
            try:
                if int(village.get("x")) == x and int(village.get("y")) == y:
                    race = race_from_village(village)
                    if race:
                        player["race"] = race
                        return race
            except (TypeError, ValueError):
                continue
    return player.get("race")


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


def request_remaining(req):
    return max(0, int(req.get("required_def", 0) or 0) - int(req.get("collected_def", 0) or 0))


def request_closed(req):
    return request_remaining(req) <= 0


def best_source_options(player, req):
    attack = request_datetime(req)
    if attack is None:
        return []
    now = datetime.now(SERVER_TZ).replace(tzinfo=None)
    options = []
    for idx, village in enumerate(player.get("villages", [])):
        eligible = []
        for item in source_village_units(player, village, req):
            variants = [(False, item["no_hero_seconds"])]
            if item["hero_seconds"] is not None:
                variants.append((True, item["hero_seconds"]))
            for with_hero, seconds in variants:
                arrival = now + timedelta(seconds=seconds)
                if arrival <= attack:
                    eligible.append({
                        "idx": idx,
                        "village": village,
                        "unit_key": item["key"],
                        "name": item["name"],
                        "amount": item["amount"],
                        "value": item["value"],
                        "arrival": arrival,
                        "seconds": seconds,
                        "with_hero": with_hero,
                        "max_def": item["amount"] * item["value"],
                    })
        if eligible:
            options.append(sorted(
                eligible,
                key=lambda x: (x["max_def"], -x["seconds"]),
                reverse=True,
            )[0])
    return sorted(options, key=lambda x: (x["seconds"], -x["max_def"]))


def send_def_requests_keyboard(requests):
    rows = []
    for req in requests:
        if req.get("status") == "active" and not request_closed(req):
            rows.append([{
                "text": f"🛡 Отправить деф #{req['id']} — {req['target_x']}|{req['target_y']}",
                "callback_data": f"send_req:{req['id']}",
            }])
    rows.append([{"text": "⬅️ Назад", "callback_data": "menu"}])
    return bot.kb(rows)


def send_def_plan_text(player, req):
    remaining = request_remaining(req)
    options = best_source_options(player, req)
    lines = [
        f"<b>🛡 ОТПРАВИТЬ ДЕФ #{req['id']}</b>",
        "",
        f"📍 Цель: {village_link(req['target_x'], req['target_y'])}",
        f"⚔️ Прибыть до: <b>{req['attack_time_display']}</b>",
        f"🛡 Осталось закрыть: <b>{remaining}</b> очков",
        "",
    ]
    if not options:
        lines.append("🔴 Подходящих деревень нет — имеющийся деф не успевает.")
    else:
        lines.append("<b>Подходящие варианты:</b>")
        for item in options:
            hero = " + герой" if item["with_hero"] else ""
            lines.append(
                f"🟢 <b>{item['village'].get('coordinates', '?')}</b> — "
                f"{item['name']}{hero}, до <b>{item['max_def']}</b> очков, "
                f"прибытие <b>{item['arrival'].strftime('%H:%M:%S')}</b>"
            )
        lines.extend([
            "",
            "Выберите подходящий вариант и укажите количество дефа.",
            "Например: <code>10000</code> (в очках дефа; пехота = 1, конница = 2).",
        ])
    return "\n".join(lines)


def send_def_plan_keyboard(player, req):
    rows = []
    if best_source_options(player, req):
        rows.append([{
            "text": "🛡 Отправить деф",
            "callback_data": f"send_amount:{req['id']}",
        }])
    rows.append([{"text": "⬅️ К заявкам", "callback_data": "send_def"}])
    return bot.kb(rows)


def send_def_amount_text(req, village, unit_name, max_def, arrival):
    return (
        f"<b>🛡 Отправка дефа</b>\n\n"
        f"🏘 Деревня: <b>{village.get('coordinates', '?')}</b>\n"
        f"⚔️ Войска: <b>{unit_name}</b>\n"
        f"⏱ Прибытие: <b>{arrival.strftime('%H:%M:%S')}</b>\n"
        f"📦 Максимум: <b>{max_def}</b> очков\n\n"
        f"Введите количество дефа. Например: <code>10000</code>"
    )

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

def notification_source_options(player, req):
    """Return every troop type from every village that can still arrive in time.

    Notification eligibility is based only on arrival time. Troop amount is
    displayed for information and never filters a defender out.
    """
    attack = request_datetime(req)
    if attack is None:
        return []

    now = datetime.now(SERVER_TZ).replace(tzinfo=None)
    options = []

    for idx, village in enumerate(player.get("villages", [])):
        for item in source_village_units(player, village, req):
            # Show the normal movement time. If the hero is available, also
            # show the faster hero-assisted time as the useful variant.
            variants = [(False, item["no_hero_seconds"])]
            if item["hero_seconds"] is not None:
                variants.append((True, item["hero_seconds"]))

            best = None
            for with_hero, seconds in variants:
                if seconds is None:
                    continue
                deadline = attack - timedelta(seconds=seconds)
                if deadline <= now:
                    continue

                candidate = {
                    "idx": idx,
                    "village": village,
                    "unit_key": item["key"],
                    "name": item["name"],
                    "amount": item["amount"],
                    "value": item["value"],
                    "seconds": seconds,
                    "arrival": now + timedelta(seconds=seconds),
                    "deadline": deadline,
                    "remaining": (deadline - now).total_seconds(),
                    "with_hero": with_hero,
                }

                if best is None or candidate["seconds"] < best["seconds"]:
                    best = candidate

            if best is not None:
                options.append(best)

    return sorted(
        options,
        key=lambda x: (x["idx"], x["remaining"], x["name"]),
    )

def notify_eligible_defenders(req):
    """Privately notify every registered player with at least one village that still theoretically arrives in time."""
    data = bot.players()
    if not isinstance(data, dict):
        return

    sent = 0
    for player in data.values():
        if not isinstance(player, dict):
            continue
        private_chat_id = player.get("private_chat_id")
        if not private_chat_id or not player.get("private_notifications", True):
            continue

        options = notification_source_options(player, req)
        if not options:
            continue

        lines = [
            "<b>🛡 НОВАЯ ЗАЯВКА НА ДЕФ</b>",
            "",
            f"🎯 Цель: <b>{req['target_x']}|{req['target_y']}</b>",
            f"👤 Игрок: <b>{html.escape(req['target_player'])}</b>",
            f"⚔️ Атака: <b>{req['attack_time_display']}</b>",
            f"🛡 Требуется: <b>{req['required_def']}</b> очков",
            "",
            "<b>Твои деревни, которые теоретически успевают:</b>",
            "",
        ]

        current_village = None
        for item in options:
            coords = item["village"].get("coordinates", "?")
            if coords != current_village:
                if current_village is not None:
                    lines.append("")
                lines.append(f"🏘 <b>{html.escape(coords)}</b>")
                current_village = coords

            hero = " + герой" if item["with_hero"] else ""
            lines.extend([
                f"🛡 {item['amount']} {item['name']}{hero}",
                f"   ⏳ Осталось: <b>{format_duration(item['remaining'])}</b>",
                f"   🚨 Отправить до: <b>{item['deadline'].strftime('%H:%M:%S')}</b>",
                f"   🏁 Прибытие: <b>{item['arrival'].strftime('%H:%M:%S')}</b>",
            ])

        lines.append("Проверь реальные войска в игре и, если можешь помочь, отправь деф из меню активных заявок в Telegram.")

        try:
            bot.tg("sendMessage", chat_id=int(private_chat_id), text="\n".join(lines), parse_mode="HTML")
            sent += 1
            print(
                f"Defence notification sent: request=#{req.get('id')} player={player.get('telegram_id')} options={len(options)}",
                flush=True,
            )
        except Exception as exc:
            print(
                f"Defence notification failed: request=#{req.get('id')} player={player.get('telegram_id')}: {exc}",
                flush=True,
            )

    print(f"Defence notifications complete: request=#{req.get('id')} sent={sent}", flush=True)




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
                f"🛡 Деф: <b>{req.get('collected_def', 0)}</b> / <b>{req['required_def']}</b> очков",
                "",
            ])

    lines.append("Деф должен прибыть <b>ДО</b> времени атаки.")
    lines.append("")
    lines.append("🛡 Нажмите «Отправить деф», выберите подходящий вариант и укажите количество.")
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
    sync_player_race(player)
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
        amount = bot.to_int(text)
        req_id = int(state.get("request_id", 0) or 0)
        if amount is None or amount <= 0:
            bot.send(chat_id, "Введите положительное количество очков дефа.", force_reply=True)
            return

        requests = bot.load_json(bot.REQUESTS_FILE, [])
        req = next((r for r in requests if int(r.get("id", -1)) == req_id and r.get("status") == "active"), None)
        if req is None or request_closed(req):
            player["state"] = None
            bot.save_players(data)
            bot.send(chat_id, "❌ Эта заявка уже закрыта или недоступна.", request_menu())
            return

        options = best_source_options(player, req)
        total_available = sum(x["max_def"] for x in options)
        remaining = request_remaining(req)
        if amount > total_available:
            bot.send(
                chat_id,
                f"❌ Сейчас из ваших подходящих деревень можно отправить максимум <b>{total_available}</b> очков дефа.\n"
                f"Введите число не больше этого значения.",
                force_reply=True,
            )
            return

        amount = min(amount, remaining)
        left = amount
        plan = []
        for item in options:
            if left <= 0:
                break
            contribution = min(left, item["max_def"])
            if contribution <= 0:
                continue
            plan.append({
                "village": item["village"].get("coordinates", ""),
                "unit": item["unit_key"],
                "unit_name": item["name"],
                "def_points": contribution,
                "arrival": item["arrival"].strftime("%H:%M:%S"),
                "with_hero": item["with_hero"],
            })
            left -= contribution

        if left > 0:
            bot.send(chat_id, "❌ Не удалось подобрать подходящий план отправки.", request_menu())
            return

        req.setdefault("contributions", []).append({
            "telegram_id": int(user.get("id", 0)),
            "username": user.get("username", ""),
            "first_name": user.get("first_name", ""),
            "def_points": amount,
            "plan": plan,
            "created_at": datetime.now(SERVER_TZ).strftime("%Y-%m-%d %H:%M:%S"),
        })
        req["collected_def"] = int(req.get("collected_def", 0) or 0) + amount
        if request_closed(req):
            req["status"] = "closed"

        bot.save_json(bot.REQUESTS_FILE, requests)
        bot.persist_data()
        player["state"] = None
        bot.save_players(data)

        plan_lines = []
        for item in plan:
            hero = " + герой" if item["with_hero"] else ""
            plan_lines.append(
                f"🏘 {item['village']} — {item['unit_name']}{hero}: <b>{item['def_points']}</b> очков, "
                f"прибытие {item['arrival']}"
            )

        if req["status"] == "closed":
            result = (
                f"<b>✅ Заявка #{req_id} закрыта.</b>\n\n"
                f"Ваш вклад: <b>{amount}</b> очков дефа.\n\n"
                + "\n".join(plan_lines)
            )
        else:
            result = (
                f"<b>✅ Вклад в заявку #{req_id} записан.</b>\n\n"
                f"Ваш вклад: <b>{amount}</b> очков.\n"
                f"Осталось: <b>{request_remaining(req)}</b> очков.\n\n"
                + "\n".join(plan_lines)
            )

        bot.send(chat_id, result, request_menu())
        refresh_center(chat_id=chat_id, create_if_missing=True)
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
    sync_player_race(player)
    chat_id, msg_id = message["chat"]["id"], message["message_id"]
    bot.answer_callback(q.get("id"))

    if action == "menu":
        refresh_center(chat_id=chat_id, create_if_missing=True)
        return

    if action == "settings":
        bot.send(chat_id, bot.settings_text(player), bot.settings_kb())
        return

    if action == "private_notify":
        if player.get("private_chat_id") and player.get("private_notifications", True):
            bot.send(
                chat_id,
                "<b>🔔 Личные уведомления подключены.</b>\n\n"
                "Когда появляется новая заявка на деф, бот будет писать вам в личку, "
                "если хотя бы одна из настроенных деревень теоретически успевает прибыть до атаки.",
                bot.settings_kb(),
            )
        else:
            bot.send(
                chat_id,
                "<b>🔔 Личные уведомления</b>\n\n"
                "Чтобы подключить уведомления, откройте личный чат с этим ботом и отправьте команду <code>/start</code>.\n\n"
                "После этого бот сможет писать вам в личку о новых заявках, если ваш деф теоретически успевает прибыть вовремя.",
                bot.settings_kb(),
            )
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
        if req is None or request_closed(req):
            bot.edit(chat_id, msg_id, "❌ Эта заявка уже закрыта.", request_menu())
            return
        bot.edit(chat_id, msg_id, send_def_plan_text(player, req), send_def_plan_keyboard(player, req))
        return

    if action.startswith("send_amount:"):
        req_id = int(action.split(":", 1)[1])
        requests = bot.load_json(bot.REQUESTS_FILE, [])
        req = next((r for r in requests if int(r.get("id", -1)) == req_id and r.get("status") == "active"), None)
        if req is None or request_closed(req):
            bot.edit(chat_id, msg_id, "❌ Эта заявка уже закрыта.", request_menu())
            return
        if not best_source_options(player, req):
            bot.edit(chat_id, msg_id, "🔴 Подходящих деревень для этой заявки сейчас нет.", request_menu())
            return
        player["state"] = {"type": "send_def_amount", "request_id": req_id}
        bot.save_players(data)
        bot.send(
            chat_id,
            f"<b>🛡 Отправить деф в заявку #{req_id}</b>\n\n"
            f"Осталось закрыть: <b>{request_remaining(req)}</b> очков.\n\n"
            "Введите количество дефа, которое готовы отправить.\n"
            "Например: <code>10000</code>",
            force_reply=True,
        )
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
        notify_eligible_defenders(req)
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
