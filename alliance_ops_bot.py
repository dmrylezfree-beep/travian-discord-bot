import os, re, json, time, html, subprocess
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
    m=re.fullmatch(r"\s*(-?\d{1,3})\s+(?:\|\s*)?(-?\d{1,3})\s*",t)
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
def menu(uid):
    rows=[[btn("⚔️ Мой офф","offer:view")],[btn("🔄 Обновить войска","offer:army"),btn("🏟 Изменить арену","offer:arena")]]
    if uid in COORDINATORS:rows += [[btn("🎯 База целей","targets:list"),btn("➕ Добавить цель","targets:add")],[btn("⚔️ Операции","ops:list"),btn("📝 Создать черновик","ops:new")]]
    return rows
def fmt_offer(o):
    lines=[f"⚔️ <b>Мой офф</b>","",f"Игрок: <b>{html.escape(o['player'])}</b>",f"Деревня: <b>{html.escape(o['village'])}</b>",f"Координаты: <code>{o['x']}|{o['y']}</code>",f"Раса: <b>{TRIBES.get(o['tribe_id'],'Неизвестно')}</b>",f"Арена: <b>{o['arena']}</b>","","<b>Войска:</b>"]
    tr=o.get("army",{}).get("troops",{})
    lines += [f"{html.escape(n)} — {v:,}".replace(",", " ") for n,v in tr.items() if v]
    if not any(tr.values()):lines.append("—")
    lines.append(f"\nОбновлено: <code>{o.get('army',{}).get('updated_at','—')}</code>")
    return "\n".join(lines)
def start(cid,uid):
    if str(uid) not in load(OFFERS) and uid not in COORDINATORS:
        state(uid,"reg_coords");send(cid,"⚔️ <b>Регистрация оффера</b>\n\nВведите координаты своей офф-деревни через пробел.\nНапример: <code>55 46</code>");return
    o=load(OFFERS).get(str(uid))
    detail=fmt_offer(o) if o else "Режим координатора. Офф-деревня не зарегистрирована."
    send(cid,"⚔️ <b>Центр операций альянса</b>\n\n"+detail+"\n\nВыберите действие:",menu(uid))
def list_targets(cid):
    ts=load(TARGETS)
    if not ts:send(cid,"🎯 <b>База целей пуста.</b>",[[btn("➕ Добавить цель","targets:add")],[btn("⬅️ Меню","menu")]]);return
    rows=[[btn(f"{k} · {v.get('player','?')} · {v.get('type','?')}",f"target:{k}")] for k,v in ts.items()]
    rows.append([btn("➕ Добавить цель","targets:add"),btn("⬅️ Меню","menu")]);send(cid,f"🎯 <b>База целей</b>\nВсего: {len(ts)}",rows)
def show_target(cid,key):
    t=load(TARGETS).get(key)
    if not t:send(cid,"❌ Цель не найдена.");return
    txt=f"🎯 <b>{html.escape(t['village'])}</b>\nКоординаты: <code>{key}</code>\nИгрок: <b>{html.escape(t['player'])}</b>\nАльянс: <b>{html.escape(t.get('alliance') or '—')}</b>\nНаселение: {t.get('population','—')}\nРаса: {TRIBES.get(t.get('tribe_id'),'Неизвестно')}\n\nТип: <b>{t.get('type','Не определено')}</b>\nВажность: <b>{t.get('priority',1)}/5</b>\nКомментарий: {html.escape(t.get('comment') or '—')}"
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
            f"Статус: <b>ЧЕРНОВИК</b>\n\n"
            f"🕐 Базовый приход: <code>{html.escape(op['arrival'])}</code>\n"
            f"🐎 Базовая скорость: <b>{op['base_speed']}</b>\n"
            f"👥 Офферов: <b>{len(op['offers'])}</b>\n"
            f"🎯 Целей: <b>{len(op['targets'])}</b>\n"
            f"⚔️ Отправок: <b>{len(op['attacks'])}</b>")

def list_ops(cid):
    ops=load(OPERATIONS)
    if not ops:
        send(cid,"⚔️ <b>Операций пока нет.</b>",[[btn("📝 Создать черновик","ops:new")],[btn("⬅️ Меню","menu")]]);return
    rows=[[btn(f"📝 {v.get('name',k)}",f"op:{k}")] for k,v in reversed(list(ops.items()))]
    rows += [[btn("📝 Создать черновик","ops:new")],[btn("⬅️ Меню","menu")]]
    send(cid,f"⚔️ <b>Операции</b>\nВсего: {len(ops)}",rows)

