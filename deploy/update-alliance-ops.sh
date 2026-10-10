#!/usr/bin/env bash
set -Eeuo pipefail

APP_DIR="/opt/travian-discord-bot"
APP_FILE="$APP_DIR/alliance_ops_bot.py"
ENV_FILE="/etc/travian-bots.env"
SERVICE="travian-alliance-ops.service"
RAW_URL="https://raw.githubusercontent.com/dmrylezfree-beep/travian-discord-bot/main/alliance_ops_bot.py"
BACKUP_DIR="$APP_DIR/.ops-backups"

if [[ "${EUID}" -ne 0 ]]; then
  echo "Run as root (sudo)." >&2
  exit 1
fi
if [[ ! -f "$APP_FILE" || ! -f "$ENV_FILE" ]]; then
  echo "Bot file or environment file missing; aborting." >&2
  exit 1
fi

# Read only the proxy URL, without printing credentials or sourcing arbitrary shell commands.
PROXY_URL="$(python3 - "$ENV_FILE" <<'PY'
import sys
for line in open(sys.argv[1], encoding="utf-8"):
    line = line.strip()
    if line.startswith("TELEGRAM_PROXY_URL="):
        print(line.split("=", 1)[1].strip().strip('"').strip("'"))
        break
PY
)"
if [[ -z "$PROXY_URL" ]]; then
  echo "TELEGRAM_PROXY_URL missing; aborting." >&2
  exit 1
fi

mkdir -p "$BACKUP_DIR"
TEMP_FILE="$(mktemp "$APP_DIR/.alliance_ops_new.XXXXXX.py")"
BACKUP_FILE=""
INSTALLED=0
cleanup() {
  rm -f "$TEMP_FILE"
}
rollback() {
  if [[ "$INSTALLED" == 1 && -n "$BACKUP_FILE" && -f "$BACKUP_FILE" ]]; then
    echo "Update failed. Restoring previous version..."
    cp -p "$BACKUP_FILE" "$APP_FILE"
    systemctl restart "$SERVICE" || true
  fi
}
trap cleanup EXIT
trap 'rollback' ERR

echo "Downloading bot through configured HTTP proxy..."
curl --fail --location --silent --show-error --retry 2 --connect-timeout 15 --max-time 90 \
  --proxy "$PROXY_URL" "$RAW_URL" --output "$TEMP_FILE"
[[ -s "$TEMP_FILE" ]] || { echo "Downloaded file is empty." >&2; exit 1; }
"$APP_DIR/.venv/bin/python" -m py_compile "$TEMP_FILE"
echo "Python syntax OK."

if cmp -s "$TEMP_FILE" "$APP_FILE"; then
  echo "Already up to date; no restart needed."
  exit 0
fi

BACKUP_FILE="$BACKUP_DIR/alliance_ops_bot_$(date +%Y%m%d_%H%M%S).py"
cp -p "$APP_FILE" "$BACKUP_FILE"
cp "$TEMP_FILE" "$APP_FILE"
INSTALLED=1
echo "Restarting $SERVICE..."
systemctl restart "$SERVICE"
sleep 3
systemctl is-active --quiet "$SERVICE"
INSTALLED=0
echo "Update successful. Backup: $BACKUP_FILE"
