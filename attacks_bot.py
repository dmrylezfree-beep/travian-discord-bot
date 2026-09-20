import os
import json
import re
import time
import math
import html
import subprocess
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import requests


print("ATTACKS BOT STARTED", flush=True)


# ============================================================
# НАСТРОЙКИ
# ============================================================

TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN")
BOT_OWNER_ID = safe_owner_id = int(os.environ.get("BOT_OWNER_ID", "0") or 0)

TELEGRAM_THREAD_ID = 76303

SERVER_NAME = "Азия 7 TEST"
SERVER_URL = "https://ts7.x1.asia.travian.com"

ENEMY_ALLIANCE_NAME = "Hero"
ENEMY_ALLIANCE_ID = 5

# ID нашего альянса.
OUR_ALLIANCE_ID = 9

# Атаки с прибытием в пределах +/- 30 минут
# относятся к одной операции.
ATTACK_OPERATION_WINDOW_SECONDS = 30 * 60

# Время игрового мира Travian — London time.
SERVER_TIMEZONE = ZoneInfo("Europe/London")

MAP_SIZE = 401
BASE_SPEED = 3.0

# При определении примерной Арены допускаем небольшую
# погрешность между рассчитанным временем полёта
# и теоретическим временем для конкретного уровня.
#
# Это не означает, что Арена точно находится в этом
# диапазоне — это только техническая зона допуска.
ARENA_ESTIMATION_TOLERANCE_SECONDS = 30


# ============================================================
# ВРАЖЕСКИЕ ОФФЕРЫ
# ============================================================

ENEMY_OFFERS = [
    {
        "id": "offer_1",
        "x": 42,
        "y": 33,
    },
    {
        "id": "offer_2",
        "x": 139,
        "y": 187,
    },
    {
        "id": "offer_3",
        "x": -8,
        "y": 69,
    },
    {
        "id": "offer_4",
        "x": 16,
        "y": 29,
    },
    {
        "id": "offer_5",
        "x": 15,
        "y": 33,
    },
]


# ============================================================
# ФАЙЛЫ
# ============================================================

DATA_DIR = Path("data/attacks")

OFFERS_FILE = DATA_DIR / "offers.json"
ATTACKS_FILE = DATA_DIR / "attacks.json"
SCOUTS_FILE = DATA_DIR / "scouts.json"
PREFERENCES_FILE = DATA_DIR / "preferences.json"
IMPORTANT_VILLAGES_FILE = DATA_DIR / "important_villages.json"
SCOUT_VILLAGES_FILE = DATA_DIR / "scout_villages.json"

# Общие настройки для всех игроков.
SHARED_PREFERENCES_KEY = "_shared"

SNAPSHOTS_DIR = Path("data/snapshots")


# ============================================================
# TELEGRAM
# ============================================================

API_URL = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}"

POLL_TIMEOUT = 30
REQUEST_TIMEOUT = 40


# ============================================================
# СОХРАНЕНИЕ ДАННЫХ
# ============================================================

def ensure_data():

    DATA_DIR.mkdir(
        parents=True,
        exist_ok=True,
    )

    offers = load_json(
        OFFERS_FILE,
        {},
    )

    if not isinstance(offers, dict):
        offers = {}

    changed = False

    for offer in ENEMY_OFFERS:
        offer_id = offer["id"]

        if offer_id not in offers or not isinstance(offers[offer_id], dict):
            offers[offer_id] = {
                "offer_id": offer_id,
                "x": offer["x"],
                "y": offer["y"],
                "arena": 0,
                "arena_source": None,
                "arena_updated_at": None,
                "arena_status": "unknown",
                "arena_reason": None,
            }
            changed = True
            continue

        state = offers[offer_id]
        for key, value in (
            ("offer_id", offer_id),
            ("x", offer["x"]),
            ("y", offer["y"]),
        ):
            if state.get(key) != value:
                state[key] = value
                changed = True

        for key, default in (
            ("arena", 0),
            ("arena_source", None),
            ("arena_updated_at", None),
            ("arena_status", "unknown"),
            ("arena_reason", None),
        ):
            if key not in state:
                state[key] = default
                changed = True

    if changed or not OFFERS_FILE.exists():
        save_json(
            OFFERS_FILE,
            offers,
        )

    if not ATTACKS_FILE.exists():

        save_json(
            ATTACKS_FILE,
            [],
        )

    if not SCOUTS_FILE.exists():

        save_json(
            SCOUTS_FILE,
            [],
        )

    if not PREFERENCES_FILE.exists():

        save_json(
            PREFERENCES_FILE,
            {},
        )

    if not IMPORTANT_VILLAGES_FILE.exists():
        save_json(IMPORTANT_VILLAGES_FILE, [])

    if not SCOUT_VILLAGES_FILE.exists():
        save_json(SCOUT_VILLAGES_FILE, [])



def load_json(
    path,
    default,
):

    try:

        with path.open(
            "r",
            encoding="utf-8",
        ) as file:

            return json.load(file)

    except (
        FileNotFoundError,
        json.JSONDecodeError,
    ):

        return default


def save_json(
    path,
    data,
):

    path.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    temp_path = path.with_suffix(
        path.suffix + ".tmp"
    )

    with temp_path.open(
        "w",
        encoding="utf-8",
    ) as file:

        json.dump(
            data,
            file,
            ensure_ascii=False,
            indent=2,
        )

    temp_path.replace(path)


def load_offers():

    return load_json(
        OFFERS_FILE,
        {},
    )


def get_all_offers():
    """Возвращает все офферы из offers.json, включая добавленные вручную."""

    offers = load_offers()
    result = []
    seen = set()

    for offer in ENEMY_OFFERS:
        offer_id = offer["id"]
        state = offers.get(offer_id, {})
        item = dict(offer)
        if isinstance(state, dict):
            if state.get("x") is not None:
                item["x"] = state["x"]
            if state.get("y") is not None:
                item["y"] = state["y"]
        result.append(item)
        seen.add(offer_id)

    for offer_id, state in offers.items():
        if offer_id in seen or not isinstance(state, dict):
            continue
        x = safe_int(state.get("x"))
        y = safe_int(state.get("y"))
        if x is None or y is None:
            continue
        result.append({
            "id": offer_id,
            "x": x,
            "y": y,
        })

    return result


def load_attacks():

    return load_json(
        ATTACKS_FILE,
        [],
    )


def load_scouts():

    return load_json(
        SCOUTS_FILE,
        [],
    )


def load_preferences():

    return load_json(
        PREFERENCES_FILE,
        {},
    )


def save_preferences(preferences):

    save_json(
        PREFERENCES_FILE,
        preferences,
    )


def get_user_preferences(user_id):

    preferences = load_preferences()
    key = str(user_id)

    if key not in preferences:

        preferences[key] = {
            "last_arrival_datetime": None,
            "recent_players": [],
            "recent_villages": [],
        }

    return preferences, key, preferences[key]


def get_shared_preferences():

    preferences = load_preferences()

    shared = preferences.get(
        SHARED_PREFERENCES_KEY
    )

    if not isinstance(shared, dict):

        shared = {}

        preferences[
            SHARED_PREFERENCES_KEY
        ] = shared

    return preferences, shared


def get_shared_last_arrival_datetime():

    preferences, shared = get_shared_preferences()

    value = shared.get(
        "last_arrival_datetime"
    )

    if not value:

        return None

    return value


def remember_shared_arrival_datetime(
    arrival_datetime_text
):

    preferences, shared = get_shared_preferences()

    shared[
        "last_arrival_datetime"
    ] = arrival_datetime_text

    shared[
        "last_arrival_updated_at"
    ] = (
        datetime.utcnow()
        .isoformat(
            timespec="seconds"
        )
        + "Z"
    )

    save_preferences(
        preferences
    )

    print(
        "Сохранено общее время входящей атаки: "
        f"{arrival_datetime_text}",
        flush=True,
    )

    persist_attacks_data_to_github()


def remember_recent_value(values, value, limit=20):

    value = str(value)

    result = [
        str(item)
        for item in values
        if str(item) != value
    ]

    result.insert(0, value)

    return result[:limit]


def remember_player(user_id, player_uid):

    preferences, key, user_preferences = get_user_preferences(user_id)

    user_preferences["recent_players"] = remember_recent_value(
        user_preferences.get("recent_players", []),
        player_uid,
    )

    save_preferences(preferences)

    persist_attacks_data_to_github()


def remember_village(user_id, village_vid):

    preferences, key, user_preferences = get_user_preferences(user_id)

    user_preferences["recent_villages"] = remember_recent_value(
        user_preferences.get("recent_villages", []),
        village_vid,
    )

    save_preferences(preferences)

    persist_attacks_data_to_github()


def remember_arrival_datetime(user_id, arrival_datetime_text):

    """
    Совместимость со старым кодом.

    Теперь время входящей атаки хранится не отдельно
    у каждого пользователя, а в общем разделе
    preferences.json.
    """

    remember_shared_arrival_datetime(
        arrival_datetime_text
    )



def load_important_villages():
    data = load_json(IMPORTANT_VILLAGES_FILE, [])
    return data if isinstance(data, list) else []


def load_scout_villages():
    data = load_json(SCOUT_VILLAGES_FILE, [])
    return data if isinstance(data, list) else []


def is_owner(user_id):
    return bool(BOT_OWNER_ID and user_id == BOT_OWNER_ID)


def is_private_chat(chat):
    return chat.get("type") == "private"


def save_important_village(x, y):
    villages = load_important_villages()
    current = next(
        (v for v in load_alliance_villages()
         if v["x"] == x and v["y"] == y),
        None,
    )
    item = {
        "x": x,
        "y": y,
        "player_name": current.get("player_name") if current else None,
        "village_name": current.get("village_name") if current else None,
        "village_id": current.get("vid") if current else None,
    }
    villages = [
        v for v in villages
        if not (safe_int(v.get("x")) == x and safe_int(v.get("y")) == y)
    ]
    villages.append(item)
    save_json(IMPORTANT_VILLAGES_FILE, villages)
    persist_attacks_data_to_github()
    return item


SCOUT_SPEED_BY_TRIBE = {
    1: 16.0,  # Римляне: Equites Legati
    2: 9.0,   # Германцы: Разведчик
    3: 17.0,  # Галлы: Следопыт
    6: 16.0,  # Египтяне: разведчик Сопду
    7: 19.0,  # Гунны: Наблюдатель
    8: 17.0,  # Спартанцы: Разведчик
}


def get_world_village_by_coords(x, y):
    for row in load_latest_map_rows():
        if len(row) <= 10:
            continue
        if safe_int(row[1]) == x and safe_int(row[2]) == y:
            return {
                "x": x,
                "y": y,
                "tribe_id": safe_int(row[3]),
                "vid": safe_int(row[4]),
                "village_name": unquote_sql_value(row[5]) or "Без названия",
                "uid": safe_int(row[6]),
                "player_name": unquote_sql_value(row[7]) or "",
                "alliance_id": safe_int(row[8]),
            }
    return None


def save_scout_village(x, y, arena):
    village = get_world_village_by_coords(x, y)
    if not village or village.get("alliance_id") != OUR_ALLIANCE_ID:
        return None, "Координаты не относятся к деревне нашего альянса."

    tribe_id = village.get("tribe_id")
    speed = SCOUT_SPEED_BY_TRIBE.get(tribe_id)
    if not speed:
        return None, "Не удалось определить скорость разведчика этой нации."

    villages = load_scout_villages()
    item = {
        "x": x,
        "y": y,
        "arena": arena,
        "tribe_id": tribe_id,
        "scout_speed": speed,
        "player_name": village.get("player_name"),
        "village_name": village.get("village_name"),
        "village_id": village.get("vid"),
    }
    villages = [
        v for v in villages
        if not (safe_int(v.get("x")) == x and safe_int(v.get("y")) == y)
    ]
    villages.append(item)
    save_json(SCOUT_VILLAGES_FILE, villages)
    persist_attacks_data_to_github()
    return item, None


def unit_travel_time_seconds(distance, base_speed, arena_level):
    if distance <= 20:
        return distance / base_speed * 3600
    first_part = 20 / base_speed
    speed_after_20 = base_speed * (1 + 0.20 * arena_level)
    second_part = (distance - 20) / speed_after_20
    return (first_part + second_part) * 3600


def load_latest_map_rows():

    latest_file = find_latest_map_sql()

    if latest_file is None:

        print(
            "map.sql не найден.",
            flush=True,
        )

        return []

    print(
        f"Используется map.sql: {latest_file}",
        flush=True,
    )

    try:

        sql = latest_file.read_text(
            encoding="utf-8",
            errors="ignore",
        )

    except Exception as error:

        print(
            "Ошибка чтения map.sql:",
            error,
            flush=True,
        )

        return []

    return extract_insert_rows(
        sql,
        "x_world",
    )


def safe_int(value, default=None):

    # Значение может приходить как из SQL (строкой), так и из JSON
    # (уже готовым int). unquote_sql_value() ожидает строку и поэтому
    # на int выдаёт AttributeError: 'int' object has no attribute 'strip'.
    if isinstance(value, bool):

        return int(value)

    if isinstance(value, int):

        return value

    if isinstance(value, float):

        try:

            return int(value)

        except (
            TypeError,
            ValueError,
        ):

            return default

    if value is None:

        return default

    try:

        value = unquote_sql_value(str(value))
        return int(value)

    except (
        TypeError,
        ValueError,
    ):

        return default


def load_alliance_villages():

    rows = load_latest_map_rows()

    villages = []

    if not rows:

        return villages

    for row in rows:

        if len(row) <= 10:

            continue

        alliance_id = safe_int(row[8])

        if alliance_id != OUR_ALLIANCE_ID:

            continue

        vid = safe_int(row[4])
        x = safe_int(row[1])
        y = safe_int(row[2])
        uid = safe_int(row[6])

        if None in (
            vid,
            x,
            y,
            uid,
        ):

            continue

        villages.append({
            "vid": vid,
            "x": x,
            "y": y,
            "village_name": (
                unquote_sql_value(row[5])
                or "Без названия"
            ),
            "uid": uid,
            "player_name": (
                unquote_sql_value(row[7])
                or f"UID {uid}"
            ),
            "alliance_id": alliance_id,
            "alliance_name": (
                unquote_sql_value(row[9])
                or ""
            ),
            "population": safe_int(
                row[10],
                0,
            ),
        })

    print(
        f"Найдено деревень нашего альянса: {len(villages)}",
        flush=True,
    )

    return villages


def load_reported_villages():
    """Возвращает только координаты, которые хотя бы раз были в отчёте."""

    attacks = load_attacks()
    current_villages = load_alliance_villages()

    by_vid = {
        str(village["vid"]): village
        for village in current_villages
    }
    by_coords = {
        (village["x"], village["y"]): village
        for village in current_villages
    }

    result = {}
    order = []

    for attack in attacks:
        coords = attack.get("own_coords") or {}
        x = safe_int(coords.get("x"))
        y = safe_int(coords.get("y"))
        if x is None or y is None:
            continue

        # Координаты являются уникальным идентификатором пункта списка.
        # Это также объединяет старые отчёты с ручным вводом и отчёты,
        # где у деревни был сохранён vid.
        key = f"coords:{x}:{y}"
        current = by_coords.get((x, y))

        item = {
            "key": key,
            "x": x,
            "y": y,
            "player_name": (
                current.get("player_name")
                if current
                else attack.get("own_player_name")
            ) or "Игрок не найден",
            "player_uid": (
                current.get("uid")
                if current
                else attack.get("own_player_uid")
            ),
            "village_id": (
                current.get("vid")
                if current
                else attack.get("own_village_id")
            ),
            "village_name": (
                current.get("village_name")
                if current
                else attack.get("own_village_name")
            ),
            "last_report": attack.get("created_at") or "",
        }

        if key not in result:
            order.append(key)
        result[key] = item

    return [result[key] for key in reversed(order)]


def reported_villages_keyboard():
    villages = load_reported_villages()
    keyboard = []

    for village in villages:
        player_name = html.escape(
            str(village.get("player_name") or "Игрок не найден")
        )
        keyboard.append([
            {
                "text": (
                    f"🏠 {village['x']} {village['y']} — "
                    f"{player_name}"
                ),
                "callback_data": (
                    f"attack_reported:{village['x']}:{village['y']}"
                ),
            }
        ])

    if not villages:
        keyboard.append([
            {
                "text": "ℹ️ Пока нет сохранённых деревень",
                "callback_data": "attack_manual_coords",
            }
        ])

    keyboard.append([
        {
            "text": "✏️ Ввести координаты вручную",
            "callback_data": "attack_manual_coords",
        }
    ])

    keyboard.append([
        {
            "text": "❌ Отмена",
            "callback_data": "menu",
        }
    ])

    return {
        "inline_keyboard": keyboard
    }


