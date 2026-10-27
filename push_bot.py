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


def roster_from_snapshot(root=ROOT, snapshot=None):
    # Reuse the maintained map SQL parser; only read the public world snapshot.
    import alliance_ops_bot as maps
    paths = sorted((root / 'data/snapshots').glob('**/map_????-??-??.sql'), key=lambda p: p.name)
    if snapshot:
        paths=[p for p in paths if p.stem=='map_'+snapshot]
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
        player = players.setdefault(str(uid), {'id': uid, 'name': maps.clean(fields[7]), 'alliance': name, 'villages': [], 'population': 0})
        player['population'] += int(maps.clean(fields[10]))
        player['villages'].append({'x': int(maps.clean(fields[1])), 'y': int(maps.clean(fields[2])), 'name': maps.clean(fields[5])})
    if found != {alliance_key('Сокол'), 'fun e'}:
        raise ValueError('В снимке не найдены оба альянса: Сокол и Fun Е. Создание приостановлено.')
    return path.stem.removeprefix('map_'), sorted(players.values(), key=player_order)


def player_order(player):
    return (0 if alliance_key(player['alliance'])==alliance_key('Сокол') else 1, -int(player.get('population',0)), player['name'].casefold(), player['id'])

class TelegramError(RuntimeError):
    def __init__(self, code, description):
        super().__init__('Telegram request rejected')
        self.code,self.description=code,description


def coordinates(text):
    value = re.sub(r'[\u202a-\u202e\u2066-\u2069]', '', str(text)).strip().replace('−', '-')
    match = re.fullmatch(r'(-?\d{1,3})\s+(-?\d{1,3})', value)
    if not match or any(abs(int(v)) > 200 for v in match.groups()):
        raise ValueError('Введите координаты через пробел в формате X Y, например 22 63. Допустимый диапазон: от −200 до 200.')
    return tuple(map(int, match.groups()))


def amount(text):
    value = re.sub(r'[ \u00a0\u202f]', '', str(text))
    if not re.fullmatch(r'[0-9]{1,13}', value) or not 0 < int(value) <= 10**12:
        raise ValueError('Введите целое количество ресурсов от 1 до 1 000 000 000 000, например 15000.')
    return int(value)


