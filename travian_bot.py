
import os
import re
import html
from datetime import datetime, timezone, timedelta
from pathlib import Path

import requests


# ============================================================
# НАСТРОЙКИ
# ============================================================

TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID")

SERVER_URL = "https://ts7.x1.asia.travian.com"
MAP_SQL_URL = f"{SERVER_URL}/map.sql"

SNAPSHOT_DIR = Path("data/snapshots")

# None = хранить всю историю
RETENTION_DAYS = None

# Минимальное падение населения для отчёта
POP_DROP_THRESHOLD = 50

# Минимальное население удалённого игрока
DELETED_PLAYER_MIN_POP = 100


# ============================================================
# ВРАЖЕСКИЙ АЛЬЯНС
# ============================================================

# Постоянный ID альянса Hero
ENEMY_ALLIANCE_ID = 5

# Тема Telegram
THREAD_ID = 75792


# ============================================================
# ИКОНКИ ПЛЕМЁН
# ============================================================

# Travian map.sql:
# 1 = Romans
# 2 = Teutons
# 3 = Gauls

TRIBE_ICONS = {
    1: "🏛️",  # Римляне
    2: "🪓",  # Германцы
    3: "🛡️",  # Галлы
}


def tribe_icon(tribe_id):
    """
    Возвращает иконку племени.

    Для неизвестного племени используется нейтральная
    иконка, чтобы отчёт не ломался.
    """

    try:
        tribe_id = int(tribe_id)
    except (TypeError, ValueError):
        return "👤"

    return TRIBE_ICONS.get(
        tribe_id,
        "👤"
    )


# ============================================================
# ОШИБКИ
# ============================================================

def fail(message):
    print(f"ERROR: {message}")
    raise RuntimeError(message)


# ============================================================
# СКАЧИВАНИЕ MAP.SQL
# ============================================================

def download_map_data():
    """Скачивает актуальный map.sql с Travian."""

    print(
        f"Скачивание свежих данных с сервера {SERVER_URL}..."
    )

    try:
        response = requests.get(
            MAP_SQL_URL,
            timeout=120
        )

        response.raise_for_status()

    except requests.RequestException as exc:
        fail(
            f"Ошибка скачивания данных Travian: {exc}"
        )

    if not response.text.strip():
        fail(
            "Travian вернул пустой map.sql."
        )

    print(
        f"Получено: {len(response.text):,} символов"
    )

    return response.text


# ============================================================
# ПАРСИНГ SQL
# ============================================================

def parse_sql_tuple(line):
    """Разбирает SQL-строку, не ломаясь на запятых внутри кавычек."""

    values = []
    current = []
    quote = None
    escape = False

    for char in line:

        if escape:
            current.append(char)
            escape = False
            continue

        if char == "\\":
            current.append(char)
            escape = True
            continue

        if quote:
            current.append(char)

            if char == quote:
                quote = None

            continue

        if char in ("'", '"'):
            quote = char
            current.append(char)

        elif char == ",":
            values.append(
                "".join(current).strip()
            )
            current = []

        else:
            current.append(char)

    values.append(
        "".join(current).strip()
    )

    return values


def clean_sql_value(value):
    value = value.strip()

    if (
        len(value) >= 2
        and value[0] == "'"
        and value[-1] == "'"
    ):
        value = value[1:-1]

        value = (
            value
            .replace("\\'", "'")
            .replace("\\\\", "\\")
        )

    return value


