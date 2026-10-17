import os, re, json, time, html, subprocess, uuid
from datetime import datetime, timezone, timedelta
from pathlib import Path
import requests

TELEGRAM_PROXY_URL = os.environ.get("TELEGRAM_PROXY_URL")
TELEGRAM_PROXIES = {"https": TELEGRAM_PROXY_URL} if TELEGRAM_PROXY_URL else None

TOKEN=os.environ.get("ALLIANCE_OPS_TELEGRAM_TOKEN")
COORDINATORS={317595036}
SNAPSHOTS=Path("data/snapshots")
DATA=Path("data/alliance_ops")
OFFERS=DATA/"offers.json"; TARGETS=DATA/"targets.json"; STATES=DATA/"states.json"; OPERATIONS=DATA/"operations.json"
TZ=timezone(timedelta(hours=3))
TRIBES={1:"Римляне",2:"Германцы",3:"Галлы",6:"Египтяне",7:"Гунны",8:"Спартанцы"}
TROOPS={
1:["Легионер","Преторианец","Империанец","Конница легата","Императорская конница","Конница Цезаря","Таран","Огненная катапульта","Сенатор"],
2:["Дубинщик","Копейщик","Топорщик","Скаут","Паладин","Тевтонская конница","Стенобитное орудие","Катапульта","Вождь"],
3:["Фаланга","Мечник","Следопыт","Гром Теутатеса","Друид-всадник","Эдуйская конница","Таран","Требушет","Предводитель"],
6:["Раб","Страж Аш","Воин Хопеш","Разведчик Сопду","Всадник Анхур","Всадник Решеф","Таран","Камнемёт","Номарх"],
7:["Наёмник","Лучник","Наблюдатель","Степной всадник","Марксман","Мародёр","Таран","Катапульта","Логад"],
8:["Гоплит","Страж","Щитоносец","Разведчик","Элпида","Коринфский всадник","Таран","Баллиста","Эфор"]}
TARGET_TYPES=["Столица","Офф","Деф","Обычная","Не определено"]

def now(): return datetime.now(TZ).isoformat(timespec="seconds")
def ensure():
    DATA.mkdir(parents=True,exist_ok=True)
    for p in (OFFERS,TARGETS,STATES,OPERATIONS):
        if not p.exists(): p.write_text("{}",encoding="utf-8")
def load(p):
    ensure()
    try: return json.loads(p.read_text(encoding="utf-8"))
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
    send(cid,fmt_offer(offer),[[btn('🔄 Войска',f'village:army:{key}'),btn('🏟 Арена',f'village:arena:{key}')],
         [btn('✏️ Изменить координаты',f'village:coords:{key}')],[btn('🗑 Удалить деревню',f'village:delete:{key}')],
         [btn('⬅️ Мои деревни','village:list')]])


def menu(uid):
    rows=[[btn("📋 Мой план","mine:list")],[btn("🏘 Мои офф-деревни","village:list")],[btn("➕ Добавить офф-деревню","village:add")]]
    if uid in COORDINATORS:rows += [[btn("🎯 База целей","targets:list"),btn("➕ Добавить цель","targets:add")],[btn("⚔️ Операции","ops:list"),btn("📝 Создать черновик","ops:new")],[btn("⚔️ Список офферов","offers:ro:list")]]
    return rows
def fmt_offer(o):
    lines=[f"⚔️ <b>Мой офф</b>","",f"Игрок: <b>{html.escape(o['player'])}</b>",f"Деревня: <b>{html.escape(o['village'])}</b>",f"Координаты: <code>{o['x']}|{o['y']}</code>",f"Раса: <b>{TRIBES.get(o['tribe_id'],'Неизвестно')}</b>",f"Арена: <b>{o['arena']}</b>","","<b>Войска:</b>"]
    tr=o.get("army",{}).get("troops",{})
    lines += [f"{html.escape(n)} — {v:,}".replace(",", " ") for n,v in tr.items() if v]
    if not any(tr.values()):lines.append("—")
    lines.append(f"\nОбновлено: <code>{o.get('army',{}).get('updated_at','—')}</code>")
    return "\n".join(lines)
def start(cid,uid):
    if not own_offers(uid) and uid not in COORDINATORS:
        state(uid,"reg_coords");send(cid,"⚔️ <b>Регистрация оффера</b>\n\nВведите координаты своей офф-деревни через пробел.\nНапример: <code>55 46</code>");return
    offers=own_offers(uid)
    detail="Офф-деревень: <b>"+str(len(offers))+"</b>\n"+"\n".join(html.escape(village_label(o)) for o in offers.values()) if offers else "Режим координатора. Офф-деревня не зарегистрирована."
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
    send(cid,txt,[[btn("🏷 Тип",f"targettype:{key}"),btn("⭐ Важность",f"targetprio:{key}")],[btn("📝 Комментарий",f"targetcomment:{key}"),btn("🗑 Удалить",f"targetdelete:{key}")],[btn("⬅️ К списку","targets:list")]])

