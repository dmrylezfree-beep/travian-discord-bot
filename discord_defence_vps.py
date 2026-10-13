"""VPS Discord defence transport (migration staging).

This module is deliberately inert until explicitly invoked. It does not alter
Telegram polling or Cloudflare routes. No credentials are stored in source.
"""
import json
import logging
import os
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone

LOG = logging.getLogger("discord_defence_vps")
API = "https://discord.com/api/v10"
REPO = "dmrylezfree-beep/travian-discord-bot"
CHANNEL = "1430982180401578153"


def request_json(url, *, token, method="GET", body=None, attempts=4):
    payload = None if body is None else json.dumps(body).encode("utf-8")
    headers = {"Authorization": token, "User-Agent": "travian-defence-vps/1.0"}
    if payload is not None:
        headers["Content-Type"] = "application/json"
    for attempt in range(attempts):
        req = urllib.request.Request(url, data=payload, headers=headers, method=method)
        try:
            with urllib.request.urlopen(req, timeout=20) as response:
                data = response.read()
                return json.loads(data) if data else {}
        except urllib.error.HTTPError as exc:
            details = exc.read().decode("utf-8", "replace")
            if exc.code == 429:
                try:
                    delay = min(30, max(1, float(json.loads(details).get("retry_after", 1))))
                except (ValueError, TypeError):
                    delay = 2
            elif exc.code >= 500:
                delay = min(16, 2 ** attempt)
            else:
                raise RuntimeError(f"HTTP {exc.code} for {method} {url}: {details[:400]}") from exc
            if attempt == attempts - 1:
                raise RuntimeError(f"HTTP {exc.code} after {attempts} attempts: {details[:400]}") from exc
            time.sleep(delay)
        except (urllib.error.URLError, TimeoutError):
            if attempt == attempts - 1:
                raise
            time.sleep(min(16, 2 ** attempt))
    raise RuntimeError("Request attempts exhausted")


def discord(path, method="GET", body=None):
    token = os.environ.get("DISCORD_BOT_TOKEN")
    if not token:
        raise RuntimeError("DISCORD_BOT_TOKEN is missing")
    return request_json(API + path, token="Bot " + token, method=method, body=body)


def load_requests():
    """Read canonical defence state from GitHub without modifying it."""
    import base64
    token = os.environ.get("GITHUB_TOKEN")
    if not token:
        raise RuntimeError("GITHUB_TOKEN is missing")
    response = request_json(
        f"https://api.github.com/repos/{REPO}/contents/data/defence/requests.json?ref=main",
        token="Bearer " + token,
    )
    return json.loads(base64.b64decode(response["content"]))


def active_requests(requests):
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
    return [
        r for r in requests
        if r.get("status") == "active"
        and float(r.get("required_def") or 0) > float(r.get("collected_def") or 0)
        and str(r.get("attack_time") or "") > now
    ]


def diagnostic():
    """Read-only smoke test; never creates messages or changes requests."""
    requests = load_requests()
    active = active_requests(requests)
    channel = discord(f"/channels/{CHANNEL}")
    result = {
        "channel_id": channel.get("id"),
        "channel_name": channel.get("name"),
        "active_request_ids": [r.get("id") for r in active],
        "total_requests": len(requests),
        "status": "read_only_ok",
    }
    LOG.info("Discord VPS diagnostic: %s", result)
    return result


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    print(json.dumps(diagnostic(), ensure_ascii=False, indent=2))
