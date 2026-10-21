# Scout Telegram bot

Russian calculator for private chats and group -1002493230303, topic 5 in @Scout_travian_bot. It asks village/oasis, first scan time and crop, second scan time and crop. Oasis resources are multiplied by 10. Signed hourly crop balance equals `(crop2-crop1)*multiplier*3600/seconds`: positive means accumulation, negative means depletion. It is net change, not isolated army upkeep. Transfers and full storage affect observations.

Times: HH:MM:SS (earlier second clock rolls to the next day) or DD.MM.YYYY HH:MM:SS in both scans for explicit dates. Equal timestamps, negative crop, mixed date formats and backward explicit dates are rejected. Inputs are isolated by chat/user and survive restarts in `/var/lib/travian-scout/state.sqlite`.

Commands: /start, /crop, /help, /cancel. In the group use /crop@Scout_travian_bot; answer input prompts using Telegram Reply. Other topics and ordinary chat messages are ignored; sessions are isolated by user. Add the bot to the group with permission to send messages in topic 5 (administrator rights are not required). No game credentials or game actions.

Deployment: `scout_bot.py` is managed by the existing GitHub → VPS updater; `test_scout_bot.py` is included in candidate validation. The separate `travian-scout.service` uses DynamicUser, a private state directory and `/etc/travian-scout-token.env` (root-only). No token belongs in GitHub or chat.

After the reviewed files/service are installed on VPS, run `travian-scout-setup` as root in an interactive terminal. It prompts secretly, validates bot identity, refuses an existing webhook, writes the token file, starts only Scout, then enables its service restart association in the updater. Before first activation, the updater association is empty, so an unconfigured Scout does not block other bots' code updates. Re-run to replace its token.

Tests: `python -m unittest test_scout_bot`. To inspect health use `systemctl is-active travian-scout.service`. Logs suppress secrets and scan contents.
