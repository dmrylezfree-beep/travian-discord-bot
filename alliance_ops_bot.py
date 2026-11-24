import os, re, json, time, html, subprocess, uuid, hashlib
from datetime import datetime, timezone, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo
import requests

TELEGRAM_PROXY_URL = os.environ.get("TELEGRAM_PROXY_URL")
TELEGRAM_PROXIES = {"https": TELEGRAM_PROXY_URL} if TELEGRAM_PROXY_URL else None

TOKEN=os.environ.get("ALLIANCE_OPS_TELEGRAM_TOKEN")
COORDINATORS={317595036}
SNAPSHOTS=Path("data/snapshots")
DATA=Path("data/alliance_ops")
OFFERS=DATA/"offers.json"; TARGETS=DATA/"targets.json"; STATES=DATA/"states.json"; OPERATIONS=DATA/"operations.json"
TZ=ZoneInfo('Europe/London')
TIME_NOTE='🕒 Время сервера Travian (Europe/London): летом UTC+1, зимой UTC.'
TRIBES={1:"Римляне",2:"Германцы",3:"Галлы",6:"Египтяне",7:"Гунны",8:"Спартанцы"}
TROOPS={
1:["Легионер","Преторианец","Империанец","Конница легата","Императорская конница","Конница Цезаря","Таран","Огненная катапульта","Сенатор"],
2:["Дубинщик","Копейщик","Топорщик","Скаут","Паладин","Тевтонская конница","Стенобитное орудие","Катапульта","Вождь"],
3:["Фаланга","Мечник","Следопыт","Гром Теутатеса","Друид-всадник","Эдуйская конница","Таран","Требушет","Предводитель"],
6:["Раб","Страж Аш","Воин Хопеш","Разведчик Сопду","Всадник Анхур","Всадник Решеф","Таран","Камнемёт","Номарх"],
7:["Наёмник","Лучник","Наблюдатель","Степной всадник","Марксман","Мародёр","Таран","Катапульта","Логад"],
8:["Гоплит","Страж","Щитоносец","Разведчик","Элпида","Коринфский всадник","Таран","Баллиста","Эфор"]}
TARGET_TYPES=["Столица","Офф","Деф","Обычная","Не определено"]

def server_datetime(value):
    value=datetime.fromisoformat(value) if isinstance(value,str) else value
    return value.replace(tzinfo=TZ) if value.tzinfo is None else value.astimezone(TZ)


def shift_seconds(value,seconds):
    return datetime.fromtimestamp(server_datetime(value).timestamp()+seconds,TZ)


def normalize_operation_times(operations):
    for op in operations.values():
        legacy=op.get('time_zone')!='Europe/London'
        for item in [op]+list(op.get('attacks',{}).values()):
            if not item.get('arrival_iso'):continue
            if legacy:
                # Explicit owner choice: keep the entered clock, reinterpret it
                # as Travian time, rather than preserve its old Moscow instant.
                wall=datetime.fromisoformat(item['arrival_iso']).replace(tzinfo=None)
                dt=op_dt(wall.strftime('%d.%m.%Y %H:%M:%S'))
                if dt is None:raise ValueError('Ambiguous legacy operation time')
            else:dt=server_datetime(item['arrival_iso'])
            item['arrival_iso']=dt.isoformat()
            item['arrival']=dt.strftime('%d.%m.%Y %H:%M:%S')
        op['time_zone']='Europe/London'
    return operations


def migrate_server_times():
    # One-time migration happens before polling/reminders. All rows are prepared
    # before either file is replaced; no silent partial conversion of an op.
    operations=json.loads(OPERATIONS.read_text(encoding='utf-8'))
    states=json.loads(STATES.read_text(encoding='utf-8'))
    original=json.dumps(operations,sort_keys=True)
    normalize_operation_times(operations)
    for session in states.values():
        data=session.get('data') or {}
        if data.get('arrival_iso') and data.get('time_zone')!='Europe/London':
            wall=datetime.fromisoformat(data['arrival_iso']).replace(tzinfo=None)
            dt=op_dt(wall.strftime('%d.%m.%Y %H:%M:%S'))
            if dt is None:raise ValueError('Ambiguous legacy wizard time')
            data['arrival_iso']=dt.isoformat();data['time_zone']='Europe/London'
    if json.dumps(operations,sort_keys=True)!=original:
        temp=OPERATIONS.with_suffix('.json.tmp');save(temp,operations);temp.replace(OPERATIONS)
    if states!=json.loads(STATES.read_text(encoding='utf-8')):
        temp=STATES.with_suffix('.json.tmp');save(temp,states);temp.replace(STATES)


def now(): return datetime.now(TZ).isoformat(timespec="seconds")
def ensure():
    DATA.mkdir(parents=True,exist_ok=True)
    for p in (OFFERS,TARGETS,STATES,OPERATIONS):
        if not p.exists(): p.write_text("{}",encoding="utf-8")
def load(p):
    ensure()
    try:
        value=json.loads(p.read_text(encoding="utf-8"))
        return normalize_operation_times(value) if p==OPERATIONS else value
    except: return {}
def save(p,d): p.write_text(json.dumps(d,ensure_ascii=False,indent=2,sort_keys=True),encoding="utf-8")
def persist(msg):
    if os.environ.get("ALLIANCE_OPS_ENABLE_GIT_PERSIST", "0") != "1":
        return
    subprocess.run(["git","config","user.name","github-actions[bot]"])
    subprocess.run(["git","config","user.email","41898282+github-actions[bot]@users.noreply.github.com"])
    subprocess.run(["git","add",str(DATA)])
    if not subprocess.run(["git","status","--porcelain",str(DATA)],capture_output=True,text=True).stdout.strip(): return
    if subprocess.run(["git","commit","-m",msg]).returncode: return
    if subprocess.run(["git","pull","--rebase","origin","main"]).returncode: return
    subprocess.run(["git","push","origin","HEAD:main"])

def latest_snapshot():
    files=[]
    for p in SNAPSHOTS.glob("**/map_*.sql"):
        m=re.fullmatch(r"map_(\d{4}-\d{2}-\d{2})\.sql",p.name)
        if m: files.append((m.group(1),p))
    return max(files,key=lambda x:x[0])[1] if files else None

def split_sql(s):
    out=[]; cur=[]; q=None; esc=False
    for c in s:
        if esc: cur.append(c); esc=False; continue
        if c=="\\": cur.append(c); esc=True; continue
        if q:
            cur.append(c)
            if c==q:q=None
        elif c in "'\"": q=c;cur.append(c)
        elif c==",": out.append("".join(cur).strip());cur=[]
        else: cur.append(c)
    out.append("".join(cur).strip()); return out
def clean(v):
    v=v.strip()
    if len(v)>1 and v[0]=="'" and v[-1]=="'": v=v[1:-1].replace("\\'","'").replace("\\\\","\\")
    return html.unescape(v)
def rows(raw):
    pat=re.compile(r"^\s*INSERT\s+INTO\s+\x60?x_world\x60?\s+VALUES\s*(.*?)\s*;?\s*$",re.I)
    for line in raw.splitlines():
        m=pat.match(line)
        if not m: continue
        s=m.group(1);cur=[];depth=0;q=None;esc=False
        for c in s:
            if esc:
                if depth:cur.append(c)
                esc=False;continue
            if c=="\\": 
                if depth:cur.append(c)
                esc=True;continue
            if q:
                if depth:cur.append(c)
                if c==q:q=None
                continue
            if c in "'\"":
                q=c
                if depth:cur.append(c)
            elif c=="(":
                if depth==0:cur=[]
                depth+=1
                if depth>1:cur.append(c)
            elif c==")":
                depth-=1
                if depth==0: yield "".join(cur)
                elif depth>0:cur.append(c)
            elif depth:cur.append(c)
def village_at(x,y):
    p=latest_snapshot()
    if not p:return None,None
    for r in rows(p.read_text(encoding="utf-8",errors="replace")):
        try:
            a=split_sql(r)
            if len(a)<11 or int(clean(a[1]))!=x or int(clean(a[2]))!=y:continue
            return {"x":x,"y":y,"tribe_id":int(clean(a[3])),"village_id":int(clean(a[4])),"village":clean(a[5]),"player_id":int(clean(a[6])),"player":clean(a[7]),"alliance_id":int(clean(a[8])),"alliance":clean(a[9]),"population":int(clean(a[10]))},p
        except: pass
    return None,p

def api(method,payload=None):
    r=requests.post(f"https://api.telegram.org/bot{TOKEN}/{method}",json=payload or {},timeout=40,proxies=TELEGRAM_PROXIES);r.raise_for_status()
    d=r.json()
    if not d.get("ok"):raise RuntimeError(d)
    return d.get("result")
def send(cid,text,kb=None):
    if TIME_NOTE not in text:text+="\n\n"+TIME_NOTE
    p={"chat_id":cid,"text":text,"parse_mode":"HTML"}
    if kb:p["reply_markup"]={"inline_keyboard":kb}
    return api("sendMessage",p)
def btn(t,d):return {"text":t,"callback_data":d}
def state(uid,step=None,data=None):
    s=load(STATES);k=str(uid)
    if step:s[k]={"step":step,"data":data or {},"updated_at":now()}
    else:s.pop(k,None)
    save(STATES,s)
def getstate(uid):return load(STATES).get(str(uid))
def coords(t):
    m=re.fullmatch(r"\s*(-?\d{1,3})(?:\s*[|,]\s*|\s+)(-?\d{1,3})\s*",t)
    if not m:return None
    x,y=map(int,m.groups())
    return (x,y) if -200<=x<=200 and -200<=y<=200 else None
def template(tid):return "\n".join(f"{x}:" for x in TROOPS.get(tid,[]))
def parse_army(text,tid):
    names=TROOPS.get(tid,[]); found={}
    for line in text.splitlines():
        if ":" not in line:continue
        n,v=line.split(":",1); n=n.strip()
        if n not in names:continue
        v=re.sub(r"[\s,.]","",v)
        if not v:v="0"
        if not v.isdigit():return None,f"Некорректное число для «{n}»."
        found[n]=int(v)
    if not found:return None,"Не удалось распознать шаблон войск."
    return {n:found.get(n,0) for n in names},None
def offer_owner(key,offer):
    return str(offer.get('telegram_id') or str(key).split('_',1)[0])


def active_offers():
    return {key:o for key,o in load(OFFERS).items() if not o.get('deleted_at')}


def own_offers(uid):
    return {key:o for key,o in active_offers().items() if offer_owner(key,o)==str(uid)}


def owns_offer(uid,key):
    offer=active_offers().get(key)
    return offer if offer and offer_owner(key,offer)==str(uid) else None


def op_owner(op,key):
    return offer_owner(key,op.get('offers',{}).get(str(key),{}))


def op_members(op):
    return {op_owner(op,key) for key in op.get('offers',{})}


def same_origin(a,b):
    return (int(a['x']),int(a['y']))==(int(b['x']),int(b['y']))


def current_plan_offer(op,key):
    snapshot=op['offers'][key];current=load(OFFERS).get(key,{})
    return current if current and same_origin(current,snapshot) else snapshot


def village_label(o):
    return f"{o.get('player','?')} · {o['x']}|{o['y']}"


def village_error(uid,v,key=None):
    for other,o in active_offers().items():
        if other!=key and same_origin(o,v):return 'Эта офф-деревня уже зарегистрирована.'
    return None


def personal_villages(cid,uid,action='view'):
    offers=own_offers(uid)
    buttons=[[btn(village_label(o),f'village:{action}:{key}')] for key,o in offers.items()]
    buttons.extend([[btn('➕ Добавить офф-деревню','village:add')],[btn('⬅️ Меню','menu')]])
    send(cid,'🏘 <b>Мои офф-деревни</b>\nВыберите деревню. Войска, арена и сейв-точки хранятся отдельно.',buttons)


def personal_village(cid,uid,key):
    offer=owns_offer(uid,key)
    if not offer:send(cid,'Деревня недоступна.');return
    point_text='\n\n🛡 Сейв-точки: '+(', '.join(f"{p[0]}|{p[1]}" for p in offer.get('save_points',[])) or 'не заданы')
    send(cid,fmt_offer(offer)+point_text,[[btn('🔄 Войска',f'village:army:{key}'),btn('🏟 Арена',f'village:arena:{key}')],
         [btn('🛡 Сейв-точки',f'village:points:{key}')],
         [btn('✏️ Изменить координаты',f'village:coords:{key}')],[btn('🗑 Удалить деревню',f'village:delete:{key}')],
         [btn('⬅️ Мои деревни','village:list')]])


# Every management callback names an existing operation in its second field.
OP_MANAGEMENT_ACTIONS=frozenset({
 'otrmask','otrmyes',
 'op','oormask','oormyes','oofferpick','oofferjoin','opdepartures','optargets','opoffers','optarget','opoffer','oa','owaves','oedit','otypes','otype',
 'owadd','owdel','odelask','odelyes','oofferedit','oretime','oall','obulk','oadd',
 'oaddoffer','oaddtarget','opdeleteask','opdeleteyes','odraftask','odraftyes','publish','progress'})


def operation_is_owned(uid,op):
    return bool(op) and op.get('created_by') is not None and str(op['created_by'])==str(uid)


def owned_operation(uid,oid):
    op=load(OPERATIONS).get(oid)
    return op if operation_is_owned(uid,op) else None


def menu(uid):
    rows=[[btn("📋 Мой план","mine:list")],[btn("🏘 Мои офф-деревни","village:list")],
          [btn("⚔️ Мои операции","ops:list"),btn("📝 Создать операцию","ops:new")]]
    rows += [[btn("🎯 База целей","targets:list"),btn("➕ Добавить цель","targets:add")]]
    if uid in COORDINATORS:rows += [[btn("⚔️ Список офферов","offers:ro:list")]]
    return rows
def fmt_offer(o):
    lines=[f"⚔️ <b>Мой офф</b>","",f"Игрок: <b>{html.escape(o['player'])}</b>",f"Деревня: <b>{html.escape(o['village'])}</b>",f"Координаты: <code>{o['x']}|{o['y']}</code>",f"Раса: <b>{TRIBES.get(o['tribe_id'],'Неизвестно')}</b>",f"Арена: <b>{o['arena']}</b>","","<b>Войска:</b>"]
    tr=o.get("army",{}).get("troops",{})
    lines += [f"{html.escape(n)} — {v:,}".replace(",", " ") for n,v in tr.items() if v]
    if not any(tr.values()):lines.append("—")
    lines.append(f"\nОбновлено: <code>{o.get('army',{}).get('updated_at','—')}</code>")
    return "\n".join(lines)