def op_dt(text):
    for fmt in ("%d.%m.%Y %H:%M:%S","%d.%m.%Y %H:%M"):
        try:return datetime.strptime(text,fmt).replace(tzinfo=TZ)
        except ValueError:pass
    return None

def op_id():
    return datetime.now(TZ).strftime("%Y%m%d%H%M%S")

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
    ops=load(OPERATIONS)
    if not ops:
        send(cid,"⚔️ <b>Операций пока нет.</b>",[[btn("📝 Создать черновик","ops:new")],[btn("⬅️ Меню","menu")]]);return
    rows=[[btn(f"{'📢' if v.get('status')=='published' else '📝'} {v.get('name',k)}",f"op:{k}")] for k,v in reversed(list(ops.items()))]
    rows += [[btn("📝 Создать черновик","ops:new")],[btn("⬅️ Меню","menu")]]
    send(cid,f"⚔️ <b>Операции</b>\nВсего: {len(ops)}",rows)

def show_op(cid,oid):
    op=load(OPERATIONS).get(oid)
    if not op:send(cid,"❌ Операция не найдена.");return
    buttons=[[btn("📊 Готовность и прогресс",f"progress:{oid}")],
             [btn("🎯 По целям",f"optargets:{oid}"),btn("👥 По офферам",f"opoffers:{oid}")],
             [btn("🕒 Изменить время операции",f"oretime:{oid}"),btn("➕ Отправка",f"oadd:{oid}")],
             ]
    if op.get("status")=="published":
        buttons.insert(0,[btn("📣 Повторить рассылку",f"publish:{oid}")])
        buttons.append([btn("🗑 Удалить операцию",f"opdeleteask:{oid}")])
    else:
        buttons.insert(0,[btn("📢 Опубликовать",f"publish:{oid}")])
        buttons.append([btn("🗑 Удалить черновик",f"odraftask:{oid}")])
    buttons.append([btn("⬅️ Операции","ops:list")])
    send(cid,op_summary(op),buttons)

def op_targets(cid,oid):
    op=load(OPERATIONS).get(oid)
    if not op:return
    rows=[]
    for k,t in op["targets"].items():
        n=sum(1 for a in op["attacks"].values() if a["target_key"]==k)
        rows.append([btn(f"{op_mode_name(t['mode'])} · {k} · {n}",f"optarget:{oid}:{k}")])
    rows.append([btn("⬅️ К операции",f"op:{oid}")])
    send(cid,"🎯 <b>Цели операции</b>",rows)

def op_offers(cid,oid):
    op=load(OPERATIONS).get(oid)
    if not op:return
    rows=[]
    for uid,o in op["offers"].items():
        n=sum(1 for a in op["attacks"].values() if a["offer_id"]==uid)
        off=o.get("offset",0); sign="+" if off>0 else ""
        rows.append([btn(f"{village_label(o)} · {sign}{off} сек · {n}",f"opoffer:{oid}:{uid}")])
    rows.append([btn("⬅️ К операции",f"op:{oid}")])
    send(cid,"👥 <b>Офферы операции</b>",rows)

def op_target_detail(cid,oid,key):
    op=load(OPERATIONS).get(oid)
    if not op or key not in op["targets"]:return
    t=op["targets"][key]; lines=[f"🎯 <b>{html.escape(t['player'])} — {html.escape(t['village'])}</b>",f"<code>{key}</code> · {op_mode_name(t['mode'])}",""]
    for a in op["attacks"].values():
        if a["target_key"]==key:
            lines.append(f"• {html.escape(a['offer_player'])}: <code>{a['arrival']}</code> · {a['waves']} волн")
    rows=[[btn(f"⚔️ {a['offer_player']} · {a['arrival']}",f"oa:{oid}:{a['id']}")] for a in op["attacks"].values() if a["target_key"]==key]
    rows.append([btn("⬅️ К целям",f"optargets:{oid}")]);send(cid,"\n".join(lines),rows)

def op_offer_detail(cid,oid,uid):
    op=load(OPERATIONS).get(oid)
    if not op or uid not in op["offers"]:return
    o=op["offers"][uid]; lines=[f"👤 <b>{html.escape(o['player'])}</b>",f"Смещение: <b>{o['offset']:+d} сек</b>",""]
    for a in op["attacks"].values():
        if a["offer_id"]==uid:
            t=op["targets"][a["target_key"]]
            lines.append(f"• {op_mode_name(a['mode'])} <code>{a['target_key']}</code> {html.escape(t['player'])} — <code>{a['arrival']}</code> · {a['waves']} волн")
    rows=[[btn(f"⚔️ {a['target_key']} · {a['arrival']}",f"oa:{oid}:{a['id']}")] for a in op["attacks"].values() if a["offer_id"]==uid]
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
    remaining=set(targets);changed=False
    for row in rows(snapshot.read_text(encoding='utf-8',errors='replace')):
        try:
            a=split_sql(row)
            if len(a)<11:continue
            key=f'{int(clean(a[1]))}|{int(clean(a[2]))}'
            if key not in remaining:continue
            update={'alliance_id':int(clean(a[8])),'alliance':clean(a[9]),
                    'player_id':int(clean(a[6])),'player':clean(a[7]),'village_id':int(clean(a[4])),
                    'village':clean(a[5]),'alliance_snapshot':snapshot.name,'map_missing':False}
            if any(targets[key].get(k)!=v for k,v in update.items()):targets[key].update(update);changed=True
            remaining.remove(key)
        except (ValueError,IndexError,TypeError):continue
    for key in remaining:
        if not targets[key].get('map_missing'):targets[key]['map_missing']=True;changed=True
    if changed:save(TARGETS,targets);persist('Refresh target alliances from map snapshot')
    return targets


