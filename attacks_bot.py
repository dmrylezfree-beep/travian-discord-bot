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

TELEGRAM_THREAD_ID = 76303

SERVER_NAME = "Азия 7 TEST"
SERVER_URL = "https://ts7.x1.asia.travian.com"

ENEMY_ALLIANCE_NAME = "Hero"
ENEMY_ALLIANCE_ID = 5

# ID нашего альянса. УКАЖИТЕ ЗДЕСЬ ФАКТИЧЕСКИЙ ID АЛЬЯНСА.
OUR_ALLIANCE_ID = 9

# Атаки с прибытием в пределах +/- 30 минут относятся к одной операции.
ATTACK_OPERATION_WINDOW_SECONDS = 30 * 60

# Время игрового мира Travian — London time.
SERVER_TIMEZONE = ZoneInfo("Europe/London")

MAP_SIZE = 401
BASE_SPEED = 3.0


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

    if not OFFERS_FILE.exists():

        offers = {}

        for offer in ENEMY_OFFERS:

            offers[offer["id"]] = {
                "offer_id": offer["id"],
                "x": offer["x"],
                "y": offer["y"],
                "arena": 0,
                "arena_source": None,
                "arena_updated_at": None,
                "arena_status": "unknown",
                "arena_reason": None,
            }

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

    preferences, key, user_preferences = get_user_preferences(user_id)
    user_preferences["last_arrival_datetime"] = arrival_datetime_text
    save_preferences(preferences)
    persist_attacks_data_to_github()


def load_latest_map_rows():

    latest_file = find_latest_map_sql()

    if latest_file is None:

        print("map.sql не найден.", flush=True)
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

    value = unquote_sql_value(value)

    try:
        return int(value)
    except (TypeError, ValueError):
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

        if None in (vid, x, y, uid):
            continue

        villages.append({
            "vid": vid,
            "x": x,
            "y": y,
            "village_name": unquote_sql_value(row[5]) or "Без названия",
            "uid": uid,
            "player_name": unquote_sql_value(row[7]) or f"UID {uid}",
            "alliance_id": alliance_id,
            "alliance_name": unquote_sql_value(row[9]) or "",
            "population": safe_int(row[10], 0),
        })

    print(
        f"Найдено деревень нашего альянса: {len(villages)}",
        flush=True,
    )

    return villages


def alliance_players_keyboard(user_id):

    villages = load_alliance_villages()
    preferences, key, user_preferences = get_user_preferences(user_id)
    recent = [str(item) for item in user_preferences.get("recent_players", [])]
    recent_index = {value: index for index, value in enumerate(recent)}

    players = {}

    for village in villages:
        uid = str(village["uid"])
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
            recent_index.get(str(player["uid"]), 999999),
            str(player["name"]).lower(),
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
                "callback_data": f"attack_player:{player['uid']}",
            }
        ])

    if not ordered:
        keyboard.append([
            {
                "text": "⚠️ Игроки не найдены в map.sql",
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
            "text": "⬅️ Назад",
            "callback_data": "menu",
        }
    ])

    return {"inline_keyboard": keyboard}