def start(cid,uid):
    offers=own_offers(uid)
    detail="Офф-деревень: <b>"+str(len(offers))+"</b>\n"+"\n".join(html.escape(village_label(o)) for o in offers.values()) if offers else "Вы можете создать свою операцию или зарегистрировать офф-деревню."
    send(cid,"⚔️ <b>Центр операций альянса</b>\n\n"+detail+"\n\nВыберите действие:",menu(uid))
def coordinator_offer_list(cid):
    offers=active_offers()
    if not offers:
        send(cid,"⚔️ Зарегистрированных офферов пока нет.",[[btn("⬅️ Меню","menu")]])
        return
    rows=[]
    for uid,o in sorted(offers.items(),key=lambda kv:kv[1].get("player","").lower()):
        troops=o.get("army",{}).get("troops",{})
        total=sum(int(v) for v in troops.values())
        name=html.escape(str(o.get("player","?")))
        rows.append([btn(f"{name} {o['x']}|{o['y']} · {total:,} войск".replace(","," "),f"offers:ro:view:{uid}")])
    rows.append([btn("⬅️ Меню","menu")])
    send(cid,f"⚔️ <b>Офф-деревни игроков</b>\nВсего деревень: {len(offers)}. Выберите деревню для просмотра армии.",rows)

def coordinator_offer_view(cid,offer_uid):
    o=load(OFFERS).get(str(offer_uid))
    if not o:
        send(cid,"❌ Оффер не найден.");return
    send(cid,fmt_offer(o),[[btn("⬅️ К списку офферов","offers:ro:list")]])

def list_targets(cid):
    ts=refresh_target_alliances()
    if not ts:send(cid,"🎯 <b>База целей пуста.</b>",[[btn("➕ Добавить цель","targets:add")],[btn("⬅️ Меню","menu")]]);return
    rows=[[btn(f"{k} · {v.get('player','?')} · {target_alliance_name(v)} · {v.get('type','?')}",f"target:{k}")] for k,v in ts.items()]
    rows.append([btn("➕ Добавить цель","targets:add"),btn("⬅️ Меню","menu")]);send(cid,f"🎯 <b>База целей</b>\nВсего: {len(ts)}",rows)
def show_target(cid,key):
    t=load(TARGETS).get(key)
    if not t:send(cid,"❌ Цель не найдена.");return
    txt=f"🎯 <b>{html.escape(t['village'])}</b>\nКоординаты: <code>{key}</code>\nИгрок: <b>{html.escape(t['player'])}</b>\nАльянс: <b>{html.escape(target_alliance_name(t))}</b>\nНаселение: {t.get('population','—')}\nРаса: {TRIBES.get(t.get('tribe_id'),'Неизвестно')}\n\nТип: <b>{t.get('type','Не определено')}</b>\nВажность: <b>{t.get('priority',1)}/5</b>\nКомментарий: {html.escape(t.get('comment') or '—')}"
    rows=[[btn("🏷 Тип",f"targettype:{key}"),btn("⭐ Важность",f"targetprio:{key}")],[btn("📝 Комментарий",f"targetcomment:{key}"),btn("🗑 Удалить",f"targetdelete:{key}")],[btn("⬅️ К списку","targets:list")]]
    if cid not in COORDINATORS:rows=[[btn("⬅️ К списку","targets:list")]]
    send(cid,txt,rows)

def op_dt(text):
    for fmt in ("%d.%m.%Y %H:%M:%S","%d.%m.%Y %H:%M"):
        try:wall=datetime.strptime(text,fmt)
        except ValueError:continue
        choices=set()
        for fold in (0,1):
            stamp=wall.replace(tzinfo=TZ,fold=fold).timestamp()
            if datetime.fromtimestamp(stamp,TZ).replace(tzinfo=None)==wall:choices.add(stamp)
        return datetime.fromtimestamp(choices.pop(),TZ) if len(choices)==1 else None
    return None


def op_id():
    return uuid.uuid4().hex[:16]

def op_attack_defaults(mode,target):
    if mode=="spam":
        waves=4 if target.get("type")=="Столица" else 2
        return {"mode":"spam","waves":waves,"wave_plan":[{"text":"19 любых юнитов + 1 катапульта"} for _ in range(waves)],"comment":""}
    if mode=="destroy":
        return {"mode":"destroy","waves":4,"wave_plan":[
            {"text":"весь офф + все тараны + 220 катапульт"},
            {"text":"100 пехоты + 220 катапульт"},
            {"text":"100 пехоты + 220 катапульт"},
            {"text":"100 пехоты + 220 катапульт"}],"comment":""}
    return {"mode":"capture","waves":2,"wave_plan":[
        {"text":"весь офф"},
        {"text":"вожди + сопровождение + катапульты"}],"comment":""}

def op_mode_name(mode):
    return {"spam":"🟡 Спам","destroy":"🔥 Уничтожение","capture":"👑 Захват"}.get(mode,mode)

WAVE_LEGEND='🟣2 — 2 волны · 🟡4 — 4 волны · ⚪ — другое число волн'


def attack_wave_count(attack):
    plan=attack.get('wave_plan')
    if isinstance(plan,list):return len(plan)
    return int(attack.get('waves',0) or 0)


def wave_badge(attack):
    count=attack_wave_count(attack)
    return {2:'🟣2',4:'🟡4'}.get(count,f'⚪{count}')


def attack_caption(attack):
    mode='Спам' if attack.get('mode')=='spam' else op_mode_name(attack.get('mode','?'))
    return f'Волн: {wave_badge(attack)} · {mode}'


def wave_button(text,data,attack):
    return btn(f'{wave_badge(attack)} {text}',data)


def op_summary(op):
    return (f"📝 <b>{html.escape(op['name'])}</b>\n"
            f"Статус: <b>{'ОПУБЛИКОВАНА' if op.get('status')=='published' else 'ЧЕРНОВИК'}</b>\n\n"+
            (f"🏳️ Альянс целей: <b>{html.escape(op['enemy_alliance'])}</b>\n" if op.get("enemy_alliance") else "")+
            f"🕐 Базовый приход: <code>{html.escape(op['arrival'])}</code>\n"
            f"🐎 Базовая скорость: <b>{op['base_speed']}</b>\n"
            f"👥 Офферов: <b>{len(op['offers'])}</b>\n"
            f"🎯 Целей: <b>{len(op['targets'])}</b>\n"
            f"⚔️ Отправок: <b>{len(op['attacks'])}</b>")

def list_ops(cid):
    ops={oid:op for oid,op in load(OPERATIONS).items() if operation_is_owned(cid,op)}
    if not ops:
        send(cid,"⚔️ <b>Операций пока нет.</b>",[[btn("📝 Создать черновик","ops:new")],[btn("⬅️ Меню","menu")]]);return
    rows=[[btn(f"{'📢' if v.get('status')=='published' else '📝'} {v.get('name',k)}",f"op:{k}")] for k,v in reversed(list(ops.items()))]
    rows += [[btn("📝 Создать черновик","ops:new")],[btn("⬅️ Меню","menu")]]
    send(cid,f"⚔️ <b>Мои операции</b>\nВсего: {len(ops)}",rows)

def show_op(cid,oid):
    sync_operation_arenas(oid,cid)
    if not owned_operation(cid,oid):send(cid,'⛔ Операция недоступна.');return
    op=load(OPERATIONS).get(oid)
    if not op:send(cid,"❌ Операция не найдена.");return
    buttons=[[btn("📊 Готовность и прогресс",f"progress:{oid}")],
             [btn("🕐 Все отправки по времени",f"opdepartures:{oid}:0")],
             [btn("🎯 По целям",f"optargets:{oid}"),btn("👥 По офферам",f"opoffers:{oid}")],
             [btn("🕒 Изменить время операции",f"oretime:{oid}"),btn("➕ Отправка",f"oadd:{oid}")],
             ]
    if op.get("status")=="published":
        buttons.insert(0,[btn("📣 Повторить рассылку",f"publish:{oid}")])
        buttons.append([btn("🗑 Удалить операцию",f"opdeleteask:{oid}")])
    else:
        buttons.insert(0,[btn("📢 Опубликовать",f"publish:{oid}")])
        buttons.append([btn("🗑 Удалить черновик",f"odraftask:{oid}")])
    buttons.append([btn("➕ Добавить офф-деревню",f"oofferpick:{oid}:0")])
    buttons.append([btn("⬅️ Операции","ops:list")])
    send(cid,op_summary(op),buttons)

def op_targets(cid,oid):
    if not owned_operation(cid,oid):send(cid,'⛔ Операция недоступна.');return
    op=load(OPERATIONS).get(oid)
    if not op:return
    rows=[]
    for k,t in op["targets"].items():
        n=sum(1 for a in op["attacks"].values() if a["target_key"]==k)
        rows.append([btn(f"{op_mode_name(t['mode'])} · {k} · {n}",f"optarget:{oid}:{k}")])
    rows.append([btn("⬅️ К операции",f"op:{oid}")])
    send(cid,"🎯 <b>Цели операции</b>",rows)

def op_offers(cid,oid):
    if not owned_operation(cid,oid):send(cid,'⛔ Операция недоступна.');return
    op=load(OPERATIONS).get(oid)
    if not op:return
    rows=[]
    for uid,o in op["offers"].items():
        n=sum(1 for a in op["attacks"].values() if a["offer_id"]==uid)
        off=o.get("offset",0); sign="+" if off>0 else ""
        rows.append([btn(f"{village_label(o)} · {sign}{off} сек · {n}",f"opoffer:{oid}:{uid}")])
    if op.get("status") in ("draft","published"):rows.append([btn("➕ Добавить офф-деревню",f"oofferpick:{oid}:0")])
    rows.append([btn("⬅️ К операции",f"op:{oid}")])
    send(cid,"👥 <b>Офферы операции</b>",rows)

def op_target_detail(cid,oid,key):
    if not owned_operation(cid,oid):send(cid,'⛔ Операция недоступна.');return
    op=load(OPERATIONS).get(oid)
    if not op or key not in op["targets"]:return
    t=op["targets"][key]; lines=[f"🎯 <b>{html.escape(t['player'])} — {html.escape(t['village'])}</b>",f"<code>{key}</code> · {op_mode_name(t['mode'])}",""]
    for a in op["attacks"].values():
        if a["target_key"]==key:
            lines.append(f"• {html.escape(a['offer_player'])}: <code>{a['arrival']}</code> · {a['waves']} волн")
    rows=[[btn(f"⚔️ {a['offer_player']} · {a['arrival']}",f"oa:{oid}:{a['id']}")] for a in op["attacks"].values() if a["target_key"]==key]
    if op.get('status') in ('draft','published'):
        rows.append([btn('🗑 Убрать цель у всех офферов',f'otrmask:{oid}:{key}')])
    rows.append([btn("⬅️ К целям",f"optargets:{oid}")]);send(cid,"\n".join(lines),rows)

def op_offer_detail(cid,oid,uid):
    if not owned_operation(cid,oid):send(cid,'⛔ Операция недоступна.');return
    op=load(OPERATIONS).get(oid)
    if not op or uid not in op["offers"]:return
    o=op["offers"][uid]; lines=[f"👤 <b>{html.escape(o['player'])}</b>",f"Смещение: <b>{o['offset']:+d} сек</b>",""]
    lines.insert(1,WAVE_LEGEND)
    for a in op["attacks"].values():
        if a["offer_id"]==uid:
            t=op["targets"][a["target_key"]]
            lines.append(f"• {op_mode_name(a['mode'])} <code>{a['target_key']}</code> {html.escape(t['player'])} — <code>{a['arrival']}</code> · {a['waves']} волн")
    rows=[[wave_button(f"{op_mode_name(a['mode'])} · {a['target_key']} · {a['arrival']}",f"oa:{oid}:{a['id']}",a)] for a in op["attacks"].values() if a["offer_id"]==uid]
    if op.get("status") in ("draft","published"):rows.append([btn("🗑 Убрать офф-деревню из операции",f"oormask:{oid}:{uid}")])
    rows += [[btn("⏱ Смещение оффера",f"oofferedit:{oid}:{uid}")],[btn("⬅️ К офферам",f"opoffers:{oid}")]];send(cid,"\n".join(lines),rows)

def op_offer_picker(cid,d):
    offers=active_offers(); selected=set(d.get("offers",[])); rows=[]
    for uid,o in offers.items():
        mark="✅" if uid in selected else "⬜"
        rows.append([btn(f"{mark} {o['player']} {o['x']}|{o['y']}",f"opofftoggle:{uid}")])
    rows.append([btn(f"➡️ Далее ({len(selected)})","opoffdone")])
    send(cid,"👥 <b>Выберите офферов операции</b>",rows)

def target_alliance_key(target):
    if target.get('map_missing') or target.get('alliance_id') is None:return 'unknown'
    return str(int(target['alliance_id']))


def target_alliance_name(target):
    key=target_alliance_key(target)
    if key=='unknown':return 'Альянс не определён'
    if key=='0':return 'Без альянса'
    return target.get('alliance') or f'Альянс #{key}'


def refresh_target_alliances():
    targets=load(TARGETS);snapshot=latest_snapshot()
    if not targets or not snapshot:return targets
    # Parse and validate the whole snapshot before removing anything. An empty,
    # unreadable or truncated map must never be interpreted as an empty world.
    try:
        raw=snapshot.read_text(encoding='utf-8-sig')
        inserts=[line for line in raw.splitlines() if re.match(r'^\s*INSERT\s+INTO\s+`?x_world`?\s+VALUES\b',line,re.I)]
        if not inserts or any(not line.rstrip().endswith(';') for line in inserts):
            raise ValueError('Incomplete world snapshot')
        world={}
        for line in inserts:
            quote=None;escaped=False;depth=0
            for char in line:
                if escaped:escaped=False;continue
                if char=='\\':escaped=True;continue
                if quote:
                    if char==quote:quote=None
                elif char in "'\"":quote=char
                elif char=='(':depth+=1
                elif char==')':
                    depth-=1
                    if depth<0:raise ValueError('Unbalanced world row')
            if quote or escaped or depth:raise ValueError('Unfinished world row')
            parsed=list(rows(line))
            if not parsed:raise ValueError('Invalid world rows')
            for row in parsed:
                a=split_sql(row)
                if len(a)<11:raise ValueError('Incomplete village row')
                x,y=int(clean(a[1])),int(clean(a[2]))
                if not -200<=x<=200 or not -200<=y<=200:raise ValueError('Invalid coordinates')
                key=f'{x}|{y}'
                if key in world:raise ValueError('Duplicate village coordinates')
                world[key]={'alliance_id':int(clean(a[8])),'alliance':clean(a[9]),
                            'player_id':int(clean(a[6])),'player':clean(a[7]),'village_id':int(clean(a[4])),
                            'village':clean(a[5]),'alliance_snapshot':snapshot.name,'map_missing':False}
    except (OSError,UnicodeError,ValueError,IndexError,TypeError):
        print('Target refresh skipped: world snapshot could not be validated',flush=True)
        return targets
    changed=False;removed=0
    for key in list(targets):
        if key not in world:
            del targets[key];changed=True;removed+=1
        elif any(targets[key].get(k)!=v for k,v in world[key].items()):
            targets[key].update(world[key]);changed=True
    if changed:
        save(TARGETS,targets);persist('Refresh target alliances and remove villages missing from world snapshot')
    if removed:print(f'Removed {removed} missing villages from target database',flush=True)
    return targets