def extract_value_rows(raw_data):
    """Извлекает все строки VALUES из INSERT INTO `x_world`."""

    rows = []

    statements = re.findall(
        r"INSERT\s+INTO\s+`x_world`\s+VALUES\s*(.*?);",
        raw_data,
        flags=re.IGNORECASE | re.DOTALL,
    )

    for values_part in statements:

        current = []
        depth = 0
        quote = None
        escape = False

        for char in values_part:

            if escape:

                if depth > 0:
                    current.append(char)

                escape = False
                continue

            if char == "\\":

                if depth > 0:
                    current.append(char)

                escape = True
                continue

            if quote:

                if depth > 0:
                    current.append(char)

                if char == quote:
                    quote = None

                continue

            if char in ("'", '"'):

                quote = char

                if depth > 0:
                    current.append(char)

                continue

            if char == "(":

                if depth == 0:
                    current = []

                depth += 1

                if depth > 1:
                    current.append(char)

                continue

            if char == ")":

                depth -= 1

                if depth == 0:

                    rows.append(
                        "".join(current)
                    )

                    current = []

                elif depth > 0:

                    current.append(char)

                continue

            if depth > 0:
                current.append(char)

    return rows


def parse_map_data(raw_data):
    """Парсит map.sql Travian по структуре таблицы x_world."""

    villages = {}
    players = set()

    rows = extract_value_rows(raw_data)

    print(
        f"Найдено SQL-строк x_world: {len(rows):,}"
    )

    for row in rows:

        try:

            parts = parse_sql_tuple(row)

            if len(parts) < 11:
                continue

            # Структура x_world:
            #
            # 0  id
            # 1  x
            # 2  y
            # 3  tid      ← племя
            # 4  vid
            # 5  village
            # 6  uid
            # 7  player
            # 8  aid
            # 9  alliance
            # 10 population

            x = clean_sql_value(parts[1])
            y = clean_sql_value(parts[2])

            tribe_id = int(
                clean_sql_value(parts[3])
            )

            village_id = int(
                clean_sql_value(parts[4])
            )

            village_name = clean_sql_value(
                parts[5]
            )

            player_id = int(
                clean_sql_value(parts[6])
            )

            player_name = clean_sql_value(
                parts[7]
            )

            alliance_id = int(
                clean_sql_value(parts[8])
            )

            alliance_name = clean_sql_value(
                parts[9]
            )

            population = int(
                clean_sql_value(parts[10])
            )

            if player_id != 0:

                players.add(
                    (
                        player_id,
                        player_name
                    )
                )

            villages[village_id] = {
                "name": village_name,
                "x": x,
                "y": y,
                "tribe_id": tribe_id,
                "player": player_name,
                "uid": player_id,
                "alliance_id": alliance_id,
                "alliance": alliance_name,
                "pop": population,
            }

        except (ValueError, IndexError):

            continue

    if not villages:
        fail(
            "Парсер не нашёл ни одной деревни в map.sql."
        )

    print(
        f"Разобрано: {len(villages):,} деревень, "
        f"{len(players):,} игроков."
    )

    return villages, players


# ============================================================
# РАБОТА СО СНИМКАМИ
# ============================================================

def snapshot_path(date_string):

    dt = datetime.strptime(
        date_string,
        "%Y-%m-%d"
    )

    directory = (
        SNAPSHOT_DIR
        / f"{dt.year:04d}"
        / f"{dt.month:02d}"
    )

    directory.mkdir(
        parents=True,
        exist_ok=True
    )

    return directory / f"map_{date_string}.sql"


def find_snapshot_by_date(date_string):
    """Возвращает снимок конкретной даты, если он существует."""

    path = snapshot_path(date_string)

    if path.exists():
        return path

    return None


def save_snapshot(raw_data, date_string):

    path = snapshot_path(date_string)

    path.write_text(
        raw_data,
        encoding="utf-8"
    )

    print(
        f"Снимок сохранён: {path} "
        f"({len(raw_data):,} символов)"
    )

    return path


def find_previous_snapshot(date_string):
    """Ищет последний доступный снимок до текущей даты."""

    current_date = datetime.strptime(
        date_string,
        "%Y-%m-%d"
    ).date()

    candidates = (
        sorted(
            SNAPSHOT_DIR.glob("**/map_*.sql")
        )
        if SNAPSHOT_DIR.exists()
        else []
    )

    previous = []

    for path in candidates:

        match = re.search(
            r"map_(\d{4}-\d{2}-\d{2})\.sql$",
            path.name
        )

        if not match:
            continue

        try:

            snapshot_date = datetime.strptime(
                match.group(1),
                "%Y-%m-%d"
            ).date()

        except ValueError:

            continue

        if snapshot_date < current_date:

            previous.append(
                (
                    snapshot_date,
                    path
                )
            )

    return (
        max(
            previous,
            key=lambda item: item[0]
        )[1]
        if previous
        else None
    )


