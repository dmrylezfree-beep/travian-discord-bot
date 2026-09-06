import os
import re
from datetime import datetime, timezone
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

POP_DROP_THRESHOLD = 10
DELETED_PLAYER_MIN_POP = 100

# Сейчас исходный бот отправлял все 4 отчёта в одну тему.
THREAD_ID = 75792


def fail(message):
    print(f"ERROR: {message}")
    raise RuntimeError(message)


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
    """Парсит map.sql по структуре, использованной исходным ботом."""
    villages = {}
    players = set()
    rows = extract_value_rows(raw_data)

    for row in rows:
        try:
            parts = parse_sql_tuple(row)
            if len(parts) < 9:
                continue

            v_id = int(clean_sql_value(parts[0]))
            x = clean_sql_value(parts[1])
            y = clean_sql_value(parts[2])
            v_name = clean_sql_value(parts[3])
            u_id = int(clean_sql_value(parts[4]))
            p_name = clean_sql_value(parts[5])
            pop = int(clean_sql_value(parts[8]))

            if u_id != 0:
                players.add((u_id, p_name))

            villages[v_id] = {
                "name": v_name,
                "x": x,
                "y": y,
                "uid": u_id,
                "player": p_name,
                "pop": pop,
            }
        except (ValueError, IndexError):
            continue

    if not villages:
        fail("Парсер не нашёл ни одной деревни в map.sql.")

    print(f"Разобрано: {len(villages):,} деревень, {len(players):,} игроков.")
    return villages, players


def snapshot_path(date_string):
    dt = datetime.strptime(date_string, "%Y-%m-%d")
    directory = SNAPSHOT_DIR / f"{dt.year:04d}" / f"{dt.month:02d}"
    directory.mkdir(parents=True, exist_ok=True)
    return directory / f"map_{date_string}.sql"


def save_snapshot(raw_data, date_string):
    path = snapshot_path(date_string)
    path.write_text(raw_data, encoding="utf-8")
    print(f"Снимок сохранён: {path} ({len(raw_data):,} символов)")
    return path


def find_previous_snapshot(date_string):
    """Ищет последний доступный снимок до текущей даты."""
    current_date = datetime.strptime(date_string, "%Y-%m-%d").date()
    candidates = sorted(SNAPSHOT_DIR.glob("**/map_*.sql")) if SNAPSHOT_DIR.exists() else []
    previous = []

    for path in candidates:
        match = re.search(r"map_(\d{4}-\d{2}-\d{2})\.sql$", path.name)
        if not match:
            continue
        try:
            snapshot_date = datetime.strptime(match.group(1), "%Y-%m-%d").date()
        except ValueError:
            continue
        if snapshot_date < current_date:
            previous.append((snapshot_date, path))

    return max(previous, key=lambda item: item[0])[1] if previous else None


def send_to_telegram(message, thread_id=None):
    if not message.strip():
        return
    if not TELEGRAM_TOKEN or not TELEGRAM_CHAT_ID:
        fail("Не заданы TELEGRAM_TOKEN и/или TELEGRAM_CHAT_ID.")

    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    payload = {
        "chat_id": TELEGRAM_CHAT_ID,
        "text": message,
        "parse_mode": "Markdown",
        "disable_web_page_preview": True,
    }
    if thread_id:
        payload["message_thread_id"] = thread_id

    try:
        response = requests.post(url, json=payload, timeout=30)
        response.raise_for_status()
        result = response.json()
        if not result.get("ok"):
            fail(f"Telegram API вернул ошибку: {result}")
    except requests.RequestException as exc:
        fail(f"Не удалось отправить сообщение в Telegram: {exc}")


def compare_snapshots(raw_today, raw_previous):
    v_today, p_today = parse_map_data(raw_today)
    v_previous, p_previous = parse_map_data(raw_previous)

    print("\n=== СТАТИСТИКА СНИМКОВ ===")
    print(f"Сегодня: {len(v_today):,} деревень / {len(p_today):,} игроков")
    print(f"Ранее:   {len(v_previous):,} деревень / {len(p_previous):,} игроков")

    today_uids = {p_id for p_id, _ in p_today}

    deleted_players = []
    for p_id, p_name in p_previous:
        if p_id not in today_uids:
            previous_pop = sum(v["pop"] for v in v_previous.values() if v["uid"] == p_id)
            if previous_pop >= DELETED_PLAYER_MIN_POP:
                deleted_players.append((p_id, p_name, previous_pop))

    conquered_villages = []
    dropped_pop_villages = []

    for v_id, previous in v_previous.items():
        today = v_today.get(v_id)
        if not today:
            continue

        if previous["uid"] != today["uid"] and previous["uid"] != 0:
            conquered_villages.append((previous, today))
        elif today["pop"] < previous["pop"]:
            diff = previous["pop"] - today["pop"]
            if diff >= POP_DROP_THRESHOLD:
                dropped_pop_villages.append((today, diff))

    inactive_players = []
    for p_id, p_name in p_today:
        pop_previous = sum(v["pop"] for v in v_previous.values() if v["uid"] == p_id)
        pop_today = sum(v["pop"] for v in v_today.values() if v["uid"] == p_id)
        if pop_previous == pop_today and pop_today > 0:
            inactive_players.append((p_id, p_name, pop_today))

    print("\n=== НАЙДЕННЫЕ ИЗМЕНЕНИЯ ===")
    print(f"Удалённые аккаунты: {len(deleted_players)}")
    print(f"Захваты:            {len(conquered_villages)}")
    print(f"Падение населения:  {len(dropped_pop_villages)}")
    print(f"Неактивные игроки:  {len(inactive_players)}")

    return deleted_players, conquered_villages, dropped_pop_villages, inactive_players