def show_op(cid,oid):
    op=load(OPERATIONS).get(oid)
    if not op:send(cid,"❌ Операция не найдена.");return
    send(cid,op_summary(op),[[btn("🎯 По целям",f"optargets:{oid}"),btn("👥 По офферам",f"opoffers:{oid}")],[btn("⏱ Смещение всех",f"oall:{oid}"),btn("➕ Отправка",f"oadd:{oid}")],[btn("💬 Комментарий",f"oedit:{oid}:op:comment"),btn("🗑 Удалить черновик",f"odraftask:{oid}")],[btn("⬅️ Операции","ops:list")]])

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
        rows.append([btn(f"{o['player']} · {sign}{off} сек · {n}",f"opoffer:{oid}:{uid}")])
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
    offers=load(OFFERS); selected=set(d.get("offers",[])); rows=[]
    for uid,o in offers.items():
        mark="✅" if uid in selected else "⬜"
        rows.append([btn(f"{mark} {o['player']} {o['x']}|{o['y']}",f"opofftoggle:{uid}")])
    rows.append([btn(f"➡️ Далее ({len(selected)})","opoffdone")])
    send(cid,"👥 <b>Выберите офферов операции</b>",rows)

def op_target_picker(cid,d):
    targets=load(TARGETS); selected=d.get("targets",{}); rows=[]
    for k,t in targets.items():
        mode=selected.get(k)
        mark={"spam":"🟡","destroy":"🔥","capture":"👑"}.get(mode,"⬜")
        rows.append([btn(f"{mark} {k} · {t.get('player','?')} · {t.get('type','?')}",f"optargetpick:{k}")])
    rows.append([btn(f"⚙️ Создать черновик ({len(selected)})","opgenerate")])
    send(cid,"🎯 <b>Цели операции</b>\n\nНажмите цель и выберите тип атаки.",rows)

def generate_op(uid,d):
    offers_all=load(OFFERS); targets_all=load(TARGETS); oid=op_id()
    arrival_dt=datetime.fromisoformat(d["arrival_iso"])
    op={"id":oid,"name":"Операция","status":"draft","arrival":arrival_dt.strftime("%d.%m.%Y %H:%M:%S"),
        "arrival_iso":d["arrival_iso"],"base_speed":d["base_speed"],"created_at":now(),"created_by":uid,
        "comment":"","offers":{},"targets":{},"attacks":{}}
    for ouid in d["offers"]:
        o=offers_all[ouid]
        op["offers"][ouid]={"player":o["player"],"village":o["village"],"x":o["x"],"y":o["y"],"arena":o["arena"],
                            "offset":int(d["offsets"].get(ouid,0)),"army_snapshot":o.get("army",{})}
    for key,mode in d["targets"].items():
        t=targets_all[key]; op["targets"][key]={**t,"mode":mode}
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

def op_store(ops, msg="Edit operation draft"):
    save(OPERATIONS,ops)
    persist(msg)

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
    send(cid,"➕ <b>Новая отправка</b>\nВыберите оффера.",[[btn(o["player"],f"oaddoffer:{oid}:{uid}")] for uid,o in op["offers"].items()]+[[btn("⬅️ Операция",f"op:{oid}")]])

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