def selected_alliance_keys(data):
    # Keep unfinished single-alliance wizards compatible with the new menu.
    if 'alliance_keys' in data:return set(map(str,data['alliance_keys']))
    return {str(data['alliance_key'])} if data.get('alliance_key') is not None else set()


def op_alliance_picker(cid,d,message_id=None):
    targets=refresh_target_alliances();groups={};selected=selected_alliance_keys(d)
    for target in targets.values():
        key=target_alliance_key(target)
        group=groups.setdefault(key,{'name':target_alliance_name(target),'count':0});group['count']+=1
    buttons=[[btn(f"{'✅' if key in selected else '⬜'} {g['name']} · {g['count']} целей",f'opalliance:{key}')]
             for key,g in sorted(groups.items(),key=lambda item:(item[0] in ('0','unknown'),item[1]['name'].casefold(),item[0]))]
    text='🏳️ <b>Выберите альянсы для операции</b>\nОтметьте один или несколько альянсов и нажмите «Дальше». Затем будут доступны цели всех выбранных альянсов. Данные — по последнему доступному снимку карты.'
    if not groups:text+='\n\nБаза целей пуста. Сначала добавьте цели.'
    if selected:buttons.append([btn(f'Дальше ➡️ ({len(selected)})','opalliance:done')])
    buttons.append([btn('⬅️ Меню','menu')])
    if message_id is None:send(cid,text,buttons)
    else:api('editMessageText',{'chat_id':cid,'message_id':message_id,'text':text,'parse_mode':'HTML','reply_markup':{'inline_keyboard':buttons}})


def op_target_picker(cid,d):
    if not selected_alliance_keys(d):op_alliance_picker(cid,d);return
    targets=load(TARGETS);selected=d.get('targets',{});buttons=[]
    eligible={k:t for k,t in targets.items() if target_alliance_key(t) in selected_alliance_keys(d)}
    for key,target in eligible.items():
        mark={'spam':'🟡','destroy':'🔥','capture':'👑'}.get(selected.get(key),'⬜')
        buttons.append([btn(f"{mark} {key} · {target.get('player','?')} · {target.get('type','?')}",f'optargetpick:{key}')])
    count=len(set(selected)&set(eligible))
    buttons.append([btn(f'⚙️ Создать черновик ({count})','opgenerate')])
    buttons.append([btn('🏳️ Изменить альянсы','opalliance:back')])
    send(cid,f"🎯 <b>Цели операции · {html.escape(d.get('alliance_name',''))}</b>\n\nНажмите, чтобы добавить или убрать цель. Все отправки создаются как спам; реальные атаки можно настроить в черновике."+('\nЦелей в этой группе больше нет — выберите другие альянсы.' if not eligible else ''),buttons)

def generate_op(uid,d):
    offers_all=active_offers(); targets_all=refresh_target_alliances(); oid=op_id()
    if not d.get('targets') or not selected_alliance_keys(d) or any(key not in targets_all or target_alliance_key(targets_all[key]) not in selected_alliance_keys(d) for key in d['targets']):
        raise ValueError('Цели или их альянс изменились. Выберите альянсы и цели заново.')
    if any(key not in offers_all for key in d.get('offers',[])):raise ValueError('Офф-деревня удалена. Выберите офферов заново.')
    arrival_dt=server_datetime(d["arrival_iso"])
    op={"id":oid,"name":"Операция","status":"draft","arrival":arrival_dt.strftime("%d.%m.%Y %H:%M:%S"),
        "time_zone":"Europe/London","arrival_iso":d["arrival_iso"],"base_speed":d["base_speed"],"created_at":now(),"created_by":uid,"creator_username":d.get("creator_username"),"creator_name":d.get("creator_name"),
        "comment":"","offers":{},"targets":{},"attacks":{},
        "enemy_alliance_keys":sorted(selected_alliance_keys(d)),"enemy_alliance_key":next(iter(selected_alliance_keys(d))) if len(selected_alliance_keys(d))==1 else None,"enemy_alliance":d.get("alliance_name","")}
    for ouid in d["offers"]:
        o=offers_all[ouid]
        op["offers"][ouid]={"telegram_id":int(offer_owner(ouid,o)),"save_points":o.get("save_points",[]),"player":o["player"],"village":o["village"],"x":o["x"],"y":o["y"],"arena":o["arena"],
                            "offset":int(d["offsets"].get(ouid,0)),"army_snapshot":o.get("army",{})}
    for key in d["targets"]:
        t=targets_all[key]; op["targets"][key]={**t,"mode":"spam"}
    i=0
    for ouid,o in op["offers"].items():
        for key,t in op["targets"].items():
            i+=1; defaults=op_attack_defaults(t["mode"],t)
            actual=shift_seconds(arrival_dt,o["offset"])
            op["attacks"][str(i)]={"id":str(i),"offer_id":ouid,"offer_player":o["player"],"target_key":key,
                "mode":defaults["mode"],"waves":defaults["waves"],"wave_plan":defaults["wave_plan"],
                "comment":"","offset":o["offset"],"arrival":actual.strftime("%d.%m.%Y %H:%M:%S"),
                "arrival_iso":actual.isoformat(),"speed":d["base_speed"],"arena":o["arena"]}
    ops=load(OPERATIONS)
    numbers=[int(m.group(1)) for existing in ops.values()
             if operation_is_owned(uid,existing) and (m:=re.fullmatch(r"Операция №(\d+)",str(existing.get("name",""))))]
    op["name"]=f"Операция №{max(numbers,default=0)+1}"
    while oid in ops:oid=op_id()
    op['id']=oid
    ops[oid]=op;save(OPERATIONS,ops);persist("Create alliance ops draft")
    return oid

def op_store(ops, msg="Edit operation"):
    previous=load(OPERATIONS)
    save(OPERATIONS,ops)
    persist(msg)
    for oid,op in ops.items():
        old=previous.get(oid,{})
        if old.get("status")!="published" or op.get("status")!="published":continue
        for uid in op_members(op)|op_members(old):
            old_jobs={k:v for k,v in old.get("attacks",{}).items() if op_owner(old,v.get("offer_id"))==uid}
            new_jobs={k:v for k,v in op.get("attacks",{}).items() if op_owner(op,v.get("offer_id"))==uid}
            if {k:{f:v for f,v in a.items() if f not in ("sent_at","reminder_sent_for","reminder_minute_sent_for")} for k,a in old_jobs.items()}=={k:{f:v for f,v in a.items() if f not in ("sent_at","reminder_sent_for","reminder_minute_sent_for")} for k,a in new_jobs.items()} or not (old_jobs or new_jobs):continue
            op.setdefault("ready",{}).pop(uid,None)
            for a in new_jobs.values():
                a.pop("reminder_sent_for",None)
                a.pop("reminder_minute_sent_for",None)
            removed=[village_label(offer) for key,offer in old.get('offers',{}).items()
                     if op_owner(old,key)==uid and key not in op.get('offers',{})]
            text=f"⚠️ <b>{html.escape(op['name'])}: план изменён!</b>"
            if removed:
                text+='\nИз плана убраны офф-деревни: '+html.escape(', '.join(removed))+'. Не отправляйте войска по их прежним заданиям. Уже отправленные в игре войска не отозваны.'
            removed_targets=sorted({a['target_key'] for a in old_jobs.values()
                                    if a.get('target_key') in old.get('targets',{}) and a['target_key'] not in op.get('targets',{})})
            if removed_targets:
                text+='\nИз плана убраны цели: '+html.escape(', '.join(removed_targets))+'. Не отправляйте войска по прежним заданиям на эти деревни. Уже отправленные в игре войска не отозваны.'
            if new_jobs:
                text+='\nПроверьте задания и повторно подтвердите готовность.'
                buttons=[[btn("📋 Открыть план",f"mine:op:{oid}")]]
            else:
                text+='\nАктивных заданий в этой операции у вас больше нет.'
                buttons=None
            try:send(int(uid),text,buttons)
            except Exception as e:print("change notification error",uid,repr(e),flush=True)
    save(OPERATIONS,ops)

def sync_operation_arenas(oid=None,owner_id=None):
    offers=active_offers();ops=load(OPERATIONS);changed=False;affected=0
    for key,op in ops.items():
        if op.get('status') not in ('draft','published') or (oid is not None and str(key)!=str(oid)):continue
        if owner_id is not None and not operation_is_owned(owner_id,op):continue
        for offer_key,stored in op.get('offers',{}).items():
            current=offers.get(offer_key)
            if not current or not same_origin(current,stored):continue
            try:old_arena=int(stored.get('arena',0));arena=int(current['arena'])
            except (ValueError,TypeError,KeyError):continue
            if not 0<=arena<=20 or old_arena==arena:continue
            stored['arena']=arena;changed=True
            for attack in op.get('attacks',{}).values():
                if str(attack.get('offer_id'))!=str(offer_key) or attack.get('sent_at'):continue
                # A village-level update is authoritative for every pending
                # send, including routes with an older manual arena value.
                attack.pop('arena_override',None)
                if int(attack.get('arena',old_arena))==arena:continue
                attack['arena']=arena;attack.pop('reminder_sent_for',None);attack.pop('reminder_minute_sent_for',None);affected+=1
    if changed:op_store(ops,'Refresh registered village arenas in draft and published operations')
    return affected


def op_retime(op,a):
    dt=shift_seconds(server_datetime(op["arrival_iso"]),int(a["offset"]))
    a["arrival_iso"]=dt.isoformat()
    a["arrival"]=dt.strftime("%d.%m.%Y %H:%M:%S")

def op_travel(a,op):
    o=op["offers"][a["offer_id"]];t=op["targets"][a["target_key"]]
    dx=abs(int(o["x"])-int(t["x"]));dy=abs(int(o["y"])-int(t["y"]))
    dist=((min(dx,401-dx))**2+(min(dy,401-dy))**2)**0.5
    speed=float(a["speed"]);arena=int(a["arena"])
    # Travian tournament square: beyond 20 fields, speed rises by 20% per arena level.
    if speed<=0:return None,dist
    hours=min(dist,20)/speed+max(0,dist-20)/(speed*(1+arena*.2))
    return shift_seconds(server_datetime(a["arrival_iso"]),-round(hours*3600)),dist

def operation_departures(op):
    result=[]
    for aid,attack in op.get('attacks',{}).items():
        try:
            departure,_=op_travel(attack,op)
            if departure is not None:
                departure=departure.replace(tzinfo=TZ) if departure.tzinfo is None else departure.astimezone(TZ)
        except (KeyError,ValueError,TypeError,OverflowError,ZeroDivisionError):departure=None
        result.append((departure,str(aid),attack))
    return sorted(result,key=lambda item:(item[0].timestamp() if item[0] else float('inf'),item[1]))