def alliance_players_keyboard(user_id):

    villages = load_alliance_villages()

    preferences, key, user_preferences = get_user_preferences(
        user_id
    )

    recent = [
        str(item)
        for item in user_preferences.get(
            "recent_players",
            [],
        )
    ]

    recent_index = {
        value: index
        for index, value in enumerate(recent)
    }

    players = {}

    for village in villages:

        uid = str(
            village["uid"]
        )

        players.setdefault(
            uid,
            {
                "uid": village["uid"],
                "name": village["player_name"],
                "villages": 0,
            },
        )

        players[uid]["villages"] += 1

    ordered = sorted(
        players.values(),
        key=lambda player: (
            recent_index.get(
                str(player["uid"]),
                999999,
            ),
            str(
                player["name"]
            ).lower(),
        ),
    )

    keyboard = []

    for player in ordered:

        keyboard.append([
            {
                "text": (
                    f"👤 {player['name']} "
                    f"({player['villages']})"
                ),
                "callback_data": (
                    f"attack_player:{player['uid']}"
                ),
            }
        ])

    if not ordered:

        keyboard.append([
            {
                "text": (
                    "⚠️ Игроки не найдены "
                    "в map.sql"
                ),
                "callback_data": (
                    "attack_manual_coords"
                ),
            }
        ])

    keyboard.append([
        {
            "text": (
                "✏️ Ввести координаты вручную"
            ),
            "callback_data": (
                "attack_manual_coords"
            ),
        }
    ])

    keyboard.append([
        {
            "text": "⬅️ Назад",
            "callback_data": "menu",
        }
    ])

    return {
        "inline_keyboard": keyboard
    }


def alliance_villages_keyboard(
    user_id,
    player_uid,
):

    villages = [
        village
        for village in load_alliance_villages()
        if village["uid"] == player_uid
    ]

    preferences, key, user_preferences = get_user_preferences(
        user_id
    )

    recent = [
        str(item)
        for item in user_preferences.get(
            "recent_villages",
            [],
        )
    ]

    recent_index = {
        value: index
        for index, value in enumerate(recent)
    }

    villages.sort(
        key=lambda village: (
            recent_index.get(
                str(village["vid"]),
                999999,
            ),
            str(
                village["village_name"]
            ).lower(),
        )
    )

    keyboard = []

    for village in villages:

        keyboard.append([
            {
                "text": (
                    f"🏠 {village['village_name']} "
                    f"({village['x']}|{village['y']})"
                ),
                "callback_data": (
                    f"attack_village:{village['vid']}"
                ),
            }
        ])

    keyboard.append([
        {
            "text": "⬅️ Другой игрок",
            "callback_data": (
                "attack_back_players"
            ),
        }
    ])

    keyboard.append([
        {
            "text": (
                "✏️ Ввести координаты вручную"
            ),
            "callback_data": (
                "attack_manual_coords"
            ),
        }
    ])

    keyboard.append([
        {
            "text": "❌ Отмена",
            "callback_data": "menu",
        }
    ])

    return {
        "inline_keyboard": keyboard
    }


# ============================================================
# СОХРАНЕНИЕ ИЗМЕНЕНИЙ В GITHUB
# ============================================================

def persist_attacks_data_to_github():

    """
    Сохраняет изменения data/attacks
    обратно в ветку main.
    """

    print(
        "=== НАЧАЛО СОХРАНЕНИЯ В GITHUB ===",
        flush=True,
    )

    try:

        status = subprocess.run(
            [
                "git",
                "status",
                "--porcelain",
                "--",
                "data/attacks",
            ],
            capture_output=True,
            text=True,
            check=True,
        )

        print(
            "Git status:",
            repr(status.stdout),
            flush=True,
        )

        if not status.stdout.strip():

            print(
                "Изменений в data/attacks нет.",
                flush=True,
            )

            return True

        subprocess.run(
            [
                "git",
                "config",
                "user.name",
                "travian-attacks-bot",
            ],
            check=True,
        )

        subprocess.run(
            [
                "git",
                "config",
                "user.email",
                "travian-attacks-bot@users.noreply.github.com",
            ],
            check=True,
        )

        print(
            "Git add...",
            flush=True,
        )

        subprocess.run(
            [
                "git",
                "add",
                "data/attacks/offers.json",
                "data/attacks/attacks.json",
                "data/attacks/scouts.json",
                "data/attacks/preferences.json",
            ],
            check=True,
        )

        print(
            "Git commit...",
            flush=True,
        )

        commit = subprocess.run(
            [
                "git",
                "commit",
                "-m",
                "Update attacks bot data",
            ],
            capture_output=True,
            text=True,
        )

        print(
            "Git commit stdout:",
            commit.stdout,
            flush=True,
        )

        print(
            "Git commit stderr:",
            commit.stderr,
            flush=True,
        )

        if commit.returncode != 0:

            print(
                "Git commit не выполнен.",
                flush=True,
            )

            return False

        print(
            "Git fetch origin main...",
            flush=True,
        )

        fetch = subprocess.run(
            [
                "git",
                "fetch",
                "origin",
                "main",
            ],
            capture_output=True,
            text=True,
        )

        print(
            "Git fetch stdout:",
            fetch.stdout,
            flush=True,
        )

        print(
            "Git fetch stderr:",
            fetch.stderr,
            flush=True,
        )

        if fetch.returncode != 0:

            print(
                "Git fetch не выполнен.",
                flush=True,
            )

            return False

        print(
            "Git rebase origin/main...",
            flush=True,
        )

        rebase = subprocess.run(
            [
                "git",
                "rebase",
                "origin/main",
            ],
            capture_output=True,
            text=True,
        )

        print(
            "Git rebase stdout:",
            rebase.stdout,
            flush=True,
        )

        print(
            "Git rebase stderr:",
            rebase.stderr,
            flush=True,
        )

        if rebase.returncode != 0:

            print(
                "Git rebase не выполнен.",
                flush=True,
            )

            print(
                "Пытаемся отменить rebase...",
                flush=True,
            )

            subprocess.run(
                [
                    "git",
                    "rebase",
                    "--abort",
                ],
                capture_output=True,
                text=True,
            )

            return False

        print(
            "Git push origin HEAD:main...",
            flush=True,
        )

        push = subprocess.run(
            [
                "git",
                "push",
                "origin",
                "HEAD:main",
            ],
            capture_output=True,
            text=True,
        )

        print(
            "Git push stdout:",
            push.stdout,
            flush=True,
        )

        print(
            "Git push stderr:",
            push.stderr,
            flush=True,
        )

        if push.returncode != 0:

            print(
                "Git push НЕ выполнен.",
                flush=True,
            )

            return False

        print(
            "Данные attacks bot успешно сохранены в GitHub.",
            flush=True,
        )

        print(
            "=== СОХРАНЕНИЕ В GITHUB УСПЕШНО ===",
            flush=True,
        )

        return True

    except Exception as error:

        print(
            "Ошибка сохранения в GitHub:",
            repr(error),
            flush=True,
        )

        print(
            "=== СОХРАНЕНИЕ В GITHUB НЕ УДАЛОСЬ ===",
            flush=True,
        )

        return False


# ============================================================
# ПОИСК ПОСЛЕДНЕГО MAP.SQL
# ============================================================

def find_latest_map_sql():

    if not SNAPSHOTS_DIR.exists():

        return None

    files = list(
        SNAPSHOTS_DIR.rglob(
            "map_*.sql"
        )
    )

    if not files:

        return None

    return max(
        files,
        key=lambda path: path.as_posix(),
    )


# ============================================================
# РАЗБОР SQL
# ============================================================

def split_sql_values(text):

    values = []

    current = []

    in_string = False
    escape = False

    for char in text:

        if escape:

            current.append(char)

            escape = False

            continue

        if char == "\\" and in_string:

            current.append(char)

            escape = True

            continue

        if char == "'":

            in_string = not in_string

            current.append(char)

            continue

        if char == "," and not in_string:

            values.append(
                "".join(current).strip()
            )

            current = []

            continue

        current.append(char)

    values.append(
        "".join(current).strip()
    )

    return values


def unquote_sql_value(value):

    if value is None:

        return None

    value = value.strip()

    if value.upper() == "NULL":

        return None

    if (
        len(value) >= 2
        and value[0] == "'"
        and value[-1] == "'"
    ):

        value = value[1:-1]

        value = value.replace(
            "\\'",
            "'",
        )

        value = value.replace(
            "\\\\",
            "\\",
        )

        value = value.replace(
            "''",
            "'",
        )

    return value


def extract_insert_rows(
    sql,
    table_name,
):

    rows = []

    pattern = re.compile(
        rf"INSERT\s+INTO\s+`?{re.escape(table_name)}`?"
        rf"\s*(?:\([^;]*?\))?"
        rf"\s*VALUES\s*(.*?);",
        re.IGNORECASE | re.DOTALL,
    )

    for match in pattern.finditer(sql):

        values_block = match.group(1)

        current = []

        depth = 0

        in_string = False

        escape = False

        tuples = []

        for char in values_block:

            if escape:

                current.append(char)

                escape = False

                continue

            if char == "\\" and in_string:

                current.append(char)

                escape = True

                continue

            if char == "'":

                in_string = not in_string

                if depth > 0:

                    current.append(char)

                continue

            if not in_string:

                if char == "(":

                    if depth == 0:

                        current = []

                    depth += 1

                    current.append(char)

                    continue

                if char == ")":

                    depth -= 1

                    current.append(char)

                    if depth == 0:

                        tuples.append(
                            "".join(current)
                        )

                        current = []

                    continue

            if depth > 0:

                current.append(char)

        for row_text in tuples:

            if (
                row_text.startswith("(")
                and row_text.endswith(")")
            ):

                row_text = row_text[1:-1]

                rows.append(
                    split_sql_values(
                        row_text
                    )
                )

    return rows


# ============================================================
# ВЛАДЕЛЬЦЫ ОФФЕРОВ
# ============================================================

def load_offer_owners():

    rows = load_latest_map_rows()
    target_coordinates = {
        (
            offer["x"],
            offer["y"],
        )
        for offer in get_all_offers()
    }

    owners = {}

    for row in rows:

        if len(row) <= 7:

            continue

        x = safe_int(row[1])
        y = safe_int(row[2])

        if x is None or y is None:

            continue

        coordinate = (
            x,
            y,
        )

        if coordinate not in target_coordinates:

            continue

        player_name = unquote_sql_value(
            row[7]
        )

        if player_name:

            owners[coordinate] = player_name

    print(
        "Найдено владельцев:",
        len(owners),
        "/",
        len(target_coordinates),
        flush=True,
    )

    for coordinate in sorted(target_coordinates):

        print(
            f"{coordinate}: "
            f"{owners.get(coordinate, 'не найден')}",
            flush=True,
        )

    return owners



offer_owners = {}


# ============================================================
# TELEGRAM API
# ============================================================

def telegram(
    method,
    **kwargs,
):

    response = requests.post(
        f"{API_URL}/{method}",
        json=kwargs,
        timeout=REQUEST_TIMEOUT,
    )

    response.raise_for_status()

    result = response.json()

    if not result.get("ok"):

        raise RuntimeError(
            result
        )

    return result.get(
        "result"
    )


def send_message(
    chat_id,
    text,
    reply_markup=None,
    thread_id=TELEGRAM_THREAD_ID,
):

    data = {
        "chat_id": chat_id,
        "text": text,
        "parse_mode": "HTML",
    }

    # message_thread_id допустим только для сообщения внутри forum-topic.
    # В личных сообщениях Telegram возвращает 400 Bad Request, если передать
    # ID групповой ветки. Поэтому ветку добавляем только когда явно пишем
    # в групповой чат, а для лички (chat_id == user_id) не передаём её.
    if (
        thread_id is not None
        and chat_id != BOT_OWNER_ID
    ):

        data[
            "message_thread_id"
        ] = thread_id

    if reply_markup is not None:

        data[
            "reply_markup"
        ] = reply_markup

    return telegram(
        "sendMessage",
        **data,
    )


def answer_callback(
    callback_id,
    text=None,
):

    data = {
        "callback_query_id": callback_id,
    }

    if text:

        data["text"] = text

    return telegram(
        "answerCallbackQuery",
        **data,
    )


def edit_message(
    chat_id,
    message_id,
    text,
    reply_markup=None,
):

    data = {
        "chat_id": chat_id,
        "message_id": message_id,
        "text": text,
        "parse_mode": "HTML",
    }

    if reply_markup is not None:

        data[
            "reply_markup"
        ] = reply_markup

    return telegram(
        "editMessageText",
        **data,
    )


# ============================================================
# КЛАВИАТУРЫ ДЛЯ ВВОДА
# ============================================================

def input_keyboard():

    return {
        "force_reply": True,
        "selective": False,
        "input_field_placeholder": "Введите ответ…",
    }


def cancel_keyboard():

    return {
        "inline_keyboard": [
            [
                {
                    "text": "❌ Отмена",
                    "callback_data": "menu",
                }
            ]
        ]
    }


# ============================================================
# ВАЛИДАЦИЯ
# ============================================================

COORDINATE_RE = re.compile(
    r"^\s*(-?\d+)\s+(-?\d+)\s*$"
)

DATETIME_RE = re.compile(
    r"^\s*(\d{1,2})\."
    r"(\d{1,2})\."
    r"(\d{4})\s+"
    r"(\d{1,2}):"
    r"(\d{2}):"
    r"(\d{2})\s*$"
)

DURATION_HMS_RE = re.compile(
    r"^\s*(\d+):(\d{1,2})(?::(\d{1,2}))?\s*$"
)


def parse_coordinates(text):

    match = COORDINATE_RE.match(
        text
    )

    if not match:

        return None

    x = int(
        match.group(1)
    )

    y = int(
        match.group(2)
    )

    if not (
        -200 <= x <= 200
    ):

        return None

    if not (
        -200 <= y <= 200
    ):

        return None

    return (
        x,
        y,
    )


def parse_server_datetime(text):

    """
    Разбирает серверные дату и время.

    Формат:
        DD.MM.YYYY HH:MM:SS

    Значение трактуется исключительно как
    серверная дата/время Travian.
    """

    text = text.strip()

    formats = (
        "%d.%m.%Y %H:%M:%S",
        "%d.%m.%Y %H:%M",
    )

    for fmt in formats:

        try:

            value = datetime.strptime(
                text,
                fmt,
            )

            return value

        except ValueError:

            continue

    return None


def format_server_datetime(value):

    return value.strftime(
        "%d.%m.%Y %H:%M:%S"
    )


def format_duration(seconds):

    seconds = int(
        round(seconds)
    )

    if seconds < 0:

        seconds = 0

    hours = seconds // 3600

    minutes = (
        seconds % 3600
    ) // 60

    remaining_seconds = (
        seconds % 60
    )

    return (
        f"{hours:02d}:"
        f"{minutes:02d}:"
        f"{remaining_seconds:02d}"
    )


def parse_duration(text):

    """
    Разбирает длительность отсутствия игрока.

    Поддерживаемые форматы:

    1. HH:MM:SS
       например 01:30:00

    2. H:MM
       например 1:30

    3. Одно целое число
       трактуется как количество минут.
       например 90 = 01:30:00
    """

    text = text.strip()

    if not text:

        return None

    if re.fullmatch(
        r"\d+",
        text,
    ):

        minutes = int(text)

        if minutes < 0:

            return None

        return minutes * 60

    match = DURATION_HMS_RE.match(
        text
    )

    if not match:

        return None

    first = int(
        match.group(1)
    )

    second = int(
        match.group(2)
    )

    third_text = match.group(3)

    if third_text is None:

        hours = first
        minutes = second
        seconds = 0

    else:

        hours = first
        minutes = second
        seconds = int(
            third_text
        )

    if minutes >= 60:

        return None

    if seconds >= 60:

        return None

    total_seconds = (
        hours * 3600
        + minutes * 60
        + seconds
    )

    return total_seconds


def parse_integer(text):

    try:

        return int(
            text.strip()
        )

    except ValueError:

        return None


def format_range(levels):

    if not levels:

        return "нет допустимых уровней"

    levels = sorted(
        set(levels)
    )

    ranges = []

    start = levels[0]

    previous = levels[0]

    for level in levels[1:]:

        if level == previous + 1:

            previous = level

        else:

            ranges.append(
                (
                    start,
                    previous,
                )
            )

            start = level

            previous = level

    ranges.append(
        (
            start,
            previous,
        )
    )

    result = []

    for start, end in ranges:

        if start == end:

            result.append(
                str(start)
            )

        else:

            result.append(
                f"{start}–{end}"
            )

    return ", ".join(
        result
    )


# ============================================================
# РАССТОЯНИЕ TRAVIAN
# ============================================================

def travian_distance(
    x1,
    y1,
    x2,
    y2,
):

    raw_dx = abs(
        x2 - x1
    )

    raw_dy = abs(
        y2 - y1
    )

    dx = min(
        raw_dx,
        MAP_SIZE - raw_dx,
    )

    dy = min(
        raw_dy,
        MAP_SIZE - raw_dy,
    )

    return math.sqrt(
        dx * dx
        + dy * dy
    )


# ============================================================
# ВРЕМЯ ДВИЖЕНИЯ
# ============================================================

