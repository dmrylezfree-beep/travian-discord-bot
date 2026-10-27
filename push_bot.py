"""Alliance push ledger. Only Telegram bookkeeping; never sends game resources."""
import html
import json
import os
import re
import sqlite3
import time
import uuid
from pathlib import Path

GROUP_ID = -1002493230303
THREAD_ID = 21472
OWNER_ID = 317595036
PAGE = 8
STATUSES = {'none': 'Не прислали', 'below': 'Меньше нормы', 'normal': 'Норму', 'above': 'Выше нормы'}
ICONS = {'none': '⏳', 'below': '🟡', 'normal': '✅', 'above': '🌟'}
ROOT = Path(__file__).resolve().parent


def esc(value):
    return html.escape(str(value))


def button(text, data):
    return {'text': text, 'callback_data': 'push:' + data}


def keyboard(rows):
    return {'inline_keyboard': rows}


def alliance_key(name):
    return ' '.join(str(name).casefold().replace('е', 'e').split())


def roster_from_snapshot(root=ROOT):
    # Reuse the maintained map SQL parser; only read the public world snapshot.
    import alliance_ops_bot as maps
    paths = sorted((root / 'data/snapshots').glob('**/map_????-??-??.sql'), key=lambda p: p.name)
    if not paths:
        raise ValueError('Нет снимка мира. Список участников пока недоступен.')
    path = paths[-1]
    players = {}
    found = set()
    for raw in maps.rows(path.read_text(encoding='utf-8', errors='replace')):
        fields = maps.split_sql(raw)
        if len(fields) < 11:
            continue
        name = maps.clean(fields[9])
        key = alliance_key(name)
        if key not in (alliance_key('Сокол'), 'fun e'):
            continue
        uid = int(maps.clean(fields[6]))
        if uid <= 0:
            continue
        found.add(key)
        players[str(uid)] = {'id': uid, 'name': maps.clean(fields[7]), 'alliance': name}
    if found != {alliance_key('Сокол'), 'fun e'}:
        raise ValueError('В снимке не найдены оба альянса: Сокол и Fun Е. Создание приостановлено.')
    return path.stem.removeprefix('map_'), sorted(players.values(), key=lambda p: (alliance_key(p['alliance']), p['name'].casefold(), p['id']))


def amount(text):
    value = re.sub(r'[ \u00a0\u202f]', '', str(text))
    if not re.fullmatch(r'[0-9]{1,13}', value) or not 0 < int(value) <= 10**12:
        raise ValueError('Введите целое количество ресурсов от 1 до 1 000 000 000 000, например 15000.')
    return int(value)