def op_departures(cid,oid,page=0,message_id=None):
    sync_operation_arenas(oid,cid)
    op=owned_operation(cid,oid)
    if not op:send(cid,'⛔ Операция недоступна.');return
    jobs=operation_departures(op);page_size=5;pages=max(1,(len(jobs)+page_size-1)//page_size)
    page=max(0,min(int(page),pages-1))
    lines=['🕐 <b>Все отправки по времени</b>',html.escape(str(op.get('name','Операция'))[:40]),
           'От самой ранней к самой поздней.',TIME_NOTE,WAVE_LEGEND,f'Всего: {len(jobs)} · Страница {page+1}/{pages}','']
    buttons=[]
    for index,(departure,aid,attack) in enumerate(jobs[page*page_size:(page+1)*page_size],page*page_size+1):
        offer=op.get('offers',{}).get(attack.get('offer_id'),{})
        target=op.get('targets',{}).get(attack.get('target_key'),{})
        origin=f"{offer.get('x','?')}|{offer.get('y','?')}"
        destination=f"{target['x']}|{target['y']}" if 'x' in target and 'y' in target else str(attack.get('target_key','?'))
        clock=departure.strftime('%d.%m.%Y %H:%M:%S') if departure else '⚠️ Время не рассчитано'
        player=html.escape(str(offer.get('player') or attack.get('offer_player') or '?')[:40])
        target_player=html.escape(str(target.get('player') or '?')[:40])
        mode=html.escape(str(op_mode_name(attack.get('mode','?')))[:40])
        lines.extend([f'<b>{index}. {clock}</b>'+(' · ✅ Отправлено' if attack.get('sent_at') else ''),
                      f'👤 {player} · 🏘 <code>{html.escape(origin)}</code>',
                      f'🎯 <code>{html.escape(destination)}</code> — {target_player}',
                      f'{mode} · Волн: {int(attack.get("waves",0) or 0)}',''])
        buttons.append([wave_button(f'{index}. '+(departure.strftime('%H:%M:%S') if departure else '⚠️')+f' · {origin} → {destination}',f'oa:{oid}:{aid}',attack)])
    if not jobs:lines.append('В операции пока нет отправок.')
    nav=[]
    if page:nav.append(btn('⬅️ Назад',f'opdepartures:{oid}:{page-1}'))
    if page+1<pages:nav.append(btn('Дальше ➡️',f'opdepartures:{oid}:{page+1}'))
    if nav:buttons.append(nav)
    buttons.append([btn('🔄 Обновить',f'opdepartures:{oid}:{page}')])
    buttons.append([btn('⬅️ К операции',f'op:{oid}')])
    text='\n'.join(lines)
    if message_id is None:send(cid,text,buttons)
    else:
        try:api('editMessageText',{'chat_id':cid,'message_id':message_id,'text':text,'parse_mode':'HTML','reply_markup':{'inline_keyboard':buttons}})
        except requests.HTTPError as error:
            response=getattr(error,'response',None)
            if response is not None and response.status_code==400 and 'message is not modified' in response.text.lower():return
            raise


def op_attack_view(cid,oid,aid):
    if not owned_operation(cid,oid):send(cid,'⛔ Операция недоступна.');return
    op=load(OPERATIONS).get(oid)
    if not op or aid not in op["attacks"]:send(cid,"❌ Отправка не найдена.");return
    a=op["attacks"][aid];t=op["targets"][a["target_key"]];o=op["offers"][a["offer_id"]]
    departure,dist=op_travel(a,op)
    waves="\n".join(f"{i}. {html.escape(w.get('text','—'))}" for i,w in enumerate(a["wave_plan"],1))
    msg=(f"⚔️ <b>{html.escape(o['player'])} → {html.escape(t['player'])}</b>\n"
         f"🎯 <code>{a['target_key']}</code> · {attack_caption(a)}\n"
         f"Приход: <code>{a['arrival']}</code>\n"
         f"Смещение: <b>{a['offset']:+d} сек</b>\n"
         f"Скорость: {a['speed']} · Арена: {a['arena']}\n"
         f"Расстояние: {dist:.2f}\n"
         f"Отправление: <code>{departure.strftime('%d.%m.%Y %H:%M:%S') if departure else '—'}</code>\n\n"
         f"<b>Волны ({len(a['wave_plan'])}):</b>\n{waves}\n\n"
         f"💬 {html.escape(a.get('comment') or '—')}")
    send(cid,msg,[[btn("⏱ Смещение",f"oedit:{oid}:{aid}:offset"),btn("🐎 Скорость",f"oedit:{oid}:{aid}:speed")],
        [btn("🏟 Арена",f"oedit:{oid}:{aid}:arena"),btn("🟡 Тип атаки",f"otypes:{oid}:{aid}")],
        [btn("🌊 Волны",f"owaves:{oid}:{aid}"),btn("💬 Комментарий",f"oedit:{oid}:{aid}:comment")],
        [btn("🗑 Удалить",f"odelask:{oid}:{aid}")],[btn("⬅️ Операция",f"op:{oid}")]])

def op_wave_view(cid,oid,aid):
    if not owned_operation(cid,oid):send(cid,'⛔ Операция недоступна.');return
    op=load(OPERATIONS).get(oid)
    if not op or aid not in op["attacks"]:return
    a=op["attacks"][aid]
    rows=[[btn(f"✏️ Волна {i}: {w.get('text','')[:30]}",f"oedit:{oid}:{aid}:wave:{i-1}")] for i,w in enumerate(a["wave_plan"],1)]
    rows += [[btn("➕ Волна",f"owadd:{oid}:{aid}"),btn("➖ Убрать последнюю",f"owdel:{oid}:{aid}")],[btn("⬅️ Отправка",f"oa:{oid}:{aid}")]]
    send(cid,f"🌊 <b>Волны отправки №{aid}</b>\nРедактируйте состав каждой волны обычным текстом.",rows)

def op_offer_edit_menu(cid,oid,ouid):
    if not owned_operation(cid,oid):send(cid,'⛔ Операция недоступна.');return
    op=load(OPERATIONS).get(oid)
    if not op or ouid not in op["offers"]:return
    o=op["offers"][ouid]
    send(cid,f"👥 <b>{html.escape(o['player'])}</b>\nОбщее смещение: {o['offset']:+d} сек\n\nИзменение перезапишет смещение <b>всех</b> отправок этого оффера.",
         [[btn("⏱ Изменить смещение всех",f"obulk:{oid}:offer:{ouid}")],[btn("⬅️ Офферы",f"opoffers:{oid}")]])

def op_all_edit_menu(cid,oid):
    if not owned_operation(cid,oid):send(cid,'⛔ Операция недоступна.');return
    send(cid,"⏱ <b>Массовое изменение</b>\nЗадать одинаковое смещение всем отправкам операции (включая ранее изменённые).",
         [[btn("⏱ Установить смещение всем",f"obulk:{oid}:all:all")],[btn("⬅️ Операция",f"op:{oid}")]])

def preserve_attack_sequence(op):
    op['last_attack_id']=max([int(op.get('last_attack_id',0))]+[int(k) for k in op.get('attacks',{}) if str(k).isdigit()])


def allocate_attack_id(op):
    preserve_attack_sequence(op)
    op['last_attack_id']+=1
    return str(op['last_attack_id'])


def target_removal_token(op,key):
    payload={'status':op.get('status'),'target':op.get('targets',{}).get(key),
             'attacks':{aid:a for aid,a in op.get('attacks',{}).items() if a.get('target_key')==key}}
    return hashlib.sha256(json.dumps(payload,sort_keys=True,ensure_ascii=False).encode()).hexdigest()[:10]


def op_remove_target(cid,oid,key,token=None):
    ops=load(OPERATIONS);op=ops.get(oid)
    if not operation_is_owned(cid,op):send(cid,'⛔ Операция недоступна.');return
    if op.get('status') not in ('draft','published'):send(cid,'Изменение целей этой операции недоступно.');return
    target=op.get('targets',{}).get(key)
    if not target:send(cid,'Эта цель уже убрана из операции.');return
    attacks={aid:a for aid,a in op.get('attacks',{}).items() if a.get('target_key')==key}
    signature=target_removal_token(op,key)
    if token is None or token!=signature:
        count=len({a.get('offer_id') for a in attacks.values()})
        text=('🗑 <b>Убрать цель у всех офферов?</b>\n'+html.escape(target.get('player',''))+' — '+html.escape(target.get('village',''))+
              f' <code>{html.escape(key)}</code>\nБудут удалены все отправки на эту деревню: <b>{len(attacks)}</b>, офф-деревень: <b>{count}</b>.'+
              '\nЦель останется в общей базе. Остальные цели, офферы и другие операции сохранятся. Уже отправленные в игре войска это действие не отзывает.')
        if len(op['targets'])==1:text+='\nЭто последняя цель: в операции не останется заданий.'
        if op['status']=='published':text+='\nУчастники с изменёнными заданиями получат уведомление.'
        if token is not None:text='⚠️ Цель или отправки изменились. Проверьте удаление ещё раз.\n\n'+text
        send(cid,text,[[btn('🗑 Да, убрать цель и отправки',f'otrmyes:{oid}:{key}:{signature}')],
                       [btn('❌ Отмена',f'optarget:{oid}:{key}')]])
        return
    preserve_attack_sequence(op)
    for aid in attacks:del op['attacks'][aid]
    del op['targets'][key]
    op_store(ops,'Remove operation target and all offers sends to it')
    send(cid,f'✅ Цель <code>{html.escape(key)}</code> убрана у всех офферов. Удалено отправок: <b>{len(attacks)}</b>.')
    op_targets(cid,oid)


def offer_removal_token(op,key):
    payload={'status':op.get('status'),'offer':op.get('offers',{}).get(key),'attacks':{aid:a for aid,a in op.get('attacks',{}).items() if str(a.get('offer_id'))==str(key)}}
    return hashlib.sha256(json.dumps(payload,sort_keys=True,ensure_ascii=False).encode()).hexdigest()[:10]


def op_remove_offer(cid,oid,key,token=None):
    if not owned_operation(cid,oid):send(cid,'⛔ Операция недоступна.');return
    ops=load(OPERATIONS);op=ops.get(oid)
    if not op or op.get('status') not in ('draft','published'):send(cid,'Изменение состава этой операции недоступно.');return
    offer=op.get('offers',{}).get(key)
    if not offer:send(cid,'Эта офф-деревня уже убрана из операции.');return
    signature=offer_removal_token(op,key)
    if token is None or token!=signature:
        count=sum(str(a.get('offer_id'))==str(key) for a in op.get('attacks',{}).values())
        text=('🗑 <b>Убрать офф-деревню из операции?</b>\n'+html.escape(village_label(offer))+
              f'\nБудут удалены все её отправки: <b>{count}</b>. Регистрация деревни, другие офферы и цели операции сохранятся.')
        if op.get('status')=='published':text+='\nУчастник получит уведомление об изменении плана. Уже отправленные в игре войска это действие не отзывает.'
        if token is not None:text='⚠️ Настройки или отправки изменились. Проверьте удаление ещё раз.\n\n'+text
        send(cid,text,[[btn('🗑 Да, убрать деревню и отправки',f'oormyes:{oid}:{key}:{signature}')],
                       [btn('❌ Отмена',f'opoffer:{oid}:{key}')]])
        return
    removed=[aid for aid,a in op.get('attacks',{}).items() if str(a.get('offer_id'))==str(key)]
    preserve_attack_sequence(op)
    for aid in removed:del op['attacks'][aid]
    del op['offers'][key]
    op_store(ops,'Remove offence village and all its sends from operation')
    send(cid,f'✅ Офф-деревня убрана из операции. Удалено отправок: <b>{len(removed)}</b>.')
    op_offers(cid,oid)


def op_add_offer_picker(cid,oid,page=0,message_id=None):
    op=owned_operation(cid,oid)
    if not op:send(cid,'⛔ Операция недоступна.');return
    if op.get('status') not in ('draft','published'):send(cid,'Изменение состава этой операции недоступно.');return
    available=[(key,offer) for key,offer in active_offers().items() if key not in op.get('offers',{})]
    available.sort(key=lambda item:(str(item[1].get('player','')).casefold(),item[1]['x'],item[1]['y'],item[0]))
    page_size=8;pages=max(1,(len(available)+page_size-1)//page_size);page=max(0,min(int(page),pages-1))
    text=('➕ <b>Добавить офф-деревню</b>\nВыберите зарегистрированную деревню. Для неё сразу создадутся спам-отправки на все цели операции. Скорость — базовая для операции, арена — из настроек деревни, смещение — 0 секунд. Его можно изменить в разделе «По офферам».\n'
          f'Доступно деревень: {len(available)} · Страница {page+1}/{pages}')
    if op.get('status')=='published':text+='\nПосле добавления участник получит уведомление. Проверьте время отправок и настройте реальные атаки при необходимости.'
    if not available:text+='\nВсе зарегистрированные офф-деревни уже добавлены или пока нет доступных деревень.'
    buttons=[[btn(village_label(offer),f'oofferjoin:{oid}:{key}')] for key,offer in available[page*page_size:(page+1)*page_size]]
    nav=[]
    if page:nav.append(btn('⬅️ Назад',f'oofferpick:{oid}:{page-1}'))
    if page+1<pages:nav.append(btn('Дальше ➡️',f'oofferpick:{oid}:{page+1}'))
    if nav:buttons.append(nav)
    buttons.append([btn('⬅️ К операции',f'op:{oid}')])
    if message_id is None:send(cid,text,buttons)
    else:
        api('editMessageText',{'chat_id':cid,'message_id':message_id,'text':text+'\n\n'+TIME_NOTE,'parse_mode':'HTML','reply_markup':{'inline_keyboard':buttons}})


def op_add_offer(cid,oid,ouid):
    if not owned_operation(cid,oid):send(cid,'⛔ Операция недоступна.');return
    ops=load(OPERATIONS);op=ops.get(oid)
    if not op or op.get('status') not in ('draft','published'):send(cid,'Изменение состава этой операции недоступно.');return
    if ouid in op.get('offers',{}):send(cid,'Эта офф-деревня уже есть в операции. Повторные отправки не созданы.');return
    source=active_offers().get(ouid)
    if not source:send(cid,'Эта офф-деревня больше недоступна. Обновите список.');return
    if not op.get('targets'):send(cid,'В операции нет целей. Сначала добавьте цели операции.');return
    offer={'telegram_id':int(offer_owner(ouid,source)),'save_points':source.get('save_points',[]),
           'player':source['player'],'village':source['village'],'x':source['x'],'y':source['y'],
           'arena':source['arena'],'offset':0,'army_snapshot':source.get('army',{})}
    additions={}
    for key,target in op['targets'].items():
        aid=allocate_attack_id(op);defaults=op_attack_defaults('spam',target)
        attack={'id':aid,'offer_id':ouid,'offer_player':offer['player'],'target_key':key,
                'mode':defaults['mode'],'waves':defaults['waves'],'wave_plan':defaults['wave_plan'],
                'comment':'','offset':0,'speed':op['base_speed'],'arena':offer['arena']}
        op_retime(op,attack);additions[aid]=attack
    op['offers'][ouid]=offer;op['attacks'].update(additions)
    op_store(ops,'Add offence village and all targets to operation')
    send(cid,f'✅ Добавлена офф-деревня <b>{html.escape(village_label(source))}</b>. Создано отправок: <b>{len(additions)}</b>. Все новые отправки — спам; реальные атаки можно настроить отдельно.')
    show_op(cid,oid)


def op_new_send_picker(cid,oid):
    if not owned_operation(cid,oid):send(cid,'⛔ Операция недоступна.');return
    op=load(OPERATIONS).get(oid)
    if not op:return
    send(cid,"➕ <b>Новая отправка</b>\nВыберите оффера.",[[btn(village_label(o),f"oaddoffer:{oid}:{uid}")] for uid,o in op["offers"].items()]+[[btn("⬅️ Операция",f"op:{oid}")]])

def op_new_send(cid,oid,ouid,key):
    if not owned_operation(cid,oid):send(cid,'⛔ Операция недоступна.');return
    ops=load(OPERATIONS);op=ops.get(oid)
    if not op or ouid not in op["offers"] or key not in op["targets"]:return
    o=op["offers"][ouid];t=op["targets"][key]
    aid=allocate_attack_id(op)
    defaults=op_attack_defaults(t["mode"],t)
    a={"id":aid,"offer_id":ouid,"offer_player":o["player"],"target_key":key,
       "mode":defaults["mode"],"waves":defaults["waves"],"wave_plan":defaults["wave_plan"],
       "comment":"","offset":o["offset"],"speed":op["base_speed"],"arena":o["arena"]}
    op_retime(op,a);op["attacks"][aid]=a;op_store(ops);op_attack_view(cid,oid,aid)


def personal_jobs(op,uid):
    jobs=[a for a in op.get("attacks",{}).values() if op_owner(op,a.get("offer_id"))==str(uid)]
    return sorted(jobs,key=lambda a:(op_travel(a,op)[0].timestamp() if op_travel(a,op)[0] else float('inf'),str(a["id"])))

def cleanup_expired_operations():
    ops=load(OPERATIONS)
    current=datetime.now(TZ)
    expired=[]
    for oid,op in ops.items():
        if op.get("status")!="published":
            continue
        attacks=list(op.get("attacks",{}).values())
        if not attacks:
            continue
        try:
            arrivals=[server_datetime(a["arrival_iso"]) for a in attacks]
            if all(dt.tzinfo is not None and dt.timestamp()<=current.timestamp() for dt in arrivals):
                expired.append(oid)
        except (KeyError,ValueError,TypeError):
            continue
    if expired:
        for oid in expired:
            del ops[oid]
        save(OPERATIONS,ops)
        persist("Remove expired operations")
    return ops

def personal_list(cid,uid):
    ops=cleanup_expired_operations()
    available=[(oid,op) for oid,op in ops.items()
               if op.get("status")=="published" and str(uid) in op_members(op)
               and any(op_owner(op,a.get("offer_id"))==str(uid) for a in op.get("attacks",{}).values())]
    if not available:
        send(cid,"📋 Сейчас у вас нет актуального плана.",[[btn("⬅️ Меню","menu")]])
        return
    if len(available)==1:personal_op(cid,uid,available[0][0]);return
    send(cid,'📋 <b>Мои личные планы</b>',[[btn(op.get('name','Операция'),f'mine:op:{oid}')] for oid,op in available]+[[btn('⬅️ Меню','menu')]])

def save_points_parse(text):
    if text.strip()=="-":return []
    points=[]
    for line in re.split(r"[;\n]+",text.strip()):
        if not line.strip():continue
        match=re.fullmatch(r"\s*(-?\d{1,3})\s*(?:[|,]\s*|\s+)(-?\d{1,3})\s*",line)
        if not match:raise ValueError("Каждая точка — два числа: 13|3. Несколько точек вводите с новой строки.")
        point=list(map(int,match.groups()))
        if not all(-200<=n<=200 for n in point):raise ValueError("Координаты должны быть от −200 до 200.")
        if point not in points:points.append(point)
    if not points:raise ValueError("Введите хотя бы одну точку или «-» для очистки.")
    if len(points)>10:raise ValueError("Можно сохранить до 10 сейв-точек.")
    return points


def personal_operation(uid,oid):
    op=load(OPERATIONS).get(oid)
    if op and op.get("status")=="published" and str(uid) in op_members(op):return op
    return None


def real_jobs(op,uid):
    current=datetime.now(TZ)
    return [a for a in personal_jobs(op,uid) if a.get("mode") in ("destroy","capture")
            and not a.get("sent_at") and op_travel(a,op)[0] and op_travel(a,op)[0].timestamp()>current.timestamp()]


def selected_real(op,uid,aid=None):
    jobs=real_jobs(op,uid)
    return next((a for a in jobs if str(a["id"])==str(aid)),None) if aid else (jobs[0] if jobs else None)


def save_trip(origin,point,arena,departure):
    dx=abs(int(origin["x"])-point[0]);dy=abs(int(origin["y"])-point[1])
    distance=(min(dx,401-dx)**2+min(dy,401-dy)**2)**0.5
    if not distance:raise ValueError("Сейв-точка совпадает с вашей офф-деревней.")
    seconds=round((min(distance,20)/3+max(0,distance-20)/(3*(1+int(arena)*.2)))*3600)
    back=shift_seconds(departure,-60)
    return shift_seconds(back,-2*seconds),shift_seconds(back,-seconds),back,distance


def spam_wave_units(text):
    """Count only explicit supported quantities; never guess a free-form wave."""
    infantry=catapults=0
    for part in re.split(r"\s*\+\s*",text.strip().lower()):
        m=re.fullmatch(r"(\d+)\s+(.+)",part)
        if not m:return None
        count=int(m[1]);unit=m[2].strip()
        if re.fullmatch(r"катапульт[аы]?|катапульт|огненн\w* катапульт\w*|требушет\w*|камнем[её]т\w*|баллист\w*",unit):catapults+=count
        elif re.fullmatch(r"пехот\w*|любых юнитов|люб\w* воин\w*|легионер\w*|преториан\w*|империан\w*|дубинщик\w*|копейщик\w*|топорщик\w*|фаланг\w*|мечник\w*|раб\w*|страж\w* аш|воин\w* хопеш|на[её]мник\w*|лучник\w*|гоплит\w*|страж\w*|щитонос\w*",unit):infantry+=count
        else:return None
    return infantry,catapults


def spam_reserve(op,uid,real):
    groups={key:{"waves":0,"infantry":0,"catapults":0,"unknown":0} for key in ("before","same","after")}
    departure=op_travel(real,op)[0]
    for a in personal_jobs(op,uid):
        if a.get("mode")!="spam" or a.get("sent_at") or a["offer_id"]!=real["offer_id"]:continue
        dt=op_travel(a,op)[0]
        key="before" if dt.timestamp()<departure.timestamp() else "after" if dt.timestamp()>departure.timestamp() else "same"
        waves=a.get("wave_plan",[])
        for wave in waves:
            group=groups[key];group["waves"]+=1
            units=spam_wave_units(wave.get("text",""))
            if units is None:group["unknown"]+=1
            else:group["infantry"]+=units[0];group["catapults"]+=units[1]
        groups[key]["unknown"]+=max(0,int(a.get("waves",len(waves)))-len(waves))
    return groups


def spam_hint(op,uid,real):
    groups=spam_reserve(op,uid,real)
    lines=["💡 <b>Резерв для спама</b>","Только неотмеченные отправки этой офф-деревни в операции:"]
    for key,label in (("before","До реальной атаки — оставить дома на время сейва"),("same","Одновременно с реальной атакой"),("after","После реальной атаки — не отправлять с основным оффом")):
        g=groups[key]
        if key=="same" and not(g["waves"] or g["unknown"]):continue
        lines.append(f"• {label}: <b>{g['infantry']} пехоты + {g['catapults']} катапульт</b> ({g['waves']} волн)."+(f" ⚠️ Не учтён состав {g['unknown']} волн — проверьте вручную." if g['unknown'] else ""))
    total_infantry=sum(g['infantry'] for g in groups.values());total_catapults=sum(g['catapults'] for g in groups.values())
    qualifier="Из распознанных волн всего" if any(g['unknown'] for g in groups.values()) else "Всего зарезервировать"
    lines.append(f"<b>{qualifier}: {total_infantry} пехоты + {total_catapults} катапульт.</b>")
    lines.append("Шаблон: 19 пехоты + 1 катапульта на волну; изменённый состав учитывается, если указаны количества. Запас до и после нужен суммарно: возврат спама не предполагается. Просроченные отправки без отметки тоже учтены.")
    return "\n".join(lines)


def village_points_prompt(cid,uid,key,delete=False):
    offer=owns_offer(uid,key)
    if not offer:send(cid,'Деревня недоступна.');return
    state(uid)
    points=offer.get('save_points',[])
    text='🛡 <b>Сейв-точки деревни</b>\n'+html.escape(village_label(offer))+'\n\n'+('\n'.join(f'📍 {p[0]}|{p[1]}' for p in points) if points else 'Сейв-точки пока не заданы.')
    if delete:
        text+='\n\nВыберите точку для удаления. Её напоминания будут отменены.'
        buttons=[[btn(f'🗑 {point[0]}|{point[1]}',f'savepoint:remove:{key}:{point[0]}:{point[1]}')] for point in points]
        buttons.append([btn('⬅️ Сейв-точки',f'village:points:{key}')])
    else:
        buttons=[[btn('➕ Добавить сейв-точку',f'savepoint:add:{key}')],[btn('🗑 Удалить сейв-точку',f'savepoint:delete:{key}')]]
    buttons.append([btn('⬅️ К деревне',f'village:view:{key}')]);send(cid,text,buttons)


def save_option(op,uid,aid,point):
    attack=op.get('attacks',{}).get(aid)
    if op.get('status')!='published' or not attack or op_owner(op,attack['offer_id'])!=str(uid):return None
    if attack.get('mode') not in ('destroy','capture') or attack.get('sent_at'):return None
    key=attack['offer_id'];offer=owns_offer(uid,key)
    if not offer or not same_origin(offer,op['offers'][key]) or point not in offer.get('save_points',[]):return None
    departure,_=op_travel(attack,op)
    if not departure:return None
    start,arrival,back,distance=save_trip(op['offers'][key],point,int(offer['arena']),departure)
    return key,start,arrival,back


def choose_save_point(cid,uid,oid,aid,point=None):
    op=personal_operation(uid,oid);attack=op.get('attacks',{}).get(aid) if op else None
    if not attack or op_owner(op,attack['offer_id'])!=str(uid):send(cid,'⛔ План недоступен.');return
    offers=load(OFFERS);key=attack['offer_id'];offer=owns_offer(uid,key)
    if not offer:send(cid,'Деревня недоступна.');return
    ident=f'{oid}:{aid}';reminders=offers[key].setdefault('save_reminders',{})
    if point is None:
        reminders.pop(ident,None);send(cid,'🔕 Напоминание о сейве отменено.')
    else:
        option=save_option(op,uid,aid,point)
        if not option or option[1].timestamp()<=datetime.now(TZ).timestamp():send(cid,'Точка недоступна или время выхода уже прошло. Обновите план.');return
        previous=reminders.get(ident,{})
        if previous.get('point')!=point:reminders[ident]={'oid':oid,'aid':aid,'point':point}
        start=option[1];due=shift_seconds(start,-300)
        send(cid,f"🔔 Выбрана точка <b>{point[0]}|{point[1]}</b>. Выход: <b>{start.strftime('%d.%m %H:%M:%S')}</b> (время Travian). "+('Напоминание придёт в ближайшее время: до выхода меньше пяти минут.' if due.timestamp()<=datetime.now(TZ).timestamp() else f"Напомню за 5 минут — {due.strftime('%d.%m %H:%M:%S')}."))
    save(OFFERS,offers);persist('Update personal save reminder')
    personal_support(cid,uid,oid,'save',aid)


def same_time_marker(first,second):
    if not first or not second:return first==second
    try:
        first_time,_,first_suffix=str(first).partition('|');second_time,_,second_suffix=str(second).partition('|')
        return first_suffix==second_suffix and server_datetime(first_time).timestamp()==server_datetime(second_time).timestamp()
    except (ValueError,TypeError):return first==second


def send_save_reminders():
    offers=load(OFFERS);ops=load(OPERATIONS);current=datetime.now(TZ)
    for key,offer in offers.items():
        reminders=offer.get('save_reminders',{})
        for ident,selection in list(reminders.items()):
            op=ops.get(selection.get('oid'),{});uid=offer_owner(key,offer);point=selection.get('point')
            try:option=save_option(op,uid,selection.get('aid'),point)
            except (ValueError,TypeError,KeyError):option=None
            if not option or option[0]!=key or option[1].timestamp()<=current.timestamp():
                reminders.pop(ident,None);save(OFFERS,offers);continue
            _,start,arrival,back=option
            marker=start.isoformat()+'|'+str(point)
            if current.timestamp()<start.timestamp()-300 or same_time_marker(selection.get('sent_for'),marker):continue
            oid=selection['oid'];aid=selection['aid']
            text=(f"🔔 <b>Пора подготовить сейв армии</b>\n{html.escape(op.get('name','Операция'))}\n"
                  f"🏘 Из: <b>{offer['x']}|{offer['y']}</b> → <b>{point[0]}|{point[1]}</b>\n"
                  f"Отправить: <b>{start.strftime('%d.%m.%Y %H:%M:%S')}</b> (время Travian)\n"
                  f"Вернуться: <b>{back.strftime('%d.%m %H:%M:%S')}</b> — за минуту до реальной атаки.\n"
                  'Скорость 3, полный поход туда и обратно.')
            try:send(int(uid),text,[[btn('🛡 Открыть сейв',f'mine:save:{oid}:{aid}')]])
            except Exception:print('Save reminder delivery failed; will retry',flush=True);continue
            selection['sent_for']=marker;selection['sent_at']=now();save(OFFERS,offers)


def personal_support(cid,uid,oid,kind="save",aid=None):
    op=personal_operation(uid,oid)
    if not op:send(cid,"⛔ Этот план недоступен.");return
    real=selected_real(op,uid,aid)
    if aid and not real:send(cid,"Эта реальная атака уже отправлена, её время прошло или план изменён.",[[btn("⬅️ Весь план",f"mine:op:{oid}")]]);return
    jobs=real_jobs(op,uid)
    buttons=[]
    if real:
        departure=op_travel(real,op)[0]
        lines=[f"🛡 <b>Сейв-точки · {html.escape(op['name'])}</b>" if kind=="save" else f"💡 <b>Спам · {html.escape(op['name'])}</b>",
               f"Офф-деревня: <b>{html.escape(village_label(op['offers'][real['offer_id']]))}</b>",
               f"Реальная атака: <code>{html.escape(real['target_key'])}</code>",
               f"Отправка: <b>{departure.strftime('%d.%m.%Y %H:%M:%S')}</b> (время Travian)",""]
        if kind=="save":
            origin=op['offers'][real['offer_id']];offer=current_plan_offer(op,real['offer_id']);arena=int(offer.get('arena',origin['arena']))
            lines.extend([f"Скорость: <b>3</b> · Текущая арена: <b>{arena}</b>","Полный поход туда и обратно, без бонусов героя и артефактов."])
            points=offer.get('save_points',[])
            if not points:lines.append("Сейв-точки ещё не заданы.")
            choice=offer.get('save_reminders',{}).get(f"{oid}:{real['id']}",{})
            for point in points:
                try:start,arrival,back,distance=save_trip(origin,point,arena,departure)
                except ValueError:continue
                lines.extend(["",f"📍 <b>{point[0]}|{point[1]}</b> · {distance:.2f} клеток",
                              f"Уйти: <code>{start.strftime('%d.%m %H:%M:%S')}</code>"+(" — время уже прошло" if start.timestamp()<=datetime.now(TZ).timestamp() else ""),
                              f"Прибыть в точку: {arrival.strftime('%d.%m %H:%M:%S')}",f"Вернуться: <b>{back.strftime('%d.%m %H:%M:%S')}</b>"])
                if start.timestamp()>datetime.now(TZ).timestamp() and owns_offer(uid,real['offer_id']) and same_origin(offer,origin):
                    mark='✅' if choice.get('point')==point else '🔔'
                    buttons.append([btn(f"{mark} {point[0]}|{point[1]} · {start.strftime('%d.%m %H:%M:%S')}",f"mine:choose:{oid}:{real['id']}:{point[0]}:{point[1]}")])
            if choice:buttons.append([btn('🔕 Отменить напоминание',f"mine:unsave:{oid}:{real['id']}")])
            lines.append('Нажмите точку, чтобы включить личное напоминание за 5 минут до выхода. Для этой атаки выбирается одна точка.')
            if not points:lines.append('Задайте постоянные точки в настройках офф-деревни.')
            lines.extend(["","Выбирайте проверенные свободные оазисы или неактивные деревни: бот не проверяет гарнизон точки.","",spam_hint(op,uid,real)])
        else:lines.append(spam_hint(op,uid,real))
        buttons.extend([[btn(f"🎯 {op['offers'][a['offer_id']]['x']}|{op['offers'][a['offer_id']]['y']} → {a['target_key']} · {op_travel(a,op)[0].strftime('%H:%M:%S')}",f"mine:{kind}:{oid}:{a['id']}")] for a in jobs if a['id']!=real['id']])
    else:lines=["В плане нет предстоящей реальной атаки. Сейв рассчитывается для уничтожения или захвата; спам не служит временем возврата."]
    buttons.append([btn("⬅️ Весь план",f"mine:op:{oid}")])
    send(cid,"\n".join(lines),buttons)


def creator_tag(op):
    uid=str(op.get('created_by',''))
    if not uid.isdigit():return 'не указан'
    username=str(op.get('creator_username') or '').lstrip('@')
    label='@'+username if username else str(op.get('creator_name') or 'Профиль создателя')
    return f'<a href="tg://user?id={uid}">{html.escape(label)}</a>'


def personal_op(cid,uid,oid,message_id=None):
    op=load(OPERATIONS).get(oid)
    if not op or op.get("status")!="published" or str(uid) not in op_members(op):
        send(cid,"⛔ Этот план недоступен.");return
    jobs=personal_jobs(op,uid)
    done=sum(bool(a.get("sent_at")) for a in jobs)
    current=datetime.now(TZ)
    pending=[(op_travel(a,op)[0],a) for a in jobs if not a.get("sent_at")]
    future=[(dt,a) for dt,a in pending if dt and dt.timestamp()>current.timestamp()]
    overdue=[(dt,a) for dt,a in pending if dt and dt.timestamp()<=current.timestamp()]
    lines=[f"⚔️ <b>{html.escape(op['name'])}</b>",
           "Автор: "+creator_tag(op),
           f"Готовность: {'✅ подтверждена' if op.get('ready',{}).get(str(uid)) else '⏳ не подтверждена'}",
           f"Отправлено: <b>{done} из {len(jobs)}</b>",""]
    if future:
        dt,a=min(future,key=lambda z:z[0].timestamp())
        remaining=max(0,int((dt.timestamp()-current.timestamp())))
        h,rem=divmod(remaining,3600);m,sec=divmod(rem,60)
        lines.append(f"⏰ Следующая: <b>{dt.strftime('%d.%m %H:%M:%S')}</b> → <code>{a['target_key']}</code>")
        lines.append(f"⌛ До отправки: <b>{h:02d}:{m:02d}:{sec:02d}</b>")
    if overdue:
        lines.append(f"🔴 Просроченных без отметки: <b>{len(overdue)}</b>")
    if not pending:lines.append("✅ Все отправки отмечены выполненными.")
    lines.append(f"🔄 Обновлено: {current.strftime('%H:%M:%S')}")
    buttons=[[btn("🔄 Обновить",f"mine:refresh:{oid}")],
             [btn("🛡 Сейв-точки",f"mine:save:{oid}"),btn("💡 Юниты для спама",f"mine:spam:{oid}")]]
    buttons += [[wave_button(f"{op_mode_name(a['mode']).split()[0]}{' ✅' if a.get('sent_at') else ' 🔴' if dt and dt.timestamp()<=current.timestamp() else ''} {dt.strftime('%H:%M:%S') if dt else '—'} · {op['offers'][a['offer_id']]['x']}|{op['offers'][a['offer_id']]['y']} → {a['target_key']}",f"mine:job:{oid}:{a['id']}",a)]
                for a in jobs[:70] for dt in [op_travel(a,op)[0]]]
    if not op.get("ready",{}).get(str(uid)):
        buttons.append([btn("✅ Подтверждаю готовность",f"mine:ready:{oid}")])
    buttons.append([btn("⬅️ Мой план","mine:list")])
    lines.insert(1,WAVE_LEGEND)
    message="\n".join(lines)+"\n\n"+TIME_NOTE
    if message_id is None:
        send(cid,message,buttons)
    else:
        try:
            api("editMessageText",{"chat_id":cid,"message_id":message_id,"text":message,
                                  "parse_mode":"HTML","reply_markup":{"inline_keyboard":buttons}})
        except RuntimeError as e:
            if "message is not modified" not in str(e):raise


def personal_job(cid,uid,oid,aid):
    op=load(OPERATIONS).get(oid)
    if not op or op.get("status")!="published" or str(uid) not in op_members(op):return
    a=op["attacks"].get(aid)
    if not a or op_owner(op,a["offer_id"])!=str(uid):return
    departure,dist=op_travel(a,op)
    waves="\n".join(f"{i}. {html.escape(w.get('text','—'))}" for i,w in enumerate(a.get("wave_plan",[]),1))
    msg=(f"🎯 <b>{html.escape(op['name'])} · {a['target_key']}</b>\n"
         f"{attack_caption(a)}\nОфф-деревня: <b>{html.escape(village_label(op['offers'][a['offer_id']]))}</b>\n"
         f"Отправление: <code>{departure.strftime('%d.%m.%Y %H:%M:%S') if departure else '—'}</code>\n"
         f"Прибытие: <code>{a['arrival']}</code>\n"
         f"Арена: {a['arena']} · Скорость: {a['speed']} · Расстояние: {dist:.2f}\n\n"
         f"<b>Волны:</b>\n{waves}\n\n💬 {html.escape(a.get('comment') or '—')}\n"
         f"Статус: {'✅ Отправлено' if a.get('sent_at') else '⏳ Ожидает'}")
    target=op["targets"][a["target_key"]]
    link=(f"https://ts8.x1.asia.travian.com/build.php?id=39&tt=2"
          f"&x={int(target['x'])}&y={int(target['y'])}&c=3&gid=16&eventType=3")
    support=[[btn("🛡 Сейв-точки",f"mine:save:{oid}:{aid}"),btn("💡 Юниты для спама",f"mine:spam:{oid}:{aid}")]] if a.get("mode") in ("destroy","capture") else []
    send(cid,msg,[[{"text":"⚔️ Открыть отправку в Travian","url":link}]]+support+[
                  [btn("↩ Отменить отметку" if a.get("sent_at") else "✅ Отправлено",f"mine:sent:{oid}:{aid}")],
                  [btn("⬅️ Весь план",f"mine:op:{oid}")]])

def operation_progress(cid,oid):
    if not owned_operation(cid,oid):send(cid,'⛔ Операция недоступна.');return
    op=load(OPERATIONS).get(oid)
    if not op:return
    lines=[f"📊 <b>{html.escape(op['name'])}</b>"]
    for uid,o in op["offers"].items():
        jobs=[a for a in personal_jobs(op,op_owner(op,uid)) if a["offer_id"]==uid]
        done=sum(bool(a.get("sent_at")) for a in jobs)
        ready="✅" if op.get("ready",{}).get(op_owner(op,uid)) else "⏳"
        lines.append(f"{ready} {html.escape(village_label(o))}: {done}/{len(jobs)}")
    send(cid,"\n".join(lines),[[btn("⬅️ Операция",f"op:{oid}")]])

def send_reminders():
    ops=cleanup_expired_operations()
    current=datetime.now(TZ)
    changed=False
    for oid,op in ops.items():
        if op.get("status")!="published":continue
        # Separate durable markers prevent duplicates. A late poll sends only
        # the urgent one-minute alert, rather than two notifications at once.
        for threshold,marker_field in ((300,'reminder_sent_for'),(60,'reminder_minute_sent_for')):
            grouped={}
            for a in op.get("attacks",{}).values():
                if a.get("sent_at"):continue
                departure,_=op_travel(a,op)
                if not departure:continue
                seconds=(departure.timestamp()-current.timestamp())
                marker=departure.isoformat()
                if not 0<seconds<=threshold or (threshold==300 and seconds<=60) or same_time_marker(a.get(marker_field),marker):continue
                grouped.setdefault(op_owner(op,a["offer_id"]),[]).append((departure,a,marker))
            for offer_uid,jobs in grouped.items():
                jobs.sort(key=lambda item:(item[0].timestamp(),str(item[1]["id"])))
                heading="🚨 Отправки в ближайшую минуту" if threshold==60 else "⏰ Отправки в ближайшие 5 минут"
                lines=[f"<b>{html.escape(op['name'])}: {heading}</b>"]
                buttons=[]
                for departure,a,marker in jobs:
                    target=op["targets"].get(a["target_key"])
                    if not target:continue
                    lines.append(f"\n🏘 {op['offers'][a['offer_id']]['x']}|{op['offers'][a['offer_id']]['y']} → 🎯 <code>{a['target_key']}</code> · <b>{departure.strftime('%H:%M:%S')}</b>"
                                 f" · {op_mode_name(a['mode'])} · {len(a.get('wave_plan',[]))} волн · арена {a['arena']}")
                    link=(f"https://ts8.x1.asia.travian.com/build.php?id=39&tt=2"
                          f"&x={int(target['x'])}&y={int(target['y'])}&c=3&gid=16&eventType=3")
                    buttons.append([{"text":f"⚔️ {departure.strftime('%H:%M:%S')} → {a['target_key']} · Travian","url":link}])
                    buttons.append([btn(f"📋 Задание {departure.strftime('%H:%M:%S')} · {op['offers'][a['offer_id']]['x']}|{op['offers'][a['offer_id']]['y']} → {a['target_key']}",f"mine:job:{oid}:{a['id']}")])
                if not buttons:continue
                try:
                    send(int(offer_uid),"\n".join(lines),buttons)
                    for departure,a,marker in jobs:
                        a[marker_field]=marker
                    changed=True
                except Exception as e:
                    print("reminder error",oid,offer_uid,repr(e),flush=True)
    if changed:save(OPERATIONS,ops)


def handle_message(m):
    # The operations wizard is private; ignore messages from group topics.
    if (m.get("chat") or {}).get("type") != "private":
        return
    uid=m["from"]["id"];cid=m["chat"]["id"];text=m.get("text","").strip()
    if text=="/start":state(uid);start(cid,uid);return
    st=getstate(uid)
    if not st:send(cid,"Используйте /start, чтобы открыть меню.");return
    step=st["step"];d=st["data"]
    if step=='add_save_point':
        key=d['key'];offer=owns_offer(uid,key)
        if not offer:state(uid);send(cid,'Деревня недоступна.');return
        point=coords(text)
        if not point:send(cid,'❌ Введите координаты одной точки: <code>13|3</code>.');return
        point=list(point);points=offer.get('save_points',[])
        if point==[int(offer['x']),int(offer['y'])]:send(cid,'❌ Точка совпадает с офф-деревней.');return
        if point in points:send(cid,'Эта сейв-точка уже добавлена.');return
        if len(points)>=10:send(cid,'Уже сохранено 10 точек. Сначала удалите ненужную.',[[btn('⬅️ Сейв-точки',f'village:points:{key}')]]);return
        offers=load(OFFERS);offers[key]['save_points']=points+[point];save(OFFERS,offers);persist('Add village save point')
        send(cid,f'✅ Добавлена сейв-точка {point[0]}|{point[1]}.');village_points_prompt(cid,uid,key);return
    if step in ('village_save_points','save_points'):
        offers=load(OFFERS);key=d.get('key',str(uid));offer=owns_offer(uid,key)
        if not offer:state(uid);send(cid,'Деревня недоступна.');return
        try:
            points=save_points_parse(text)
            if [int(offer['x']),int(offer['y'])] in points:raise ValueError('Сейв-точка не должна совпадать с офф-деревней.')
        except ValueError as exc:send(cid,'❌ '+str(exc));return
        offers[key]['save_points']=points
        pending=offers[key].get('save_reminders',{})
        offers[key]['save_reminders']={ident:item for ident,item in pending.items() if item.get('point') in points}
        save(OFFERS,offers);persist('Update permanent village save points');state(uid)
        send(cid,'✅ Сейв-точки сохранены.' if points else '✅ Сейв-точки очищены.')
        personal_village(cid,uid,key);return
    if step in ("reg_coords","target_coords"):
        c=coords(text)
        if not c:send(cid,"❌ Введите координаты через пробел, например <code>55 46</code>.");return
        v,p=village_at(*c)
        if not v:send(cid,f"❌ Деревня <code>{c[0]}|{c[1]}</code> не найдена в последнем снимке мира.");return
        if step=="reg_coords":
            if v["tribe_id"] not in TROOPS:send(cid,"❌ Для этой расы пока нет шаблона войск.");return
            error=village_error(uid,v,d.get('key'))
            if error:send(cid,'❌ '+error);return
            if d.get('key') and not owns_offer(uid,d['key']):state(uid);send(cid,'Деревня недоступна.');return
            state(uid,"reg_arena",{"village":v,"key":d.get('key')});send(cid,f"✅ Найдено: <b>{html.escape(v['player'])}</b> — {html.escape(v['village'])}\nРаса: <b>{TRIBES.get(v['tribe_id'])}</b>\n\nВведите уровень арены от <b>0</b> до <b>20</b>.");return
        d={"village":v};state(uid,"target_type",d)
        send(cid,f"🎯 <b>Новая цель</b>\n{html.escape(v['player'])} — {html.escape(v['village'])} <code>{v['x']}|{v['y']}</code>\nАльянс: <b>{html.escape(target_alliance_name(v))}</b>\n\nВыберите тип:",[[btn(x,f"newtype:{x}")] for x in TARGET_TYPES]);return
    if step=="reg_arena":
        if not text.isdigit() or not 0<=int(text)<=20:send(cid,"❌ Арена должна быть числом 0–20.");return
        d["arena"]=int(text);state(uid,"reg_army",d);v=d["village"]
        send(cid,f"⚔️ <b>Войска — {TRIBES[v['tribe_id']]}</b>\n\nСкопируйте шаблон, впишите числа и отправьте обратно.\n\n<pre>{html.escape(template(v['tribe_id']))}</pre>");return
    if step in ("reg_army","army"):
        tid=d["village"]["tribe_id"] if step=="reg_army" else d["tribe_id"];army,err=parse_army(text,tid)
        if err:send(cid,"❌ "+html.escape(err));return
        os_=load(OFFERS);k=d.get('key') or str(uid)
        if step=='reg_army':
            v=d['village'];error=village_error(uid,v,d.get('key'))
            if error:send(cid,'❌ '+error);return
            if d.get('key') and not owns_offer(uid,d['key']):state(uid);send(cid,'Деревня недоступна.');return
            if not d.get('key') and k in os_:k=str(uid)+'_'+uuid.uuid4().hex[:8]
            os_[k]={"telegram_id":uid,**v,"arena":d["arena"],"registered_at":now(),"army":{"troops":army,"updated_at":now()}}
        else:
            if not owns_offer(uid,k):state(uid);send(cid,'Деревня недоступна.');return
            os_[k]['army']={'troops':army,'updated_at':now()}
        save(OFFERS,os_);state(uid);persist("Update alliance ops offers");send(cid,"✅ Данные сохранены.\n\n"+fmt_offer(os_[k]),menu(uid));return
    if step=="arena":
        if not text.isdigit() or not 0<=int(text)<=20:send(cid,"❌ Арена должна быть числом 0–20.");return
        key=d.get('key',str(uid))
        if not owns_offer(uid,key):state(uid);send(cid,'Деревня недоступна.');return
        os_=load(OFFERS);os_[key]["arena"]=int(text);save(OFFERS,os_);state(uid);persist("Update alliance ops arena")
        affected=sync_operation_arenas()
        send(cid,f"✅ Арена обновлена. Пересчитано ещё не отправленных заданий в черновиках и опубликованных операциях: {affected}. Изменённые личные планы требуют повторного подтверждения готовности.",menu(uid));return


    if step=="op_arrival":
        dt=op_dt(text)
        if not dt:send(cid,"❌ Введите время сервера Travian: <code>05.10.2026 20:00:00</code>. В час перевода часов выберите однозначное время.");return
        d["arrival_iso"]=dt.isoformat();d["time_zone"]="Europe/London";d["base_speed"]=3
        d["offers"]=[];d["offsets"]={}
        state(uid,"op_pick_offers",d);op_offer_picker(cid,d);return
    if step=="op_offset":
        try:off=int(text)
        except:send(cid,"❌ Введите целое число секунд: <code>0</code>, <code>-1</code>, <code>+2</code>.");return
        ouid=d["offset_uid"];d["offsets"][ouid]=off
        remaining=[x for x in d["offers"] if x not in d["offsets"]]
        if remaining:
            nxt=remaining[0];d["offset_uid"]=nxt;state(uid,"op_offset",d);o=load(OFFERS)[nxt];send(cid,f"⏱ Смещение для <b>{html.escape(village_label(o))}</b> в секундах.\nНапример: <code>0</code>, <code>-1</code>, <code>+2</code>.");return
        d.pop("offset_uid",None);d["targets"]={}
        if selected_alliance_keys(d):state(uid,'op_pick_targets',d);op_target_picker(cid,d)
        else:state(uid,'op_pick_alliance',d);op_alliance_picker(cid,d)
        return

    if step=="op_edit_value":
        if not owned_operation(uid,d.get('oid')):state(uid);send(cid,'⛔ Операция недоступна.');return
        oid=d["oid"];aid=d["aid"];field=d["field"];ops=load(OPERATIONS);op=ops.get(oid)
        if not op:state(uid);send(cid,"❌ Операция не найдена.");return
        if aid=="op":
            op["comment"]="" if text=="-" else text
            op_store(ops);state(uid);show_op(cid,oid);return
        a=op["attacks"].get(aid)
        if not a:state(uid);send(cid,"❌ Отправка не найдена.");return
        if field=="offset":
            try:v=int(text)
            except:send(cid,"❌ Введите целое число секунд.");return
            a["offset"]=v;op_retime(op,a)
        elif field=="speed":
            try:v=float(text.replace(",","."))
            except:send(cid,"❌ Введите число.");return
            if not 0<v<=1000:send(cid,"❌ Скорость должна быть больше нуля.");return
            a["speed"]=v
        elif field=="arena":
            if not text.isdigit() or not 0<=int(text)<=20:send(cid,"❌ Арена 0–20.");return
            a["arena"]=int(text);a["arena_override"]=True
        elif field=="comment":a["comment"]="" if text=="-" else text
        elif field.startswith("wave:"):
            idx=int(field.split(":")[1])
            if idx>=len(a["wave_plan"]):send(cid,"❌ Волна не найдена.");return
            a["wave_plan"][idx]["text"]=text
        else:return
        a["waves"]=len(a["wave_plan"]);op_store(ops);state(uid);op_attack_view(cid,oid,aid);return
    if step=="op_change_time":
        if not owned_operation(uid,d.get('oid')):state(uid);send(cid,'⛔ Операция недоступна.');return
        dt=op_dt(text)
        if not dt:
            send(cid,"❌ Введите дату и время сервера Travian: <code>10.10.2026 23:30:00</code>. В час перевода часов выберите однозначное время.");return
        oid=d["oid"];ops=load(OPERATIONS);op=ops.get(oid)
        if not op:state(uid);send(cid,"❌ Операция не найдена.");return
        old_dt=server_datetime(op["arrival_iso"])
        delta=timedelta(seconds=dt.timestamp()-old_dt.timestamp())
        if delta.total_seconds()==0:
            state(uid);send(cid,"Время операции не изменилось.");show_op(cid,oid);return
        op["arrival_iso"]=dt.isoformat()
        op["arrival"]=dt.strftime("%d.%m.%Y %H:%M:%S")
        changed=0;sent=0
        for a in op["attacks"].values():
            if a.get("sent_at"):
                sent+=1
                continue
            op_retime(op,a)
            a.pop("reminder_sent_for",None)
            a.pop("reminder_minute_sent_for",None)
            changed+=1
        op_store(ops,"Change operation arrival time")
        state(uid)
        send(cid,f"✅ Новое время операции: <b>{op['arrival']}</b>. Пересчитано отправок: {changed}. Уже отправленных без изменений: {sent}. Индивидуальные смещения сохранены.")
        show_op(cid,oid)
        return
    if step=="op_bulk_offset":
        if not owned_operation(uid,d.get('oid')):state(uid);send(cid,'⛔ Операция недоступна.');return
        try:offset=int(text)
        except:send(cid,"❌ Введите целое число секунд.");return
        oid=d["oid"];ops=load(OPERATIONS);op=ops.get(oid)
        if not op:state(uid);return
        if d["scope"]=="offer":
            ouid=d["ouid"];op["offers"][ouid]["offset"]=offset
            affected=[a for a in op["attacks"].values() if a["offer_id"]==ouid]
        else:
            for o in op["offers"].values():o["offset"]=offset
            affected=list(op["attacks"].values())
        for a in affected:a["offset"]=offset;op_retime(op,a)
        op_store(ops);state(uid);send(cid,f"✅ Смещение {offset:+d} сек установлено для {len(affected)} отправок.");show_op(cid,oid);return
    if step=="target_comment":
        ts=load(TARGETS);k=d["key"]
        if k in ts:ts[k]["comment"]="" if text=="-" else text;ts[k]["updated_at"]=now();save(TARGETS,ts);persist("Update alliance ops target")
        state(uid);show_target(cid,k)

def callback(c):
    try:api("answerCallbackQuery",{"callback_query_id":c["id"]})
    except:pass
    uid=c["from"]["id"];cid=c["message"]["chat"]["id"];x=c.get("data","")
    if str(cid)!=str(uid) or c['message']['chat'].get('type','private')!='private':return
    parts=x.split(':');action=parts[0]
    if action in OP_MANAGEMENT_ACTIONS and (len(parts)<2 or not owned_operation(uid,parts[1])):
        send(cid,'⛔ Операция недоступна.');return
    if x=="menu":state(uid);start(cid,uid);return
    if x=="offers:ro:list":
        if uid not in COORDINATORS:return
        coordinator_offer_list(cid);return
    if x.startswith("offers:ro:view:"):
        if uid not in COORDINATORS:return
        coordinator_offer_view(cid,x.rsplit(":",1)[1]);return
    if x.startswith('savepoint:'):
        parts=x.split(':')
        if len(parts)<3:return
        action,key=parts[1:3];offer=owns_offer(uid,key)
        if not offer:send(cid,'Деревня недоступна.');return
        if action=='add':
            state(uid,'add_save_point',{'key':key});send(cid,'➕ Введите координаты одной сейв-точки, например <code>13|3</code>.',[[btn('Отмена',f'village:points:{key}')]])
        elif action=='delete':village_points_prompt(cid,uid,key,delete=True)
        elif action=='remove' and len(parts)==5:
            try:point=[int(parts[3]),int(parts[4])]
            except ValueError:return
            offers=load(OFFERS);points=offers[key].get('save_points',[])
            if point not in points:send(cid,'Эта точка уже удалена.');village_points_prompt(cid,uid,key);return
            offers[key]['save_points']=[p for p in points if p!=point]
            offers[key]['save_reminders']={ident:item for ident,item in offers[key].get('save_reminders',{}).items() if item.get('point')!=point}
            save(OFFERS,offers);persist('Remove village save point');send(cid,f'✅ Удалена сейв-точка {point[0]}|{point[1]}.');village_points_prompt(cid,uid,key)
        return
    if x.startswith(('mine:choose:','mine:unsave:')):
        parts=x.split(':')
        if parts[1]=='choose':
            if len(parts)!=6:return
            try:point=[int(parts[4]),int(parts[5])]
            except ValueError:return
            choose_save_point(cid,uid,parts[2],parts[3],point)
        elif len(parts)==4:choose_save_point(cid,uid,parts[2],parts[3])
        return
    if x.startswith(("mine:save:","mine:spam:","mine:points:")):
        parts=x.split(":");kind=parts[1];oid=parts[2];aid=parts[3] if len(parts)>3 and parts[3]!="-" else None
        op=personal_operation(uid,oid)
        if not op:send(cid,"⛔ Этот план недоступен.");return
        if kind=="points":
            send(cid,'Сейв-точки теперь задаются в «Моих офф-деревнях» → нужная деревня → «Сейв-точки».');return
        state(uid);personal_support(cid,uid,oid,kind,aid);return
    if x=="mine:list":personal_list(cid,uid);return
    if x.startswith("mine:refresh:"):
        personal_op(cid,uid,x.split(":",2)[2],c["message"]["message_id"]);return
    if x.startswith("mine:op:"):personal_op(cid,uid,x.split(":",2)[2]);return
    if x.startswith("mine:job:"):
        _,_,oid,aid=x.split(":",3);personal_job(cid,uid,oid,aid);return
    if x.startswith("mine:ready:"):
        oid=x.split(":",2)[2];ops=load(OPERATIONS);op=ops.get(oid)
        if not op or op.get("status")!="published" or str(uid) not in op_members(op):return
        op.setdefault("ready",{})[str(uid)]=now();op_store(ops);personal_op(cid,uid,oid);return
    if x.startswith("mine:sent:"):
        _,_,oid,aid=x.split(":",3);ops=load(OPERATIONS);op=ops.get(oid)
        if not op or op.get("status")!="published" or str(uid) not in op_members(op):return
        a=op["attacks"].get(aid)
        if not a or op_owner(op,a.get("offer_id"))!=str(uid):return
        if a.get("sent_at"):a.pop("sent_at")
        else:a["sent_at"]=now()
        op_store(ops);personal_job(cid,uid,oid,aid);return
    if x.startswith("publish:"):
        oid=x.split(":",1)[1];ops=load(OPERATIONS);op=ops.get(oid)
        if not op:return
        op["status"]="published";op.setdefault("published_at",now());op_store(ops)
        ok=0;failed=[]
        for ouid in op_members(op):
            try:
                send(int(ouid),f"📢 <b>{html.escape(op['name'])} опубликована!</b>\nВаш персональный план готов.",[[btn("📋 Открыть план",f"mine:op:{oid}")]])
                ok+=1
            except Exception as e:failed.append(ouid);print("publish delivery error",ouid,repr(e),flush=True)
        send(cid,f"📢 Рассылка завершена: {ok} доставлено, {len(failed)} ошибок."+("\nНе доставлено: "+", ".join(failed) if failed else ""));show_op(cid,oid);return
    if x.startswith("progress:"):
        operation_progress(cid,x.split(":",1)[1])
        return
    if x in ('village:list','offer:view','offer:army','offer:arena'):
        state(uid);personal_villages(cid,uid,x.split(':')[1] if x.startswith('offer:') and x!='offer:view' else 'view');return
    if x=='village:add':
        state(uid,'reg_coords',{});send(cid,'➕ Введите координаты новой офф-деревни через пробел.');return
    if x.startswith('village:'):
        parts=x.split(':');action=parts[1];key=parts[2] if len(parts)>2 else ''
        offer=owns_offer(uid,key)
        if not offer:send(cid,'Деревня недоступна.');return
        state(uid)
        if action=='view':personal_village(cid,uid,key)
        elif action=='points':village_points_prompt(cid,uid,key)
        elif action=='army':
            state(uid,'army',{'key':key,'tribe_id':offer['tribe_id']});send(cid,'🔄 Обновите войска этой деревни:\n<pre>'+html.escape(template(offer['tribe_id']))+'</pre>')
        elif action=='arena':state(uid,'arena',{'key':key});send(cid,'🏟 Введите уровень арены этой деревни: 0–20.')
        elif action=='coords':
            state(uid,'reg_coords',{'key':key});send(cid,'✏️ Введите новые координаты. Затем укажите арену и войска новой деревни. Сейв-точки будут очищены. Уже созданные планы сохранят прежние координаты; для изменения плана обратитесь к координатору.')
        elif action=='delete':send(cid,'Удалить эту офф-деревню из регистрации? В уже созданных планах она сохранится.',[[btn('🗑 Да, удалить',f'village:remove:{key}')],[btn('Отмена',f'village:view:{key}')]])
        elif action=='remove':
            offers=load(OFFERS);offers[key]['deleted_at']=now();save(OFFERS,offers);persist('Remove registered offence village');personal_villages(cid,uid)
        return
    if x.startswith(("targettype:","targetprio:","targetcomment:","targetdelete:","settype:","setprio:","confirmdelete:")) and uid not in COORDINATORS:send(cid,"⛔ Только для координатора.");return

    if x=="ops:list":list_ops(cid);return
    if x=="ops:new":state(uid,"op_pick_alliance",{});op_alliance_picker(cid,{});return
    if x.startswith('opalliance:'):
        st=getstate(uid)
        if not st or st['step'] not in ('op_pick_alliance','op_pick_targets'):return
        d=st['data'];key=x.split(':',1)[1]
        if key=='back':state(uid,'op_pick_alliance',d);op_alliance_picker(cid,d);return
        targets=refresh_target_alliances();groups={target_alliance_key(t):target_alliance_name(t) for t in targets.values()}
        selected=selected_alliance_keys(d)
        if key=='done':
            if not selected or not selected.issubset(groups):
                send(cid,'Выберите хотя бы один альянс с доступными целями.');op_alliance_picker(cid,d);return
            d['alliance_keys']=sorted(selected);d['alliance_name']=', '.join(groups[k] for k in sorted(selected))
            if len(selected)==1:d['alliance_key']=next(iter(selected))
            else:d.pop('alliance_key',None)
            d['targets']={k:v for k,v in d.get('targets',{}).items() if k in targets and target_alliance_key(targets[k]) in selected}
            if d.get('arrival_iso'):
                state(uid,'op_pick_targets',d);op_target_picker(cid,d)
            else:
                state(uid,'op_arrival',d);send(cid,'🕐 <b>Новая операция</b>\nАльянсы: <b>'+html.escape(d['alliance_name'])+'</b>\nВведите дату и время прибытия по серверу Travian.\nФормат: <code>05.10.2026 20:00:00</code>')
            return
        if key not in groups:send(cid,'Целей этого альянса больше нет.');op_alliance_picker(cid,d);return
        if key in selected:selected.remove(key)
        else:selected.add(key)
        d['alliance_keys']=sorted(selected)
        d.pop('alliance_key',None)
        d['alliance_name']=', '.join(groups[k] for k in sorted(selected) if k in groups)
        d['targets']={k:v for k,v in d.get('targets',{}).items() if k in targets and target_alliance_key(targets[k]) in selected}
        state(uid,'op_pick_alliance',d);op_alliance_picker(cid,d,c.get('message',{}).get('message_id'))
        return
    if x.startswith("opofftoggle:"):
        st=getstate(uid)
        if not st or st['step']!='op_pick_offers':return
        d=st['data'];ouid=x.split(':',1)[1]
        if ouid not in active_offers():send(cid,'Офф-деревня больше недоступна.');op_offer_picker(cid,d);return
        if ouid in d["offers"]:d["offers"].remove(ouid);d["offsets"].pop(ouid,None)
        else:d["offers"].append(ouid)
        state(uid,"op_pick_offers",d);op_offer_picker(cid,d);return
    if x=="opoffdone":
        st=getstate(uid);d=st["data"]
        d['offers']=[key for key in d.get('offers',[]) if key in active_offers()]
        if not d.get("offers"):state(uid,'op_pick_offers',d);send(cid,"❌ Выберите хотя бы одну офф-деревню.");op_offer_picker(cid,d);return
        nxt=d["offers"][0];d["offset_uid"]=nxt;state(uid,"op_offset",d);o=load(OFFERS)[nxt];send(cid,f"⏱ <b>Смещения офферов</b>\n\nВведите смещение для <b>{html.escape(village_label(o))}</b> в секундах.\nНапример: <code>0</code>, <code>-1</code>, <code>+2</code>.");return
    if x.startswith("optargetpick:"):
        st=getstate(uid)
        if not st or st["step"]!="op_pick_targets":return
        d=st["data"];key=x.split(":",1)[1]
        target=load(TARGETS).get(key)
        if not target or target_alliance_key(target) not in selected_alliance_keys(d):
            send(cid,'Эта цель не относится к выбранным альянсам.');return
        if key in d["targets"]:d["targets"].pop(key)
        else:d["targets"][key]="spam"
        state(uid,"op_pick_targets",d)
        op_target_picker(cid,d)
        return
    if x=="opgenerate":
        st=getstate(uid)
        if not st or st['step']!='op_pick_targets':return
        d=st['data']
        if not d.get('targets'):send(cid,'❌ Выберите хотя бы одну цель.');return
        d['creator_username']=c['from'].get('username')
        d['creator_name']=' '.join(str(c['from'].get(k,'')) for k in ('first_name','last_name')).strip()
        try:oid=generate_op(uid,d)
        except ValueError as exc:
            send(cid,'❌ '+str(exc))
            if any(key not in active_offers() for key in d.get('offers',[])):
                d['offers']=[];d['offsets']={};state(uid,'op_pick_offers',d);op_offer_picker(cid,d)
            else:d['targets']={};state(uid,'op_pick_alliance',d);op_alliance_picker(cid,d)
            return
        state(uid);show_op(cid,oid);return
    if x.startswith('opdepartures:'):
        parts=x.split(':')
        page=int(parts[2]) if len(parts)>2 and parts[2].isdigit() else 0
        op_departures(cid,parts[1],page,c['message'].get('message_id'));return
    if x.startswith("optargets:"):op_targets(cid,x.split(":",1)[1]);return
    if x.startswith("opoffers:"):op_offers(cid,x.split(":",1)[1]);return
    if x.startswith("optarget:"):
        _,oid,key=x.split(":",2);op_target_detail(cid,oid,key);return
    if x.startswith("opoffer:"):
        _,oid,ouid=x.split(":",2);op_offer_detail(cid,oid,ouid);return
    if x.startswith("op:"):show_op(cid,x.split(":",1)[1]);return

    if x.startswith("oa:"):
        _,oid,aid=x.split(":",2);op_attack_view(cid,oid,aid);return
    if x.startswith("owaves:"):
        _,oid,aid=x.split(":",2);op_wave_view(cid,oid,aid);return
    if x.startswith("oedit:"):
        _,oid,aid,field=x.split(":",3)
        if not load(OPERATIONS).get(oid):return
        state(uid,"op_edit_value",{"oid":oid,"aid":aid,"field":field})
        prompts={"offset":"Введите смещение в секундах: -2, 0, +1.","speed":"Введите скорость (клеток/час).",
                 "arena":"Введите уровень арены 0–20.","comment":"Введите комментарий (или - для очистки)."}
        send(cid,"✏️ "+html.escape(prompts.get(field,"Введите состав волны текстом.")));return
    if x.startswith("otypes:"):
        _,oid,aid=x.split(":",2)
        send(cid,"Выберите новый тип отправки. Состав волн будет заменён шаблоном.",[[btn(op_mode_name(mode),f"otype:{oid}:{aid}:{mode}")] for mode in ("spam","destroy","capture")]);return
    if x.startswith("otype:"):
        _,oid,aid,mode=x.split(":",3);ops=load(OPERATIONS);op=ops.get(oid)
        if not op or aid not in op["attacks"]:return
        a=op["attacks"][aid];defs=op_attack_defaults(mode,op["targets"][a["target_key"]])
        a["mode"]=mode;a["waves"]=defs["waves"];a["wave_plan"]=defs["wave_plan"]
        op_store(ops);op_attack_view(cid,oid,aid);return
    if x.startswith(("owadd:","owdel:")):
        action,oid,aid=x.split(":",2);ops=load(OPERATIONS);op=ops.get(oid)
        if not op or aid not in op["attacks"]:return
        a=op["attacks"][aid]
        if action=="owadd":
            if len(a["wave_plan"])>=20:send(cid,"❌ Максимум 20 волн.");return
            a["wave_plan"].append({"text":"Укажите состав"})
        elif len(a["wave_plan"])>1:a["wave_plan"].pop()
        else:send(cid,"❌ Должна остаться хотя бы одна волна.");return
        a["waves"]=len(a["wave_plan"]);op_store(ops);op_wave_view(cid,oid,aid);return
    if x.startswith("odelask:"):
        _,oid,aid=x.split(":",2)
        send(cid,"🗑 Удалить эту отправку?",[[btn("✅ Удалить",f"odelyes:{oid}:{aid}")],[btn("⬅️ Назад",f"oa:{oid}:{aid}")]]);return
    if x.startswith("odelyes:"):
        _,oid,aid=x.split(":",2);ops=load(OPERATIONS);op=ops.get(oid)
        if not op:return
        op["attacks"].pop(aid,None);op_store(ops);show_op(cid,oid);return
    if x.startswith("oofferedit:"):
        _,oid,ouid=x.split(":",2);op_offer_edit_menu(cid,oid,ouid);return
    if x.startswith("oretime:"):
        oid=x.split(":",1)[1];op=load(OPERATIONS).get(oid)
        if not op:return
        sent=sum(bool(a.get("sent_at")) for a in op["attacks"].values())
        state(uid,"op_change_time",{"oid":oid})
        send(cid,f"🕒 <b>Изменить время операции</b>\nТекущее: <b>{op['arrival']}</b>\\n"
             f"Введите новую дату и время прибытия по серверу Travian в формате <code>10.10.2026 23:30:00</code>.\\n"
             f"Индивидуальные смещения сохранятся. Уже отправленных атак: {sent} (не изменятся).")
        return
    if x.startswith("oall:"):op_all_edit_menu(cid,x.split(":",1)[1]);return
    if x.startswith("obulk:"):
        _,oid,scope,ouid=x.split(":",3)
        if oid not in load(OPERATIONS):return
        state(uid,"op_bulk_offset",{"oid":oid,"scope":scope,"ouid":ouid})
        send(cid,"⏱ Введите новое смещение в секундах. Оно перезапишет смещение всех выбранных отправок.");return
    if x.startswith('otrmask:'):
        _,oid,key=x.split(':',2);op_remove_target(cid,oid,key);return
    if x.startswith('otrmyes:'):
        parts=x.split(':')
        if len(parts)==4:op_remove_target(cid,parts[1],parts[2],parts[3])
        return
    if x.startswith('oormask:'):
        _,oid,key=x.split(':',2);op_remove_offer(cid,oid,key);return
    if x.startswith('oormyes:'):
        parts=x.split(':')
        if len(parts)==4:op_remove_offer(cid,parts[1],parts[2],parts[3])
        return
    if x.startswith('oofferpick:'):
        parts=x.split(':');page=int(parts[2]) if len(parts)>2 and parts[2].isdigit() else 0
        op_add_offer_picker(cid,parts[1],page,c['message'].get('message_id'));return
    if x.startswith('oofferjoin:'):
        _,oid,ouid=x.split(':',2);op_add_offer(cid,oid,ouid);return
    if x.startswith("oadd:"):op_new_send_picker(cid,x.split(":",1)[1]);return
    if x.startswith("oaddoffer:"):
        _,oid,ouid=x.split(":",2);op=load(OPERATIONS).get(oid)
        if not op:return
        send(cid,"🎯 Выберите цель новой отправки.",[[btn(f"{k} · {t['player']}",f"oaddtarget:{oid}:{ouid}:{k}")] for k,t in op["targets"].items()]);return
    if x.startswith("oaddtarget:"):
        _,oid,ouid,key=x.split(":",3);op_new_send(cid,oid,ouid,key);return
    if x.startswith("opdeleteask:"):
        oid=x.split(":",1)[1]
        op=load(OPERATIONS).get(oid)
        if not op or op.get("status")!="published":return
        send(cid,"Удалить опубликованную операцию без возможности восстановления?",
             [[btn("Да, удалить",f"opdeleteyes:{oid}")],[btn("Отмена",f"op:{oid}")]])
        return
    if x.startswith("opdeleteyes:"):
        oid=x.split(":",1)[1]
        ops=load(OPERATIONS)
        if oid not in ops or ops[oid].get("status")!="published":return
        del ops[oid]
        op_store(ops,"Delete published operation")
        list_ops(cid)
        return
    if x.startswith("odraftask:"):
        oid=x.split(":",1)[1];send(cid,"🗑 Удалить черновик без возможности восстановления?",[[btn("✅ Удалить",f"odraftyes:{oid}")],[btn("⬅️ Отмена",f"op:{oid}")]]);return
    if x.startswith("odraftyes:"):
        oid=x.split(":",1)[1];ops=load(OPERATIONS)
        if ops[oid].get('status')!='draft':send(cid,'Операция уже опубликована. Откройте её заново.');return
        ops.pop(oid);op_store(ops);list_ops(cid);return
    if x=="targets:add":state(uid,"target_coords");send(cid,"➕ Введите координаты цели через пробел.");return
    if x=="targets:list":list_targets(cid);return
    if x.startswith(("newtype:","newprio:")):
        st=getstate(uid) or {}
        # Old priority buttons can finish an already-open wizard after updating.
        expected="target_type" if x.startswith("newtype:") else "target_priority"
        if st.get("step")!=expected:send(cid,"Откройте добавление цели заново.");return
        if x.startswith("newtype:"):
            kind=x.split(":",1)[1]
            if kind not in TARGET_TYPES:send(cid,"Выберите тип цели кнопкой.");return
            st["data"]["type"]=kind
        v=st["data"]["village"];k=f"{v['x']}|{v['y']}";ts=load(TARGETS)
        if k in ts:
            state(uid);send(cid,"Эта цель уже есть в общей базе.");show_target(cid,k);return
        ts[k]={**v,"type":st["data"]["type"],"priority":1,"comment":"","created_at":now(),"updated_at":now()}
        save(TARGETS,ts);state(uid);persist("Add alliance ops target");show_target(cid,k);return
    if x.startswith("target:"):show_target(cid,x.split(":",1)[1]);return
    if x.startswith("targettype:"):
        k=x.split(":",1)[1];send(cid,"🏷 Выберите тип:",[[btn(t,f"settype:{k}:{t}")] for t in TARGET_TYPES]);return
    if x.startswith("settype:"):
        _,k,v=x.split(":",2);ts=load(TARGETS)
        if k not in ts:show_target(cid,k);return
        ts[k]["type"]=v;save(TARGETS,ts);persist("Update alliance ops target");show_target(cid,k);return
    if x.startswith("targetprio:"):
        k=x.split(":",1)[1];send(cid,"⭐ Выберите важность:",[[btn(str(i),f"setprio:{k}:{i}") for i in range(1,6)]]);return
    if x.startswith("setprio:"):
        _,k,v=x.split(":",2);ts=load(TARGETS)
        if k not in ts:show_target(cid,k);return
        ts[k]["priority"]=int(v);save(TARGETS,ts);persist("Update alliance ops target");show_target(cid,k);return
    if x.startswith("targetcomment:"):k=x.split(":",1)[1];state(uid,"target_comment",{"key":k});send(cid,"📝 Введите комментарий. Для очистки отправьте <code>-</code>.");return
    if x.startswith("targetdelete:"):
        k=x.split(":",1)[1];send(cid,f"Удалить <code>{k}</code>?",[[btn("✅ Да",f"confirmdelete:{k}"),btn("❌ Нет",f"target:{k}")]]);return
    if x.startswith("confirmdelete:"):
        k=x.split(":",1)[1];ts=load(TARGETS);ts.pop(k,None);save(TARGETS,ts);persist("Delete alliance ops target");list_targets(cid)

def main():
    ensure()
    migrate_server_times()
    if not TOKEN:raise RuntimeError("ALLIANCE_OPS_TELEGRAM_TOKEN is required")
    print("ALLIANCE OPS BOT",api("getMe").get("username"),flush=True)
    offset=None
    last_target_refresh=None
    last_arena_refresh=None
    while True:
        if last_arena_refresh is None or time.monotonic()-last_arena_refresh>=60:
            last_arena_refresh=time.monotonic()
            try:sync_operation_arenas()
            except Exception:print("Operation arena refresh failed; will retry",flush=True)
        if last_target_refresh is None or time.monotonic()-last_target_refresh>=24*60*60:
            last_target_refresh=time.monotonic()
            try:refresh_target_alliances()
            except Exception:print("Target refresh failed; will retry",flush=True)
        try:
            p={"timeout":25,"allowed_updates":["message","callback_query"]}
            if offset is not None:p["offset"]=offset
            for u in api("getUpdates",p):
                offset=u["update_id"]+1
                try:
                    if "message" in u:handle_message(u["message"])
                    elif "callback_query" in u:callback(u["callback_query"])
                except Exception as e:print("update error",repr(e),flush=True)
        except Exception as e:print("poll error",repr(e),flush=True);time.sleep(5)
        try:send_save_reminders()
        except Exception:print('Save reminder loop failed; will retry',flush=True)
        try:send_reminders()
        except Exception as e:print("reminder loop error",repr(e),flush=True)
if __name__=="__main__":main()


