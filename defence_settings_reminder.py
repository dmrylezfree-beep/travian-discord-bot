import html
import os

import defence_bot as bot


def reminder_text(player):
    units = bot.settings().get("units", {})
    name = player.get("first_name") or player.get("username") or "игрок"
    lines = [
        "<b>🔄 Пора обновить данные о дефе</b>",
        "",
        f"{html.escape(str(name))}, проверь количество войск в своих деревнях.",
        "Актуальные данные помогают точнее рассчитывать уведомления и оптимальный план защиты.",
        "",
        "<b>Сейчас у тебя указано:</b>",
    ]

    villages = player.get("villages", [])
    if not villages:
        lines += ["", "Деревни и войска пока не указаны."]
    for village in villages:
        lines += ["", f"🏘 <b>{html.escape(str(village.get('coordinates', '?')))}</b> · Арена {int(village.get('arena', 0) or 0)}"]
        troops = []
        for key in bot.allowed_units(player):
            amount = int((village.get("troops") or {}).get(key, 0) or 0)
            if amount > 0:
                troops.append(f"{html.escape(str(units.get(key, {}).get('name', key)))} — <b>{amount}</b>")
        lines.extend(troops or ["Войска не указаны"])

        hero = village.get("hero") or {}
        if hero.get("present"):
            lines.append("🦸 <b>Герой находится здесь</b>")

    inv = bot.hero_inventory(player)
    lines += ["", "<b>🎒 Инвентарь героя:</b>"]
    lines.append("🚩 Штандарты: " + (", ".join(f"+{x}%" for x in inv.get("standards", [])) or "нет"))
    lines.append("🥾 Сапоги: " + (", ".join(f"+{x}%" for x in inv.get("boots", [])) or "нет"))
    lines.append("🗺 Карты: " + (", ".join(f"+{x}%" for x in inv.get("maps", [])) or "нет"))

    lines += [
        "",
        "Если данные изменились, открой <b>⚙️ Мои настройки</b> в Центре дефа и обнови их.",
    ]
    return "\n".join(lines)


def main():
    players = bot.players()
    sent = 0
    for player in players.values() if isinstance(players, dict) else []:
        if not isinstance(player, dict):
            continue
        chat_id = player.get("private_chat_id")
        if not chat_id or not player.get("private_notifications", True):
            continue
        if not player.get("villages"):
            continue
        try:
            bot.send_private(int(chat_id), reminder_text(player))
            sent += 1
        except Exception as exc:
            print(f"Settings reminder failed for {player.get('telegram_id')}: {exc}", flush=True)
    print(f"Settings reminders sent: {sent}", flush=True)


if __name__ == "__main__":
    main()
