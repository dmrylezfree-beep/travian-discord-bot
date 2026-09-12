import os
import json
import re
import time
import math
import html
from datetime import datetime
from pathlib import Path

import requests


# ============================================================
# НАСТРОЙКИ
# ============================================================

TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN")

# Telegram thread, в котором работает бот
TELEGRAM_THREAD_ID = 76303

# ============================================================
# СЕРВЕР
# ============================================================

# Сейчас тестируем на Азия 7.
# Для Азия 8 достаточно поменять эти настройки.
SERVER_NAME = "Азия 7 TEST"
SERVER_URL = "https://ts7.x1.asia.travian.com"

ENEMY_ALLIANCE_NAME = "Hero"
ENEMY_ALLIANCE_ID = 5

# Travian: координаты от -200 до +200.
# Полный размер карты = 401.
MAP_SIZE = 401

# Скорость войск для расчёта.
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
# ФАЙЛЫ ДАННЫХ
# ============================================================

DATA_DIR = Path("data/attacks")

OFFERS_FILE = DATA_DIR / "offers.json"
ATTACKS_FILE = DATA_DIR / "attacks.json"
SCOUTS_FILE = DATA_DIR / "scouts.json"


# ============================================================
# TELEGRAM
# ============================================================

API_URL = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}"

POLL_TIMEOUT = 30
REQUEST_TIMEOUT = 40


# ============================================================
# СОЗДАНИЕ / ЗАГРУЗКА ДАННЫХ
# ============================================================

def ensure_data():
    DATA_DIR.mkdir(parents=True, exist_ok=True)

    # --------------------------------------------------------
    # Текущая информация об офферах
    # --------------------------------------------------------

    if not OFFERS_FILE.exists():

        offers = {}

        for offer in ENEMY_OFFERS:

            offers[offer["id"]] = {
                "offer_id": offer["id"],
                "x": offer["x"],
                "y": offer["y"],

                # 0 = пока неизвестна
                "arena": 0,

                # Откуда получено текущее значение
                "arena_source": None,

                # Когда было установлено
                "arena_updated_at": None,

                # confirmed / unknown / disputed
                "arena_status": "unknown",

                # Причина последнего изменения
                "arena_reason": None,
            }

        save_json(OFFERS_FILE, offers)

    # --------------------------------------------------------
    # История входящих атак
    # --------------------------------------------------------

    if not ATTACKS_FILE.exists():
        save_json(ATTACKS_FILE, [])

    # --------------------------------------------------------
    # История скаут-проверок
    # --------------------------------------------------------

    if not SCOUTS_FILE.exists():
        save_json(SCOUTS_FILE, [])


def load_json(path, default):

    try:

        with path.open("r", encoding="utf-8") as file:
            return json.load(file)

    except (FileNotFoundError, json.JSONDecodeError):

        return default


def save_json(path, data):

    path.parent.mkdir(parents=True, exist_ok=True)

    temp_path = path.with_suffix(path.suffix + ".tmp")

    with temp_path.open("w", encoding="utf-8") as file:

        json.dump(
            data,
            file,
            ensure_ascii=False,
            indent=2,
        )

    temp_path.replace(path)


def load_offers():
    return load_json(OFFERS_FILE, {})


def load_attacks():
    return load_json(ATTACKS_FILE, [])


def load_scouts():
    return load_json(SCOUTS_FILE, [])


# ============================================================
# TELEGRAM API
# ============================================================

def telegram(method, **kwargs):

    response = requests.post(
        f"{API_URL}/{method}",
        json=kwargs,
        timeout=REQUEST_TIMEOUT,
    )

    response.raise_for_status()

    result = response.json()

    if not result.get("ok"):
        raise RuntimeError(result)

    return result.get("result")


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
        data["message_thread_id"] = thread_id

    if reply_markup is not None:
        data["reply_markup"] = reply_markup

    return telegram(
        "sendMessage",
        **data,
    )