def travel_time_seconds(
    distance,
    arena_level,
):

    if distance <= 20:

        return (
            distance
            / BASE_SPEED
            * 3600
        )

    speed_after_20 = (
        BASE_SPEED
        * (
            1
            + 0.20 * arena_level
        )
    )

    first_part = (
        20 / BASE_SPEED
    )

    second_part = (
        (distance - 20)
        / speed_after_20
    )

    return (
        first_part
        + second_part
    ) * 3600


def possible_arena_levels(
    distance,
    travel_seconds,
):

    """
    Определяет уровни Арены, теоретическое
    время движения которых находится рядом
    с фактически рассчитанным временем полёта.

    Используется для старой/точечной оценки
    и для совместимости со скаут-проверкой.
    """

    target_time = float(
        travel_seconds
    )

    possible = []

    for arena in range(
        0,
        21,
    ):

        theoretical_time = travel_time_seconds(
            distance,
            arena,
        )

        difference = abs(
            theoretical_time
            - target_time
        )

        if (
            difference
            <= ARENA_ESTIMATION_TOLERANCE_SECONDS
        ):

            possible.append(
                arena
            )

    return possible


def possible_arena_levels_by_time_range(
    distance,
    min_travel_seconds,
    max_travel_seconds,
):

    """
    Определяет возможные уровни Арены,
    если известно не точное время в пути,
    а его диапазон.

    Для каждого уровня проверяется,
    попадает ли теоретическое время движения
    в допустимый диапазон с учётом технической
    погрешности.
    """

    lower = min(
        float(min_travel_seconds),
        float(max_travel_seconds),
    )

    upper = max(
        float(min_travel_seconds),
        float(max_travel_seconds),
    )

    possible = []

    for arena in range(
        0,
        21,
    ):

        theoretical_time = travel_time_seconds(
            distance,
            arena,
        )

        if (
            theoretical_time
            >= lower - ARENA_ESTIMATION_TOLERANCE_SECONDS
            and theoretical_time
            <= upper + ARENA_ESTIMATION_TOLERANCE_SECONDS
        ):

            possible.append(
                arena
            )

    return possible


def estimate_arena_level(
    distance,
    travel_seconds,
):

    """
    Возвращает ближайший к фактическому
    времени в пути уровень Арены.

    Это именно оценка, а не подтверждённый
    уровень.
    """

    target_time = float(
        travel_seconds
    )

    candidates = []

    for arena in range(
        0,
        21,
    ):

        theoretical_time = travel_time_seconds(
            distance,
            arena,
        )

        difference = abs(
            theoretical_time
            - target_time
        )

        candidates.append(
            (
                difference,
                arena,
                theoretical_time,
            )
        )

    candidates.sort(
        key=lambda item: item[0]
    )

    difference, arena, theoretical_time = candidates[0]

    return {
        "arena": arena,
        "difference_seconds": difference,
        "theoretical_seconds": theoretical_time,
    }


def estimate_arena_for_time_range(
    distance,
    min_travel_seconds,
    max_travel_seconds,
):

    """
    Выбирает наиболее близкий уровень Арены
    к середине возможного диапазона времени в пути.
    """

    midpoint = (
        float(min_travel_seconds)
        + float(max_travel_seconds)
    ) / 2

    return estimate_arena_level(
        distance,
        midpoint,
    )


# ============================================================
# ОФФЕРЫ
# ============================================================

def get_offer(
    offer_id,
):

    offers = load_offers()

    return offers.get(
        offer_id
    )


def set_arena(
    offer_id,
    arena,
    source,
    reason,
):

    offers = load_offers()

    if offer_id not in offers:

        print(
            f"Оффер {offer_id} не найден в offers.json.",
            flush=True,
        )

        return False

    old_arena = offers[offer_id].get(
        "arena",
        0,
    )

    print(
        f"Изменение Арены: "
        f"{offer_id}: {old_arena} -> {arena}",
        flush=True,
    )

    offers[offer_id][
        "arena"
    ] = arena

    offers[offer_id][
        "arena_source"
    ] = source

    offers[offer_id][
        "arena_updated_at"
    ] = (
        datetime.utcnow()
        .isoformat(
            timespec="seconds"
        )
        + "Z"
    )

    offers[offer_id][
        "arena_status"
    ] = "confirmed"

    offers[offer_id][
        "arena_reason"
    ] = reason

    save_json(
        OFFERS_FILE,
        offers,
    )

    print(
        "offers.json изменён локально.",
        flush=True,
    )

    github_saved = persist_attacks_data_to_github()

    if github_saved:

        print(
            "Арена успешно сохранена в GitHub.",
            flush=True,
        )

    else:

        print(
            "Арена изменена локально, "
            "но сохранить изменение в GitHub НЕ удалось.",
            flush=True,
        )

    return github_saved


def get_offer_owner(
    offer,
):

    if not isinstance(offer, dict):

        return None

    x = safe_int(offer.get("x"))
    y = safe_int(offer.get("y"))

    if x is None or y is None:

        return None

    # Для офферов, добавленных уже после запуска бота,
    # стартовый кэш offer_owners ещё не содержит владельца.
    # Поэтому всегда проверяем координаты в последнем снимке мира.
    rows = load_latest_map_rows()

    for row in rows:

        if len(row) <= 7:

            continue

        row_x = safe_int(row[1])
        row_y = safe_int(row[2])

        if row_x != x or row_y != y:

            continue

        player_name = unquote_sql_value(row[7])

        if player_name:

            return player_name

    # Если в последнем снимке деревня не найдена, сохраняем
    # старое поведение через кэш.
    return offer_owners.get((x, y))


def offers_keyboard(
    prefix,
):

    offers = load_offers()
    all_offers = get_all_offers()

    keyboard = []

    for offer in all_offers:

        state = offers.get(
            offer["id"],
            {},
        )

        arena = state.get(
            "arena",
            0,
        )

        if arena == 0:

            arena_text = "?"

        else:

            arena_text = str(
                arena
            )

        owner = get_offer_owner(
            offer
        )

        if owner:

            owner_text = owner

        else:

            owner_text = (
                "Владелец не найден"
            )

        keyboard.append(
            [
                {
                    "text": (
                        f"{owner_text} — "
                        f"({offer['x']} {offer['y']}) — "
                        f"A{arena_text}"
                    ),
                    "callback_data": (
                        f"{prefix}:"
                        f"{offer['id']}"
                    ),
                }
            ]
        )

    if prefix == "attack_offer":
        keyboard.append(
            [
                {
                    "text": "✏️ Ввести координаты оффера",
                    "callback_data": "attack_manual_offer",
                }
            ]
        )

    keyboard.append(
        [
            {
                "text": "⬅️ Назад",
                "callback_data": "menu",
            }
        ]
    )

    return {
        "inline_keyboard": keyboard
    }



# ============================================================
# ID
# ============================================================

def next_id(
    items,
    prefix,
):

    highest = 0

    for item in items:

        value = item.get(
            "id",
            "",
        )

        match = re.match(
            rf"^{re.escape(prefix)}_(\d+)$",
            value,
        )

        if match:

            highest = max(
                highest,
                int(
                    match.group(1)
                ),
            )

    return (
        f"{prefix}_{highest + 1}"
    )


# ============================================================
# ВХОДЯЩАЯ АТАКА
# ============================================================

def parse_arrival_datetime(text):

    return parse_server_datetime(
        text
    )


def format_arrival_datetime(value):

    return format_server_datetime(
        value
    )


def operation_ids(attacks):

    return [
        attack.get("operation_id")
        for attack in attacks
        if attack.get("operation_id")
    ]


def next_operation_id(attacks):

    highest = 0

    for operation_id in operation_ids(attacks):

        match = re.match(
            r"^operation_(\d+)$",
            str(operation_id),
        )

        if match:

            highest = max(
                highest,
                int(
                    match.group(1)
                ),
            )

    return f"operation_{highest + 1}"


def close_expired_operations():

    attacks = load_attacks()

    now = datetime.now(
        SERVER_TIMEZONE
    ).replace(
        tzinfo=None
    )

    changed = False

    operation_times = {}

    for attack in attacks:

        operation_id = attack.get(
            "operation_id"
        )

        arrival_text = attack.get(
            "operation_arrival_datetime"
        )

        if (
            not operation_id
            or not arrival_text
        ):

            continue

        try:

            arrival = datetime.fromisoformat(
                arrival_text
            )

        except ValueError:

            continue

        operation_times.setdefault(
            operation_id,
            arrival,
        )

    expired_ids = {
        operation_id
        for operation_id, arrival
        in operation_times.items()
        if arrival <= now
    }

    if not expired_ids:

        return False

    for attack in attacks:

        if (
            attack.get(
                "operation_id"
            ) in expired_ids
            and attack.get(
                "operation_status"
            ) == "active"
        ):

            attack[
                "operation_status"
            ] = "closed"

            changed = True

    if changed:

        save_json(
            ATTACKS_FILE,
            attacks,
        )

        persist_attacks_data_to_github()

    return changed


def find_or_create_operation(
    attacks,
    arrival_datetime,
):

    close_expired_operations()

    attacks = load_attacks()

    candidates = {}

    for attack in attacks:

        operation_id = attack.get(
            "operation_id"
        )

        operation_status = attack.get(
            "operation_status"
        )

        operation_arrival = attack.get(
            "operation_arrival_datetime"
        )

        if (
            not operation_id
            or operation_status != "active"
            or not operation_arrival
        ):

            continue

        try:

            canonical = datetime.fromisoformat(
                operation_arrival
            )

        except ValueError:

            continue

        candidates.setdefault(
            operation_id,
            canonical,
        )

    matching = []

    for operation_id, canonical in candidates.items():

        difference = abs(
            (
                arrival_datetime
                - canonical
            ).total_seconds()
        )

        if (
            difference
            <= ATTACK_OPERATION_WINDOW_SECONDS
        ):

            matching.append(
                (
                    difference,
                    operation_id,
                    canonical,
                )
            )

    if matching:

        matching.sort(
            key=lambda item: item[0]
        )

        _, operation_id, canonical = matching[0]

        return (
            operation_id,
            canonical,
        )

    operation_id = next_operation_id(
        attacks
    )

    return (
        operation_id,
        arrival_datetime,
    )


def create_attack(session):

    attacks = load_attacks()

    own_x, own_y = session[
        "own_coords"
    ]

    offer = get_offer(
        session["offer_id"]
    )

    distance = travian_distance(
        own_x,
        own_y,
        offer["x"],
        offer["y"],
    )

    travel_seconds = session[
        "travel_seconds"
    ]

    min_travel_seconds = session.get(
        "min_travel_seconds",
        travel_seconds,
    )

    max_travel_seconds = session.get(
        "max_travel_seconds",
        travel_seconds,
    )

    possible = possible_arena_levels_by_time_range(
        distance,
        min_travel_seconds,
        max_travel_seconds,
    )

    arena_estimate = estimate_arena_for_time_range(
        distance,
        min_travel_seconds,
        max_travel_seconds,
    )

    current_arena = offer.get(
        "arena",
        0,
    )

    owner = get_offer_owner(
        offer
    )

    operation_id, operation_arrival = find_or_create_operation(
        attacks,
        session["arrival_datetime"],
    )

    attack = {
        "id": next_id(
            attacks,
            "attack",
        ),

        "created_at": (
            datetime.utcnow()
            .isoformat(
                timespec="seconds"
            )
            + "Z"
        ),

        "report_date": session.get(
            "report_date"
        ),

        "report_message_datetime": session.get(
            "report_message_datetime"
        ),

        "server_name": SERVER_NAME,

        "server_url": SERVER_URL,

        "own_player_uid": session.get(
            "own_player_uid"
        ),

        "own_player_name": session.get(
            "own_player_name"
        ),

        "own_village_id": session.get(
            "own_village_id"
        ),

        "own_village_name": session.get(
            "own_village_name"
        ),

        "own_coords": {
            "x": own_x,
            "y": own_y,
        },

        "offer_id": offer[
            "offer_id"
        ],

        "offer_coords": {
            "x": offer["x"],
            "y": offer["y"],
        },

        "offer_owner": owner,

        "waves": session[
            "waves"
        ],

        "arrival_datetime": (
            session[
                "arrival_datetime"
            ].isoformat(
                timespec="seconds"
            )
        ),

        "arrival_datetime_text": (
            session[
                "arrival_datetime_text"
            ]
        ),

        "detected_server_datetime": (
            session[
                "detected_datetime"
            ].isoformat(
                timespec="seconds"
            )
        ),

        "detected_server_datetime_text": (
            session[
                "detected_datetime_text"
            ]
        ),

        "offline_seconds": session.get(
            "offline_seconds",
            0,
        ),

        "offline_time_text": session.get(
            "offline_time_text",
            "00:00:00",
        ),

        "possible_send_from_datetime": (
            session[
                "possible_send_from_datetime"
            ].isoformat(
                timespec="seconds"
            )
        ),

        "possible_send_from_datetime_text": (
            session[
                "possible_send_from_datetime_text"
            ]
        ),

        "possible_send_to_datetime": (
            session[
                "possible_send_to_datetime"
            ].isoformat(
                timespec="seconds"
            )
        ),

        "possible_send_to_datetime_text": (
            session[
                "possible_send_to_datetime_text"
            ]
        ),

        "operation_id": operation_id,

        "operation_arrival_datetime": (
            operation_arrival.isoformat(
                timespec="seconds"
            )
        ),

        "operation_status": "active",

        "travel_time": (
            session[
                "travel_time_text"
            ]
        ),

        "travel_seconds": (
            session[
                "travel_seconds"
            ]
        ),

        "min_travel_seconds": (
            min_travel_seconds
        ),

        "max_travel_seconds": (
            max_travel_seconds
        ),

        "min_travel_time": (
            format_duration(
                min_travel_seconds
            )
        ),

        "max_travel_time": (
            format_duration(
                max_travel_seconds
            )
        ),

        "distance": round(
            distance,
            4,
        ),

        "base_speed": BASE_SPEED,

        "possible_arena_levels": possible,

        "possible_arena_text": format_range(
            possible
        ),

        "estimated_arena_level": (
            arena_estimate[
                "arena"
            ]
        ),

        "estimated_arena_difference_seconds": round(
            arena_estimate[
                "difference_seconds"
            ],
            2,
        ),

        "estimated_arena_theoretical_time": (
            format_duration(
                arena_estimate[
                    "theoretical_seconds"
                ]
            )
        ),

        "arena_at_report": current_arena,

        "arena_at_report_source": offer.get(
            "arena_source"
        ),

        "status": "new",
    }

    attacks.append(
        attack
    )

    save_json(
        ATTACKS_FILE,
        attacks,
    )

    print(
        f"Создана атака {attack['id']} "
        f"в операции {operation_id}.",
        flush=True,
    )

    print(
        f"Расстояние: {distance:.4f}",
        flush=True,
    )

    print(
        f"Время в пути: "
        f"{session['travel_time_text']}",
        flush=True,
    )

    print(
        f"Возможный диапазон времени в пути: "
        f"{format_duration(min_travel_seconds)} — "
        f"{format_duration(max_travel_seconds)}",
        flush=True,
    )

    print(
        f"Возможная Арена: "
        f"{format_range(possible)}",
        flush=True,
    )

    persist_attacks_data_to_github()

    return attack


def find_attack(
    attack_id,
):

    attacks = load_attacks()

    for attack in attacks:

        if (
            attack.get("id")
            == attack_id
        ):

            return attack

    return None


# ============================================================
# СКАУТ
# ============================================================

def add_scout_evidence(
    offer_id,
    attack_id,
    tested_arena,
    observed_change,
    verdict,
):

    scouts = load_scouts()

    attack = find_attack(
        attack_id
    )

    offer = get_offer(
        offer_id
    )

    evidence = {

        "id": next_id(
            scouts,
            "scout",
        ),

        "created_at": (
            datetime.utcnow()
            .isoformat(
                timespec="seconds"
            )
            + "Z"
        ),

        "offer_id": offer_id,

        "attack_id": attack_id,

        "tested_arena": tested_arena,

        "observed_change": observed_change,

        "verdict": verdict,

        "attack_exists": (
            attack is not None
        ),

        "automatic_arena_change": False,

        "arena_before": (
            offer.get(
                "arena",
                0,
            )
        ),

        "arena_after": (
            offer.get(
                "arena",
                0,
            )
        ),
    }

    if (
        verdict == "confirmed"
        and attack is not None
    ):

        possible = attack.get(
            "possible_arena_levels",
            [],
        )

        if (
            attack.get(
                "offer_id"
            ) == offer_id
            and tested_arena in possible
        ):

            current_arena = offer.get(
                "arena",
                0,
            )

            arena_saved = set_arena(
                offer_id,
                tested_arena,
                "scout_auto",
                (
                    "Подтверждено "
                    "скаут-проверкой "
                    f"{evidence['id']} "
                    "по входящей атаке "
                    f"{attack_id}. "
                    f"Наблюдение: "
                    f"{observed_change}"
                ),
            )

            if arena_saved:

                evidence[
                    "automatic_arena_change"
                ] = True

            else:

                evidence[
                    "automatic_arena_change"
                ] = False

            evidence[
                "arena_before"
            ] = current_arena

            evidence[
                "arena_after"
            ] = tested_arena

    scouts.append(
        evidence
    )

    save_json(
        SCOUTS_FILE,
        scouts,
    )

    persist_attacks_data_to_github()

    return evidence


