import json
import html
import os
import time
import subprocess
from pathlib import Path

import requests


from contextlib import contextmanager
from contextvars import ContextVar
from functools import wraps
_language = ContextVar('defence_telegram_language', default='ru')
TRANSLATIONS = {
    'Галл': 'Gaul',
    'Германец': 'Teuton',
    'Римлянин': 'Roman',
    'С чего начать': 'Getting started',
    'Бот помогает собрать защиту для деревни: показывает заявки, учитывает обещанный деф и рассчитывает время отправки.\n\n<b>Чтобы записать деф в заявку, не обязательно заранее заполнять деревни, армию и вещи героя.</b> Вы можете просто указать количество дефа. Настройки нужны для автоматического расчёта времени отправки и личных напоминаний за 5 минут до него.\n\nОткройте личный чат с ботом и нажмите /start. В чате альянса центр дефа открывается командой /def и доступен в закреплённом сообщении.\n\nБот сам не отправляет войска в Travian. Это делаете вы в игре.': 'The bot helps organise village defence: it shows requests, records pledged defence and calculates departure times.\n\n<b>You do not need to register villages, troops or hero items to pledge defence.</b> You can simply enter defence points. Village settings are needed for travel calculations and private reminders 5 minutes before departure.\n\nOpen the bot in a private chat and send /start. In the alliance chat, use /def or the pinned Defence Centre.\n\nThe bot does not send troops in Travian. You must send them in the game.',
    'Настройте свои деревни': 'Set up your villages',
    '<b>Этот раздел необязателен для простой записи дефа в заявку.</b> Настройте деревни, если хотите пользоваться расчётом отправки и напоминаниями.\n\nОткройте «Мои настройки» → «Добавить деревню» и введите координаты через пробел, например 15 3. Можно добавить несколько деревень.\n\nВ разделе «Мои деревни» укажите уровень арены и количество каждого вида защитных войск. Координаты, арену и войска можно менять; ненужную деревню — удалить.\n\nОбновляйте эти данные после изменения армии: бот не считывает ваши войска из игры.': '<b>This is optional for simply recording defence points.</b> Set up villages if you want departure calculations and reminders.\n\nOpen “My settings” → “Add village” and enter coordinates separated by a space, for example 15 3. You can add several villages.\n\nUnder “My villages”, set the Tournament Square level and the number of each defensive unit. You can edit coordinates, Tournament Square and troops, or delete a village.\n\nKeep these numbers up to date: the bot cannot read your troops from the game.',
    'Герой и снаряжение': 'Hero and equipment',
    'В «Мои настройки» → «Герой и инвентарь» отметьте деревню, где находится герой, и имеющиеся предметы: знамёна, сапоги и карты.\n\nПри расчёте отправки бот предлагает доступные варианты движения с учётом настроек. Выбирайте вариант, который действительно используете в игре. Без героя его бонусы не действуют.': 'In “My settings” → “Hero and inventory”, select the village where your hero is located and the items you own: standards, boots and maps.\n\nThe bot uses these settings to offer travel options. Choose the option you will actually use in the game. Hero bonuses do not apply without the hero.',
    'Как попросить защиту': 'Request defence',
    'В центре дефа нажмите «Запросить деф». Введите координаты атакуемой деревни, дату и точное время прихода атаки, затем необходимое количество дефа.\n\nПосле ввода количества дефа заявка сразу публикуется. Если ошиблись, удалите свою заявку через меню бота.\n\nУказывайте время сервера Travian (Europe/London: летом UTC+1, зимой UTC), а не время на телефоне. Проверяйте дату: атака после полуночи относится уже к следующему дню.': 'Tap “Request defence” in the Defence Centre. Enter the target village coordinates, the attack date and exact arrival time, then the defence points required.\n\nThe request is published immediately after entering the amount. If you made a mistake, delete your request through the menu.\n\nUse Travian server time (Europe/London: UTC+1 in summer, UTC in winter), not your phone clock. Check the date: an attack after midnight is on the next day.',
    'Как помочь союзнику': 'Help an ally',
    '<b>Можно помочь и без заполнения деревень и вещей героя.</b> Нажмите «Отправить деф», выберите активную заявку и укажите, сколько дефа готовы выделить. Это очки защиты, а не просто число солдат.\n\nЕсли подходящих настроенных деревень нет, бот всё равно запишет ваш деф в заявку. Время отправки при этом не рассчитывается.\n\nЕсли нужен расчёт отправки и напоминание, выберите настроенную деревню и подходящий вариант движения. Вещи героя указывайте только если используете их. После выбора варианта отправки помощь сразу записывается. Для помощи из другой деревни нажмите «Отправить ещё деф».\n\nПосле ввода количества дефа без деревни или выбора варианта отправки вклад сразу учитывается в заявке. Не записывайте одну и ту же помощь повторно.': '<b>You can help without registering villages or hero items.</b> Tap “Send defence”, choose an active request and enter the defence points you can provide. These are defence points, not simply the number of soldiers.\n\n“Quick send” records only the points, without travel calculations or reminders, even if you have registered villages.\n\nFor departure calculations and a reminder, select a configured village and travel option. Include hero items only if you will use them. Your contribution is recorded immediately after selecting the travel option. Use “Send more defence” to add another contribution.\n\nDo not record the same contribution twice. To send on behalf of another account, its owner must first add your Telegram ID as a substitute.',
    'Когда отправлять войска': 'When to send troops',
    'Бот рассчитывает крайнее время отправки по расстоянию, скорости войск, арене и выбранным бонусам героя. Для смешанного отряда важна скорость самого медленного юнита. Варианты с тараном или катапультой требуют взять соответствующий юнит в отряд.\n\nПеред отправкой откройте Travian, проверьте состав и время прибытия. Отправьте войска как подкрепление в нужную деревню до прихода атаки.\n\nРасчёт бота помогает планировать, но окончательно проверяйте время в игре.': 'The bot calculates the latest departure time using distance, troop speed, Tournament Square and selected hero bonuses. A mixed army travels at the speed of its slowest unit. Ram or catapult options require including that unit in the army.\n\nBefore sending, open Travian and check the troops and arrival time. Send reinforcements to the correct village before the attack.\n\nThe calculation helps you plan, but always check the final time in the game.',
    'Уведомления и напоминания': 'Notifications and reminders',
    'После /start бот может писать вам в личные сообщения. О новых заявках он уведомляет, если настроенная деревня теоретически успевает помочь. Управление — «Мои настройки» → «Личные уведомления».\n\nДля подтверждённого плана отправки предусмотрено личное напоминание за 5 минут до рассчитанного срока. В карточке плана показано время напоминания.\n\nОставьте личный чат с ботом доступным и проверяйте план заранее: если до отправки уже мало времени, не ждите напоминания.': 'After /start, the bot can message you privately. It notifies you about new requests when a configured village could theoretically arrive in time. Manage this in “My settings” → “Private notifications”.\n\nA timed departure plan has a private reminder 5 minutes before the calculated deadline. The plan card shows the reminder time. Quick send has no reminder.\n\nKeep the private chat with the bot available and check your plan early: if departure is soon, do not wait for a reminder.',
    'Как читать заявку и закрыть её': 'Read and close requests',
    'В центре дефа видны активные заявки: куда нужна помощь, время атаки, сколько дефа требуется и сколько уже записано участниками. Записанный деф не означает, что войска уже дошли в игре.\n\nКогда участники набрали необходимое количество дефа, заявка закрывается. После времени атаки она также перестаёт быть активной. Если помощь больше не нужна раньше, используйте «Удалить заявку» и подтвердите действие. Удаление доступно только при наличии прав на эту заявку.': 'The Defence Centre shows active requests: the target, attack time, required defence and the amount pledged by players. Recorded defence does not mean troops have already arrived in the game.\n\nA request closes when enough points are pledged. It also becomes inactive after the attack time. If help is no longer needed, use “Delete request” and confirm deletion. Only authorised users can delete it.',
    'Рекомендованный план защиты': 'Recommended defence plan',
    '<b>Задача плана — собрать нужный деф и по возможности сберечь конницу.</b> Кони дороже и ценнее, поэтому бот старается обойтись пехотой.\n\n1. Сначала бот проверяет, какие войска по данным игроков ещё успевают к атаке.\n\n2. Из подходящей пехоты он сначала предлагает ближайшие деревни. Если пехоты хватает, конница в план не включается — даже если она стоит ближе.\n\n3. Если успевающей пехоты недостаточно, бот предлагает добрать недостающую защиту конницей. Если и её не хватает, карточка показывает нехватку.\n\n4. В карточке видно, из какой деревни, каких юнитов и сколько рекомендуется отправить, а также крайнее время отправки. План рассчитывается на оставшийся незакрытый объём заявки.\n\n<b>Это рекомендация, а не приказ и не автоматическая отправка.</b> Бот опирается на войска, указанные игроками в настройках, и не знает их фактическую доступность в игре. План не резервирует армию. Если готовы помочь, отдельно запишитесь через «Отправить деф» и согласуйте отправку с координатором.': '<b>The plan aims to collect enough defence while saving cavalry where possible.</b> Cavalry is more expensive and valuable, so the bot tries to use infantry first.\n\n1. It checks which troops, according to player settings, can still arrive before the attack.\n\n2. It recommends the nearest eligible infantry first. If infantry is sufficient, cavalry is excluded, even if it is closer.\n\n3. If eligible infantry is insufficient, it adds cavalry to cover the shortage. If that is still insufficient, the card shows how many points are missing.\n\n4. The card lists villages, unit types, quantities and latest departure times. It covers the remaining unfilled part of the request.\n\n<b>This is advice, not an order or automatic troop dispatch.</b> The bot uses player settings and cannot know actual troop availability. The plan does not reserve troops. If you can help, record your contribution through “Send defence” and coordinate the dispatch.',
    'Остальные настройки и памятка': 'Other settings and checklist',
    'В личных настройках можно указать до двух заместителей: введите их Telegram ID через запятую. Свой ID можно узнать отдельной кнопкой и сообщить союзнику. Владельцу бота также доступны обзор обороны альянса и рейтинг деферов.\n\nПеред участием проверьте 4 вещи: координаты деревни, уровень арены, актуальные войска и время сервера. При изменении плана согласуйте помощь с координатором дефа.\n\nИнструкцию можно открыть повторно в главном меню в любой момент.': 'You can authorise up to two substitutes in your private settings by entering their Telegram IDs separated by commas. Use the Telegram ID button to get your own ID and share it with an ally. The bot owner can also view alliance defence totals and rankings.\n\nBefore participating, check village coordinates, Tournament Square level, current troops and server time. Coordinate any changes with the defence coordinator.\n\nOpen this guide from the main menu whenever needed. Use “Язык / Language” to choose Russian or English.',
    '<b>📖 Инструкция · ': '<b>📖 Guide · ',
    'не выбрана': 'not selected',
    '<b>🛡 Мои настройки дефа</b>': '<b>🛡 My defence settings</b>',
    'подключены': 'enabled',
    'не подключены': 'disabled',
    '<b>🛡 ОБОРОНА АЛЬЯНСА</b>': '<b>🛡 ALLIANCE DEFENCE</b>',
    '<b>По юнитам:</b>': '<b>By unit:</b>',
    'ℹ️ Рейтинг: пехота ×1, конница ×2.': 'ℹ️ Score: infantry ×1, cavalry ×2.',
    '⚠️ Расчёт по войскам, указанным игроками в настройках.': '⚠️ Based on troops entered by players in their settings.',
    '<b>🏆 РЕЙТИНГ ДЕФЕРОВ</b>': '<b>🏆 DEFENDER RANKINGS</b>',
    'Рейтинг = пехота ×1 + конница ×2': 'Score = infantry ×1 + cavalry ×2',
    'Данные игрока не найдены.': 'Player data not found.',
    '<b>По деревням:</b>': '<b>By village:</b>',
    '<b>Войска:</b>': '<b>Troops:</b>',
    'не выбран': 'not selected',
    '<b>🦸 Герой и инвентарь</b>\n\n📍 Герой: <b>': '<b>🦸 Hero and inventory</b>\n\n📍 Hero: <b>',
    '</b>\n\n<b>🎒 Доступно в инвентаре:</b>\n🚩 Штандарты: <b>': '</b>\n\n<b>🎒 Available in inventory:</b>\n🚩 Standards: <b>',
    '</b>\n🥾 Сапоги: <b>': '</b>\n🥾 Boots: <b>',
    '</b>\n🗺 Карты: <b>': '</b>\n🗺 Maps: <b>',
    '</b>\n\nВыберите деревню, где находится герой, или измените инвентарь.': "</b>\n\nSelect the hero's village or edit the inventory.",
    '<b>🦸 Герой — ': '<b>🦸 Hero — ',
    '</b>\n\nГерой находится здесь: <b>': '</b>\n\nHero is here: <b>',
    '</b>\n\nНажатие на предмет добавляет или убирает его из инвентаря.': '</b>\n\nTap an item to add it to or remove it from your inventory.',
    '🧬 Раса: <b>': '🧬 Tribe: <b>',
    'Деревни пока не добавлены.': 'No villages added yet.',
    '<b>🎒 Инвентарь героя:</b>': '<b>🎒 Hero inventory:</b>',
    '🔔 Личные уведомления: <b>': '🔔 Private notifications: <b>',
    '👥 Заместители: ': '👥 Substitutes: ',
    '👥 Игроков с дефом: <b>': '👥 Players with defence: <b>',
    '🏘 Деф-деревень: <b>': '🏘 Defence villages: <b>',
    '🛡 Рейтинг дефа: <b>': '🛡 Defence score: <b>',
    '🚶 Пехота: <b>0</b>': '🚶 Infantry: <b>0</b>',
    '🐎 Конница: <b>0</b>': '🐎 Cavalry: <b>0</b>',
    'Пока никто не указал деф.': 'No defence has been entered yet.',
    '🏆 Место: <b>': '🏆 Rank: <b>',
    ' из ': ' of ',
    '🛡 Рейтинг: <b>': '🛡 Score: <b>',
    '🚶 Пехота: <b>': '🚶 Infantry: <b>',
    '🐎 Конница: <b>': '🐎 Cavalry: <b>',
    '<b>🏘 Деревня ': '<b>🏘 Village ',
    'Арена: ': 'Tournament Square: ',
    'пока не указаны': 'not entered yet',
    '🦸 <b>Герой находится в этой деревне</b>': '🦸 <b>The hero is in this village</b>',
    '<b>🛡 ЦЕНТР ДЕФА</b>\n\nВыберите раздел:': '<b>🛡 DEFENCE CENTRE</b>\n\nChoose a section:',
    'Введите уровень Арены (0–20):': 'Enter the Tournament Square level (0–20):',
    '⬅️ Назад': '⬅️ Back',
    'Дальше ➡️': 'Next ➡️',
    '⬅️ Главное меню': '⬅️ Main menu',
    'Инструкция отправлена вам в личные сообщения': 'The guide has been sent to you privately',
    '</b> — Арена ': '</b> — Tournament Square ',
    '  🦸 Герой находится здесь': '  🦸 Hero is here',
    '🚩 Штандарты: ': '🚩 Standards: ',
    '🥾 Сапоги: ': '🥾 Boots: ',
    '🗺 Карты: ': '🗺 Maps: ',
    '🏘 Мои деревни': '🏘 My villages',
    '🦸 Герой и инвентарь': '🦸 Hero and inventory',
    '🆔 Узнать мой Telegram ID': '🆔 My Telegram ID',
    '➕ Добавить деревню': '➕ Add village',
    '✏️ Изменить деревню': '✏️ Edit village',
    '🗑 Удалить деревню': '🗑 Delete village',
    '👥 Заместители': '👥 Substitutes',
    '🔔 Личные уведомления': '🔔 Private notifications',
    '📖 Инструкция': '📖 Guide',
    '⬅️ Общая армия': '⬅️ Alliance army',
    '✏️ Координаты': '✏️ Coordinates',
    '✏️ Арена': '✏️ Tournament Square',
    'нет': 'none',
    '⬅️ Мои настройки': '⬅️ My settings',
    'да': 'yes',
    'Неверный формат. Введите координаты через пробел, например: <code>45 -62</code>': 'Invalid format. Enter coordinates separated by a space, for example: <code>45 -62</code>',
    'не найден': 'not found',
    '❌ Не удалось определить владельца этой деревни в map.sql.': '❌ Could not identify the village owner in map.sql.',
    '❌ Эта деревня принадлежит другому Travian-аккаунту. В одном профиле Defence Bot можно хранить деревни только одного игрового аккаунта.': '❌ This village belongs to a different Travian account. One Defence Bot profile can only contain villages from one game account.',
    '❌ Координаты этой деревни принадлежат другой расе. Проверьте координаты.': '❌ These coordinates belong to a different tribe. Check the coordinates.',
    'Введите целое число от 0 до 20.': 'Enter a whole number from 0 to 20.',
    'Откройте личный чат с ботом, нажмите /start → Инструкция': 'Open a private chat with the bot and send /start → Guide',
    '➕ Запросить деф': '➕ Request defence',
    '⚙️ Мои настройки': '⚙️ My settings',
    '🇫🇷 Галл': '🇫🇷 Gaul',
    '🇩🇪 Германец': '🇩🇪 Teuton',
    '🇮🇹 Римлянин': '🇮🇹 Roman',
    'войска не указаны': 'no troops entered',
    '📊 Оборона альянса': '📊 Alliance defence',
    '🏆 Рейтинг деферов': '🏆 Defender rankings',
    ' полей/ч': ' fields/hour',
    '📍 Герой здесь / убрать': '📍 Hero here / remove',
    '❌ Не удалось прочитать последний слепок map.sql. Попробуйте ещё раз чуть позже.': '❌ Could not read the latest map.sql snapshot. Please try again later.',
    '❌ Деревня <code>': '❌ Village <code>',
    '</code> не найдена в последнем слепке <code>': '</code> was not found in the latest snapshot <code>',
    '</code>. Проверьте координаты.': '</code>. Check the coordinates.',
    '❌ Деревня найдена, но её раса не поддерживается ботом (tribe_id=<code>': '❌ The village was found, but its tribe is not supported (tribe_id=<code>',
    '❌ Этот Travian-аккаунт уже зарегистрирован в Defence Bot.\n\nОдин игровой аккаунт может использовать только один профиль бота.': '❌ This Travian account is already registered in Defence Bot.\n\nOne game account can use only one bot profile.',
    'Введите целое число 0 или больше.': 'Enter a whole number of 0 or more.',
    'Этот юнит не доступен для выбранной расы.': 'This unit is not available for the selected tribe.',
    '🆔 Ваш Telegram ID: <code>': '🆔 Your Telegram ID: <code>',
    'Введите до двух Telegram ID через запятую. Например: <code>111111111,222222222</code>': 'Enter up to two Telegram IDs separated by commas. For example: <code>111111111,222222222</code>',
    'Личные настройки изменяются только в личном чате': 'Personal settings can only be changed in private chat',
    'Настройки отправлены вам в личные сообщения': 'Settings have been sent to you privately',
    'Сначала откройте личный чат с ботом и нажмите /start': 'First open a private chat with the bot and send /start',
    'Доступ запрещён': 'Access denied',
    '<b>🧬 Выбор расы</b>\n\nВыберите вашу расу. После смены расы список доступных юнитов во всех ваших деревнях будет автоматически отфильтрован.': '<b>🧬 Select tribe</b>\n\nChoose your tribe. Changing it will automatically filter available unit types in all your villages.',
    '⬅️ Рейтинг': '⬅️ Rankings',
    '<b>🏘 Мои деревни</b>\n\nВыберите деревню:': '<b>🏘 My villages</b>\n\nChoose a village:',
    'Введите координаты новой деревни через пробел, например <code>45 -62</code>:': 'Enter the new village coordinates separated by a space, for example <code>45 -62</code>:',
    'Выберите деревню:': 'Choose a village:',
    'Выберите деревню для удаления:': 'Choose a village to delete:',
    'Введите количество <b>': 'Enter the number of <b>',
    '</b>. Сейчас: <b>': '</b>. Current: <b>',
    'Введите новые координаты через пробел, например <code>45 -62</code>:': 'Enter the new coordinates separated by a space, for example <code>45 -62</code>:',
    'Введите Telegram ID до двух заместителей через запятую.\nПример: <code>111111111,222222222</code>': 'Enter Telegram IDs for up to two substitutes, separated by commas.\nExample: <code>111111111,222222222</code>',
    '\n👤 Войска: <a href="tg://user?id=': '\n👤 Troops: <a href="tg://user?id=',
    '</a> · записал <a href="tg://user?id=': '</a> · recorded by <a href="tg://user?id=',
    'с': 's',
    '<b>🛡 ПЛАН ОТПРАВКИ</b>': '<b>🛡 DEPARTURE PLAN</b>',
    '<b>🛡 Отправка дефа</b>\n\n🏘 Деревня: <b>': '<b>🛡 Send defence</b>\n\n🏘 Village: <b>',
    '</b>\n⚔️ Войска: <b>': '</b>\n⚔️ Troops: <b>',
    '</b>\n⏱ Прибытие: <b>': '</b>\n⏱ Arrival: <b>',
    '</b>\n📦 Максимум: <b>': '</b>\n📦 Maximum: <b>',
    '</b> очков\n\nВведите количество дефа. Например: <code>10000</code>': '</b> points\n\nEnter defence points. For example: <code>10000</code>',
    '<b>🛡 ЗАПРОС НА ДЕФ #': '<b>🛡 DEFENCE REQUEST #',
    '</b>\n\n📍 Деревня: ': '</b>\n\n📍 Village: ',
    '\n👤 Игрок: <b>': '\n👤 Player: <b>',
    '</b>\n⚔️ Атака: <b>': '</b>\n⚔️ Attack: <b>',
    '</b>\n🛡 Требуется: <b>': '</b>\n🛡 Required: <b>',
    '</b> очков дефа\n\nДеф должен прибыть <b>ДО</b> указанного времени.': '</b> defence points\n\nDefence must arrive <b>BEFORE</b> this time.',
    '<b>🛡 ЗАПРОС НА ДЕФ</b>\n\n📍 Деревня: ': '<b>🛡 DEFENCE REQUEST</b>\n\n📍 Village: ',
    '</b> очков дефа\n\nПехота = 1\nКонница = 2\n\nДеф должен прибыть <b>ДО</b> указанного времени.\n\nВсё верно?': '</b> defence points\n\nInfantry = 1\nCavalry = 2\n\nDefence must arrive <b>BEFORE</b> this time.\n\nIs everything correct?',
    '<b>🛡 Запросить деф</b>\n\nВведите координаты деревни назначения.\nНапример: <code>45 -62</code>': '<b>🛡 Request defence</b>\n\nEnter the target village coordinates.\nFor example: <code>45 -62</code>',
    '<b>🛡 ЦЕНТР ДЕФА</b>': '<b>🛡 DEFENCE CENTRE</b>',
    '<b>📋 АКТИВНЫЕ ЗАЯВКИ</b>': '<b>📋 ACTIVE REQUESTS</b>',
    '🛡 Чтобы помочь, нажмите «Отправить деф».': '🛡 To help, tap “Send defence”.',
    'Время атаки попадает на перевод часов Travian: укажите однозначное время.': 'The attack time falls within a Travian daylight saving clock change: choose an unambiguous time.',
    'ч ': 'h ',
    'м': 'm',
    'м ': 'm ',
    'нет времени': 'no time left',
    'нет указанных войск': 'no troops entered',
    'нет доступных войск': 'no available troops',
    ' +герой': ' +hero',
    'ближайшее: ': 'earliest: ',
    '<b>Итого: ': '<b>Total: ',
    ' очков</b>': ' points</b>',
    '<b>🛡 ОТПРАВИТЬ ДЕФ #': '<b>🛡 SEND DEFENCE #',
    '📍 Цель: ': '📍 Target: ',
    '⚔️ Прибыть до: <b>': '⚔️ Arrive before: <b>',
    '🛡 Осталось закрыть: <b>': '🛡 Still needed: <b>',
    '</b> очков': '</b> points',
    '<b>По данным настроек можно отправить из:</b>': '<b>Based on your settings, you can send from:</b>',
    '<b>🤖 ОПТИМАЛЬНЫЙ ПЛАН ЗАЩИТЫ #': '<b>🤖 OPTIMAL DEFENCE PLAN #',
    '🎯 Цель: ': '🎯 Target: ',
    '⚔️ Атака: <b>': '⚔️ Attack: <b>',
    '<b>Рекомендуется:</b>': '<b>Recommended:</b>',
    '📊 План: <b>': '📊 Plan: <b>',
    '</b> · 🐎 Конница: <b>': '</b> · 🐎 Cavalry: <b>',
    'ℹ️ План рекомендательный. Он рассчитан по войскам, указанным игроками в настройках; их фактическая доступность боту неизвестна.': 'ℹ️ This is a recommendation based on troops entered by players. The bot cannot know their actual availability.',
    '<b>🛡 НОВАЯ ЗАЯВКА НА ДЕФ</b>': '<b>🛡 NEW DEFENCE REQUEST</b>',
    '<b>Ты можешь успеть из:</b>': '<b>You could arrive in time from:</b>',
    'Если можешь помочь, открой «Отправить деф» в Центре дефа.': 'If you can help, open “Send defence” in the Defence Centre.',
    'Активных заявок нет.': 'No active requests.',
    'Введите требуемое количество дефа.\n\n<b>Пехота = 1\nКонница = 2</b>\n\nНапример:\n5000 пехоты = 5000\n2500 конницы = 5000\n1000 пехоты + 2000 конницы = 5000': 'Enter the defence points required.\n\n<b>Infantry = 1\nCavalry = 2</b>\n\nExamples:\n5000 infantry = 5000\n2500 cavalry = 5000\n1000 infantry + 2000 cavalry = 5000',
    '⏳ Сохраняю заявку…': '⏳ Saving request…',
    '<b>🛡 ОТПРАВИТЬ ДЕФ</b>\n\nВыберите заявку:': '<b>🛡 SEND DEFENCE</b>\n\nChoose a request:',
    '<b>🗑 УДАЛИТЬ ЗАЯВКУ</b>\n\nВыберите заявку:': '<b>🗑 DELETE REQUEST</b>\n\nChoose a request:',
    '<b>🛡 ЦЕНТР ДЕФА</b>\n\nУдаление заявки отменено.': '<b>🛡 DEFENCE CENTRE</b>\n\nRequest deletion cancelled.',
    '<b>🏘 Выберите ещё одну деревню:</b>': '<b>🏘 Choose another village:</b>',
    '<b>🛡 ЗАПРОС НА ДЕФ</b>\n\nЗаявка отменена.': '<b>🛡 DEFENCE REQUEST</b>\n\nRequest cancelled.',
    '🦸 Герой': '🦸 Hero',
    '🐏 + 1 таран': '🐏 + 1 ram',
    '🪨 + 1 катапульта': '🪨 + 1 catapult',
    '⚡ Быстрая отправка': '⚡ Quick send',
    '⬅️ К заявке': '⬅️ Back to request',
    '❌ Отмена': '❌ Cancel',
    ' · 🦸 с героем': ' · 🦸 with hero',
    '\n🚨 Отправить: <b>': '\n🚨 Send at: <b>',
    '</b>\n🔔 Напомню: <b>': '</b>\n🔔 Reminder at: <b>',
    '✅ Готово': '✅ Done',
    '⚪ В настройках нет подходящих данных для расчёта времени отправки.': '⚪ Your settings do not contain suitable data for a departure calculation.',
    'Фактический деф всё равно можно указать кнопкой ниже.': 'You can still record your actual defence using the button below.',
    ' + герой': ' + hero',
    'Нажми «Отправить деф» и сначала укажи фактическое количество.': 'Tap “Send defence” and enter the actual amount first.',
    '💡 Пехота = 1 очко · Конница = 2 очка.': '💡 Infantry = 1 point · Cavalry = 2 points.',
    '🛡 Отправить деф от себя': '🛡 Send my defence',
    '⬅️ К заявкам': '⬅️ Back to requests',
    '⚠️ По указанным в настройках войскам не хватает: <b>': '⚠️ Troops in player settings are short by: <b>',
    '✅ Заявка теоретически закрывается только пехотой.': '✅ This request could be covered by infantry alone.',
    '⚠️ Для полного закрытия по текущему расчёту требуется конница.': '⚠️ Cavalry is needed to fully cover this request in the current calculation.',
    '🎯 Цель: <b>': '🎯 Target: <b>',
    '👤 Игрок: <b>': '👤 Player: <b>',
    '🛡 Требуется: <b>': '🛡 Required: <b>',
    '🛡 ЦЕНТР ДЕФА': '🛡 DEFENCE CENTRE',
    '\n\nВыберите действие:': '\n\nChoose an action:',
    '❌ Доступ к аккаунту больше недоступен. Выберите отправку заново.': '❌ Account access is no longer available. Start sending again.',
    'Введите положительное количество очков дефа.': 'Enter a positive number of defence points.',
    '❌ Эта заявка уже закрыта или недоступна.': '❌ This request is already closed or unavailable.',
    '\n⏱ Записаны только очки дефа. Время отправки и напоминание не назначены.': '\n⏱ Only defence points were recorded. No departure time or reminder has been set.',
    '❌ Эта деревня уже не успевает.': '❌ This village can no longer arrive in time.',
    '<b>🚨 Когда отправлять</b>\n\n🏘 <b>': '<b>🚨 When to send</b>\n\n🏘 <b>',
    '</b> очков\n\nВыбери вариант:': '</b> points\n\nChoose an option:',
    'Неизвестно': 'Unknown',
    '📍 Деревня: ': '📍 Village: ',
    '</b>\n\n📅 Выберите дату атаки:': '</b>\n\n📅 Choose the attack date:',
    'Некорректное или неоднозначное время. Используйте время Travian: <code>17.09.2026 21:30:45</code>. В час перевода часов выберите однозначное время.': 'Invalid or ambiguous time. Use Travian time: <code>17.09.2026 21:30:45</code>. During a clock change, choose an unambiguous time.',
    'Введите целое положительное число, например <code>5000</code>.': 'Enter a positive whole number, for example <code>5000</code>.',
    'Не удалось начать сохранение. Попробуйте ещё раз.': 'Could not start saving. Please try again.',
    'Вам пока не доверили другие аккаунты. Владелец должен добавить ваш Telegram ID в «Мои настройки → Заместители».': 'No other accounts have authorised you yet. The owner must add your Telegram ID in “My settings → Substitutes”.',
    '👥 С какого аккаунта отправить деф?': '👥 Which account are you sending defence from?',
    '❌ У вас нет доступа к этому аккаунту.': '❌ You do not have access to this account.',
    '❌ Доступ к аккаунту отозван. Выберите отправку заново.': '❌ Account access was revoked. Start sending again.',
    'Эта форма уже завершена. Выберите отправку заново.': 'This form has already been completed. Start sending again.',
    '<b>🔔 Личные уведомления подключены.</b>\n\nКогда появляется новая заявка на деф, бот будет писать вам в личку, если хотя бы одна из настроенных деревень теоретически успевает прибыть до атаки.': '<b>🔔 Private notifications enabled.</b>\n\nWhen a new defence request appears, the bot will message you privately if at least one configured village could theoretically arrive before the attack.',
    '<b>🔔 Личные уведомления</b>\n\nЧтобы подключить уведомления, откройте личный чат с этим ботом и отправьте команду <code>/start</code>.\n\nПосле этого бот сможет писать вам в личку о новых заявках, если ваш деф теоретически успевает прибыть вовремя.': '<b>🔔 Private notifications</b>\n\nTo enable notifications, open a private chat with this bot and send <code>/start</code>.\n\nThe bot can then privately notify you about new requests when your defence could theoretically arrive in time.',
    '<b>🛡 ОТПРАВИТЬ ДЕФ</b>\n\nАктивных заявок нет.': '<b>🛡 SEND DEFENCE</b>\n\nNo active requests.',
    '<b>🗑 УДАЛИТЬ ЗАЯВКУ</b>\n\nАктивных заявок нет.': '<b>🗑 DELETE REQUEST</b>\n\nNo active requests.',
    '❌ Эта заявка уже не активна.': '❌ This request is no longer active.',
    '❌ Удалить заявку может только её создатель.': '❌ Only the creator can delete this request.',
    '<b>🗑 УДАЛЕНИЕ ЗАЯВКИ #': '<b>🗑 DELETE REQUEST #',
    '</b>\n\n📍 Цель: ': '</b>\n\n📍 Target: ',
    '</b>\n🛡 Деф: <b>': '</b>\n🛡 Defence: <b>',
    '</b> очков\n\nЗаявка больше не нужна? Она будет снята с активных заявок.': '</b> points\n\nIs this request no longer needed? It will be removed from active requests.',
    '<b>✅ Заявка #': '<b>✅ Request #',
    ' удалена.</b>\n\nОна больше не отображается среди активных заявок.': ' deleted.</b>\n\nIt no longer appears in active requests.',
    '❌ Эта заявка уже закрыта.': '❌ This request is already closed.',
    'Сколько дефа вы фактически отправите?\nВведите количество очков дефа, например: <code>10000</code>': 'How much defence will you actually send?\nEnter defence points, for example: <code>10000</code>',
    '</b>\n🛡 В настройках указано: <b>': '</b>\n🛡 In your settings: <b>',
    '</b> очков дефа\n\nСколько отправите фактически?\n\n💡 Пехота = 1 очко · Конница = 2 очка': '</b> defence points\n\nHow much will you actually send?\n\n💡 Infantry = 1 point · Cavalry = 2 points',
    '❌ План отправки устарел. Начните выбор заново.': '❌ The departure plan is outdated. Start selecting again.',
    '❌ Этот вариант уже не успевает.': '❌ This option can no longer arrive in time.',
    '❌ План отправки устарел.': '❌ The departure plan is outdated.',
    '❌ План отправки пуст или заявка уже закрыта.': '❌ The departure plan is empty or the request is already closed.',
    '❌ Не удалось сохранить отправку дефа. Попробуйте ещё раз.': '❌ Could not save the contribution. Please try again.',
    '\n\n✅ Записано: <b>': '\n\n✅ Recorded: <b>',
    '</b> очков.': '</b> points.',
    '\nОсталось: <b>': '\nRemaining: <b>',
    '📅 Дата атаки: <b>': '📅 Attack date: <b>',
    '</b>\n\n⏰ Введите время атаки по времени сервера Travian.\nФормат: <code>22:30:45</code>': '</b>\n\n⏰ Enter the attack time in Travian server time.\nFormat: <code>22:30:45</code>',
    'Это старое подтверждение. Откройте актуальную форму заявки.': 'This confirmation is outdated. Open the current request form.',
    '🛡 Отправить деф': '🛡 Send defence',
    '🗑 Удалить заявку': '🗑 Delete request',
    '⚡ Без героя': '⚡ Without hero',
    ' · 🐏 + 1 таран': ' · 🐏 + 1 ram',
    '➕ Добавить ещё деревню': '➕ Add another village',
    ', до <b>': ', up to <b>',
    '</b> очков, прибытие <b>': '</b> points, arrival <b>',
    '👥 Отправить деф с другого аккаунта': '👥 Send from another account',
    '✅ Создать заявку': '✅ Create request',
    '<b>🛡 Указано: ': '<b>🛡 Entered: ',
    ' очков дефа</b>\n\nТеперь выберите деревню отправки. Настройки используются только для расчёта времени отправки:': ' defence points</b>\n\nNow choose the source village. Settings are used only to calculate departure time:',
    '❌ В репозитории не найден ни одного сохранённого слепка карты.': '❌ No saved map snapshots were found in the repository.',
    ' создана.</b>\n\nОна добавлена в Центр дефа.': ' created.</b>\n\nIt has been added to the Defence Centre.',
    ' — до ': ' — up to ',
    ' · 🪨 + 1 катапульта': ' · 🪨 + 1 catapult',
    '📅 Сегодня — ': '📅 Today — ',
    '📅 Завтра — ': '📅 Tomorrow — ',
    ' поля · отправить до <b>': ' fields · send by <b>',
    '📩 По этой заявке ранее заявлено из деревни: <b>': '📩 Already pledged from this village for this request: <b>',
    '🚨 Отправить до: <b>': '🚨 Send by: <b>',
    '🛡 Собрано: <b>': '🛡 Pledged: <b>',
    '⏳ Осталось собрать: <b>': '⏳ Still needed: <b>',
    '✅ Принято: <b>': '✅ Accepted: <b>',
    '</b> очков дефа в заявку #': '</b> defence points for request #',
    '❌ Деревня с координатами <code>': '❌ Village at <code>',
    '</code> не найдена в последнем слепке карты (<code>': '</code> was not found in the latest map snapshot (<code>',
    '</code>).\n\nПроверьте координаты и попробуйте ещё раз.': '</code>).\n\nCheck the coordinates and try again.',
    '</b>\n👤 Аккаунт: <b>': '</b>\n👤 Account: <b>',
    '\n🛡 Осталось закрыть: <b>': '\n🛡 Still needed: <b>',
    '</b> очков\n\n': '</b> points\n\n',
    '⚡ Только учёт очков: без расчёта времени и напоминания.\n': '⚡ Points only: no departure calculation or reminder.\n',
    ' уже создана.</b>\n\nПовторно создавать её не нужно.': ' already exists.</b>\n\nThere is no need to create it again.',
    '❌ Не удалось сохранить заявку. Повторите попытку — дубликат не создастся.': '❌ Could not save the request. Try again — this will not create a duplicate.',
    '🛡 Отправить деф #': '🛡 Send defence #',
    '🗑 Заявка #': '🗑 Request #',
    '✅ Да, удалить заявку': '✅ Yes, delete request',
    '➕ Отправить ещё деф': '➕ Send more defence',
    '🔄 Повторить сохранение': '🔄 Retry saving',
    '<b>🔔 Личные уведомления подключены.</b>\n\nТеперь бот будет писать вам в личку, когда появляется новая заявка на деф и хотя бы одна из ваших настроенных деревень теоретически успевает прибыть до атаки.\n\nКоличество доступного дефа не используется как условие для уведомления.': '<b>🔔 Private notifications enabled.</b>\n\nThe bot will message you privately when a new defence request appears and at least one configured village could theoretically arrive before the attack.\n\nThe amount of available defence is not a condition for this notification.',
    'Данные изменились одновременно с вашим действием. Откройте заявку заново и повторите действие.': 'The data changed while you were acting. Open the request again and retry.',
    'игрок': 'player',
    '<b>🔄 Пора обновить данные о дефе</b>': '<b>🔄 Time to update your defence data</b>',
    ', проверь количество войск в своих деревнях.': ', please check the troop counts in your villages.',
    'Актуальные данные помогают точнее рассчитывать уведомления и оптимальный план защиты.': 'Up-to-date data improves notifications and the optimal defence plan.',
    '<b>Сейчас у тебя указано:</b>': '<b>Your current settings:</b>',
    'Деревни и войска пока не указаны.': 'No villages or troops entered yet.',
    '</b> · Арена ': '</b> · Tournament Square ',
    'Войска не указаны': 'No troops entered',
    '🦸 <b>Герой находится здесь</b>': '🦸 <b>Hero is here</b>',
    'Если данные изменились, открой <b>⚙️ Мои настройки</b> в Центре дефа и обнови их.': 'If anything has changed, open <b>⚙️ My settings</b> in the Defence Centre and update it.',
}
UNIT_NAMES_EN = {
    'legionnaire': 'Legionnaire', 'praetorian': 'Praetorian', 'imperian': 'Imperian',
    'equites_legati': 'Equites Legati', 'equites_imperatoris': 'Equites Imperatoris',
    'equites_caesaris': 'Equites Caesaris', 'ram': 'Ram', 'catapult': 'Catapult',
    'senator': 'Senator', 'settler': 'Settler', 'phalanx': 'Phalanx', 'swordsman': 'Swordsman',
    'pathfinder': 'Pathfinder', 'theutates_thunder': 'Theutates Thunder', 'druidrider': 'Druidrider',
    'haeduan': 'Haeduan', 'clubswinger': 'Clubswinger', 'spearman': 'Spearman', 'axeman': 'Axeman',
    'scout': 'Scout', 'paladin': 'Paladin', 'teutonic_knight': 'Teutonic Knight', 'chief': 'Chief',
}


