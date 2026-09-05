import os
import re
import requests

# === НАСТРОЙКИ ===
WEBHOOK_URL = "https://discord.com/api/webhooks/1545847132056068238/Vl22SrzP0Waecu2C2o4wl27GZ50MVp54h87_H598q4C-X4nFvGZX7PWkIF2aO4hAadKL"
SERVER_URL = "https://ts7.x1.asia.travian.com/"  # Укажите адрес вашего сервера
MAP_SQL_URL = f"{SERVER_URL}/map.sql"
DB_FILE_TODAY = "map_today.txt"
DB_FILE_YESTERDAY = "map_yesterday.txt"


def download_map_data():
    """Скачивает актуальный файл map.sql"""
    response = requests.get(MAP_SQL_URL)
    if response.status_code == 200:
        return response.text
    print("Ошибка скачивания данных Travian")
    return None


def parse_map_data(raw_data):
    """
    Парсит map.sql в структурированный словарь.
    Формат строки обычно: INSERT INTO `map_sql` VALUES (id, x, y, tid, vid, village, uid, player, kid, alliance, population)
    """
    villages = {}
    players = set()

    # Регулярное выражение для поиска значений внутри скобок (VALUES)
    pattern = re.compile(r"\((\d+),(-?\d+),(-?\d+),(\d+),(\d+),'(.*?)',(\d+),'(.*?)',(\d+),'(.*?)',(\d+)\)")

    for match in pattern.finditer(raw_data):
        v_id, x, y, _, _, v_name, u_id, p_name, _, _, pop = match.groups()

        u_id = int(u_id)
        v_id = int(v_id)
        pop = int(pop)

        if u_id != 0:  # Исключаем натуров / свободные оазисы
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


def save_local_data(raw_data):
    """Ротация файлов: сегодня становится вчерашним"""
    if os.path.exists(DB_FILE_TODAY):
        if os.path.exists(DB_FILE_YESTERDAY):
            os.remove(DB_FILE_YESTERDAY)
        os.rename(DB_FILE_TODAY, DB_FILE_YESTERDAY)

    with open(DB_FILE_TODAY, "w", encoding="utf-8") as f:
        f.write(raw_data)


def load_local_data(filename):
    if os.path.exists(filename):
        with open(filename, "r", encoding="utf-8") as f:
            return f.read()
    return None


def send_to_discord(message):
    """Отправляет чанками сообщение в Discord, так как лимит 2000 символов"""
    if not message.strip():
        return

    payload = {"content": message}
    requests.post(WEBHOOK_URL, json=payload)


def analyze_changes():
    raw_today = download_map_data()
    if not raw_today:
        return

    raw_yesterday = load_local_data(DB_FILE_YESTERDAY)
    save_local_data(raw_today)  # Сохраняем для следующего дня

    if not raw_yesterday:
        print(
            "Нет вчерашних данных для сравнения. База создана, ожидайте следующего запуска."
        )
        return

    v_today, p_today = parse_map_data(raw_today)
    v_yesterday, p_yesterday = parse_map_data(raw_yesterday)

    # 1. Удаленные аккаунты
    uids_today = {p[0] for p in p_today}
    deleted_players = [p for p in p_yesterday if p[0] not in uids_today]

    # 2 и 3. Захваты и падение населения
    conquered_villages = []
    dropped_pop_villages = []

    for v_id, data_y in v_yesterday.items():
        if v_id in v_today:
            data_t = v_today[v_id]

            # Проверка на захват (сменился владелец и старый владелец не 0)
            if data_y["uid"] != data_t["uid"] and data_y["uid"] != 0:
                conquered_villages.append((data_y, data_t))

            # Проверка на падение населения
            elif data_t["pop"] < data_y["pop"]:
                diff = data_y["pop"] - data_t["pop"]
                dropped_pop_villages.append((data_t, diff))

    # Формируем отчет
    report = "📊 **ЕЖЕДНЕВНЫЙ ОТЧЕТ СЕРВЕРА TRAVIAN** 📊\n\n"

    if deleted_players:
        report += "❌ **Удаленные аккаунты:**\n"
        for _, name in deleted_players[:20]:  # Ограничим вывод
            report += f"- {name}\n"
    else:
        report += "❌ **Удаленные аккаунты:** Нет\n"

    if conquered_villages:
        report += "\n⚔️ **Захваченные деревни:**\n"
        for y, t in conquered_villages[:20]:
            report += f"- Деревня `{t['name']}` ({t['x']}|{t['y']}) игрока **{y['player']}** захвачена игроком **{t['player']}**\n"
    else:
        report += "\n⚔️ **Захваченные деревни:** Нет\n"

    if dropped_pop_villages:
        report += "\n📉 **Деревни с потерей населения:**\n"
        for t, diff in dropped_pop_villages[:20]:
            report += f"- `{t['name']}` ({t['x']}|{t['y']}) игрока **{t['player']}**: -{diff} населения (сейчас: {t['pop']})\n"
    else:
        report += "\n📉 **Деревни с потерей населения:** Нет\n"

    # Отправка
    send_to_discord(report)


if __name__ == "__main__":
    analyze_changes()
