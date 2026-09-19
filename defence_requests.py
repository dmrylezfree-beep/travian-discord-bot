import html
import os

import requests
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import defence_bot as bot
from travian_bot import parse_map_data, SERVER_URL

SNAPSHOT_DIR = Path("data/snapshots")
STATE_FILE = bot.DATA_DIR / "state.json"
SERVER_TZ = ZoneInfo("Europe/London")
DEFENCE_WORKER_URL = "https://travian-defence.dmrylezfree.workers.dev"
_snapshot_cache_path = None
_snapshot_cache = None

_original_process_text = bot.process_text
_original_callback_query = bot.callback_query


def schedule_defence_reminders(req, contribution):
    """Queue exact private reminders without any permanent GitHub cron."""
    token = os.environ.get("DEFENCE_TELEGRAM_TOKEN")
    if not token:
        print("Reminder scheduling skipped: DEFENCE_TELEGRAM_TOKEN is missing", flush=True)
        return False

    players = bot.players()
    player = players.get(str(contribution.get("telegram_id"))) or {}
    private_chat_id = player.get("private_chat_id")
    if not private_chat_id or not player.get("private_notifications", True):
        print("Reminder scheduling skipped: private notifications are unavailable", flush=True)
        return False

    reminders = []
    for item in contribution.get("plan", []):
        reminder_at = item.get("reminder_at")
        if not reminder_at or item.get("reminder_sent"):
            continue
        reminders.append({
            "request_id": req.get("id"),
            "telegram_id": contribution.get("telegram_id"),
            "private_chat_id": int(private_chat_id),
            "village": item.get("village"),
            "def_points": int(item.get("def_points", 0) or 0),
            "speed_mode": item.get("speed_mode", "normal"),
            "reminder_at": reminder_at,
            "deadline_at": item.get("deadline_at"),
            "deadline": item.get("deadline"),
            "target_x": req.get("target_x"),
            "target_y": req.get("target_y"),
            "attack_time": req.get("attack_time"),
            "attack_time_display": req.get("attack_time_display"),
        })

    if not reminders:
        return True

    try:
        response = requests.post(
            f"{DEFENCE_WORKER_URL}/schedule-reminders",
            json={"reminders": reminders},
            headers={"Authorization": f"Bearer {token}"},
            timeout=30,
        )
        response.raise_for_status()
        print(
            f"Queued {len(reminders)} defence reminder(s) for request #{req.get('id')}",
            flush=True,
        )
        return True
    except Exception as exc:
        # The contribution itself must remain saved even if reminder scheduling
        # temporarily fails.
        print(f"Reminder scheduling failed: {exc}", flush=True)
        return False


def load_state():
    return bot.load_json(STATE_FILE, {})


def save_state(state):
    bot.save_json(STATE_FILE, state)
    bot.persist_data()


