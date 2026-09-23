import json
import os
import time
import crop_bot as bot

RUN_SECONDS=int(os.environ.get("CROP_RUN_SECONDS","510"))
POLL_TIMEOUT=int(os.environ.get("CROP_TG_POLL_TIMEOUT","20"))

def accepted(update):
    msg=update.get("message") or (update.get("callback_query") or {}).get("message") or {}
    chat=msg.get("chat") or {}
    return chat.get("type")=="private" or msg.get("message_thread_id")==bot.TELEGRAM_THREAD_ID

def main():
    bot.ensure_data()
    raw=os.environ.get("CROP_INITIAL_UPDATE_JSON","").strip()
    if raw:
        try:
            u=json.loads(raw)
            if accepted(u): bot.process_update(u)
        except Exception as exc: print("Initial update failed:",repr(exc),flush=True)
    offset=None; deadline=time.monotonic()+RUN_SECONDS
    while time.monotonic()<deadline:
        kw={"timeout":min(POLL_TIMEOUT,max(1,int(deadline-time.monotonic()))),"allowed_updates":["message","callback_query"]}
        if offset is not None: kw["offset"]=offset
        try: updates=bot.telegram("getUpdates",**kw) or []
        except Exception as exc:
            print("getUpdates:",repr(exc),flush=True); time.sleep(2); continue
        for u in updates:
            if isinstance(u.get("update_id"),int): offset=u["update_id"]+1
            if accepted(u):
                try: bot.process_update(u)
                except Exception as exc: print("process:",repr(exc),flush=True)
if __name__=="__main__": main()
