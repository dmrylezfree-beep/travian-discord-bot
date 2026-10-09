"""Back up the current UTC day's Travian snapshot to GitHub without git pull."""
import base64
import os
from datetime import datetime, timezone
from pathlib import Path

import requests

token = os.environ.get("GITHUB_TOKEN", "").strip()
if not token:
    raise SystemExit("GITHUB_TOKEN missing: snapshot remains safely stored on VPS")

date = datetime.now(timezone.utc).date()
path = Path("data/snapshots") / str(date.year) / f"{date.month:02d}" / f"map_{date.isoformat()}.sql"
if not path.is_file():
    raise SystemExit(f"Snapshot not found: {path}")

url = f"https://api.github.com/repos/dmrylezfree-beep/travian-discord-bot/contents/{path.as_posix()}"
headers = {"Authorization": f"Bearer {token}", "Accept": "application/vnd.github+json"}
content = path.read_bytes()

for attempt in range(3):
    previous = requests.get(url, headers=headers, params={"ref": "main"}, timeout=30)
    if previous.status_code not in (200, 404):
        raise SystemExit(f"GitHub lookup failed: HTTP {previous.status_code}")
    payload = {
        "branch": "main",
        "message": f"Backup Travian map {date.isoformat()}",
        "content": base64.b64encode(content).decode("ascii"),
    }
    if previous.status_code == 200:
        metadata = previous.json()
        payload["sha"] = metadata["sha"]
        if metadata.get("content") and base64.b64decode(metadata["content"]) == content:
            print("GitHub snapshot backup already current")
            break
    response = requests.put(url, headers=headers, json=payload, timeout=120)
    if response.status_code in (200, 201):
        print("GitHub snapshot backup uploaded")
        break
    if response.status_code not in (409, 422) or attempt == 2:
        raise SystemExit(f"GitHub backup failed: HTTP {response.status_code}")