class PushBot:
    def __init__(self, path, call, roster=roster_from_snapshot):
        self.call, self.roster = call, roster
        self.panel_id=None
        self.population_cache={}
        self.last_menu_check=0
        self.db = sqlite3.connect(path)
        self.db.row_factory = sqlite3.Row
        self.db.execute('PRAGMA journal_mode=WAL')
        self.db.executescript('''
        CREATE TABLE IF NOT EXISTS pushes(id INTEGER PRIMARY KEY,submit_key TEXT UNIQUE NOT NULL,recipient INTEGER NOT NULL,recipient_user INTEGER NOT NULL,norm INTEGER NOT NULL,roster TEXT NOT NULL,snapshot TEXT NOT NULL,status TEXT NOT NULL DEFAULT 'active',created REAL NOT NULL);
        CREATE TABLE IF NOT EXISTS sessions(user INTEGER PRIMARY KEY,data TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS payments(push INTEGER NOT NULL,player INTEGER NOT NULL,status TEXT NOT NULL,updated REAL NOT NULL,PRIMARY KEY(push,player));
        CREATE TABLE IF NOT EXISTS audit(id INTEGER PRIMARY KEY,push INTEGER,player INTEGER,actor INTEGER,status TEXT,created REAL);
        CREATE TABLE IF NOT EXISTS settings(key TEXT PRIMARY KEY,value TEXT NOT NULL);
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

    def setting(self,key,value=None):
        if value is None:
            row=self.db.execute('SELECT value FROM settings WHERE key=?',(key,)).fetchone()
            return json.loads(row[0]) if row else None
        with self.db:self.db.execute('INSERT OR REPLACE INTO settings VALUES(?,?)',(key,json.dumps(value)))

    def edit_panel(self,ident,text,rows):
        try:
            self.call('editMessageText',chat_id=GROUP_ID,message_id=ident,text=text,parse_mode='HTML',disable_web_page_preview=True,reply_markup=keyboard(rows))
            return {'message_id':ident}
        except TelegramError as error:
            if 'message is not modified' in error.description.lower():return {'message_id':ident}
            if error.code==400 and any(s in error.description.lower() for s in ("message to edit not found","message can't be edited")):return None
            raise

    def panel(self,text,rows):
        if self.panel_id:
            edited=self.edit_panel(self.panel_id,text,rows)
            if edited:return edited
        sent=self.send(text,rows)
        self.panel_id=sent['message_id']
        return sent

    def ensure_menu(self):
        rows=[[button('📊 Учёт','list:0')],[button('➕ Создать заявку (координатор)','new')],[button('📖 Как пользоваться','help')]]
        text='<b>📦 УЧЁТ ПУША</b>\n\nВыберите заявку в разделе «Учёт». Получатель отмечает отправителей; остальные участники могут смотреть результаты.\n\nНорма — сумма всех ресурсов с одного аккаунта. Создавать заявки может только координатор.'
        ident=self.setting('menu_id')
        if not ident or not self.edit_panel(ident,text,rows):
            ident=self.send(text,rows)['message_id'];self.setting('menu_id',ident)
        if self.setting('pinned_id')!=ident:
            self.call('pinChatMessage',chat_id=GROUP_ID,message_id=ident,disable_notification=True)
            self.setting('pinned_id',ident)
        self.last_menu_check=time.time()
        return ident

    def menu(self,uid):
        self.ensure_menu()

    def job(self, ident):
        row = self.db.execute('SELECT * FROM pushes WHERE id=?', (ident,)).fetchone()
        if not row:
            return None
        job = dict(row)
        job['roster'] = json.loads(job['roster'])
        if any('population' not in p for p in job['roster']):
            if job['snapshot'] not in self.population_cache:
                try:
                    _,players=roster_from_snapshot(snapshot=job['snapshot']) if self.roster is roster_from_snapshot else self.roster()
                    self.population_cache[job['snapshot']]={p['id']:p.get('population',0) for p in players}
                except ValueError:self.population_cache[job['snapshot']]={}
            job['roster']=[{**p,'population':p.get('population',self.population_cache[job['snapshot']].get(p['id'],0))} for p in job['roster']]
        return job

    def statuses(self, ident):
        return {str(r['player']): r['status'] for r in self.db.execute('SELECT player,status FROM payments WHERE push=?', (ident,))}

    def donors(self, job):
        return sorted((p for p in job['roster'] if p['id'] != job['recipient']),key=player_order)

    def title(self, job):
        player = next(p for p in job['roster'] if p['id'] == job['recipient'])
        village = player.get('push_village')
        destination = f'\nДеревня: <b>{esc(village["name"])}</b> · <code>{village["x"]} {village["y"]}</code>' if village else ''
        return f'<b>📦 Пуш #{job["id"]} → {esc(player["name"])}</b>{destination}\nАльянс: {esc(player["alliance"])}\nНорма с аккаунта: <b>{job["norm"]:,}</b> ресурсов\nПолучатель в Telegram: <a href="tg://user?id={job["recipient_user"]}">открыть профиль</a>\n' + ('🟢 Открыт' if job['status'] == 'active' else '🔒 Завершён')

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
        self.panel('<b>📊 Учёт пуша</b>' + ('' if jobs else '\nЗаявок пока нет.'), rows)

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
        self.panel(text, rows)

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
            label = f'{ICONS[key]} {player["name"]} · {player["alliance"]} · 👥 {player.get("population",0)}'
            text += '\n' + esc(label)
            if editable:
                rows.append([button(label[:90], f'pick:{job["id"]}:{player["id"]}')])
        if not players:
            text += '\nСписок пуст.'
        prefix = f'group:{job["id"]}:{status}' if status is not None else f'donors:{job["id"]}'
        rows += self.pager(page, len(players), prefix)
        rows.append([button('⬅️ К учёту', f'view:{job["id"]}')])
        self.panel(text, rows)

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
        self.panel_id=message.get('message_id') if q and message.get('message_id')!=self.setting('menu_id') else None
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
        finally:
            self.panel_id=None
        return True

    def action(self, uid, action):
        parts = action.split(':')
        verb = parts[0]
        sizes={'menu':1,'help':1,'cancel':1,'new':1,'list':2,'view':2,'group':4,'donors':3,'pick':3,'set':4,'close':2}
        if len(parts)!=sizes.get(verb,0):
            raise ValueError('Кнопка устарела. Откройте /push.')
        if verb in ('new', 'close') and uid != OWNER_ID:
            raise ValueError('Создавать и завершать пуш может только координатор.')
        if verb == 'menu':
            self.menu(uid)
        elif verb == 'help':
            self.panel('<b>📖 Как пользоваться</b>\n1. Координатор вводит координаты деревни через пробел (например 22 63). Бот определяет игрока из Сокола или Fun Е. Затем координатор указывает его Telegram и норму с каждого аккаунта.\n2. Получатель открывает «Учёт» → свою заявку → «Отметить отправителя».\n3. Выбирает аккаунт и отмечает: меньше нормы, норму или выше нормы.\n4. Если ошибся, выбирает аккаунт повторно и меняет отметку либо сбрасывает её.\n5. Все участники могут смотреть учёт. «Не прислали» означает, что получатель пока не внёс отметку.\n\nЭто ручной учёт. Бот не проверяет игровые отправки. Состав двух альянсов сохраняется на момент создания; получатель из списка отправителей исключён.', [[button('🏠 Меню', 'menu')]])
        elif verb == 'cancel':
            if uid == OWNER_ID:
                self.state(uid, {})
            self.menu(uid)
        elif verb == 'new':
            snapshot, players = self.roster()
            data = dict(stage='coords', roster=players, snapshot=snapshot, token=uuid.uuid4().hex)
            self.prompt(uid, data, 'введите координаты деревни, которую пушим, <b>через пробел</b>: <code>22 63</code>. Игрок определится автоматически по снимку мира за '+esc(snapshot)+'.')
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
                    self.panel(f'<b>{esc(player["name"])} · {esc(player["alliance"])}</b>\nНорма: {job["norm"]:,} ресурсов.\nСколько прислал этот аккаунт?', rows)
                else:
                    key = parts[3]
                    if key not in STATUSES:
                        raise ValueError('Выберите количество кнопкой.')
                    with self.db:
                        self.db.execute('INSERT OR REPLACE INTO payments VALUES(?,?,?,?)', (job['id'], ident, key, time.time()))
                        self.db.execute('INSERT INTO audit(push,player,actor,status,created) VALUES(?,?,?,?,?)', (job['id'], ident, uid, key, time.time()))
                    self.panel(f'{ICONS[key]} {esc(player["name"])}: {STATUSES[key]}. Отметка сохранена.', [[button('✍️ Следующий отправитель', f'donors:{job["id"]}:0')], [button('📊 Учёт', f'view:{job["id"]}')]])
        else:
            raise ValueError('Кнопка устарела. Откройте /push.')

    def bind_recipient(self, uid, state, ident):
        if ident <= 0 or not self.member(ident):
            raise ValueError('Получатель должен быть участником чата. Проверьте Telegram ID.')
        state.update(stage='norm', recipient_user=ident)
        self.prompt(uid, state, 'введите норму ресурсов с каждого аккаунта, например <code>15000</code>. Это сумма всех типов ресурсов. После ввода заявка сразу создаётся.')

    def input(self, uid, state, text, message):
        if state['stage'] == 'coords':
            x,y = coordinates(text)
            found = next(((player,village) for player in state['roster'] for village in player.get('villages',[]) if (village['x'],village['y'])==(x,y)),None)
            if not found:
                raise ValueError(f'Деревня {x} {y} не найдена среди деревень Сокола и Fun Е в снимке за {state["snapshot"]}. Проверьте координаты и альянс игрока.')
            player,village=found
            state['roster']=[{**p,'push_village':village} if p['id']==player['id'] else p for p in state['roster']]
            state.update(stage='telegram',recipient=player['id'])
            self.prompt(uid,state, f'найден игрок <b>{esc(player["name"])}</b>, альянс <b>{esc(player["alliance"])}</b>, деревня <b>{esc(village["name"])}</b> · <code>{x} {y}</code>.\nУкажите Telegram ID получателя числом либо отправьте /recipient ответом на сообщение самого получателя в этой ветке.')
        elif state['stage'] == 'telegram':
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
        if response.status_code == 400:
            data=response.json()
            raise TelegramError(400,data.get('description','Request rejected'))
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
    try:app.ensure_menu()
    except Exception:print('Push menu refresh unavailable; will retry.',flush=True)
    print('Push ledger ready.', flush=True)
    while True:
        row = app.db.execute('SELECT next_update FROM progress WHERE id=1').fetchone()
        try:
            if time.time()-app.last_menu_check>=60:
                try:app.ensure_menu()
                except Exception:
                    app.last_menu_check=time.time()
                    print('Push menu refresh unavailable; will retry.',flush=True)
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
