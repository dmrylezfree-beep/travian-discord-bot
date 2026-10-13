#!/usr/bin/env bash
# Read-only production isolation: fetch the migration branch and test a
# disposable worktree. Never checkout, reset or restart the live application.
set -Eeuo pipefail
export GIT_TERMINAL_PROMPT=0
REPO="/opt/travian-discord-bot"
TARGET="/opt/travian-discord-staging"
BRANCH="discord-vps-migration"
LOCK="/tmp/travian-discord-staging-sync.lock"

exec 9>"$LOCK"
flock -n 9 || exit 0
cd "$REPO"
git fetch --quiet origin "refs/heads/$BRANCH:refs/remotes/origin/$BRANCH"
mkdir -p "$TARGET"
for name in package.json defence-worker.js discord_worker_vps_http.js discord_defence_queue_vps.js discord_defence_queue_vps.test.js discord_signature_vps.test.js; do
  git show "origin/$BRANCH:$name" > "$TARGET/$name.tmp"
  mv "$TARGET/$name.tmp" "$TARGET/$name"
done
cd "$TARGET"
node --check defence-worker.js
node --check discord_worker_vps_http.js
node --check discord_defence_queue_vps.js
node --test discord_defence_queue_vps.test.js discord_signature_vps.test.js
echo "Staging checks passed at $(date -u +%FT%TZ)"