def answer_callback(callback_id, text=None):

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
        data["reply_markup"] = reply_markup

    return telegram(
        "editMessageText",
        **data,
    )


# ============================================================
# ВАЛИДАЦИЯ ВВОДА
# ============================================================

COORDINATE_RE = re.compile(
    r"^\s*(-?\d+)\s*\|\s*(-?\d+)\s*$"
)

TIME_RE = re.compile(
    r"^\s*(\d{1,2}):(\d{2}):(\d{2})\s*$"
)


def parse_coordinates(text):

    match = COORDINATE_RE.match(text)

    if not match:
        return None

    x = int(match.group(1))
    y = int(match.group(2))

    if not (-200 <= x <= 200):
        return None

    if not (-200 <= y <= 200):
        return None

    return x, y


def parse_time(text):

    match = TIME_RE.match(text)

    if not match:
        return None

    hours = int(match.group(1))
    minutes = int(match.group(2))
    seconds = int(match.group(3))

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
        return int(text.strip())

    except ValueError:
        return None


def format_range(levels):

    if not levels:
        return "нет допустимых уровней"

    levels = sorted(set(levels))

    ranges = []

    start = levels[0]
    previous = levels[0]

    for level in levels[1:]:

        if level == previous + 1:

            previous = level

        else:

            ranges.append(
                (start, previous)
            )

            start = level
            previous = level

    ranges.append(
        (start, previous)
    )

    result = []

    for start, end in ranges:

        if start == end:

            result.append(str(start))

        else:

            result.append(
                f"{start}–{end}"
            )

    return ", ".join(result)


# ============================================================
# РАССТОЯНИЕ TRAVIAN
# ============================================================

def travian_distance(
    x1,
    y1,
    x2,
    y2,
):

    raw_dx = abs(x2 - x1)
    raw_dy = abs(y2 - y1)

    dx = min(
        raw_dx,
        MAP_SIZE - raw_dx,
    )

    dy = min(
        raw_dy,
        MAP_SIZE - raw_dy,
    )

    return math.sqrt(
        dx * dx + dy * dy
    )


# ============================================================
# ВРЕМЯ ДВИЖЕНИЯ С АРЕНОЙ
# ============================================================

def travel_time_seconds(
    distance,
    arena_level,
):

    """
    Первые 20 полей:

        базовая скорость.

    После 20 полей:

        каждый уровень Арены
        увеличивает скорость на 20%.

    При скорости 3:

        speed = 3 * (1 + 0.2 * arena)

    Возвращаем время в секундах.
    """

    if distance <= 20:

        return (
            distance
            / BASE_SPEED
            * 3600
        )

    speed_after_20 = (
        BASE_SPEED
        * (1 + 0.20 * arena_level)
    )

    first_part = (
        20 / BASE_SPEED
    )

    second_part = (
        (distance - 20)
        / speed_after_20
    )

    total_hours = (
        first_part
        + second_part
    )

    return total_hours * 3600


# ============================================================
# ВЫЧИСЛЕНИЕ ВОЗМОЖНЫХ УРОВНЕЙ АРЕНЫ
# ============================================================

def possible_arena_levels(
    distance,
    remaining_seconds,
    offline_minutes,
):

    """
    Игрок обнаружил атаку.

    В этот момент до прибытия осталось:

        remaining_seconds

    До этого игрок мог находиться офлайн:

        offline_minutes

    Поэтому фактическое время движения атаки
    может находиться между:

        remaining_seconds

    и

        remaining_seconds
        + offline_minutes * 60

    Мы НЕ пытаемся определить точную Арену.

    Мы просто исключаем уровни, которые
    невозможны в этом временном интервале.
    """

    minimum_time = float(
        remaining_seconds
    )

    maximum_time = float(
        remaining_seconds
        + offline_minutes * 60
    )

    possible = []

    # Арена 0–20.
    for arena in range(0, 21):

        travel_time = travel_time_seconds(
            distance,
            arena,
        )

        if (
            minimum_time
            <= travel_time
            <= maximum_time
        ):

            possible.append(arena)

    return possible


