"""Telegram scout calculator for private chats and one alliance topic; no game/account access required."""
import json
import html
import os
import re
import sqlite3
import time
from datetime import datetime, timedelta
from decimal import Decimal, ROUND_HALF_UP
from pathlib import Path

GROUP_ID = -1002493230303
THREAD_ID = 5


def accepted(message):
    chat = message.get("chat") or {}
    return chat.get("type") == "private" or (chat.get("id") == GROUP_ID and message.get("message_thread_id") == THREAD_ID)


def accepts_input(message, state):
    if not accepted(message):
        return False
    if (message.get("chat") or {}).get("type") == "private":
        return True
    text = message.get("text") or ""
    if text.split("@",1)[0].split(" ",1)[0] in ("/start", "/crop", "/help", "/cancel"):
        command = text.split()[0]
        return "@" not in command or command.split("@",1)[1].lower() == "scout_travian_bot"
    return bool(state.get("stage") not in (None,"kind") and state.get("prompt_message_id")
                and (message.get("reply_to_message") or {}).get("message_id") == state["prompt_message_id"])


MENU = {"inline_keyboard": [[{"text": "🌾 Рассчитать расход кропа", "callback_data": "crop:start"}], [{"text": "📖 Как это работает", "callback_data": "help"}]]}
CANCEL = {"inline_keyboard": [[{"text": "❌ Отменить", "callback_data": "cancel"}]]}
KINDS = {"inline_keyboard": [[{"text": "🏘 Деревня", "callback_data": "crop:village"}, {"text": "🌴 Оазис игрока (×10)", "callback_data": "crop:oasis"}], [{"text": "❌ Отменить", "callback_data": "cancel"}]]}
HELP = ("📖 Расчёт по двум сканам\n\nВыберите деревню или оазис игрока, затем введите время и кроп первого и второго скана. "
        "Для оазиса бот умножает показанные ресурсы на 10. Для деревни множитель — 1.\n\n"
        "Формула: (кроп₂ − кроп₁) × множитель × 3600 ÷ секунды между сканами.\n\n"
        "Плюс означает накопление кропа, минус — уменьшение запаса. Это чистый баланс с учётом производства, а не отдельное содержание армии. "
        "Поступления, вывоз ресурсов и переполнение склада могут повлиять на результат.\n\n"
        "Время: ЧЧ:ММ:СС, например 22:02:50. При переходе через полночь второй скан считается сканом следующего дня. "
        "Для интервала в сутки и больше укажите в обоих сканах дату: ДД.ММ.ГГГГ ЧЧ:ММ:СС. Все значения вводите в одном часовом поясе.")


def parse_scan_time(value):
    value = str(value).strip()
    try:
        if re.fullmatch(r"\d{2}:\d{2}:\d{2}", value):
            return datetime.strptime(value, "%H:%M:%S"), False
        if re.fullmatch(r"\d{2}\.\d{2}\.\d{4} \d{2}:\d{2}:\d{2}", value):
            return datetime.strptime(value, "%d.%m.%Y %H:%M:%S"), True
    except ValueError:
        pass
    raise ValueError("Введите корректное время ЧЧ:ММ:СС, например 22:02:50, или дату и время: 21.10.2026 22:02:50.")


def parse_crop(value):
    value = re.sub(r"[ \u00a0\u202f]", "", str(value).strip())
    if not re.fullmatch(r"[0-9]{1,13}", value):
        raise ValueError("Введите целое количество кропа от 0 до 1 000 000 000 000, без знака и дробной части.")
    amount = int(value)
    if amount > 10**12:
        raise ValueError("Слишком большое количество кропа. Максимум — 1 000 000 000 000.")
    return amount


def calculate(kind, first_time, first_crop, second_time, second_crop):
    if kind not in ("village", "oasis"):
        raise ValueError("Выберите деревню или оазис.")
    first, first_dated = parse_scan_time(first_time)
    second, second_dated = parse_scan_time(second_time)
    if first_dated != second_dated:
        raise ValueError("Используйте одинаковый формат обоих сканов: оба с датой или оба без даты.")
    if not first_dated and second < first:
        second += timedelta(days=1)
    seconds = int((second - first).total_seconds())
    if seconds <= 0:
        raise ValueError("Второй скан должен быть позже первого. При одинаковом времени укажите даты или исправьте время.")
    crop1, crop2 = parse_crop(first_crop), parse_crop(second_crop)
    multiplier = 10 if kind == "oasis" else 1
    change = (crop2 - crop1) * multiplier
    return dict(seconds=seconds, multiplier=multiplier, change=change,
                rate=Decimal(change) * 3600 / Decimal(seconds),
                first_crop=crop1, second_crop=crop2, midnight=not first_dated and second.day != first.day)