# ============================================================
# TELEGRAM
# ============================================================

def send_to_telegram(message, thread_id=None):

    if not message.strip():
        return

    if not TELEGRAM_TOKEN or not TELEGRAM_CHAT_ID:
        fail(
            "Не заданы TELEGRAM_TOKEN "
            "и/или TELEGRAM_CHAT_ID."
        )

    url = (
        f"https://api.telegram.org/"
        f"bot{TELEGRAM_TOKEN}/sendMessage"
    )

    payload = {
        "chat_id": TELEGRAM_CHAT_ID,
        "text": message,
        "parse_mode": "HTML",
        "disable_web_page_preview": True,
    }

    if thread_id:
        payload["message_thread_id"] = thread_id

    try:
        response = requests.post(
            url,
            json=payload,
            timeout=30
        )

        try:
            result = response.json()
        except ValueError:
            result = {"raw_response": response.text}

        if not response.ok or not result.get("ok"):
            fail(
                "Telegram API вернул ошибку "
                f"HTTP {response.status_code}: {result}"
            )

    except requests.RequestException as exc:
        response_text = ""
        if getattr(exc, "response", None) is not None:
            try:
                response_text = exc.response.text
            except Exception:
                response_text = ""

        details = (
            f"; ответ Telegram: {response_text}"
            if response_text
            else ""
        )

        fail(
            "Не удалось отправить сообщение "
            f"в Telegram: {exc}{details}"
        )


def html_escape(text):
    """Безопасно экранирует динамический текст для Telegram HTML."""
    return html.escape(str(text or ""), quote=True)


def village_link(x, y):
    """HTML-ссылка на деревню по координатам."""
    url = (
        f"{SERVER_URL}/karte.php"
        f"?x={x}&y={y}"
    )

    return (
        f'<a href="{html_escape(url)}">'
        f'{html_escape(x)}|{html_escape(y)}'
        f'</a>'
    )


def player_with_alliance(player, alliance):
    """Формирует безопасное HTML-отображение игрока и альянса."""
    player = html_escape(player)
    alliance = html_escape(alliance)

    if alliance:
        return f"<b>{player}</b> 🔴 {alliance}"

    return f"<b>{player}</b> ⚫ без альянса"


def player_with_tribe_and_alliance(
    player,
    alliance,
    tribe_id
):
    """
    Форматирование игрока для блока захватов.

    Формат:
    🏛️ Игрок — Альянс

    Иконка определяется по tid из map.sql.
    """

    icon = tribe_icon(tribe_id)

    player = html_escape(player)
    alliance = html_escape(alliance)

    if alliance:
        return (
            f"{icon} <b>{player}</b>"
            f" — {alliance}"
        )

    return (
        f"{icon} <b>{player}</b>"
        f" — без альянса"
    )


# ============================================================
# СРАВНЕНИЕ СНИМКОВ
# ============================================================

