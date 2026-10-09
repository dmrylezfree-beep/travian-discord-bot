"""Download an independent daily Travian map snapshot in GitHub Actions."""
from datetime import datetime, timezone
from pathlib import Path
import requests

url = "https://ts8.x1.asia.travian.com/map.sql"
response = requests.get(url, timeout=120)
response.raise_for_status()
if not response.content.strip():
    raise SystemExit("Travian returned an empty map.sql")

today = datetime.now(timezone.utc).date()
destination = Path("data/snapshots") / str(today.year) / f"{today.month:02d}" / f"map_{today.isoformat()}.sql"
destination.parent.mkdir(parents=True, exist_ok=True)
destination.write_bytes(response.content)
print(f"Saved {destination} ({len(response.content)} bytes)")
