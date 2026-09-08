import os
import html
import math
from datetime import datetime

import requests

from travian_bot import (
    TELEGRAM_TOKEN,
    SERVER_URL,
    SNAPSHOT_DIR,
    parse_map_data,
)

FEEDER_THREAD_ID = 75984
PAGE_SIZE = 5
FEEDER_PLAYER_ID = os.environ.get("FEEDER_PLAYER_ID")

# Standard Travian Legends map: -200..200 = 401 tiles.
# Can be overridden if the world has another map size.
MAP_SIZE = int(os.environ.get("TRAVIAN_MAP_SIZE", "401"))

POP_MAX_SCORE = 30
DISTANCE_MAX_SCORE = 40
DISTANCE_MIN_SCORE = 1
DISTANCE_FULL_SCORE_DISTANCE = 10.0
DISTANCE_MIN_SCORE_DISTANCE = 200.0
INACTIVE_MAX_SCORE = 30


def telegram_request(method, payload=None, timeout=40):
    if not TELEGRAM_TOKEN:
        raise RuntimeError("TELEGRAM_TOKEN не задан")
    response = requests.post(
        f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/{method}",
        json=payload or {}, timeout=timeout,
    )
    response.raise_for_status()
    result = response.json()
    if not result.get("ok"):
        raise RuntimeError(f"Telegram API error: {result}")
    return result.get("result")


def send_message(chat_id, text, thread_id=None, reply_markup=None):
    payload = {
        "chat_id": chat_id,
        "text": text,
        "parse_mode": "HTML",
        "disable_web_page_preview": True,
    }
    if thread_id is not None:
        payload["message_thread_id"] = thread_id
    if reply_markup is not None:
        payload["reply_markup"] = reply_markup
    return telegram_request("sendMessage", payload)


def edit_message(chat_id, message_id, text, thread_id=None, reply_markup=None):
    payload = {
        "chat_id": chat_id,
        "message_id": message_id,
        "text": text,
        "parse_mode": "HTML",
        "disable_web_page_preview": True,
    }
    if reply_markup is not None:
        payload["reply_markup"] = reply_markup
    return telegram_request("editMessageText", payload)


def answer_callback(callback_id):
    if not callback_id:
        return
    try:
        telegram_request(
            "answerCallbackQuery",
            {"callback_query_id": callback_id},
            timeout=20,
        )
    except Exception as exc:
        print(f"Не удалось ответить на callback: {exc}")


def snapshot_files():
    if not SNAPSHOT_DIR.exists():
        return []
    result = []
    for path in SNAPSHOT_DIR.glob("**/map_*.sql"):
        name = path.name
        if len(name) != len("map_2026-01-01.sql"):
            continue
        try:
            date_value = datetime.strptime(name[4:-4], "%Y-%m-%d").date()
        except ValueError:
            continue
        result.append((date_value, path))
    return sorted(result, key=lambda item: item[0])


def load_latest_snapshot():
    files = snapshot_files()
    if not files:
        return None, None, None
    date_value, path = files[-1]
    villages, players = parse_map_data(path.read_text(encoding="utf-8"))
    return date_value, villages, players


def load_player_population_history(player_id):
    history = []
    for date_value, path in snapshot_files():
        try:
            villages, _ = parse_map_data(path.read_text(encoding="utf-8"))
        except (OSError, RuntimeError) as exc:
            print(f"Не удалось прочитать snapshot {path}: {exc}")
            continue
        population = sum(
            village["pop"] for village in villages.values()
            if village["uid"] == player_id
        )
        history.append((date_value, population))
    return history


def inactivity_days(player_id, latest_date):
    history = [
        (date_value, pop)
        for date_value, pop in load_player_population_history(player_id)
        if date_value <= latest_date
    ]
    if len(history) < 2:
        return 0

    latest_date_value, latest_pop = history[-1]
    if latest_date_value != latest_date or latest_pop <= 0:
        return 0

    days = 0
    previous_pop = latest_pop
    for index in range(len(history) - 2, -1, -1):
        current_date, current_pop = history[index]
        if current_pop != previous_pop:
            break
        if (history[index + 1][0] - current_date).days != 1:
            break
        days += 1
        previous_pop = current_pop
    return days


