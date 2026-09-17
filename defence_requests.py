import html
import os
from datetime import datetime
from pathlib import Path

import defence_bot as bot
from travian_bot import parse_map_data, SERVER_URL

SNAPSHOT_DIR = Path("data/snapshots")
STATE_FILE = bot.DATA_DIR / "state.json"
_snapshot_cache_path = None
_snapshot_cache = None

_original_process_text = bot.process_text
_original_callback_query = bot.callback_query


def load_state():
    return bot.load_json(STATE_FILE, {})


def save_state(state):
    bot.save_json(STATE_FILE, state)
    bot.persist_data()


def request_menu():
    return bot.kb([
        [{"text": "➕ Запросить деф", "callback_data": "request_def"}],
        [{"text": "⚙️ Мои настройки", "callback_data": "settings"}],
    ])


def latest_snapshot():
    global _snapshot_cache_path, _snapshot_cache
    paths = sorted(SNAPSHOT_DIR.glob("*/**/map_*.sql"), key=lambda p: p.name, reverse=True)
    if not paths:
        return None, None
    path = paths[0]
    if _snapshot_cache_path == path and _snapshot_cache is not None:
        return path, _snapshot_cache
    try:
        raw = path.read_text(encoding="utf-8")
        villages, _ = parse_map_data(raw)
    except Exception as exc:
        print(f"Defence snapshot parse error: {exc}", flush=True)
        return path, None
    _snapshot_cache_path = path
    _snapshot_cache = villages
    return path, villages


def find_target(coords):
    parts = coords.split()
    x, y = int(parts[0]), int(parts[1])
    path, villages = latest_snapshot()
    if villages is None:
        return None, path
    for village in villages.values():
        try:
            if int(village.get("x")) == x and int(village.get("y")) == y:
                return village, path
        except (TypeError, ValueError):
            continue
    return None, path


def parse_attack_time(text):
    try:
        return datetime.strptime(text, "%d.%m.%Y %H:%M:%S")
    except ValueError:
        return None


def village_link(x, y):
    url = f"{SERVER_URL}/karte.php?x={x}&y={y}"
    return f'<a href="{html.escape(url, quote=True)}">{x} {y}</a>'


def request_text(req):
    return (
        f"<b>🛡 ЗАПРОС НА ДЕФ #{req['id']}</b>\n\n"
        f"📍 Деревня: {village_link(req['target_x'], req['target_y'])}\n"
        f"👤 Игрок: <b>{html.escape(req['target_player'])}</b>\n"
        f"⚔️ Атака: <b>{req['attack_time_display']}</b>\n"
        f"🛡 Требуется: <b>{req['required_def']}</b> очков дефа\n\n"
        "Деф должен прибыть <b>ДО</b> указанного времени."
    )


def confirm_keyboard():
    return bot.kb([
        [{"text": "✅ Создать заявку", "callback_data": "request_confirm"}],
        [{"text": "❌ Отмена", "callback_data": "request_cancel"}],
    ])


def request_summary(player):
    state = player.get("state", {})
    return (
        "<b>🛡 ЗАПРОС НА ДЕФ</b>\n\n"
        f"📍 Деревня: {village_link(state['target_x'], state['target_y'])}\n"
        f"👤 Игрок: <b>{html.escape(state['target_player'])}</b>\n"
        f"⚔️ Атака: <b>{state['attack_time_display']}</b>\n"
        f"🛡 Требуется: <b>{state['required_def']}</b> очков дефа\n\n"
        "Пехота = 1\n"
        "Конница = 2\n\n"
        "Деф должен прибыть <b>ДО</b> указанного времени.\n\n"
        "Всё верно?"
    )


def next_request_id(requests):
    ids = [int(r.get("id", 0)) for r in requests if str(r.get("id", "")).isdigit()]
    return max(ids, default=0) + 1


def save_request(request):
    requests = bot.load_json(bot.REQUESTS_FILE, [])
    if not isinstance(requests, list):
        requests = []
    requests.append(request)
    bot.save_json(bot.REQUESTS_FILE, requests)
    bot.persist_data()
    return request


def start_request(chat_id, player, data):
    player["state"] = {"type": "request_target_coords"}
    bot.save_players(data)
    bot.send(
        chat_id,
        "<b>🛡 Запросить деф</b>\n\nВведите координаты деревни назначения.\nНапример: <code>45 -62</code>",
        force_reply=True,
    )