# ============================================================
# ОФФЕРЫ
# ============================================================

def get_offer(offer_id):

    offers = load_offers()

    return offers.get(offer_id)


def set_arena(
    offer_id,
    arena,
    source,
    reason,
):

    offers = load_offers()

    if offer_id not in offers:
        return False

    offers[offer_id]["arena"] = arena

    offers[offer_id]["arena_source"] = source

    offers[offer_id]["arena_updated_at"] = (
        datetime.utcnow()
        .isoformat(timespec="seconds")
        + "Z"
    )

    offers[offer_id]["arena_status"] = (
        "confirmed"
    )

    offers[offer_id]["arena_reason"] = reason

    save_json(
        OFFERS_FILE,
        offers,
    )

    return True


def offers_keyboard(prefix):

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
            arena_text = str(arena)

        keyboard.append(
            [
                {
                    "text": (
                        f"({offer['x']}|{offer['y']}) "
                        f"A{arena_text}"
                    ),
                    "callback_data": (
                        f"{prefix}:{offer['id']}"
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
# ID ДЛЯ ИСТОРИИ
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

            number = int(
                match.group(1)
            )

            highest = max(
                highest,
                number,
            )

    return f"{prefix}_{highest + 1}"


# ============================================================
# СОХРАНЕНИЕ ВХОДЯЩЕЙ АТАКИ
# ============================================================

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

    possible = possible_arena_levels(
        distance,
        session["remaining_seconds"],
        session["offline_minutes"],
    )

    current_arena = offer.get(
        "arena",
        0,
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

        "server_name": SERVER_NAME,

        "server_url": SERVER_URL,

        "own_coords": {
            "x": own_x,
            "y": own_y,
        },

        "offer_id": offer["id"],

        "offer_coords": {
            "x": offer["x"],
            "y": offer["y"],
        },

        "waves": session["waves"],

        "detected_server_time": (
            session[
                "detected_time_text"
            ]
        ),

        "remaining_time": (
            session[
                "remaining_text"
            ]
        ),

        "remaining_seconds": (
            session[
                "remaining_seconds"
            ]
        ),

        "offline_minutes": (
            session[
                "offline_minutes"
            ]
        ),

        "distance": round(
            distance,
            4,
        ),

        "base_speed": BASE_SPEED,

        "possible_arena_levels": possible,

        "possible_arena_text": (
            format_range(possible)
        ),

        # Какой была текущая информация
        # на момент регистрации атаки.
        "arena_at_report": (
            current_arena
        ),

        "arena_at_report_source": (
            offer.get(
                "arena_source"
            )
        ),

        "status": "new",
    }

    attacks.append(attack)

    save_json(
        ATTACKS_FILE,
        attacks,
    )

    return attack


def find_attack(attack_id):

    attacks = load_attacks()

    for attack in attacks:

        if attack.get("id") == attack_id:

            return attack

    return None


# ============================================================
# СКАУТ-ДОКАЗАТЕЛЬСТВО
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

        "tested_arena": (
            tested_arena
        ),

        "observed_change": (
            observed_change
        ),

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

    # ========================================================
    # АВТОМАТИЧЕСКАЯ ПЕРЕЗАПИСЬ
    # ========================================================

    if (
        verdict == "confirmed"
        and attack is not None
    ):

        possible = attack.get(
            "possible_arena_levels",
            [],
        )

        # Проверяем:
        #
        # 1. это действительно атака этого оффера;
        # 2. проверяемая Арена входит в диапазон атаки;
        # 3. скаут подтверждает именно эту гипотезу.
        #
        # Только тогда разрешаем автоматическое
        # изменение текущей Арены.

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

            set_arena(
                offer_id,
                tested_arena,
                "scout_auto",
                (
                    "Подтверждено скаут-"
                    "проверкой "
                    f"{evidence['id']} "
                    "по входящей атаке "
                    f"{attack_id}. "
                    f"Наблюдение: "
                    f"{observed_change}"
                ),
            )

            evidence[
                "automatic_arena_change"
            ] = True

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

    return evidence


# ============================================================
# TELEGRAM СЕССИИ
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
# ГЛАВНОЕ МЕНЮ
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

    session["step"] = (
        "own_coords"
    )

    send_message(
        chat_id,
        (
            "📥 <b>Отчёт об атаке</b>\n\n"
            "Введите координаты вашей "
            "деревни.\n\n"
            "Например:\n"
            "<code>46|-62</code>"
        ),
        reply_markup=cancel_keyboard(),
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
        "Выберите вражеский оффер:",
        reply_markup=offers_keyboard(
            "attack_offer"
        ),
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

    session["offer_id"] = (
        offer_id
    )

    session["step"] = "waves"

    send_message(
        chat_id,
        (
            f"Выбран оффер "
            f"<b>({offer['x']}|{offer['y']})</b>.\n\n"
            "Введите количество волн."
        ),
        reply_markup=cancel_keyboard(),
    )


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

    if possible:

        possible_text = format_range(
            possible
        )

        individual_levels = ", ".join(
            str(level)
            for level in possible
        )

    else:

        possible_text = (
            "нет допустимых уровней"
        )

        individual_levels = "нет"

    current_arena = attack[
        "arena_at_report"
    ]

    if current_arena == 0:

        current_arena_text = (
            "неизвестна"
        )

    else:

        current_arena_text = str(
            current_arena
        )

    text = (

        "✅ <b>Отчёт об атаке сохранён</b>\n\n"

        f"<b>ID:</b> "
        f"<code>{attack['id']}</code>\n"

        f"<b>Ваша деревня:</b> "
        f"({attack['own_coords']['x']}|"
        f"{attack['own_coords']['y']})\n"

        f"<b>Оффер:</b> "
        f"({offer['x']}|{offer['y']})\n"

        f"<b>Расстояние:</b> "
        f"{attack['distance']:.2f}\n"

        f"<b>Волн:</b> "
        f"{attack['waves']}\n"

        f"<b>Обнаружено:</b> "
        f"{attack['detected_server_time']}\n"

        f"<b>До прибытия:</b> "
        f"{attack['remaining_time']}\n"

        f"<b>Офлайн:</b> "
        f"{attack['offline_minutes']} мин.\n\n"

        f"<b>Арена в базе:</b> "
        f"{current_arena_text}\n"

        f"<b>Возможная Арена:</b> "
        f"{possible_text}\n"

        f"<b>Возможные уровни:</b> "
        f"{individual_levels}\n\n"

        "Диапазон используется для "
        "исключения невозможных уровней. "
        "Он не означает, что один из "
        "уровней определён точно."
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
# РУЧНАЯ УСТАНОВКА АРЕНЫ
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

    session["offer_id"] = (
        offer_id
    )

    session["step"] = (
        "arena_value"
    )

    current = offer.get(
        "arena",
        0,
    )

    send_message(
        chat_id,
        (
            f"Оффер: "
            f"<b>({offer['x']}|{offer['y']})</b>\n"
            f"Текущая Арена: "
            f"<b>{current}</b>\n\n"
            "Введите новый уровень Арены "
            "от 0 до 20."
        ),
        reply_markup=cancel_keyboard(),
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

    set_arena(
        offer_id,
        arena,
        "manual",
        "Установлено вручную через Telegram.",
    )

    clear_session(
        chat_id,
        user_id,
    )

    send_message(
        chat_id,
        (
            "✅ <b>Арена обновлена</b>\n\n"

            f"<b>Оффер:</b> "
            f"({offer['x']}|{offer['y']})\n"

            f"<b>Было:</b> "
            f"{old_arena}\n"

            f"<b>Стало:</b> "
            f"{arena}\n"

            "<b>Источник:</b> ручной ввод"
        ),
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

    session["offer_id"] = (
        offer_id
    )

    session["step"] = (
        "attack_id"
    )

    send_message(
        chat_id,
        (
            f"Оффер: "
            f"<b>({offer['x']}|{offer['y']})</b>\n\n"

            "Введите ID входящей атаки, "
            "под которую проводилась "
            "скаут-проверка.\n\n"

            "Например:\n"
            "<code>attack_1</code>\n\n"

            "Связь с атакой обязательна для "
            "автоматического изменения Арены."
        ),
        reply_markup=cancel_keyboard(),
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
            reply_markup=cancel_keyboard(),
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
            reply_markup=cancel_keyboard(),
        )

        return

    session["attack_id"] = (
        attack_id
    )

    session["step"] = (
        "tested_arena"
    )

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
        reply_markup=cancel_keyboard(),
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

    # Нельзя проверять через этот отчёт
    # уровень, который сам отчёт исключает.
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
            reply_markup=cancel_keyboard(),
        )

        return

    session["tested_arena"] = (
        arena
    )

    session["step"] = (
        "observed_change"
    )

    send_message(
        chat_id,
        (
            "Введите результат скаут-проверки.\n\n"

            "Например:\n"
            "<code>76+4 за 20 секунд</code>\n\n"

            "Это наблюдение будет сохранено "
            "в истории."
        ),
        reply_markup=cancel_keyboard(),
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
            reply_markup=cancel_keyboard(),
        )

        return

    session = get_session(
        chat_id,
        user_id,
    )

    session[
        "observed_change"
    ] = text

    session["step"] = (
        "verdict"
    )

    keyboard = {
        "inline_keyboard": [

            [
                {
                    "text": (
                        "✅ Подтверждает"
                    ),
                    "callback_data": (
                        "scout_verdict:confirmed"
                    ),
                }
            ],

            [
                {
                    "text": (
                        "❌ Опровергает"
                    ),
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
        offer_id=session[
            "offer_id"
        ],

        attack_id=session[
            "attack_id"
        ],

        tested_arena=session[
            "tested_arena"
        ],

        observed_change=session[
            "observed_change"
        ],

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

    send_message(
        chat_id,
        (
            "<b>Скаут-проверка сохранена</b>\n\n"

            f"<b>Оффер:</b> "
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
# СТАТУС ВСЕХ ОФФЕРОВ
# ============================================================

def show_offers_status(
    chat_id,
):

    offers = load_offers()

    lines = [
        f"<b>Состояние офферов</b>",
        f"{SERVER_NAME}",
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

        lines.append(
            f"<b>({offer['x']}|{offer['y']})</b>\n"
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
# CALLBACK QUERY
# ============================================================

def process_callback(
    callback,
):

    callback_id = callback["id"]

    data = callback.get(
        "data",
        "",
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

    # Только ветка 76303.
    if thread_id != TELEGRAM_THREAD_ID:

        answer_callback(
            callback_id,
            "Бот работает в ветке 76303.",
        )

        return

    answer_callback(
        callback_id
    )

    # --------------------------------------------------------
    # МЕНЮ
    # --------------------------------------------------------

    if data == "menu":

        clear_session(
            chat_id,
            user_id,
        )

        edit_message(
            chat_id,
            message["message_id"],
            "<b>Меню анализа входящих атак</b>",
            main_menu(),
        )

        return

    # --------------------------------------------------------
    # ОТЧЁТ ОБ АТАКЕ
    # --------------------------------------------------------

    if data == "attack_report":

        start_attack_report(
            chat_id,
            user_id,
        )

        return

    if data.startswith(
        "attack_offer:"
    ):

        offer_id = data.split(
            ":",
            1
        )[1]

        attack_offer_selected(
            chat_id,
            user_id,
            offer_id,
        )

        return

    # --------------------------------------------------------
    # РУЧНАЯ АРЕНА
    # --------------------------------------------------------

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
            1
        )[1]

        manual_offer_selected(
            chat_id,
            user_id,
            offer_id,
        )

        return

    # --------------------------------------------------------
    # СКАУТ
    # --------------------------------------------------------

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
            1
        )[1]

        scout_offer_selected(
            chat_id,
            user_id,
            offer_id,
        )

        return

    if data.startswith(
        "scout_verdict:"
    ):

        verdict = data.split(
            ":",
            1
        )[1]

        finish_scout(
            chat_id,
            user_id,
            verdict,
        )

        return

    # --------------------------------------------------------
    # СТАТУС
    # --------------------------------------------------------

    if data == "offers_status":

        show_offers_status(
            chat_id
        )

        return


# ============================================================
# ОБРАБОТКА СООБЩЕНИЙ
# ============================================================

def process_message(
    message,
):

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
        message.get(
            "text"
        )
        or ""
    ).strip()

    # Только ветка 76303.
    if thread_id != TELEGRAM_THREAD_ID:
        return

    # --------------------------------------------------------
    # START
    # --------------------------------------------------------

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

                f"Сервер: "
                f"<b>{SERVER_NAME}</b>\n"

                f"Вражеский альянс: "
                f"<b>{ENEMY_ALLIANCE_NAME}</b>\n\n"

                "Выберите действие:"
            ),
            reply_markup=main_menu(),
        )

        return

    # --------------------------------------------------------
    # MENU
    # --------------------------------------------------------

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
            reply_markup=main_menu(),
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

    # ========================================================
    # ОТЧЁТ ОБ АТАКЕ
    # ========================================================

    if flow == "attack":

        # ----------------------------------------------------
        # Координаты
        # ----------------------------------------------------

        if step == "own_coords":

            coords = parse_coordinates(
                text
            )

            if not coords:

                send_message(
                    chat_id,
                    (
                        "❌ Неверный формат.\n\n"
                        "Введите координаты "
                        "например:\n"
                        "<code>46|-62</code>"
                    ),
                    reply_markup=cancel_keyboard(),
                )

                return

            session[
                "own_coords"
            ] = coords

            attack_choose_offer(
                chat_id,
                user_id,
            )

            return

        # ----------------------------------------------------
        # Количество волн
        # ----------------------------------------------------

        if step == "waves":

            waves = parse_integer(
                text
            )

            if waves is None or waves <= 0:

                send_message(
                    chat_id,
                    (
                        "Введите положительное "
                        "целое число волн."
                    ),
                    reply_markup=cancel_keyboard(),
                )

                return

            session[
                "waves"
            ] = waves

            session[
                "step"
            ] = "detected_time"

            send_message(
                chat_id,
                (
                    "Введите серверное время, "
                    "когда вы заметили входящую атаку.\n\n"
                    "Например:\n"
                    "<code>08:37:12</code>"
                ),
                reply_markup=cancel_keyboard(),
            )

            return

        # ----------------------------------------------------
        # Время обнаружения
        # ----------------------------------------------------

        if step == "detected_time":

            seconds = parse_time(
                text
            )

            if seconds is None:

                send_message(
                    chat_id,
                    (
                        "❌ Неверный формат.\n\n"
                        "Введите, например:\n"
                        "<code>08:37:12</code>"
                    ),
                    reply_markup=cancel_keyboard(),
                )

                return

            session[
                "detected_time_text"
            ] = text

            session[
                "detected_time_seconds"
            ] = seconds

            session[
                "step"
            ] = "remaining"

            send_message(
                chat_id,
                (
                    "Теперь введите, сколько "
                    "времени оставалось до "
                    "прибытия атаки.\n\n"

                    "Это НЕ время суток.\n"
                    "Это длительность.\n\n"

                    "Например:\n"
                    "<code>18:36:55</code>"
                ),
                reply_markup=cancel_keyboard(),
            )

            return

        # ----------------------------------------------------
        # Остаток времени
        # ----------------------------------------------------

        if step == "remaining":

            seconds = parse_time(
                text
            )

            if seconds is None:

                send_message(
                    chat_id,
                    (
                        "❌ Неверный формат.\n\n"
                        "Введите длительность "
                        "например:\n"
                        "<code>18:36:55</code>"
                    ),
                    reply_markup=cancel_keyboard(),
                )

                return

            session[
                "remaining_text"
            ] = text

            session[
                "remaining_seconds"
            ] = seconds

            session[
                "step"
            ] = "offline"

            send_message(
                chat_id,
                (
                    "Сколько минут вы находились "
                    "офлайн до обнаружения атаки?\n\n"

                    "Например:\n"
                    "<code>27</code>"
                ),
                reply_markup=cancel_keyboard(),
            )

            return

        # ----------------------------------------------------
        # Офлайн
        # ----------------------------------------------------

        if step == "offline":

            minutes = parse_integer(
                text
            )

            if (
                minutes is None
                or minutes < 0
            ):

                send_message(
                    chat_id,
                    (
                        "Введите количество минут "
                        "целым числом.\n\n"
                        "Например:\n"
                        "<code>27</code>"
                    ),
                    reply_markup=cancel_keyboard(),
                )

                return

            session[
                "offline_minutes"
            ] = minutes

            finish_attack_report(
                chat_id,
                user_id,
            )

            return

    # ========================================================
    # РУЧНАЯ АРЕНА
    # ========================================================

    if flow == "manual_arena":

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
                        "Уровень Арены должен "
                        "быть от 0 до 20."
                    ),
                    reply_markup=cancel_keyboard(),
                )

                return

            save_manual_arena(
                chat_id,
                user_id,
                arena,
            )

            return

    # ========================================================
    # СКАУТ-ПРОВЕРКА
    # ========================================================

    if flow == "scout":

        # ----------------------------------------------------
        # ID атаки
        # ----------------------------------------------------

        if step == "attack_id":

            scout_attack_selected(
                chat_id,
                user_id,
                text,
            )

            return

        # ----------------------------------------------------
        # Проверяемая Арена
        # ----------------------------------------------------

        if step == "tested_arena":

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
                        "Уровень Арены должен "
                        "быть от 0 до 20."
                    ),
                    reply_markup=cancel_keyboard(),
                )

                return

            scout_arena_selected(
                chat_id,
                user_id,
                arena,
            )

            return

        # ----------------------------------------------------
        # Наблюдение
        # ----------------------------------------------------

        if step == "observed_change":

            scout_observation_entered(
                chat_id,
                user_id,
                text,
            )

            return


# ============================================================
# UPDATE
# ============================================================

def process_update(
    update,
):

    try:

        if "callback_query" in update:

            process_callback(
                update[
                    "callback_query"
                ]
            )

        elif "message" in update:

            process_message(
                update[
                    "message"
                ]
            )

    except Exception as error:

        print(
            "Ошибка обработки update:",
            error,
        )


# ============================================================
# ОСНОВНОЙ ЦИКЛ
# ============================================================

def run():

    if not TELEGRAM_TOKEN:

        raise RuntimeError(
            "Не задан TELEGRAM_TOKEN."
        )

    ensure_data()

    print(
        "attacks_bot started"
    )

    print(
        f"Server: {SERVER_NAME}"
    )

    print(
        f"Thread: {TELEGRAM_THREAD_ID}"
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

            updates = telegram(
                "getUpdates",
                **kwargs,
            )

            for update in updates:

                offset = (
                    update[
                        "update_id"
                    ]
                    + 1
                )

                process_update(
                    update
                )

        except requests.RequestException as error:

            print(
                "Ошибка соединения с Telegram:",
                error,
            )

            time.sleep(5)

        except Exception as error:

            print(
                "Ошибка основного цикла:",
                error,
            )

            time.sleep(5)


# ============================================================
# START
# ============================================================

if __name__ == "__main__":
    run()
