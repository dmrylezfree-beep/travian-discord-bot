import os
import requests

# === НАСТРОЙКИ ===
TELEGRAM_TOKEN = "8990787224:AAFgmGwAMaufksTOmvUFcHND5w05N6vcnuw"
TELEGRAM_CHAT_ID = "-1002493230303"
SERVER_URL = "https://ts7.x1.asia.travian.com"
MAP_SQL_URL = f"{SERVER_URL}/map.sql"

# ПОСТОЯННЫЕ ФАЙЛЫ НА ВКЛАДКЕ CODE
DB_FILE_CURRENT = "current_map.sql"
DB_FILE_YESTERDAY = "yesterday_map.sql"

# ИДЕНТИФИКАТОРЫ ВЕТОК ГРУППЫ ТЕЛЕГРАМ (ПРОПИСАНЫ ЖЕСТКО ДЛЯ ГАРАНТИИ ВИДИМОСТИ)
THREAD_DELETIONS = 75792
THREAD_CONQUERS = 75792
THREAD_POP_DROPS = 75792



def download_map_data():
    """Скачивает актуальный файл map.sql"""
    print(f"Скачивание свежих данных с сервера {SERVER_URL}...")
    response = requests.get(MAP_SQL_URL)
    if response.status_code == 200:
        return response.text
    print(f"Ошибка скачивания данных Travian: статус {response.status_code}")
    return None


def parse_map_data(raw_data):
    """Парсит дамп Травиана построчно без сбоев кодировки"""
    villages = {}
    players = set()
    
    if "VALUES" in raw_data:
        raw_data = raw_data.split("VALUES")[-1]

    lines = raw_data.split("),(")
    for line in lines:
        line = line.replace("(", "").replace(")", "").replace(";", "")
        parts = line.split(",")
        if len(parts) >= 11:
            try:
                v_id = int(parts[0])
                x = parts[1]
                y = parts[2]
                u_id = int(parts[4])
                p_name = parts[5].strip("'")
                v_name = parts[3].strip("'")
                pop = int(parts[8])


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
            except:
                continue
    return villages, players


def send_to_telegram(message, thread_id=None):
    """Отправляет сообщение в Telegram (в общий чат или конкретную тему)"""
    if not message.strip():
        return
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    payload = {
        "chat_id": TELEGRAM_CHAT_ID,
        "text": message,
        "parse_mode": "Markdown",
        "disable_web_page_preview": True
    }
    if thread_id:
        payload["message_thread_id"] = thread_id
        
    try:
        requests.post(url, json=payload)
    except Exception as e:
        print(f"Не удалось связаться с Telegram: {e}")