def distance(x1, y1, x2, y2):
    """Travian distance: shortest straight-line distance with map wrapping."""
    dx_raw = abs(int(x2) - int(x1))
    dy_raw = abs(int(y2) - int(y1))
    dx = min(dx_raw, MAP_SIZE - dx_raw)
    dy = min(dy_raw, MAP_SIZE - dy_raw)
    return math.sqrt(dx * dx + dy * dy)


def population_score(population):
    return min(POP_MAX_SCORE, population // 8)


def distance_score(dist):
    if dist <= DISTANCE_FULL_SCORE_DISTANCE:
        return DISTANCE_MAX_SCORE
    if dist >= DISTANCE_MIN_SCORE_DISTANCE:
        return DISTANCE_MIN_SCORE
    score = DISTANCE_MAX_SCORE - (
        (dist - DISTANCE_FULL_SCORE_DISTANCE)
        * (DISTANCE_MAX_SCORE - DISTANCE_MIN_SCORE)
        / (DISTANCE_MIN_SCORE_DISTANCE - DISTANCE_FULL_SCORE_DISTANCE)
    )
    return max(DISTANCE_MIN_SCORE, min(DISTANCE_MAX_SCORE, score))


def inactivity_score(days):
    return min(INACTIVE_MAX_SCORE, days)


def player_villages(villages, player_id):
    return [v for v in villages.values() if v["uid"] == player_id]


def parse_origins(origin_spec, villages):
    if origin_spec.startswith("coords:"):
        origins = []
        for pair in origin_spec[7:].split(";"):
            if not pair:
                continue
            x, y = pair.split(",", 1)
            origins.append({"x": x, "y": y, "uid": -1, "player": "", "name": ""})
        return origins

    if origin_spec.startswith("player:"):
        return player_villages(villages, int(origin_spec[7:]))

    if FEEDER_PLAYER_ID:
        return player_villages(villages, int(FEEDER_PLAYER_ID))

    return []


def find_feeders(origins, villages, latest_date):
    player_pop = {}
    player_names = {}
    player_alliances = {}
    player_villages_map = {}

    for village in villages.values():
        uid = village["uid"]
        if uid == 0:
            continue
        player_pop[uid] = player_pop.get(uid, 0) + village["pop"]
        player_names[uid] = village["player"]
        player_alliances[uid] = village["alliance"]
        player_villages_map.setdefault(uid, []).append(village)

    origin_uids = {
        village.get("uid") for village in origins
        if village.get("uid") not in (None, -1, 0)
    }
    candidates = []

    for uid, villages_of_player in player_villages_map.items():
        if uid in origin_uids:
            continue
        population = player_pop.get(uid, 0)
        # No 100-population minimum: any positive population is eligible.
        if population <= 0:
            continue

        inactive = inactivity_days(uid, latest_date)
        if inactive < 1:
            continue

        best_village = None
        best_distance = None
        for village in villages_of_player:
            for origin in origins:
                dist = distance(origin["x"], origin["y"], village["x"], village["y"])
                if best_distance is None or dist < best_distance:
                    best_distance = dist
                    best_village = village

        if best_village is None:
            continue

        pop_points = population_score(population)
        dist_points = distance_score(best_distance)
        inactive_points = inactivity_score(inactive)
        candidates.append({
            "uid": uid,
            "player": player_names.get(uid, ""),
            "alliance": player_alliances.get(uid, ""),
            "population": population,
            "inactive_days": inactive,
            "village": best_village,
            "distance": best_distance,
            "pop_points": pop_points,
            "distance_points": dist_points,
            "inactive_points": inactive_points,
            "score": pop_points + dist_points + inactive_points,
        })

    candidates.sort(key=lambda item: (
        -item["score"], -item["inactive_days"], -item["population"],
        item["distance"], item["player"].lower(),
    ))
    return candidates


def village_link(village):
    x = html.escape(str(village["x"]), quote=True)
    y = html.escape(str(village["y"]), quote=True)
    url = f"{SERVER_URL}/karte.php?x={village['x']}&y={village['y']}"
    return f'<a href="{html.escape(url, quote=True)}">{x}|{y}</a>'


def format_feeder(item, number):
    player = html.escape(str(item["player"]), quote=True)
    alliance = html.escape(str(item["alliance"] or "без альянса"), quote=True)
    village_name = html.escape(str(item["village"]["name"]), quote=True)
    return (
        f"<b>{number}. {player}</b> — {item['score']} баллов\n"
        f"   🏘 {village_name} {village_link(item['village'])}\n"
        f"   👥 население: {item['population']}\n"
        f"   💤 неактивность: {item['inactive_days']} дн.\n"
        f"   📏 расстояние: {item['distance']:.1f}\n"
        f"   🎯 население {item['pop_points']} + расстояние {item['distance_points']:.1f} + неактивность {item['inactive_points']}\n"
        f"   🔴 {alliance}"
    )


def make_page(items, page, origin_spec):
    start = page * PAGE_SIZE
    end = min(start + PAGE_SIZE, len(items))
    chunk = items[start:end]
    text = "🌾 <b>КОРМУШКИ</b>\n\n"
    for index, item in enumerate(chunk, start=start + 1):
        text += format_feeder(item, index) + "\n\n"
    text += f"Показано {start + 1}–{end} из {len(items)}."

    buttons = []
    if end < len(items):
        buttons.append({
            "text": "Показать ещё",
            "callback_data": f"feeders|{page + 1}|{origin_spec}",
        })
    if page > 0:
        buttons.append({
            "text": "Назад",
            "callback_data": f"feeders|{page - 1}|{origin_spec}",
        })
    return text, ({"inline_keyboard": [buttons]} if buttons else None)


def parse_legacy_command(text):
    parts = text.strip().split()
    if len(parts) < 2:
        return ""
    if len(parts) == 2:
        try:
            return f"player:{int(parts[1])}"
        except ValueError:
            return ""
    if len(parts[1:]) % 2 != 0:
        return ""
    try:
        values = [int(v) for v in parts[1:]]
    except ValueError:
        return ""
    return "coords:" + ";".join(
        f"{values[i]},{values[i + 1]}" for i in range(0, len(values), 2)
    )


def process_request():
    action = os.environ.get("ACTION", "command")
    chat_id = os.environ.get("CHAT_ID")
    message_id = os.environ.get("MESSAGE_ID")
    thread_id = int(os.environ.get("THREAD_ID", str(FEEDER_THREAD_ID)))
    origin_spec = os.environ.get("ORIGIN_SPEC", "")
    page = int(os.environ.get("PAGE", "0"))

    if not chat_id:
        raise RuntimeError("CHAT_ID не задан")

    latest_date, villages, _ = load_latest_snapshot()
    if latest_date is None:
        send_message(chat_id, "⚠️ <b>Снимки ещё не найдены.</b>", thread_id)
        return

    origins = parse_origins(origin_spec, villages)
    if not origins:
        send_message(
            chat_id,
            "⚠️ Не удалось определить деревни, от которых искать кормушки.\n\n"
            "Используйте <code>/feeders UID</code> или <code>/feeders X Y</code>.",
            thread_id,
        )
        return

    candidates = find_feeders(origins, villages, latest_date)
    if not candidates:
        send_message(
            chat_id,
            "🌾 <b>Кормушки не найдены.</b>\n"
            f"Актуальный snapshot: <code>{latest_date.isoformat()}</code>.",
            thread_id,
        )
        return

    page = max(0, min(page, (len(candidates) - 1) // PAGE_SIZE))
    text, markup = make_page(candidates, page, origin_spec)

    if action == "callback":
        answer_callback(os.environ.get("CALLBACK_ID", ""))
        if not message_id:
            raise RuntimeError("MESSAGE_ID не задан для callback")
        edit_message(chat_id, int(message_id), text, thread_id, markup)
    else:
        send_message(chat_id, text, thread_id, markup)


if __name__ == "__main__":
    process_request()
