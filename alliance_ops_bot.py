import os, re, json, time, html, subprocess
from datetime import datetime, timezone, timedelta
from pathlib import Path
import requests

TOKEN=os.environ.get("ALLIANCE_OPS_TELEGRAM_TOKEN")
COORDINATORS={317595036}
SNAPSHOTS=Path("data/snapshots")
DATA=Path("data/alliance_ops")
OFFERS=DATA/"offers.json"; TARGETS=DATA/"targets.json"; STATES=DATA/"states.json"
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
    for p in (OFFERS,TARGETS,STATES):
        if not p.exists(): p.write_text("{}",encoding="utf-8")
def load(p):
    ensure()
    try: return json.loads(p.read_text(encoding="utf-8"))
    except: return {}
def save(p,d): p.write_text(json.dumps(d,ensure_ascii=False,indent=2,sort_keys=True),encoding="utf-8")
def persist(msg):
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
    r=requests.post(f"https://api.telegram.org/bot{TOKEN}/{method}",json=payload or {},timeout=40);r.raise_for_status()
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
    if uid in COORDINATORS:rows += [[btn("🎯 База целей","targets:list"),btn("➕ Добавить цель","targets:add")]]
    return rows
def fmt_offer(o):
    lines=[f"⚔️ <b>Мой офф</b>","",f"Игрок: <b>{html.escape(o['player'])}</b>",f"Деревня: <b>{html.escape(o['village'])}</b>",f"Координаты: <code>{o['x']}|{o['y']}</code>",f"Раса: <b>{TRIBES.get(o['tribe_id'],'Неизвестно')}</b>",f"Арена: <b>{o['arena']}</b>","","<b>Войска:</b>"]
    tr=o.get("army",{}).get("troops",{})
    lines += [f"{html.escape(n)} — {v:,}".replace(",", " ") for n,v in tr.items() if v]
    if not any(tr.values()):lines.append("—")
    lines.append(f"\nОбновлено: <code>{o.get('army',{}).get('updated_at','—')}</code>")
    return "\n".join(lines)
def start(cid,uid):
    if str(uid) not in load(OFFERS):
        state(uid,"reg_coords");send(cid,"⚔️ <b>Регистрация оффера</b>\n\nВведите координаты своей офф-деревни через пробел.\nНапример: <code>55 46</code>");return
    o=load(OFFERS).get(str(uid))
    send(cid,"⚔️ <b>Центр операций альянса</b>\n\n"+fmt_offer(o)+"\n\nВыберите действие:",menu(uid))
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

def handle_message(m):
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
    if step=="target_comment":
        ts=load(TARGETS);k=d["key"]
        if k in ts:ts[k]["comment"]="" if text=="-" else text;ts[k]["updated_at"]=now();save(TARGETS,ts);persist("Update alliance ops target")
        state(uid);show_target(cid,k)

def callback(c):
    try:api("answerCallbackQuery",{"callback_query_id":c["id"]})
    except:pass
    uid=c["from"]["id"];cid=c["message"]["chat"]["id"];x=c.get("data","")
    if x=="menu":start(cid,uid);return
    if x=="offer:view":
        o=load(OFFERS).get(str(uid));send(cid,fmt_offer(o),menu(uid)) if o else start(cid,uid);return
    if x=="offer:army":
        o=load(OFFERS).get(str(uid))
        if not o:start(cid,uid);return
        state(uid,"army",{"tribe_id":o["tribe_id"]});send(cid,f"🔄 <b>Обновление войск</b>\n\n<pre>{html.escape(template(o['tribe_id']))}</pre>");return
    if x=="offer:arena":state(uid,"arena");send(cid,"🏟 Введите новый уровень арены 0–20.");return
    if x.startswith(("targets","target","newtype:","newprio:","settype:","setprio:","confirmdelete:")) and uid not in COORDINATORS:send(cid,"⛔ Только для координатора.");return
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
