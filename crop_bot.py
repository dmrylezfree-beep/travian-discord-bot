import html
import json
import math
import os
import re
import subprocess
from pathlib import Path

import requests

TELEGRAM_TOKEN = os.environ.get("CROP_TELEGRAM_TOKEN") or os.environ.get("TELEGRAM_TOKEN")
TELEGRAM_THREAD_ID = 20
SERVER_URL = os.environ.get("TRAVIAN_SERVER_URL", "https://ts8.x1.asia.travian.com").rstrip("/")
MAP_SIZE = 401
PAGE_SIZE = 5
DATA_DIR = Path("data/crop_fields")
CROPS_FILE = DATA_DIR / "crop_fields.json"
RESERVATIONS_FILE = DATA_DIR / "reservations.json"

SESSIONS = {}


def ensure_data():
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    if not RESERVATIONS_FILE.exists():
        RESERVATIONS_FILE.write_text("[]\n", encoding="utf-8")


def telegram(method, **kwargs):
    if not TELEGRAM_TOKEN:
        raise RuntimeError("Не задан CROP_TELEGRAM_TOKEN/TELEGRAM_TOKEN")
    r = requests.post(f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/{method}", json=kwargs, timeout=40)
    r.raise_for_status()
    data = r.json()
    if not data.get("ok"):
        raise RuntimeError(str(data))
    return data.get("result")


def send(chat_id, text, thread_id=None, keyboard=None, force_reply=False):
    payload = dict(chat_id=chat_id, text=text, parse_mode="HTML", disable_web_page_preview=True)
    if thread_id is not None:
        payload["message_thread_id"] = thread_id
    if keyboard is not None:
        payload["reply_markup"] = keyboard
    elif force_reply:
        payload["reply_markup"] = {"force_reply": True}
    return telegram("sendMessage", **payload)


def answer_callback(callback_id, text=None):
    try:
        telegram("answerCallbackQuery", callback_query_id=callback_id, text=text or "")
    except Exception as exc:
        print("answerCallbackQuery:", exc, flush=True)


def main_keyboard():
    return {"inline_keyboard": [
        [{"text": "🔎 Поиск кропок", "callback_data": "crop:search"}],
        [{"text": "✅ Проверить доступность", "callback_data": "crop:check"}],
        [{"text": "📌 Забронировать кропку", "callback_data": "crop:reserve"}],
        [{"text": "📋 Моя бронь", "callback_data": "crop:mine"}],
    ]}


def load_crops():
    ensure_data()
    if not CROPS_FILE.exists():
        return {"crop_fields": [], "test_data": False}
    return json.loads(CROPS_FILE.read_text(encoding="utf-8"))


def load_reservations():
    ensure_data()
    try:
        return json.loads(RESERVATIONS_FILE.read_text(encoding="utf-8"))
    except Exception:
        return []


def save_reservations(rows):
    RESERVATIONS_FILE.write_text(json.dumps(rows, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    try:
        subprocess.run(["git", "config", "user.name", "github-actions[bot]"], check=False)
        subprocess.run(["git", "config", "user.email", "41898282+github-actions[bot]@users.noreply.github.com"], check=False)
        subprocess.run(["git", "add", str(RESERVATIONS_FILE)], check=True)
        diff = subprocess.run(["git", "diff", "--cached", "--quiet"])
        if diff.returncode != 0:
            subprocess.run(["git", "commit", "-m", "Update crop reservations"], check=True)
            subprocess.run(["git", "pull", "--rebase", "origin", "main"], check=True)
            subprocess.run(["git", "push", "origin", "HEAD:main"], check=True)
    except Exception as exc:
        print("Git save failed:", repr(exc), flush=True)


def distance(x1, y1, x2, y2):
    dx = abs(int(x2)-int(x1)); dy = abs(int(y2)-int(y1))
    dx = min(dx, MAP_SIZE-dx); dy = min(dy, MAP_SIZE-dy)
    return math.sqrt(dx*dx + dy*dy)


def parse_coords(text):
    m = re.fullmatch(r"\s*(-?\d{1,3})\s+(?:\|\s*)?(-?\d{1,3})\s*", text or "")
    if not m:
        return None
    x, y = map(int, m.groups())
    if not (-200 <= x <= 200 and -200 <= y <= 200):
        return None
    return x, y


def latest_snapshot_occupied():
    files = sorted(Path("data/snapshots").glob("**/map_*.sql"))
    if not files:
        return set()
    text = files[-1].read_text(encoding="utf-8", errors="ignore")
    occupied = set()
    for line in text.splitlines():
        if not line.startswith("INSERT INTO"):
            continue
        m = re.search(r"VALUES\s*\((.*)\)\s*;?\s*$", line)
        if not m:
            continue
        raw = m.group(1)
        parts = []
        cur = ""; quoted = False; esc = False
        for ch in raw:
            if esc: cur += ch; esc = False
            elif ch == "\\": cur += ch; esc = True
            elif ch == "'": cur += ch; quoted = not quoted
            elif ch == "," and not quoted: parts.append(cur.strip()); cur = ""
            else: cur += ch
        parts.append(cur.strip())
        if len(parts) >= 3:
            try: occupied.add((int(parts[1].strip("'")), int(parts[2].strip("'"))))
            except ValueError: pass
    return occupied


def shared_oases(candidate, chosen):
    a = {(o["x"], o["y"]) for o in candidate.get("oases", [])}
    b = {(o["x"], o["y"]) for o in chosen.get("oases", [])}
    return sorted(a & b)


def search_results(origin, crop_fields, bonus):
    data = load_crops()
    occupied = latest_snapshot_occupied()
    reservations = {(r["x"], r["y"]) for r in load_reservations()}
    rows = []
    for c in data.get("crop_fields", []):
        if int(c.get("crop_fields", 0)) != crop_fields: continue
        if int(c.get("crop_bonus", 0)) < bonus: continue
        xy = (int(c["x"]), int(c["y"]))
        if xy in occupied: continue
        row = dict(c)
        row["distance"] = distance(origin[0], origin[1], xy[0], xy[1])
        row["reserved"] = xy in reservations
        rows.append(row)
    rows.sort(key=lambda c: (c["distance"], -int(c.get("crop_bonus",0))))
    return rows


def format_results(rows, page):
    start = page * PAGE_SIZE
    part = rows[start:start+PAGE_SIZE]
    if not part:
        return "Подходящих свободных кропок не найдено."
    lines = ["<b>🌾 Найденные кропки</b>", ""]
    for i, c in enumerate(part, start+1):
        status = " 📌 бронь" if c.get("reserved") else ""
        link = f'{SERVER_URL}/karte.php?x={c["x"]}&y={c["y"]}'
        lines.append(f'{i}. <a href="{html.escape(link)}"><b>{c["x"]} {c["y"]}</b></a> — {c["crop_fields"]}c, +{c.get("crop_bonus",0)}% 🌾 — {c["distance"]:.2f}{status}')
    return "\n".join(lines)


def show_menu(chat_id, thread_id):
    send(chat_id, "<b>🌾 Бот кропок</b>\n\nПоиск свободных 9c/15c, бонусов оазисов и бронирование.", thread_id, main_keyboard())


def process_message(msg):
    chat = msg.get("chat") or {}
    chat_id = chat.get("id"); user = msg.get("from") or {}; uid = user.get("id")
    thread = msg.get("message_thread_id")
    if chat.get("type") != "private" and thread != TELEGRAM_THREAD_ID:
        return
    text = (msg.get("text") or "").strip()
    if text.startswith("/start"):
        SESSIONS.pop(uid, None); show_menu(chat_id, thread); return
    state = SESSIONS.get(uid)
    if not state: return
    if state["step"] == "origin":
        coords = parse_coords(text)
        if not coords:
            send(chat_id, "Введите координаты через пробел, например: <code>55 46</code>", thread, force_reply=True); return
        state["origin"] = coords; state["step"] = "type"
        send(chat_id, "Какую кропку ищем?", thread, {"inline_keyboard":[[{"text":"15c","callback_data":"crop:type:15"},{"text":"9c","callback_data":"crop:type:9"}]]})
    elif state["step"] == "check_coords":
        coords = parse_coords(text)
        if not coords:
            send(chat_id, "Введите координаты через пробел, например: <code>196 195</code>", thread, force_reply=True); return
        check_availability(chat_id, thread, user, *coords)
    elif state["step"] == "reserve_coords":
        coords = parse_coords(text)
        if not coords:
            send(chat_id, "Введите координаты через пробел, например: <code>196 195</code>", thread, force_reply=True); return
        reserve(chat_id, thread, user, *coords)


def check_availability(chat_id, thread, user, x, y):
    crop = next((c for c in load_crops().get("crop_fields", []) if int(c["x"]) == x and int(c["y"]) == y), None)
    if not crop:
        send(chat_id, f"❌ <b>{x} {y}</b> — этой кропки нет в базе.", thread, main_keyboard())
    elif (x, y) in latest_snapshot_occupied():
        send(chat_id, f"❌ <b>{x} {y}</b> — кропка уже занята на последнем снимке карты.", thread, main_keyboard())
    elif any(int(r["x"]) == x and int(r["y"]) == y for r in load_reservations()):
        send(chat_id, f"📌 <b>{x} {y}</b> — кропка уже забронирована.", thread, main_keyboard())
    else:
        send(chat_id, f'✅ <b>{x} {y}</b> — кропка свободна и доступна для бронирования.\nТип: <b>{crop.get("crop_fields", "?")}c</b>, бонус: <b>+{crop.get("crop_bonus", 0)}%</b> 🌾', thread, main_keyboard())
    SESSIONS.pop(user.get("id"), None)


def reserve(chat_id, thread, user, x, y):
    rows = load_reservations()
    uid = user.get("id")
    mine = next((r for r in rows if r.get("user_id") == uid), None)
    if mine:
        send(chat_id, f'У вас уже есть бронь: <b>{mine["x"]} {mine["y"]}</b>. Сначала отмените её.', thread); return
    crop = next((c for c in load_crops().get("crop_fields", []) if int(c["x"])==x and int(c["y"])==y), None)
    if not crop:
        send(chat_id, "Этой кропки нет в базе.", thread); return
    if (x,y) in latest_snapshot_occupied():
        send(chat_id, "Эта кропка уже занята на последнем снимке карты.", thread); return
    if any(r["x"]==x and r["y"]==y for r in rows):
        send(chat_id, "Эта кропка уже забронирована другим игроком.", thread); return
    rows.append({"user_id":uid,"username":user.get("username") or "","name":user.get("first_name") or "","x":x,"y":y})
    save_reservations(rows)
    SESSIONS.pop(uid, None)
    send(chat_id, f'📌 Кропка <b>{x} {y}</b> забронирована за вами.', thread, main_keyboard())


def show_mine(chat_id, thread, user):
    uid = user.get("id")
    r = next((x for x in load_reservations() if x.get("user_id")==uid), None)
    if not r:
        send(chat_id, "У вас нет забронированной кропки.", thread, main_keyboard()); return
    send(chat_id, f'📌 Ваша бронь: <b>{r["x"]} {r["y"]}</b>', thread,
         {"inline_keyboard":[[{"text":"❌ Отменить бронь","callback_data":"crop:cancel"}],[{"text":"⬅️ Меню","callback_data":"crop:menu"}]]})


def process_callback(q):
    answer_callback(q.get("id"))
    msg=q.get("message") or {}; chat=msg.get("chat") or {}; chat_id=chat.get("id")
    thread=msg.get("message_thread_id"); user=q.get("from") or {}; uid=user.get("id"); data=q.get("data") or ""
    if chat.get("type") != "private" and thread != TELEGRAM_THREAD_ID: return
    if data=="crop:menu": SESSIONS.pop(uid,None); show_menu(chat_id,thread)
    elif data=="crop:search":
        SESSIONS[uid]={"step":"origin"}
        send(chat_id,"Введите координаты вашей деревни через пробел.\nНапример: <code>55 46</code>",thread,force_reply=True)
    elif data=="crop:check":
        SESSIONS[uid]={"step":"check_coords"}
        send(chat_id,"Введите координаты кропки, доступность которой хотите проверить.\nНапример: <code>196 195</code>",thread,force_reply=True)
    elif data=="crop:reserve":
        SESSIONS[uid]={"step":"reserve_coords"}
        send(chat_id,"⚠️ <b>Бронируйте кропку только тогда, когда до готовности очков культуры и поселенцев осталось не более 2 часов.</b>\n\nВведите координаты кропки для бронирования через пробел.\nНапример: <code>196 195</code>",thread,force_reply=True)
    elif data=="crop:mine": show_mine(chat_id,thread,user)
    elif data=="crop:cancel":
        rows = load_reservations()
        mine = next((r for r in rows if r.get("user_id") == uid), None)
        if not mine:
            answer_callback(q.get("id"), "У вас нет активной брони.")
            return
        rows = [r for r in rows if r.get("user_id") != uid]
        save_reservations(rows)
        send(chat_id, "Бронь отменена.", thread, main_keyboard())
    elif data.startswith("crop:type:"):
        state=SESSIONS.setdefault(uid,{})
        state["crop_fields"]=int(data.rsplit(":",1)[1]); state["step"]="bonus"
        buttons=[[{"text":f"{b}%+","callback_data":f"crop:bonus:{b}"} for b in (0,50,100,150)]]
        send(chat_id,"Минимальный бонус зерна от трёх лучших оазисов:",thread,{"inline_keyboard":buttons})
    elif data.startswith("crop:bonus:"):
        state=SESSIONS.get(uid)
        if not state or "origin" not in state or "crop_fields" not in state: show_menu(chat_id,thread); return
        bonus=int(data.rsplit(":",1)[1])
        if state["crop_fields"] == 15 and bonus == 150:
            SESSIONS.pop(uid, None)
            send(chat_id, "Для поиска кропок 15с 150% установите национальный мессенджер MAX.", thread, main_keyboard())
            return
        rows=search_results(state["origin"],state["crop_fields"],bonus)
        state.update({"bonus":bonus,"rows":rows,"page":0})
        kb=[]
        if len(rows)>PAGE_SIZE: kb.append([{"text":"Показать ещё ➡️","callback_data":"crop:more"}])
        kb.append([{"text":"⬅️ Меню","callback_data":"crop:menu"}])
        send(chat_id,format_results(rows,0),thread,{"inline_keyboard":kb})
    elif data=="crop:more":
        state=SESSIONS.get(uid) or {}; rows=state.get("rows",[]); page=state.get("page",0)+1; state["page"]=page
        kb=[]
        if (page+1)*PAGE_SIZE < len(rows): kb.append([{"text":"Показать ещё ➡️","callback_data":"crop:more"}])
        kb.append([{"text":"⬅️ Меню","callback_data":"crop:menu"}])
        send(chat_id,format_results(rows,page),thread,{"inline_keyboard":kb})


def process_update(update):
    if update.get("callback_query"): process_callback(update["callback_query"])
    elif update.get("message"): process_message(update["message"])
