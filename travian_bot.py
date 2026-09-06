
import os
import re
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

# История ежедневных снимков.
SNAPSHOT_DIR = Path("data/snapshots")

# None = хранить всю историю. Позже можно, например, поставить 365.
RETENTION_DAYS = None

# Минимальное падение населения для отчёта.
POP_DROP_THRESHOLD = 50

# Минимальное население удалённого игрока.
DELETED_PLAYER_MIN_POP = 100

# ============================================================
# ВРАЖЕСКИЙ АЛЬЯНС
# ============================================================


ENEMY_ALLIANCE_ID = 5

# Тема Telegram, куда отправляются все отчёты.
THREAD_ID = 75792


def fail(message):
    print(f"ERROR: {message}")
    raise RuntimeError(message)


# ============================================================
# СКАЧИВАНИЕ MAP.SQL
# ============================================================

def download_map_data():
    """Скачивает актуальный map.sql с Travian."""
    print(f"Скачивание свежих данных с сервера {SERVER_URL}...")

    try:
        response = requests.get(MAP_SQL_URL, timeout=120)
        response.raise_for_status()

    except requests.RequestException as exc:
        fail(f"Ошибка скачивания данных Travian: {exc}")

    if not response.text.strip():
        fail("Travian вернул пустой map.sql.")

    print(f"Получено: {len(response.text):,} символов")

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
            values.append("".join(current).strip())
            current = []

        else:
            current.append(char)

    values.append("".join(current).strip())

    return values


def clean_sql_value(value):

    value = value.strip()

    if len(value) >= 2 and value[0] == "'" and value[-1] == "'":
        value = value[1:-1]
        value = value.replace("\\'", "'").replace("\\\\", "\\")

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

                    rows.append("".join(current))
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

    print(f"Найдено SQL-строк x_world: {len(rows):,}")

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
            # 3  tid
            # 4  vid
            # 5  village
            # 6  uid
            # 7  player
            # 8  aid
            # 9  alliance
            # 10 population

            field_id = int(clean_sql_value(parts[0]))

            x = clean_sql_value(parts[1])
            y = clean_sql_value(parts[2])

            tribe = int(clean_sql_value(parts[3]))

            village_id = int(clean_sql_value(parts[4]))
            village_name = clean_sql_value(parts[5])

            player_id = int(clean_sql_value(parts[6]))
            player_name = clean_sql_value(parts[7])

            alliance_id = int(clean_sql_value(parts[8]))
            alliance_name = clean_sql_value(parts[9])

            population = int(clean_sql_value(parts[10]))

            if player_id != 0:
                players.add((player_id, player_name))

            villages[village_id] = {
                "name": village_name,
                "x": x,
                "y": y,
                "uid": player_id,
                "player": player_name,
                "alliance_id": alliance_id,
                "alliance": alliance_name,
                "pop": population,
            }

        except (ValueError, IndexError):
            continue

    if not villages:
        fail("Парсер не нашёл ни одной деревни в map.sql.")

    print(
        f"Разобрано: {len(villages):,} деревень, "
        f"{len(players):,} игроков."
    )

    return villages, players


# ============================================================
# РАБОТА СО СНИМКАМИ
# ============================================================