def compare_snapshots(
    raw_today,
    raw_previous,
    raw_day_before
):

    v_today, p_today = parse_map_data(
        raw_today
    )

    v_previous, p_previous = parse_map_data(
        raw_previous
    )

    print("\n=== СТАТИСТИКА СНИМКОВ ===")

    print(
        f"Сегодня: {len(v_today):,} деревень / "
        f"{len(p_today):,} игроков"
    )

    print(
        f"Ранее:   {len(v_previous):,} деревень / "
        f"{len(p_previous):,} игроков"
    )

    # ========================================================
    # УДАЛЁННЫЕ АККАУНТЫ
    # ========================================================

    today_uids = {
        p_id
        for p_id, _ in p_today
    }

    deleted_players = []

    for p_id, p_name in p_previous:

        if p_id not in today_uids:

            previous_pop = sum(
                v["pop"]
                for v in v_previous.values()
                if v["uid"] == p_id
            )

            if (
                previous_pop
                >= DELETED_PLAYER_MIN_POP
            ):

                # Последний альянс игрока перед удалением.
                # Берём его из предыдущего снимка.
                last_alliance = ""

                for village in v_previous.values():

                    if (
                        village["uid"] == p_id
                        and village["alliance"]
                    ):
                        last_alliance = village["alliance"]
                        break

                deleted_players.append(
                    (
                        p_id,
                        p_name,
                        previous_pop,
                        last_alliance
                    )
                )

    # ========================================================
    # ЗАХВАТЫ И ПАДЕНИЕ НАСЕЛЕНИЯ
    # ========================================================

    conquered_villages = []
    dropped_pop_villages = []

    for v_id, previous in v_previous.items():

        today = v_today.get(v_id)

        if not today:
            continue

        if (
            previous["uid"] != today["uid"]
            and previous["uid"] != 0
        ):

            conquered_villages.append(
                (
                    previous,
                    today
                )
            )

        elif today["pop"] < previous["pop"]:

            diff = (
                previous["pop"]
                - today["pop"]
            )

            if diff >= POP_DROP_THRESHOLD:

                dropped_pop_villages.append(
                    (
                        today,
                        diff
                    )
                )

    # ========================================================
    # НЕАКТИВНЫЕ ЗА ПОСЛЕДНИЕ 24 ЧАСА
    # ========================================================

    inactive_players = []

    if raw_day_before is not None:
        v_day_before, _ = parse_map_data(
            raw_day_before
        )
    else:
        v_day_before = {}

    for p_id, p_name in p_today:

        pop_today = sum(
            v["pop"]
            for v in v_today.values()
            if v["uid"] == p_id
        )

        pop_yesterday = sum(
            v["pop"]
            for v in v_previous.values()
            if v["uid"] == p_id
        )

        pop_day_before = sum(
            v["pop"]
            for v in v_day_before.values()
            if v["uid"] == p_id
        )

        # Показываем игрока, если он не изменился
        # сегодня относительно вчера, но при этом
        # вчера отличался от позавчера.
        if (
            raw_day_before is not None
            and pop_today > 100
            and pop_today == pop_yesterday
            and pop_yesterday != pop_day_before
        ):

            alliance = ""

            for village in v_today.values():

                if (
                    village["uid"] == p_id
                    and village["alliance"]
                ):

                    alliance = village["alliance"]
                    break

            inactive_players.append(
                (
                    p_id,
                    p_name,
                    alliance
                )
            )

    print("\n=== НАЙДЕННЫЕ ИЗМЕНЕНИЯ ===")

    print(
        f"Удалённые аккаунты: "
        f"{len(deleted_players)}"
    )

    print(
        f"Захваты: "
        f"{len(conquered_villages)}"
    )

    print(
        f"Падение населения: "
        f"{len(dropped_pop_villages)}"
    )

    print(
        f"Неактивные игроки: "
        f"{len(inactive_players)}"
    )

    return (
        deleted_players,
        conquered_villages,
        dropped_pop_villages,
        inactive_players
    )


# ============================================================
# АКТИВНОСТЬ ВРАЖЕСКОГО АЛЬЯНСА
# ============================================================

