"""Send Telegram HTML report text to Discord through a webhook."""
import html
import os
import re

import requests

WEBHOOK = os.environ.get("DISCORD_JAPAN_WEBHOOK_URL", "").strip()
PROXY = os.environ.get("TELEGRAM_PROXY_URL", "").strip()
PROXIES = {"https": PROXY} if PROXY else None


def to_discord(message):
    message = re.sub(
        r'<a\s+href="([^"]+)">([^<]*)</a>',
        lambda m: f'[{html.unescape(m.group(2))}]({html.unescape(m.group(1))})',
        message,
    )
    message = re.sub(r"</?b>", "**", message)
    message = re.sub(r"</?i>", "*", message)
    message = re.sub(r"<[^>]+>", "", message)
    return html.unescape(message)


def send(message):
    if not WEBHOOK:
        raise RuntimeError("DISCORD_JAPAN_WEBHOOK_URL is not configured")
    message = to_discord(message)
    # Discord webhook content limit is 2000 characters.
    chunks = []
    while message:
        if len(message) <= 1900:
            chunks.append(message)
            break
        split = message.rfind("\n", 0, 1900)
        if split < 1:
            split = 1900
        chunks.append(message[:split])
        message = message[split:].lstrip("\n")
    for chunk in chunks:
        response = requests.post(
            WEBHOOK, json={"content": chunk, "allowed_mentions": {"parse": []}},
            timeout=40, proxies=PROXIES,
        )
        response.raise_for_status()
