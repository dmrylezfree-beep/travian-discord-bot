"""Alliance scouting queue, coordinator settings and public screenshot results."""
import contextlib
import html
import json
import math
import re
import time
import uuid
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
from urllib.parse import urlencode

GROUP_ID = -1002493230303
THREAD_ID = 5
COORDINATOR_ID = 317595036
GAME_TZ = ZoneInfo('Europe/London')
WORLD = 'https://ts8.x1.asia.travian.com'
KINDS = {'resources': 'Ресурсы и войска', 'buildings': 'Строения и войска'}
PAGE_SIZE = 8


def coordinates(text):
    text = re.sub(r'[\u202a-\u202e\u2066-\u2069]', '', str(text)).strip().strip('()').strip()
    match = re.fullmatch(r'(-?\d{1,3})\s*(?:\||,|\s)\s*(-?\d{1,3})', text)
    if not match or any(abs(int(v)) > 200 for v in match.groups()):
        raise ValueError('Введите координаты от −200 до 200: в формате X Y через пробел, например 22 63.')
    return tuple(map(int, match.groups()))


def parse_arrival(text, now):
    raw = str(text).strip()
    if not re.fullmatch(r'\d{2}:\d{2}(?::\d{2})?', raw):
        raise ValueError('Введите только время прибытия по Travian: ЧЧ:ММ или ЧЧ:ММ:СС, например 20:30.')
    try:
        clock = datetime.strptime(raw, '%H:%M:%S' if raw.count(':') == 2 else '%H:%M').time()
    except ValueError:
        raise ValueError('Введите корректное время: ЧЧ:ММ или ЧЧ:ММ:СС, например 20:30.') from None
    local_now = datetime.fromtimestamp(now, GAME_TZ).replace(tzinfo=None)
    wall = datetime.combine(local_now.date(), clock)
    if wall <= local_now:
        wall += timedelta(days=1)
    candidates = set()
    for fold in (0, 1):
        stamp = wall.replace(tzinfo=GAME_TZ, fold=fold).timestamp()
        if datetime.fromtimestamp(stamp, GAME_TZ).replace(tzinfo=None) == wall:
            candidates.add(stamp)
    if len(candidates) != 1:
        raise ValueError('Это время попадает на перевод часов. Укажите однозначное время Travian.')
    stamp = next(iter(candidates))
    if stamp <= now:
        raise ValueError('Время прибытия должно быть в будущем.')
    return stamp


def game_time(stamp):
    return datetime.fromtimestamp(stamp, GAME_TZ).strftime('%d.%m.%Y %H:%M:%S')


def travel_seconds(origin, target, arena):
    dx = abs(origin[0]-target[0]);dy = abs(origin[1]-target[1])
    dx,dy = min(dx,401-dx),min(dy,401-dy)
    distance = math.hypot(dx,dy)
    # Equites Legati, x1 world. Arena applies only after the first 20 fields.
    return math.ceil((min(distance,20)/16 + max(0,distance-20)/(16*(1+0.2*arena)))*3600)


def rally_url(x, y):
    return WORLD+'/build.php?'+urlencode({'gid':16,'tt':2,'x':x,'y':y})


def target_link(x,y):
    return f'<a href="{html.escape(rally_url(x,y),quote=True)}">{x}|{y}</a>'


def public_link(message_id):
    return f'https://t.me/c/2493230303/{THREAD_ID}/{int(message_id)}'


def panel_entry(action):
    # Shared navigation opens the caller's own panel; form buttons stay private.
    return action in ('scan:new','scan:settings','crop:start','help') or action.startswith(('scan:list:','scan:results:','scan:view:'))


def accepts_panel_input(message,state,now,legacy_panel=None):
    prompt=state.get('prompt_message_id')
    if not prompt:return False
    reply=(message.get('reply_to_message') or {}).get('message_id')
    topic_root=message.get('message_thread_id')
    # Telegram may link an ordinary forum message to its topic's root. This
    # is not an explicit reply to another user's message.
    if reply is not None and reply!=topic_root:return reply==prompt
    requested=state.get('input_requested_at')
    if requested is None:
        if legacy_panel!=prompt:return False
    elif not 0<=now-requested<=15*60:return False
    text=re.sub(r'[\u202a-\u202e\u2066-\u2069]','',str(message.get('text') or '')).strip()
    stage=state.get('stage')
    if stage in ('coords','origin'):
        return bool(re.fullmatch(r'\(?\s*-?\d{1,3}\s*(?:\||,|\s)\s*-?\d{1,3}\s*\)?',text))
    if stage=='arrival':return bool(re.fullmatch(r'\d{2}:\d{2}(?::\d{2})?',text))
    if stage=='arena':return bool(re.fullmatch(r'\d{1,3}',text))
    if stage in ('time1','time2'):
        return bool(re.fullmatch(r'(?:\d{2}\.\d{2}\.\d{4} )?\d{2}:\d{2}:\d{2}',text))
    if stage in ('crop1','crop2'):return bool(re.fullmatch(r'[0-9][0-9 \u00a0\u202f]*',text))
    return False