def op_alliance_picker(cid,d):
    targets=refresh_target_alliances();groups={}
    for target in targets.values():
        key=target_alliance_key(target)
        group=groups.setdefault(key,{'name':target_alliance_name(target),'count':0});group['count']+=1
    buttons=[[btn(f"{g['name']} · {g['count']} целей",f'opalliance:{key}')]
             for key,g in sorted(groups.items(),key=lambda item:(item[0] in ('0','unknown'),item[1]['name'].casefold(),item[0]))]
    text='🏳️ <b>Выберите альянс для операции</b>\nЗатем будут доступны только цели этого альянса. Данные — по последнему доступному снимку карты.'
    if not groups:text+='\n\nБаза целей пуста. Сначала добавьте цели.'
    if 'unknown' in groups:text+='\n«Альянс не определён»: нет данных об альянсе или деревня отсутствует в снимке.'
    buttons.append([btn('⬅️ Меню','menu')]);send(cid,text,buttons)


def op_target_picker(cid,d):
    if 'alliance_key' not in d:op_alliance_picker(cid,d);return
    targets=load(TARGETS);selected=d.get('targets',{});buttons=[]
    eligible={k:t for k,t in targets.items() if target_alliance_key(t)==d['alliance_key']}
    for key,target in eligible.items():
        mark={'spam':'🟡','destroy':'🔥','capture':'👑'}.get(selected.get(key),'⬜')
        buttons.append([btn(f"{mark} {key} · {target.get('player','?')} · {target.get('type','?')}",f'optargetpick:{key}')])
    count=len(set(selected)&set(eligible))
    buttons.append([btn(f'⚙️ Создать черновик ({count})','opgenerate')])
    buttons.append([btn('🏳️ Сменить альянс','opalliance:back')])
    send(cid,f"🎯 <b>Цели операции · {html.escape(d.get('alliance_name',''))}</b>\n\nНажмите, чтобы добавить или убрать цель. Все отправки создаются как спам; реальные атаки можно настроить в черновике."+('\nЦелей в этой группе больше нет — выберите другой альянс.' if not eligible else ''),buttons)

def generate_op(uid,d):
    offers_all=active_offers(); targets_all=refresh_target_alliances(); oid=op_id()
    if not d.get('targets') or 'alliance_key' not in d or any(key not in targets_all or target_alliance_key(targets_all[key])!=d['alliance_key'] for key in d['targets']):
        raise ValueError('Цели или их альянс изменились. Выберите альянс и цели заново.')
    if any(key not in offers_all for key in d.get('offers',[])):raise ValueError('Офф-деревня удалена. Выберите офферов заново.')
    arrival_dt=datetime.fromisoformat(d["arrival_iso"])
    op={"id":oid,"name":"Операция","status":"draft","arrival":arrival_dt.strftime("%d.%m.%Y %H:%M:%S"),
        "arrival_iso":d["arrival_iso"],"base_speed":d["base_speed"],"created_at":now(),"created_by":uid,
        "comment":"","offers":{},"targets":{},"attacks":{},
        "enemy_alliance_key":d["alliance_key"],"enemy_alliance":d.get("alliance_name","")}
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
            actual=arrival_dt+timedelta(seconds=o["offset"])
            op["attacks"][str(i)]={"id":str(i),"offer_id":ouid,"offer_player":o["player"],"target_key":key,
                "mode":defaults["mode"],"waves":defaults["waves"],"wave_plan":defaults["wave_plan"],
                "comment":"","offset":o["offset"],"arrival":actual.strftime("%d.%m.%Y %H:%M:%S"),
                "arrival_iso":actual.isoformat(),"speed":d["base_speed"],"arena":o["arena"]}
    ops=load(OPERATIONS)
    numbers=[int(m.group(1)) for existing in ops.values()
             if (m:=re.fullmatch(r"Операция №(\\d+)",str(existing.get("name",""))))]
    op["name"]=f"Операция №{max(numbers,default=0)+1}"
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
            if {k:{f:v for f,v in a.items() if f not in ("sent_at","reminder_sent_for")} for k,a in old_jobs.items()}=={k:{f:v for f,v in a.items() if f not in ("sent_at","reminder_sent_for")} for k,a in new_jobs.items()} or not (old_jobs or new_jobs):continue
            op.setdefault("ready",{}).pop(uid,None)
            for a in new_jobs.values():
                a.pop("reminder_sent_for",None)
            try:send(int(uid),f"⚠️ <b>{html.escape(op['name'])}: план изменён!</b>\nПроверьте задания и повторно подтвердите готовность.",[[btn("📋 Открыть план",f"mine:op:{oid}")]])
            except Exception as e:print("change notification error",uid,repr(e),flush=True)
    save(OPERATIONS,ops)