def tr(text):
    """Translate source UI literals; never translate player-entered text."""
    return TRANSLATIONS.get(text, text) if _language.get() == 'en' else text


def gear_label(text):
    pairs=(('🦸 Герой','🦸 Hero'),('⚡ Без героя','⚡ Without hero'),('🐏 + 1 таран','🐏 + 1 ram'),('🪨 + 1 катапульта','🪨 + 1 catapult'))
    for ru,en in pairs:
        source,target=(ru,en) if _language.get()=='en' else (en,ru)
        if text==source or text.startswith(source+' · '):
            return target+text[len(source):]
    return text


@contextmanager
def language_scope(player):
    token = _language.set('en' if player.get('telegram_language') == 'en' else 'ru')
    try:
        yield
    finally:
        _language.reset(token)


def shared_language(function):
    @wraps(function)
    def wrapped(*args, **kwargs):
        with language_scope({}):
            return function(*args, **kwargs)
    return wrapped


def handle_language(message=None, callback=None):
    query=callback or {}
    message=message or query.get('message') or {}
    action=str(query.get('data') or '')
    text=str(message.get('text') or '').split()
    command=text[0].split('@')[0] if text else ''
    if not action.startswith('def_language:') and command!='/language':return False
    chat=message.get('chat') or {}
    if chat.get('type')!='private' and not in_def_thread(message):return False
    user=query.get('from') or message.get('from') or {}
    if not user.get('id'):return True
    data,player=get_player(user)
    choice=action.partition(':')[2]
    if choice in ('ru','en'):
        player['telegram_language']=choice
        save_players(data)
    with language_scope(player):
        if choice in ('ru','en'):
            reply='✅ English selected.' if choice=='en' else '✅ Выбран русский язык.'
            markup=main_menu()
        else:
            reply='🌐 Выберите язык / Choose your language'
            markup=kb([[{'text':'🇷🇺 Русский','callback_data':'def_language:ru'}, {'text':'🇬🇧 English','callback_data':'def_language:en'}]])
        if chat.get('type')=='private':
            if callback:edit(chat['id'],message['message_id'],reply,markup)
            else:send_private(chat['id'],reply,markup)
        else:
            try:
                send_private(user['id'],reply,markup)
                answer_callback(query.get('id'),tr('Настройки отправлены вам в личные сообщения'))
            except Exception:
                answer_callback(query.get('id'),tr('Сначала откройте личный чат с ботом и нажмите /start'))
        if chat.get('type')=='private' and callback:answer_callback(query.get('id'))
    return True