def main_buttons():
    return {'inline_keyboard':[
        [{'text':'📝 Заявка на скан','callback_data':'scan:new'},{'text':'📋 Заявки на скан','callback_data':'scan:list:0'}],
        [{'text':'📷 Результаты сканов','callback_data':'scan:results:0'},{'text':'⚙️ Настройки координатора','callback_data':'scan:settings'}],
        [{'text':'🌾 Расход кропа','callback_data':'crop:start'},{'text':'📖 Как пользоваться','callback_data':'help'}]]}


def scan_kind_buttons():
    return {'inline_keyboard':[[{'text':'🌾 Ресурсы и войска','callback_data':'scan:kind:resources'}],[{'text':'🏛 Строения и войска','callback_data':'scan:kind:buildings'}],cancelled()['inline_keyboard'][0]]}


def cancelled():
    return {'inline_keyboard':[[{'text':'❌ Отменить','callback_data':'scan:cancel'}]]}


class ScoutRequests:
    def __init__(self, store, call, now=time.time):
        self.store,self.db,self.call,self.now=store,store.db,call,now
        self.db.executescript('''
        CREATE TABLE IF NOT EXISTS scout_jobs(id INTEGER PRIMARY KEY AUTOINCREMENT,submit_key TEXT UNIQUE NOT NULL,status TEXT NOT NULL,data TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS scout_sessions(chat INTEGER,user INTEGER,data TEXT NOT NULL,PRIMARY KEY(chat,user));
        CREATE TABLE IF NOT EXISTS scout_settings(key TEXT PRIMARY KEY,data TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS scout_bindings(chat INTEGER,message INTEGER,request INTEGER NOT NULL,PRIMARY KEY(chat,message));
        CREATE TABLE IF NOT EXISTS scout_results(id INTEGER PRIMARY KEY AUTOINCREMENT,request INTEGER NOT NULL,source_chat INTEGER NOT NULL,source_message INTEGER NOT NULL,public_message INTEGER NOT NULL,created REAL NOT NULL,UNIQUE(source_chat,source_message));
        CREATE TABLE IF NOT EXISTS scout_panels(chat INTEGER,user INTEGER,message INTEGER NOT NULL,PRIMARY KEY(chat,user));
        CREATE TABLE IF NOT EXISTS scout_uploads(chat INTEGER,request INTEGER,message INTEGER NOT NULL,PRIMARY KEY(chat,request));
        CREATE TABLE IF NOT EXISTS scout_albums(chat INTEGER,album TEXT,request INTEGER NOT NULL,PRIMARY KEY(chat,album));
        ''')
        self.db.execute('INSERT OR IGNORE INTO scout_settings VALUES(?,?)',('coordinator',json.dumps({'user_id':COORDINATOR_ID,'x':22,'y':63,'arena':7})))
        self.db.commit()
        self.last_refresh=0
        self.members={}
        self.member_labels={}
        self.fresh_panels=set()

    def setting(self,key,default=None):
        row=self.db.execute('SELECT data FROM scout_settings WHERE key=?',(key,)).fetchone()
        return json.loads(row[0]) if row else default

    def set_setting(self,key,value):
        self.db.execute('INSERT OR REPLACE INTO scout_settings VALUES(?,?)',(key,json.dumps(value)))

    def session(self,chat,user):
        row=self.db.execute('SELECT data FROM scout_sessions WHERE chat=? AND user=?',(chat,user)).fetchone()
        return json.loads(row[0]) if row else {}

    def save_session(self,chat,user,data):
        self.db.execute('INSERT OR REPLACE INTO scout_sessions VALUES(?,?,?)',(chat,user,json.dumps(data)))

    def job(self,ident):
        row=self.db.execute('SELECT id,status,data FROM scout_jobs WHERE id=?',(int(ident),)).fetchone()
        return dict(json.loads(row[2]),id=row[0],status=row[1]) if row else None

    def jobs(self,results=False):
        if results:
            rows=self.db.execute('SELECT DISTINCT j.id FROM scout_jobs j JOIN scout_results r ON j.id=r.request ORDER BY j.id DESC').fetchall()
        else:
            rows=self.db.execute("SELECT id FROM scout_jobs WHERE status='pending' ORDER BY id").fetchall()
        return [self.job(r[0]) for r in rows]

    def mention(self,user_id,fallback=None):
        """Chat-assigned tag first, then username/name; link always targets the user."""
        fallback=fallback or {}
        if not isinstance(fallback,dict):fallback={'first_name':str(fallback)}
        if not user_id:return html.escape(str(fallback.get('first_name') or 'Игрок'))
        user_id=int(user_id);cached=self.member_labels.get(user_id)
        if not cached or self.now()-cached[0]>=300:
            try:member=self.call('getChatMember',chat_id=GROUP_ID,user_id=user_id)
            except Exception:member={}
            self.member_labels[user_id]=(self.now(),member)
        else:member=cached[1]
        profile=member.get('user') or {}
        tag=str(member.get('tag') or '').strip()
        username=profile.get('username') or fallback.get('username')
        name=' '.join(str(profile.get(key) or '').strip() for key in ('first_name','last_name')).strip()
        label=tag or ('@'+str(username).lstrip('@') if username else '') or name or fallback.get('first_name') or str(user_id)
        return f'<a href="tg://user?id={user_id}">{html.escape(str(label)[:128])}</a>'

    def send(self,chat,text,keyboard=None,user=None,force=False,reply_to=None):
        args={'chat_id':chat,'text':text,'parse_mode':'HTML'}
        if chat==GROUP_ID:
            args['message_thread_id']=THREAD_ID
            if user:args['text']=self.mention(user['id'],user)+'\n'+text
        if force:
            args['reply_markup']={'force_reply':True,'selective':True}
            args['text']+='\n\nОтветьте на это сообщение. Отмена: /cancel'
        elif keyboard:args['reply_markup']=keyboard
        if reply_to:args['reply_parameters']={'message_id':reply_to,'allow_sending_without_reply':True}
        return self.call('sendMessage',**args)

    def foreign_panel(self,message,user,action=""):
        if panel_entry(action):return False
        row=self.db.execute('SELECT user FROM scout_panels WHERE chat=? AND message=?',(message['chat']['id'],message['message_id'])).fetchone()
        return bool(row and row[0]!=user['id'])

    def adopt_panel(self,message,user):
        chat=message['chat']
        if chat.get('type')=='private' and not self.db.execute('SELECT 1 FROM scout_bindings WHERE chat=? AND message=?',(chat['id'],message['message_id'])).fetchone() and not self.db.execute('SELECT 1 FROM scout_panels WHERE chat=? AND user=?',(chat['id'],user['id'])).fetchone():
            self.db.execute('INSERT INTO scout_panels VALUES(?,?,?)',(chat['id'],user['id'],message['message_id']))

    def focus_panel(self,message,user,action='',command=''):
        chat=message['chat']['id'];key=(chat,user['id'])
        row=self.db.execute('SELECT message FROM scout_panels WHERE chat=? AND user=?',key).fetchone()
        if command in ('/start','/scout','/requests','/settings','/crop','/help') or (panel_entry(action) and row and row[0]!=message['message_id']):
            self.fresh_panels.add(key)

    def render(self,chat,text,keyboard=None,user=None,force=False):
        """One durable working panel per user; the shared pinned queue stays separate."""
        uid=user['id'];keyboard=keyboard or main_buttons()
        if chat==GROUP_ID:
            text=self.mention(uid,user)+'\n'+text
            if force:text+='\n\nМожно просто написать ответ в эту ветку или ответить на это меню. Отмена: /cancel'
        args={'chat_id':chat,'text':text,'parse_mode':'HTML','reply_markup':keyboard}
        row=self.db.execute('SELECT message FROM scout_panels WHERE chat=? AND user=?',(chat,uid)).fetchone()
        fresh=(chat,uid) in self.fresh_panels
        if row and not fresh:
            try:
                self.call('editMessageText',message_id=row[0],**args)
                return {'message_id':row[0]}
            except Exception as error:
                response=getattr(error,'response',None)
                description=(response.text or '').lower() if response is not None else ''
                if response is not None and response.status_code==400 and 'message is not modified' in description:
                    return {'message_id':row[0]}
                missing=response is not None and response.status_code==400 and any(value in description for value in ('message to edit not found','message_id_invalid',"message can't be edited",'message cannot be edited'))
                if not missing:raise
        if chat==GROUP_ID:args['message_thread_id']=THREAD_ID
        sent=self.call('sendMessage',**args)
        self.db.execute('INSERT OR REPLACE INTO scout_panels VALUES(?,?,?)',(chat,uid,sent['message_id']))
        self.fresh_panels.discard((chat,uid))
        if row and row[0]!=sent['message_id'] and row[0]!=self.setting('centre_id') and not self.db.execute('SELECT 1 FROM scout_bindings WHERE chat=? AND message=?',(chat,row[0])).fetchone():
            try:self.call('editMessageReplyMarkup',chat_id=chat,message_id=row[0],reply_markup={'inline_keyboard':[]})
            except Exception:pass
        return sent

    def prompt(self,chat,user,state,text,keyboard=None,force=False):
        sent=self.render(chat,text,keyboard or (cancelled() if force else None),user,force)
        state['prompt_message_id']=sent['message_id'];state['input_requested_at']=self.now();self.save_session(chat,user['id'],state)

    def schedule(self,job):
        settings=self.setting('coordinator')
        if job.get('arrival') is None:return None
        seconds=travel_seconds((settings['x'],settings['y']),(job['x'],job['y']),settings['arena'])
        return job['arrival']-seconds,seconds

    def job_text(self,job):
        data=(f'<b>🔎 Заявка на скан #{job["id"]}</b>\n\n🎯 {target_link(job["x"],job["y"])}\n'
              f'📋 {KINDS[job["kind"]]}\n👤 Заявитель: {self.mention(job.get("creator"),{"first_name":job["creator_name"],"username":job.get("creator_username")})}\n')
        timing=self.schedule(job)
        if timing:
            departure,seconds=timing;s=self.setting('coordinator')
            data+=(f'🎯 Прибытие скана: <b>{game_time(job["arrival"])}</b>\n'
                   f'🏘 Отправлять из: {s["x"]}|{s["y"]}, арена {s["arena"]}\n'
                   f'🐎 Римские разведчики: 16 полей/ч\n'
                   f'⏱ В пути: {seconds//3600:02}:{seconds%3600//60:02}:{seconds%60:02}\n'
                   f'🚀 Отправить: <b>{game_time(departure)}</b>\n')
            if departure<=self.now() and job['status']=='pending':data+='⚠️ <b>Срок отправки прошёл. Ко времени уже не успеть.</b>\n'
            data+='🕒 Время Travian (Europe/London). Расчёт без героя и артефактов; проверьте время в игре.\n'
        else:data+='🕒 В любое время\n'
        data+='\n'+('🗑 Удалена автором' if job['status']=='cancelled' else '✅ Выполнена' if job['status']=='done' else '⏳ Ожидает выполнения')
        results=self.db.execute('SELECT public_message FROM scout_results WHERE request=? ORDER BY id',(job['id'],)).fetchall()
        for i,r in enumerate(results,1):data+=f'\n📷 <a href="{public_link(r[0])}">Результат {i}</a>'
        return data

    def queue_view(self,page=0,results=False):
        jobs=self.jobs(results);page=max(0,min(int(page),max(0,(len(jobs)-1)//PAGE_SIZE)))
        text='<b>📷 РЕЗУЛЬТАТЫ СКАНОВ</b>' if results else '<b>🔎 ЦЕНТР РАЗВЕДКИ</b>\nОткрытые заявки на скан'
        text+=f'\nВсего: {len(jobs)}'
        if not jobs:text+='\n\nПока нет результатов.' if results else '\n\nОткрытых заявок нет.'
        buttons=[]
        for job in jobs[page*PAGE_SIZE:(page+1)*PAGE_SIZE]:
            timing=self.schedule(job)
            when=('в любое время' if timing is None else 'прибытие '+game_time(job['arrival']))
            late=' · ⚠️ срок отправки прошёл' if timing and timing[0]<=self.now() and job['status']=='pending' else ''
            text+=f'\n\n<b>#{job["id"]}</b> · {target_link(job["x"],job["y"])}\n{KINDS[job["kind"]]} · {when}{late}'
            if timing:text+='\n🚀 Отправить: '+game_time(timing[0])
            buttons.append([{'text':f'🔎 #{job["id"]} · {job["x"]}|{job["y"]}','callback_data':f'scan:view:{job["id"]}'}])
        nav=[];prefix='results' if results else 'list'
        if page:nav.append({'text':'⬅️ Назад','callback_data':f'scan:{prefix}:{page-1}'})
        if (page+1)*PAGE_SIZE<len(jobs):nav.append({'text':'Дальше ➡️','callback_data':f'scan:{prefix}:{page+1}'})
        if nav:buttons.append(nav)
        buttons+=main_buttons()['inline_keyboard']
        return text,{'inline_keyboard':buttons}

    def ensure_centre(self):
        # A network error must never cause a second centre to be posted.
        context=contextlib.nullcontext() if self.db.in_transaction else self.db
        with context:
            text,keyboard=self.queue_view();message_id=self.setting('centre_id')
            if message_id:
                try:self.call('editMessageText',chat_id=GROUP_ID,message_id=message_id,text=text,parse_mode='HTML',reply_markup=keyboard)
                except Exception as error:
                    r=getattr(error,'response',None);description=r.text.lower() if r is not None else ''
                    if r is not None and r.status_code==400 and 'message is not modified' in description:pass
                    elif r is not None and r.status_code==400 and any(t in description for t in ['message to edit not found',"message can't be edited",'message_id_invalid']):message_id=None
                    else:return False
            if not message_id:
                try:message_id=self.send(GROUP_ID,text,keyboard)['message_id']
                except Exception:return False
                self.set_setting('centre_id',message_id)
            if self.setting('pinned_id')!=message_id:
                try:self.call('pinChatMessage',chat_id=GROUP_ID,message_id=message_id,disable_notification=True)
                except Exception:return False
                self.set_setting('pinned_id',message_id)
            remaining=[]
            for old_id in self.setting('retired_centre_ids',[]):
                if old_id==message_id:continue
                try:self.call('unpinChatMessage',chat_id=GROUP_ID,message_id=old_id)
                except Exception as error:
                    response=getattr(error,'response',None)
                    description=(response.text or '').lower() if response is not None else ''
                    gone=response is not None and response.status_code==400 and any(value in description for value in ('message is not pinned','message to unpin not found','message_id_invalid'))
                    if not gone:remaining.append(old_id)
            self.set_setting('retired_centre_ids',remaining)
            if remaining:return False
            self.last_refresh=self.now()
            return True

    def restart_centre(self,chat,user):
        previous=self.setting('centre_id');text,keyboard=self.queue_view()
        sent=self.send(GROUP_ID,text,keyboard);message_id=sent['message_id']
        retired=self.setting('retired_centre_ids',[])
        if previous and previous!=message_id and previous not in retired:retired.append(previous)
        self.set_setting('centre_id',message_id);self.set_setting('retired_centre_ids',retired)
        # Save the posted message ID before pinning: failures retry the pin,
        # rather than creating another centre on the next periodic refresh.
        self.db.commit()
        self.ensure_centre()
        row=self.db.execute('SELECT message FROM scout_panels WHERE chat=? AND user=?',(chat,user['id'])).fetchone()
        if row and row[0] not in (previous,message_id) and not self.db.execute('SELECT 1 FROM scout_bindings WHERE chat=? AND message=?',(chat,row[0])).fetchone():
            try:self.call('editMessageReplyMarkup',chat_id=chat,message_id=row[0],reply_markup={'inline_keyboard':[]})
            except Exception:pass
        self.fresh_panels.discard((chat,user['id']))

    def tick(self):
        if self.now()-self.last_refresh>=60:self.ensure_centre()

    def detail(self,chat,user,job):
        text=self.job_text(job);rows=[[{'text':'🏹 Открыть пункт сбора','url':rally_url(job['x'],job['y'])}]]
        if user['id']==COORDINATOR_ID and job['status']!='cancelled':
            text+='\n\n📷 Нажмите «Прикрепить результат», затем ответьте скриншотом на отдельное сообщение с координатами.'
            rows.append([{'text':'📷 Прикрепить результат','callback_data':f'scan:upload:{job["id"]}'}])
            rows.append([{'text':'✅ Выполнена' if job['status']=='pending' else '↩️ Вернуть в очередь','callback_data':f'scan:done:{job["id"]}' if job['status']=='pending' else f'scan:reopen:{job["id"]}'}])
        if user['id']==job['creator'] and job['status']=='pending':
            rows.append([{'text':'🗑 Удалить мою заявку','callback_data':f'scan:delete:{job["id"]}'}])
        rows.append([{'text':'📋 К заявкам','callback_data':'scan:list:0'}])
        self.render(chat,text,{'inline_keyboard':rows},user)

    def upload_prompt(self,chat,user,job):
        row=self.db.execute('SELECT message FROM scout_uploads WHERE chat=? AND request=?',(chat,job['id'])).fetchone()
        if not row:
            text=f'<b>📷 Результат скана #{job["id"]}</b>\n🎯 {target_link(job["x"],job["y"])}\n📋 {KINDS[job["kind"]]}\n\nПрикрепите скриншот ответом на это сообщение. Эта привязка сохранится при переходах по меню.'
            sent=self.send(chat,text,user=user,force=True)
            message_id=sent['message_id']
            self.db.execute('INSERT INTO scout_uploads VALUES(?,?,?)',(chat,job['id'],message_id))
            self.db.execute('INSERT OR REPLACE INTO scout_bindings VALUES(?,?,?)',(chat,message_id,job['id']))
        else:message_id=row[0]
        text=f'📷 Для заявки #{job["id"]} ответьте скриншотом на сообщение «Результат скана #{job["id"]}» с координатами {job["x"]} {job["y"]}.'
        if chat==GROUP_ID:text+=f'\n<a href="{public_link(message_id)}">Открыть сообщение для скриншота</a>'
        self.render(chat,text,{'inline_keyboard':[[{'text':'⬅️ К заявке','callback_data':f'scan:view:{job["id"]}'}]]},user)

    def publish_photo(self,message,user):
        chat=message['chat']['id'];reply=(message.get('reply_to_message') or {}).get('message_id')
        row=self.db.execute('SELECT request FROM scout_bindings WHERE chat=? AND message=?',(chat,reply)).fetchone() if reply else None
        album=message.get('media_group_id')
        if not row and album:row=self.db.execute('SELECT request FROM scout_albums WHERE chat=? AND album=?',(chat,album)).fetchone()
        if not row:return False
        if user['id']!=COORDINATOR_ID:
            self.render(chat,'Прикреплять результаты заявок может только координатор.',user=user);return True
        if self.db.execute('SELECT 1 FROM scout_results WHERE source_chat=? AND source_message=?',(chat,message['message_id'])).fetchone():return True
        document=message.get('document') or {}
        if not message.get('photo') and not str(document.get('mime_type','')).startswith('image/'):
            self.render(chat,'Пришлите скриншот как фотографию или файл изображения.',user=user);return True
        job=self.job(row[0]);caption=f'📷 <b>Результат скана #{job["id"]}</b>\n🎯 {target_link(job["x"],job["y"])}\n📋 {KINDS[job["kind"]]}'
        if chat==GROUP_ID:
            public_message=message['message_id']
            self.send(GROUP_ID,caption+'\nСкриншот — в сообщении выше. Для завершения нажмите «Выполнена» в карточке.',reply_to=public_message)
        else:
            sent=self.call('copyMessage',chat_id=GROUP_ID,message_thread_id=THREAD_ID,from_chat_id=chat,message_id=message['message_id'],caption=caption,parse_mode='HTML')
            public_message=sent['message_id']
            self.render(chat,'✅ Скриншот опубликован в общей ветке.\n'+f'<a href="{public_link(public_message)}">Открыть результат</a>',user=user)
        self.db.execute('INSERT INTO scout_results(request,source_chat,source_message,public_message,created) VALUES(?,?,?,?,?)',(job['id'],chat,message['message_id'],public_message,self.now()))
        if album:self.db.execute('INSERT OR REPLACE INTO scout_albums VALUES(?,?,?)',(chat,album,job['id']))
        self.ensure_centre();return True

    def handle(self,update):
        q=update.get('callback_query') or {};message=update.get('message') or q.get('message') or {}
        chat=message.get('chat') or {};user=(q.get('from') if q else message.get('from')) or {}
        if not q and chat.get('id')==GROUP_ID and user.get('id') and re.fullmatch(r'-?\d{1,3}\s+-?\d{1,3}',str(message.get('text') or '').strip()):
            current=self.session(chat['id'],user['id']);row=self.db.execute('SELECT message FROM scout_panels WHERE chat=? AND user=?',(chat['id'],user['id'])).fetchone()
            reply=(message.get('reply_to_message') or {}).get('message_id')
            kind='none' if reply is None else 'menu' if reply==current.get('prompt_message_id') else 'topic_root' if reply==message.get('message_thread_id') else 'other'
            print('Scout coordinate route '+json.dumps({'topic_match':message.get('message_thread_id')==THREAD_ID,'stage':current.get('stage'),'reply_kind':kind,'accepted_input':accepts_panel_input(message,current,self.now(),row[0] if row else None)}),flush=True)
        if not user.get('id') or not (chat.get('type')=='private' or (chat.get('id')==GROUP_ID and message.get('message_thread_id')==THREAD_ID)):return False
        if q:
            if self.foreign_panel(message,user,q.get("data", "")):
                self.call('answerCallbackQuery',callback_query_id=q['id'],text='Это меню другого участника. Откройте своё через /scout.')
                return True
            self.adopt_panel(message,user)
        if chat.get('type')=='private' and user['id']!=COORDINATOR_ID:
            raw_command=str(message.get('text') or '').split()
            raw_command=raw_command[0].split('@')[0] if raw_command else ''
            is_scan=q.get('data','').startswith('scan:') or raw_command in ('/scout','/requests','/settings') or bool(self.session(chat['id'],user['id']))
            if is_scan:
                cached=self.members.get(user['id'])
                if cached and self.now()-cached[0]<120:member=cached[1]
                else:
                    try:
                        info=self.call('getChatMember',chat_id=GROUP_ID,user_id=user['id'])
                        member=info.get('status') in ('member','administrator','creator') or (info.get('status')=='restricted' and info.get('is_member'))
                    except Exception:member=False
                    self.members[user['id']]=(self.now(),member)
                if not member:
                    self.send(chat['id'],'Заявки на скан доступны участникам чата альянса. Откройте меню в общей ветке или проверьте членство в группе.',user=user)
                    return True
        with self.db:
            raw=str(message.get('text') or '').split() if not q else []
            command=raw[0] if raw else ''
            if '@' not in command or command.split('@',1)[1].lower()=='scout_travian_bot':
                self.focus_panel(message,user,q.get('data',''),command.split('@')[0])
            handled=self._handle(update,q,message,chat['id'],user)
            if handled and isinstance(update.get('update_id'),int):
                self.db.execute('INSERT OR REPLACE INTO progress VALUES(1,?)',(update['update_id']+1,))
            return handled

    def _handle(self,update,q,message,chat,user):
        uid=user['id'];action=str(q.get('data') or '');text=str(message.get('text') or '').strip();state=self.session(chat,uid)
        command=text.split()[0] if text.startswith('/') else ''
        if '@' in command and command.split('@',1)[1].lower()!='scout_travian_bot':return False
        command=command.split('@')[0]
        if command=='/start' and chat==GROUP_ID:
            self.save_session(chat,uid,{})
            self.db.execute('INSERT OR REPLACE INTO sessions VALUES(?,?,?)',(chat,uid,'{}'))
            self.restart_centre(chat,user)
            return True
        if action.startswith('crop:') or action in ('help','cancel') or command in ('/start','/crop','/help'):
            self.save_session(chat,uid,{});return False
        if command in ('/scout','/requests'):action='scan:list:0'
        if command=='/settings':action='scan:settings'
        if command=='/cancel' and state:action='scan:cancel'
        if not q and not user.get('is_bot') and chat==GROUP_ID and re.fullmatch(r'-?\d{1,3}\s+-?\d{1,3}',re.sub(r'[\u202a-\u202e\u2066-\u2069]','',text)):
            crop_state=self.store.load(chat,uid)
            row=self.db.execute('SELECT message FROM scout_panels WHERE chat=? AND user=?',(chat,uid)).fetchone();panel=row[0] if row else None
            in_settings=state.get('stage') in ('origin','arena') and accepts_panel_input(message,state,self.now(),panel)
            in_calculator=crop_state.get('stage') in ('time1','crop1','time2','crop2') and accepts_panel_input(message,crop_state,self.now(),panel)
            if not in_settings and not in_calculator:
                self.start_coordinates(chat,user,message,state,text)
                return True
        if action.startswith('scan:'):
            self.db.execute('INSERT OR REPLACE INTO sessions VALUES(?,?,?)',(chat,uid,'{}'))
            return self.action(chat,user,state,action)
        if message.get('photo') or message.get('document'):
            return self.publish_photo(message,user)
        if not state.get('stage') or q:return False
        if chat==GROUP_ID:
            row=self.db.execute('SELECT message FROM scout_panels WHERE chat=? AND user=?',(chat,uid)).fetchone()
            if not accepts_panel_input(message,state,self.now(),row[0] if row else None):return False
        self.input(chat,user,state,text);return True

    def action(self,chat,user,state,action):
        uid=user['id'];parts=action.split(':');verb=parts[1] if len(parts)>1 else ''
        if verb in ('list','results','settings','view','done','reopen','delete','upload'):self.save_session(chat,uid,{})
        if verb in ('settings','origin','arena','done','reopen','upload') and uid!=COORDINATOR_ID:
            self.render(chat,'Эта функция доступна только скаут-координатору.',user=user);return True
        if verb=='new':
            self.db.execute('INSERT OR REPLACE INTO sessions VALUES(?,?,?)',(chat,uid,'{}'))
            self.prompt(chat,user,{'stage':'coords','token':uuid.uuid4().hex},'Введите координаты деревни, которую нужно разведать, <b>через пробел</b>: <code>145 52</code>. Формат: X Y.',force=True)
        elif verb=='cancel':
            self.save_session(chat,uid,{});self.render(chat,'Действие отменено.',main_buttons(),user)
        elif verb in ('list','results'):
            page=int(parts[2]) if len(parts)>2 and parts[2].isdigit() else 0
            self.render(chat,*self.queue_view(page,verb=='results'),user=user);self.ensure_centre()
        elif verb=='delete':
            ident=int(parts[2]) if len(parts)>2 and parts[2].isdigit() else -1
            job=self.job(ident)
            if not job or job['creator']!=uid:
                self.render(chat,'Можно удалить только свою заявку.',user=user);return True
            if job['status'] not in ('pending','cancelled'):
                self.render(chat,'Эта заявка уже выполнена. Результат сохранён.',user=user);return True
            self.db.execute("UPDATE scout_jobs SET status='cancelled' WHERE id=?",(ident,))
            self.ensure_centre()
            self.render(chat,f'🗑 Заявка #{ident} удалена из очереди.',main_buttons(),user)
        elif verb in ('view','done','reopen','upload'):
            ident=int(parts[2]) if len(parts)>2 and parts[2].isdigit() else -1;job=self.job(ident)
            if not job:self.render(chat,'Заявка не найдена.',user=user);return True
            if verb in ('done','reopen') and job['status']=='cancelled':
                self.render(chat,'Заявка удалена автором.',user=user);return True
            if verb in ('done','reopen'):
                self.db.execute('UPDATE scout_jobs SET status=? WHERE id=?',('done' if verb=='done' else 'pending',ident));self.ensure_centre();job=self.job(ident)
            if verb=='upload':
                if job['status']=='cancelled':self.render(chat,'Заявка удалена автором.',user=user)
                else:self.upload_prompt(chat,user,job)
            else:self.detail(chat,user,job)
        elif verb=='settings':
            s=self.setting('coordinator')
            self.render(chat,f'<b>⚙️ Настройки координатора</b>\nTelegram ID: {COORDINATOR_ID}\n🏘 Деревня: {s["x"]}|{s["y"]}\n🏟 Арена: {s["arena"]}\n🐎 Римские разведчики: 16 полей/ч\n\nИзменения пересчитывают время отправки открытых заявок.',{'inline_keyboard':[[{'text':'🏘 Изменить деревню','callback_data':'scan:origin'},{'text':'🏟 Изменить арену','callback_data':'scan:arena'}],[{'text':'📋 К заявкам','callback_data':'scan:list:0'}]]},user)
        elif verb in ('origin','arena'):
            self.prompt(chat,user,{'stage':verb},'Введите координаты деревни отправки <b>через пробел</b>: <code>22 63</code>. Формат: X Y.' if verb=='origin' else 'Введите уровень арены от 0 до 20.',force=True)
        elif verb=='kind' and state.get('stage')=='kind' and len(parts)>2 and parts[2] in KINDS:
            state.update(kind=parts[2],stage='timing')
            self.prompt(chat,user,state,'Когда нужен скан?',{'inline_keyboard':[[{'text':'🕒 В любое время','callback_data':'scan:any'},{'text':'⏰ К определённому времени','callback_data':'scan:timed'}],cancelled()['inline_keyboard'][0]]})
        elif verb=='any' and state.get('stage')=='timing':
            state['arrival']=None;self.submit(chat,user,state)
        elif verb=='timed' and state.get('stage')=='timing':
            state['stage']='arrival';example=datetime.fromtimestamp(self.now()+7200, GAME_TZ).strftime('%H:%M:%S')
            self.prompt(chat,user,state,'Введите <b>только время прибытия разведчиков</b> по серверу Travian (ЧЧ:ММ или ЧЧ:ММ:СС), без даты.\nЕсли время ещё впереди — сегодня; если уже прошло — завтра.\nНапример: <code>'+example+'</code>',force=True)
        elif verb=='confirm' and len(parts)>2:
            token=parts[2];existing=self.db.execute('SELECT id,data FROM scout_jobs WHERE submit_key=?',(token,)).fetchone()
            if existing:
                if json.loads(existing[1])['creator']!=uid:self.render(chat,'Это подтверждение другого пользователя.',user=user)
                else:self.render(chat,f'✅ Заявка #{existing[0]} уже создана.',main_buttons(),user)
                self.ensure_centre();return True
            if state.get('stage')!='confirm' or token!=state.get('token'):
                self.render(chat,'Это старое подтверждение. Создайте заявку заново.',main_buttons(),user);return True
            payload={k:state[k] for k in ('x','y','kind','arrival')}
            payload.update(creator=uid,creator_name=user.get('first_name') or str(uid),creator_username=user.get('username'),created=self.now())
            timing=self.schedule(payload)
            if timing and timing[0]<=self.now():
                state['stage']='arrival';self.prompt(chat,user,state,'К этому времени разведчики уже не успеют. Введите более позднее время прибытия (ЧЧ:ММ или ЧЧ:ММ:СС).',force=True);return True
            row=self.db.execute("INSERT INTO scout_jobs(submit_key,status,data) VALUES(?,'pending',?)",(token,json.dumps(payload)));ident=row.lastrowid
            self.save_session(chat,uid,{});self.ensure_centre()
            self.render(chat,f'✅ Заявка на скан #{ident} добавлена в общую очередь.',{'inline_keyboard':[[{'text':'🔎 Открыть заявку','callback_data':f'scan:view:{ident}'}],[{'text':'🗑 Удалить мою заявку','callback_data':f'scan:delete:{ident}'}]]},user)
        else:self.render(chat,'Эта кнопка устарела. Откройте нужный раздел заново.',main_buttons(),user)
        return True

    def start_coordinates(self,chat,user,message,state,text):
        token=uuid.uuid5(uuid.NAMESPACE_URL,f'scout-coordinate:{chat}:{user["id"]}:{message["message_id"]}').hex
        existing=self.db.execute('SELECT id FROM scout_jobs WHERE submit_key=?',(token,)).fetchone()
        if existing:
            self.render(chat,f'✅ Заявка #{existing[0]} уже создана.',main_buttons(),user)
            return
        if state.get('token')==token:return
        self.db.execute('INSERT OR REPLACE INTO sessions VALUES(?,?,?)',(chat,user['id'],'{}'))
        state={'stage':'coords','token':token}
        try:state['x'],state['y']=coordinates(text)
        except ValueError as error:
            self.prompt(chat,user,state,'❌ '+html.escape(str(error)),cancelled(),force=True)
            return
        state['stage']='kind'
        self.fresh_panels.add((chat,user['id']))
        self.prompt(chat,user,state,f'<b>🔎 Новая заявка на скан</b>\n🎯 {target_link(state["x"],state["y"])}\n\nКакой скан нужен?',scan_kind_buttons())
        print('Scout coordinate draft started',flush=True)

    def submit(self,chat,user,state):
        # Reuse the durable submission key for retry protection and old buttons.
        state['stage']='confirm'
        self.save_session(chat,user['id'],state)
        self.action(chat,user,state,'scan:confirm:'+state['token'])

    def input(self,chat,user,state,text):
        stage=state['stage']
        try:
            if stage in ('origin','arena'):
                if user['id']!=COORDINATOR_ID:raise ValueError('Настройки доступны только координатору.')
                settings=self.setting('coordinator')
                if stage=='origin':settings['x'],settings['y']=coordinates(text)
                else:
                    if not re.fullmatch(r'\d{1,2}',text) or not 0<=int(text)<=20:raise ValueError('Уровень арены — целое число от 0 до 20.')
                    settings['arena']=int(text)
                self.set_setting('coordinator',settings);self.save_session(chat,user['id'],{});self.ensure_centre()
                self.render(chat,'✅ Настройки сохранены. Время открытых заявок пересчитано.',main_buttons(),user);return
            if stage=='coords':
                state['x'],state['y']=coordinates(text);state['stage']='kind'
                self.prompt(chat,user,state,'Какой скан нужен?',scan_kind_buttons());return
            if stage=='arrival':
                state['arrival']=parse_arrival(text,self.now());self.submit(chat,user,state);return
            raise ValueError('Выберите вариант кнопкой под вопросом бота.')
        except ValueError as error:
            self.prompt(chat,user,state,'❌ '+html.escape(str(error)),force=stage in ('coords','arrival','origin','arena'),keyboard=cancelled())