def handle_message(m):
    # The operations wizard is private; ignore messages from group topics.
    if (m.get("chat") or {}).get("type") != "private":
        return
    uid=m["from"]["id"];cid=m["chat"]["id"];text=m.get("text","").strip()
    if text=="/start":state(uid);start(cid,uid);return
    st=getstate(uid)
    if not st:send(cid,"Используйте /start, чтобы открыть меню.");return
    step=st["step"];d=st["data"]
    if step in ("reg_coords","target_coords"):
        c=coords(text)
        if not c:send(cid,"❌ Введите координаты через пробел, например <code>55 46</code>.");return
        v,p=village_at(*c)
        if not v:send(cid,f"❌ Деревня <code>{c[0]}|{c[1]}</code> не найдена в последнем снимке мира.");return
        if step=="reg_coords":
            if v["tribe_id"] not in TROOPS:send(cid,"❌ Для этой расы пока нет шаблона войск.");return
            state(uid,"reg_arena",{"village":v});send(cid,f"✅ Найдено: <b>{html.escape(v['player'])}</b> — {html.escape(v['village'])}\nРаса: <b>{TRIBES.get(v['tribe_id'])}</b>\n\nВведите уровень арены от <b>0</b> до <b>20</b>.");return
        d={"village":v};state(uid,"target_type",d)
        send(cid,f"🎯 <b>Новая цель</b>\n{html.escape(v['player'])} — {html.escape(v['village'])} <code>{v['x']}|{v['y']}</code>\n\nВыберите тип:",[[btn(x,f"newtype:{x}")] for x in TARGET_TYPES]);return
    if step=="reg_arena":
        if not text.isdigit() or not 0<=int(text)<=20:send(cid,"❌ Арена должна быть числом 0–20.");return
        d["arena"]=int(text);state(uid,"reg_army",d);v=d["village"]
        send(cid,f"⚔️ <b>Войска — {TRIBES[v['tribe_id']]}</b>\n\nСкопируйте шаблон, впишите числа и отправьте обратно.\n\n<pre>{html.escape(template(v['tribe_id']))}</pre>");return
    if step in ("reg_army","army"):
        tid=d["village"]["tribe_id"] if step=="reg_army" else d["tribe_id"];army,err=parse_army(text,tid)
        if err:send(cid,"❌ "+html.escape(err));return
        os_=load(OFFERS);k=str(uid)
        if step=="reg_army":
            v=d["village"];os_[k]={"telegram_id":uid,**v,"arena":d["arena"],"registered_at":now(),"army":{"troops":army,"updated_at":now()}}
        else:os_[k]["army"]={"troops":army,"updated_at":now()}
        save(OFFERS,os_);state(uid);persist("Update alliance ops offers");send(cid,"✅ Данные сохранены.\n\n"+fmt_offer(os_[k]),menu(uid));return
    if step=="arena":
        if not text.isdigit() or not 0<=int(text)<=20:send(cid,"❌ Арена должна быть числом 0–20.");return
        os_=load(OFFERS);os_[str(uid)]["arena"]=int(text);save(OFFERS,os_);state(uid);persist("Update alliance ops arena");send(cid,"✅ Арена обновлена.",menu(uid));return

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
            nxt=remaining[0];d["offset_uid"]=nxt;state(uid,"op_offset",d);o=load(OFFERS)[nxt];send(cid,f"⏱ Смещение для <b>{html.escape(o['player'])}</b> в секундах.\nНапример: <code>0</code>, <code>-1</code>, <code>+2</code>.");return
        d.pop("offset_uid",None);d["targets"]={};state(uid,"op_pick_targets",d);op_target_picker(cid,d);return

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
    if x=="offer:view":
        o=load(OFFERS).get(str(uid));send(cid,fmt_offer(o),menu(uid)) if o else start(cid,uid);return
    if x=="offer:army":
        o=load(OFFERS).get(str(uid))
        if not o:start(cid,uid);return
        state(uid,"army",{"tribe_id":o["tribe_id"]});send(cid,f"🔄 <b>Обновление войск</b>\n\n<pre>{html.escape(template(o['tribe_id']))}</pre>");return
    if x=="offer:arena":state(uid,"arena");send(cid,"🏟 Введите новый уровень арены 0–20.");return
    if x.startswith(("targets","target","newtype:","newprio:","settype:","setprio:","confirmdelete:","ops","op","oa:","ow","oe","ot","od","ob","oall:","oofferedit:","oadd")) and uid not in COORDINATORS:send(cid,"⛔ Только для координатора.");return

    if x=="ops:list":list_ops(cid);return
    if x=="ops:new":state(uid,"op_arrival",{});send(cid,"🕐 <b>Новая операция</b>\n\nВведите дату и время прибытия.\nФормат: <code>05.10.2026 20:00:00</code>");return
    if x.startswith("opofftoggle:"):
        st=getstate(uid);d=st["data"];ouid=x.split(":",1)[1]
        if ouid in d["offers"]:d["offers"].remove(ouid);d["offsets"].pop(ouid,None)
        else:d["offers"].append(ouid)
        state(uid,"op_pick_offers",d);op_offer_picker(cid,d);return
    if x=="opoffdone":
        st=getstate(uid);d=st["data"]
        if not d.get("offers"):send(cid,"❌ Выберите хотя бы одного оффера.");return
        nxt=d["offers"][0];d["offset_uid"]=nxt;state(uid,"op_offset",d);o=load(OFFERS)[nxt];send(cid,f"⏱ <b>Смещения офферов</b>\n\nВведите смещение для <b>{html.escape(o['player'])}</b> в секундах.\nНапример: <code>0</code>, <code>-1</code>, <code>+2</code>.");return
    if x.startswith("optargetpick:"):
        st=getstate(uid);d=st["data"];key=x.split(":",1)[1];t=load(TARGETS).get(key)
        if not t:return
        send(cid,f"🎯 <b>{html.escape(t['player'])} — {html.escape(t['village'])}</b>\n<code>{key}</code>\nТип деревни: <b>{t.get('type','Не определено')}</b>\n\nЧто это за атака?",[
            [btn("🟡 Спам",f"opmode:{key}:spam")],
            [btn("🔥 Уничтожение",f"opmode:{key}:destroy")],
            [btn("👑 Захват",f"opmode:{key}:capture")],
            [btn("❌ Убрать цель",f"opmode:{key}:remove")]]);return
    if x.startswith("opmode:"):
        _,key,mode=x.split(":",2);st=getstate(uid);d=st["data"]
        if mode=="remove":d["targets"].pop(key,None)
        else:d["targets"][key]=mode
        state(uid,"op_pick_targets",d);op_target_picker(cid,d);return
    if x=="opgenerate":
        st=getstate(uid);d=st["data"]
        if not d.get("targets"):send(cid,"❌ Выберите хотя бы одну цель.");return
        oid=generate_op(uid,d);state(uid);show_op(cid,oid);return
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
if __name__=="__main__":main()
