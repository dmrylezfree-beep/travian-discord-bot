# VPS runtime and GitHub updates

Telegram polling, Discord Gateway, shared defence JSON documents and durable SQLite reminders run on VPS 194.87.1.107. GitHub is not a runtime state store. The shared state directory is /opt/travian-discord-bot/data/defence; concurrent independent edits are merged and competing edits are rejected. Requests are matched by ID. Malformed JSON is never replaced by an empty document.

Production Python files are at repository root. Discord and local API code are in vps-runtime/. The historical root defence-worker.js is a legacy Cloudflare artifact, not the deployed VPS code. Do not redeploy it or restore Telegram webhooks.

The code updater reads main every five minutes into a separate bare cache, pins a commit, validates Python/JavaScript and runs the state/queue tests. It installs only explicitly managed code files; data/, secrets, environments and systemd definitions are excluded. It preserves local edits by refusing updates when installed checksums drift. It backs up code, restarts affected services, observes stability, and rolls back on failure. Dependency lockfile changes require a reviewed dependency installation. The updater itself and allowlist require a reviewed deployment. Old staging checks remain separate.

An update to main is authorization to deploy the managed code automatically. Make code changes at repository root (Python) or vps-runtime/ (Discord/local API), and retain tests. Editing data/ in GitHub does not change live bot data. Never use git pull/reset in the production directory.

Existing map snapshot backups and their GitHub schedules are retained. Bot data backup policy is separate from code deployment; no automatic import from a backup into live state occurs.

Local synchronization uses the persistent reminder queue and a periodic recovery timer. Delivery is at least once: an external message can be repeated after a crash between sending and acknowledgement. Old Cloudflare queue resources may only be retired after confirming all outstanding and delayed messages are drained.

## Completed cutover (2026-10-15)

The owner confirmed Discord and Telegram commands/forms work after switching. All seven services are active; state contains 27 Telegram profiles, 5 Discord profiles and 9 requests. The old defence Actions were disabled by the owner. Cloudflare production/preview URLs and automatic builds are disabled for all three legacy Workers; no cron triggers remain. The old reminder queue was empty (including delayed backlog), had no DLQ, and its consumer was detached without deleting the queue.

The hourly GitHub backup now contains 21 allowlisted JSON documents plus a consistent SQLite copy at backups/vps-state/latest.json. The owner explicitly approved the current public repository. A downloaded backup passed a SQLite integrity check. Existing map snapshot backups remain enabled. The main code update timer is enabled and has successfully checked the current release; it only installs allowlisted code files after validation. Dependency changes and systemd/updater changes still require a reviewed maintenance deployment. No synthetic notification delivery was sent during this migration.