def op_retime(op,a):
    dt=datetime.fromisoformat(op["arrival_iso"])+timedelta(seconds=int(a["offset"]))
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
    return datetime.fromisoformat(a["arrival_iso"])-timedelta(seconds=round(hours*3600)),dist

def op_attack_view(cid,oid,aid):
    op=load(OPERATIONS).get(oid)
    if not op or aid not in op["attacks"]:send(cid,"❌ Отправка не найдена.");return
    a=op["attacks"][aid];t=op["targets"][a["target_key"]];o=op["offers"][a["offer_id"]]
    departure,dist=op_travel(a,op)
    waves="\n".join(f"{i}. {html.escape(w.get('text','—'))}" for i,w in enumerate(a["wave_plan"],1))
    msg=(f"⚔️ <b>{html.escape(o['player'])} → {html.escape(t['player'])}</b>\n"
         f"🎯 <code>{a['target_key']}</code> · {op_mode_name(a['mode'])}\n"
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
    op=load(OPERATIONS).get(oid)
    if not op or aid not in op["attacks"]:return
    a=op["attacks"][aid]
    rows=[[btn(f"✏️ Волна {i}: {w.get('text','')[:30]}",f"oedit:{oid}:{aid}:wave:{i-1}")] for i,w in enumerate(a["wave_plan"],1)]
    rows += [[btn("➕ Волна",f"owadd:{oid}:{aid}"),btn("➖ Убрать последнюю",f"owdel:{oid}:{aid}")],[btn("⬅️ Отправка",f"oa:{oid}:{aid}")]]
    send(cid,f"🌊 <b>Волны отправки №{aid}</b>\nРедактируйте состав каждой волны обычным текстом.",rows)

def op_offer_edit_menu(cid,oid,ouid):
    op=load(OPERATIONS).get(oid)
    if not op or ouid not in op["offers"]:return
    o=op["offers"][ouid]
    send(cid,f"👥 <b>{html.escape(o['player'])}</b>\nОбщее смещение: {o['offset']:+d} сек\n\nИзменение перезапишет смещение <b>всех</b> отправок этого оффера.",
         [[btn("⏱ Изменить смещение всех",f"obulk:{oid}:offer:{ouid}")],[btn("⬅️ Офферы",f"opoffers:{oid}")]])

def op_all_edit_menu(cid,oid):
    send(cid,"⏱ <b>Массовое изменение</b>\nЗадать одинаковое смещение всем отправкам операции (включая ранее изменённые).",
         [[btn("⏱ Установить смещение всем",f"obulk:{oid}:all:all")],[btn("⬅️ Операция",f"op:{oid}")]])

def op_new_send_picker(cid,oid):
    op=load(OPERATIONS).get(oid)
    if not op:return
    send(cid,"➕ <b>Новая отправка</b>\nВыберите оффера.",[[btn(village_label(o),f"oaddoffer:{oid}:{uid}")] for uid,o in op["offers"].items()]+[[btn("⬅️ Операция",f"op:{oid}")]])

def op_new_send(cid,oid,ouid,key):
    ops=load(OPERATIONS);op=ops.get(oid)
    if not op or ouid not in op["offers"] or key not in op["targets"]:return
    o=op["offers"][ouid];t=op["targets"][key]
    aid=str(max([int(k) for k in op["attacks"] if k.isdigit()] or [0])+1)
    defaults=op_attack_defaults(t["mode"],t)
    a={"id":aid,"offer_id":ouid,"offer_player":o["player"],"target_key":key,
       "mode":defaults["mode"],"waves":defaults["waves"],"wave_plan":defaults["wave_plan"],
       "comment":"","offset":o["offset"],"speed":op["base_speed"],"arena":o["arena"]}
    op_retime(op,a);op["attacks"][aid]=a;op_store(ops);op_attack_view(cid,oid,aid)


def personal_jobs(op,uid):
    jobs=[a for a in op.get("attacks",{}).values() if op_owner(op,a.get("offer_id"))==str(uid)]
    return sorted(jobs,key=lambda a:(op_travel(a,op)[0] or datetime.max.replace(tzinfo=TZ),str(a["id"])))

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
            arrivals=[datetime.fromisoformat(a["arrival_iso"]) for a in attacks]
            if all(dt.tzinfo is not None and dt<=current for dt in arrivals):
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
    oid,op=max(available,key=lambda pair:max(
        (a.get("arrival_iso","") for a in pair[1].get("attacks",{}).values()),default=""))
    personal_op(cid,uid,oid)

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
            and not a.get("sent_at") and op_travel(a,op)[0] and op_travel(a,op)[0]>current]


def selected_real(op,uid,aid=None):
    jobs=real_jobs(op,uid)
    return next((a for a in jobs if str(a["id"])==str(aid)),None) if aid else (jobs[0] if jobs else None)


