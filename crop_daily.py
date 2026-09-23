import json
import os
from pathlib import Path
import requests

THREAD_ID=20
TOKEN=os.environ.get("CROP_TELEGRAM_TOKEN")
CHAT_ID=os.environ.get("TELEGRAM_GROUP_CHAT_ID")
CROPS=Path("data/crop_fields/crop_fields.json")
STATE=Path("data/crop_fields/state.json")

def coords_from_snapshot(path):
    result=set()
    text=path.read_text(encoding="utf-8",errors="ignore")
    import re
    for line in text.splitlines():
        m=re.search(r"VALUES\s*\((.*)\)\s*;?\s*$",line)
        if not m: continue
        parts=m.group(1).split(",")
        if len(parts)>=3:
            try: result.add((int(parts[1]),int(parts[2])))
            except: pass
    return result

def main():
    if not CROPS.exists(): return
    snaps=sorted(Path("data/snapshots").glob("**/map_*.sql"))
    if len(snaps)<2: return
    crop=json.loads(CROPS.read_text(encoding="utf-8"))
    known={(int(c["x"]),int(c["y"])) for c in crop.get("crop_fields",[])}
    prev=coords_from_snapshot(snaps[-2]); now=coords_from_snapshot(snaps[-1])
    freed=sorted((prev-now)&known)
    newly=sorted((now-prev)&known)
    if not freed and not newly: return
    lines=["<b>🌾 Изменения по кропкам</b>"]
    if freed: lines+=["","Освободились:"]+[f"• <b>{x} {y}</b>" for x,y in freed]
    if newly: lines+=["","Теперь заняты/перешли под владельца:"]+[f"• <b>{x} {y}</b>" for x,y in newly]
    if TOKEN and CHAT_ID:
        r=requests.post(f"https://api.telegram.org/bot{TOKEN}/sendMessage",json={"chat_id":CHAT_ID,"message_thread_id":THREAD_ID,"text":"\n".join(lines),"parse_mode":"HTML"},timeout=40)
        print(r.status_code,r.text)
if __name__=="__main__": main()