def main():
    raw_today = download_map_data()
    if not raw_today:
        return

    # ШАГ 1: Всегда сохраняем то, что скачали прямо сейчас, в файл current_map.sql
    with open(DB_FILE_CURRENT, "w", encoding="utf-8") as f:
        f.write(raw_today)

    # Проверяем, существует ли вчерашняя контрольная точка
    has_yesterday = os.path.exists(DB_FILE_YESTERDAY)

    if not has_yesterday:
        print("Вчерашняя база данных (yesterday_map.sql) не найдена. Создаем её из текущих данных...")
        # СНАЧАЛА ЖЕЛЕЗНО СОЗДАЕМ ФАЙЛ БЭКАПА:
        with open(DB_FILE_YESTERDAY, "w", encoding="utf-8") as f:
            f.write(raw_today)

        # ТЕПЕРЬ ШЛЕМ В TELEGRAM (даже если тут упадет, файл уже сохранен):
        send_to_telegram("🟢 **Бот Travian успешно переведен на систему двух баз!** Стартовая точка `yesterday_map.sql` создана на вкладке Code.", THREAD_DELETIONS)
        return


    print("Вчерашняя база найдена! Начинаем сравнительный анализ...")
    with open(DB_FILE_YESTERDAY, "r", encoding="utf-8") as f:
        raw_yesterday = f.read()

    v_today, p_today = parse_map_data(raw_today)
    v_yesterday, p_yesterday = parse_map_data(raw_yesterday)

    uids_today = {p for p in p_today}

    # 1. Удаленные аккаунты
    deleted_players = []
    for p_id, p_name in p_yesterday:
        if (p_id, p_name) not in uids_today:
            yesterday_pop = sum(v["pop"] for v in v_yesterday.values() if v["uid"] == p_id)
            if yesterday_pop >= 100:
                deleted_players.append((p_id, p_name))

    # 2 и 3. Захваты и падение населения
    conquered_villages = []
    dropped_pop_villages = []

    for v_id, data_y in v_yesterday.items():
        if v_id in v_today:
            data_t = v_today[v_id]
            if data_y["uid"] != data_t["uid"] and data_y["uid"] != 0:
                conquered_villages.append((data_y, data_t))
            elif data_t["pop"] < data_y["pop"]:
                diff = data_y["pop"] - data_t["pop"]
                if diff >= 10:
                    dropped_pop_villages.append((data_t, diff))

    # 4. Неактивные игроки
    inactive_players = []
    for p_id, p_name in p_today:
        pop_yesterday = sum(v["pop"] for v in v_yesterday.values() if v["uid"] == p_id)
        pop_today = sum(v["pop"] for v in v_today.values() if v["uid"] == p_id)
        if pop_yesterday == pop_today and pop_yesterday > 0:
            inactive_players.append((p_id, p_name, pop_today))

    # === ОТПРАВКА ОТЧЕТОВ ===
    
    # Отчет 1: Удаления (в ветку №5)
    report_del = "❌ *Удаленные аккаунты (Asia 7):*\n"
    if deleted_players:
        for _, name in deleted_players[:30]:
            report_del += f"- {name}\n"
    else:
        report_del += "Нет изменений за сутки.\n"
    send_to_telegram(report_del, 75792)

    # Отчет 2: Захваты (в ветку №12)
    report_conq = "⚔️ *Захваченные деревни (Asia 7):*\n"
    if conquered_villages:
        for y, t in conquered_villages[:30]:
            report_conq += f"- Деревня `{t['name']}` ({t['x']}|{t['y']}) игрока *{y['player']}* захвачена игроком *{t['player']}*\n"
    else:
        report_conq += "Нет изменений за сутки.\n"
    send_to_telegram(report_conq, 75792)

    # Отчет 3: Потеря населения (в ветку №18)
    report_pop = "📉 *Деревни с потерей населения (Asia 7):*\n"
    if dropped_pop_villages:
        for t, diff in dropped_pop_villages[:30]:
            if diff >= 150:
                report_pop += f"- 🚨🚨🚨 Деревня `{t['name']}` ({t['x']}|{t['y']}) игрока *{t['player']}*: -{diff} (сейчас: {t['pop']}) 🚨🚨🚨\n"
            else:
                report_pop += f"- Деревня `{t['name']}` ({t['x']}|{t['y']}) игрока *{t['player']}*: -{diff} (сейчас: {t['pop']})\n"
    else:
        report_pop += "Нет изменений за сутки.\n"
    send_to_telegram(report_pop, 75792)

    # Отчет 4: Неактивные игроки (в ветку №5)
    report_inact = "💤 *Неактивны 24 часа (Asia 7):*\n"
    if inactive_players:
        inactive_players.sort(key=lambda x: x[2], reverse=True)
        for p_id, p_name, pop in inactive_players[:30]:
            profile_url = f"{SERVER_URL}/profile/{p_id}"
            report_inact += f"- [{p_name}]({profile_url}) — население: {pop} (без изменений)\n"
    else:
        report_inact += "Все игроки проявили активность.\n"
    send_to_telegram(report_inact, 75792)


if __name__ == "__main__":
    main()
