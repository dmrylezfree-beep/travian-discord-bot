import os
import time
import html
import math
from datetime import datetime
from pathlib import Path

import requests

from travian_bot import (
    TELEGRAM_TOKEN,
    TELEGRAM_CHAT_ID,
    SERVER_URL,
    SNAPSHOT_DIR,
    parse_map_data,
    find_snapshot_by_date,
)

# ============================================================
# НАСТРОЙКИ TELEGRAM-БОТА
# ============================================================

FEEDER_THREAD_ID = 75984
PAGE_SIZE = 5

# Необязательно. Если задан — команда /feeders без аргументов
# автоматически использует все деревни этого игрока как точки старта.
FEEDER_PLAYER_ID = os.environ.get("FEEDER_PLAYER_ID")

# Точки старта сохраняются в памяти процесса, чтобы кнопка «Показать ещё»
# продолжала работать, если команда /feeders была вызвана с координатами.
FEEDER_SESSIONS = {}

# Файл состояния long polling. Его НЕ нужно коммитить в Git.
UPDATE_OFFSET_FILE = Path("data/telegram_update_offset.txt")

# ============================================================
# РЕЙТИНГ КОРМУШКИ
# ============================================================

# Население: 8 населения = 1 балл, максимум 30.
POP_POINTS_PER_8 = 1
POP_MAX_SCORE = 30

# Расстояние: <=10 = 40 баллов, 200 = 1 балл.
DISTANCE_MAX_SCORE = 40
DISTANCE_MIN_SCORE = 1
DISTANCE_FULL_SCORE_DISTANCE = 10.0
DISTANCE_MIN_SCORE_DISTANCE = 200.0

# Неактивность: 1 день = 1 балл, 7+ дней = 30.
INACTIVE_MAX_SCORE = 30
INACTIVE_MAX_DAYS = 7

# ============================================================
# TELEGRAM API
# ============================================================


def telegram_request(method, payload=None, timeout=40):
    if not TELEGRAM_TOKEN:
        raise RuntimeError("TELEGRAM_TOKEN не задан")

    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/{method}"
    response = requests.post(url, json=payload or {}, timeout=timeout)
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


def answer_callback(callback_id):
    try:
        telegram_request("answerCallbackQuery", {"callback_query_id": callback_id}, timeout=20)
    except Exception as exc:
        print(f"Не удалось ответить на callback: {exc}")


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

# ============================================================
# SNAPSHOTS
# ============================================================


def snapshot_files():
    if not SNAPSHOT_DIR.exists():
        return []

    result = []
    for path in SNAPSHOT_DIR.glob("**/map_*.sql"):
        name = path.name
        if len(name) != len("map_2026-01-01.sql"):
            continue
        date_string = name[4:-4]
        try:
            date_value = datetime.strptime(date_string, "%Y-%m-%d").date()
        except ValueError:
            continue
        result.append((date_value, path))

    return sorted(result, key=lambda item: item[0])


def load_latest_snapshot():
    files = snapshot_files()
    if not files:
        return None, None, None

    date_value, path = files[-1]
    raw = path.read_text(encoding="utf-8")
    villages, players = parse_map_data(raw)
    return date_value, villages, players


def load_player_population_history(player_id):
    """Возвращает историю общего населения игрока по всем сохранённым snapshots."""
    history = []

    for date_value, path in snapshot_files():
        try:
            raw = path.read_text(encoding="utf-8")
            villages, _ = parse_map_data(raw)
        except (OSError, RuntimeError) as exc:
            print(f"Не удалось прочитать snapshot {path}: {exc}")
            continue

        population = sum(
            village["pop"]
            for village in villages.values()
            if village["uid"] == player_id
        )

        history.append((date_value, population))

    return history


def inactivity_days(player_id, latest_date):
    """Считает количество последовательных суток без изменения населения."""
    history = load_player_population_history(player_id)
    if not history:
        return 0

    history = [(date_value, pop) for date_value, pop in history if date_value <= latest_date]
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

        # История может содержать пропущенные даты. Считаем только
        # непрерывные сутки, чтобы не объявлять игрока неактивным
        # через большой разрыв в snapshots.
        next_date = history[index + 1][0]
        if (next_date - current_date).days != 1:
            break

        days += 1
        previous_pop = current_pop

    return days

# ============================================================
# КОРМУШКИ
# ============================================================


def distance(x1, y1, x2, y2):
    """Формула расстояния Travian: евклидово расстояние."""
    return math.sqrt((x2 - x1) ** 2 + (y2 - y1) ** 2)