def save_trip(origin,point,arena,departure):
    dx=abs(int(origin["x"])-point[0]);dy=abs(int(origin["y"])-point[1])
    distance=(min(dx,401-dx)**2+min(dy,401-dy)**2)**0.5
    if not distance:raise ValueError("Сейв-точка совпадает с вашей офф-деревней.")
    seconds=round((min(distance,20)/3+max(0,distance-20)/(3*(1+int(arena)*.2)))*3600)
    back=departure-timedelta(minutes=1)
    return back-timedelta(seconds=2*seconds),back-timedelta(seconds=seconds),back,distance


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
        key="before" if dt<departure else "after" if dt>departure else "same"
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
               f"Отправка: <b>{departure.strftime('%d.%m.%Y %H:%M:%S')}</b> (МСК)",""]
        if kind=="save":
            origin=op['offers'][real['offer_id']];offer=current_plan_offer(op,real['offer_id']);arena=int(offer.get('arena',origin['arena']))
            lines.extend([f"Скорость: <b>3</b> · Текущая арена: <b>{arena}</b>","Полный поход туда и обратно, без бонусов героя и артефактов."])
            points=offer.get('save_points',[])
            if not points:lines.append("Сейв-точки ещё не заданы.")
            for point in points:
                try:start,arrival,back,distance=save_trip(origin,point,arena,departure)
                except ValueError:continue
                lines.extend(["",f"📍 <b>{point[0]}|{point[1]}</b> · {distance:.2f} клеток",
                              f"Уйти: <code>{start.strftime('%d.%m %H:%M:%S')}</code>"+(" — время уже прошло" if start<=datetime.now(TZ) else ""),
                              f"Прибыть в точку: {arrival.strftime('%d.%m %H:%M:%S')}",f"Вернуться: <b>{back.strftime('%d.%m %H:%M:%S')}</b>"])
            lines.extend(["","Выбирайте проверенные свободные оазисы или неактивные деревни: бот не проверяет гарнизон точки.","",spam_hint(op,uid,real)])
        else:lines.append(spam_hint(op,uid,real))
        buttons.extend([[btn(f"🎯 {op['offers'][a['offer_id']]['x']}|{op['offers'][a['offer_id']]['y']} → {a['target_key']} · {op_travel(a,op)[0].strftime('%H:%M:%S')}",f"mine:{kind}:{oid}:{a['id']}")] for a in jobs if a['id']!=real['id']])
    else:lines=["В плане нет предстоящей реальной атаки. Сейв рассчитывается для уничтожения или захвата; спам не служит временем возврата."]
    if kind=="save":buttons.append([btn("✏️ Задать сейв-точки",f"mine:points:{oid}:{real['id'] if real else '-'}")])
    buttons.append([btn("⬅️ Весь план",f"mine:op:{oid}")])
    send(cid,"\n".join(lines),buttons)