def find_enemy_alliance_activity(
    raw_today,
    raw_previous
):
    """
    Анализирует активность альянса по постоянному ID.

    Определяется:

    1. Новые деревни.
    2. Захваченные деревни.
    3. Потерянные деревни.
    """

    print(
        "\n=== ПРОВЕРКА ВРАЖЕСКОГО АЛЬЯНСА ==="
    )

    print(
        f"Искомый alliance_id: "
        f"{ENEMY_ALLIANCE_ID}"
    )

    v_today, _ = parse_map_data(
        raw_today
    )

    v_previous, _ = parse_map_data(
        raw_previous
    )

    # ========================================================
    # ИЩЕМ ТЕКУЩЕЕ НАЗВАНИЕ АЛЬЯНСА
    # ========================================================

    alliance_name = ""

    enemy_villages_today = []

    for village in v_today.values():

        if (
            village["alliance_id"]
            == ENEMY_ALLIANCE_ID
        ):

            enemy_villages_today.append(
                village
            )

            if not alliance_name:

                alliance_name = (
                    village["alliance"]
                )

    # Если сегодня деревень альянса нет,
    # ищем название во вчерашнем снимке.

    if not alliance_name:

        for village in v_previous.values():

            if (
                village["alliance_id"]
                == ENEMY_ALLIANCE_ID
            ):

                alliance_name = (
                    village["alliance"]
                )

                break

    if not alliance_name:

        alliance_name = (
            f"ID {ENEMY_ALLIANCE_ID}"
        )

    founded = []
    captured = []
    lost = []

    # ========================================================
    # 1. НОВЫЕ ДЕРЕВНИ
    # ========================================================

    for v_id, today in v_today.items():

        if v_id not in v_previous:

            if (
                today["alliance_id"]
                == ENEMY_ALLIANCE_ID
            ):

                founded.append(
                    today
                )

    # ========================================================
    # 2. ЗАХВАТЫ HERO
    # ========================================================

    for v_id, previous in v_previous.items():

        today = v_today.get(v_id)

        if not today:
            continue

        if (
            previous["uid"] != today["uid"]
            and previous["uid"] != 0
        ):

            # Сегодня деревня принадлежит Hero,
            # вчера принадлежала другому альянсу.

            if (
                today["alliance_id"]
                == ENEMY_ALLIANCE_ID
                and previous["alliance_id"]
                != ENEMY_ALLIANCE_ID
            ):

                captured.append(
                    (
                        previous,
                        today
                    )
                )

    # ========================================================
    # 3. ПОТЕРИ HERO
    # ========================================================

    for v_id, previous in v_previous.items():

        today = v_today.get(v_id)

        if not today:
            continue

        if (
            previous["uid"] != today["uid"]
            and previous["uid"] != 0
        ):

            # Вчера деревня принадлежала Hero,
            # сегодня принадлежит другому альянсу.

            if (
                previous["alliance_id"]
                == ENEMY_ALLIANCE_ID
                and today["alliance_id"]
                != ENEMY_ALLIANCE_ID
            ):

                lost.append(
                    (
                        previous,
                        today
                    )
                )

    # ========================================================
    # СОРТИРОВКА
    # ========================================================

    founded.sort(
        key=lambda v: (
            int(v["x"]),
            int(v["y"])
        )
    )

    captured.sort(
        key=lambda item: (
            int(item[1]["x"]),
            int(item[1]["y"])
        )
    )

    lost.sort(
        key=lambda item: (
            int(item[0]["x"]),
            int(item[0]["y"])
        )
    )

    # ========================================================
    # ДИАГНОСТИКА
    # ========================================================

    print(
        f"Название альянса: {alliance_name}"
    )

    print(
        f"Деревень альянса сегодня: "
        f"{len(enemy_villages_today)}"
    )

    print(
        f"Новые деревни: "
        f"{len(founded)}"
    )

    print(
        f"Захваты Hero: "
        f"{len(captured)}"
    )

    print(
        f"Потери Hero: "
        f"{len(lost)}"
    )

    if not enemy_villages_today:

        print(
            f"ВНИМАНИЕ: в сегодняшнем map.sql "
            f"не найдено деревень с alliance_id "
            f"{ENEMY_ALLIANCE_ID}."
        )

    print(
        "=== ПРОВЕРКА ВРАЖЕСКОГО АЛЬЯНСА ЗАВЕРШЕНА ==="
    )

    return {
        "alliance_id": ENEMY_ALLIANCE_ID,
        "alliance": alliance_name,
        "founded": founded,
        "captured": captured,
        "lost": lost,
    }