# ============================================================
# СЕССИИ
# ============================================================

sessions = {}


def session_key(
    chat_id,
    user_id,
):

    return (
        f"{chat_id}:{user_id}"
    )


def get_session(
    chat_id,
    user_id,
):

    key = session_key(
        chat_id,
        user_id,
    )

    if key not in sessions:

        sessions[key] = {}

    return sessions[key]


def clear_session(
    chat_id,
    user_id,
):

    sessions.pop(
        session_key(
            chat_id,
            user_id,
        ),
        None,
    )


# ============================================================
# МЕНЮ
# ============================================================

def main_menu(owner_private=False):
    keyboard = [
        [
            {
                "text": "📥 Отчёт об атаке",
                "callback_data": "attack_report",
            }
        ],
        [
            {
                "text": "🔎 Добавить скаут-проверку",
                "callback_data": "scout_report",
            }
        ],
        [
            {
                "text": "🔭 План скаут-проверок",
                "callback_data": "scout_plan",
            }
        ],
    ]

    if owner_private:
        keyboard.extend([
            [
                {
                    "text": "🏟 Офферы и Арены",
                    "callback_data": "set_arena",
                }
            ],
            [
                {
                    "text": "⚙️ Настройки разведки",
                    "callback_data": "scout_settings",
                }
            ],
        ])

    return {"inline_keyboard": keyboard}


# ============================================================
# ОТЧЁТ ОБ АТАКЕ
# ============================================================

def start_attack_report(
    chat_id,
    user_id,
):

    clear_session(
        chat_id,
        user_id,
    )

    session = get_session(
        chat_id,
        user_id,
    )

    session["flow"] = "attack"
    session["step"] = "player"

    if OUR_ALLIANCE_ID == 0:

        send_message(
            chat_id,
            (
                "📥 <b>Отчёт об атаке</b>\n\n"
                "⚠️ В настройках бота не указан "
                "<code>OUR_ALLIANCE_ID</code>.\n\n"
                "Введите координаты вашей деревни вручную.\n"
                "Формат: <code>46 -62</code>"
            ),
            reply_markup={
                "inline_keyboard": [
                    [
                        {
                            "text": "✏️ Ввести координаты вручную",
                            "callback_data": "attack_manual_coords",
                        }
                    ],
                    [
                        {
                            "text": "⬅️ Назад",
                            "callback_data": "menu",
                        }
                    ],
                ]
            },
        )

        return

    send_message(
        chat_id,
        (
            "📥 <b>Отчёт об атаке</b>\n\n"
            "Выберите игрока вашего альянса:"
        ),
        reply_markup=alliance_players_keyboard(user_id),
    )



def attack_player_selected(
    chat_id,
    user_id,
    player_uid,
):

    villages = load_alliance_villages()

    player_villages = [
        village
        for village in villages
        if village["uid"] == player_uid
    ]

    if not player_villages:

        send_message(
            chat_id,
            (
                "❌ У этого игрока не найдены "
                "деревни в последнем map.sql."
            ),
            reply_markup=alliance_players_keyboard(
                user_id
            ),
        )

        return

    player_name = player_villages[0][
        "player_name"
    ]

    session = get_session(
        chat_id,
        user_id,
    )

    session["own_player_uid"] = player_uid

    session["own_player_name"] = player_name

    session["step"] = "village"

    remember_player(
        user_id,
        player_uid,
    )

    send_message(
        chat_id,
        (
            f"👤 Игрок: "
            f"<b>{html.escape(player_name)}</b>\n\n"
            "Выберите деревню:"
        ),
        reply_markup=alliance_villages_keyboard(
            user_id,
            player_uid,
        ),
    )


def attack_village_selected(
    chat_id,
    user_id,
    village_vid,
):

    villages = load_alliance_villages()

    village = next(
        (
            item
            for item in villages
            if item["vid"] == village_vid
        ),
        None,
    )

    if not village:

        send_message(
            chat_id,
            (
                "❌ Деревня не найдена "
                "в последнем map.sql."
            ),
            reply_markup=alliance_players_keyboard(
                user_id
            ),
        )

        return

    session = get_session(
        chat_id,
        user_id,
    )

    session["own_player_uid"] = village[
        "uid"
    ]

    session["own_player_name"] = village[
        "player_name"
    ]

    session["own_village_id"] = village[
        "vid"
    ]

    session["own_village_name"] = village[
        "village_name"
    ]

    session["own_coords"] = (
        village["x"],
        village["y"],
    )

    remember_player(
        user_id,
        village["uid"],
    )

    remember_village(
        user_id,
        village["vid"],
    )

    attack_choose_offer(
        chat_id,
        user_id,
    )


def attack_reported_village_selected(
    chat_id,
    user_id,
    x,
    y,
):

    session = get_session(
        chat_id,
        user_id,
    )

    villages = load_alliance_villages()
    village = next(
        (
            item
            for item in villages
            if item["x"] == x and item["y"] == y
        ),
        None,
    )

    session["own_player_uid"] = (
        village["uid"] if village else None
    )
    session["own_player_name"] = (
        village["player_name"] if village else None
    )
    session["own_village_id"] = (
        village["vid"] if village else None
    )
    session["own_village_name"] = (
        village["village_name"] if village else None
    )
    session["own_coords"] = (x, y)

    attack_choose_offer(
        chat_id,
        user_id,
    )


def attack_manual_offer_start(
    chat_id,
    user_id,
):

    session = get_session(
        chat_id,
        user_id,
    )

    session["step"] = "offer_manual_coords"

    send_message(
        chat_id,
        (
            "✏️ <b>Новый вражеский оффер</b>\n\n"
            "Введите координаты деревни-оффера.\n\n"
            "Координаты вводятся через пробел:\n"
            "<code>46 -62</code>\n\n"
            "После добавления оффер будет сохранён в базе.\n"
            "Арена по умолчанию: <b>0</b> (неизвестна)."
        ),
        reply_markup=input_keyboard(),
    )


def add_or_get_manual_offer(
    x,
    y,
):

    offers = load_offers()

    for offer_id, offer in offers.items():
        if not isinstance(offer, dict):
            continue
        if (
            safe_int(offer.get("x")) == x
            and safe_int(offer.get("y")) == y
        ):
            return offer_id, False

    # В offers.json идентификатор хранится одновременно в ключе
    # словаря и в поле offer_id. Универсальная next_id() смотрит
    # только на поле id, поэтому для офферов она могла снова
    # вернуть offer_1 и перезаписать существующий оффер.
    highest = 0

    for existing_id, state in offers.items():
        candidates = [
            existing_id,
            state.get("id") if isinstance(state, dict) else None,
            state.get("offer_id") if isinstance(state, dict) else None,
        ]

        for candidate in candidates:
            match = re.match(
                r"^offer_(\d+)$",
                str(candidate or ""),
            )
            if match:
                highest = max(
                    highest,
                    int(match.group(1)),
                )

    offer_id = f"offer_{highest + 1}"

    offers[offer_id] = {
        "offer_id": offer_id,
        "x": x,
        "y": y,
        "arena": 0,
        "arena_source": None,
        "arena_updated_at": None,
        "arena_status": "unknown",
        "arena_reason": None,
        "manually_added": True,
    }

    save_json(
        OFFERS_FILE,
        offers,
    )

    print(
        f"Добавлен новый оффер: {offer_id} ({x} {y}), Арена 0.",
        flush=True,
    )

    # Не выполняем Git push здесь. GitHub-операции могут занять
    # заметное время и блокируют polling Telegram. Сначала возвращаем
    # управление в Telegram и показываем пользователю результат,
    # а сохранение в GitHub выполняем после отправки сообщения.

    return offer_id, True


def attack_manual_offer_selected(
    chat_id,
    user_id,
    coords,
):

    x, y = coords
    offer_id, created = add_or_get_manual_offer(x, y)

    session = get_session(
        chat_id,
        user_id,
    )
    session["offer_id"] = offer_id
    session["step"] = "waves"

    offer = get_offer(offer_id)
    owner = get_offer_owner(offer) if offer else None
    owner_text = (
        html.escape(owner)
        if owner
        else "Владелец не найден"
    )

    action_text = (
        "добавлен в базу"
        if created
        else "уже есть в базе"
    )

    send_message(
        chat_id,
        (
            f"✅ Оффер <b>({x}|{y})</b> {action_text}.\n"
            f"Владелец: <b>{owner_text}</b>\n"
            "Арена: <b>0</b> (по умолчанию).\n\n"
            "Сколько входящих волн?"
        ),
        reply_markup=attack_waves_keyboard(),
    )

    # Только после ответа пользователю синхронизируем изменённые
    # данные с GitHub. Локальный offers.json уже сохранён выше.
    if created:
        persist_attacks_data_to_github()



def attack_manual_coords_start(
    chat_id,
    user_id,
):

    session = get_session(
        chat_id,
        user_id,
    )

    session["step"] = "own_coords"

    session["own_player_uid"] = None

    session["own_player_name"] = None

    session["own_village_id"] = None

    session["own_village_name"] = None

    send_message(
        chat_id,
        (
            "✏️ <b>Ручной ввод</b>\n\n"
            "Введите координаты вашей деревни.\n\n"
            "Например:\n"
            "<code>46 -62</code>"
        ),
        reply_markup=input_keyboard(),
    )


def attack_choose_offer(
    chat_id,
    user_id,
):

    session = get_session(
        chat_id,
        user_id,
    )

    session["step"] = "offer"

    send_message(
        chat_id,
        "Выберите вражеского оффера:",
        reply_markup=offers_keyboard(
            "attack_offer"
        ),
    )


def attack_waves_keyboard():

    return {
        "inline_keyboard": [
            [
                {
                    "text": "1 волна",
                    "callback_data": (
                        "attack_waves:1"
                    ),
                },
                {
                    "text": "2 волны",
                    "callback_data": (
                        "attack_waves:2"
                    ),
                },
            ],
            [
                {
                    "text": "4 волны",
                    "callback_data": (
                        "attack_waves:4"
                    ),
                },
            ],
            [
                {
                    "text": "✏️ Свой вариант",
                    "callback_data": (
                        "attack_waves:custom"
                    ),
                },
            ],
            [
                {
                    "text": "❌ Отмена",
                    "callback_data": "menu",
                },
            ],
        ]
    }


def attack_waves_selected(
    chat_id,
    user_id,
    waves_value,
):

    session = get_session(
        chat_id,
        user_id,
    )

    if waves_value == "custom":

        session["step"] = "waves_custom"

        send_message(
            chat_id,
            (
                "✏️ <b>Своё количество волн</b>\n\n"
                "Введите количество входящих волн "
                "целым положительным числом.\n\n"
                "Например:\n"
                "<code>3</code>"
            ),
            reply_markup=input_keyboard(),
        )

        return

    waves = parse_integer(
        waves_value
    )

    if (
        waves is None
        or waves <= 0
    ):

        send_message(
            chat_id,
            "❌ Некорректное количество волн.",
            reply_markup=attack_waves_keyboard(),
        )

        return

    session["waves"] = waves

    attack_arrival_prompt(
        chat_id,
        user_id,
    )


def attack_offer_selected(
    chat_id,
    user_id,
    offer_id,
):

    offer = get_offer(
        offer_id
    )

    if not offer:

        send_message(
            chat_id,
            "Оффер не найден.",
        )

        return

    session = get_session(
        chat_id,
        user_id,
    )

    session["offer_id"] = offer_id

    session["step"] = "waves"

    owner = get_offer_owner(
        offer
    )

    owner_text = (
        html.escape(owner)
        if owner
        else "Владелец не найден"
    )

    send_message(
        chat_id,
        (
            f"Выбран оффер "
            f"<b>{owner_text} "
            f"({offer['x']}|{offer['y']})</b>.\n\n"
            "Сколько входящих волн?"
        ),
        reply_markup=attack_waves_keyboard(),
    )


# ============================================================
# ОБЩЕЕ ВРЕМЯ ВХОДЯЩЕЙ АТАКИ
# ============================================================

def attack_arrival_prompt(
    chat_id,
    user_id,
):

    """
    Показывает последнее введённое время входящей
    атаки, общее для всех игроков.

    В отличие от старой версии значение больше
    не привязано к user_id.
    """

    session = get_session(
        chat_id,
        user_id,
    )

    session["step"] = "arrival_datetime"

    last_arrival = (
        get_shared_last_arrival_datetime()
    )

    if last_arrival:

        parsed = parse_arrival_datetime(
            last_arrival
        )

        if parsed:

            keyboard = {
                "inline_keyboard": [
                    [
                        {
                            "text": (
                                f"🕒 {last_arrival}"
                            ),
                            "callback_data": (
                                "attack_arrival_default"
                            ),
                        }
                    ],
                    [
                        {
                            "text": (
                                "✏️ Ввести другое время"
                            ),
                            "callback_data": (
                                "attack_arrival_manual"
                            ),
                        }
                    ],
                    [
                        {
                            "text": "❌ Отмена",
                            "callback_data": "menu",
                        }
                    ],
                ]
            }

            send_message(
                chat_id,
                (
                    "🕒 <b>Когда прибывают войска?</b>\n\n"
                    "Последнее введённое время "
                    "входящей атаки:\n"
                    f"<code>{html.escape(last_arrival)}</code>\n\n"
                    "Если это та же операция — просто "
                    "нажмите на время.\n\n"
                    "Если время другое — выберите "
                    "«Ввести другое время».\n\n"
                    "Указывайте именно серверное "
                    "время Travian."
                ),
                reply_markup=keyboard,
            )

            return

    send_message(
        chat_id,
        (
            "🕒 <b>Когда прибывают войска?</b>\n\n"
            "Для этой операции пока нет сохранённого "
            "общего времени.\n\n"
            "Введите серверную дату и время "
            "прибытия атаки.\n\n"
            "После ввода это время станет доступно "
            "всем следующим игрокам как готовый вариант.\n\n"
            "Указывайте именно серверное время Travian, "
            "а не ваше локальное время.\n\n"
            "Формат:\n"
            "<code>14.09.2026 02:05:25</code>"
        ),
        reply_markup=input_keyboard(),
    )


def attack_arrival_default(
    chat_id,
    user_id,
):

    session = get_session(
        chat_id,
        user_id,
    )

    value = get_shared_last_arrival_datetime()

    arrival = (
        parse_arrival_datetime(value)
        if value
        else None
    )

    if not arrival:

        attack_arrival_prompt(
            chat_id,
            user_id,
        )

        return

    session["arrival_datetime"] = arrival

    session["arrival_datetime_text"] = (
        format_arrival_datetime(
            arrival
        )
    )

    session["step"] = "detected_datetime"

    send_message(
        chat_id,
        (
            f"🕒 Прибытие: "
            f"<b>{session['arrival_datetime_text']}</b>\n\n"
            "Теперь введите серверную дату и время, "
            "когда вы заметили входящую атаку.\n\n"
            "Указывайте именно время сервера Travian, "
            "а не ваше локальное время.\n\n"
            "Формат:\n"
            "<code>13.09.2026 01:26:40</code>"
        ),
        reply_markup=input_keyboard(),
    )


def attack_arrival_manual(
    chat_id,
    user_id,
):

    session = get_session(
        chat_id,
        user_id,
    )

    session["step"] = "arrival_datetime"

    send_message(
        chat_id,
        (
            "✏️ <b>Новое время входящей атаки</b>\n\n"
            "Введите серверную дату и время "
            "прибытия атаки.\n\n"
            "После ввода это значение станет "
            "последним общим временем для всех игроков.\n\n"
            "Указывайте именно серверное время "
            "Travian.\n\n"
            "Формат:\n"
            "<code>14.09.2026 02:05:25</code>"
        ),
        reply_markup=input_keyboard(),
    )


def attack_detected_prompt(
    chat_id,
    user_id,
):

    session = get_session(
        chat_id,
        user_id,
    )

    session["step"] = "detected_datetime"

    send_message(
        chat_id,
        (
            "🔎 <b>Когда вы заметили атаку?</b>\n\n"
            "Введите серверную дату и время, "
            "когда вы заметили входящую атаку.\n\n"
            "Указывайте именно время сервера Travian, "
            "а не ваше локальное время.\n\n"
            "Формат:\n"
            "<code>13.09.2026 01:26:40</code>"
        ),
        reply_markup=input_keyboard(),
    )