def personal_op(cid,uid,oid,message_id=None):
    op=load(OPERATIONS).get(oid)
    if not op or op.get("status")!="published" or str(uid) not in op_members(op):
        send(cid,"⛔ Этот план недоступен.");return
    jobs=personal_jobs(op,uid)
    done=sum(bool(a.get("sent_at")) for a in jobs)
    current=datetime.now(TZ)
    pending=[(op_travel(a,op)[0],a) for a in jobs if not a.get("sent_at")]
    future=[(dt,a) for dt,a in pending if dt and dt>current]
    overdue=[(dt,a) for dt,a in pending if dt and dt<=current]
    lines=[f"⚔️ <b>{html.escape(op['name'])}</b>",
           f"Готовность: {'✅ подтверждена' if op.get('ready',{}).get(str(uid)) else '⏳ не подтверждена'}",
           f"Отправлено: <b>{done} из {len(jobs)}</b>",""]
    if future:
        dt,a=min(future,key=lambda z:z[0])
        remaining=max(0,int((dt-current).total_seconds()))
        h,rem=divmod(remaining,3600);m,sec=divmod(rem,60)
        lines.append(f"⏰ Следующая: <b>{dt.strftime('%d.%m %H:%M:%S')}</b> → <code>{a['target_key']}</code>")
        lines.append(f"⌛ До отправки: <b>{h:02d}:{m:02d}:{sec:02d}</b>")
    if overdue:
        lines.append(f"🔴 Просроченных без отметки: <b>{len(overdue)}</b>")
    if not pending:lines.append("✅ Все отправки отмечены выполненными.")
    lines.append(f"🔄 Обновлено: {current.strftime('%H:%M:%S')}")
    buttons=[[btn("🔄 Обновить",f"mine:refresh:{oid}")],
             [btn("🛡 Сейв-точки",f"mine:save:{oid}"),btn("💡 Юниты для спама",f"mine:spam:{oid}")]]
    buttons += [[btn(f"{'✅' if a.get('sent_at') else '🔴' if dt and dt<=current else '⏳'} {dt.strftime('%H:%M:%S') if dt else '—'} · {op['offers'][a['offer_id']]['x']}|{op['offers'][a['offer_id']]['y']} → {a['target_key']}",f"mine:job:{oid}:{a['id']}")]
                for a in jobs[:70] for dt in [op_travel(a,op)[0]]]
    if not op.get("ready",{}).get(str(uid)):
        buttons.append([btn("✅ Подтверждаю готовность",f"mine:ready:{oid}")])
    buttons.append([btn("⬅️ Мой план","mine:list")])
    message="\n".join(lines)
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
         f"{op_mode_name(a['mode'])}\nОфф-деревня: <b>{html.escape(village_label(op['offers'][a['offer_id']]))}</b>\n"
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
        grouped={}
        for a in op.get("attacks",{}).values():
            if a.get("sent_at"):continue
            departure,_=op_travel(a,op)
            if not departure:continue
            seconds=(departure-current).total_seconds()
            marker=departure.isoformat()
            if not 0<seconds<=300 or a.get("reminder_sent_for")==marker:continue
            grouped.setdefault(op_owner(op,a["offer_id"]),[]).append((departure,a,marker))
        for offer_uid,jobs in grouped.items():
            jobs.sort(key=lambda item:(item[0],str(item[1]["id"])))
            lines=[f"⏰ <b>{html.escape(op['name'])}: отправки в ближайшие 5 минут</b>"]
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
                    a["reminder_sent_for"]=marker
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
    if step=="save_points":
        op=personal_operation(uid,d["oid"]);offers=load(OFFERS)
        real=selected_real(op,uid,d.get('aid')) if op else None
        key=d.get('key') or (real['offer_id'] if real else str(uid));offer=owns_offer(uid,key)
        if not op or not offer:state(uid);send(cid,"⛔ План или офф-деревня недоступны.");return
        try:
            points=save_points_parse(text)
            origin=op['offers'][key]
            if not same_origin(offer,origin):raise ValueError('Деревня в плане изменилась. Обратитесь к координатору.')
            if [int(origin['x']),int(origin['y'])] in points:raise ValueError("Сейв-точка не должна совпадать с вашей офф-деревней.")
        except ValueError as exc:send(cid,"❌ "+str(exc));return
        offers[key]['save_points']=points;save(OFFERS,offers);persist("Update alliance ops save points");state(uid)
        send(cid,"✅ Сейв-точки сохранены." if points else "✅ Сейв-точки очищены.")
        personal_support(cid,uid,d['oid'],"save",d.get("aid"));return
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
        ops=load(OPERATIONS);affected=0
        for op in ops.values():
            if op.get("status")!="published" or key not in op.get("offers",{}) or not same_origin(os_[key],op["offers"][key]):continue
            op["offers"][key]["arena"]=int(text)
            for a in op["attacks"].values():
                if str(a["offer_id"])==key and not a.get("sent_at"):
                    a["arena"]=int(text);a.pop("reminder_sent_for",None);affected+=1
        if affected:op_store(ops)
        send(cid,f"✅ Арена обновлена. Пересчитано отправок: {affected}.",menu(uid));return

    if step=="op_arrival":
        dt=op_dt(text)
        if not dt:send(cid,"❌ Формат: <code>05.10.2026 20:00:00</code>");return
        d["arrival_iso"]=dt.isoformat();d["base_speed"]=3
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
        if 'alliance_key' in d:state(uid,'op_pick_targets',d);op_target_picker(cid,d)
        else:state(uid,'op_pick_alliance',d);op_alliance_picker(cid,d)
        return

    if step=="op_edit_value":
        if uid not in COORDINATORS:return
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
            a["arena"]=int(text)
        elif field=="comment":a["comment"]="" if text=="-" else text
        elif field.startswith("wave:"):
            idx=int(field.split(":")[1])
            if idx>=len(a["wave_plan"]):send(cid,"❌ Волна не найдена.");return
            a["wave_plan"][idx]["text"]=text
        else:return
        a["waves"]=len(a["wave_plan"]);op_store(ops);state(uid);op_attack_view(cid,oid,aid);return
    if step=="op_change_time":
        if uid not in COORDINATORS:return
        dt=op_dt(text)
        if not dt:
            send(cid,"❌ Введите дату и время: <code>10.10.2026 23:30:00</code>");return
        oid=d["oid"];ops=load(OPERATIONS);op=ops.get(oid)
        if not op:state(uid);send(cid,"❌ Операция не найдена.");return
        old_dt=datetime.fromisoformat(op["arrival_iso"])
        delta=dt-old_dt
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
            changed+=1
        op_store(ops,"Change operation arrival time")
        state(uid)
        send(cid,f"✅ Новое время операции: <b>{op['arrival']}</b>. Пересчитано отправок: {changed}. Уже отправленных без изменений: {sent}. Индивидуальные смещения сохранены.")
        show_op(cid,oid)
        return
    if step=="op_bulk_offset":
        if uid not in COORDINATORS:return
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
    if x=="menu":state(uid);start(cid,uid);return
    if x=="offers:ro:list":
        if uid not in COORDINATORS:return
        coordinator_offer_list(cid);return
    if x.startswith("offers:ro:view:"):
        if uid not in COORDINATORS:return
        coordinator_offer_view(cid,x.rsplit(":",1)[1]);return
    if x.startswith(("mine:save:","mine:spam:","mine:points:")):
        parts=x.split(":");kind=parts[1];oid=parts[2];aid=parts[3] if len(parts)>3 and parts[3]!="-" else None
        op=personal_operation(uid,oid)
        if not op:send(cid,"⛔ Этот план недоступен.");return
        if kind=="points":
            real=selected_real(op,uid,aid)
            if not real:send(cid,'Выберите предстоящую реальную атаку.');return
            key=real['offer_id'];offer=owns_offer(uid,key)
            if not offer or not same_origin(offer,op['offers'][key]):send(cid,'Деревня этого плана удалена или изменена. Обратитесь к координатору.');return
            state(uid,"save_points",{"oid":oid,"aid":real['id'],"key":key})
            existing=offer.get('save_points',[])
            text="🛡 <b>Сейв-точки</b>\nВведите до 10 координат, каждую с новой строки:\n<code>13|3\n-20 45</code>\nСписок заменит предыдущий. Для очистки отправьте <code>-</code>."
            if existing:text+="\nСохранены: "+", ".join(f"{p[0]}|{p[1]}" for p in existing)
            send(cid,text,[[btn("Отмена",f"mine:save:{oid}")]]);return
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
        if uid not in COORDINATORS:return
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
        if uid in COORDINATORS:operation_progress(cid,x.split(":",1)[1])
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
        elif action=='army':
            state(uid,'army',{'key':key,'tribe_id':offer['tribe_id']});send(cid,'🔄 Обновите войска этой деревни:\n<pre>'+html.escape(template(offer['tribe_id']))+'</pre>')
        elif action=='arena':state(uid,'arena',{'key':key});send(cid,'🏟 Введите уровень арены этой деревни: 0–20.')
        elif action=='coords':
            state(uid,'reg_coords',{'key':key});send(cid,'✏️ Введите новые координаты. Затем укажите арену и войска новой деревни. Сейв-точки будут очищены. Уже созданные планы сохранят прежние координаты; для изменения плана обратитесь к координатору.')
        elif action=='delete':send(cid,'Удалить эту офф-деревню из регистрации? В уже созданных планах она сохранится.',[[btn('🗑 Да, удалить',f'village:remove:{key}')],[btn('Отмена',f'village:view:{key}')]])
        elif action=='remove':
            offers=load(OFFERS);offers[key]['deleted_at']=now();save(OFFERS,offers);persist('Remove registered offence village');personal_villages(cid,uid)
        return
    if x.startswith(("targets","target","newtype:","newprio:","settype:","setprio:","confirmdelete:","ops","op","oa:","ow","oe","ot","od","ob","oall:","oofferedit:","oadd")) and uid not in COORDINATORS:send(cid,"⛔ Только для координатора.");return

    if x=="ops:list":list_ops(cid);return
    if x=="ops:new":state(uid,"op_pick_alliance",{});op_alliance_picker(cid,{});return
    if x.startswith('opalliance:'):
        st=getstate(uid)
        if not st or st['step'] not in ('op_pick_alliance','op_pick_targets'):return
        d=st['data'];key=x.split(':',1)[1]
        if key=='back':state(uid,'op_pick_alliance',d);op_alliance_picker(cid,d);return
        targets=load(TARGETS);target=next((t for t in targets.values() if target_alliance_key(t)==key),None)
        if target is None:send(cid,'Целей этого альянса больше нет.');op_alliance_picker(cid,d);return
        if d.get('alliance_key')!=key:d['targets']={}
        d['alliance_key']=key;d['alliance_name']=target_alliance_name(target)
        if d.get('arrival_iso'):
            state(uid,'op_pick_targets',d);op_target_picker(cid,d)
        else:
            state(uid,'op_arrival',d);send(cid,'🕐 <b>Новая операция</b>\nАльянс: <b>'+html.escape(d['alliance_name'])+'</b>\nВведите дату и время прибытия.\nФормат: <code>05.10.2026 20:00:00</code>')
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
        if uid not in COORDINATORS:return
        st=getstate(uid)
        if not st or st["step"]!="op_pick_targets":return
        d=st["data"];key=x.split(":",1)[1]
        target=load(TARGETS).get(key)
        if not target or target_alliance_key(target)!=d.get('alliance_key'):
            send(cid,'Эта цель не относится к выбранному альянсу.');return
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
        try:oid=generate_op(uid,d)
        except ValueError as exc:
            send(cid,'❌ '+str(exc))
            if any(key not in active_offers() for key in d.get('offers',[])):
                d['offers']=[];d['offsets']={};state(uid,'op_pick_offers',d);op_offer_picker(cid,d)
            else:d['targets']={};state(uid,'op_pick_alliance',d);op_alliance_picker(cid,d)
            return
        state(uid);show_op(cid,oid);return
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
        if uid not in COORDINATORS:return
        oid=x.split(":",1)[1];op=load(OPERATIONS).get(oid)
        if not op:return
        sent=sum(bool(a.get("sent_at")) for a in op["attacks"].values())
        state(uid,"op_change_time",{"oid":oid})
        send(cid,f"🕒 <b>Изменить время операции</b>\nТекущее: <b>{op['arrival']}</b>\\n"
             f"Введите новую дату и время прибытия в формате <code>10.10.2026 23:30:00</code>.\\n"
             f"Индивидуальные смещения сохранятся. Уже отправленных атак: {sent} (не изменятся).")
        return
    if x.startswith("oall:"):op_all_edit_menu(cid,x.split(":",1)[1]);return
    if x.startswith("obulk:"):
        _,oid,scope,ouid=x.split(":",3)
        if oid not in load(OPERATIONS):return
        state(uid,"op_bulk_offset",{"oid":oid,"scope":scope,"ouid":ouid})
        send(cid,"⏱ Введите новое смещение в секундах. Оно перезапишет смещение всех выбранных отправок.");return
    if x.startswith("oadd:"):op_new_send_picker(cid,x.split(":",1)[1]);return
    if x.startswith("oaddoffer:"):
        _,oid,ouid=x.split(":",2);op=load(OPERATIONS).get(oid)
        if not op:return
        send(cid,"🎯 Выберите цель новой отправки.",[[btn(f"{k} · {t['player']}",f"oaddtarget:{oid}:{ouid}:{k}")] for k,t in op["targets"].items()]);return
    if x.startswith("oaddtarget:"):
        _,oid,ouid,key=x.split(":",3);op_new_send(cid,oid,ouid,key);return
    if x.startswith("opdeleteask:"):
        if uid not in COORDINATORS:return
        oid=x.split(":",1)[1]
        op=load(OPERATIONS).get(oid)
        if not op or op.get("status")!="published":return
        send(cid,"Удалить опубликованную операцию без возможности восстановления?",
             [[btn("Да, удалить",f"opdeleteyes:{oid}")],[btn("Отмена",f"op:{oid}")]])
        return
    if x.startswith("opdeleteyes:"):
        if uid not in COORDINATORS:return
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
        oid=x.split(":",1)[1];ops=load(OPERATIONS);ops.pop(oid,None);op_store(ops);list_ops(cid);return
    if x=="targets:add":state(uid,"target_coords");send(cid,"➕ Введите координаты цели через пробел.");return
    if x=="targets:list":list_targets(cid);return
    if x.startswith("newtype:"):
        st=getstate(uid);d=st["data"];d["type"]=x.split(":",1)[1];state(uid,"target_priority",d);send(cid,"⭐ Важность цели:",[[btn(str(i),f"newprio:{i}") for i in range(1,6)]]);return
    if x.startswith("newprio:"):
        st=getstate(uid);v=st["data"]["village"];k=f"{v['x']}|{v['y']}";ts=load(TARGETS);ts[k]={**v,"type":st["data"]["type"],"priority":int(x.split(":")[1]),"comment":"","created_at":now(),"updated_at":now()};save(TARGETS,ts);state(uid);persist("Add alliance ops target");show_target(cid,k);return
    if x.startswith("target:"):show_target(cid,x.split(":",1)[1]);return
    if x.startswith("targettype:"):
        k=x.split(":",1)[1];send(cid,"🏷 Выберите тип:",[[btn(t,f"settype:{k}:{t}")] for t in TARGET_TYPES]);return
    if x.startswith("settype:"):
        _,k,v=x.split(":",2);ts=load(TARGETS);ts[k]["type"]=v;save(TARGETS,ts);persist("Update alliance ops target");show_target(cid,k);return
    if x.startswith("targetprio:"):
        k=x.split(":",1)[1];send(cid,"⭐ Выберите важность:",[[btn(str(i),f"setprio:{k}:{i}") for i in range(1,6)]]);return
    if x.startswith("setprio:"):
        _,k,v=x.split(":",2);ts=load(TARGETS);ts[k]["priority"]=int(v);save(TARGETS,ts);persist("Update alliance ops target");show_target(cid,k);return
    if x.startswith("targetcomment:"):k=x.split(":",1)[1];state(uid,"target_comment",{"key":k});send(cid,"📝 Введите комментарий. Для очистки отправьте <code>-</code>.");return
    if x.startswith("targetdelete:"):
        k=x.split(":",1)[1];send(cid,f"Удалить <code>{k}</code>?",[[btn("✅ Да",f"confirmdelete:{k}"),btn("❌ Нет",f"target:{k}")]]);return
    if x.startswith("confirmdelete:"):
        k=x.split(":",1)[1];ts=load(TARGETS);ts.pop(k,None);save(TARGETS,ts);persist("Delete alliance ops target");list_targets(cid)

def main():
    ensure()
    if not TOKEN:raise RuntimeError("ALLIANCE_OPS_TELEGRAM_TOKEN is required")
    print("ALLIANCE OPS BOT",api("getMe").get("username"),flush=True)
    offset=None
    while True:
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
        try:send_reminders()
        except Exception as e:print("reminder loop error",repr(e),flush=True)
if __name__=="__main__":main()