# ============================================================
# ОТПРАВКА ОТЧЁТОВ
# ============================================================

def send_reports(
    results,
    enemy_activity=None
):

    (
        deleted_players,
        conquered_villages,
        dropped_pop_villages,
        inactive_players
    ) = results

    # ========================================================
    # 1. УДАЛЁННЫЕ АККАУНТЫ
    # ========================================================

    report_del = (
        "❌ <b>Удаленные аккаунты (Asia 7):</b>\n"
    )

    if deleted_players:

        for _, name, pop, alliance in deleted_players[:30]:

            alliance_text = (
                f" ({html_escape(alliance)})"
                if alliance
                else " (без альянса)"
            )

            report_del += (
                f"- {html_escape(name)}"
                f"{alliance_text} "
                f"(население: {pop})\n"
            )

    else:

        report_del += (
            "Нет изменений за период.\n"
        )

    send_to_telegram(
        report_del,
        THREAD_ID
    )

    # ========================================================
    # 2. ЗАХВАЧЕННЫЕ ДЕРЕВНИ
    # ========================================================

    report_conq = (
        "⚔️ <b>Захваченные деревни (Asia 7):</b>\n\n"
    )

    if conquered_villages:

        for number, (previous, today) in enumerate(
            conquered_villages[:30],
            start=1
        ):

            # Игрок, который получил деревню.
            new_owner = player_with_tribe_and_alliance(
                today["player"],
                today["alliance"],
                today["tribe_id"]
            )

            # Игрок, который потерял деревню.
            old_owner = player_with_tribe_and_alliance(
                previous["player"],
                previous["alliance"],
                previous["tribe_id"]
            )

            report_conq += (
                f"<b>{number}.</b> "
                f"{new_owner}\n"
                f"      ⬇️ <b>ЗАХВАТИЛ У</b>\n"
                f"   {old_owner}\n\n"
                f"   👥 {previous['pop']} → {today['pop']}\n"
                f"   📍 {village_link(today['x'], today['y'])}\n"
            )

            if number < min(
                len(conquered_villages),
                30
            ):
                report_conq += (
                    "\n"
                    "────────────────────\n\n"
                )

    else:

        report_conq += (
            "Нет изменений за период.\n"
        )

    send_to_telegram(
        report_conq,
        THREAD_ID
    )

    # ========================================================
    # 3. ПАДЕНИЕ НАСЕЛЕНИЯ
    # ========================================================

    report_pop = (
        "📉 <b>Кого катали за прошедшие сутки (Asia 7):</b>\n"
    )

    if dropped_pop_villages:

        for today, diff in dropped_pop_villages[:30]:

            report_pop += (
                f"- Деревня "
                f"<code>{html_escape(today['name'])}</code> "
                f"{village_link(today['x'], today['y'])} "
                f"игрока "
                f"{player_with_alliance(today['player'], today['alliance'])}: "
                f"-{diff} "
                f"(сейчас: {today['pop']})\n"
            )

    else:

        report_pop += (
            "Нет изменений за период.\n"
        )

    send_to_telegram(
        report_pop,
        THREAD_ID
    )

    # ========================================================
    # 4. НЕАКТИВНЫЕ ЗА 24 ЧАСА
    # ========================================================

    report_inact = (
        "💤 <b>Неактивны за последние 24 часа (Asia 7):</b>\n"
    )

    if inactive_players:

        inactive_players.sort(
            key=lambda x: x[1].lower()
        )

        for p_id, p_name, alliance in inactive_players[:30]:

            profile_url = (
                f"{SERVER_URL}/profile/{p_id}"
            )

            alliance_text = (
                html_escape(alliance)
                if alliance
                else "без альянса"
            )

            report_inact += (
                f'- <a href="{html_escape(profile_url)}">'
                f'{html_escape(p_name)}</a> — '
                f'{alliance_text}\n'
            )

    else:

        report_inact += (
            "Нет игроков, которые были неактивны "
            "только сегодня и вчера.\n"
        )

    send_to_telegram(
        report_inact,
        THREAD_ID
    )

    # ========================================================
    # 5. АКТИВНОСТЬ ВРАЖЕСКОГО АЛЬЯНСА
    # ========================================================

    print(
        "\n=== ПОДГОТОВКА ОТЧЁТА ВРАЖЕСКОГО АЛЬЯНСА ==="
    )

    if enemy_activity is None:

        print(
            "ВНИМАНИЕ: enemy_activity = None"
        )

        report_enemy = (
            "⚠️ <b>Активность альянса:</b>\n"
            "Данные об альянсе не получены."
        )

    else:

        alliance = enemy_activity["alliance"]

        alliance_id = (
            enemy_activity["alliance_id"]
        )

        report_enemy = (
            f"⚔️ <b>Активность альянса "
            f"{html_escape(alliance)} "
            f"(ID: {alliance_id}, Asia 7):</b>\n\n"
        )

        # ----------------------------------------------------
        # НОВЫЕ ДЕРЕВНИ
        # ----------------------------------------------------

        report_enemy += (
            "🆕 <b>Новые деревни:</b>\n"
        )

        if enemy_activity["founded"]:

            for village in enemy_activity["founded"][:30]:

                report_enemy += (
                    f"- Деревня "
                    f"<code>{html_escape(village['name'])}</code> "
                    f"{village_link(village['x'], village['y'])} "
                    f"основана игроком "
                    f"{player_with_alliance(village['player'], village['alliance'])}\n"
                )

        else:

            report_enemy += (
                "Нет новых деревень.\n"
            )

        report_enemy += "\n"

        # ----------------------------------------------------
        # ЗАХВАЧЕННЫЕ
        # ----------------------------------------------------

        report_enemy += (
            "⚔️ <b>Захваченные деревни:</b>\n"
        )

        if enemy_activity["captured"]:

            for previous, today in enemy_activity["captured"][:30]:

                report_enemy += (
                    f"- Деревня "
                    f"<code>{html_escape(today['name'])}</code> "
                    f"{village_link(today['x'], today['y'])} "
                    f"захвачена игроком "
                    f"{player_with_alliance(today['player'], today['alliance'])} "
                    f"у "
                    f"{player_with_alliance(previous['player'], previous['alliance'])}\n"
                )

        else:

            report_enemy += (
                "Нет захватов.\n"
            )

        report_enemy += "\n"

        # ----------------------------------------------------
        # ПОТЕРЯННЫЕ
        # ----------------------------------------------------

        report_enemy += (
            "💀 <b>Потерянные деревни:</b>\n"
        )

        if enemy_activity["lost"]:

            for previous, today in enemy_activity["lost"][:30]:

                report_enemy += (
                    f"- Деревня "
                    f"<code>{html_escape(previous['name'])}</code> "
                    f"{village_link(previous['x'], previous['y'])} "
                    f"потеряна игроком "
                    f"{player_with_alliance(previous['player'], previous['alliance'])} "
                    f"в пользу "
                    f"{player_with_alliance(today['player'], today['alliance'])}\n"
                )

        else:

            report_enemy += (
                "Нет потерянных деревень.\n"
            )

    print(
        f"Длина отчёта Hero: "
        f"{len(report_enemy)} символов"
    )

    print(
        "Отправка отчёта Hero в Telegram..."
    )

    send_to_telegram(
        report_enemy,
        THREAD_ID
    )

    print(
        "=== ОТЧЁТ HERO ОТПРАВЛЕН ==="
    )


