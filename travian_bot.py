import os
import re
import requests

# === НАСТРОЙКИ ===
TELEGRAM_TOKEN = "8990787224:AAFgmGwAMaufksTOmvUFcHND5w05N6vcnuw"
TELEGRAM_CHAT_ID = "-1002493230303"
SERVER_URL = "https://ts7.x1.asia.travian.com"  # Сервер Asia 7
MAP_SQL_URL = f"{SERVER_URL}/map.sql"
DB_FILE_TODAY = "map_today.txt"
DB_FILE_YESTERDAY = "map_yesterday.txt"


def download_map_data():
    """Скачивает актуальный файл map.sql"""
    print(f"Скачивание данных с сервера {SERVER_URL}...")
    response = requests.get(MAP_SQL_URL)
    if response.status_code == 200:
        return response.text
    print(f"Ошибка скачивания данных Travian: статус {response.status_code}")
    return None


def parse_map_data(raw_data):
    """Парсит дамп Травиана"""
    villages = {}
    players = set()
    pattern = re.compile(
        r"\((\d+),(-?\d+),(-?\d+),(\d+),(\d+),'(.*?)',(\d+),'(.*?)',(\d+),'(.*?)',(\d+)\)"
    )

    for match in pattern.finditer(raw_data):
        v_id, x, y, _, _, v_name, u_id, p_name, _, _, pop = match.groups()
        u_id = int(u_id)
        v_id = int(v_id)
        pop = int(pop)

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
    return villages, players


def send_to_telegram(message):
    """Отправляет отчет в Telegram чат с расширенным выводом ошибок в логи"""
    if not message.strip():
        print("Сообщение пустое, отправка отменена.")
        return
    
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    payload = {
        "chat_id": TELEGRAM_CHAT_ID,
        "text": message
    }
    
    try:
        res = requests.post(url, json=payload)
        if res.status_code == 200:
            print("!!! ОТЧЕТ УСПЕШНО ОТПРАВЛЕН В TELEGRAM !!!")
        else:
            print("!!! ОШИБКА ОТПРАВКИ В TELEGRAM !!!")
            print(f"Код статуса ответа: {res.status_code}")
            print(f"Полный ответ от сервера Telegram: {res.text}")
            print("ВНИМАНИЕ: Проверьте, добавлен ли бот в группу администратором и включена ли отправка сообщений!")
    except Exception as e:
        print(f"Не удалось связаться с серверами Telegram: {e}")


def main():
    raw_today = download_map_data()
    if not raw_today:
        return

    has_yesterday = os.path.exists(DB_FILE_YESTERDAY)

    with open(DB_FILE_TODAY, "w", encoding="utf-8") as f:
        f.write(raw_today)

    if not has_yesterday:
        print("Вчерашняя база данных не найдена. Создаем стартовую точку...")
        send_to_telegram(
            "🟢 Бот Travian успешно запущен в Telegram! Стартовая база данных создана. Первый отчет со сравнением придет при следующем запуске."
        )
        return

    print("Вчерашняя база найдена! Начинаем анализ изменений...")
    with open(DB_FILE_YESTERDAY, "r", encoding="utf-8") as f:
        raw_yesterday = f.read()

    v_today, p_today = parse_map_data(raw_today)
    v_yesterday, p_yesterday = parse_map_data(raw_yesterday)

     # Анализ изменений
 uids_today = {p for p in p_today}

 # Ищем удаленные аккаунты с фильтром по вчерашнему населению >= 100
 deleted_players = []
 for p_id, p_name in p_yesterday:
     if (p_id, p_name) not in uids_today:
         # Считаем сумму населения всех вчерашних деревень этого игрока
         yesterday_pop = sum(v["pop"] for v in v_yesterday.values() if v["uid"] == p_id)
         if yesterday_pop >= 100:
             deleted_players.append((p_id, p_name))


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


    # Формируем отчет без Markdown тегов во избежание конфликтов парсинга
    report = "📊 ЕЖЕДНЕВНЫЙ ОТЧЕТ СЕРВЕРА TRAVIAN (Asia 7) 📊\n\n"

    if deleted_players:
        report += "❌ Удаленные аккаунты:\n"
        for _, name in deleted_players[:30]:
            report += f"- {name}\n"
    else:
        report += "❌ Удаленные аккаунты: Нет\n"

    if conquered_villages:
        report += "\n⚔️ Захваченные деревни:\n"
        for y, t in conquered_villages[:30]:
            report += f"- Деревня {t['name']} ({t['x']}|{t['y']}) игрока {y['player']} захвачена игроком {t['player']}\n"
    else:
        report += "\n⚔️ Захваченные деревни: Нет\n"

    if dropped_pop_villages:
        report += "\n📉 Деревни с потерей населения:\n"
        for t, diff in dropped_pop_villages[:30]:
            report += f"- Деревня {t['name']} ({t['x']}|{t['y']}) игрока {t['player']}: -{diff} (сейчас: {t['pop']})\n"
    else:
        report += "\n📉 Деревни с потерей населения: Нет\n"

    send_to_telegram(report)


if __name__ == "__main__":
    main()