def number(value, signed=False):
    n = Decimal(value).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    text = f"{abs(n):,.2f}".replace(",", " ").rstrip("0").rstrip(".").replace(".", ",")
    return ("−" if n < 0 else "+" if signed and n > 0 else "") + text


def result_text(state):
    r = calculate(state['kind'], state['time1'], state['crop1'], state['time2'], state['crop2'])
    trend = "📈 Запас кропа растёт." if r['change'] > 0 else "📉 Запас кропа уменьшается." if r['change'] < 0 else "➖ Запас не изменился."
    text = ("🌾 Результат расчёта\n\n" + ("🌴 Оазис игрока: показанные ресурсы ×10" if state['kind'] == 'oasis' else "🏘 Деревня: ресурсы ×1") +
            f"\nПервый скан: {state['time1']} — {number(r['first_crop'])}" +
            f"\nВторой скан: {state['time2']} — {number(r['second_crop'])}" +
            f"\nИнтервал: {r['seconds']} сек." + (" (через полночь)" if r['midnight'] else "") +
            f"\nИзменение реального запаса: {number(r['change'], signed=True)}" +
            f"\n\nБаланс кропа: {number(r['rate'], signed=True)} в час\n{trend}" +
            "\n\nЭто изменение запаса с учётом производства. Бот не определяет отдельно расход армии.")
    return text


def respond(state, text=None, action=None):
    """Pure dialogue: returns new state, reply, keyboard; invalid input retains stage."""
    if text in ('/start', '/cancel') or action == 'cancel':
        return {}, "🌾 Scout Travian\n\nРассчитаю изменение запаса кропа за час по двум сканам.", MENU
    if text == '/help' or action == 'help':
        return {}, HELP, MENU
    if text == '/crop' or action == 'crop:start':
        return {'stage': 'kind'}, "Что вы сканировали?", KINDS
    if action in ('crop:village', 'crop:oasis'):
        if state.get('stage') != 'kind':
            return state, "Этот выбор устарел. Начните новый расчёт кнопкой в меню.", MENU
        return {'stage': 'time1', 'kind': action.split(':')[1]}, "Введите время первого скана: ЧЧ:ММ:СС, например 22:02:50.\nМожно с датой: 21.10.2026 22:02:50.", CANCEL
    if action:
        return state, "Начните новый расчёт в меню.", MENU
    stage = state.get('stage')
    if not stage or stage == 'kind':
        return state, "Выберите тип скана кнопкой ниже." if stage else "Нажмите «Рассчитать расход кропа».", KINDS if stage else MENU
    value = str(text or '').strip()
    updated = dict(state)
    try:
        if stage in ('time1', 'time2'):
            parse_scan_time(value)
        else:
            value = parse_crop(value)
        updated[stage] = value
        if stage == 'time2':
            calculate(updated['kind'], updated['time1'], updated['crop1'], value, updated['crop1'])
        if stage == 'crop2':
            return {}, result_text(updated), MENU
    except ValueError as error:
        message = str(error) if not str(error).startswith(('time data', 'unconverted data')) else "Некорректное время. Используйте ЧЧ:ММ:СС или ДД.ММ.ГГГГ ЧЧ:ММ:СС."
        return state, "❌ " + message, CANCEL
    stages = {'time1': ('crop1', 'Сколько кропа показано в первом скане? Введите число, например 2749.'),
              'crop1': ('time2', 'Введите время второго скана в том же формате, что и первого.'),
              'time2': ('crop2', 'Сколько кропа показано во втором скане? Введите число, например 2767.')}
    updated['stage'], prompt = stages[stage]
    return updated, prompt, CANCEL