# ============================================================
# УДАЛЕНИЕ СТАРЫХ СНИМКОВ
# ============================================================

def cleanup_old_snapshots():

    if RETENTION_DAYS is None:
        return

    cutoff = (
        datetime.now(timezone.utc)
        .date()
        .toordinal()
        - RETENTION_DAYS
    )

    deleted = 0

    for path in SNAPSHOT_DIR.glob(
        "**/map_*.sql"
    ):

        match = re.search(
            r"map_(\d{4}-\d{2}-\d{2})\.sql$",
            path.name
        )

        if not match:
            continue

        try:

            file_date = datetime.strptime(
                match.group(1),
                "%Y-%m-%d"
            ).date()

        except ValueError:

            continue

        if file_date.toordinal() < cutoff:

            path.unlink()
            deleted += 1

    if deleted:

        print(
            f"Удалено старых снимков: {deleted}"
        )


# ============================================================
# MAIN
# ============================================================

def main():

    today_string = (
        datetime.now(timezone.utc)
        .date()
        .isoformat()
    )

    print(
        "========================================"
    )

    print(
        "       TRAVIAN DAILY ANALYSIS"
    )

    print(
        "========================================"
    )

    print(
        f"Дата снимка: {today_string}"
    )

    # ========================================================
    # СКАЧИВАЕМ СВЕЖИЙ СНИМОК
    # ========================================================

    raw_today = download_map_data()

    v_today, p_today = parse_map_data(
        raw_today
    )

    print(
        f"Проверка нового снимка OK: "
        f"{len(v_today):,} деревень / "
        f"{len(p_today):,} игроков"
    )

    # ========================================================
    # ПРЕДЫДУЩИЙ СНИМОК
    # ========================================================

    previous_path = find_previous_snapshot(
        today_string
    )

    # ========================================================
    # СОХРАНЯЕМ СЕГОДНЯШНИЙ СНИМОК
    # ========================================================

    current_path = save_snapshot(
        raw_today,
        today_string
    )

    # ========================================================
    # ПЕРВАЯ ТОЧКА ИСТОРИИ
    # ========================================================

    if previous_path is None:

        print(
            "Предыдущий снимок не найден — "
            "создана первая точка истории."
        )

        send_to_telegram(
            "🟢 <b>Бот Travian запущен "
            "в режиме исторических снимков.</b>\n"
            f"Первый снимок: <code>{html_escape(today_string)}</code>.\n"
            "Начиная со следующего снимка "
            "будет выполняться сравнительный анализ.",
            THREAD_ID,
        )

        cleanup_old_snapshots()

        return

    print(
        f"Предыдущий снимок: {previous_path}"
    )

    raw_previous = previous_path.read_text(
        encoding="utf-8"
    )

    # ========================================================
    # ПОИСК СНИМКА ПОЗАВЧЕРА
    # ========================================================

    today_date = datetime.strptime(
        today_string,
        "%Y-%m-%d"
    ).date()

    day_before_date = (
        today_date
        - timedelta(days=2)
    ).isoformat()

    day_before_path = find_snapshot_by_date(
        day_before_date
    )

    if day_before_path is None:

        print(
            "Снимок позавчера не найден — "
            "отчёт по неактивности пропущен."
        )

        raw_day_before = None

    else:

        print(
            f"Снимок позавчера найден: "
            f"{day_before_path}"
        )

        raw_day_before = (
            day_before_path.read_text(
                encoding="utf-8"
            )
        )

    # ========================================================
    # СРАВНЕНИЕ СЕГОДНЯ ↔ ВЧЕРА ↔ ПОЗАВЧЕРА
    # ========================================================

    results = compare_snapshots(
        raw_today,
        raw_previous,
        raw_day_before
    )

    # ========================================================
    # АКТИВНОСТЬ ВРАЖЕСКОГО АЛЬЯНСА
    # ========================================================

    enemy_activity = (
        find_enemy_alliance_activity(
            raw_today,
            raw_previous
        )
    )

    # ========================================================
    # ОТПРАВКА ОТЧЁТОВ
    # ========================================================

    send_reports(
        results,
        enemy_activity
    )

    # ========================================================
    # ОЧИСТКА СТАРЫХ СНИМКОВ
    # ========================================================

    cleanup_old_snapshots()

    print(
        f"Текущий снимок: {current_path}"
    )

    print(
        "=== ГОТОВО ==="
    )


if __name__ == "__main__":
    main()