TELEGRAM_PROXY_URL = os.environ.get("TELEGRAM_PROXY_URL")
TELEGRAM_PROXIES = {"https": TELEGRAM_PROXY_URL} if TELEGRAM_PROXY_URL else None
DEFENCE_WORKER_URL = os.environ.get("DEFENCE_WORKER_URL", "http://127.0.0.1:18788").rstrip("/")
DEFENCE_WORKER_PROXY_URL = os.environ.get("DEFENCE_WORKER_PROXY_URL") or TELEGRAM_PROXY_URL
DEFENCE_WORKER_PROXIES = {"https": DEFENCE_WORKER_PROXY_URL} if DEFENCE_WORKER_PROXY_URL else None
if DEFENCE_WORKER_URL == "http://127.0.0.1:18788":
    DEFENCE_WORKER_PROXIES = {"http": "", "https": ""}

TELEGRAM_TOKEN = os.environ.get("DEFENCE_TELEGRAM_TOKEN") or os.environ.get("TELEGRAM_TOKEN")
THREAD_ID = 38636
POLL_TIMEOUT = 25
REQUEST_TIMEOUT = 40
DATA_DIR = Path("data/defence")
SETTINGS_FILE = DATA_DIR / "settings.json"
STATE_FILE = DATA_DIR / "state.json"
PLAYERS_FILE = DATA_DIR / "players.json"
REQUESTS_FILE = DATA_DIR / "requests.json"
API = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}"
OWNER_TELEGRAM_ID = 317595036