class PushBot:
    def __init__(self, path, call, roster=roster_from_snapshot):
        self.call, self.roster = call, roster
        self.db = sqlite3.connect(path)
        self.db.row_factory = sqlite3.Row
        self.db.execute('PRAGMA journal_mode=WAL')
        self.db.executescript('''
        CREATE TABLE IF NOT EXISTS pushes(id INTEGER PRIMARY KEY,submit_key TEXT UNIQUE NOT NULL,recipient INTEGER NOT NULL,recipient_user INTEGER NOT NULL,norm INTEGER NOT NULL,roster TEXT NOT NULL,snapshot TEXT NOT NULL,status TEXT NOT NULL DEFAULT 'active',created REAL NOT NULL);
        CREATE TABLE IF NOT EXISTS sessions(user INTEGER PRIMARY KEY,data TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS payments(push INTEGER NOT NULL,player INTEGER NOT NULL,status TEXT NOT NULL,updated REAL NOT NULL,PRIMARY KEY(push,player));
        CREATE TABLE IF NOT EXISTS audit(id INTEGER PRIMARY KEY,push INTEGER,player INTEGER,actor INTEGER,status TEXT,created REAL);
        CREATE TABLE IF NOT EXISTS progress(id INTEGER PRIMARY KEY CHECK(id=1),next_update INTEGER NOT NULL);
        ''')
        self.db.commit()

    def send(self, text, rows=None, reply=False):
        args = dict(chat_id=GROUP_ID, message_thread_id=THREAD_ID, text=text, parse_mode='HTML', disable_web_page_preview=True)
        if reply:
            args['reply_markup'] = {'force_reply': True, 'selective': True}
        elif rows:
            args['reply_markup'] = keyboard(rows)
        return self.call('sendMessage', **args)

    def state(self, uid, data=None):
        if data is None:
            row = self.db.execute('SELECT data FROM sessions WHERE user=?', (uid,)).fetchone()
            return json.loads(row[0]) if row else {}
        with self.db:
            self.db.execute('INSERT OR REPLACE INTO sessions VALUES(?,?)', (uid, json.dumps(data)))

    def prompt(self, uid, data, text):
        sent = self.send(f'<a href="tg://user?id={uid}">Ваш шаг</a>: ' + text, reply=True)
        data['prompt'] = sent['message_id']
        self.state(uid, data)

    def menu(self, uid):
        rows = [[button('📊 Учёт', 'list:0')]]
        if uid == OWNER_ID:
            rows.insert(0, [button('➕ Создать заявку на пуш', 'new')])
        rows.append([button('📖 Как пользоваться', 'help')])
        self.send('<b>📦 УЧЁТ ПУША</b>\n\nНорма — общее количество ресурсов с одного аккаунта (сумма дерева, глины, железа и кропа). Отправку отмечает получатель пуша.\n\nВыберите «Учёт», затем нужную заявку.', rows)

    def job(self, ident):
        row = self.db.execute('SELECT * FROM pushes WHERE id=?', (ident,)).fetchone()
        if not row:
            return None
        job = dict(row)
        job['roster'] = json.loads(job['roster'])
        return job

    def statuses(self, ident):
        return {str(r['player']): r['status'] for r in self.db.execute('SELECT player,status FROM payments WHERE push=?', (ident,))}

    def donors(self, job):
        return [p for p in job['roster'] if p['id'] != job['recipient']]

    def title(self, job):
        player = next(p for p in job['roster'] if p['id'] == job['recipient'])
        return f'<b>📦 Пуш #{job["id"]} → {esc(player["name"])}</b>\nАльянс: {esc(player["alliance"])}\nНорма с аккаунта: <b>{job["norm"]:,}</b> ресурсов\nПолучатель в Telegram: <a href="tg://user?id={job["recipient_user"]}">открыть профиль</a>\n' + ('🟢 Открыт' if job['status'] == 'active' else '🔒 Завершён')

    def pager(self, page, count, prefix):
        rows = []
        nav = []
        if page:
            nav.append(button('⬅️ Назад', f'{prefix}:{page-1}'))
        if (page + 1) * PAGE < count:
            nav.append(button('Дальше ➡️', f'{prefix}:{page+1}'))
        if nav:
            rows.append(nav)
        return rows

    def list_jobs(self, page=0):
        jobs = list(self.db.execute('SELECT id FROM pushes ORDER BY id DESC'))
        page = max(0, min(page, max(0, (len(jobs)-1)//PAGE)))
        rows = []
        for row in jobs[page*PAGE:(page+1)*PAGE]:
            job = self.job(row['id'])
            name = next(p['name'] for p in job['roster'] if p['id'] == job['recipient'])
            rows.append([button(f'#{job["id"]} · {name} · {"открыт" if job["status"]=="active" else "завершён"}', f'view:{job["id"]}')])
        rows += self.pager(page, len(jobs), 'list')
        rows.append([button('🏠 Меню', 'menu')])
        self.send('<b>📊 Учёт пуша</b>' + ('' if jobs else '\nЗаявок пока нет.'), rows)

    def overview(self, job, uid):
        status = self.statuses(job['id'])
        text = self.title(job) + f'\n\nУчастников к отправке: {len(self.donors(job))}\nСостав за {esc(job["snapshot"])}; получатель не учитывается как отправитель.'
        rows = []
        for key, label in STATUSES.items():
            n = sum(status.get(str(p['id']), 'none') == key for p in self.donors(job))
            text += f'\n{ICONS[key]} {label}: <b>{n}</b>'
            rows.append([button(f'{ICONS[key]} {label} ({n})', f'group:{job["id"]}:{key}:0')])
        if uid == job['recipient_user'] and job['status'] == 'active':
            rows.insert(0, [button('✍️ Отметить отправителя', f'donors:{job["id"]}:0')])
        if uid == OWNER_ID and job['status'] == 'active':
            rows.append([button('🔒 Завершить пуш', f'close:{job["id"]}')])
        rows.append([button('📊 Все заявки', 'list:0')])
        self.send(text, rows)

    def show_players(self, job, uid, page, status=None):
        values = self.statuses(job['id'])
        players = self.donors(job)
        if status is not None:
            players = [p for p in players if values.get(str(p['id']), 'none') == status]
        page = max(0, min(page, max(0, (len(players)-1)//PAGE)))
        text = self.title(job) + '\n\n' + (STATUSES[status] if status is not None else 'Выберите аккаунт, приславший ресурсы:')
        rows = []
        editable = uid == job['recipient_user'] and job['status'] == 'active'
        for player in players[page*PAGE:(page+1)*PAGE]:
            key = values.get(str(player['id']), 'none')
            label = f'{ICONS[key]} {player["name"]} · {player["alliance"]}'
            text += '\n' + esc(label)
            if editable:
                rows.append([button(label[:90], f'pick:{job["id"]}:{player["id"]}')])
        if not players:
            text += '\nСписок пуст.'
        prefix = f'group:{job["id"]}:{status}' if status is not None else f'donors:{job["id"]}'
        rows += self.pager(page, len(players), prefix)
        rows.append([button('⬅️ К учёту', f'view:{job["id"]}')])
        self.send(text, rows)

    def recipient_page(self, state, page):
        players = state['roster']
        page = max(0, min(page, max(0, (len(players)-1)//PAGE)))
        rows = [[button(f'{p["name"]} · {p["alliance"]}'[:90], f'recipient:{state["token"]}:{p["id"]}')] for p in players[page*PAGE:(page+1)*PAGE]]
        rows += self.pager(page, len(players), 'recipients')
        rows.append([button('❌ Отмена', 'cancel')])
        self.send('<b>Кого пушим?</b>\nВыберите аккаунт из Сокола или Fun Е. Одна строка — один игровой аккаунт.', rows)

    def member(self, uid):
        data = self.call('getChatMember', chat_id=GROUP_ID, user_id=uid)
        return data.get('status') in ('member', 'administrator', 'creator') or (data.get('status') == 'restricted' and data.get('is_member'))

    def handle(self, update):
        q = update.get('callback_query') or {}
        message = q.get('message') or update.get('message') or {}
        chat = message.get('chat') or {}
        if chat.get('type') == 'private' and not q:
            if str(message.get('text') or '').split('@')[0].split(' ')[0] in ('/start','/push','/help'):
                self.call('sendMessage', chat_id=chat['id'], text='Бот работает в ветке учёта пуша: https://t.me/c/2493230303/21472')
                return True
        if chat.get('id') != GROUP_ID or message.get('message_thread_id') != THREAD_ID:
            return False
        user = q.get('from') or message.get('from') or {}
        uid = user.get('id')
        if not uid or user.get('is_bot'):
            return False
        if q:
            if not str(q.get('data', '')).startswith('push:'):
                return False
            try:
                self.call('answerCallbackQuery', callback_query_id=q['id'])
            except Exception:
                pass
        text = str(message.get('text') or '').strip()
        command = text.split()[0] if text.startswith('/') else ''
        if '@' in command and command.split('@', 1)[1].casefold() != 'push_travian_bot':
            return False
        command = command.split('@')[0]
        try:
            if q:
                self.action(uid, q['data'][5:])
            elif command == '/recipient' and uid == OWNER_ID:
                state = self.state(uid)
                target = (message.get('reply_to_message') or {}).get('from') or {}
                if state.get('stage') != 'telegram' or not target.get('id') or target.get('is_bot'):
                    raise ValueError('Сначала выберите аккаунт, затем отправьте /recipient ответом на сообщение получателя в этой ветке.')
                self.bind_recipient(uid, state, target['id'])
            elif command in ('/start', '/push', '/help', '/cancel'):
                if command in ('/cancel', '/start'):
                    self.state(uid, {})
                self.menu(uid)
            else:
                state = self.state(uid)
                if uid != OWNER_ID or not state.get('stage') or (message.get('reply_to_message') or {}).get('message_id') != state.get('prompt'):
                    return False
                self.input(uid, state, text, message)
        except ValueError as error:
            self.send('❌ ' + esc(error))
        return True

    def action(self, uid, action):
        parts = action.split(':')
        verb = parts[0]
        sizes={'menu':1,'help':1,'cancel':1,'new':1,'recipients':2,'recipient':3,'list':2,'view':2,'group':4,'donors':3,'pick':3,'set':4,'close':2}
        if len(parts)!=sizes.get(verb,0):
            raise ValueError('Кнопка устарела. Откройте /push.')
        if verb in ('new', 'recipients', 'recipient', 'close') and uid != OWNER_ID:
            raise ValueError('Создавать и завершать пуш может только координатор.')
        if verb == 'menu':
            self.menu(uid)
        elif verb == 'help':
            self.send('<b>📖 Как пользоваться</b>\n1. Координатор выбирает игровой аккаунт получателя, указывает его Telegram и норму с каждого аккаунта.\n2. Получатель открывает «Учёт» → свою заявку → «Отметить отправителя».\n3. Выбирает аккаунт и отмечает: меньше нормы, норму или выше нормы.\n4. Если ошибся, выбирает аккаунт повторно и меняет отметку либо сбрасывает её.\n5. Все участники могут смотреть учёт. «Не прислали» означает, что получатель пока не внёс отметку.\n\nЭто ручной учёт. Бот не проверяет игровые отправки. Состав двух альянсов сохраняется на момент создания; получатель из списка отправителей исключён.', [[button('🏠 Меню', 'menu')]])
        elif verb == 'cancel':
            if uid == OWNER_ID:
                self.state(uid, {})
            self.menu(uid)
        elif verb == 'new':
            snapshot, players = self.roster()
            data = dict(stage='recipient', roster=players, snapshot=snapshot, token=uuid.uuid4().hex)
            self.state(uid, data)
            self.recipient_page(data, 0)
        elif verb == 'recipients':
            state = self.state(uid)
            if state.get('stage') != 'recipient':
                raise ValueError('Список устарел. Откройте создание заявки заново.')
            self.recipient_page(state, int(parts[1]))
        elif verb == 'recipient':
            state = self.state(uid)
            if state.get('stage') != 'recipient' or len(parts) != 3 or parts[1] != state['token']:
                raise ValueError('Список устарел. Откройте создание заявки заново.')
            ident = int(parts[2])
            if not any(p['id'] == ident for p in state['roster']):
                raise ValueError('Аккаунт не найден в составе альянсов.')
            state.update(stage='telegram', recipient=ident)
            self.prompt(uid, state, 'укажите Telegram ID получателя числом. Либо отправьте /recipient ответом на сообщение самого получателя в этой ветке. Права будут выданы только выбранному Telegram-пользователю.')
        elif verb == 'list':
            self.list_jobs(int(parts[1]))
        elif verb in ('view', 'group', 'donors', 'pick', 'set', 'close'):
            job = self.job(int(parts[1]))
            if not job:
                raise ValueError('Заявка не найдена.')
            if verb == 'view':
                self.overview(job, uid)
            elif verb == 'group':
                if parts[2] not in STATUSES:
                    raise ValueError('Категория не найдена.')
                self.show_players(job, uid, int(parts[3]), parts[2])
            elif verb == 'close':
                with self.db:
                    self.db.execute("UPDATE pushes SET status='closed' WHERE id=?", (job['id'],))
                self.overview(self.job(job['id']), uid)
            else:
                if uid != job['recipient_user'] or job['status'] != 'active' or not self.member(uid):
                    raise ValueError('Отметки в открытой заявке может вносить только получатель пуша.')
                if verb == 'donors':
                    self.show_players(job, uid, int(parts[2]))
                    return
                ident = int(parts[2])
                player = next((p for p in self.donors(job) if p['id'] == ident), None)
                if not player:
                    raise ValueError('Этот аккаунт не является отправителем в данной заявке.')
                if verb == 'pick':
                    rows = [[button(label, f'set:{job["id"]}:{ident}:{key}')] for key, label in STATUSES.items() if key != 'none']
                    rows += [[button('↩️ Сбросить отметку', f'set:{job["id"]}:{ident}:none')], [button('⬅️ К отправителям', f'donors:{job["id"]}:0')]]
                    self.send(f'<b>{esc(player["name"])} · {esc(player["alliance"])}</b>\nНорма: {job["norm"]:,} ресурсов.\nСколько прислал этот аккаунт?', rows)
                else:
                    key = parts[3]
                    if key not in STATUSES:
                        raise ValueError('Выберите количество кнопкой.')
                    with self.db:
                        self.db.execute('INSERT OR REPLACE INTO payments VALUES(?,?,?,?)', (job['id'], ident, key, time.time()))
                        self.db.execute('INSERT INTO audit(push,player,actor,status,created) VALUES(?,?,?,?,?)', (job['id'], ident, uid, key, time.time()))
                    self.send(f'{ICONS[key]} {esc(player["name"])}: {STATUSES[key]}. Отметка сохранена.', [[button('✍️ Следующий отправитель', f'donors:{job["id"]}:0')], [button('📊 Учёт', f'view:{job["id"]}')]])
        else:
            raise ValueError('Кнопка устарела. Откройте /push.')

    def bind_recipient(self, uid, state, ident):
        if ident <= 0 or not self.member(ident):
            raise ValueError('Получатель должен быть участником чата. Проверьте Telegram ID.')
        state.update(stage='norm', recipient_user=ident)
        self.prompt(uid, state, 'введите норму ресурсов с каждого аккаунта, например <code>15000</code>. Это сумма всех типов ресурсов. После ввода заявка сразу создаётся.')

    def input(self, uid, state, text, message):
        if state['stage'] == 'telegram':
            if not re.fullmatch(r'[0-9]{1,16}', text):
                raise ValueError('Укажите Telegram ID числом либо отправьте /recipient ответом на сообщение получателя.')
            self.bind_recipient(uid, state, int(text))
        elif state['stage'] == 'norm':
            norm = amount(text)
            if not self.member(state['recipient_user']):
                raise ValueError('Получатель больше не состоит в чате. Создайте заявку заново.')
            with self.db:
                self.db.execute('INSERT OR IGNORE INTO pushes(submit_key,recipient,recipient_user,norm,roster,snapshot,created) VALUES(?,?,?,?,?,?,?)', (state['token'], state['recipient'], state['recipient_user'], norm, json.dumps(state['roster']), state['snapshot'], time.time()))
            job = self.db.execute('SELECT id FROM pushes WHERE submit_key=?', (state['token'],)).fetchone()
            self.state(uid, {})
            self.send(f'✅ Создана заявка на пуш #{job[0]}. <a href="tg://user?id={state["recipient_user"]}">Получатель</a>, вам доступен учёт отправок.', [[button('📊 Открыть учёт', f'view:{job[0]}')]])


def main():
    import requests
    token = os.environ.get('PUSH_TELEGRAM_TOKEN')
    if not token:
        raise RuntimeError('Push token missing')
    proxy = os.environ.get('TELEGRAM_PROXY_URL')
    def api(method, **payload):
        response = requests.post('https://api.telegram.org/bot' + token + '/' + method, json=payload, proxies={'https': proxy} if proxy else None, timeout=40)
        if response.status_code == 409:
            raise RuntimeError('Polling conflict')
        response.raise_for_status()
        data = response.json()
        if not data.get('ok'):
            raise RuntimeError('Telegram request rejected')
        return data['result']
    root = Path(os.environ.get('PUSH_DATA_DIR', '/var/lib/travian-push'))
    root.mkdir(parents=True, exist_ok=True)
    app = PushBot(root / 'ledger.sqlite', api)
    me = api('getMe')
    if me.get('username', '').casefold() != 'push_travian_bot':
        raise RuntimeError('Unexpected bot identity')
    if api('getWebhookInfo').get('url'):
        raise RuntimeError('Webhook already configured')
    print('Push ledger ready.', flush=True)
    while True:
        row = app.db.execute('SELECT next_update FROM progress WHERE id=1').fetchone()
        try:
            for update in api('getUpdates', offset=row[0] if row else None, timeout=25, allowed_updates=['message', 'callback_query']):
                try:
                    app.handle(update)
                except Exception:
                    # Retry safely; never log API URLs or message contents.
                    print('Push update failed; will retry.', flush=True)
                    time.sleep(5)
                    break
                with app.db:
                    app.db.execute('INSERT OR REPLACE INTO progress VALUES(1,?)', (update['update_id'] + 1,))
        except Exception:
            print('Push polling unavailable; retrying.', flush=True)
            time.sleep(5)


if __name__ == '__main__':
    try:
        main()
    except Exception:
        print('Push startup failed; sensitive details suppressed.', flush=True)
        raise SystemExit(1)
