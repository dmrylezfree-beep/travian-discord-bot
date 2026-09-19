import html
import time
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import defence_bot as bot
import defence_requests

SERVER_TZ = ZoneInfo("Europe/London")
LOOKAHEAD_SECONDS = 360


def parse_dt(value):
    try:
        return datetime.strptime(value, "%Y-%m-%d %H:%M:%S")
    except (TypeError, ValueError):
        return None


def main():
    requests = bot.load_json(bot.REQUESTS_FILE, [])
    players = bot.players()
    now = datetime.now(SERVER_TZ).replace(tzinfo=None)
    due = []

    for req in requests if isinstance(requests, list) else []:
        if req.get("status") == "cancelled":
            continue
        for contribution in req.get("contributions", []):
            player = players.get(str(contribution.get("telegram_id"))) or {}
            chat_id = player.get("private_chat_id")
            if not chat_id or not player.get("private_notifications", True):
                continue
            for item in contribution.get("plan", []):
                if item.get("reminder_sent"):
                    continue
                reminder = parse_dt(item.get("reminder_at"))
                deadline = parse_dt(item.get("deadline_at"))
                if reminder is None or deadline is None:
                    continue
                # A scheduled GitHub run can be delayed. Never discard a reminder
                # while the actual send deadline has not passed.
                if deadline <= now:
                    continue
                if reminder <= now + timedelta(seconds=LOOKAHEAD_SECONDS):
                    due.append((reminder, req, contribution, item, int(chat_id)))

    due.sort(key=lambda x: x[0])
    changed = False
    for reminder, req, contribution, item, chat_id in due:
        wait = (reminder - datetime.now(SERVER_TZ).replace(tzinfo=None)).total_seconds()
        if wait > 0:
            time.sleep(wait)

        mode = item.get("speed_mode", "normal")
        extra = ""
        warning = ""
        if mode == "ram":
            extra = " + 1 таран"
            warning = "\n\n❗ Не забудь добавить <b>1 таран</b>."
        elif mode == "catapult":
            extra = " + 1 катапульта"
            warning = "\n\n❗ Не забудь добавить <b>1 катапульту</b>."

        text = (
            "<b>🚨 ЧЕРЕЗ 5 МИНУТ ОТПРАВКА ДЕФА</b>\n\n"
            f"🏘 {html.escape(item.get('village', '?'))} → "
            f"🎯 {req.get('target_x')} {req.get('target_y')}\n"
            f"🛡 {item.get('def_points', 0)} очков дефа{extra}\n"
            f"⏰ Отправить: <b>{item.get('deadline', '?')}</b>\n"
            f"⚔️ Атака: <b>{req.get('attack_time_display', req.get('attack_time', '?'))}</b>"
            + warning
        )
        try:
            bot.send_private(chat_id, text)
            item["reminder_sent"] = True
            item["reminder_sent_at"] = datetime.now(SERVER_TZ).strftime("%Y-%m-%d %H:%M:%S")
            changed = True
            print(f"Reminder sent: request={req.get('id')} chat={chat_id} village={item.get('village')}", flush=True)
        except Exception as exc:
            print(f"Reminder failed: request={req.get('id')} chat={chat_id}: {exc}", flush=True)

    if changed:
        bot.save_json(bot.REQUESTS_FILE, requests)
        bot.persist_data()

    # The same five-minute job also keeps public optimal plans current.
    # A plan is deleted and reposted only when the recommendation actually changes.
    try:
        defence_requests.refresh_optimal_plans()
    except Exception as exc:
        print(f"Optimal plan refresh failed: {exc}", flush=True)


if __name__ == "__main__":
    main()