def snapshot_path(date_string):

    dt = datetime.strptime(date_string, "%Y-%m-%d")

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
        sorted(SNAPSHOT_DIR.glob("**/map_*.sql"))
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
                (snapshot_date, path)
            )

    return (
        max(previous, key=lambda item: item[0])[1]
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
        "parse_mode": "Markdown",
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

        response.raise_for_status()

        result = response.json()

        if not result.get("ok"):

            fail(
                f"Telegram API вернул ошибку: {result}"
            )

    except requests.RequestException as exc:

        fail(
            f"Не удалось отправить сообщение "
            f"в Telegram: {exc}"
        )


def village_link(x, y):
    """Возвращает Markdown-ссылку на деревню по координатам."""

    url = (
        f"{SERVER_URL}/karte.php"
        f"?x={x}&y={y}"
    )

    return f"[{x}|{y}]({url})"


def escape_markdown(text):
    """Экранирует специальные символы Telegram Markdown."""

    if not text:
        return ""

    for char in [
        "\\",
        "*",
        "_",
        "`",
        "[",
    ]:
        text = text.replace(
            char,
            "\\" + char
        )

    return text


def player_with_alliance(player, alliance):
    """Формирует отображение игрока и его альянса."""

    player = escape_markdown(player)
    alliance = escape_markdown(alliance)

    if alliance:
        return f"*{player}* 🔴 {alliance}"

    return f"*{player}* ⚫ без альянса"


# ============================================================
# СРАВНЕНИЕ СНИМКОВ
# ============================================================

def compare_snapshots(raw_today, raw_previous):

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

            if previous_pop >= DELETED_PLAYER_MIN_POP:

                deleted_players.append(
                    (
                        p_id,
                        p_name,
                        previous_pop
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

        # Смена владельца.
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

        # Падение населения.
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
    # НЕАКТИВНЫЕ 24 ЧАСА
    # ========================================================

    inactive_players = []

    for p_id, p_name in p_today:

        pop_previous = sum(
            v["pop"]
            for v in v_previous.values()
            if v["uid"] == p_id
        )

        pop_today = sum(
            v["pop"]
            for v in v_today.values()
            if v["uid"] == p_id
        )

        if (
            pop_previous == pop_today
            and pop_today > 0
        ):

            inactive_players.append(
                (
                    p_id,
                    p_name,
                    pop_today
                )
            )

    print("\n=== НАЙДЕННЫЕ ИЗМЕНЕНИЯ ===")

    print(
        f"Удалённые аккаунты: "
        f"{len(deleted_players)}"
    )

    print(
        f"Захваты:            "
        f"{len(conquered_villages)}"
    )

    print(
        f"Падение населения:  "
        f"{len(dropped_pop_villages)}"
    )

    print(
        f"Неактивные игроки:  "
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
    Находит активность игроков указанного
    вражеского альянса между двумя снимками.

    Определяется:

    1. Новые деревни.
    2. Захваченные деревни.
    3. Потерянные деревни.

    Альянс задаётся в ENEMY_ALLIANCE.
    """

    v_today, _ = parse_map_data(
        raw_today
    )

    v_previous, _ = parse_map_data(
        raw_previous
    )

    enemy_alliance = ENEMY_ALLIANCE.strip()

    if not enemy_alliance:
        print(
            "ENEMY_ALLIANCE не задан. "
            "Проверка активности альянса пропущена."
        )

        return {
            "alliance": "",
            "founded": [],
            "captured": [],
            "lost": [],
        }

    founded = []
    captured = []
    lost = []

    # ========================================================
    # 1. НОВЫЕ ДЕРЕВНИ
    # ========================================================

    for v_id, today in v_today.items():

        # Деревни, которых вообще не было
        # в предыдущем снимке.
        if v_id not in v_previous:

            # Деревня принадлежит нужному альянсу.
            if (
                today["alliance"]
                == enemy_alliance
            ):

                founded.append(today)

    # ========================================================
    # 2. ЗАХВАТЫ
    # ========================================================

    for v_id, previous in v_previous.items():

        today = v_today.get(v_id)

        if not today:
            continue

        # Владелец изменился.
        if (
            previous["uid"] != today["uid"]
            and previous["uid"] != 0
        ):

            # Сегодня деревня принадлежит
            # нужному вражескому альянсу.
            if (
                today["alliance"]
                == enemy_alliance
            ):

                captured.append(
                    (
                        previous,
                        today
                    )
                )

    # ========================================================
    # 3. ПОТЕРИ
    # ========================================================

    for v_id, previous in v_previous.items():

        today = v_today.get(v_id)

        if not today:
            continue

        # Владелец изменился.
        if (
            previous["uid"] != today["uid"]
            and previous["uid"] != 0
        ):

            # Вчера деревня принадлежала
            # нужному вражескому альянсу.
            if (
                previous["alliance"]
                == enemy_alliance
            ):

                lost.append(
                    (
                        previous,
                        today
                    )
                )

    # Сначала самые интересные изменения.
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

    print("\n=== АКТИВНОСТЬ ВРАЖЕСКОГО АЛЬЯНСА ===")

    print(
        f"Альянс: {enemy_alliance}"
    )

    print(
        f"Новые деревни: {len(founded)}"
    )

    print(
        f"Захваты:       {len(captured)}"
    )

    print(
        f"Потери:        {len(lost)}"
    )

    return {
        "alliance": enemy_alliance,
        "founded": founded,
        "captured": captured,
        "lost": lost,
    }


# ============================================================
# НЕАКТИВНОСТЬ 3 ДНЯ
# ============================================================

def find_inactive_3_days(
    raw_today,
    raw_yesterday,
    raw_day_before
):
    """Находит игроков, население которых не менялось 3 дня подряд."""

    v_today, p_today = parse_map_data(
        raw_today
    )

    v_yesterday, _ = parse_map_data(
        raw_yesterday
    )

    v_day_before, _ = parse_map_data(
        raw_day_before
    )

    inactive_players = []

    for p_id, p_name in p_today:

        pop_today = sum(
            v["pop"]
            for v in v_today.values()
            if v["uid"] == p_id
        )

        pop_yesterday = sum(
            v["pop"]
            for v in v_yesterday.values()
            if v["uid"] == p_id
        )

        pop_day_before = sum(
            v["pop"]
            for v in v_day_before.values()
            if v["uid"] == p_id
        )

        if (
            pop_today > 0
            and pop_today == pop_yesterday
            and pop_today == pop_day_before
        ):

            inactive_players.append(
                (
                    p_id,
                    p_name,
                    pop_today
                )
            )

    inactive_players.sort(
        key=lambda x: x[2],
        reverse=True
    )

    return inactive_players


# ============================================================
# ОТПРАВКА ОТЧЁТОВ
# ============================================================

def send_reports(
    results,
    inactive_players_3d=None,
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
        "❌ *Удаленные аккаунты (Asia 7):*\n"
    )

    if deleted_players:

        for _, name, pop in deleted_players[:30]:

            report_del += (
                f"- {escape_markdown(name)} "
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
        "⚔️ *Захваченные деревни (Asia 7):*\n"
    )

    if conquered_villages:

        for previous, today in conquered_villages[:30]:

            report_conq += (
                f"- Деревня `{escape_markdown(today['name'])}` "
                f"{village_link(today['x'], today['y'])} "
                f"игрока "
                f"{player_with_alliance(previous['player'], previous['alliance'])} "
                f"захвачена игроком "
                f"{player_with_alliance(today['player'], today['alliance'])}\n"
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
        "📉 *Деревни с потерей населения (Asia 7):*\n"
    )

    if dropped_pop_villages:

        for today, diff in dropped_pop_villages[:30]:

            # Красные 🚨 полностью убраны.
            report_pop += (
                f"- Деревня `{escape_markdown(today['name'])}` "
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
        "💤 *Неактивны за последние 24 часа (Asia 7):*\n"
    )

    if inactive_players:

        inactive_players.sort(
            key=lambda x: x[2],
            reverse=True
        )

        for p_id, p_name, pop in inactive_players[:30]:

            profile_url = (
                f"{SERVER_URL}/profile/{p_id}"
            )

            report_inact += (
                f"- [{escape_markdown(p_name)}]"
                f"({profile_url}) — "
                f"население: {pop} "
                f"(без изменений за 24 часа)\n"
            )

    else:

        report_inact += (
            "Нет игроков без изменений "
            "за 24 часа.\n"
        )

    send_to_telegram(
        report_inact,
        THREAD_ID
    )

    # ========================================================
    # 5. НЕАКТИВНЫЕ 3 ДНЯ ПОДРЯД
    # ========================================================

    report_inact_3d = (
        "😴 *Неактивны 3 дня подряд (Asia 7):*\n"
    )

    if inactive_players_3d:

        for p_id, p_name, pop in inactive_players_3d[:30]:

            profile_url = (
                f"{SERVER_URL}/profile/{p_id}"
            )

            report_inact_3d += (
                f"- [{escape_markdown(p_name)}]"
                f"({profile_url}) — "
                f"население: {pop} "
                f"(без изменений 3 дня подряд)\n"
            )

    else:

        report_inact_3d += (
            "Нет игроков без изменений "
            "3 дня подряд.\n"
        )

    send_to_telegram(
        report_inact_3d,
        THREAD_ID
    )

    # ========================================================
    # 6. АКТИВНОСТЬ ВРАЖЕСКОГО АЛЬЯНСА
    # ========================================================

    if enemy_activity:

        alliance = enemy_activity["alliance"]

        report_enemy = (
            f"⚔️ *Активность альянса "
            f"{escape_markdown(alliance)} (Asia 7):*\n\n"
        )

        # ----------------------------------------------------
        # НОВЫЕ ДЕРЕВНИ
        # ----------------------------------------------------

        report_enemy += (
            "🆕 *Новые деревни:*\n"
        )

        if enemy_activity["founded"]:

            for village in enemy_activity["founded"][:30]:

                report_enemy += (
                    f"- Деревня "
                    f"`{escape_markdown(village['name'])}` "
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
            "⚔️ *Захваченные деревни:*\n"
        )

        if enemy_activity["captured"]:

            for previous, today in enemy_activity["captured"][:30]:

                report_enemy += (
                    f"- Деревня "
                    f"`{escape_markdown(today['name'])}` "
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
            "💀 *Потерянные деревни:*\n"
        )

        if enemy_activity["lost"]:

            for previous, today in enemy_activity["lost"][:30]:

                report_enemy += (
                    f"- Деревня "
                    f"`{escape_markdown(previous['name'])}` "
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

        send_to_telegram(
            report_enemy,
            THREAD_ID
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

    print("========================================")
    print("       TRAVIAN DAILY ANALYSIS")
    print("========================================")

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
            "🟢 *Бот Travian запущен "
            "в режиме исторических снимков.*\n"
            f"Первый снимок: `{today_string}`.\n"
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
    # СРАВНЕНИЕ СЕГОДНЯ ↔ ВЧЕРА
    # ========================================================

    results = compare_snapshots(
        raw_today,
        raw_previous
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

    # ========================================================
    # НЕАКТИВНОСТЬ 3 ДНЯ ПОДРЯД
    # ========================================================

    inactive_players_3d = None

    if day_before_path is not None:

        print(
            f"Снимок позавчера найден: "
            f"{day_before_path}"
        )

        raw_day_before = (
            day_before_path.read_text(
                encoding="utf-8"
            )
        )

        inactive_players_3d = (
            find_inactive_3_days(
                raw_today,
                raw_previous,
                raw_day_before
            )
        )

        print(
            f"Неактивны 3 дня подряд: "
            f"{len(inactive_players_3d)} игроков"
        )

    else:

        print(
            "Снимок позавчера не найден — "
            "проверка неактивности "
            "за 3 дня пропущена."
        )

    # ========================================================
    # ОТПРАВКА ОТЧЁТОВ
    # ========================================================

    send_reports(
        results,
        inactive_players_3d,
        enemy_activity
    )

    # ========================================================
    # ОЧИСТКА СТАРЫХ СНИМКОВ
    # ========================================================

    cleanup_old_snapshots()

    print(
        f"Текущий снимок: {current_path}"
    )

    print("=== ГОТОВО ===")


if __name__ == "__main__":
    main()