def population_score(population):
    return min(POP_MAX_SCORE, population // 8)


def distance_score(dist):
    if dist <= DISTANCE_FULL_SCORE_DISTANCE:
        return DISTANCE_MAX_SCORE

    if dist >= DISTANCE_MIN_SCORE_DISTANCE:
        return DISTANCE_MIN_SCORE

    # Линейная шкала между 10 и 200 клетками:
    # 10 -> 40 баллов, 200 -> 1 балл.
    score = DISTANCE_MAX_SCORE - (
        (dist - DISTANCE_FULL_SCORE_DISTANCE)
        * (DISTANCE_MAX_SCORE - DISTANCE_MIN_SCORE)
        / (DISTANCE_MIN_SCORE_DISTANCE - DISTANCE_FULL_SCORE_DISTANCE)
    )

    return max(DISTANCE_MIN_SCORE, min(DISTANCE_MAX_SCORE, score))


def inactivity_score(days):
    return min(INACTIVE_MAX_SCORE, days)


def player_villages(villages, player_id):
    return [
        village
        for village in villages.values()
        if village["uid"] == player_id
    ]


def parse_player_id_argument(text):
    parts = text.strip().split()
    if len(parts) < 2:
        return None

    try:
        return int(parts[1])
    except ValueError:
        return None


def parse_coordinate_origins(text):
    """
    Дополнительный режим:
    /feeders 10 20
    /feeders 10 20 15 25

    Параметры задаются парами x y.
    """
    parts = text.strip().split()[1:]
    if not parts or len(parts) % 2 != 0:
        return None

    try:
        values = [int(value) for value in parts]
    except ValueError:
        return None

    return list(zip(values[::2], values[1::2]))


def get_origins(text, villages):
    # Явно указанный UID имеет приоритет.
    player_id = parse_player_id_argument(text)
    if player_id is not None:
        origins = player_villages(villages, player_id)
        return origins, player_id

    # Если переданы координаты — используем их.
    coordinates = parse_coordinate_origins(text)
    if coordinates is not None:
        return [
            {"x": str(x), "y": str(y), "uid": -1, "player": "", "name": ""}
            for x, y in coordinates
        ], None

    # Иначе используем настроенного игрока.
    if FEEDER_PLAYER_ID:
        try:
            player_id = int(FEEDER_PLAYER_ID)
        except ValueError:
            raise RuntimeError("FEEDER_PLAYER_ID должен быть числом")

        return player_villages(villages, player_id), player_id

    return [], None


def find_feeders(origins, villages, latest_date):
    # Сначала собираем игроков, чтобы считать население один раз.
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

    # Не показываем владельца точек старта.
    origin_uids = {
        village.get("uid")
        for village in origins
        if village.get("uid") not in (None, -1, 0)
    }

    candidates = []

    for uid, villages_of_player in player_villages_map.items():
        if uid in origin_uids:
            continue

        population = player_pop.get(uid, 0)
        if population <= 0:
            continue

        inactive_days = inactivity_days(uid, latest_date)

        # Кормушка должна иметь хотя бы 1 сутки отсутствия роста.
        if inactive_days < 1:
            continue

        best_village = None
        best_distance = None

        for village in villages_of_player:
            vx = int(village["x"])
            vy = int(village["y"])

            for origin in origins:
                ox = int(origin["x"])
                oy = int(origin["y"])
                dist = distance(ox, oy, vx, vy)

                if best_distance is None or dist < best_distance:
                    best_distance = dist
                    best_village = village

        if best_village is None:
            continue

        pop_points = population_score(population)
        dist_points = distance_score(best_distance)
        inactive_points = inactivity_score(inactive_days)
        total = pop_points + dist_points + inactive_points

        candidates.append({
            "uid": uid,
            "player": player_names.get(uid, ""),
            "alliance": player_alliances.get(uid, ""),
            "population": population,
            "inactive_days": inactive_days,
            "village": best_village,
            "distance": best_distance,
            "pop_points": pop_points,
            "distance_points": dist_points,
            "inactive_points": inactive_points,
            "score": total,
        })

    candidates.sort(
        key=lambda item: (
            -item["score"],
            -item["inactive_days"],
            -item["population"],
            item["distance"],
            item["player"].lower(),
        )
    )

    return candidates

# ============================================================
# ОТЧЁТ
# ============================================================


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
        f"   🎯 население {item['pop_points']} + расстояние {item['distance_points']:.1f} + неактивность {item['inactive_points']}"
        f"\n   🔴 {alliance}"
    )


def make_page(items, page):
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
            "callback_data": f"feeders:{page + 1}",
        })

    if page > 0:
        buttons.append({
            "text": "Назад",
            "callback_data": f"feeders:{page - 1}",
        })

    markup = {"inline_keyboard": [buttons]} if buttons else None
    return text, markup