def active_requests_text(requests):
    now = datetime.now()
    active = []
    changed = False

    for req in requests:
        if req.get("status") != "active":
            continue
        try:
            attack = datetime.strptime(req["attack_time"], "%Y-%m-%d %H:%M:%S")
        except (KeyError, TypeError, ValueError):
            attack = None
        if attack is not None and attack <= now:
            req["status"] = "expired"
            changed = True
            continue
        active.append(req)

    active.sort(key=lambda r: r.get("attack_time", ""))

    lines = ["<b>🛡 ЦЕНТР ДЕФА</b>", "", "<b>📋 АКТИВНЫЕ ЗАЯВКИ</b>", ""]
    if not active:
        lines.append("Активных заявок нет.")
    else:
        for req in active:
            try:
                attack = datetime.strptime(req["attack_time"], "%Y-%m-%d %H:%M:%S")
                urgent = (attack - now).total_seconds() <= 30 * 60
            except (KeyError, TypeError, ValueError):
                urgent = False
            icon = "🔴" if urgent else "🟡"
            lines.extend([
                f"{icon} <b>#{req['id']}</b>",
                f"📍 {village_link(req['target_x'], req['target_y'])} — <b>{html.escape(req['target_player'])}</b>",
                f"⚔️ Атака: <b>{req['attack_time_display']}</b>",
                f"🛡 Требуется: <b>{req['required_def']}</b> очков",
                "",
            ])

    lines.append("Деф должен прибыть <b>ДО</b> времени атаки.")
    return "\n".join(lines), changed


def refresh_center(chat_id=None, create_if_missing=False):
    state = load_state()
    center_chat_id = state.get("center_chat_id") or chat_id
    center_message_id = state.get("center_message_id")
    if center_chat_id is None:
        return False

    requests = bot.load_json(bot.REQUESTS_FILE, [])
    if not isinstance(requests, list):
        requests = []

    text, changed = active_requests_text(requests)
    if changed:
        bot.save_json(bot.REQUESTS_FILE, requests)
        bot.persist_data()

    if center_message_id:
        try:
            bot.edit(center_chat_id, center_message_id, text, request_menu())
            return True
        except Exception as exc:
            print(f"Centre edit failed, will recreate: {exc}", flush=True)

    if not create_if_missing:
        return False

    message = bot.send(center_chat_id, text, request_menu())
    center_message_id = message.get("message_id") if isinstance(message, dict) else None
    if not center_message_id:
        return False

    state["center_chat_id"] = int(center_chat_id)
    state["center_message_id"] = int(center_message_id)
    save_state(state)
    try:
        bot.tg("pinChatMessage", chat_id=center_chat_id, message_id=center_message_id, disable_notification=True)
    except Exception as exc:
        print(f"Pin centre failed: {exc}", flush=True)
    return True


def process_text(message):
    user = message.get("from", {})
    text = (message.get("text") or "").strip()
    if not text or not bot.in_def_thread(message):
        return

    data, player = bot.get_player(user)
    chat_id = message["chat"]["id"]
    state = player.get("state")

    if text.startswith("/start"):
        return
    if text.startswith("/def"):
        player["state"] = None
        bot.save_players(data)
        refresh_center(chat_id=chat_id, create_if_missing=True)
        return

    if not isinstance(state, dict):
        return _original_process_text(message)

    typ = state.get("type")
    if typ == "request_target_coords":
        coords = bot.parse_coords(text)
        if coords is None:
            bot.send(chat_id, "Неверный формат. Введите координаты через пробел, например: <code>45 -62</code>", force_reply=True)
            return
        village, path = find_target(coords)
        if village is None:
            if path is None:
                bot.send(chat_id, "❌ В репозитории не найден ни одного сохранённого слепка карты.", force_reply=True)
            else:
                bot.send(chat_id, f"❌ Деревня с координатами <code>{coords}</code> не найдена в последнем слепке карты (<code>{path.name}</code>).\n\nПроверьте координаты и попробуйте ещё раз.", force_reply=True)
            return
        player_name = str(village.get("player") or "Неизвестно")
        player["state"] = {
            "type": "request_attack_time",
            "target_coords": coords,
            "target_x": int(village["x"]),
            "target_y": int(village["y"]),
            "target_player": player_name,
        }
        bot.save_players(data)
        bot.send(
            chat_id,
            f"📍 Деревня: {village_link(village['x'], village['y'])}\n👤 Игрок: <b>{html.escape(player_name)}</b>\n\nВведите время атаки по времени сервера Travian.\nФормат: <code>17.09.2026 21:30:45</code>",
            force_reply=True,
        )
        return

    if typ == "request_attack_time":
        attack_time = parse_attack_time(text)
        if attack_time is None:
            bot.send(chat_id, "Неверный формат даты и времени. Используйте: <code>17.09.2026 21:30:45</code>", force_reply=True)
            return
        player["state"]["attack_time"] = attack_time.strftime("%Y-%m-%d %H:%M:%S")
        player["state"]["attack_time_display"] = attack_time.strftime("%d.%m.%Y %H:%M:%S")
        player["state"]["type"] = "request_def_amount"
        bot.save_players(data)
        bot.send(
            chat_id,
            "Введите требуемое количество дефа.\n\n<b>Пехота = 1\nКонница = 2</b>\n\nНапример:\n5000 пехоты = 5000\n2500 конницы = 5000\n1000 пехоты + 2000 конницы = 5000",
            force_reply=True,
        )
        return

    if typ == "request_def_amount":
        required = bot.to_int(text)
        if required is None or required <= 0:
            bot.send(chat_id, "Введите целое положительное число, например <code>5000</code>.", force_reply=True)
            return
        player["state"]["required_def"] = required
        player["state"]["type"] = "request_confirm"
        bot.save_players(data)
        bot.send(chat_id, request_summary(player), confirm_keyboard())
        return

    return _original_process_text(message)


