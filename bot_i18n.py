import json
import subprocess
from pathlib import Path

PREFERENCES_FILE = Path("data/users/preferences.json")
LANGUAGES = {"ru", "en", "ja"}

TRANSLATIONS = {
    "en": {
        "🌐 Язык / Language": "🌐 Language",
        "🔎 Поиск кропок": "🔎 Find crop fields",
        "✅ Проверить доступность": "✅ Check availability",
        "📌 Забронировать кропку": "📌 Reserve crop field",
        "📋 Моя бронь": "📋 My reservations",
        "👥 Все брони": "👥 All reservations",
        "⬅️ Меню": "⬅️ Menu",
        "Показать ещё ➡️": "Show more ➡️",
        "➕ Запросить деф": "➕ Request defence",
        "⚙️ Мои настройки": "⚙️ My settings",
        "🏘 Мои деревни": "🏘 My villages",
        "🆔 Узнать мой Telegram ID": "🆔 Show my Telegram ID",
        "➕ Добавить деревню": "➕ Add village",
        "✏️ Изменить деревню": "✏️ Edit village",
        "🗑 Удалить деревню": "🗑 Delete village",
        "👥 Заместители": "👥 Sitters",
        "🔔 Личные уведомления": "🔔 Private notifications",
        "⬅️ Назад": "⬅️ Back",
        "📊 Оборона альянса": "📊 Alliance defence",
        "📥 Отчёт об атаке": "📥 Incoming attack report",
        "🔎 Добавить скаут-проверку": "🔎 Add scout check",
        "🔭 План скаут-проверок": "🔭 Scout check plan",
        "📚 История скаутов": "📚 Scout history",
        "🏟 Офферы и Арены": "🏟 Off players & Tournament Squares",
        "⚙️ Настройки разведки": "⚙️ Scouting settings",
    },
    "ja": {
        "🌐 Язык / Language": "🌐 言語 / Language",
        "🔎 Поиск кропок": "🔎 クロップ村を探す",
        "✅ Проверить доступность": "✅ 空き状況を確認",
        "📌 Забронировать кропку": "📌 クロップ村を予約",
        "📋 Моя бронь": "📋 自分の予約",
        "👥 Все брони": "👥 すべての予約",
        "⬅️ Меню": "⬅️ メニュー",
        "Показать ещё ➡️": "さらに表示 ➡️",
        "➕ Запросить деф": "➕ 防衛を要請",
        "⚙️ Мои настройки": "⚙️ 自分の設定",
        "🏘 Мои деревни": "🏘 自分の村",
        "🆔 Узнать мой Telegram ID": "🆔 Telegram IDを表示",
        "➕ Добавить деревню": "➕ 村を追加",
        "✏️ Изменить деревню": "✏️ 村を編集",
        "🗑 Удалить деревню": "🗑 村を削除",
        "👥 Заместители": "👥 シッター",
        "🔔 Личные уведомления": "🔔 個人通知",
        "⬅️ Назад": "⬅️ 戻る",
        "📊 Оборона альянса": "📊 同盟防衛",
        "📥 Отчёт об атаке": "📥 攻撃報告",
        "🔎 Добавить скаут-проверку": "🔎 偵察チェックを追加",
        "🔭 План скаут-проверок": "🔭 偵察チェック計画",
        "📚 История скаутов": "📚 偵察履歴",
        "🏟 Офферы и Арены": "🏟 攻撃プレイヤーと闘技場",
        "⚙️ Настройки разведки": "⚙️ 偵察設定",
    },
}

LANGUAGE_TEXT = {
    "ru": "🌐 <b>Язык</b>\n\nВыберите язык интерфейса:",
    "en": "🌐 <b>Language</b>\n\nChoose the interface language:",
    "ja": "🌐 <b>言語</b>\n\nインターフェースの言語を選択してください:",
}

SAVED_TEXT = {
    "ru": "✅ Язык изменён на русский.",
    "en": "✅ Language changed to English.",
    "ja": "✅ 言語を日本語に変更しました。",
}


