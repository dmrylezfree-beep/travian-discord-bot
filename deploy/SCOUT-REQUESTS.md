# Scout requests

@Scout_travian_bot operates in alliance group -1002493230303, topic 5, and private chats. The crop calculator remains available. Requests in private chats require verified group membership; public callbacks are accepted only in the configured topic. The persistent queue menu is pinned without removing any other pins. The bot needs message/pin administrator rights.

Users choose target village coordinates, resources+troops or buildings+troops, and anytime or specified ARRIVAL date/time. Dates are Travian Europe/London with DST. Roman Equites Legati use speed16; Tournament Square adds20% per level after the first20 fields, 401-field wrapping map. Initial coordinator settings: Telegram317595036, origin22|63, arena7. Settings can be changed only by coordinator and open request departure times recalculate. Computation excludes hero/artifacts; actual game rally-point travel time should be checked. Coordinates/buttons open the rally-point send form with x/y filled; users select troops and send in-game themselves from the configured origin.

Coordinator opens a request. The bot posts its coordinates and binds THAT message to THAT request. Reply with a screenshot/photo or image document. In-group photos are linked in place, without duplicating the image. Private coordinator attachments are copied into topic5 with identifying caption. Albums inherit the first bound reply. Screenshot submission does not automatically close a request. Coordinator uses Done to hide it from pending queue, or Reopen to restore it. Results remain publicly accessible to alliance members through Results. Ordinary users cannot complete/reopen, attach results or change settings.

Requests, drafts, message bindings, results, settings and crop state persist in the same private SQLite store /var/lib/travian-scout/state.sqlite. Submitted drafts have unique nonces to prevent duplicate requests on repeated confirmation. Group input is accepted only as replies to the correct user's prompt. No game login, troop submission or OCR is performed.

Commands: /scout@Scout_travian_bot or /requests@Scout_travian_bot in topic5; /settings for coordinator. Main menu includes New Request, Queue, Results, Coordinator Settings, Crop and Help.

Official game references: https://blog.travian.com/2022/03/the-power-of-scouts/ (Roman scouts16 fields/hour), https://support.travian.com/en/articles/71-troops-speed-increase-and-tournament-square (20-field arena threshold and per-level bonus).