INFANTRY_UNITS = {"phalanx", "spearman", "legionnaire", "praetorian"}
CAVALRY_UNITS = {"druidrider", "haeduan", "paladin", "equites_caesaris"}

RACES = {
    "gaul": {"name": tr('Галл'), "units": ["phalanx", "druidrider", "haeduan"]},
    "teuton": {"name": tr('Германец'), "units": ["spearman", "paladin"]},
    "roman": {"name": tr('Римлянин'), "units": ["legionnaire", "praetorian", "equites_caesaris"]},
}


def load_json(path, default):
    from defence_store import load
    return load(Path(path).name, default)


def save_json(path, value):
    from defence_store import save
    save(Path(path).name, value)


def settings():
    value=load_json(SETTINGS_FILE, {})
    if _language.get()=='en':
        value={**value,'units':{key:{**unit,'name':UNIT_NAMES_EN.get(key,unit.get('name',key))} for key,unit in value.get('units',{}).items()}}
    return value


def players():
    return load_json(PLAYERS_FILE, {})


def save_players(value):
    save_json(PLAYERS_FILE, value)
    # Interactive VPS sessions must never wait for GitHub.  Git persistence is
    # enabled only when explicitly requested by a maintenance/legacy process.
    if os.environ.get("DEFENCE_ENABLE_GIT_PERSIST") == "1" and os.environ.get("DEFENCE_DEFER_GIT") != "1":
        persist_data()