class Store:
    def __init__(self, path):
        self.db = sqlite3.connect(path)
        self.db.execute('CREATE TABLE IF NOT EXISTS sessions(chat INTEGER,user INTEGER,state TEXT,PRIMARY KEY(chat,user))')
        self.db.execute('CREATE TABLE IF NOT EXISTS progress(id INTEGER PRIMARY KEY CHECK(id=1),offset INTEGER)')
        self.db.commit()
    def load(self, chat, user):
        row = self.db.execute('SELECT state FROM sessions WHERE chat=? AND user=?', (chat, user)).fetchone()
        return json.loads(row[0]) if row else {}
    def save(self, chat, user, state, offset=None):
        self.db.execute('INSERT OR REPLACE INTO sessions VALUES(?,?,?)', (chat,user,json.dumps(state)))
        if offset is not None:
            self.db.execute('INSERT OR REPLACE INTO progress VALUES(1,?)', (offset,))
        self.db.commit()
    def offset(self):
        row = self.db.execute('SELECT offset FROM progress WHERE id=1').fetchone()
        return row[0] if row else None
    def acknowledge(self, value):
        self.db.execute('INSERT OR REPLACE INTO progress VALUES(1,?)', (value,));self.db.commit()


def main():
    import requests
    token = os.environ['SCOUT_TELEGRAM_TOKEN']
    api = 'https://api.telegram.org/bot' + token + '/'
    proxy = os.environ.get('TELEGRAM_PROXY_URL')
    proxies = {'https': proxy} if proxy else None
    session = requests.Session()
    def call(method, **data):
        response = session.post(api + method, json=data, proxies=proxies, timeout=40)
        response.raise_for_status()
        body = response.json()
        if not body.get('ok'):raise RuntimeError('Telegram operation failed')
        return body.get('result')
    directory = Path(os.environ.get('SCOUT_DATA_DIR','/var/lib/travian-scout'))
    directory.mkdir(parents=True,exist_ok=True)
    os.umask(0o077)
    store = Store(directory / 'state.sqlite')
    me = call('getMe')
    if str(me.get('username','')).lower() != 'scout_travian_bot':raise RuntimeError('Unexpected bot identity')
    if call('getWebhookInfo').get('url'):raise RuntimeError('Webhook configured; polling refused')
    print('Scout calculator ready.',flush=True)
    while True:
        try:
            updates = call('getUpdates', offset=store.offset(), timeout=25, allowed_updates=['message','callback_query']) or []
        except Exception:
            print('Telegram polling unavailable; retrying.',flush=True);time.sleep(3);continue
        for update in updates:
            try:
                q = update.get('callback_query') or {}
                message = update.get('message') or q.get('message') or {}
                chat = message.get('chat') or {}
                user = (q.get('from') if q else message.get('from')) or {}
                if q:
                    try:call('answerCallbackQuery',callback_query_id=q['id'])
                    except Exception:pass
                if accepted(message) and user.get('id') and not user.get('is_bot'):
                    text = message.get('text') if not q else None
                    if text and text.startswith('/'):
                        text = text.split()[0].split('@')[0]
                    previous = store.load(chat['id'],user['id'])
                    if q or (text and accepts_input(message,previous)):
                        state, reply, keyboard = respond(previous,text, q.get('data'))
                        data = dict(chat_id=chat['id'],text=reply,reply_markup=keyboard)
                        if chat.get('type') != 'private':
                            data['message_thread_id'] = THREAD_ID
                            data['parse_mode'] = 'HTML'
                            name = html.escape(str(user.get('first_name') or 'Игрок'))
                            data['text'] = f'<a href="tg://user?id={int(user["id"])}">{name}</a>\n' + html.escape(reply)
                            if state.get('stage') not in (None,'kind'):
                                data['reply_markup'] = {'force_reply': True, 'selective': True}
                                data['text'] += '\n\nОтветьте на это сообщение. Отмена: /cancel'
                        sent = call('sendMessage',**data)
                        if state.get('stage'):
                            state['prompt_message_id'] = sent['message_id']
                        store.save(chat['id'],user['id'],state,update['update_id']+1)
                store.acknowledge(update['update_id']+1)
            except Exception:
                # Do not log request URLs, tokens, scan contents or personal IDs.
                print('Scout update failed; waiting for retry.',flush=True)
                time.sleep(2)
                break


if __name__ == '__main__':
    try:main()
    except KeyboardInterrupt:pass
    except Exception:
        print('Scout startup failed; sensitive details suppressed.',flush=True)
        raise SystemExit(1)