def handle_feeders(chat_id, message_id, thread_id, command_text):
    if thread_id != FEEDER_THREAD_ID:
        return

    latest_date, villages, players = load_latest_snapshot()

    if latest_date is None:
        send_message(
            chat_id,
            "⚠️ <b>Снимки ещё не найдены.</b>\nСначала должен появиться хотя бы один ежедневный snapshot.",
            FEEDER_THREAD_ID,
        )
        return

    origins, player_id = get_origins(command_text, villages)

    if not origins:
        send_message(
            chat_id,
            "⚠️ Не удалось определить деревни, от которых искать кормушки.\n\n"
            "Можно настроить <code>FEEDER_PLAYER_ID</code> или выполнить команду с UID игрока:\n"
            "<code>/feeders 123456</code>\n\n"
            "Также можно указать координаты напрямую:\n"
            "<code>/feeders 10 20</code>",
            FEEDER_THREAD_ID,
        )
        return

    candidates = find_feeders(origins, villages, latest_date)

    if not candidates:
        send_message(
            chat_id,
            "🌾 <b>Кормушки не найдены.</b>\n"
            f"Актуальный snapshot: <code>{latest_date.isoformat()}</code>.",
            FEEDER_THREAD_ID,
        )
        return

    text, markup = make_page(candidates, 0)
    sent = send_message(chat_id, text, FEEDER_THREAD_ID, markup)

    # Сохраняем точки старта для callback-кнопок.
    if sent and sent.get("message_id"):
        FEEDER_SESSIONS[sent["message_id"]] = {
            "origins": origins,
            "latest_date": latest_date,
        }

# ============================================================
# CALLBACKS
# ============================================================


def handle_callback(callback):
    callback_id = callback.get("id")
    answer_callback(callback_id)

    data = callback.get("data", "")
    message = callback.get("message") or {}
    chat = message.get("chat") or {}
    chat_id = chat.get("id")
    message_id = message.get("message_id")
    thread_id = message.get("message_thread_id")

    if not data.startswith("feeders:"):
        return

    if thread_id != FEEDER_THREAD_ID:
        return

    try:
        page = int(data.split(":", 1)[1])
    except ValueError:
        return

    latest_date, villages, _ = load_latest_snapshot()
    if latest_date is None:
        return

    session = FEEDER_SESSIONS.get(message_id)
    if session:
        origins = session["origins"]
    elif FEEDER_PLAYER_ID:
        try:
            player_id = int(FEEDER_PLAYER_ID)
        except ValueError:
            return
        origins = player_villages(villages, player_id)
    else:
        return

    candidates = find_feeders(origins, villages, latest_date)

    if not candidates:
        return

    page = max(0, min(page, (len(candidates) - 1) // PAGE_SIZE))
    text, markup = make_page(candidates, page)

    try:
        edit_message(chat_id, message_id, text, thread_id, markup)
    except Exception as exc:
        print(f"Не удалось обновить страницу кормушек: {exc}")

# ============================================================
# POLLING
# ============================================================


def load_offset():
    try:
        return int(UPDATE_OFFSET_FILE.read_text(encoding="utf-8").strip())
    except (OSError, ValueError):
        return 0


def save_offset(offset):
    UPDATE_OFFSET_FILE.parent.mkdir(parents=True, exist_ok=True)
    UPDATE_OFFSET_FILE.write_text(str(offset), encoding="utf-8")


def process_update(update):
    if "callback_query" in update:
        handle_callback(update["callback_query"])
        return

    message = update.get("message")
    if not message:
        return

    chat = message.get("chat") or {}
    chat_id = chat.get("id")
    thread_id = message.get("message_thread_id")
    text = message.get("text", "").strip()

    if not chat_id or not text:
        return

    command = text.split()[0].split("@", 1)[0].lower()

    if command == "/feeders":
        handle_feeders(chat_id, message.get("message_id"), thread_id, text)


def run_polling():
    if not TELEGRAM_TOKEN:
        raise RuntimeError("TELEGRAM_TOKEN не задан")

    print("========================================")
    print("       TRAVIAN TELEGRAM BOT")
    print("========================================")
    print(f"Тема кормушек: {FEEDER_THREAD_ID}")

    # Удаляем webhook, если он был установлен ранее.
    try:
        telegram_request("deleteWebhook", {"drop_pending_updates": False}, timeout=30)
    except Exception as exc:
        print(f"Не удалось удалить webhook: {exc}")

    offset = load_offset()

    while True:
        try:
            updates = telegram_request(
                "getUpdates",
                {
                    "offset": offset,
                    "timeout": 50,
                    "allowed_updates": ["message", "callback_query"],
                },
                timeout=60,
            )

            for update in updates or []:
                offset = update["update_id"] + 1
                save_offset(offset)

                try:
                    process_update(update)
                except Exception as exc:
                    print(f"Ошибка обработки update: {exc}")

        except requests.RequestException as exc:
            print(f"Ошибка сети Telegram: {exc}")
            time.sleep(5)
        except Exception as exc:
            print(f"Ошибка polling: {exc}")
            time.sleep(5)


if __name__ == "__main__":
    run_polling()