def persist_data():
    # State is durable on VPS. GitHub backup/update jobs run separately.
    return None


def tg(method, **kwargs):
    response = requests.post(f"{API}/{method}", data=kwargs, timeout=REQUEST_TIMEOUT, proxies=TELEGRAM_PROXIES)
    response.raise_for_status()
    result = response.json()
    if not result.get("ok"):
        raise RuntimeError(result)
    return result.get("result")


def is_private_chat_id(chat_id):
    return any(str(p.get("private_chat_id")) == str(chat_id) for p in players().values() if isinstance(p, dict) and p.get("private_chat_id"))


def send(chat_id, text, reply_markup=None, thread_id=THREAD_ID, force_reply=False):
    args = {"chat_id": chat_id, "text": text, "parse_mode": "HTML"}
    if thread_id is not None and not is_private_chat_id(chat_id):
        args["message_thread_id"] = thread_id
    if force_reply:
        args["reply_markup"] = json.dumps({"force_reply": True, "selective": False}, ensure_ascii=False)
    elif reply_markup:
        args["reply_markup"] = json.dumps(reply_markup, ensure_ascii=False)
    return tg("sendMessage", **args)


def edit(chat_id, message_id, text, reply_markup=None):
    args = {"chat_id": chat_id, "message_id": message_id, "text": text, "parse_mode": "HTML"}
    if reply_markup is not None:
        args["reply_markup"] = json.dumps(reply_markup, ensure_ascii=False)
    return tg("editMessageText", **args)


def send_private(chat_id, text, reply_markup=None):
    args = {"chat_id": chat_id, "text": text, "parse_mode": "HTML"}
    if reply_markup:
        args["reply_markup"] = json.dumps(reply_markup, ensure_ascii=False)
    return tg("sendMessage", **args)


def answer_callback(callback_id, text=None):
    try:
        kwargs = {"callback_query_id": callback_id}
        if text:
            kwargs["text"] = text
            kwargs["show_alert"] = False
        tg("answerCallbackQuery", **kwargs)
    except Exception:
        pass


def in_def_thread(message):
    return message.get("message_thread_id") == THREAD_ID


def kb(rows):
    return {"inline_keyboard": rows}



DEFENCE_GUIDE = (
    (tr('С чего начать'), tr('Бот помогает собрать защиту для деревни: показывает заявки, учитывает обещанный деф и рассчитывает время отправки.\n\n<b>Чтобы записать деф в заявку, не обязательно заранее заполнять деревни, армию и вещи героя.</b> Вы можете просто указать количество дефа. Настройки нужны для автоматического расчёта времени отправки и личных напоминаний за 5 минут до него.\n\nОткройте личный чат с ботом и нажмите /start. В чате альянса центр дефа открывается командой /def и доступен в закреплённом сообщении.\n\nБот сам не отправляет войска в Travian. Это делаете вы в игре.')),
    (tr('Настройте свои деревни'), tr('<b>Этот раздел необязателен для простой записи дефа в заявку.</b> Настройте деревни, если хотите пользоваться расчётом отправки и напоминаниями.\n\nОткройте «Мои настройки» → «Добавить деревню» и введите координаты через пробел, например 15 3. Можно добавить несколько деревень.\n\nВ разделе «Мои деревни» укажите уровень арены и количество каждого вида защитных войск. Координаты, арену и войска можно менять; ненужную деревню — удалить.\n\nОбновляйте эти данные после изменения армии: бот не считывает ваши войска из игры.')),
    (tr('Герой и снаряжение'), tr('В «Мои настройки» → «Герой и инвентарь» отметьте деревню, где находится герой, и имеющиеся предметы: знамёна, сапоги и карты.\n\nПри расчёте отправки бот предлагает доступные варианты движения с учётом настроек. Выбирайте вариант, который действительно используете в игре. Без героя его бонусы не действуют.')),
    (tr('Как попросить защиту'), tr('В центре дефа нажмите «Запросить деф». Введите координаты атакуемой деревни, дату и точное время прихода атаки, затем необходимое количество дефа.\n\nПосле ввода количества дефа заявка сразу публикуется. Если ошиблись, удалите свою заявку через меню бота.\n\nУказывайте время сервера Travian (Europe/London: летом UTC+1, зимой UTC), а не время на телефоне. Проверяйте дату: атака после полуночи относится уже к следующему дню.')),
    (tr('Как помочь союзнику'), tr('<b>Можно помочь и без заполнения деревень и вещей героя.</b> Нажмите «Отправить деф», выберите активную заявку и укажите, сколько дефа готовы выделить. Это очки защиты, а не просто число солдат.\n\nЕсли подходящих настроенных деревень нет, бот всё равно запишет ваш деф в заявку. Время отправки при этом не рассчитывается.\n\nЕсли нужен расчёт отправки и напоминание, выберите настроенную деревню и подходящий вариант движения. Вещи героя указывайте только если используете их. После выбора варианта отправки помощь сразу записывается. Для помощи из другой деревни нажмите «Отправить ещё деф».\n\nПосле ввода количества дефа без деревни или выбора варианта отправки вклад сразу учитывается в заявке. Не записывайте одну и ту же помощь повторно.')),
    (tr('Когда отправлять войска'), tr('Бот рассчитывает крайнее время отправки по расстоянию, скорости войск, арене и выбранным бонусам героя. Для смешанного отряда важна скорость самого медленного юнита. Варианты с тараном или катапультой требуют взять соответствующий юнит в отряд.\n\nПеред отправкой откройте Travian, проверьте состав и время прибытия. Отправьте войска как подкрепление в нужную деревню до прихода атаки.\n\nРасчёт бота помогает планировать, но окончательно проверяйте время в игре.')),
    (tr('Уведомления и напоминания'), tr('После /start бот может писать вам в личные сообщения. О новых заявках он уведомляет, если настроенная деревня теоретически успевает помочь. Управление — «Мои настройки» → «Личные уведомления».\n\nДля подтверждённого плана отправки предусмотрено личное напоминание за 5 минут до рассчитанного срока. В карточке плана показано время напоминания.\n\nОставьте личный чат с ботом доступным и проверяйте план заранее: если до отправки уже мало времени, не ждите напоминания.')),
    (tr('Как читать заявку и закрыть её'), tr('В центре дефа видны активные заявки: куда нужна помощь, время атаки, сколько дефа требуется и сколько уже записано участниками. Записанный деф не означает, что войска уже дошли в игре.\n\nКогда участники набрали необходимое количество дефа, заявка закрывается. После времени атаки она также перестаёт быть активной. Если помощь больше не нужна раньше, используйте «Удалить заявку» и подтвердите действие. Удаление доступно только при наличии прав на эту заявку.')),
    (tr('Рекомендованный план защиты'), tr('<b>Задача плана — собрать нужный деф и по возможности сберечь конницу.</b> Кони дороже и ценнее, поэтому бот старается обойтись пехотой.\n\n1. Сначала бот проверяет, какие войска по данным игроков ещё успевают к атаке.\n\n2. Из подходящей пехоты он сначала предлагает ближайшие деревни. Если пехоты хватает, конница в план не включается — даже если она стоит ближе.\n\n3. Если успевающей пехоты недостаточно, бот предлагает добрать недостающую защиту конницей. Если и её не хватает, карточка показывает нехватку.\n\n4. В карточке видно, из какой деревни, каких юнитов и сколько рекомендуется отправить, а также крайнее время отправки. План рассчитывается на оставшийся незакрытый объём заявки.\n\n<b>Это рекомендация, а не приказ и не автоматическая отправка.</b> Бот опирается на войска, указанные игроками в настройках, и не знает их фактическую доступность в игре. План не резервирует армию. Если готовы помочь, отдельно запишитесь через «Отправить деф» и согласуйте отправку с координатором.')),
    (tr('Остальные настройки и памятка'), tr('В личных настройках можно указать до двух заместителей: введите их Telegram ID через запятую. Свой ID можно узнать отдельной кнопкой и сообщить союзнику. Владельцу бота также доступны обзор обороны альянса и рейтинг деферов.\n\nПеред участием проверьте 4 вещи: координаты деревни, уровень арены, актуальные войска и время сервера. При изменении плана согласуйте помощь с координатором дефа.\n\nИнструкцию можно открыть повторно в главном меню в любой момент.')),
)


def defence_guide_page(page=0):
    try:
        page = int(page)
    except (TypeError, ValueError):
        page = 0
    page = max(0, min(page, len(DEFENCE_GUIDE) - 1))
    title, body = (tr(value) for value in DEFENCE_GUIDE[page])
    text = (tr('<b>📖 Инструкция · ') + f'{page + 1}' + '/' + f'{len(DEFENCE_GUIDE)}' + '</b>\n\n<b>' + f'{page + 1}' + '. ' + f'{title}' + '</b>\n\n' + f'{body}')
    nav = []
    if page:
        nav.append({"text": tr('⬅️ Назад'), "callback_data": f"def_guide:{page - 1}"})
    if page + 1 < len(DEFENCE_GUIDE):
        nav.append({"text": tr('Дальше ➡️'), "callback_data": f"def_guide:{page + 1}"})
    rows = [nav] if nav else []
    rows.append([{"text": tr('⬅️ Главное меню'), "callback_data": "menu"}])
    return text, kb(rows)


def handle_guide_callback(q):
    action = str(q.get("data", ""))
    if action != "def_guide" and not action.startswith("def_guide:"):
        return False
    message = q.get("message") or {}
    private = (message.get("chat") or {}).get("type") == "private"
    if not private and message.get("message_thread_id") != THREAD_ID:
        return True
    text, markup = defence_guide_page(action.partition(":")[2] or 0)
    answer_callback(q.get("id"))
    if private:
        edit(message["chat"]["id"], message["message_id"], text, markup)
    else:
        # Never replace the shared pinned centre with one reader's tutorial.
        try:
            send_private(q["from"]["id"], text, markup)
            answer_callback(q.get("id"), tr('Инструкция отправлена вам в личные сообщения'))
        except Exception:
            answer_callback(q.get("id"), tr('Откройте личный чат с ботом, нажмите /start → Инструкция'))
    return True


def main_menu():
    return kb([
        [{"text": tr('➕ Запросить деф'), "callback_data": "request_def"}],
        [{"text": tr('⚙️ Мои настройки'), "callback_data": "settings"}],
        [{"text": tr('📖 Инструкция'), "callback_data": "def_guide"}],
        [{"text": "🌐 Язык / Language", "callback_data": "def_language:menu"}],
    ])


def player_default(user):
    return {
        "telegram_id": user["id"],
        "username": user.get("username", ""),
        "first_name": user.get("first_name", ""),
        "race": None,
        "villages": [],
        "substitutes": [],
        "state": None,
        "private_chat_id": None,
        "private_notifications": True,
        "hero_inventory": {"standards": [], "boots": [], "maps": []},
    }


def get_player(user):
    data = players()
    key = str(user["id"])
    if key not in data:
        data[key] = player_default(user)
    data[key]["username"] = user.get("username", data[key].get("username", ""))
    data[key]["first_name"] = user.get("first_name", data[key].get("first_name", ""))
    data[key].setdefault("race", None)
    data[key].setdefault("villages", [])
    data[key].setdefault("substitutes", [])
    data[key].setdefault("state", None)
    data[key].setdefault("private_chat_id", None)
    data[key].setdefault("private_notifications", True)
    inv = data[key].setdefault("hero_inventory", {"standards": [], "boots": [], "maps": []})
    for kind in ("standards", "boots", "maps"):
        inv.setdefault(kind, [])
    # One-time compatibility: preserve old equipped standard/boots as owned items.
    for village in data[key].get("villages", []):
        hero = village.get("hero") or {}
        std = int(round(float(hero.get("standard_bonus", 0) or 0) * 100))
        boots = int(round(float(hero.get("boots_bonus", 0) or 0) * 100))
        if std and std not in inv["standards"]:
            inv["standards"].append(std)
        if boots and boots not in inv["boots"]:
            inv["boots"].append(boots)
    save_json(PLAYERS_FILE, data)
    return data, data[key]