def attack_offline_prompt(
    chat_id,
    user_id,
):

    session = get_session(
        chat_id,
        user_id,
    )

    session["step"] = "offline_duration"

    send_message(
        chat_id,
        (
            "⏱ <b>Сколько времени вы были офлайн?</b>\n\n"
            "Это нужно для расчёта возможного "
            "времени отправки атаки и диапазона "
            "Арены.\n\n"
            "Если вы заметили атаку сразу после "
            "захода в игру — укажите <code>0</code>.\n\n"
            "Можно указать:\n"
            "• <code>01:30:00</code>\n"
            "• <code>1:30</code>\n"
            "• <code>90</code> — минут\n\n"
            "Чем точнее это значение, тем уже будет "
            "диапазон возможной Арены."
        ),
        reply_markup=input_keyboard(),
    )


def calculate_travel_time(
    detected_datetime,
    arrival_datetime,
):

    travel_seconds = (
        arrival_datetime
        - detected_datetime
    ).total_seconds()

    return travel_seconds


def finish_attack_report(
    chat_id,
    user_id,
):

    session = get_session(
        chat_id,
        user_id,
    )

    attack = create_attack(
        session
    )

    offer = get_offer(
        attack["offer_id"]
    )

    possible = attack[
        "possible_arena_levels"
    ]

    possible_text = (
        format_range(
            possible
        )
        if possible
        else "нет допустимых уровней"
    )

    individual_levels = (
        ", ".join(
            str(level)
            for level in possible
        )
        if possible
        else "нет"
    )

    current_arena = attack[
        "arena_at_report"
    ]

    current_arena_text = (
        "неизвестна"
        if current_arena == 0
        else str(current_arena)
    )

    estimated_arena = attack[
        "estimated_arena_level"
    ]

    estimate_difference = attack[
        "estimated_arena_difference_seconds"
    ]

    owner = get_offer_owner(
        offer
    )

    owner_text = (
        html.escape(owner)
        if owner
        else "Владелец не найден"
    )

    village_text = (
        f"{html.escape(attack.get('own_village_name') or 'Ручной ввод')} "
        f"({attack['own_coords']['x']}|"
        f"{attack['own_coords']['y']})"
    )

    operation_status = attack.get(
        "operation_status",
        "active",
    )

    status_text = (
        "активна"
        if operation_status == "active"
        else "закрыта"
    )

    text = (
        "✅ <b>Отчёт об атаке сохранён</b>\n\n"

        f"<b>ID:</b> "
        f"<code>{attack['id']}</code>\n"

        f"<b>Дата отчёта:</b> "
        f"{attack.get('report_date') or '—'}\n"

        f"<b>Ваша деревня:</b> "
        f"{village_text}\n"

        f"<b>Оффер:</b> "
        f"{owner_text} "
        f"({offer['x']}|{offer['y']})\n"

        f"<b>Расстояние:</b> "
        f"{attack['distance']:.2f}\n"

        f"<b>Волн:</b> "
        f"{attack['waves']}\n"

        f"<b>Обнаружено:</b> "
        f"<b>{attack['detected_server_datetime_text']}</b>\n"

        f"<b>Офлайн:</b> "
        f"<b>{attack['offline_time_text']}</b>\n"

        f"<b>Возможная отправка:</b>\n"
        f"<code>"
        f"{attack['possible_send_from_datetime_text']}"
        f"</code> — "
        f"<code>"
        f"{attack['possible_send_to_datetime_text']}"
        f"</code>\n"

        f"<b>Прибытие:</b> "
        f"<b>{attack['arrival_datetime_text']}</b>\n"

        f"<b>Время в пути:</b> "
        f"<b>{attack['min_travel_time']} — "
        f"{attack['max_travel_time']}</b>\n"

        f"<b>Операция:</b> "
        f"<code>{attack['operation_id']}</code>\n"

        f"<b>Статус операции:</b> "
        f"{status_text}\n\n"

        f"<b>Арена в базе:</b> "
        f"{current_arena_text}\n"

        f"<b>Примерная Арена:</b> "
        f"<b>A{estimated_arena}</b>\n"

        f"<b>Ближайшие допустимые уровни:</b> "
        f"{possible_text}\n"

        f"<b>Уровни:</b> "
        f"{individual_levels}\n\n"

        "Диапазон Арены рассчитан с учётом "
        "времени, которое игрок мог находиться "
        "офлайн. Поэтому фактическое время отправки "
        "атаки могло находиться внутри указанного "
        "диапазона.\n\n"

        "Скаут-проверка при расчёте не учитывается."
    )

    clear_session(
        chat_id,
        user_id,
    )

    send_message(
        chat_id,
        text,
        reply_markup=main_menu(),
    )


# ============================================================
# РУЧНАЯ АРЕНА
# ============================================================

def start_manual_arena(
    chat_id,
    user_id,
):

    clear_session(
        chat_id,
        user_id,
    )

    session = get_session(
        chat_id,
        user_id,
    )

    session["flow"] = "manual_arena"

    send_message(
        chat_id,
        (
            "🏟 <b>Установка Арены</b>\n\n"
            "Выберите вражеского оффера:"
        ),
        reply_markup=offers_keyboard(
            "manual_offer"
        ),
    )



def manual_offer_selected(
    chat_id,
    user_id,
    offer_id,
):

    offer = get_offer(
        offer_id
    )

    if not offer:

        send_message(
            chat_id,
            "Оффер не найден.",
        )

        return

    session = get_session(
        chat_id,
        user_id,
    )

    session["offer_id"] = offer_id

    session["step"] = "arena_value"

    current = offer.get(
        "arena",
        0,
    )

    owner = get_offer_owner(
        offer
    )

    if owner:

        owner_text = html.escape(
            owner
        )

    else:

        owner_text = (
            "Владелец не найден"
        )

    print(
        "MANUAL ARENA INPUT: "
        f"chat_id={chat_id}, "
        f"user_id={user_id}, "
        f"offer_id={offer_id}, "
        f"current_arena={current}",
        flush=True,
    )

    send_message(
        chat_id,
        (
            f"Оффер: "
            f"<b>{owner_text} "
            f"({offer['x']}|{offer['y']})</b>\n"
            f"Текущая Арена: "
            f"<b>{current}</b>\n\n"
            "Введите новый уровень Арены "
            "от 0 до 20."
        ),
        reply_markup=input_keyboard(),
    )


def save_manual_arena(
    chat_id,
    user_id,
    arena,
):

    session = get_session(
        chat_id,
        user_id,
    )

    offer_id = session.get(
        "offer_id"
    )

    offer = get_offer(
        offer_id
    )

    if not offer:

        send_message(
            chat_id,
            "Оффер не найден.",
        )

        clear_session(
            chat_id,
            user_id,
        )

        return

    old_arena = offer.get(
        "arena",
        0,
    )

    print(
        f"Получен ручной ввод Арены: "
        f"offer={offer_id}, arena={arena}",
        flush=True,
    )

    success = set_arena(
        offer_id,
        arena,
        "manual",
        "Установлено вручную через Telegram.",
    )

    clear_session(
        chat_id,
        user_id,
    )

    owner = get_offer_owner(
        offer
    )

    if owner:

        owner_text = html.escape(
            owner
        )

    else:

        owner_text = (
            "Владелец не найден"
        )

    if success:

        text = (
            "✅ <b>Арена обновлена</b>\n\n"

            f"<b>Оффер:</b> "
            f"{owner_text} "
            f"({offer['x']}|{offer['y']})\n"

            f"<b>Было:</b> "
            f"{old_arena}\n"

            f"<b>Стало:</b> "
            f"{arena}\n"

            "<b>Источник:</b> ручной ввод\n\n"

            "Изменение сохранено в GitHub."
        )

    else:

        text = (
            "❌ <b>Арена не сохранена</b>\n\n"

            "Локальный файл был изменён, "
            "но GitHub не подтвердил сохранение.\n\n"

            "Посмотрите лог текущего запуска "
            "бота — там будет точная причина "
            "ошибки Git."
        )

    send_message(
        chat_id,
        text,
        reply_markup=main_menu(),
    )


# ============================================================
# СКАУТ-ПРОВЕРКА
# ============================================================

SCOUT_TRIBES = {
    1: {
        "name": "Римляне",
        "units": [
            ("Легионер", "legionnaire"),
            ("Преторианец", "praetorian"),
            ("Империанец", "imperian"),
            ("Конный разведчик", "equites_legati"),
            ("Конница императора", "equites_imperatoris"),
            ("Конница цезаря", "equites_caesaris"),
            ("Таран", "ram"),
            ("Огненная катапульта", "fire_catapult"),
            ("Сенатор", "senator"),
            ("Поселенец", "settler"),
        ],
    },
    2: {
        "name": "Германцы",
        "units": [
            ("Дубинщик", "clubswinger"),
            ("Копейщик", "spearman"),
            ("Топорщик", "axeman"),
            ("Разведчик", "scout"),
            ("Паладин", "paladin"),
            ("Тевтонская конница", "teutonic_knight"),
            ("Таран", "ram"),
            ("Катапульта", "catapult"),
            ("Вождь", "chief"),
            ("Поселенец", "settler"),
        ],
    },
    3: {
        "name": "Галлы",
        "units": [
            ("Фаланга", "phalanx"),
            ("Мечник", "swordsman"),
            ("Следопыт", "pathfinder"),
            ("Гром Теутатеса", "theutates_thunder"),
            ("Друид-всадник", "druidrider"),
            ("Эдуйская конница", "haeduan"),
            ("Таран", "ram"),
            ("Требушет", "trebuchet"),
            ("Предводитель", "chieftain"),
            ("Поселенец", "settler"),
        ],
    },
    6: {
        "name": "Египтяне",
        "units": [
            ("Раб", "slave_militia"),
            ("Страж", "ash_warden"),
            ("Хопеш-воин", "khopesh_warrior"),
            ("Разведчик Сопду", "sopdu_explorer"),
            ("Страж Анхур", "anhur_guard"),
            ("Колесница Решефа", "resheph_chariot"),
            ("Таран", "ram"),
            ("Камнемёт", "stone_catapult"),
            ("Номарх", "nomarch"),
            ("Поселенец", "settler"),
        ],
    },
    7: {
        "name": "Гунны",
        "units": [
            ("Наёмник", "mercenary"),
            ("Лучник", "bowman"),
            ("Наблюдатель", "spotter"),
            ("Степной всадник", "steppe_rider"),
            ("Стрелок", "marksman"),
            ("Мародёр", "marauder"),
            ("Таран", "ram"),
            ("Катапульта", "catapult"),
            ("Логад", "logades"),
            ("Поселенец", "settler"),
        ],
    },
    8: {
        "name": "Спартанцы",
        "units": [
            ("Гоплит", "hoplite"),
            ("Страж", "sentinel"),
            ("Щитоносец", "shieldman"),
            ("Разведчик", "scout"),
            ("Элпида-всадник", "elpida_rider"),
            ("Коринфский всадник", "corinthian_crusher"),
            ("Таран", "ram"),
            ("Баллиста", "ballista"),
            ("Эфор", "ephor"),
            ("Поселенец", "settler"),
        ],
    },
}


def get_enemy_village_by_coords(x, y):
    rows = load_latest_map_rows()

    for row in rows:
        if len(row) <= 10:
            continue

        row_x = safe_int(row[1])
        row_y = safe_int(row[2])

        if row_x != x or row_y != y:
            continue

        return {
            "x": row_x,
            "y": row_y,
            "tribe_id": safe_int(row[3]),
            "village_id": safe_int(row[4]),
            "village_name": unquote_sql_value(row[5]) or "",
            "player_uid": safe_int(row[6]),
            "player_name": unquote_sql_value(row[7]) or "",
            "alliance_id": safe_int(row[8]),
            "alliance_name": unquote_sql_value(row[9]) or "",
            "population": safe_int(row[10], 0),
        }

    return None


def scout_date_keyboard():
    today = datetime.now(SERVER_TIMEZONE).date()

    return {
        "inline_keyboard": [
            [
                {
                    "text": f"📅 Сегодня — {today.strftime('%d.%m.%Y')}",
                    "callback_data": "scout_date_today",
                }
            ],
            [
                {
                    "text": "✏️ Ввести другую дату",
                    "callback_data": "scout_date_custom",
                }
            ],
            [
                {
                    "text": "❌ Отмена",
                    "callback_data": "menu",
                }
            ],
        ]
    }


def parse_scout_date(text):
    value = (text or "").strip()
    now = datetime.now(SERVER_TIMEZONE)

    for fmt in ("%d.%m.%Y", "%d.%m"):
        try:
            parsed = datetime.strptime(value, fmt)
            year = parsed.year if fmt == "%d.%m.%Y" else now.year
            return parsed.replace(year=year).date()
        except ValueError:
            pass

    return None


def parse_scout_time(text):
    try:
        return datetime.strptime(
            (text or "").strip(),
            "%H:%M:%S",
        ).time()
    except ValueError:
        return None


def get_latest_village_scout(x, y):
    result = []

    for scout in load_scouts():
        coords = scout.get("village_coords") or {}
        sx = safe_int(coords.get("x"))
        sy = safe_int(coords.get("y"))

        if sx != x or sy != y:
            continue

        scanned_at = scout.get("scanned_at")
        if not scanned_at:
            continue

        try:
            dt = datetime.fromisoformat(scanned_at)
        except (TypeError, ValueError):
            continue

        result.append((dt, scout))

    if not result:
        return None

    result.sort(key=lambda item: item[0])
    return result[-1][1]


def build_scout_template(tribe_id, previous=None):
    tribe = SCOUT_TRIBES.get(tribe_id)

    if not tribe:
        return None

    old_units = {}
    old_hero = 0

    if isinstance(previous, dict):
        old_units = previous.get("units") or {}
        old_hero = safe_int(previous.get("hero"), 0) or 0

    lines = []

    for label, key in tribe["units"]:
        value = safe_int(old_units.get(key), 0) or 0
        lines.append(f"{label}: {value}")

    # Герой намеренно идёт последним — как в отчёте Travian.
    lines.append(f"Герой: {old_hero}")

    return "\n".join(lines)


def parse_scout_units(text, tribe_id):
    tribe = SCOUT_TRIBES.get(tribe_id)

    if not tribe:
        return None, "Неизвестная народность деревни."

    expected = [(label, key) for label, key in tribe["units"]]
    expected.append(("Герой", "hero"))

    aliases = {
        re.sub(r"[^а-яёa-z0-9]+", "", label.lower()): (label, key)
        for label, key in expected
    }

    values = {}

    for raw_line in (text or "").splitlines():
        line = raw_line.strip()

        if not line:
            continue

        match = re.match(r"^(.+?)\s*:?\s*([0-9][0-9\s]*)$", line)

        if not match:
            return None, f"Не удалось разобрать строку: {line}"

        raw_name = re.sub(
            r"[^а-яёa-z0-9]+",
            "",
            match.group(1).lower(),
        )

        item = aliases.get(raw_name)

        if not item:
            return None, f"Неизвестный юнит: {match.group(1).strip()}"

        label, key = item

        try:
            value = int(match.group(2).replace(" ", ""))
        except ValueError:
            return None, f"Неверное число для {label}."

        values[key] = value

    missing = [
        label
        for label, key in expected
        if key not in values
    ]

    if missing:
        return None, (
            "Не заполнены строки: "
            + ", ".join(missing)
        )

    hero = values.pop("hero")
    return {
        "units": values,
        "hero": hero,
    }, None


def start_scout_report(chat_id, user_id):
    clear_session(chat_id, user_id)

    session = get_session(chat_id, user_id)
    session["flow"] = "scout"
    session["step"] = "village"

    send_message(
        chat_id,
        (
            "🔎 <b>Скаут-проверка</b>\n\n"
            "Выберите конкретную вражескую деревню:"
        ),
        reply_markup=offers_keyboard("scout_offer"),
    )


def scout_offer_selected(chat_id, user_id, offer_id):
    offer = get_offer(offer_id)

    if not offer:
        send_message(chat_id, "❌ Деревня не найдена.")
        return

    x = safe_int(offer.get("x"))
    y = safe_int(offer.get("y"))
    village = get_enemy_village_by_coords(x, y)

    if not village:
        send_message(
            chat_id,
            (
                "❌ Эта деревня не найдена в последнем map.sql.\n\n"
                "Без данных map.sql бот не может автоматически "
                "определить народность и сформировать шаблон войск."
            ),
            reply_markup=main_menu(),
        )
        return

    tribe_id = village.get("tribe_id")

    if tribe_id not in SCOUT_TRIBES:
        send_message(
            chat_id,
            (
                "❌ Не удалось определить поддерживаемую народность "
                f"деревни. ID народности: <code>{tribe_id}</code>."
            ),
            reply_markup=main_menu(),
        )
        return

    session = get_session(chat_id, user_id)
    session["offer_id"] = offer_id
    session["village_x"] = x
    session["village_y"] = y
    session["village_id"] = village.get("village_id")
    session["village_name"] = village.get("village_name")
    session["player_uid"] = village.get("player_uid")
    session["player_name"] = village.get("player_name")
    session["tribe_id"] = tribe_id
    session["tribe_name"] = SCOUT_TRIBES[tribe_id]["name"]
    session["step"] = "date"

    player = html.escape(village.get("player_name") or "Владелец не найден")
    village_name = html.escape(village.get("village_name") or "Без названия")

    send_message(
        chat_id,
        (
            "🔎 <b>Скаут-проверка</b>\n\n"
            f"<b>Деревня:</b> {x} {y} — {village_name}\n"
            f"<b>Игрок:</b> {player}\n"
            f"<b>Народность:</b> {SCOUT_TRIBES[tribe_id]['name']}\n\n"
            "Выберите дату скаут-отчёта:"
        ),
        reply_markup=scout_date_keyboard(),
    )


