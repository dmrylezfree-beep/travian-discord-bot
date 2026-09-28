import csv
import html
import io
import json
import os
import re
from pathlib import Path

import requests

THREAD_ID = 20
JAPANESE_THREAD_ID = 79936
TOKEN = os.environ.get("CROP_TELEGRAM_TOKEN")
CHAT_ID = os.environ.get("TELEGRAM_GROUP_CHAT_ID")
CROPS = Path("data/crop_fields/crop_fields.json")
STATE = Path("data/crop_fields/state.json")


def snapshot_rows(path):
    """Return {(x, y): village/player/alliance data} from Travian map.sql."""
    result = {}
    text = path.read_text(encoding="utf-8", errors="ignore")
    for line in text.splitlines():
        m = re.search(r"VALUES\s*\((.*)\)\s*;?\s*$", line)
        if not m:
            continue
        try:
            parts = next(csv.reader(
                io.StringIO(m.group(1)),
                delimiter=",",
                quotechar="'",
                escapechar="\\",
                skipinitialspace=True,
            ))
            if len(parts) < 10:
                continue
            x, y = int(parts[1]), int(parts[2])
            result[(x, y)] = {
                "uid": int(parts[6]),
                "player": parts[7],
                "aid": int(parts[8]),
                "alliance": parts[9],
            }
        except (ValueError, csv.Error, StopIteration):
            continue
    return result


def crop_label(crop_by_coord, coord):
    row = crop_by_coord.get(coord, {})
    fields = row.get("crop_fields")
    return f"{fields}c" if fields in (9, 15) else "?c"


def crop_bonus(crop_by_coord, coord):
    row = crop_by_coord.get(coord, {})
    bonus = row.get("crop_bonus")
    return f"{bonus}%" if isinstance(bonus, (int, float)) else "?%"


def main():
    if not CROPS.exists():
        return

    snaps = sorted(Path("data/snapshots").glob("**/map_*.sql"))
    if len(snaps) < 2:
        return

    crop = json.loads(CROPS.read_text(encoding="utf-8"))
    crop_by_coord = {
        (int(c["x"]), int(c["y"])): c
        for c in crop.get("crop_fields", [])
    }
    known = set(crop_by_coord)

    prev_rows = snapshot_rows(snaps[-2])
    now_rows = snapshot_rows(snaps[-1])
    prev = set(prev_rows)
    now = set(now_rows)

    freed = sorted((prev - now) & known)
    newly = sorted((now - prev) & known)

    # A newly occupied crop is a crop that was absent from yesterday's
    # map.sql but is present in today's snapshot.
    settled_by_players = [
        coord for coord in newly
        if now_rows[coord]["uid"] != 1
        and now_rows[coord]["player"].strip().lower() != "natars"
    ]
    settled_by_natars = [
        coord for coord in newly
        if now_rows[coord]["uid"] == 1
        or now_rows[coord]["player"].strip().lower() == "natars"
    ]

    if not freed and not settled_by_players and not settled_by_natars:
        return

    lines = ["<b>🌾 Изменения по кропкам</b>"]

    if freed:
        lines += ["", "<b>Освободились:</b>"]
        for coord in freed:
            x, y = coord
            lines.append(
                f"• <b>{x} {y}</b> — {crop_label(crop_by_coord, coord)}"
            )

    if settled_by_players:
        lines += ["", "<b>🏘 Заселены игроками:</b>"]
        for coord in settled_by_players:
            x, y = coord
            row = now_rows[coord]
            player = html.escape(row["player"] or "—")
            alliance = html.escape(row["alliance"] or "без альянса")
            lines.append(
                f"• <b>{x} {y}</b> — {crop_label(crop_by_coord, coord)}"
                f" | 🌾 {crop_bonus(crop_by_coord, coord)}"
                f" | 👤 {player} | 🛡 {alliance}"
            )

    if settled_by_natars:
        lines += ["", "<b>🏴 Теперь заняты Натарами:</b>"]
        for coord in settled_by_natars:
            x, y = coord
            lines.append(
                f"• <b>{x} {y}</b> — {crop_label(crop_by_coord, coord)}"
            )

    if TOKEN and CHAT_ID:
        russian_text = "\n".join(lines)
        r = requests.post(
            f"https://api.telegram.org/bot{TOKEN}/sendMessage",
            json={
                "chat_id": CHAT_ID,
                "message_thread_id": THREAD_ID,
                "text": russian_text,
                "parse_mode": "HTML",
            },
            timeout=40,
        )
        print(r.status_code, r.text)
        r.raise_for_status()

        japanese_text = russian_text
        for source, target in [
            ("🌾 Изменения по кропкам", "🌾 クロップ村の変更"),
            ("Освободились:", "空きになったクロップ村:"),
            ("🏘 Заселены игроками:", "🏘 プレイヤーが入植したクロップ村:"),
            ("🏴 Теперь заняты Натарами:", "🏴 ナタールが占領したクロップ村:"),
            ("без альянса", "同盟なし"),
        ]:
            japanese_text = japanese_text.replace(source, target)

        r = requests.post(
            f"https://api.telegram.org/bot{TOKEN}/sendMessage",
            json={
                "chat_id": CHAT_ID,
                "message_thread_id": JAPANESE_THREAD_ID,
                "text": japanese_text,
                "parse_mode": "HTML",
            },
            timeout=40,
        )
        print(r.status_code, r.text)
        r.raise_for_status()


if __name__ == "__main__":
    main()