def race_name(player):
    return tr(RACES.get(player.get("race"), {}).get("name", tr('не выбрана')))


def allowed_units(player):
    return RACES.get(player.get("race"), {}).get("units", [])


def race_keyboard():
    return kb([
        [{"text": tr('🇫🇷 Галл'), "callback_data": "race:gaul"}],
        [{"text": tr('🇩🇪 Германец'), "callback_data": "race:teuton"}],
        [{"text": tr('🇮🇹 Римлянин'), "callback_data": "race:roman"}],
        [{"text": tr('⬅️ Назад'), "callback_data": "settings"}],
    ])


def hero_inventory(player):
    inv = player.setdefault("hero_inventory", {"standards": [], "boots": [], "maps": []})
    for kind in ("standards", "boots", "maps"):
        inv.setdefault(kind, [])
        inv[kind] = sorted({int(x) for x in inv[kind] if int(x) > 0})
    return inv


def hero_village_index(player):
    for i, village in enumerate(player.get("villages", [])):
        if (village.get("hero") or {}).get("present"):
            return i
    return None


def settings_text(player):
    units = settings().get("units", {})
    inv = hero_inventory(player)
    lines = [tr('<b>🛡 Мои настройки дефа</b>'), "", (tr('🧬 Раса: <b>') + f'{race_name(player)}' + '</b>')]
    villages = player.get("villages", [])
    if not villages:
        lines.append(tr('Деревни пока не добавлены.'))
    for i, v in enumerate(villages, 1):
        lines.append(('<b>' + f'{i}' + '. ' + f'{v.get('coordinates', '?')}' + tr('</b> — Арена ') + f'{v.get('arena', 0)}'))
        active = [f"{units.get(k, {}).get('name', k)}: {n}" for k, n in v.get("troops", {}).items() if int(n or 0) > 0]
        lines.append("  " + (", ".join(active) if active else tr('войска не указаны')))
        if (v.get("hero") or {}).get("present"):
            lines.append(tr('  🦸 Герой находится здесь'))
    if any(inv.values()):
        lines += ["", tr('<b>🎒 Инвентарь героя:</b>')]
        lines.append(tr('🚩 Штандарты: ') + (", ".join(f"+{x}%" for x in inv["standards"]) or tr('нет')))
        lines.append(tr('🥾 Сапоги: ') + (", ".join(f"+{x}%" for x in inv["boots"]) or tr('нет')))
        lines.append(tr('🗺 Карты: ') + (", ".join(f"+{x}%" for x in inv["maps"]) or tr('нет')))
    notification_status = tr('подключены') if player.get("private_chat_id") and player.get("private_notifications", True) else tr('не подключены')
    lines += ["", (tr('🔔 Личные уведомления: <b>') + f'{notification_status}' + '</b>'), (tr('👥 Заместители: ') + f'{len(player.get('substitutes', []))}' + '/2')]
    return "\n".join(lines)


def is_owner(user):
    return int(user.get("id", 0) or 0) == OWNER_TELEGRAM_ID


def settings_kb(owner=False):
    rows = [
        [{"text": tr('🏘 Мои деревни'), "callback_data": "villages"}],
        [{"text": tr('🦸 Герой и инвентарь'), "callback_data": "hero_menu"}],
        [{"text": tr('🆔 Узнать мой Telegram ID'), "callback_data": "my_id"}],
        [{"text": tr('➕ Добавить деревню'), "callback_data": "add_village"}],
        [{"text": tr('✏️ Изменить деревню'), "callback_data": "edit_village"}],
        [{"text": tr('🗑 Удалить деревню'), "callback_data": "delete_village"}],
        [{"text": tr('👥 Заместители'), "callback_data": "subs"}],
        [{"text": tr('🔔 Личные уведомления'), "callback_data": "private_notify"}],
        [{"text": tr('📖 Инструкция'), "callback_data": "def_guide"}],
        [{"text": "🌐 Язык / Language", "callback_data": "def_language:menu"}],
        [{"text": tr('⬅️ Назад'), "callback_data": "menu"}],
    ]
    if owner:
        rows.insert(0, [{"text": tr('📊 Оборона альянса'), "callback_data": "alliance_def"}])
    return kb(rows)


def fmt_num(value):
    return f"{int(value):,}".replace(",", " ")


_member_tag_cache = {}


def telegram_member_tag(telegram_id):
    """Cache optional chat tags; profile lookup must not hold up defence work."""
    if not TELEGRAM_TOKEN or not telegram_id:
        return ""
    state = load_json(STATE_FILE, {})
    group_chat_id = state.get("center_chat_id") if isinstance(state, dict) else None
    if not group_chat_id:
        return ""
    key = (str(group_chat_id), str(telegram_id))
    now = time.monotonic()
    cached = _member_tag_cache.get(key)
    if cached and cached["expires"] > now:
        return cached["tag"]
    tag = cached["tag"] if cached else ""
    ttl = 30
    try:
        response = requests.get(
            f"{API}/getChatMember",
            params={"chat_id": int(group_chat_id), "user_id": int(telegram_id)},
            timeout=(2, 3),
            proxies=TELEGRAM_PROXIES,
        )
        payload = response.json()
        if response.ok and payload.get("ok"):
            tag = str((payload.get("result") or {}).get("tag") or "").strip()
            ttl = 300
    except Exception:
        print("Telegram member tag lookup unavailable; using cached label.", flush=True)
    _member_tag_cache[key] = {"tag": tag, "expires": time.monotonic() + ttl}
    return tag


def player_name(p):
    tag = telegram_member_tag(p.get("telegram_id"))
    return tag or p.get("player_name") or p.get("first_name") or (("@" + p.get("username")) if p.get("username") else str(p.get("telegram_id", "?")))


def defence_stats():
    units_cfg = settings().get("units", {})
    totals = {key: 0 for key in INFANTRY_UNITS | CAVALRY_UNITS}
    rows = []
    village_count = 0

    def collect_profile(p, platform):
        nonlocal village_count
        if not isinstance(p, dict):
            return
        inf = cav = 0
        per_unit = {key: 0 for key in totals}
        player_villages = []
        for v in p.get("villages", []):
            v_inf = v_cav = 0
            for key, raw in (v.get("troops") or {}).items():
                if key not in totals:
                    continue
                try:
                    amount = max(0, int(raw or 0))
                except (TypeError, ValueError):
                    amount = 0
                totals[key] += amount
                per_unit[key] += amount
                if key in INFANTRY_UNITS:
                    inf += amount
                    v_inf += amount
                else:
                    cav += amount
                    v_cav += amount
            if v_inf or v_cav:
                village_count += 1
                player_villages.append((v.get("coordinates", "?"), v_inf, v_cav))
        if not (inf or cav):
            return
        if platform == "discord":
            ident = "discord:" + str(p.get("discord_id", ""))
            name = p.get("player_name") or p.get("discord_global_name") or p.get("discord_username") or ident
        else:
            ident = "telegram:" + str(p.get("telegram_id", ""))
            name = player_name(p)
        rows.append({
            "id": ident, "platform": platform, "name": name,
            "inf": inf, "cav": cav, "score": inf + cav * 2,
            "units": per_unit, "villages": player_villages,
        })

    for p in players().values():
        collect_profile(p, "telegram")

    discord_data = load_json(DATA_DIR / "discord_players.json", {})
    if isinstance(discord_data, dict):
        for p in discord_data.values():
            collect_profile(p, "discord")

    rows.sort(key=lambda x: (-x["score"], x["name"].lower()))
    return totals, rows, village_count, units_cfg


def alliance_def_text():
    totals, rows, village_count, units_cfg = defence_stats()
    inf = sum(totals.get(k, 0) for k in INFANTRY_UNITS)
    cav = sum(totals.get(k, 0) for k in CAVALRY_UNITS)
    score = inf + cav * 2
    total_troops = inf + cav
    lines = [tr('<b>🛡 ОБОРОНА АЛЬЯНСА</b>'), "", (tr('👥 Игроков с дефом: <b>') + f'{len(rows)}' + '</b>'), (tr('🏘 Деф-деревень: <b>') + f'{village_count}' + '</b>'), "", (tr('🛡 Рейтинг дефа: <b>') + f'{fmt_num(score)}' + '</b>'), (tr('🚶 Пехота: <b>') + f'{fmt_num(inf)}' + '</b> (' + f'{inf * 100 / total_troops:.1f}' + '%)') if total_troops else tr('🚶 Пехота: <b>0</b>'), (tr('🐎 Конница: <b>') + f'{fmt_num(cav)}' + '</b> (' + f'{cav * 100 / total_troops:.1f}' + '%)') if total_troops else tr('🐎 Конница: <b>0</b>'), "", tr('<b>По юнитам:</b>')]
    for key in ("phalanx", "druidrider", "haeduan", "spearman", "paladin", "legionnaire", "praetorian", "equites_caesaris"):
        lines.append(f"{units_cfg.get(key, {}).get('name', key)} — <b>{fmt_num(totals.get(key, 0))}</b>")
    lines += ["", tr('ℹ️ Рейтинг: пехота ×1, конница ×2.'), tr('⚠️ Расчёт по войскам, указанным игроками в настройках.')]
    return "\n".join(lines)


def alliance_def_kb():
    return kb([[{"text": tr('🏆 Рейтинг деферов'), "callback_data": "def_rank"}], [{"text": tr('⬅️ Мои настройки'), "callback_data": "settings"}]])


def defence_rank_text():
    _, rows, _, _ = defence_stats()
    lines = [tr('<b>🏆 РЕЙТИНГ ДЕФЕРОВ</b>'), "", tr('Рейтинг = пехота ×1 + конница ×2'), ""]
    if not rows:
        lines.append(tr('Пока никто не указал деф.'))
    for i, row in enumerate(rows, 1):
        lines.append(f"{i}. <b>{row['name']}</b> — {fmt_num(row['score'])} 🛡")
    return "\n".join(lines)


def defence_rank_kb():
    _, rows, _, _ = defence_stats()
    buttons = [[{"text": f"{i}. {row['name']} — {fmt_num(row['score'])}", "callback_data": f"def_player:{row['id']}"}] for i, row in enumerate(rows, 1)]
    buttons.append([{"text": tr('⬅️ Общая армия'), "callback_data": "alliance_def"}])
    return kb(buttons)


def defence_player_text(player_id):
    _, rows, _, units_cfg = defence_stats()
    row = next((r for r in rows if str(r["id"]) == str(player_id)), None)
    if not row:
        return tr('Данные игрока не найдены.')
    place = rows.index(row) + 1
    lines = [f"<b>👤 {row['name']}</b>", "", (tr('🏆 Место: <b>') + f'{place}' + tr(' из ') + f'{len(rows)}' + '</b>'), (tr('🛡 Рейтинг: <b>') + f'{fmt_num(row['score'])}' + '</b>'), (tr('🚶 Пехота: <b>') + f'{fmt_num(row['inf'])}' + '</b>'), (tr('🐎 Конница: <b>') + f'{fmt_num(row['cav'])}' + '</b>'), "", tr('<b>По юнитам:</b>')]
    for key in ("phalanx", "druidrider", "haeduan", "spearman", "paladin", "legionnaire", "praetorian", "equites_caesaris"):
        amount = row["units"].get(key, 0)
        if amount:
            lines.append(f"{units_cfg.get(key, {}).get('name', key)} — <b>{fmt_num(amount)}</b>")
    lines += ["", tr('<b>По деревням:</b>')]
    for coords, inf, cav in row["villages"]:
        lines.append(f"🏘 <b>{coords}</b> — 🚶 {fmt_num(inf)} · 🐎 {fmt_num(cav)}")
    return "\n".join(lines)