def scout_date_selected(chat_id, user_id, report_date):
    session = get_session(chat_id, user_id)
    session["report_date"] = report_date.strftime("%d.%m.%Y")
    session["step"] = "time"

    send_message(
        chat_id,
        (
            f"📅 Дата отчёта: <b>{session['report_date']}</b>\n\n"
            "🕐 Введите <b>точное время</b> скаут-отчёта "
            "по серверу Travian.\n\n"
            "Формат обязательно с секундами:\n"
            "<code>14:37:26</code>"
        ),
        reply_markup=input_keyboard(),
    )


def scout_send_army_template(chat_id, user_id):
    session = get_session(chat_id, user_id)

    previous = get_latest_village_scout(
        session["village_x"],
        session["village_y"],
    )

    template = build_scout_template(
        session["tribe_id"],
        previous,
    )

    if template is None:
        send_message(
            chat_id,
            "❌ Не удалось сформировать шаблон войск.",
            reply_markup=main_menu(),
        )
        return

    session["step"] = "units"

    send_message(
        chat_id,
        (
            "📋 <b>Состав войск</b>\n\n"
            "Ниже отдельный шаблон. Скопируйте его, вставьте "
            "в новое сообщение и измените числа по новому "
            "скаут-отчёту.\n\n"
            "Если по этой деревне уже есть проверки, шаблон "
            "заполнен данными самого позднего по времени скана."
        ),
    )

    send_message(
        chat_id,
        f"<pre>{html.escape(template)}</pre>",
        reply_markup=input_keyboard(),
    )


def scout_show_confirmation(chat_id, user_id):
    session = get_session(chat_id, user_id)
    tribe = SCOUT_TRIBES[session["tribe_id"]]

    lines = [
        "🔎 <b>Проверьте скаут-проверку</b>",
        "",
        (
            f"<b>Деревня:</b> "
            f"{session['village_x']} {session['village_y']}"
        ),
        (
            f"<b>Игрок:</b> "
            f"{html.escape(session.get('player_name') or 'Владелец не найден')}"
        ),
        f"<b>Дата:</b> {session['report_date']}",
        f"<b>Время:</b> {session['report_time']}",
        "",
    ]

    for label, key in tribe["units"]:
        lines.append(
            f"{html.escape(label)}: "
            f"<b>{session['units'][key]:,}</b>".replace(",", " ")
        )

    lines.append(f"Герой: <b>{session['hero']}</b>")

    keyboard = {
        "inline_keyboard": [
            [
                {
                    "text": "✅ Сохранить",
                    "callback_data": "scout_save",
                }
            ],
            [
                {
                    "text": "✏️ Исправить состав",
                    "callback_data": "scout_edit_units",
                }
            ],
            [
                {
                    "text": "❌ Отмена",
                    "callback_data": "menu",
                }
            ],
        ]
    }

    send_message(
        chat_id,
        "\n".join(lines),
        reply_markup=keyboard,
    )


def save_scout_report(chat_id, user_id):
    session = get_session(chat_id, user_id)

    required = (
        "village_x",
        "village_y",
        "tribe_id",
        "report_date",
        "report_time",
        "units",
        "hero",
    )

    if any(key not in session for key in required):
        send_message(
            chat_id,
            "❌ Данные скаут-проверки неполные. Начните ввод заново.",
            reply_markup=main_menu(),
        )
        clear_session(chat_id, user_id)
        return

    scanned_at = datetime.strptime(
        f"{session['report_date']} {session['report_time']}",
        "%d.%m.%Y %H:%M:%S",
    ).replace(
        tzinfo=SERVER_TIMEZONE
    )

    scouts = load_scouts()

    if not isinstance(scouts, list):
        scouts = []

    record = {
        "id": f"scout_{int(time.time() * 1000)}",
        "record_type": "village_troops",
        "offer_id": session.get("offer_id"),
        "village_id": session.get("village_id"),
        "village_coords": {
            "x": session["village_x"],
            "y": session["village_y"],
        },
        "village_name": session.get("village_name"),
        "player_uid": session.get("player_uid"),
        "player_name": session.get("player_name"),
        "tribe_id": session["tribe_id"],
        "tribe_name": session.get("tribe_name"),
        "scanned_at": scanned_at.isoformat(timespec="seconds"),
        "units": dict(session["units"]),
        "hero": session["hero"],
        "created_at": datetime.utcnow().isoformat(timespec="seconds") + "Z",
        "created_by": user_id,
    }

    scouts.append(record)
    save_json(SCOUTS_FILE, scouts)
    persist_attacks_data_to_github()

    # Если двойной скан поймал небольшую отправку, сопоставляем её с базой
    # входящих и отправляем рекомендацию по Арене только владельцу.
    notify_owner_arena_suggestion(record)

    clear_session(chat_id, user_id)

    send_message(
        chat_id,
        (
            "✅ <b>Скаут-проверка сохранена</b>\n\n"
            f"<b>Деревня:</b> "
            f"{record['village_coords']['x']} "
            f"{record['village_coords']['y']}\n"
            f"<b>Дата:</b> {scanned_at.strftime('%d.%m.%Y')}\n"
            f"<b>Время:</b> {scanned_at.strftime('%H:%M:%S')}"
        ),
        reply_markup=main_menu(),
    )


# ============================================================
# СТАТУС
# ============================================================

def show_offers_status(
    chat_id,
):

    offers = load_offers()

    lines = [
        "<b>Состояние офферов</b>",
        SERVER_NAME,
        "",
    ]

    for offer in ENEMY_OFFERS:

        state = offers.get(
            offer["id"],
            {},
        )

        arena = state.get(
            "arena",
            0,
        )

        source = state.get(
            "arena_source"
        ) or "нет данных"

        updated = state.get(
            "arena_updated_at"
        ) or "—"

        status = state.get(
            "arena_status",
            "unknown",
        )

        arena_text = (
            "неизвестна"
            if arena == 0
            else str(arena)
        )

        owner = get_offer_owner(
            offer
        )

        if owner:

            owner_text = html.escape(
                owner
            )

        else:

            owner_text = (
                "Владелец не найден"
            )

        lines.append(
            f"<b>{owner_text} "
            f"({offer['x']}|{offer['y']})</b>\n"
            f"Арена: <b>{arena_text}</b>\n"
            f"Источник: "
            f"{html.escape(source)}\n"
            f"Обновлено: {updated}\n"
            f"Статус: "
            f"{html.escape(status)}\n"
        )

    send_message(
        chat_id,
        "\n".join(lines),
        reply_markup=main_menu(),
    )




# ============================================================
# ПОДСКАЗКА ПО УТОЧНЕНИЮ АРЕНЫ ПО ДВОЙНОМУ СКАНУ
# ============================================================

SCOUT_SPAM_UNITS = {
    1: {"infantry": {"legionnaire", "praetorian", "imperian"}, "catapult": "fire_catapult"},
    2: {"infantry": {"clubswinger", "spearman", "axeman"}, "catapult": "catapult"},
    3: {"infantry": {"phalanx", "swordsman"}, "catapult": "trebuchet"},
    6: {"infantry": {"slave_militia", "ash_warden", "khopesh_warrior"}, "catapult": "stone_catapult"},
    7: {"infantry": {"mercenary", "bowman"}, "catapult": "catapult"},
    8: {"infantry": {"hoplite", "sentinel", "shieldman"}, "catapult": "ballista"},
}


def previous_scout_for_record(record, scouts):
    coords = record.get("village_coords") or {}
    current_dt = datetime.fromisoformat(record["scanned_at"])
    candidates = []
    for scout in scouts:
        if scout.get("id") == record.get("id"):
            continue
        sc = scout.get("village_coords") or {}
        if safe_int(sc.get("x")) != safe_int(coords.get("x")):
            continue
        if safe_int(sc.get("y")) != safe_int(coords.get("y")):
            continue
        try:
            dt = datetime.fromisoformat(scout.get("scanned_at"))
        except Exception:
            continue
        if dt < current_dt:
            candidates.append((dt, scout))
    if not candidates:
        return None
    candidates.sort(key=lambda item: item[0], reverse=True)
    return candidates[0][1]


def scout_arena_suggestion(record):
    scouts = load_scouts()
    previous = previous_scout_for_record(record, scouts)
    if not previous:
        return None

    try:
        before_dt = datetime.fromisoformat(previous["scanned_at"])
        after_dt = datetime.fromisoformat(record["scanned_at"])
    except Exception:
        return None

    # Подсказка рассчитана именно на двойной скан вокруг выхода.
    # Слишком широкие интервалы не используем для автоматической рекомендации.
    interval = (after_dt - before_dt).total_seconds()
    if interval <= 0 or interval > 90:
        return None

    tribe_id = safe_int(record.get("tribe_id"))
    model = SCOUT_SPAM_UNITS.get(tribe_id)
    if not model:
        return None

    old_units = previous.get("units") or {}
    new_units = record.get("units") or {}
    infantry_delta = sum(
        safe_int(new_units.get(key), 0) - safe_int(old_units.get(key), 0)
        for key in model["infantry"]
    )
    cat_delta = (
        safe_int(new_units.get(model["catapult"]), 0)
        - safe_int(old_units.get(model["catapult"]), 0)
    )

    cats_gone = -cat_delta
    if cats_gone not in (1, 2, 4):
        return None

    expected_infantry = 19 * cats_gone
    infantry_gone = -infantry_delta
    # Не требуем точных 19/38/76: между сканами могли строиться/возвращаться войска.
    tolerance = max(12, round(expected_infantry * 0.45))
    if abs(infantry_gone - expected_infantry) > tolerance:
        return None

    offer_id = record.get("offer_id")
    offer = get_offer(offer_id)
    if not offer:
        return None

    midpoint = before_dt + (after_dt - before_dt) / 2
    matches = []

    for attack in load_attacks():
        if attack.get("offer_id") != offer_id:
            continue
        try:
            arrival = datetime.fromisoformat(attack.get("arrival_datetime"))
        except Exception:
            continue
        coords = attack.get("own_coords") or {}
        tx, ty = safe_int(coords.get("x")), safe_int(coords.get("y"))
        if tx is None or ty is None:
            continue
        distance = travian_distance(offer["x"], offer["y"], tx, ty)

        for arena in range(0, 21):
            exit_at = arrival - timedelta(
                seconds=travel_time_seconds(distance, arena)
            )
            if before_dt <= exit_at <= after_dt:
                waves = safe_int(attack.get("waves"), 0)
                wave_penalty = 0 if waves == cats_gone else 1
                midpoint_diff = abs((exit_at - midpoint).total_seconds())
                matches.append((
                    wave_penalty,
                    midpoint_diff,
                    attack,
                    arena,
                    exit_at,
                ))

    if not matches:
        return None

    matches.sort(key=lambda item: (item[0], item[1]))
    best = matches[0]
    wave_penalty, _, attack, arena, exit_at = best

    # Если есть несколько одинаково сильных кандидатов, показываем гипотезу,
    # но не предлагаем одним нажатием менять базу.
    equally_strong = [
        m for m in matches
        if m[0] == best[0] and abs(m[1] - best[1]) <= 2
    ]

    return {
        "previous": previous,
        "before_dt": before_dt,
        "after_dt": after_dt,
        "infantry_delta": infantry_delta,
        "cat_delta": cat_delta,
        "waves_hint": cats_gone,
        "expected_infantry": expected_infantry,
        "attack": attack,
        "arena": arena,
        "exit_at": exit_at,
        "unique": len(equally_strong) == 1,
        "waves_match": wave_penalty == 0,
    }


def notify_owner_arena_suggestion(record):
    if not BOT_OWNER_ID:
        return

    suggestion = scout_arena_suggestion(record)
    if not suggestion:
        return

    offer = get_offer(record.get("offer_id"))
    if not offer:
        return

    attack = suggestion["attack"]
    target = attack.get("own_coords") or {}
    current_arena = safe_int(offer.get("arena"), 0)
    owner = get_offer_owner(offer) or record.get("player_name") or record.get("offer_id")

    lines = [
        "🏟 <b>Подсказка по Арене</b>",
        "",
        f"<b>Оффер:</b> {html.escape(str(owner))} "
        f"({offer['x']}|{offer['y']})",
        f"<b>Двойной скан:</b> "
        f"{suggestion['before_dt'].strftime('%H:%M:%S')} → "
        f"{suggestion['after_dt'].strftime('%H:%M:%S')}",
        f"<b>Изменение пехоты:</b> {suggestion['infantry_delta']:+d}",
        f"<b>Изменение катапульт:</b> {suggestion['cat_delta']:+d}",
        f"Масштаб близок к <b>{suggestion['waves_hint']} небольшим волнам</b>.",
        "",
        f"<b>В базе входящих найден кандидат:</b>",
        f"{html.escape(attack.get('own_player_name') or 'игрок')} "
        f"({target.get('x')}|{target.get('y')}) — "
        f"{attack.get('waves')} волн",
        f"При <b>A{suggestion['arena']}</b> расчётный выход: "
        f"<code>{suggestion['exit_at'].strftime('%H:%M:%S')}</code>",
        f"Текущая Арена в базе: <b>"
        f"{'неизвестна' if not current_arena else 'A' + str(current_arena)}</b>",
    ]

    keyboard = None
    if suggestion["unique"] and suggestion["waves_match"] and suggestion["arena"] != current_arena:
        lines.extend([
            "",
            f"Совпадают временное окно и число волн. "
            f"Рекомендуется проверить замену Арены на <b>A{suggestion['arena']}</b>.",
        ])
        keyboard = {
            "inline_keyboard": [
                [{
                    "text": f"✅ Установить A{suggestion['arena']}",
                    "callback_data": (
                        f"arena_suggest:{record.get('offer_id')}:{suggestion['arena']}"
                    ),
                }],
                [{"text": "❌ Оставить текущее значение", "callback_data": "menu"}],
            ]
        }
    else:
        lines.extend([
            "",
            "Есть временное совпадение, но оно не уникально либо число волн "
            "не совпадает точно. Автоматическая кнопка изменения Арены не предлагается.",
        ])

    send_message(BOT_OWNER_ID, "\n".join(lines), reply_markup=keyboard)


# ============================================================
# ПЛАН СКАУТ-ПРОВЕРОК
# ============================================================

def active_operation_context():
    attacks = load_attacks()
    active = [a for a in attacks if a.get("operation_status") == "active"]
    if not active:
        return None, []

    def dt(a):
        try:
            return datetime.fromisoformat(a.get("operation_arrival_datetime") or a.get("arrival_datetime"))
        except Exception:
            return datetime.min.replace(tzinfo=SERVER_TIMEZONE)

    newest = max(active, key=dt)
    op_id = newest.get("operation_id")
    op = [a for a in active if a.get("operation_id") == op_id]
    return newest, op


def operation_targets(operation_attacks):
    result = {}
    for v in load_important_villages():
        x, y = safe_int(v.get("x")), safe_int(v.get("y"))
        if x is None or y is None:
            continue
        result[(x, y)] = {
            "x": x, "y": y,
            "player_name": v.get("player_name"),
            "village_name": v.get("village_name"),
            "source": "важная",
        }

    for a in operation_attacks:
        coords = a.get("own_coords") or {}
        x, y = safe_int(coords.get("x")), safe_int(coords.get("y"))
        if x is None or y is None:
            continue
        result[(x, y)] = {
            "x": x, "y": y,
            "player_name": a.get("own_player_name"),
            "village_name": a.get("own_village_name"),
            "source": "входящая",
        }
    return list(result.values())


def offer_arena_hypotheses(offer, operation_attacks):
    offer_id = offer.get("id") or offer.get("offer_id")
    related = [a for a in operation_attacks if a.get("offer_id") == offer_id]
    estimated = []
    possible = []
    for a in related:
        e = safe_int(a.get("estimated_arena_level"))
        if e is not None and 0 <= e <= 20:
            estimated.append(e)
        for level in a.get("possible_arena_levels") or []:
            level = safe_int(level)
            if level is not None and 0 <= level <= 20:
                possible.append(level)

    state = load_offers().get(offer_id, {})
    fixed = safe_int(state.get("arena"), 0)
    ordered = []
    # Свежая оценка первой, затем жестко записанная Арена, затем весь диапазон.
    for level in estimated + ([fixed] if fixed else []) + sorted(set(possible)):
        if level not in ordered:
            ordered.append(level)
    if not ordered:
        ordered = [0]
    return ordered