def callback_query(q):
    message = q.get("message", {})
    if message.get("message_thread_id") != bot.THREAD_ID:
        return
    action = q.get("data", "")
    user = q.get("from", {})
    data, player = bot.get_player(user)
    chat_id, msg_id = message["chat"]["id"], message["message_id"]
    bot.answer_callback(q.get("id"))

    if action == "menu":
        refresh_center(chat_id=chat_id, create_if_missing=True)
        return

    if action == "request_def":
        start_request(chat_id, player, data)
        return

    if action == "request_cancel":
        player["state"] = None
        bot.save_players(data)
        bot.edit(chat_id, msg_id, "<b>🛡 ЗАПРОС НА ДЕФ</b>\n\nЗаявка отменена.", request_menu())
        return

    if action == "request_confirm":
        state = player.get("state") or {}
        if state.get("type") != "request_confirm":
            bot.edit(chat_id, msg_id, "❌ Данные заявки устарели. Создайте заявку заново.", request_menu())
            return
        requests = bot.load_json(bot.REQUESTS_FILE, [])
        if not isinstance(requests, list):
            requests = []
        req_id = next_request_id(requests)
        req = {
            "id": req_id,
            "requester_id": int(user["id"]),
            "requester_username": user.get("username", ""),
            "requester_first_name": user.get("first_name", ""),
            "target_x": state["target_x"],
            "target_y": state["target_y"],
            "target_player": state["target_player"],
            "attack_time": state["attack_time"],
            "attack_time_display": state["attack_time_display"],
            "required_def": state["required_def"],
            "status": "active",
            "created_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        }
        save_request(req)
        player["state"] = None
        bot.save_players(data)
        bot.edit(chat_id, msg_id, "<b>✅ Заявка создана.</b>\n\nОна добавлена в закреплённый Центр дефа.", request_menu())
        refresh_center(chat_id=chat_id, create_if_missing=True)
        return

    return _original_callback_query(q)


def handle_update(message=None, callback=None):
    if callback is not None:
        callback_query(callback)
    elif message is not None:
        process_text(message)


def env_message():
    text = os.environ.get("MESSAGE_TEXT", "")
    if not text:
        return None
    return {
        "message_id": int(os.environ.get("MESSAGE_ID", "0") or 0),
        "chat": {"id": int(os.environ.get("CHAT_ID", "0") or 0)},
        "from": {
            "id": int(os.environ.get("USER_ID", "0") or 0),
            "username": os.environ.get("USERNAME", ""),
            "first_name": os.environ.get("FIRST_NAME", ""),
        },
        "text": text,
        "message_thread_id": int(os.environ.get("THREAD_ID", str(bot.THREAD_ID)) or bot.THREAD_ID),
    }


def env_callback():
    data = os.environ.get("CALLBACK_DATA", "")
    if not data:
        return None
    return {
        "id": os.environ.get("CALLBACK_ID", ""),
        "data": data,
        "from": {
            "id": int(os.environ.get("USER_ID", "0") or 0),
            "username": os.environ.get("USERNAME", ""),
            "first_name": os.environ.get("FIRST_NAME", ""),
        },
        "message": {
            "message_id": int(os.environ.get("MESSAGE_ID", "0") or 0),
            "chat": {"id": int(os.environ.get("CHAT_ID", "0") or 0)},
            "message_thread_id": int(os.environ.get("THREAD_ID", str(bot.THREAD_ID)) or bot.THREAD_ID),
        },
    }


bot.main_menu = request_menu
bot.process_text = process_text
bot.callback_query = callback_query

if __name__ == "__main__":
    action = os.environ.get("ACTION", "refresh_center")
    if action == "refresh_center":
        refresh_center(chat_id=os.environ.get("CHAT_ID") or None, create_if_missing=False)
    elif action == "callback":
        callback = env_callback()
        if callback:
            handle_update(callback=callback)
        refresh_center(chat_id=os.environ.get("CHAT_ID") or None, create_if_missing=False)
    elif action == "message":
        message = env_message()
        if message:
            handle_update(message=message)
        refresh_center(chat_id=os.environ.get("CHAT_ID") or None, create_if_missing=False)