def _load():
    try:
        data = json.loads(PREFERENCES_FILE.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def get_language(user_id):
    row = _load().get(str(user_id), {})
    lang = row.get("language", "ru") if isinstance(row, dict) else "ru"
    return lang if lang in LANGUAGES else "ru"


def set_language(user_id, language):
    if language not in LANGUAGES:
        return False
    data = _load()
    row = data.setdefault(str(user_id), {})
    if not isinstance(row, dict):
        row = {}
        data[str(user_id)] = row
    row["language"] = language
    PREFERENCES_FILE.parent.mkdir(parents=True, exist_ok=True)
    PREFERENCES_FILE.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    _persist()
    return True


def _persist():
    try:
        subprocess.run(["git", "config", "user.name", "travian-bots"], check=False, capture_output=True)
        subprocess.run(["git", "config", "user.email", "travian-bots@users.noreply.github.com"], check=False, capture_output=True)
        subprocess.run(["git", "add", str(PREFERENCES_FILE)], check=False, capture_output=True)
        status = subprocess.run(["git", "status", "--porcelain", str(PREFERENCES_FILE)], text=True, capture_output=True)
        if not status.stdout.strip():
            return
        subprocess.run(["git", "commit", "-m", "Update bot language preference"], check=False, capture_output=True)
        subprocess.run(["git", "pull", "--rebase", "origin", "main"], check=False, capture_output=True)
        subprocess.run(["git", "push", "origin", "HEAD:main"], check=False, capture_output=True)
    except Exception as exc:
        print("Language preference persistence error:", repr(exc), flush=True)


def language_keyboard(prefix="lang"):
    return {"inline_keyboard": [
        [{"text": "🇷🇺 Русский", "callback_data": f"{prefix}:ru"}],
        [{"text": "🇬🇧 English", "callback_data": f"{prefix}:en"}],
        [{"text": "🇯🇵 日本語", "callback_data": f"{prefix}:ja"}],
    ]}


def language_text(user_id):
    return LANGUAGE_TEXT[get_language(user_id)]


def saved_text(language):
    return SAVED_TEXT.get(language, SAVED_TEXT["ru"])


def tr_button(text, user_id):
    lang = get_language(user_id)
    return TRANSLATIONS.get(lang, {}).get(text, text)


def localize_keyboard(markup, user_id):
    if not markup or not isinstance(markup, dict):
        return markup
    result = {"inline_keyboard": []}
    for row in markup.get("inline_keyboard", []):
        new_row = []
        for button in row:
            b = dict(button)
            if "text" in b:
                b["text"] = tr_button(b["text"], user_id)
            new_row.append(b)
        result["inline_keyboard"].append(new_row)
    return result


CROP_TEXT_REPLACEMENTS = {
    "en": {
        "🌾 Бот кропок": "🌾 Crop Fields Bot",
        "Поиск свободных 9c/15c, бонусов оазисов и бронирование.": "Find free 9c/15c fields, oasis bonuses and manage reservations.",
        "Введите координаты через пробел, например:": "Enter coordinates separated by a space, for example:",
        "Введите координаты вашей деревни через пробел.": "Enter your village coordinates separated by a space.",
        "Введите координаты кропки, доступность которой хотите проверить.": "Enter the crop field coordinates you want to check.",
        "Бронируйте кропку только тогда, когда до готовности очков культуры и поселенцев осталось не более 2 часов.": "Reserve a crop field only when your culture points and settlers will be ready within 2 hours.",
        "Введите координаты кропки для бронирования через пробел.": "Enter the crop field coordinates to reserve, separated by a space.",
        "Какую кропку ищем?": "Which crop field are you looking for?",
        "Минимальный бонус зерна от трёх лучших оазисов:": "Minimum crop bonus from the three best oases:",
        "Подходящих свободных кропок не найдено.": "No suitable free crop fields found.",
        "🌾 Найденные кропки": "🌾 Crop fields found",
        "бронь": "reserved",
        "этой кропки нет в базе.": "this crop field is not in the database.",
        "кропка уже занята на последнем снимке карты.": "the crop field is already occupied in the latest map snapshot.",
        "кропка уже забронирована.": "the crop field is already reserved.",
        "кропка свободна и доступна для бронирования.": "the crop field is free and available for reservation.",
        "Тип:": "Type:",
        "бонус:": "bonus:",
        "Этой кропки нет в базе.": "This crop field is not in the database.",
        "Эта кропка уже занята на последнем снимке карты.": "This crop field is already occupied in the latest map snapshot.",
        "Эта кропка уже забронирована другим игроком.": "This crop field is already reserved by another player.",
        "Кропка": "Crop field",
        "забронирована за вами.": "has been reserved for you.",
        "У вас нет забронированных кропок.": "You have no reserved crop fields.",
        "Ваши брони:": "Your reservations:",
        "Отменить": "Cancel",
        "Сейчас нет забронированных кропок.": "There are currently no reserved crop fields.",
        "Все брони:": "All reservations:",
        "Некорректная бронь.": "Invalid reservation.",
        "Эта бронь уже отсутствует.": "This reservation no longer exists.",
        "Бронь": "Reservation",
        "отменена.": "cancelled.",
        "Например:": "Example:",
    },
    "ja": {
        "🌾 Бот кропок": "🌾 クロップ村ボット",
        "Поиск свободных 9c/15c, бонусов оазисов и бронирование.": "空いている9c/15c、オアシスボーナスを検索し、予約を管理します。",
        "Введите координаты через пробел, например:": "座標をスペース区切りで入力してください。例:",
        "Введите координаты вашей деревни через пробел.": "自分の村の座標をスペース区切りで入力してください。",
        "Введите координаты кропки, доступность которой хотите проверить.": "空き状況を確認したいクロップ村の座標を入力してください。",
        "Бронируйте кропку только тогда, когда до готовности очков культуры и поселенцев осталось не более 2 часов.": "カルチャーポイントと開拓者の準備完了まで2時間以内の場合のみ予約してください。",
        "Введите координаты кропки для бронирования через пробел.": "予約するクロップ村の座標をスペース区切りで入力してください。",
        "Какую кропку ищем?": "どのクロップ村を探しますか？",
        "Минимальный бонус зерна от трёх лучших оазисов:": "上位3つのオアシスによる最低穀物ボーナス:",
        "Подходящих свободных кропок не найдено.": "条件に合う空きクロップ村が見つかりません。",
        "🌾 Найденные кропки": "🌾 見つかったクロップ村",
        "бронь": "予約済み",
        "этой кропки нет в базе.": "このクロップ村はデータベースにありません。",
        "кропка уже занята на последнем снимке карты.": "最新のマップでは既に占領されています。",
        "кропка уже забронирована.": "既に予約されています。",
        "кропка свободна и доступна для бронирования.": "空いており予約可能です。",
        "Тип:": "タイプ:",
        "бонус:": "ボーナス:",
        "Этой кропки нет в базе.": "このクロップ村はデータベースにありません。",
        "Эта кропка уже занята на последнем снимке карты.": "最新のマップでは既に占領されています。",
        "Эта кропка уже забронирована другим игроком.": "このクロップ村は他のプレイヤーが予約済みです。",
        "Кропка": "クロップ村",
        "забронирована за вами.": "を予約しました。",
        "У вас нет забронированных кропок.": "予約中のクロップ村はありません。",
        "Ваши брони:": "自分の予約:",
        "Отменить": "キャンセル",
        "Сейчас нет забронированных кропок.": "現在予約されているクロップ村はありません。",
        "Все брони:": "すべての予約:",
        "Некорректная бронь.": "無効な予約です。",
        "Эта бронь уже отсутствует.": "この予約は既に存在しません。",
        "Бронь": "予約",
        "отменена.": "をキャンセルしました。",
        "Например:": "例:",
    },
}


def tr_crop_text(text, user_id):
    lang = get_language(user_id)
    if lang == "ru":
        return text
    result = str(text)
    for source, target in CROP_TEXT_REPLACEMENTS.get(lang, {}).items():
        result = result.replace(source, target)
    return result