def villages_kb(player, prefix="village"):
    rows = [[{"text": f"{i+1}. {v.get('coordinates', '?')}", "callback_data": f"{prefix}:{i}"}] for i, v in enumerate(player.get("villages", []))]
    rows.append([{"text": tr('➕ Добавить деревню'), "callback_data": "add_village"}])
    rows.append([{"text": tr('⬅️ Назад'), "callback_data": "settings"}])
    return kb(rows)


def unit_text(v, player):
    units = settings().get("units", {})
    lines = [(tr('<b>🏘 Деревня ') + f'{v.get('coordinates')}' + '</b>'), (tr('Арена: ') + f'{v.get('arena', 0)}'), "", tr('<b>Войска:</b>')]
    for key in allowed_units(player):
        unit = units.get(key)
        if not unit:
            continue
        amount = int(v.get("troops", {}).get(key, 0) or 0)
        if amount:
            lines.append((f'{unit['name']}' + ': <b>' + f'{amount}' + '</b> — ' + f'{unit['speed']}' + tr(' полей/ч')))
    if len(lines) == 4:
        lines.append(tr('пока не указаны'))
    if (v.get("hero") or {}).get("present"):
        lines += ["", tr('🦸 <b>Герой находится в этой деревне</b>')]
    return "\n".join(lines)


def unit_keyboard(index, player):
    rows = []
    units = settings().get("units", {})
    for key in allowed_units(player):
        unit = units.get(key)
        if unit:
            rows.append([{"text": unit["name"], "callback_data": f"unit:{index}:{key}"}])
    rows += [
        [{"text": tr('✏️ Координаты'), "callback_data": f"coords:{index}"}, {"text": tr('✏️ Арена'), "callback_data": f"arena:{index}"}],
        [{"text": tr('⬅️ Назад'), "callback_data": "villages"}],
    ]
    return kb(rows)


def hero_menu_text(player):
    inv = hero_inventory(player)
    idx = hero_village_index(player)
    village = player.get("villages", [])[idx] if idx is not None and idx < len(player.get("villages", [])) else None
    location = village.get("coordinates", "?") if village else tr('не выбран')
    return (
        (tr('<b>🦸 Герой и инвентарь</b>\n\n📍 Герой: <b>') + f'{location}' + tr('</b>\n\n<b>🎒 Доступно в инвентаре:</b>\n🚩 Штандарты: <b>') + f'{', '.join(('+' + str(x) + '%' for x in inv['standards'])) or tr('нет')}' + tr('</b>\n🥾 Сапоги: <b>') + f'{', '.join(('+' + str(x) + '%' for x in inv['boots'])) or tr('нет')}' + tr('</b>\n🗺 Карты: <b>') + f'{', '.join(('+' + str(x) + '%' for x in inv['maps'])) or tr('нет')}' + tr('</b>\n\nВыберите деревню, где находится герой, или измените инвентарь.'))
    )


def hero_menu_keyboard(player):
    inv = hero_inventory(player)
    def mark(kind, value, icon):
        return f"{'✅' if value in inv[kind] else '▫️'} {icon} +{value}%"
    rows = []
    for idx, village in enumerate(player.get("villages", [])):
        here = bool((village.get("hero") or {}).get("present"))
        rows.append([{"text": f"{'📍' if here else '▫️'} {village.get('coordinates', '?')}", "callback_data": f"hero_loc:{idx}"}])
    rows += [
        [{"text": mark("standards", 15, "🚩"), "callback_data": "hinv_main:standards:15"},
         {"text": mark("standards", 20, "🚩"), "callback_data": "hinv_main:standards:20"},
         {"text": mark("standards", 25, "🚩"), "callback_data": "hinv_main:standards:25"}],
        [{"text": mark("boots", 25, "🥾"), "callback_data": "hinv_main:boots:25"},
         {"text": mark("boots", 50, "🥾"), "callback_data": "hinv_main:boots:50"},
         {"text": mark("boots", 75, "🥾"), "callback_data": "hinv_main:boots:75"}],
        [{"text": mark("maps", 30, "🗺"), "callback_data": "hinv_main:maps:30"},
         {"text": mark("maps", 40, "🗺"), "callback_data": "hinv_main:maps:40"},
         {"text": mark("maps", 50, "🗺"), "callback_data": "hinv_main:maps:50"}],
        [{"text": tr('⬅️ Мои настройки'), "callback_data": "settings"}],
    ]
    return kb(rows)


def hero_text(v, player):
    inv = hero_inventory(player)
    return (
        (tr('<b>🦸 Герой — ') + f'{v.get('coordinates')}' + tr('</b>\n\nГерой находится здесь: <b>') + f'{(tr('да') if (v.get('hero') or {}).get('present') else tr('нет'))}' + tr('</b>\n\n<b>🎒 Доступно в инвентаре:</b>\n🚩 Штандарты: <b>') + f'{', '.join(('+' + str(x) + '%' for x in inv['standards'])) or tr('нет')}' + tr('</b>\n🥾 Сапоги: <b>') + f'{', '.join(('+' + str(x) + '%' for x in inv['boots'])) or tr('нет')}' + tr('</b>\n🗺 Карты: <b>') + f'{', '.join(('+' + str(x) + '%' for x in inv['maps'])) or tr('нет')}' + tr('</b>\n\nНажатие на предмет добавляет или убирает его из инвентаря.'))
    )


def hero_keyboard(idx, player):
    inv = hero_inventory(player)
    def mark(kind, value, icon):
        return f"{'✅' if value in inv[kind] else '▫️'} {icon} +{value}%"
    return kb([
        [{"text": tr('📍 Герой здесь / убрать'), "callback_data": f"hero_present:{idx}"}],
        [{"text": mark("standards", 15, "🚩"), "callback_data": f"hinv:{idx}:standards:15"},
         {"text": mark("standards", 20, "🚩"), "callback_data": f"hinv:{idx}:standards:20"},
         {"text": mark("standards", 25, "🚩"), "callback_data": f"hinv:{idx}:standards:25"}],
        [{"text": mark("boots", 25, "🥾"), "callback_data": f"hinv:{idx}:boots:25"},
         {"text": mark("boots", 50, "🥾"), "callback_data": f"hinv:{idx}:boots:50"},
         {"text": mark("boots", 75, "🥾"), "callback_data": f"hinv:{idx}:boots:75"}],
        [{"text": mark("maps", 30, "🗺"), "callback_data": f"hinv:{idx}:maps:30"},
         {"text": mark("maps", 40, "🗺"), "callback_data": f"hinv:{idx}:maps:40"},
         {"text": mark("maps", 50, "🗺"), "callback_data": f"hinv:{idx}:maps:50"}],
        [{"text": tr('⬅️ Назад'), "callback_data": f"village:{idx}"}],
    ])

def parse_coords(value):
    try:
        parts = value.split()
        if len(parts) != 2:
            return None
        x, y = int(parts[0]), int(parts[1])
        if -200 <= x <= 200 and -200 <= y <= 200:
            return f"{x} {y}"
    except (ValueError, TypeError):
        pass
    return None


def to_int(value):
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def process_text(message):
    user = message.get("from", {})
    text = (message.get("text") or "").strip()
    is_private = message.get("chat", {}).get("type") == "private"
    if not text or (not is_private and not in_def_thread(message)):
        return
    data, player = get_player(user)
    state = player.get("state")
    chat_id = message["chat"]["id"]
    if text.startswith("/start") and is_private:
        player["state"] = None
        player["private_chat_id"] = chat_id
        player["private_notifications"] = True
        save_players(data)
        send(chat_id, settings_text(player), settings_kb(is_owner(user)), thread_id=None)
        return
    if text.startswith("/def") and not is_private:
        player["state"] = None
        save_players(data)
        send(chat_id, tr('<b>🛡 ЦЕНТР ДЕФА</b>\n\nВыберите раздел:'), main_menu())
        return
    if not state:
        return
    if state == "add_village_coords":
        coords = parse_coords(text)
        if coords is None:
            send(chat_id, tr('Неверный формат. Введите координаты через пробел, например: <code>45 -62</code>'), force_reply=True)
            return
        try:
            from defence_requests import find_target, race_from_village
            village, snapshot_path = find_target(coords)
            detected_race = race_from_village(village) if village else None
        except Exception as exc:
            print(f"Defence village lookup failed for {coords}: {exc!r}", flush=True)
            send(
                chat_id,
                tr('❌ Не удалось прочитать последний слепок map.sql. Попробуйте ещё раз чуть позже.'),
                force_reply=True,
            )
            return
        if village is None:
            snapshot_name = snapshot_path.name if snapshot_path else tr('не найден')
            send(
                chat_id,
                (tr('❌ Деревня <code>') + f'{html.escape(coords)}' + tr('</code> не найдена в последнем слепке <code>') + f'{html.escape(snapshot_name)}' + tr('</code>. Проверьте координаты.')),
                force_reply=True,
            )
            return
        if detected_race is None:
            tribe_id = village.get("tribe_id")
            send(
                chat_id,
                (tr('❌ Деревня найдена, но её раса не поддерживается ботом (tribe_id=<code>') + f'{html.escape(str(tribe_id))}' + '</code>).'),
                force_reply=True,
            )
            return
        travian_uid = int(village.get("uid", 0) or 0)
        if travian_uid <= 0:
            send(chat_id, tr('❌ Не удалось определить владельца этой деревни в map.sql.'), force_reply=True)
            return

        current_uid = int(player.get("travian_uid", 0) or 0)
        if current_uid and current_uid != travian_uid:
            send(
                chat_id,
                tr('❌ Эта деревня принадлежит другому Travian-аккаунту. В одном профиле Defence Bot можно хранить деревни только одного игрового аккаунта.'),
                force_reply=True,
            )
            return

        # One Travian account may belong to only one Defence Bot profile.
        # Check the stable Travian UID, not Telegram nickname or village name.
        for other_key, other_player in data.items():
            if other_player is player or not isinstance(other_player, dict):
                continue
            other_uid = int(other_player.get("travian_uid", 0) or 0)
            if not other_uid:
                # Backfill legacy profiles from any already saved village.
                for saved_village in other_player.get("villages", []):
                    saved_coords = saved_village.get("coordinates")
                    if not saved_coords:
                        continue
                    try:
                        saved_map_village, _ = find_target(saved_coords)
                    except Exception:
                        saved_map_village = None
                    if saved_map_village:
                        other_uid = int(saved_map_village.get("uid", 0) or 0)
                        if other_uid:
                            other_player["travian_uid"] = other_uid
                            break
            if other_uid == travian_uid:
                save_players(data)
                send(
                    chat_id,
                    tr('❌ Этот Travian-аккаунт уже зарегистрирован в Defence Bot.\n\nОдин игровой аккаунт может использовать только один профиль бота.'),
                    force_reply=True,
                )
                return

        current_race = player.get("race")
        if current_race and current_race != detected_race:
            send(chat_id, tr('❌ Координаты этой деревни принадлежат другой расе. Проверьте координаты.'), force_reply=True)
            return
        player["race"] = detected_race
        player["travian_uid"] = travian_uid
        player["state"] = {"type": "add_village_arena", "coordinates": coords, "travian_uid": travian_uid}
        save_players(data)
        send(chat_id, tr('Введите уровень Арены (0–20):'), force_reply=True)
        return
    typ = state.get("type") if isinstance(state, dict) else None
    if typ == "add_village_arena":
        arena = to_int(text)
        if arena is None or not 0 <= arena <= 20:
            send(chat_id, tr('Введите целое число от 0 до 20.'), force_reply=True)
            return
        player["villages"].append({"coordinates": state["coordinates"], "arena": arena, "troops": {}, "hero": {"present": False}})
        idx = len(player["villages"]) - 1
        player["state"] = None
        save_players(data)
        send(chat_id, unit_text(player["villages"][idx], player), unit_keyboard(idx, player))
    elif typ == "unit_amount":
        amount = to_int(text)
        if amount is None or amount < 0:
            send(chat_id, tr('Введите целое число 0 или больше.'), force_reply=True)
            return
        idx, unit = state["index"], state["unit"]
        if idx >= len(player["villages"]):
            return
        if unit not in allowed_units(player):
            player["state"] = None
            save_players(data)
            send(chat_id, tr('Этот юнит не доступен для выбранной расы.'), unit_keyboard(idx, player))
            return
        player["villages"][idx].setdefault("troops", {})[unit] = amount
        player["state"] = None
        save_players(data)
        send(chat_id, unit_text(player["villages"][idx], player), unit_keyboard(idx, player))
    elif typ == "subs":
        ids = [x.strip() for x in text.split(",") if x.strip()]
        if len(ids) > 2 or any(to_int(x) is None or to_int(x) <= 0 for x in ids):
            send(chat_id, tr('Введите до двух Telegram ID через запятую. Например: <code>111111111,222222222</code>'), force_reply=True)
            return
        player["substitutes"] = [int(x) for x in ids]
        player["state"] = None
        save_players(data)
        send(chat_id, settings_text(player), settings_kb(is_owner(user)))
    elif typ in ("coords", "arena"):
        idx = state["index"]
        if idx >= len(player["villages"]):
            return
        if typ == "coords":
            coords = parse_coords(text)
            if coords is None:
                send(chat_id, tr('Неверный формат. Введите координаты через пробел, например: <code>45 -62</code>'), force_reply=True)
                return
            player["villages"][idx]["coordinates"] = coords
        else:
            value = to_int(text)
            if value is None or not 0 <= value <= 20:
                send(chat_id, tr('Введите целое число от 0 до 20.'), force_reply=True)
                return
            player["villages"][idx]["arena"] = value
        player["state"] = None
        save_players(data)
        send(chat_id, unit_text(player["villages"][idx], player), unit_keyboard(idx, player))