def alliance_villages_keyboard(user_id, player_uid):

    villages = [
        village
        for village in load_alliance_villages()
        if village["uid"] == player_uid
    ]

    preferences, key, user_preferences = get_user_preferences(user_id)
    recent = [str(item) for item in user_preferences.get("recent_villages", [])]
    recent_index = {value: index for index, value in enumerate(recent)}

    villages.sort(
        key=lambda village: (
            recent_index.get(str(village["vid"]), 999999),
            str(village["village_name"]).lower(),
        )
    )

    keyboard = []

    for village in villages:
        name = html.escape(village["village_name"])
        keyboard.append([
            {
                "text": (
                    f"🏠 {village['village_name']} "
                    f"({village['x']}|{village['y']})"
                ),
                "callback_data": f"attack_village:{village['vid']}",
            }
        ])

    keyboard.append([
        {
            "text": "⬅️ Другой игрок",
            "callback_data": "attack_back_players",
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

    return {"inline_keyboard": keyboard}



# ============================================================
# СОХРАНЕНИЕ ИЗМЕНЕНИЙ В GITHUB
# ============================================================

def persist_attacks_data_to_github():

    """
    Сохраняет изменения data/attacks
    обратно в ветку main.

    GitHub Actions работает во временной
    копии репозитория, поэтому после изменения
    JSON необходимо сделать commit и push.

    Перед push получаем актуальный main
    и выполняем rebase, чтобы избежать
    ошибки non-fast-forward, если параллельно
    другой workflow уже изменил репозиторий.
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
        for offer in ENEMY_OFFERS
    }

    owners = {}

    for row in rows:

        if len(row) <= 7:
            continue

        x = safe_int(row[1])
        y = safe_int(row[2])

        if x is None or y is None:
            continue

        coordinate = (x, y)

        if coordinate not in target_coordinates:
            continue

        player_name = unquote_sql_value(row[7])

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

    if thread_id is not None:

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
        "selective": True,
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
    r"^\s*(-?\d+)\s*\|\s*(-?\d+)\s*$"
)

TIME_RE = re.compile(
    r"^\s*(\d{1,2}):(\d{2}):(\d{2})\s*$"
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


def parse_time(text):

    match = TIME_RE.match(
        text
    )

    if not match:

        return None

    hours = int(
        match.group(1)
    )

    minutes = int(
        match.group(2)
    )

    seconds = int(
        match.group(3)
    )

    if minutes >= 60:

        return None

    if seconds >= 60:

        return None

    return (
        hours * 3600
        + minutes * 60
        + seconds
    )


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
    remaining_seconds,
    offline_minutes,
):

    minimum_time = float(
        remaining_seconds
    )

    maximum_time = float(
        remaining_seconds
        + offline_minutes * 60
    )

    possible = []

    for arena in range(
        0,
        21,
    ):

        travel_time = travel_time_seconds(
            distance,
            arena,
        )

        if (
            minimum_time
            <= travel_time
            <= maximum_time
        ):

            possible.append(
                arena
            )

    return possible


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

    return offer_owners.get(
        (
            offer["x"],
            offer["y"],
        )
    )


def offers_keyboard(
    prefix,
):

    offers = load_offers()

    keyboard = []

    for offer in ENEMY_OFFERS:

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
                        f"({offer['x']}|{offer['y']}) — "
                        f"A{arena_text}"
                    ),
                    "callback_data": (
                        f"{prefix}:"
                        f"{offer['id']}"
                    ),
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

    text = text.strip()

    formats = (
        "%d.%m.%Y %H:%M:%S",
        "%d.%m.%Y %H:%M",
    )

    for fmt in formats:
        try:
            value = datetime.strptime(text, fmt)
            return value
        except ValueError:
            continue

    return None


def format_arrival_datetime(value):

    return value.strftime("%d.%m.%Y %H:%M:%S")


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
                int(match.group(1)),
            )

    return f"operation_{highest + 1}"


def close_expired_operations():

    attacks = load_attacks()
    now = datetime.now(SERVER_TIMEZONE).replace(tzinfo=None)
    changed = False

    operation_times = {}

    for attack in attacks:
        operation_id = attack.get("operation_id")
        arrival_text = attack.get("operation_arrival_datetime")

        if not operation_id or not arrival_text:
            continue

        try:
            arrival = datetime.fromisoformat(arrival_text)
        except ValueError:
            continue

        operation_times.setdefault(
            operation_id,
            arrival,
        )

    expired_ids = {
        operation_id
        for operation_id, arrival in operation_times.items()
        if arrival <= now
    }

    if not expired_ids:
        return False

    for attack in attacks:
        if (
            attack.get("operation_id") in expired_ids
            and attack.get("operation_status") == "active"
        ):
            attack["operation_status"] = "closed"
            changed = True

    if changed:
        save_json(
            ATTACKS_FILE,
            attacks,
        )
        persist_attacks_data_to_github()

    return changed


def find_or_create_operation(attacks, arrival_datetime):

    close_expired_operations()
    attacks = load_attacks()

    candidates = {}

    for attack in attacks:
        operation_id = attack.get("operation_id")
        operation_status = attack.get("operation_status")
        operation_arrival = attack.get("operation_arrival_datetime")

        if (
            not operation_id
            or operation_status != "active"
            or not operation_arrival
        ):
            continue

        try:
            canonical = datetime.fromisoformat(operation_arrival)
        except ValueError:
            continue

        candidates.setdefault(
            operation_id,
            canonical,
        )

    matching = []

    for operation_id, canonical in candidates.items():
        difference = abs(
            (arrival_datetime - canonical).total_seconds()
        )

        if difference <= ATTACK_OPERATION_WINDOW_SECONDS:
            matching.append(
                (difference, operation_id, canonical)
            )

    if matching:
        matching.sort(key=lambda item: item[0])
        _, operation_id, canonical = matching[0]

        return operation_id, canonical

    operation_id = next_operation_id(attacks)
    return operation_id, arrival_datetime


def create_attack(session):

    attacks = load_attacks()

    own_x, own_y = session["own_coords"]

    offer = get_offer(
        session["offer_id"]
    )

    distance = travian_distance(
        own_x,
        own_y,
        offer["x"],
        offer["y"],
    )

    possible = possible_arena_levels(
        distance,
        session["remaining_seconds"],
        session["offline_minutes"],
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
            .isoformat(timespec="seconds")
            + "Z"
        ),

        "report_date": session.get("report_date"),
        "report_message_datetime": session.get("report_message_datetime"),

        "server_name": SERVER_NAME,
        "server_url": SERVER_URL,

        "own_player_uid": session.get("own_player_uid"),
        "own_player_name": session.get("own_player_name"),
        "own_village_id": session.get("own_village_id"),
        "own_village_name": session.get("own_village_name"),

        "own_coords": {
            "x": own_x,
            "y": own_y,
        },

        "offer_id": offer["offer_id"],

        "offer_coords": {
            "x": offer["x"],
            "y": offer["y"],
        },

        "offer_owner": owner,

        "waves": session["waves"],

        "arrival_datetime": (
            session["arrival_datetime"].isoformat(
                timespec="seconds"
            )
        ),

        "arrival_datetime_text": session["arrival_datetime_text"],

        "operation_id": operation_id,
        "operation_arrival_datetime": (
            operation_arrival.isoformat(
                timespec="seconds"
            )
        ),
        "operation_status": "active",

        "detected_server_time": session["detected_time_text"],

        "remaining_time": session["remaining_text"],
        "remaining_seconds": session["remaining_seconds"],

        "offline_minutes": session["offline_minutes"],

        "distance": round(
            distance,
            4,
        ),

        "base_speed": BASE_SPEED,

        "possible_arena_levels": possible,
        "possible_arena_text": format_range(possible),

        "arena_at_report": current_arena,
        "arena_at_report_source": offer.get("arena_source"),

        "status": "new",
    }

    attacks.append(attack)

    save_json(
        ATTACKS_FILE,
        attacks,
    )

    print(
        f"Создана атака {attack['id']} "
        f"в операции {operation_id}.",
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

def main_menu():

    return {
        "inline_keyboard": [

            [
                {
                    "text": "📥 Отчёт об атаке",
                    "callback_data": "attack_report",
                }
            ],

            [
                {
                    "text": "🏟 Установить Арену оффера",
                    "callback_data": "set_arena",
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
                    "text": "📊 Состояние офферов",
                    "callback_data": "offers_status",
                }
            ],

        ]
    }


# ============================================================
# ОТЧЁТ ОБ АТАКЕ
# ============================================================
# После выбора оффера количество волн выбирается кнопкой:
# 1, 2, 4 или "Свой вариант".

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
                "Пока можно использовать ручной ввод "
                "координат. Для автоматического списка "
                "игроков укажите ID вашего альянса "
                "в настройках."
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
            "❌ У этого игрока не найдены деревни в последнем map.sql.",
            reply_markup=alliance_players_keyboard(user_id),
        )
        return

    player_name = player_villages[0]["player_name"]
    session = get_session(chat_id, user_id)
    session["own_player_uid"] = player_uid
    session["own_player_name"] = player_name
    session["step"] = "village"

    remember_player(user_id, player_uid)

    send_message(
        chat_id,
        (
            f"👤 Игрок: <b>{html.escape(player_name)}</b>\n\n"
            "Выберите деревню:"
        ),
        reply_markup=alliance_villages_keyboard(user_id, player_uid),
    )


def attack_village_selected(
    chat_id,
    user_id,
    village_vid,
):

    villages = load_alliance_villages()
    village = next(
        (item for item in villages if item["vid"] == village_vid),
        None,
    )

    if not village:
        send_message(
            chat_id,
            "❌ Деревня не найдена в последнем map.sql.",
            reply_markup=alliance_players_keyboard(user_id),
        )
        return

    session = get_session(chat_id, user_id)
    session["own_player_uid"] = village["uid"]
    session["own_player_name"] = village["player_name"]
    session["own_village_id"] = village["vid"]
    session["own_village_name"] = village["village_name"]
    session["own_coords"] = (village["x"], village["y"])

    remember_player(user_id, village["uid"])
    remember_village(user_id, village["vid"])

    attack_choose_offer(chat_id, user_id)


def attack_manual_coords_start(chat_id, user_id):

    session = get_session(chat_id, user_id)
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
            "<code>46|-62</code>"
        ),
        reply_markup=input_keyboard(),
    )


def attack_choose_offer(chat_id, user_id):

    session = get_session(chat_id, user_id)
    session["step"] = "offer"

    send_message(
        chat_id,
        "Выберите вражеский оффер:",
        reply_markup=offers_keyboard("attack_offer"),
    )


def attack_waves_keyboard():
    return {
        "inline_keyboard": [
            [
                {
                    "text": "1 волна",
                    "callback_data": "attack_waves:1",
                },
                {
                    "text": "2 волны",
                    "callback_data": "attack_waves:2",
                },
            ],
            [
                {
                    "text": "4 волны",
                    "callback_data": "attack_waves:4",
                },
            ],
            [
                {
                    "text": "✏️ Свой вариант",
                    "callback_data": "attack_waves:custom",
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
    session = get_session(chat_id, user_id)

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

    waves = parse_integer(waves_value)

    if waves is None or waves <= 0:
        send_message(
            chat_id,
            "❌ Некорректное количество волн.",
            reply_markup=attack_waves_keyboard(),
        )
        return

    session["waves"] = waves
    attack_arrival_prompt(chat_id, user_id)


def attack_offer_selected(
    chat_id,
    user_id,
    offer_id,
):

    offer = get_offer(offer_id)

    if not offer:
        send_message(chat_id, "Оффер не найден.")
        return

    session = get_session(chat_id, user_id)
    session["offer_id"] = offer_id
    session["step"] = "waves"

    owner = get_offer_owner(offer)
    owner_text = html.escape(owner) if owner else "Владелец не найден"

    send_message(
        chat_id,
        (
            f"Выбран оффер <b>{owner_text} "
            f"({offer['x']}|{offer['y']})</b>.\n\n"
            "Сколько входящих волн?"
        ),
        reply_markup=attack_waves_keyboard(),
    )


def attack_arrival_prompt(chat_id, user_id):

    preferences, key, user_preferences = get_user_preferences(user_id)
    last_arrival = user_preferences.get("last_arrival_datetime")
    session = get_session(chat_id, user_id)
    session["step"] = "arrival_datetime"

    if last_arrival:
        parsed = parse_arrival_datetime(last_arrival)

        if parsed:
            keyboard = {
                "inline_keyboard": [
                    [
                        {
                            "text": f"🕒 Использовать {last_arrival}",
                            "callback_data": "attack_arrival_default",
                        }
                    ],
                    [
                        {
                            "text": "✏️ Ввести другое время",
                            "callback_data": "attack_arrival_manual",
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
                    f"Последнее значение: <code>{html.escape(last_arrival)}</code>\n\n"
                    "Можно использовать его или ввести другое."
                ),
                reply_markup=keyboard,
            )
            return

    send_message(
        chat_id,
        (
            "🕒 <b>Когда прибывают войска?</b>\n\n"
            "Введите дату и время прибытия.\n\n"
            "Формат:\n"
            "<code>14.09.2026 02:05:25</code>"
        ),
        reply_markup=input_keyboard(),
    )


def attack_arrival_default(chat_id, user_id):

    session = get_session(chat_id, user_id)
    preferences, key, user_preferences = get_user_preferences(user_id)
    value = user_preferences.get("last_arrival_datetime")
    arrival = parse_arrival_datetime(value) if value else None

    if not arrival:
        attack_arrival_prompt(chat_id, user_id)
        return

    session["arrival_datetime"] = arrival
    session["arrival_datetime_text"] = format_arrival_datetime(arrival)
    session["step"] = "detected_time"

    send_message(
        chat_id,
        (
            f"🕒 Прибытие: <b>{session['arrival_datetime_text']}</b>\n\n"
            "Введите серверное время, когда вы заметили входящую атаку.\n\n"
            "Например:\n"
            "<code>08:37:12</code>"
        ),
        reply_markup=input_keyboard(),
    )


def attack_arrival_manual(chat_id, user_id):

    session = get_session(chat_id, user_id)
    session["step"] = "arrival_datetime"

    send_message(
        chat_id,
        (
            "Введите дату и время прибытия.\n\n"
            "Формат:\n"
            "<code>14.09.2026 02:05:25</code>"
        ),
        reply_markup=input_keyboard(),
    )


def finish_attack_report(chat_id, user_id):

    session = get_session(chat_id, user_id)
    attack = create_attack(session)
    offer = get_offer(attack["offer_id"])

    possible = attack["possible_arena_levels"]
    possible_text = format_range(possible) if possible else "нет допустимых уровней"
    individual_levels = (
        ", ".join(str(level) for level in possible)
        if possible else "нет"
    )

    current_arena = attack["arena_at_report"]
    current_arena_text = (
        "неизвестна"
        if current_arena == 0
        else str(current_arena)
    )

    owner = get_offer_owner(offer)
    owner_text = html.escape(owner) if owner else "Владелец не найден"

    village_text = (
        f"{html.escape(attack.get('own_village_name') or 'Ручной ввод')} "
        f"({attack['own_coords']['x']}|{attack['own_coords']['y']})"
    )

    report_date = attack.get("report_date") or "—"

    operation_status = attack.get("operation_status", "active")
    status_text = "активна" if operation_status == "active" else "закрыта"

    text = (
        "✅ <b>Отчёт об атаке сохранён</b>\n\n"
        f"<b>ID:</b> <code>{attack['id']}</code>\n"
        f"<b>Дата отчёта:</b> {report_date}\n"
        f"<b>Ваша деревня:</b> {village_text}\n"
        f"<b>Оффер:</b> {owner_text} ({offer['x']}|{offer['y']})\n"
        f"<b>Расстояние:</b> {attack['distance']:.2f}\n"
        f"<b>Волн:</b> {attack['waves']}\n"
        f"<b>Прибытие:</b> <b>{attack['arrival_datetime_text']}</b>\n"
        f"<b>Операция:</b> <code>{attack['operation_id']}</code>\n"
        f"<b>Статус операции:</b> {status_text}\n"
        f"<b>Обнаружено:</b> {attack['detected_server_time']}\n"
        f"<b>До прибытия:</b> {attack['remaining_time']}\n"
        f"<b>Офлайн:</b> {attack['offline_minutes']} мин.\n\n"
        f"<b>Арена в базе:</b> {current_arena_text}\n"
        f"<b>Возможная Арена:</b> {possible_text}\n"
        f"<b>Возможные уровни:</b> {individual_levels}\n\n"
        "Диапазон используется для исключения невозможных уровней. "
        "Он не означает, что один из уровней определён точно."
    )

    clear_session(chat_id, user_id)
    send_message(chat_id, text, reply_markup=main_menu())



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
            "Выберите вражеский оффер:"
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

def start_scout_report(
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

    session["flow"] = "scout"

    send_message(
        chat_id,
        (
            "🔎 <b>Скаут-проверка</b>\n\n"
            "Сначала выберите оффер:"
        ),
        reply_markup=offers_keyboard(
            "scout_offer"
        ),
    )


def scout_offer_selected(
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

    session["step"] = "attack_id"

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

    send_message(
        chat_id,
        (
            f"Оффер: "
            f"<b>{owner_text} "
            f"({offer['x']}|{offer['y']})</b>\n\n"

            "Введите ID входящей атаки, "
            "под которую проводилась "
            "скаут-проверка.\n\n"

            "Например:\n"
            "<code>attack_1</code>\n\n"

            "Связь с атакой обязательна для "
            "автоматического изменения Арены."
        ),
        reply_markup=input_keyboard(),
    )


def scout_attack_selected(
    chat_id,
    user_id,
    attack_id,
):

    attack = find_attack(
        attack_id
    )

    if not attack:

        send_message(
            chat_id,
            (
                "❌ Такая атака не найдена.\n"
                "Введите существующий ID."
            ),
            reply_markup=input_keyboard(),
        )

        return

    session = get_session(
        chat_id,
        user_id,
    )

    if attack.get(
        "offer_id"
    ) != session.get(
        "offer_id"
    ):

        send_message(
            chat_id,
            (
                "❌ Эта атака относится "
                "к другому офферу."
            ),
            reply_markup=input_keyboard(),
        )

        return

    session["attack_id"] = attack_id

    session["step"] = "tested_arena"

    possible = attack.get(
        "possible_arena_levels",
        [],
    )

    send_message(
        chat_id,
        (
            f"Атака: "
            f"<code>{attack_id}</code>\n"

            f"Возможная Арена по атаке: "
            f"<b>{format_range(possible)}</b>\n\n"

            "Введите уровень Арены, "
            "который проверяли скаутами."
        ),
        reply_markup=input_keyboard(),
    )


def scout_arena_selected(
    chat_id,
    user_id,
    arena,
):

    session = get_session(
        chat_id,
        user_id,
    )

    attack = find_attack(
        session.get(
            "attack_id"
        )
    )

    if not attack:

        send_message(
            chat_id,
            "Атака не найдена.",
        )

        clear_session(
            chat_id,
            user_id,
        )

        return

    possible = attack.get(
        "possible_arena_levels",
        [],
    )

    if arena not in possible:

        send_message(
            chat_id,
            (
                f"⚠️ Арена {arena} "
                f"не входит в диапазон "
                f"{format_range(possible)}.\n\n"

                "Введите уровень, который "
                "действительно проверяли."
            ),
            reply_markup=input_keyboard(),
        )

        return

    session["tested_arena"] = arena

    session["step"] = "observed_change"

    send_message(
        chat_id,
        (
            "Введите результат скаут-проверки.\n\n"

            "Например:\n"
            "<code>76+4 за 20 секунд</code>\n\n"

            "Это наблюдение будет сохранено "
            "в истории."
        ),
        reply_markup=input_keyboard(),
    )


def scout_observation_entered(
    chat_id,
    user_id,
    text,
):

    if not text:

        send_message(
            chat_id,
            "Введите результат проверки.",
            reply_markup=input_keyboard(),
        )

        return

    session = get_session(
        chat_id,
        user_id,
    )

    session["observed_change"] = text

    session["step"] = "verdict"

    keyboard = {
        "inline_keyboard": [

            [
                {
                    "text": "✅ Подтверждает",
                    "callback_data": (
                        "scout_verdict:confirmed"
                    ),
                }
            ],

            [
                {
                    "text": "❌ Опровергает",
                    "callback_data": (
                        "scout_verdict:rejected"
                    ),
                }
            ],

            [
                {
                    "text": "⬅️ Отмена",
                    "callback_data": "menu",
                }
            ],
        ]
    }

    send_message(
        chat_id,
        (
            f"Наблюдение: "
            f"<code>{html.escape(text)}</code>\n"

            f"Проверяемая Арена: "
            f"<b>{session['tested_arena']}</b>\n\n"

            "Результат?"
        ),
        reply_markup=keyboard,
    )


def finish_scout(
    chat_id,
    user_id,
    verdict,
):

    session = get_session(
        chat_id,
        user_id,
    )

    evidence = add_scout_evidence(
        offer_id=session["offer_id"],
        attack_id=session["attack_id"],
        tested_arena=session["tested_arena"],
        observed_change=session["observed_change"],
        verdict=verdict,
    )

    offer = get_offer(
        session["offer_id"]
    )

    clear_session(
        chat_id,
        user_id,
    )

    if verdict == "confirmed":

        if evidence[
            "automatic_arena_change"
        ]:

            result = (
                "✅ Гипотеза подтверждена.\n"
                "Арена автоматически обновлена."
            )

        else:

            result = (
                "✅ Гипотеза сохранена.\n"
                "Автоматическое изменение "
                "Арены не выполнено."
            )

    else:

        result = (
            "❌ Гипотеза опровергнута.\n"
            "Текущая Арена не изменена."
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

    send_message(
        chat_id,
        (
            "<b>Скаут-проверка сохранена</b>\n\n"

            f"<b>Оффер:</b> "
            f"{owner_text} "
            f"({offer['x']}|{offer['y']})\n"

            f"<b>Атака:</b> "
            f"<code>{evidence['attack_id']}</code>\n"

            f"<b>Проверяли Арену:</b> "
            f"{evidence['tested_arena']}\n"

            f"<b>Наблюдение:</b> "
            f"<code>"
            f"{html.escape(evidence['observed_change'])}"
            f"</code>\n\n"

            f"{result}\n\n"

            f"<b>Текущая Арена:</b> "
            f"{offer.get('arena', 0)}"
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
# CALLBACK
# ============================================================

def process_callback(
    callback,
):

    callback_id = callback["id"]
    data = callback.get("data", "")
    message = callback.get("message")

    if not message:
        answer_callback(callback_id)
        return

    chat = message.get("chat", {})
    chat_id = chat.get("id")
    thread_id = message.get("message_thread_id")
    user = callback.get("from", {})
    user_id = user.get("id")

    print(
        "CALLBACK:",
        json.dumps(callback, ensure_ascii=False, indent=2),
        flush=True,
    )

    if thread_id != TELEGRAM_THREAD_ID:
        answer_callback(
            callback_id,
            "Бот работает в ветке 76303.",
        )
        return

    answer_callback(callback_id)

    if data == "menu":
        clear_session(chat_id, user_id)
        edit_message(
            chat_id,
            message["message_id"],
            "<b>Меню анализа входящих атак</b>",
            main_menu(),
        )
        return

    if data == "attack_report":
        start_attack_report(chat_id, user_id)
        return

    if data == "attack_manual_coords":
        attack_manual_coords_start(chat_id, user_id)
        return

    if data == "attack_back_players":
        session = get_session(chat_id, user_id)
        session["step"] = "player"
        send_message(
            chat_id,
            "Выберите игрока вашего альянса:",
            reply_markup=alliance_players_keyboard(user_id),
        )
        return

    if data.startswith("attack_player:"):
        player_uid = parse_integer(data.split(":", 1)[1])
        if player_uid is None:
            send_message(chat_id, "❌ Некорректный ID игрока.")
            return
        attack_player_selected(chat_id, user_id, player_uid)
        return

    if data.startswith("attack_village:"):
        village_vid = parse_integer(data.split(":", 1)[1])
        if village_vid is None:
            send_message(chat_id, "❌ Некорректный ID деревни.")
            return
        attack_village_selected(chat_id, user_id, village_vid)
        return

    if data == "attack_arrival_default":
        attack_arrival_default(chat_id, user_id)
        return

    if data == "attack_arrival_manual":
        attack_arrival_manual(chat_id, user_id)
        return

    if data.startswith("attack_offer:"):
        offer_id = data.split(":", 1)[1]
        attack_offer_selected(chat_id, user_id, offer_id)
        return

    if data.startswith("attack_waves:"):
        waves_value = data.split(":", 1)[1]
        attack_waves_selected(chat_id, user_id, waves_value)
        return

    if data == "set_arena":
        start_manual_arena(chat_id, user_id)
        return

    if data.startswith("manual_offer:"):
        offer_id = data.split(":", 1)[1]
        manual_offer_selected(chat_id, user_id, offer_id)
        return

    if data == "scout_report":
        start_scout_report(chat_id, user_id)
        return

    if data.startswith("scout_offer:"):
        offer_id = data.split(":", 1)[1]
        scout_offer_selected(chat_id, user_id, offer_id)
        return

    if data.startswith("scout_verdict:"):
        verdict = data.split(":", 1)[1]
        finish_scout(chat_id, user_id, verdict)
        return

    if data == "offers_status":
        show_offers_status(chat_id)
        return



# ============================================================
# СООБЩЕНИЯ
# ============================================================

def process_message(message):

    print(
        "PROCESS MESSAGE:",
        json.dumps(message, ensure_ascii=False, indent=2),
        flush=True,
    )

    chat = message.get("chat", {})
    chat_id = chat.get("id")
    thread_id = message.get("message_thread_id")
    user = message.get("from", {})
    user_id = user.get("id")
    text = (message.get("text") or "").strip()

    print(
        "MESSAGE INFO:",
        f"chat_id={chat_id}",
        f"user_id={user_id}",
        f"thread_id={thread_id}",
        f"text={text!r}",
        flush=True,
    )

    if thread_id != TELEGRAM_THREAD_ID:
        return

    if text.startswith("/start"):
        clear_session(chat_id, user_id)
        send_message(
            chat_id,
            (
                "<b>Анализ входящих атак</b>\n\n"
                f"Сервер: <b>{SERVER_NAME}</b>\n"
                f"Вражеский альянс: <b>{ENEMY_ALLIANCE_NAME}</b>\n\n"
                "Выберите действие:"
            ),
            reply_markup=main_menu(),
        )
        return

    if text.startswith("/menu"):
        clear_session(chat_id, user_id)
        send_message(
            chat_id,
            "<b>Меню анализа входящих атак</b>",
            reply_markup=main_menu(),
        )
        return

    session = get_session(chat_id, user_id)

    if not session:
        return

    flow = session.get("flow")
    step = session.get("step")

    print(
        f"PROCESSING TEXT: flow={flow}, step={step}, text={text!r}",
        flush=True,
    )

    if flow == "attack":

        if step == "own_coords":
            coords = parse_coordinates(text)

            if not coords:
                send_message(
                    chat_id,
                    (
                        "❌ Неверный формат.\n\n"
                        "Введите координаты, например:\n"
                        "<code>46|-62</code>"
                    ),
                    reply_markup=input_keyboard(),
                )
                return

            session["own_coords"] = coords
            attack_choose_offer(chat_id, user_id)
            return

        if step in ("waves", "waves_custom"):
            waves = parse_integer(text)

            if waves is None or waves <= 0:
                send_message(
                    chat_id,
                    "Введите положительное целое число волн.",
                    reply_markup=input_keyboard(),
                )
                return

            session["waves"] = waves
            attack_arrival_prompt(chat_id, user_id)
            return

        if step == "arrival_datetime":
            arrival = parse_arrival_datetime(text)

            if not arrival:
                send_message(
                    chat_id,
                    (
                        "❌ Неверный формат даты и времени.\n\n"
                        "Используйте:\n"
                        "<code>14.09.2026 02:05:25</code>"
                    ),
                    reply_markup=input_keyboard(),
                )
                return

            session["arrival_datetime"] = arrival
            session["arrival_datetime_text"] = format_arrival_datetime(arrival)
            remember_arrival_datetime(user_id, session["arrival_datetime_text"])

            session["step"] = "detected_time"

            send_message(
                chat_id,
                (
                    f"🕒 Прибытие: <b>{session['arrival_datetime_text']}</b>\n\n"
                    "Введите серверное время, когда вы заметили входящую атаку.\n\n"
                    "Например:\n"
                    "<code>08:37:12</code>"
                ),
                reply_markup=input_keyboard(),
            )
            return

        if step == "detected_time":
            seconds = parse_time(text)

            if seconds is None:
                send_message(
                    chat_id,
                    (
                        "❌ Неверный формат.\n\n"
                        "Введите, например:\n"
                        "<code>08:37:12</code>"
                    ),
                    reply_markup=input_keyboard(),
                )
                return

            session["detected_time_text"] = text
            session["detected_time_seconds"] = seconds
            session["step"] = "remaining"

            send_message(
                chat_id,
                (
                    "Теперь введите, сколько времени оставалось до прибытия атаки.\n\n"
                    "Это НЕ время суток. Это длительность.\n\n"
                    "Например:\n"
                    "<code>18:36:55</code>"
                ),
                reply_markup=input_keyboard(),
            )
            return

        if step == "remaining":
            seconds = parse_time(text)

            if seconds is None:
                send_message(
                    chat_id,
                    (
                        "❌ Неверный формат.\n\n"
                        "Введите длительность, например:\n"
                        "<code>18:36:55</code>"
                    ),
                    reply_markup=input_keyboard(),
                )
                return

            # Только здесь фиксируем дату отчёта: по message.date
            # сообщения, в котором пользователь передал remaining time.
            telegram_timestamp = message.get("date")

            if telegram_timestamp is not None:
                report_datetime = datetime.fromtimestamp(
                    int(telegram_timestamp),
                    SERVER_TIMEZONE,
                )
                session["report_date"] = report_datetime.strftime("%d.%m.%Y")
                session["report_message_datetime"] = report_datetime.isoformat(
                    timespec="seconds"
                )
            else:
                session["report_date"] = None
                session["report_message_datetime"] = None

            session["remaining_text"] = text
            session["remaining_seconds"] = seconds
            session["step"] = "offline"

            send_message(
                chat_id,
                (
                    "Сколько минут вы находились офлайн до обнаружения атаки?\n\n"
                    "Например:\n"
                    "<code>27</code>"
                ),
                reply_markup=input_keyboard(),
            )
            return

        if step == "offline":
            minutes = parse_integer(text)

            if minutes is None or minutes < 0:
                send_message(
                    chat_id,
                    (
                        "Введите количество минут целым числом.\n\n"
                        "Например:\n"
                        "<code>27</code>"
                    ),
                    reply_markup=input_keyboard(),
                )
                return

            session["offline_minutes"] = minutes
            finish_attack_report(chat_id, user_id)
            return

    if flow == "manual_arena":
        if step == "arena_value":
            arena = parse_integer(text)

            if arena is None or arena < 0 or arena > 20:
                send_message(
                    chat_id,
                    "Уровень Арены должен быть от 0 до 20.",
                    reply_markup=input_keyboard(),
                )
                return

            save_manual_arena(chat_id, user_id, arena)
            return

    if flow == "scout":
        if step == "attack_id":
            scout_attack_selected(chat_id, user_id, text)
            return

        if step == "tested_arena":
            arena = parse_integer(text)

            if arena is None or arena < 0 or arena > 20:
                send_message(
                    chat_id,
                    "Уровень Арены должен быть от 0 до 20.",
                    reply_markup=input_keyboard(),
                )
                return

            scout_arena_selected(chat_id, user_id, arena)
            return

        if step == "observed_change":
            scout_observation_entered(chat_id, user_id, text)
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
                f"Получено обновлений: {len(updates)}",
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