def choose_scout_source(enemy_x, enemy_y, scan_before, scan_after, now):
    candidates = []
    for source in load_scout_villages():
        x, y = safe_int(source.get("x")), safe_int(source.get("y"))
        arena = safe_int(source.get("arena"))
        speed = source.get("scout_speed")
        try:
            speed = float(speed)
        except (TypeError, ValueError):
            continue
        if x is None or y is None or arena is None:
            continue
        distance = travian_distance(x, y, enemy_x, enemy_y)
        seconds = unit_travel_time_seconds(distance, speed, arena)
        send_before = scan_before - timedelta(seconds=seconds)
        send_after = scan_after - timedelta(seconds=seconds)
        if send_before <= now or send_after <= now:
            continue
        candidates.append((send_before, send_after, source, seconds))

    if not candidates:
        return None
    # Чем позже нужно отправлять, тем проще реально успеть.
    candidates.sort(key=lambda item: item[0], reverse=True)
    return candidates[0]


def build_scout_plan():
    operation_head, operation_attacks = active_operation_context()
    if not operation_head:
        return None, "Нет активной операции."

    targets = operation_targets(operation_attacks)
    if not targets:
        return None, "Нет целей для расчёта."
    if not load_scout_villages():
        return None, "Не настроены наши скаут-деревни."

    try:
        operation_arrival = datetime.fromisoformat(
            operation_head.get("operation_arrival_datetime")
            or operation_head.get("arrival_datetime")
        )
    except Exception:
        return None, "Не удалось определить время операции."

    if operation_arrival.tzinfo is None:
        operation_arrival = operation_arrival.replace(tzinfo=SERVER_TIMEZONE)

    now = datetime.now(SERVER_TIMEZONE)
    tasks = []

    for offer in get_all_offers():
        offer_id = offer.get("id") or offer.get("offer_id")
        arenas = offer_arena_hypotheses(offer, operation_attacks)
        arena_count = len(arenas)

        for arena_index, arena in enumerate(arenas):
            candidates = []
            for target in targets:
                distance = travian_distance(
                    offer["x"], offer["y"], target["x"], target["y"]
                )
                enemy_seconds = travel_time_seconds(distance, arena)
                exit_at = operation_arrival - timedelta(seconds=enemy_seconds)
                scan_before = exit_at - timedelta(seconds=10)
                scan_after = exit_at + timedelta(seconds=10)

                if scan_before <= now:
                    continue

                source = choose_scout_source(
                    offer["x"], offer["y"], scan_before, scan_after, now
                )
                if not source:
                    continue
                candidates.append((exit_at, target, source, scan_before, scan_after))

            if not candidates:
                continue

            candidates.sort(key=lambda item: item[0])
            # Разные гипотезы Арены разводим по разным частям временного диапазона.
            fraction = (arena_index + 1) / (arena_count + 1)
            idx = round(fraction * (len(candidates) - 1))
            exit_at, target, source, scan_before, scan_after = candidates[idx]
            send_before, send_after, scout_village, scout_seconds = source

            tasks.append({
                "offer_id": offer_id,
                "offer_x": offer["x"],
                "offer_y": offer["y"],
                "arena": arena,
                "target": target,
                "exit_at": exit_at,
                "scan_before": scan_before,
                "scan_after": scan_after,
                "send_before": send_before,
                "send_after": send_after,
                "scout_village": scout_village,
            })

    tasks.sort(key=lambda t: t["send_before"])
    return tasks, None


def show_scout_plan(chat_id):
    tasks, error = build_scout_plan()
    if error:
        send_message(chat_id, f"🔭 <b>План скаут-проверок</b>\n\n{html.escape(error)}")
        return

    if not tasks:
        send_message(
            chat_id,
            "🔭 <b>План скаут-проверок</b>\n\n"
            "Нет проверок, на которые разведчики ещё успевают."
        )
        return

    lines = ["🔭 <b>План скаут-проверок</b>", ""]
    for task in tasks:
        offer = get_offer(task["offer_id"])
        owner = get_offer_owner(offer) if offer else None
        target = task["target"]
        sv = task["scout_village"]
        lines.extend([
            f"<b>{html.escape(owner or task['offer_id'])} "
            f"({task['offer_x']}|{task['offer_y']}) — A{task['arena']}</b>",
            f"Проверяем выход на: "
            f"<b>{html.escape(target.get('player_name') or 'игрок')} "
            f"({target['x']}|{target['y']})</b>",
            f"Теоретический выход: <code>{task['exit_at'].strftime('%H:%M:%S')}</code>",
            f"Сканы: <code>{task['scan_before'].strftime('%H:%M:%S')}</code> / "
            f"<code>{task['scan_after'].strftime('%H:%M:%S')}</code>",
            f"Отправить из {sv['x']}|{sv['y']}: "
            f"<code>{task['send_before'].strftime('%H:%M:%S')}</code> / "
            f"<code>{task['send_after'].strftime('%H:%M:%S')}</code>",
            "",
        ])

    # Telegram message limit: делим длинный план на части.
    chunk = ""
    for line in lines:
        candidate = chunk + line + "\n"
        if len(candidate) > 3800:
            send_message(chat_id, chunk)
            chunk = line + "\n"
        else:
            chunk = candidate
    if chunk.strip():
        send_message(chat_id, chunk)


def scout_settings_menu():
    return {
        "inline_keyboard": [
            [{"text": "⭐ Добавить важную деревню", "callback_data": "add_important"}],
            [{"text": "🛰 Добавить скаут-деревню", "callback_data": "add_scout_village"}],
            [{"text": "📋 Показать настройки", "callback_data": "show_scout_settings"}],
            [{"text": "⬅️ Назад", "callback_data": "menu"}],
        ]
    }


def show_scout_settings(chat_id):
    important = load_important_villages()
    scouts = load_scout_villages()
    lines = ["⚙️ <b>Настройки разведки</b>", "", "<b>Важные деревни:</b>"]
    if important:
        for v in important:
            lines.append(
                f"• {html.escape(v.get('player_name') or '')} "
                f"{v.get('x')}|{v.get('y')}"
            )
    else:
        lines.append("— не добавлены")

    lines.extend(["", "<b>Наши скаут-деревни:</b>"])
    if scouts:
        for v in scouts:
            lines.append(
                f"• {html.escape(v.get('player_name') or '')} "
                f"{v.get('x')}|{v.get('y')} — A{v.get('arena')} "
                f"(скорость {v.get('scout_speed')})"
            )
    else:
        lines.append("— не добавлены")

    send_message(chat_id, "\n".join(lines), reply_markup=scout_settings_menu())


# ============================================================
# CALLBACK
# ============================================================

def process_callback(
    callback,
):

    callback_id = callback["id"]

    data = callback.get(
        "data",
        ""
    )

    message = callback.get(
        "message"
    )

    if not message:

        answer_callback(
            callback_id
        )

        return

    chat = message.get(
        "chat",
        {}
    )

    chat_id = chat.get(
        "id"
    )

    thread_id = message.get(
        "message_thread_id"
    )

    user = callback.get(
        "from",
        {}
    )

    user_id = user.get(
        "id"
    )

    print(
        "CALLBACK:",
        json.dumps(
            callback,
            ensure_ascii=False,
            indent=2,
        ),
        flush=True,
    )

    owner_private = is_owner(user_id) and is_private_chat(chat)
    in_group_thread = thread_id == TELEGRAM_THREAD_ID

    if not in_group_thread and not owner_private:
        answer_callback(callback_id, "Эта функция здесь недоступна.")
        return

    # Изменение Арены и настройки разведки доступны только владельцу в личке.
    owner_only = (
        data == "set_arena"
        or data.startswith("manual_offer:")
        or data.startswith("arena_suggest:")
        or data in {"scout_settings", "add_important", "add_scout_village", "show_scout_settings"}
    )
    if owner_only and not owner_private:
        answer_callback(callback_id, "Доступно только владельцу в личных сообщениях.")
        return

    answer_callback(callback_id)

    if data == "menu":

        clear_session(
            chat_id,
            user_id,
        )

        edit_message(
            chat_id,
            message["message_id"],
            "<b>Меню анализа входящих атак</b>",
            main_menu(owner_private=owner_private),
        )

        return

    if data == "scout_plan":
        show_scout_plan(chat_id)
        return

    if data == "scout_settings":
        edit_message(
            chat_id,
            message["message_id"],
            "⚙️ <b>Настройки разведки</b>",
            scout_settings_menu(),
        )
        return

    if data == "show_scout_settings":
        show_scout_settings(chat_id)
        return

    if data == "add_important":
        clear_session(chat_id, user_id)
        session = get_session(chat_id, user_id)
        session["flow"] = "scout_settings"
        session["step"] = "important_coords"
        send_message(chat_id, "⭐ Введите координаты важной деревни: <code>55 46</code>")
        return

    if data == "add_scout_village":
        clear_session(chat_id, user_id)
        session = get_session(chat_id, user_id)
        session["flow"] = "scout_settings"
        session["step"] = "scout_coords_arena"
        send_message(
            chat_id,
            "🛰 Введите координаты нашей скаут-деревни и её Арену:\n"
            "<code>55 46 18</code>\n\n"
            "Скорость разведчика бот определит по нации деревни.",
        )
        return

    if data == "attack_report":

        start_attack_report(
            chat_id,
            user_id,
        )

        return

    if data == "attack_manual_coords":

        attack_manual_coords_start(
            chat_id,
            user_id,
        )

        return

    if data.startswith("attack_reported:"):
        parts = data.split(":")
        if len(parts) != 3:
            send_message(
                chat_id,
                "❌ Некорректные координаты.",
            )
            return

        x = parse_integer(parts[1])
        y = parse_integer(parts[2])

        if (
            x is None
            or y is None
            or not (-200 <= x <= 200)
            or not (-200 <= y <= 200)
        ):
            send_message(
                chat_id,
                "❌ Некорректные координаты.",
            )
            return

        attack_reported_village_selected(
            chat_id,
            user_id,
            x,
            y,
        )
        return

    if data == "attack_manual_offer":
        attack_manual_offer_start(
            chat_id,
            user_id,
        )
        return

    if data == "attack_back_players":

        session = get_session(
            chat_id,
            user_id,
        )

        session["step"] = "player"

        send_message(
            chat_id,
            "Выберите игрока вашего альянса:",
            reply_markup=alliance_players_keyboard(
                user_id
            ),
        )

        return

    if data.startswith(
        "attack_player:"
    ):

        player_uid = parse_integer(
            data.split(
                ":",
                1,
            )[1]
        )

        if player_uid is None:

            send_message(
                chat_id,
                "❌ Некорректный ID игрока.",
            )

            return

        attack_player_selected(
            chat_id,
            user_id,
            player_uid,
        )

        return

    if data.startswith(
        "attack_village:"
    ):

        village_vid = parse_integer(
            data.split(
                ":",
                1,
            )[1]
        )

        if village_vid is None:

            send_message(
                chat_id,
                "❌ Некорректный ID деревни.",
            )

            return

        attack_village_selected(
            chat_id,
            user_id,
            village_vid,
        )

        return

    if data == "attack_arrival_default":

        attack_arrival_default(
            chat_id,
            user_id,
        )

        return

    if data == "attack_arrival_manual":

        attack_arrival_manual(
            chat_id,
            user_id,
        )

        return

    if data.startswith(
        "attack_offer:"
    ):

        offer_id = data.split(
            ":",
            1,
        )[1]

        attack_offer_selected(
            chat_id,
            user_id,
            offer_id,
        )

        return

    if data.startswith(
        "attack_waves:"
    ):

        waves_value = data.split(
            ":",
            1,
        )[1]

        attack_waves_selected(
            chat_id,
            user_id,
            waves_value,
        )

        return

    if data.startswith("arena_suggest:"):
        parts = data.split(":")
        if len(parts) != 3:
            send_message(chat_id, "❌ Некорректная рекомендация.")
            return
        offer_id = parts[1]
        arena = parse_integer(parts[2])
        if arena is None or not (0 <= arena <= 20):
            send_message(chat_id, "❌ Некорректный уровень Арены.")
            return
        offer = get_offer(offer_id)
        old_arena = safe_int(offer.get("arena"), 0) if offer else 0
        success = set_arena(
            offer_id,
            arena,
            "scout_verified",
            "Подтверждено владельцем по двойному скауту и совпавшей входящей атаке.",
        )
        if success:
            send_message(
                chat_id,
                f"✅ Арена обновлена: <b>A{old_arena}</b> → <b>A{arena}</b>.\n"
                "Следующий план скаут-проверок будет использовать новое значение.",
                reply_markup=main_menu(owner_private=True),
            )
        else:
            send_message(chat_id, "❌ Не удалось сохранить Арену в GitHub.")
        return

    if data == "set_arena":

        start_manual_arena(
            chat_id,
            user_id,
        )

        return

    if data.startswith(
        "manual_offer:"
    ):

        offer_id = data.split(
            ":",
            1,
        )[1]

        manual_offer_selected(
            chat_id,
            user_id,
            offer_id,
        )

        return

    if data == "scout_report":

        start_scout_report(
            chat_id,
            user_id,
        )

        return

    if data.startswith(
        "scout_offer:"
    ):

        offer_id = data.split(
            ":",
            1,
        )[1]

        scout_offer_selected(
            chat_id,
            user_id,
            offer_id,
        )

        return

    if data == "scout_date_today":

        scout_date_selected(
            chat_id,
            user_id,
            datetime.now(SERVER_TIMEZONE).date(),
        )

        return

    if data == "scout_date_custom":

        session = get_session(
            chat_id,
            user_id,
        )
        session["step"] = "date_custom"

        send_message(
            chat_id,
            (
                "📅 Введите дату скаут-отчёта.\n\n"
                "Формат: <code>20.09.2026</code>\n"
                "или <code>20.09</code>."
            ),
            reply_markup=input_keyboard(),
        )

        return

    if data == "scout_edit_units":

        scout_send_army_template(
            chat_id,
            user_id,
        )

        return

    if data == "scout_save":

        save_scout_report(
            chat_id,
            user_id,
        )

        return



# ============================================================
# СООБЩЕНИЯ
# ============================================================