def send_reports(results):
    deleted_players, conquered_villages, dropped_pop_villages, inactive_players = results

    report_del = "❌ *Удаленные аккаунты (Asia 7):*\n"
    if deleted_players:
        for _, name, pop in deleted_players[:30]:
            report_del += f"- {name} (население: {pop})\n"
    else:
        report_del += "Нет изменений за период.\n"
    send_to_telegram(report_del, THREAD_ID)

    report_conq = "⚔️ *Захваченные деревни (Asia 7):*\n"
    if conquered_villages:
        for previous, today in conquered_villages[:30]:
            report_conq += (
                f"- Деревня `{today['name']}` ({today['x']}|{today['y']}) "
                f"игрока *{previous['player']}* захвачена игроком *{today['player']}*\n"
            )
    else:
        report_conq += "Нет изменений за период.\n"
    send_to_telegram(report_conq, THREAD_ID)

    report_pop = "📉 *Деревни с потерей населения (Asia 7):*\n"
    if dropped_pop_villages:
        for today, diff in dropped_pop_villages[:30]:
            if diff >= 150:
                report_pop += (
                    f"- 🚨🚨🚨 Деревня `{today['name']}` ({today['x']}|{today['y']}) "
                    f"игрока *{today['player']}*: -{diff} (сейчас: {today['pop']}) 🚨🚨🚨\n"
                )
            else:
                report_pop += (
                    f"- Деревня `{today['name']}` ({today['x']}|{today['y']}) "
                    f"игрока *{today['player']}*: -{diff} (сейчас: {today['pop']})\n"
                )
    else:
        report_pop += "Нет изменений за период.\n"
    send_to_telegram(report_pop, THREAD_ID)

    report_inact = "💤 *Неактивны за период (Asia 7):*\n"
    if inactive_players:
        inactive_players.sort(key=lambda x: x[2], reverse=True)
        for p_id, p_name, pop in inactive_players[:30]:
            profile_url = f"{SERVER_URL}/profile/{p_id}"
            report_inact += f"- [{p_name}]({profile_url}) — население: {pop} (без изменений)\n"
    else:
        report_inact += "Все игроки проявили активность.\n"
    send_to_telegram(report_inact, THREAD_ID)


def cleanup_old_snapshots():
    if RETENTION_DAYS is None:
        return

    cutoff = datetime.now(timezone.utc).date().toordinal() - RETENTION_DAYS
    deleted = 0

    for path in SNAPSHOT_DIR.glob("**/map_*.sql"):
        match = re.search(r"map_(\d{4}-\d{2}-\d{2})\.sql$", path.name)
        if not match:
            continue
        try:
            file_date = datetime.strptime(match.group(1), "%Y-%m-%d").date()
        except ValueError:
            continue
        if file_date.toordinal() < cutoff:
            path.unlink()
            deleted += 1

    if deleted:
        print(f"Удалено старых снимков: {deleted}")


def main():
    today_string = datetime.now(timezone.utc).date().isoformat()

    print("========================================")
    print("       TRAVIAN DAILY ANALYSIS")
    print("========================================")
    print(f"Дата снимка: {today_string}")

    # Скачиваем и сначала проверяем парсером.
    raw_today = download_map_data()
    v_today, p_today = parse_map_data(raw_today)
    print(f"Проверка нового снимка OK: {len(v_today):,} деревень / {len(p_today):,} игроков")

    # На случай повторного ручного запуска в тот же день:
    # существующий снимок этой даты заменяется свежим.
    previous_path = find_previous_snapshot(today_string)
    current_path = save_snapshot(raw_today, today_string)

    if previous_path is None:
        print("Предыдущий снимок не найден — создана первая точка истории.")
        send_to_telegram(
            "🟢 *Бот Travian запущен в режиме исторических снимков.*\n"
            f"Первый снимок: `{today_string}`.\n"
            "Начиная со следующего снимка будет выполняться сравнительный анализ.",
            THREAD_ID,
        )
        cleanup_old_snapshots()
        return

    print(f"Предыдущий снимок: {previous_path}")
    raw_previous = previous_path.read_text(encoding="utf-8")

    results = compare_snapshots(raw_today, raw_previous)
    send_reports(results)
    cleanup_old_snapshots()

    print(f"Текущий снимок: {current_path}")
    print("=== ГОТОВО ===")


if __name__ == "__main__":
    main()