def callback_query(q):
    if handle_guide_callback(q):
        return
    message = q.get("message", {})
    is_private = message.get("chat", {}).get("type") == "private"
    if not is_private and message.get("message_thread_id") != THREAD_ID:
        return
    user = q.get("from", {})
    data, player = get_player(user)
    chat_id, msg_id = message["chat"]["id"], message["message_id"]
    action = q.get("data", "")
    answer_callback(q["id"])

    if action == "menu":
        edit(chat_id, msg_id, tr('<b>🛡 ЦЕНТР ДЕФА</b>\n\nВыберите раздел:'), main_menu())
    elif action == "my_id":
        send(chat_id, (tr('🆔 Ваш Telegram ID: <code>') + f'{user.get('id')}' + '</code>'))
    elif action == "settings":
        if not is_private:
            private_chat_id = player.get("private_chat_id")
            if private_chat_id:
                send_private(private_chat_id, settings_text(player), settings_kb())
                answer_callback(q["id"], tr('Настройки отправлены вам в личные сообщения'))
            else:
                answer_callback(q["id"], tr('Сначала откройте личный чат с ботом и нажмите /start'))
            return
        edit(chat_id, msg_id, settings_text(player), settings_kb(is_owner(user)))
    elif not is_private and action not in ("menu", "request_def"):
        answer_callback(q["id"], tr('Личные настройки изменяются только в личном чате'))
        return
    elif action in ("alliance_def", "def_rank") or action.startswith("def_player:"):
        if not is_private or not is_owner(user):
            answer_callback(q["id"], tr('Доступ запрещён'))
            return
        if action == "alliance_def":
            edit(chat_id, msg_id, alliance_def_text(), alliance_def_kb())
        elif action == "def_rank":
            edit(chat_id, msg_id, defence_rank_text(), defence_rank_kb())
        else:
            profile_id = action.split(":", 1)[1]
            edit(chat_id, msg_id, defence_player_text(profile_id), kb([[{"text": tr('⬅️ Рейтинг'), "callback_data": "def_rank"}]]))
    elif action == "hero_menu":
        edit(chat_id, msg_id, hero_menu_text(player), hero_menu_keyboard(player))
    elif action.startswith("hero_loc:"):
        idx = int(action.split(":", 1)[1])
        if 0 <= idx < len(player.get("villages", [])):
            currently_here = bool((player["villages"][idx].get("hero") or {}).get("present"))
            for village in player.get("villages", []):
                village.setdefault("hero", {})["present"] = False
            if not currently_here:
                player["villages"][idx].setdefault("hero", {})["present"] = True
            save_players(data)
        edit(chat_id, msg_id, hero_menu_text(player), hero_menu_keyboard(player))
    elif action.startswith("hinv_main:"):
        _, kind, value = action.split(":", 2)
        value = int(value)
        inv = hero_inventory(player)
        if kind in ("standards", "boots", "maps"):
            if value in inv[kind]:
                inv[kind].remove(value)
            else:
                inv[kind].append(value)
                inv[kind].sort()
            save_players(data)
        edit(chat_id, msg_id, hero_menu_text(player), hero_menu_keyboard(player))
    elif action == "race_menu":
        edit(chat_id, msg_id, tr('<b>🧬 Выбор расы</b>\n\nВыберите вашу расу. После смены расы список доступных юнитов во всех ваших деревнях будет автоматически отфильтрован.'), race_keyboard())
    elif action.startswith("race:"):
        race = action.split(":", 1)[1]
        if race not in RACES:
            return
        player["race"] = race
        allowed = set(allowed_units(player))
        for village in player.get("villages", []):
            troops = village.setdefault("troops", {})
            village["troops"] = {key: value for key, value in troops.items() if key in allowed}
        player["state"] = None
        save_players(data)
        edit(chat_id, msg_id, settings_text(player), settings_kb())
    elif action == "villages":
        edit(chat_id, msg_id, tr('<b>🏘 Мои деревни</b>\n\nВыберите деревню:'), villages_kb(player))
    elif action == "add_village":
        player["state"] = "add_village_coords"
        save_players(data)
        send(chat_id, tr('Введите координаты новой деревни через пробел, например <code>45 -62</code>:'), force_reply=True)
    elif action == "edit_village":
        edit(chat_id, msg_id, tr('Выберите деревню:'), villages_kb(player))
    elif action == "delete_village":
        rows = [[{"text": f"🗑 {v.get('coordinates')}", "callback_data": f"delv:{i}"}] for i, v in enumerate(player.get("villages", []))]
        rows.append([{"text": tr('⬅️ Назад'), "callback_data": "settings"}])
        edit(chat_id, msg_id, tr('Выберите деревню для удаления:'), kb(rows))
    elif action.startswith("delv:"):
        idx = int(action.split(":", 1)[1])
        if 0 <= idx < len(player["villages"]):
            player["villages"].pop(idx)
            save_players(data)
        edit(chat_id, msg_id, settings_text(player), settings_kb())
    elif action.startswith("village:"):
        idx = int(action.split(":", 1)[1])
        if 0 <= idx < len(player.get("villages", [])):
            edit(chat_id, msg_id, unit_text(player["villages"][idx], player), unit_keyboard(idx, player))
    elif action.startswith("unit:"):
        _, idx, unit = action.split(":", 2)
        idx = int(idx)
        if idx < len(player["villages"]):
            if unit not in allowed_units(player) or unit not in settings().get("units", {}):
                edit(chat_id, msg_id, unit_text(player["villages"][idx], player), unit_keyboard(idx, player))
                return
            player["state"] = {"type": "unit_amount", "index": idx, "unit": unit}
            save_players(data)
            name = settings()["units"][unit]["name"]
            current = player["villages"][idx].get("troops", {}).get(unit, 0)
            send(chat_id, (tr('Введите количество <b>') + f'{name}' + tr('</b>. Сейчас: <b>') + f'{current}' + '</b>'), force_reply=True)
    elif action.startswith("coords:"):
        idx = int(action.split(":", 1)[1])
        if idx < len(player["villages"]):
            player["state"] = {"type": "coords", "index": idx}
            save_players(data)
            send(chat_id, tr('Введите новые координаты через пробел, например <code>45 -62</code>:'), force_reply=True)
    elif action.startswith("arena:"):
        idx = int(action.split(":", 1)[1])
        if idx < len(player["villages"]):
            player["state"] = {"type": "arena", "index": idx}
            save_players(data)
            send(chat_id, tr('Введите уровень Арены (0–20):'), force_reply=True)
    elif action.startswith("hero:"):
        idx = int(action.split(":", 1)[1])
        if idx < len(player["villages"]):
            player["villages"][idx].setdefault("hero", {"present": False})
            edit(chat_id, msg_id, hero_text(player["villages"][idx], player), hero_keyboard(idx, player))
    elif action.startswith("hero_present:"):
        idx = int(action.split(":", 1)[1])
        if idx < len(player["villages"]):
            currently_here = bool((player["villages"][idx].get("hero") or {}).get("present"))
            # There is only one hero per account.
            for village in player.get("villages", []):
                village.setdefault("hero", {})["present"] = False
            if not currently_here:
                player["villages"][idx]["hero"]["present"] = True
            save_players(data)
            edit(chat_id, msg_id, hero_text(player["villages"][idx], player), hero_keyboard(idx, player))
    elif action.startswith("hinv:"):
        _, idx_s, kind, value_s = action.split(":")
        idx, value = int(idx_s), int(value_s)
        if kind not in ("standards", "boots", "maps") or idx >= len(player["villages"]):
            return
        inv = hero_inventory(player)
        if value in inv[kind]:
            inv[kind].remove(value)
        else:
            inv[kind].append(value)
            inv[kind].sort()
        save_players(data)
        edit(chat_id, msg_id, hero_text(player["villages"][idx], player), hero_keyboard(idx, player))
    elif action == "subs":
        player["state"] = {"type": "subs"}
        save_players(data)
        send(chat_id, tr('Введите Telegram ID до двух заместителей через запятую.\nПример: <code>111111111,222222222</code>'), force_reply=True)


def run():
    if not TELEGRAM_TOKEN:
        raise RuntimeError("DEFENCE_TELEGRAM_TOKEN is not set")
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    offset = None
    print(f"DEFENCE BOT STARTED, THREAD_ID={THREAD_ID}", flush=True)
    while True:
        try:
            updates = tg("getUpdates", offset=offset, timeout=POLL_TIMEOUT, allowed_updates=json.dumps(["message", "callback_query"]))
            for update in updates:
                offset = update["update_id"] + 1
                if "callback_query" in update:
                    callback_query(update["callback_query"])
                elif "message" in update:
                    process_text(update["message"])
        except Exception as exc:
            print("Polling error:", exc, flush=True)
            time.sleep(5)


if __name__ == "__main__":
    run()