def process_message(
    message
):

    print(
        "PROCESS MESSAGE:",
        json.dumps(
            message,
            ensure_ascii=False,
            indent=2,
        ),
        flush=True,
    )

    chat = message.get(
        "chat",
        {}
    )

    chat_id = chat.get(
        "id"
    )

    thread_id = message.get(
        "message_thread_id"
    )

    user = message.get(
        "from",
        {}
    )

    user_id = user.get(
        "id"
    )

    text = (
        message.get("text")
        or ""
    ).strip()

    print(
        "MESSAGE INFO:",
        f"chat_id={chat_id}",
        f"user_id={user_id}",
        f"thread_id={thread_id}",
        f"text={text!r}",
        flush=True,
    )

    owner_private = is_owner(user_id) and is_private_chat(chat)
    in_group_thread = thread_id == TELEGRAM_THREAD_ID

    if not in_group_thread and not owner_private:
        return

    if text.startswith(
        "/start"
    ):

        clear_session(
            chat_id,
            user_id,
        )

        send_message(
            chat_id,
            (
                "<b>Анализ входящих атак</b>\n\n"
                f"Сервер: <b>{SERVER_NAME}</b>\n"
                f"Вражеский альянс: "
                f"<b>{ENEMY_ALLIANCE_NAME}</b>\n\n"
                "Выберите действие:"
            ),
            reply_markup=main_menu(owner_private=owner_private),
        )

        return

    if text.startswith(
        "/menu"
    ):

        clear_session(
            chat_id,
            user_id,
        )

        send_message(
            chat_id,
            "<b>Меню анализа входящих атак</b>",
            reply_markup=main_menu(owner_private=owner_private),
        )

        return

    session = get_session(
        chat_id,
        user_id,
    )

    if not session:

        return

    flow = session.get(
        "flow"
    )

    step = session.get(
        "step"
    )

    print(
        f"PROCESSING TEXT: "
        f"flow={flow}, "
        f"step={step}, "
        f"text={text!r}",
        flush=True,
    )

    # ========================================================
    # НАСТРОЙКИ РАЗВЕДКИ — ТОЛЬКО ВЛАДЕЛЕЦ В ЛИЧКЕ
    # ========================================================

    if flow == "scout_settings":
        if not owner_private:
            clear_session(chat_id, user_id)
            return

        if step == "important_coords":
            coords = parse_coordinates(text)
            if not coords:
                send_message(chat_id, "❌ Формат: <code>55 46</code>")
                return
            x, y = coords
            item = save_important_village(x, y)
            clear_session(chat_id, user_id)
            send_message(
                chat_id,
                f"✅ Важная деревня добавлена: "
                f"<b>{html.escape(item.get('player_name') or '')} {x}|{y}</b>",
                reply_markup=scout_settings_menu(),
            )
            return

        if step == "scout_coords_arena":
            parts = text.replace("|", " ").split()
            if len(parts) != 3:
                send_message(chat_id, "❌ Формат: <code>55 46 18</code>")
                return
            x, y, arena = (parse_integer(p) for p in parts)
            if (
                x is None or y is None or arena is None
                or not (-200 <= x <= 200)
                or not (-200 <= y <= 200)
                or not (0 <= arena <= 20)
            ):
                send_message(chat_id, "❌ Проверьте координаты и уровень Арены 0–20.")
                return
            item, error = save_scout_village(x, y, arena)
            if error:
                send_message(chat_id, f"❌ {html.escape(error)}")
                return
            clear_session(chat_id, user_id)
            send_message(
                chat_id,
                f"✅ Скаут-деревня добавлена: <b>{x}|{y}</b>, "
                f"Арена <b>A{arena}</b>, скорость разведчика "
                f"<b>{item['scout_speed']}</b>.",
                reply_markup=scout_settings_menu(),
            )
            return

    # ========================================================
    # АТАКА
    # ========================================================

    if flow == "attack":

        if step == "own_coords":

            coords = parse_coordinates(
                text
            )

            if not coords:

                send_message(
                    chat_id,
                    (
                        "❌ Неверный формат.\n\n"
                        "Введите координаты, например:\n"
                        "<code>46 -62</code>"
                    ),
                    reply_markup=input_keyboard(),
                )

                return

            session["own_coords"] = coords

            # Если ручные координаты соответствуют нашей деревне в map.sql,
            # автоматически определяем игрока и village_id для истории.
            matched_village = next(
                (
                    village
                    for village in load_alliance_villages()
                    if (village["x"], village["y"]) == coords
                ),
                None,
            )

            if matched_village:
                session["own_player_uid"] = matched_village["uid"]
                session["own_player_name"] = matched_village["player_name"]
                session["own_village_id"] = matched_village["vid"]
                session["own_village_name"] = matched_village["village_name"]

            attack_choose_offer(
                chat_id,
                user_id,
            )

            return

        if step == "offer_manual_coords":
            coords = parse_coordinates(
                text
            )

            if not coords:
                send_message(
                    chat_id,
                    (
                        "❌ Неверный формат координат.\n\n"
                        "Введите два числа через пробел:\n"
                        "<code>46 -62</code>"
                    ),
                    reply_markup=input_keyboard(),
                )
                return

            attack_manual_offer_selected(
                chat_id,
                user_id,
                coords,
            )
            return

        if step in (
            "waves",
            "waves_custom",
        ):

            waves = parse_integer(
                text
            )

            if (
                waves is None
                or waves <= 0
            ):

                send_message(
                    chat_id,
                    (
                        "Введите положительное "
                        "целое число волн."
                    ),
                    reply_markup=input_keyboard(),
                )

                return

            session["waves"] = waves

            attack_arrival_prompt(
                chat_id,
                user_id,
            )

            return

        # ----------------------------------------------------
        # ВРЕМЯ ПРИБЫТИЯ
        # ----------------------------------------------------

        if step == "arrival_datetime":

            arrival = parse_arrival_datetime(
                text
            )

            if not arrival:

                send_message(
                    chat_id,
                    (
                        "❌ Неверный формат "
                        "даты и времени.\n\n"

                        "Указывайте серверные "
                        "дату и время Travian.\n\n"

                        "Используйте:\n"
                        "<code>14.09.2026 02:05:25</code>"
                    ),
                    reply_markup=input_keyboard(),
                )

                return

            session["arrival_datetime"] = arrival

            session["arrival_datetime_text"] = (
                format_arrival_datetime(
                    arrival
                )
            )

            # ВАЖНО:
            # Теперь это значение сохраняется
            # как общее для всех игроков.
            remember_shared_arrival_datetime(
                session[
                    "arrival_datetime_text"
                ]
            )

            session["step"] = (
                "detected_datetime"
            )

            send_message(
                chat_id,
                (
                    f"🕒 Прибытие: "
                    f"<b>"
                    f"{session['arrival_datetime_text']}"
                    f"</b>\n\n"

                    "Теперь введите серверную "
                    "дату и время, когда вы "
                    "заметили входящую атаку.\n\n"

                    "Указывайте именно время "
                    "сервера Travian, а не "
                    "ваше локальное время.\n\n"

                    "Формат:\n"
                    "<code>13.09.2026 01:26:40</code>"
                ),
                reply_markup=input_keyboard(),
            )

            return

        # ----------------------------------------------------
        # ВРЕМЯ ОБНАРУЖЕНИЯ
        # ----------------------------------------------------

        if step == "detected_datetime":

            detected_datetime = parse_server_datetime(
                text
            )

            if not detected_datetime:

                send_message(
                    chat_id,
                    (
                        "❌ Неверный формат "
                        "даты и времени.\n\n"

                        "Введите именно "
                        "серверные дату и время.\n\n"

                        "Формат:\n"
                        "<code>13.09.2026 01:26:40</code>"
                    ),
                    reply_markup=input_keyboard(),
                )

                return

            arrival_datetime = session.get(
                "arrival_datetime"
            )

            if not arrival_datetime:

                send_message(
                    chat_id,
                    (
                        "❌ Не найдено время "
                        "прибытия.\n"
                        "Начните отчёт заново."
                    ),
                    reply_markup=main_menu(),
                )

                clear_session(
                    chat_id,
                    user_id,
                )

                return

            if (
                detected_datetime
                >= arrival_datetime
            ):

                send_message(
                    chat_id,
                    (
                        "❌ Время обнаружения "
                        "не может быть позже "
                        "или равно времени прибытия.\n\n"

                        f"Обнаружение: "
                        f"<code>"
                        f"{format_server_datetime(detected_datetime)}"
                        f"</code>\n"

                        f"Прибытие: "
                        f"<code>"
                        f"{format_server_datetime(arrival_datetime)}"
                        f"</code>\n\n"

                        "Проверьте введённые "
                        "дату и время."
                    ),
                    reply_markup=input_keyboard(),
                )

                return

            session[
                "detected_datetime"
            ] = detected_datetime

            session[
                "detected_datetime_text"
            ] = format_server_datetime(
                detected_datetime
            )

            # Теперь, когда известно время обнаружения,
            # спрашиваем продолжительность офлайна.
            attack_offline_prompt(
                chat_id,
                user_id,
            )

            return

        # ----------------------------------------------------
        # ВРЕМЯ ОФЛАЙНА
        # ----------------------------------------------------

        if step == "offline_duration":

            offline_seconds = parse_duration(
                text
            )

            if (
                offline_seconds is None
                or offline_seconds < 0
            ):

                send_message(
                    chat_id,
                    (
                        "❌ Неверный формат "
                        "длительности.\n\n"

                        "Используйте, например:\n"
                        "<code>01:30:00</code>\n"
                        "<code>1:30</code>\n"
                        "<code>90</code> — минут."
                    ),
                    reply_markup=input_keyboard(),
                )

                return

            arrival_datetime = session.get(
                "arrival_datetime"
            )

            detected_datetime = session.get(
                "detected_datetime"
            )

            if (
                not arrival_datetime
                or not detected_datetime
            ):

                send_message(
                    chat_id,
                    (
                        "❌ Не удалось восстановить "
                        "время обнаружения или прибытия.\n"
                        "Начните отчёт заново."
                    ),
                    reply_markup=main_menu(),
                )

                clear_session(
                    chat_id,
                    user_id,
                )

                return

            possible_send_from_datetime = (
                detected_datetime
                - timedelta(
                    seconds=offline_seconds
                )
            )

            possible_send_to_datetime = (
                detected_datetime
            )

            if (
                possible_send_to_datetime
                >= arrival_datetime
            ):

                send_message(
                    chat_id,
                    (
                        "❌ Получился некорректный "
                        "диапазон времени отправки.\n\n"

                        "Проверьте время прибытия, "
                        "время обнаружения и "
                        "продолжительность офлайна."
                    ),
                    reply_markup=input_keyboard(),
                )

                return

            min_travel_seconds = (
                arrival_datetime
                - possible_send_to_datetime
            ).total_seconds()

            max_travel_seconds = (
                arrival_datetime
                - possible_send_from_datetime
            ).total_seconds()

            if (
                min_travel_seconds <= 0
                or max_travel_seconds <= 0
            ):

                send_message(
                    chat_id,
                    (
                        "❌ Получилось "
                        "неположительное время в пути.\n\n"
                        "Проверьте введённые значения."
                    ),
                    reply_markup=input_keyboard(),
                )

                return

            travel_seconds = min_travel_seconds

            session[
                "offline_seconds"
            ] = offline_seconds

            session[
                "offline_time_text"
            ] = format_duration(
                offline_seconds
            )

            session[
                "possible_send_from_datetime"
            ] = possible_send_from_datetime

            session[
                "possible_send_from_datetime_text"
            ] = format_server_datetime(
                possible_send_from_datetime
            )

            session[
                "possible_send_to_datetime"
            ] = possible_send_to_datetime

            session[
                "possible_send_to_datetime_text"
            ] = format_server_datetime(
                possible_send_to_datetime
            )

            session[
                "travel_seconds"
            ] = travel_seconds

            session[
                "min_travel_seconds"
            ] = min_travel_seconds

            session[
                "max_travel_seconds"
            ] = max_travel_seconds

            session[
                "travel_time_text"
            ] = format_duration(
                travel_seconds
            )

            session[
                "min_travel_time_text"
            ] = format_duration(
                min_travel_seconds
            )

            session[
                "max_travel_time_text"
            ] = format_duration(
                max_travel_seconds
            )

            session[
                "report_date"
            ] = detected_datetime.strftime(
                "%d.%m.%Y"
            )

            session[
                "report_message_datetime"
            ] = detected_datetime.isoformat(
                timespec="seconds"
            )

            print(
                "Рассчитано минимальное время в пути:",
                session[
                    "min_travel_time_text"
                ],
                flush=True,
            )

            print(
                "Рассчитано максимальное время в пути:",
                session[
                    "max_travel_time_text"
                ],
                flush=True,
            )

            print(
                "Возможное время отправки:",
                session[
                    "possible_send_from_datetime_text"
                ],
                "—",
                session[
                    "possible_send_to_datetime_text"
                ],
                flush=True,
            )

            # ------------------------------------------------
            # Рассчитываем диапазон возможной Арены.
            # ------------------------------------------------

            own_x, own_y = session[
                "own_coords"
            ]

            offer = get_offer(
                session["offer_id"]
            )

            distance = travian_distance(
                own_x,
                own_y,
                offer["x"],
                offer["y"],
            )

            arena_estimate = estimate_arena_for_time_range(
                distance,
                min_travel_seconds,
                max_travel_seconds,
            )

            possible = possible_arena_levels_by_time_range(
                distance,
                min_travel_seconds,
                max_travel_seconds,
            )

            session[
                "estimated_arena_level"
            ] = arena_estimate[
                "arena"
            ]

            session[
                "possible_arena_levels"
            ] = possible

            send_message(
                chat_id,
                (
                    "✅ <b>Время в пути рассчитано</b>\n\n"

                    f"<b>Обнаружение:</b>\n"
                    f"<code>"
                    f"{session['detected_datetime_text']}"
                    f"</code>\n\n"

                    f"<b>Офлайн:</b>\n"
                    f"<b>"
                    f"{session['offline_time_text']}"
                    f"</b>\n\n"

                    f"<b>Возможное время отправки:</b>\n"
                    f"<code>"
                    f"{session['possible_send_from_datetime_text']}"
                    f"</code> — "
                    f"<code>"
                    f"{session['possible_send_to_datetime_text']}"
                    f"</code>\n\n"

                    f"<b>Прибытие:</b>\n"
                    f"<code>"
                    f"{session['arrival_datetime_text']}"
                    f"</code>\n\n"

                    f"<b>Возможное время в пути:</b>\n"
                    f"<b>"
                    f"{session['min_travel_time_text']}"
                    f" — "
                    f"{session['max_travel_time_text']}"
                    f"</b>\n\n"

                    f"<b>Расстояние:</b> "
                    f"{distance:.2f}\n\n"

                    f"<b>Примерная Арена:</b> "
                    f"<b>A"
                    f"{arena_estimate['arena']}"
                    f"</b>\n"

                    f"<b>Возможные уровни:</b> "
                    f"<b>"
                    f"{format_range(possible)}"
                    f"</b>\n\n"

                    "Диапазон рассчитан с учётом "
                    "времени офлайна. "
                    "Скаут-проверка пока не учитывается."
                ),
            )

            finish_attack_report(
                chat_id,
                user_id,
            )

            return

    # ========================================================
    # РУЧНАЯ АРЕНА
    # ========================================================

    if flow == "manual_arena":

        if not owner_private:
            clear_session(chat_id, user_id)
            return

        if step == "arena_value":

            arena = parse_integer(
                text
            )

            if (
                arena is None
                or arena < 0
                or arena > 20
            ):

                send_message(
                    chat_id,
                    (
                        "Уровень Арены "
                        "должен быть от 0 до 20."
                    ),
                    reply_markup=input_keyboard(),
                )

                return

            save_manual_arena(
                chat_id,
                user_id,
                arena,
            )

            return

    # ========================================================
    # СКАУТ
    # ========================================================

    if flow == "scout":

        if step == "date_custom":

            report_date = parse_scout_date(
                text
            )

            if not report_date:

                send_message(
                    chat_id,
                    (
                        "❌ Неверная дата.\n\n"
                        "Введите <code>20.09.2026</code> "
                        "или <code>20.09</code>."
                    ),
                    reply_markup=input_keyboard(),
                )

                return

            scout_date_selected(
                chat_id,
                user_id,
                report_date,
            )

            return

        if step == "time":

            report_time = parse_scout_time(
                text
            )

            if not report_time:

                send_message(
                    chat_id,
                    (
                        "❌ Неверное время.\n\n"
                        "Нужна точность до секунды. "
                        "Введите время в формате:\n"
                        "<code>14:37:26</code>"
                    ),
                    reply_markup=input_keyboard(),
                )

                return

            session["report_time"] = report_time.strftime(
                "%H:%M:%S"
            )

            scout_send_army_template(
                chat_id,
                user_id,
            )

            return

        if step == "units":

            parsed, error = parse_scout_units(
                text,
                session.get("tribe_id"),
            )

            if error:

                send_message(
                    chat_id,
                    (
                        f"❌ {html.escape(error)}\n\n"
                        "Скопируйте шаблон целиком и "
                        "измените только числа."
                    ),
                    reply_markup=input_keyboard(),
                )

                return

            session["units"] = parsed["units"]
            session["hero"] = parsed["hero"]
            session["step"] = "confirm"

            scout_show_confirmation(
                chat_id,
                user_id,
            )

            return


# ============================================================
# UPDATE
# ============================================================

def process_update(
    update,
):

    try:

        print(
            "UPDATE TYPE:",
            list(update.keys()),
            flush=True,
        )

        if "callback_query" in update:

            print(
                "Обрабатываем callback_query",
                flush=True,
            )

            process_callback(
                update[
                    "callback_query"
                ]
            )

        elif "message" in update:

            print(
                "Обрабатываем message",
                flush=True,
            )

            process_message(
                update[
                    "message"
                ]
            )

        else:

            print(
                "Неизвестный тип update.",
                flush=True,
            )

    except Exception as error:

        print(
            "Ошибка обработки update:",
            repr(error),
            flush=True,
        )


# ============================================================
# ЗАПУСК
# ============================================================

def run():

    global offer_owners

    if not TELEGRAM_TOKEN:

        raise RuntimeError(
            "Не задан TELEGRAM_TOKEN."
        )

    ensure_data()

    offer_owners = load_offer_owners()

    print(
        "attacks_bot started",
        flush=True,
    )

    print(
        f"Server: {SERVER_NAME}",
        flush=True,
    )

    print(
        f"Thread: {TELEGRAM_THREAD_ID}",
        flush=True,
    )

    offset = None

    while True:

        try:

            kwargs = {
                "timeout": POLL_TIMEOUT,
                "allowed_updates": [
                    "message",
                    "callback_query",
                ],
            }

            if offset is not None:

                kwargs[
                    "offset"
                ] = offset

            print(
                "Перед запросом getUpdates",
                flush=True,
            )

            updates = telegram(
                "getUpdates",
                **kwargs,
            )

            print(
                f"getUpdates завершён. "
                f"Получено обновлений: "
                f"{len(updates)}",
                flush=True,
            )

            close_expired_operations()

            for update in updates:

                print(
                    f"Получено обновление: "
                    f"{update.get('update_id')}",
                    flush=True,
                )

                print(
                    json.dumps(
                        update,
                        ensure_ascii=False,
                        indent=2,
                    ),
                    flush=True,
                )

                offset = (
                    update["update_id"]
                    + 1
                )

                print(
                    "Перед process_update",
                    flush=True,
                )

                process_update(
                    update
                )

                print(
                    "process_update завершён",
                    flush=True,
                )

        except requests.RequestException as error:

            print(
                "Ошибка соединения с Telegram:",
                repr(error),
                flush=True,
            )

            time.sleep(5)

        except Exception as error:

            print(
                "Ошибка основного цикла:",
                repr(error),
                flush=True,
            )

            time.sleep(5)


# ============================================================
# START
# ============================================================

if __name__ == "__main__":

    print(
        "STARTING TELEGRAM POLLING",
        flush=True,
    )

    run()