def request_menu():
    return bot.kb([
        [{"text": "➕ Запросить деф", "callback_data": "request_def"}],
        [{"text": "🛡 Отправить деф", "callback_data": "send_def"}],
        [{"text": "🗑 Удалить заявку", "callback_data": "delete_request_menu"}],
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


def travel_seconds(distance, unit_speed, village, with_hero=False, standard_bonus=None, boots_bonus=None):
    cfg = bot.settings()
    world_speed = float(cfg.get("world_speed_multiplier", 1.0) or 1.0)
    arena = int(village.get("arena", 0) or 0)
    hero = village.get("hero", {}) or {}

    base_speed = float(unit_speed) * world_speed
    if with_hero and hero.get("present"):
        standard = float(standard_bonus if standard_bonus is not None else hero.get("standard_bonus", 0) or 0)
        boots = float(boots_bonus if boots_bonus is not None else hero.get("boots_bonus", 0) or 0)
    else:
        standard = 0.0
        boots = 0.0

    after20_bonus = (arena * 0.20) + boots
    first_leg = min(distance, 20.0)
    seconds = first_leg * 3600.0 / (base_speed * (1.0 + standard))
    if distance > 20:
        second_leg = distance - 20.0
        seconds += second_leg * 3600.0 / (
            base_speed * (1.0 + standard) * (1.0 + after20_bonus)
        )
    return seconds


def hero_gear_options(player, village, distance, unit_speed):
    """Outbound hero gear combinations from the saved inventory."""
    if not (village.get("hero") or {}).get("present"):
        return []
    inv = bot.hero_inventory(player)
    standards = [0] + list(inv.get("standards", []))
    boots_values = [0] + list(inv.get("boots", []))
    best_map = max(inv.get("maps", []) or [0])
    options = []
    seen = set()
    for std in standards:
        for boots in boots_values:
            seconds = travel_seconds(
                distance, unit_speed, village, with_hero=True,
                standard_bonus=std / 100.0, boots_bonus=boots / 100.0,
            )
            # Equal travel times do not need duplicate buttons. Prefer the
            # strongest boots and, without a standard, the best return map.
            rounded = int(round(seconds))
            label_parts = ["🦸 Герой"]
            if std:
                label_parts.append(f"🚩 +{std}%")
            elif best_map:
                label_parts.append(f"🗺 +{best_map}%")
            if boots:
                label_parts.append(f"🥾 +{boots}%")
            item = {
                "seconds": seconds,
                "standard": std,
                "boots": boots,
                "map": best_map if std == 0 else 0,
                "label": " · ".join(label_parts),
            }
            old = next((x for x in options if x["_rounded"] == rounded and x["standard"] == std), None)
            if old is not None:
                if boots > old["boots"]:
                    options.remove(old)
                else:
                    continue
            item["_rounded"] = rounded
            options.append(item)
    for item in options:
        item.pop("_rounded", None)
    return options


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
        gear = hero_gear_options(player, village, distance, speed)
        hero_seconds = min((x["seconds"] for x in gear), default=None)
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


def village_send_options(player, req):
    """Available timing variants. The no-hero option is always considered."""
    attack = request_datetime(req)
    if attack is None:
        return []
    now = datetime.now(SERVER_TZ).replace(tzinfo=None)
    remaining = (attack - now).total_seconds()
    if remaining <= 0:
        return []

    result = []
    for idx, village in enumerate(player.get("villages", [])):
        units = source_village_units(player, village, req)
        if not units:
            continue
        variants = []

        # Always offer a no-hero route when the registered troops can arrive.
        normal_units = [x for x in units if x["no_hero_seconds"] <= remaining]
        if normal_units:
            seconds = max(x["no_hero_seconds"] for x in normal_units)
            variants.append({
                "key": "normal", "label": "⚡ Без героя", "seconds": seconds,
                "deadline": attack - timedelta(seconds=seconds), "arrival": attack,
                "max_def": sum(int(x["amount"]) * int(x["value"]) for x in normal_units),
                "with_hero": False,
            })

        # Build useful hero+inventory combinations. A combination must work for
        # every registered unit included in that variant; the slowest governs.
        if (village.get("hero") or {}).get("present"):
            inv = bot.hero_inventory(player)
            standards = [0] + list(inv.get("standards", []))
            boots_values = [0] + list(inv.get("boots", []))
            best_map = max(inv.get("maps", []) or [0])
            candidates = []
            for std in standards:
                for boots in boots_values:
                    eligible = []
                    for item in units:
                        seconds = travel_seconds(
                            item["distance"], item["speed"], village, with_hero=True,
                            standard_bonus=std / 100.0, boots_bonus=boots / 100.0,
                        )
                        if seconds <= remaining:
                            eligible.append((item, seconds))
                    if not eligible:
                        continue
                    seconds = max(x[1] for x in eligible)
                    label = "🦸 Герой"
                    if std:
                        label += f" · 🚩 +{std}%"
                    elif best_map:
                        label += f" · 🗺 +{best_map}%"
                    if boots:
                        label += f" · 🥾 +{boots}%"
                    candidates.append({
                        "key": f"h{std}b{boots}m{best_map if std == 0 else 0}",
                        "label": label,
                        "seconds": seconds,
                        "deadline": attack - timedelta(seconds=seconds),
                        "arrival": attack,
                        "max_def": sum(int(x[0]["amount"]) * int(x[0]["value"]) for x in eligible),
                        "with_hero": True,
                        "standard": std, "boots": boots, "map": best_map if std == 0 else 0,
                    })

            # Remove combinations that produce the same deadline/max capacity.
            unique = {}
            for item in candidates:
                sig = (int(round(item["seconds"])), int(item["max_def"]))
                current = unique.get(sig)
                score = (item.get("standard", 0), item.get("boots", 0), item.get("map", 0))
                if current is None or score > (
                    current.get("standard", 0), current.get("boots", 0), current.get("map", 0)
                ):
                    unique[sig] = item
            variants.extend(sorted(unique.values(), key=lambda x: x["deadline"]))

        # Slowing tools remain separate no-hero timing variants.
        for key, label, speed in (
            ("ram", "🐏 + 1 таран", 4.0),
            ("catapult", "🪨 + 1 катапульта", 3.0),
        ):
            eligible = []
            for item in units:
                seconds = travel_seconds(item["distance"], min(float(item["speed"]), speed), village, with_hero=False)
                if seconds <= remaining:
                    eligible.append((item, seconds))
            if eligible:
                seconds = max(x[1] for x in eligible)
                variants.append({
                    "key": key, "label": label, "seconds": seconds,
                    "deadline": attack - timedelta(seconds=seconds), "arrival": attack,
                    "max_def": sum(int(x[0]["amount"]) * int(x[0]["value"]) for x in eligible),
                    "with_hero": False,
                })

        if variants:
            result.append({
                "idx": idx, "village": village, "units": units,
                "max_def": max(int(v["max_def"]) for v in variants), "variants": variants,
            })
    return result


def send_village_keyboard(player, req, exclude=None):
    exclude = set(exclude or [])
    rows = []
    for item in village_send_options(player, req):
        if item["idx"] in exclude:
            continue
        rows.append([{
            "text": f"🏘 {item['village'].get('coordinates', '?')} — до {item['max_def']}",
            "callback_data": f"send_village:{req['id']}:{item['idx']}",
        }])
    rows.append([{"text": "⬅️ К заявке", "callback_data": f"send_req:{req['id']}"}])
    return bot.kb(rows)


def speed_variant_keyboard(req_id, village_idx, variants):
    rows = []
    for item in variants:
        rows.append([{
            "text": f"{item['label']} — {item['deadline'].strftime('%H:%M:%S')}",
            "callback_data": f"send_speed:{req_id}:{village_idx}:{item['key']}",
        }])
    rows.append([{"text": "❌ Отмена", "callback_data": f"send_req:{req_id}"}])
    return bot.kb(rows)


def draft_summary(state, req=None):
    lines = ["<b>🛡 ПЛАН ОТПРАВКИ</b>", ""]
    if req is not None:
        lines.extend([
            f"🎯 Цель: {village_link(req['target_x'], req['target_y'])}",
            f"⚔️ Атака: <b>{req['attack_time_display']}</b>",
            "",
        ])
    total = 0
    for item in state.get("draft", []):
        mode = ""
        if item.get("gear_label"):
            mode = " · " + item["gear_label"]
        elif str(item.get("speed_mode", "")).startswith("h"):
            mode = " · 🦸 с героем"
        elif item["speed_mode"] == "ram":
            mode = " · 🐏 + 1 таран"
        elif item["speed_mode"] == "catapult":
            mode = " · 🪨 + 1 катапульта"
        total += int(item.get("def_points", 0) or 0)
        lines.append(
            f"🏘 <b>{html.escape(item['village'])}</b>\n"
            f"🛡 <b>{item['def_points']}</b> очков{mode}\n"
            f"🚨 Отправить: <b>{item['deadline']}</b>\n"
            f"🔔 Напомню: <b>{item['reminder_time']}</b>"
        )
        lines.append("")
    lines.append(f"<b>Итого: {total} очков</b>")
    return "\n".join(lines)


def draft_actions_keyboard(req_id, can_add=True):
    rows = []
    if can_add:
        rows.append([{"text": "➕ Добавить ещё деревню", "callback_data": f"send_add:{req_id}"}])
    rows.append([{"text": "✅ Готово", "callback_data": f"send_finish:{req_id}"}])
    rows.append([{"text": "❌ Отмена", "callback_data": f"send_req:{req_id}"}])
    return bot.kb(rows)


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
        lines.append("🔴 Из твоих деревень сейчас ничего не успевает к атаке.")
    else:
        lines.append("<b>Можно отправить из:</b>")
        for item in options:
            hero = " + герой" if item["with_hero"] else ""
            lines.append(
                f"🟢 <b>{item['village'].get('coordinates', '?')}</b> — "
                f"{item['name']}{hero}, до <b>{item['max_def']}</b> очков, "
                f"прибытие <b>{item['arrival'].strftime('%H:%M:%S')}</b>"
            )
        lines.extend([
            "",
            "Выбери деревню и укажи количество дефа.",
            "💡 Пехота = 1 очко · Конница = 2 очка.",
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


def _player_label(player):
    return (
        player.get("first_name")
        or player.get("username")
        or f"ID {player.get('telegram_id', '?')}"
    )


def _previously_declared_by_village(req):
    """Informational only: never subtract these amounts from theoretical availability."""
    result = {}
    if req.get("status") != "active":
        return result
    for contribution in req.get("contributions", []):
        for leg in contribution.get("plan", []):
            coords = str(leg.get("village", "")).strip()
            if not coords:
                continue
            result[coords] = result.get(coords, 0) + int(leg.get("def_points", 0) or 0)
    return result


def build_optimal_plan(req):
    """Build a recommendation from declared settings, without reserving troops.

    Priority: infantry first, then shorter distance. Cavalry is used only for
    the remainder that eligible infantry cannot cover. Confirmed sends reduce
    only the request's remaining need; they never reduce a village's declared
    theoretical troop pool.
    """
    if req.get("status") != "active":
        return None
    attack = request_datetime(req)
    now = datetime.now(SERVER_TZ).replace(tzinfo=None)
    remaining = request_remaining(req)
    if attack is None or attack <= now or remaining <= 0:
        return None

    candidates = []
    players = bot.players()
    for player in players.values() if isinstance(players, dict) else []:
        if not isinstance(player, dict):
            continue
        label = _player_label(player)
        for village in player.get("villages", []):
            coords = str(village.get("coordinates", "?"))
            for item in source_village_units(player, village, req):
                normal_deadline = attack - timedelta(seconds=item["no_hero_seconds"])
                with_hero = False
                deadline = normal_deadline
                seconds = item["no_hero_seconds"]

                # The hero is used in the recommendation only when the same
                # troops would otherwise be too late.
                if deadline <= now and item.get("hero_seconds") is not None:
                    hero_deadline = attack - timedelta(seconds=item["hero_seconds"])
                    if hero_deadline > now:
                        with_hero = True
                        deadline = hero_deadline
                        seconds = item["hero_seconds"]

                if deadline <= now:
                    continue

                cavalry = item["key"] in CAVALRY_UNITS
                candidates.append({
                    "player": label,
                    "telegram_id": player.get("telegram_id"),
                    "village": coords,
                    "unit_key": item["key"],
                    "unit_name": item["name"],
                    "available_units": int(item["amount"]),
                    "value": int(item["value"]),
                    "max_def": int(item["amount"]) * int(item["value"]),
                    "distance": float(item["distance"]),
                    "seconds": float(seconds),
                    "deadline": deadline,
                    "with_hero": with_hero,
                    "cavalry": cavalry,
                })

    # Preserve mobile cavalry whenever eligible infantry can do the job.
    candidates.sort(key=lambda x: (
        1 if x["cavalry"] else 0,
        x["distance"],
        x["seconds"],
        x["player"].lower(),
        x["village"],
        x["unit_name"],
    ))

    need = remaining
    chosen = []
    for item in candidates:
        if need <= 0:
            break
        points = min(need, item["max_def"])
        # Cavalry contributes two defence points per registered unit.
        units = min(item["available_units"], (points + item["value"] - 1) // item["value"])
        points = min(need, units * item["value"])
        if points <= 0 or units <= 0:
            continue
        picked = dict(item)
        picked["units"] = units
        picked["def_points"] = points
        chosen.append(picked)
        need -= points

    return {
        "remaining": remaining,
        "covered": remaining - need,
        "deficit": need,
        "items": chosen,
    }


def optimal_plan_text(req, plan):
    previous = _previously_declared_by_village(req)
    lines = [
        f"<b>🤖 ОПТИМАЛЬНЫЙ ПЛАН ЗАЩИТЫ #{req['id']}</b>",
        "",
        f"🎯 Цель: {village_link(req['target_x'], req['target_y'])} — <b>{html.escape(req['target_player'])}</b>",
        f"⚔️ Атака: <b>{req['attack_time_display']}</b>",
        f"🛡 Осталось закрыть: <b>{plan['remaining']}</b> очков",
        "",
    ]

    if plan["items"]:
        lines.append("<b>Рекомендуется:</b>")
        lines.append("")
        for item in plan["items"]:
            troop_icon = "🐎" if item["cavalry"] else "🚶"
            hero = " + герой" if item["with_hero"] else ""
            lines.extend([
                f"🏘 <b>{html.escape(item['village'])}</b> — {html.escape(item['player'])}",
                f"{troop_icon} <b>{item['units']}</b> {html.escape(item['unit_name'])}{hero}"
                + (f" = <b>{item['def_points']}</b> очков" if item["value"] != 1 else ""),
                f"📏 {item['distance']:.1f} поля · отправить до <b>{item['deadline'].strftime('%H:%M:%S')}</b>",
            ])
            already = previous.get(item["village"], 0)
            if already:
                lines.append(f"📩 По этой заявке ранее заявлено из деревни: <b>{already}</b> очков")
            lines.append("")

    infantry_points = sum(x["def_points"] for x in plan["items"] if not x["cavalry"])
    cavalry_points = sum(x["def_points"] for x in plan["items"] if x["cavalry"])
    lines.append(f"📊 План: <b>{plan['covered']} / {plan['remaining']}</b>")
    lines.append(f"🚶 Пехота: <b>{infantry_points}</b> · 🐎 Конница: <b>{cavalry_points}</b>")
    if plan["deficit"] > 0:
        lines.append(f"⚠️ По указанным в настройках войскам не хватает: <b>{plan['deficit']}</b> очков")
    elif cavalry_points == 0:
        lines.append("✅ Заявка теоретически закрывается только пехотой.")
    else:
        lines.append("⚠️ Для полного закрытия по текущему расчёту требуется конница.")

    lines.extend([
        "",
        "ℹ️ План рекомендательный. Он рассчитан по войскам, указанным игроками в настройках; их фактическая доступность боту неизвестна.",
    ])
    return "\n".join(lines)


def _delete_plan_message(req, chat_id=None):
    message_id = req.get("optimal_plan_message_id")
    plan_chat_id = req.get("optimal_plan_chat_id") or chat_id
    if message_id and plan_chat_id:
        try:
            bot.tg("deleteMessage", chat_id=int(plan_chat_id), message_id=int(message_id))
        except Exception as exc:
            print(f"Optimal plan delete failed: request=#{req.get('id')}: {exc}", flush=True)
    req.pop("optimal_plan_message_id", None)
    req.pop("optimal_plan_chat_id", None)
    req.pop("optimal_plan_signature", None)


def refresh_optimal_plans(chat_id=None, force=False):
    """Recalculate active recommendations and repost only when the plan changed."""
    state = load_state()
    target_chat_id = chat_id or state.get("center_chat_id")
    if not target_chat_id:
        return False

    requests = bot.load_json(bot.REQUESTS_FILE, [])
    if not isinstance(requests, list):
        return False

    changed_data = False
    now = datetime.now(SERVER_TZ).replace(tzinfo=None)
    for req in requests:
        attack = request_datetime(req)
        active = (
            req.get("status") == "active"
            and attack is not None
            and attack > now
            and request_remaining(req) > 0
        )
        if not active:
            if req.get("optimal_plan_message_id"):
                _delete_plan_message(req, target_chat_id)
                changed_data = True
            continue

        plan = build_optimal_plan(req)
        if plan is None:
            continue
        text = optimal_plan_text(req, plan)
        # The rendered text is also a stable signature. Deadlines are fixed,
        # so a periodic run changes it only when eligibility/recommendations change.
        signature = text
        if not force and req.get("optimal_plan_signature") == signature:
            continue

        if req.get("optimal_plan_message_id"):
            _delete_plan_message(req, target_chat_id)

        try:
            message = bot.send(int(target_chat_id), text)
            message_id = message.get("message_id") if isinstance(message, dict) else None
            if message_id:
                req["optimal_plan_message_id"] = int(message_id)
                req["optimal_plan_chat_id"] = int(target_chat_id)
                req["optimal_plan_signature"] = signature
                req["optimal_plan_updated_at"] = datetime.now(SERVER_TZ).strftime("%Y-%m-%d %H:%M:%S")
                changed_data = True
        except Exception as exc:
            print(f"Optimal plan publish failed: request=#{req.get('id')}: {exc}", flush=True)

    if changed_data:
        bot.save_json(bot.REQUESTS_FILE, requests)
        bot.persist_data()
    return changed_data

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
            "<b>Ты можешь успеть из:</b>",
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
            points = int(item["amount"]) * int(item.get("value", 1))
            lines.extend([
                f"🛡 {item['amount']} {item['name']}{hero} — <b>{points}</b> очков",
                f"🚨 Отправить до: <b>{item['deadline'].strftime('%H:%M:%S')}</b>",
            ])

        lines.append("Если можешь помочь, открой «Отправить деф» в Центре дефа.")

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
                f"🛡 Собрано: <b>{req.get('collected_def', 0)}</b> / <b>{req['required_def']}</b> очков",
                f"⏳ Осталось собрать: <b>{request_remaining(req)}</b> очков",
                "",
            ])

    lines.append("🛡 Чтобы помочь, нажмите «Отправить деф».")
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
    is_private = message.get("chat", {}).get("type") == "private"
    if not text:
        return
    if is_private:
        return _original_process_text(message)
    if not bot.in_def_thread(message):
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
    if typ == "send_village_amount":
        amount = bot.to_int(text)
        req_id = int(state.get("request_id", 0) or 0)
        village_idx = int(state.get("village_idx", -1))
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
        option = next((x for x in village_send_options(player, req) if x["idx"] == village_idx), None)
        if option is None:
            bot.send(chat_id, "❌ Эта деревня уже не успевает.", request_menu())
            return
        # Registered troop counts are advisory and may be stale. They are used
        # to determine which village/timing variants can theoretically arrive,
        # but never cap the amount a player says they are actually sending.
        eligible_variants = list(option["variants"])
        state["pending_amount"] = amount
        player["state"] = state
        bot.save_players(data)
        bot.send(
            chat_id,
            f"<b>🚨 Когда отправлять</b>\n\n"
            f"🏘 <b>{option['village'].get('coordinates', '?')}</b> → 🎯 <b>{req['target_x']} {req['target_y']}</b>\n"
            f"🛡 <b>{amount}</b> очков\n\nВыбери вариант:",
            speed_variant_keyboard(req_id, village_idx, eligible_variants),
        )
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
    is_private = message.get("chat", {}).get("type") == "private"
    if is_private:
        return _original_callback_query(q)
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
        private_chat_id = player.get("private_chat_id")
        if private_chat_id:
            bot.send_private(
                private_chat_id,
                bot.settings_text(player),
                bot.settings_kb(bot.is_owner(user)),
            )
            bot.answer_callback(q.get("id"), "Настройки отправлены вам в личные сообщения")
        else:
            bot.answer_callback(q.get("id"), "Сначала откройте личный чат с ботом и нажмите /start")
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

    if action == "delete_request_menu":
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
                continue
            active.append(req)
        if changed:
            bot.save_json(bot.REQUESTS_FILE, requests)
            bot.persist_data()

        if not active:
            bot.edit(
                chat_id,
                msg_id,
                "<b>🗑 УДАЛИТЬ ЗАЯВКУ</b>\n\nАктивных заявок нет.",
                request_menu(),
            )
            return

        rows = []
        for req in active:
            rows.append([{
                "text": f"🗑 Заявка #{req['id']} — {req['target_x']}|{req['target_y']}",
                "callback_data": f"delete_req:{req['id']}",
            }])
        rows.append([{"text": "⬅️ Назад", "callback_data": "menu"}])
        bot.edit(
            chat_id,
            msg_id,
            "<b>🗑 УДАЛИТЬ ЗАЯВКУ</b>\n\nВыберите заявку:",
            bot.kb(rows),
        )
        return

    if action.startswith("delete_req:"):
        req_id = int(action.split(":", 1)[1])
        requests = bot.load_json(bot.REQUESTS_FILE, [])
        req = next(
            (r for r in requests if int(r.get("id", -1)) == req_id and r.get("status") == "active"),
            None,
        )
        if req is None:
            bot.edit(chat_id, msg_id, "❌ Эта заявка уже не активна.", request_menu())
            return

        if int(req.get("requester_id", -1)) != int(user.get("id", -2)):
            bot.edit(
                chat_id,
                msg_id,
                "❌ Удалить заявку может только её создатель.",
                request_menu(),
            )
            return

        bot.edit(
            chat_id,
            msg_id,
            (
                f"<b>🗑 УДАЛЕНИЕ ЗАЯВКИ #{req_id}</b>\n\n"
                f"📍 Цель: {village_link(req['target_x'], req['target_y'])}\n"
                f"👤 Игрок: <b>{html.escape(req['target_player'])}</b>\n"
                f"⚔️ Атака: <b>{req['attack_time_display']}</b>\n"
                f"🛡 Деф: <b>{req.get('collected_def', 0)}</b> / <b>{req['required_def']}</b> очков\n\n"
                "Заявка больше не нужна? Она будет снята с активных заявок."
            ),
            bot.kb([
                [{"text": "✅ Да, удалить заявку", "callback_data": f"delete_confirm:{req_id}"}],
                [{"text": "❌ Отмена", "callback_data": f"delete_cancel:{req_id}"}],
            ]),
        )
        return

    if action.startswith("delete_cancel:"):
        refresh_center(chat_id=chat_id, create_if_missing=True)
        return

    if action.startswith("delete_confirm:"):
        req_id = int(action.split(":", 1)[1])
        requests = bot.load_json(bot.REQUESTS_FILE, [])
        if not isinstance(requests, list):
            requests = []
        req = next(
            (r for r in requests if int(r.get("id", -1)) == req_id and r.get("status") == "active"),
            None,
        )
        if req is None:
            bot.edit(chat_id, msg_id, "❌ Эта заявка уже не активна.", request_menu())
            return

        if int(req.get("requester_id", -1)) != int(user.get("id", -2)):
            bot.edit(
                chat_id,
                msg_id,
                "❌ Удалить заявку может только её создатель.",
                request_menu(),
            )
            return

        req["status"] = "cancelled"
        req["cancelled_at"] = datetime.now(SERVER_TZ).strftime("%Y-%m-%d %H:%M:%S")
        req["cancelled_by"] = int(user.get("id", 0))
        req["cancelled_by_username"] = user.get("username", "")
        req["cancelled_by_first_name"] = user.get("first_name", "")

        bot.save_json(bot.REQUESTS_FILE, requests)
        bot.persist_data()
        refresh_optimal_plans(chat_id=chat_id)

        bot.edit(
            chat_id,
            msg_id,
            f"<b>✅ Заявка #{req_id} удалена.</b>\n\nОна больше не отображается среди активных заявок.",
            request_menu(),
        )
        refresh_center(chat_id=chat_id, create_if_missing=True)
        return

    if action.startswith("send_req:"):
        req_id = int(action.split(":", 1)[1])
        requests = bot.load_json(bot.REQUESTS_FILE, [])
        req = next((r for r in requests if int(r.get("id", -1)) == req_id and r.get("status") == "active"), None)
        if req is None or request_closed(req):
            bot.edit(chat_id, msg_id, "❌ Эта заявка уже закрыта.", request_menu())
            return
        player["state"] = None
        bot.save_players(data)
        bot.edit(chat_id, msg_id, send_def_plan_text(player, req), send_def_plan_keyboard(player, req))
        return

    if action.startswith("send_amount:"):
        req_id = int(action.split(":", 1)[1])
        requests = bot.load_json(bot.REQUESTS_FILE, [])
        req = next((r for r in requests if int(r.get("id", -1)) == req_id and r.get("status") == "active"), None)
        if req is None or request_closed(req):
            bot.edit(chat_id, msg_id, "❌ Эта заявка уже закрыта.", request_menu())
            return
        options = village_send_options(player, req)
        if not options:
            bot.edit(chat_id, msg_id, "🔴 Подходящих деревень для этой заявки сейчас нет.", request_menu())
            return
        player["state"] = {"type": "send_draft", "request_id": req_id, "draft": []}
        bot.save_players(data)
        bot.edit(chat_id, msg_id, "<b>🏘 Выберите деревню, из которой отправите деф:</b>", send_village_keyboard(player, req))
        return

    if action.startswith("send_village:"):
        _, req_s, idx_s = action.split(":")
        req_id, village_idx = int(req_s), int(idx_s)
        requests = bot.load_json(bot.REQUESTS_FILE, [])
        req = next((r for r in requests if int(r.get("id", -1)) == req_id and r.get("status") == "active"), None)
        option = next((x for x in village_send_options(player, req) if x["idx"] == village_idx), None) if req else None
        if option is None:
            bot.edit(chat_id, msg_id, "❌ Эта деревня уже не успевает.", request_menu())
            return
        old = player.get("state") if isinstance(player.get("state"), dict) else {}
        draft = old.get("draft", []) if int(old.get("request_id", 0) or 0) == req_id else []
        player["state"] = {"type": "send_village_amount", "request_id": req_id, "village_idx": village_idx, "draft": draft}
        bot.save_players(data)
        bot.send(
            chat_id,
            f"<b>🏘 {option['village'].get('coordinates', '?')}</b>\n"
            f"🛡 В настройках указано: <b>{option['max_def']}</b> очков дефа\n\n"
            "Сколько отправите фактически?\n\n"
            "💡 Пехота = 1 очко · Конница = 2 очка",
            force_reply=True,
        )
        return

    if action.startswith("send_speed:"):
        _, req_s, idx_s, mode = action.split(":")
        req_id, village_idx = int(req_s), int(idx_s)
        state = player.get("state") or {}
        if state.get("type") != "send_village_amount" or int(state.get("request_id", 0)) != req_id or int(state.get("village_idx", -1)) != village_idx:
            bot.edit(chat_id, msg_id, "❌ План отправки устарел. Начните выбор заново.", request_menu())
            return
        requests = bot.load_json(bot.REQUESTS_FILE, [])
        req = next((r for r in requests if int(r.get("id", -1)) == req_id and r.get("status") == "active"), None)
        option = next((x for x in village_send_options(player, req) if x["idx"] == village_idx), None) if req else None
        variant = next((v for v in option["variants"] if v["key"] == mode), None) if option else None
        pending_amount = int(state.get("pending_amount", 0) or 0)
        if variant is None:
            bot.edit(chat_id, msg_id, "❌ Этот вариант уже не успевает.", request_menu())
            return
        deadline = variant["deadline"]
        reminder = deadline - timedelta(minutes=5)
        draft = list(state.get("draft", []))
        draft.append({
            "village_idx": village_idx,
            "village": option["village"].get("coordinates", ""),
            "def_points": int(state["pending_amount"]),
            "speed_mode": mode,
            "gear_label": variant.get("label", ""),
            "deadline_at": deadline.strftime("%Y-%m-%d %H:%M:%S"),
            "deadline": deadline.strftime("%H:%M:%S"),
            "reminder_at": reminder.strftime("%Y-%m-%d %H:%M:%S"),
            "reminder_time": reminder.strftime("%H:%M:%S"),
            "reminder_sent": False,
        })
        player["state"] = {"type": "send_draft", "request_id": req_id, "draft": draft}
        bot.save_players(data)
        used = [x["village_idx"] for x in draft]
        can_add = any(x["idx"] not in used for x in village_send_options(player, req))
        bot.edit(chat_id, msg_id, draft_summary(player["state"], req), draft_actions_keyboard(req_id, can_add))
        return

    if action.startswith("send_add:"):
        req_id = int(action.split(":", 1)[1])
        state = player.get("state") or {}
        requests = bot.load_json(bot.REQUESTS_FILE, [])
        req = next((r for r in requests if int(r.get("id", -1)) == req_id and r.get("status") == "active"), None)
        if req is None or int(state.get("request_id", 0) or 0) != req_id:
            bot.edit(chat_id, msg_id, "❌ План отправки устарел.", request_menu())
            return
        used = [x["village_idx"] for x in state.get("draft", [])]
        bot.edit(chat_id, msg_id, "<b>🏘 Выберите ещё одну деревню:</b>", send_village_keyboard(player, req, used))
        return

    if action.startswith("send_finish:"):
        req_id = int(action.split(":", 1)[1])
        state = player.get("state") or {}
        draft = list(state.get("draft", []))
        requests = bot.load_json(bot.REQUESTS_FILE, [])
        req = next((r for r in requests if int(r.get("id", -1)) == req_id and r.get("status") == "active"), None)
        if req is None or not draft or int(state.get("request_id", 0) or 0) != req_id:
            bot.edit(chat_id, msg_id, "❌ План отправки пуст или заявка уже закрыта.", request_menu())
            return
        total = sum(int(x["def_points"]) for x in draft)
        remaining = request_remaining(req)
        if total > remaining:
            bot.edit(chat_id, msg_id, f"❌ В заявке осталось только <b>{remaining}</b> очков. Уменьшите план.", request_menu())
            player["state"] = None
            bot.save_players(data)
            return
        req.setdefault("contributions", []).append({
            "telegram_id": int(user.get("id", 0)), "username": user.get("username", ""),
            "first_name": user.get("first_name", ""), "def_points": total,
            "plan": draft, "created_at": datetime.now(SERVER_TZ).strftime("%Y-%m-%d %H:%M:%S"),
        })
        req["collected_def"] = int(req.get("collected_def", 0) or 0) + total
        if request_closed(req):
            req["status"] = "closed"
        bot.save_json(bot.REQUESTS_FILE, requests)
        bot.persist_data()
        schedule_defence_reminders(req, req["contributions"][-1])
        refresh_optimal_plans(chat_id=chat_id)
        player["state"] = None
        bot.save_players(data)
        result = draft_summary({"draft": draft}, req) + f"\n\n✅ Записано: <b>{total}</b> очков."
        if req.get("status") != "closed":
            result += f"\nОсталось: <b>{request_remaining(req)}</b> очков."
        bot.edit(chat_id, msg_id, result, request_menu())
        refresh_center(chat_id=chat_id, create_if_missing=True)
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
        refresh_optimal_plans(chat_id=chat_id)
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
