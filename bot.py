"""
Freelance Parser Bot for VK
Парсер заказов и упоминаний с фриланс-бирж, Telegram, VK-групп, RSS-лент
"""

import vk_api
from vk_api.longpoll import VkLongPoll, VkEventType
from vk_api.keyboard import VkKeyboard, VkKeyboardColor
import threading
import time
import logging
import json
import os
from datetime import datetime

from parsers.freelance_ru import parse_freelance_ru
from parsers.kwork import parse_kwork
from parsers.fl_ru import parse_fl_ru
from parsers.hh_ru import parse_hh_ru
from parsers.upwork import parse_upwork
from parsers.rss_parser import parse_rss_sources
from parsers.telegram_parser import parse_telegram_channels
from parsers.vk_parser import parse_vk_groups
from data.categories import CATEGORIES_RU, CATEGORIES_EN
from data.sources import RSS_SOURCES, TELEGRAM_CHANNELS, VK_GROUPS

# ─── Logging ────────────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.FileHandler("logs/bot.log", encoding="utf-8"),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

# ─── Config ─────────────────────────────────────────────────────────────────
with open("config.json", encoding="utf-8") as f:
    CONFIG = json.load(f)

VK_TOKEN = CONFIG["vk_token"]
ADMIN_IDS = CONFIG.get("admin_ids", [])
PARSE_INTERVAL = CONFIG.get("parse_interval_minutes", 30)

# ─── State storage (in-memory, persisted to JSON) ────────────────────────────
USERS_FILE = "data/users.json"
SEEN_FILE = "data/seen_ids.json"


def load_json(path, default):
    if os.path.exists(path):
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    return default


def save_json(path, data):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


# user_id -> {lang: "ru"|"en", categories: [...], active: bool}
users = load_json(USERS_FILE, {})
# set of already-sent item IDs to avoid duplicates
seen_ids = set(load_json(SEEN_FILE, []))


def save_users():
    save_json(USERS_FILE, users)


def save_seen():
    save_json(SEEN_FILE, list(seen_ids))


# ─── VK API setup ────────────────────────────────────────────────────────────
vk_session = vk_api.VkApi(token=VK_TOKEN)
vk = vk_session.get_api()
longpoll = VkLongPoll(vk_session)


def send_message(user_id, text, keyboard=None):
    """Send message to user with optional keyboard."""
    params = {
        "user_id": user_id,
        "message": text,
        "random_id": int(time.time() * 1000),
    }
    if keyboard:
        params["keyboard"] = keyboard.get_keyboard()
    try:
        vk.messages.send(**params)
    except Exception as e:
        logger.error(f"send_message error to {user_id}: {e}")


# ─── Keyboards ───────────────────────────────────────────────────────────────

def kb_main_menu():
    kb = VkKeyboard(one_time=False)
    kb.add_button("🇷🇺 Русские заказы", color=VkKeyboardColor.PRIMARY)
    kb.add_button("🇺🇸 English orders", color=VkKeyboardColor.PRIMARY)
    kb.add_line()
    kb.add_button("📋 Мои категории", color=VkKeyboardColor.SECONDARY)
    kb.add_button("🔔 Подписка вкл/выкл", color=VkKeyboardColor.SECONDARY)
    kb.add_line()
    kb.add_button("🔄 Обновить сейчас", color=VkKeyboardColor.POSITIVE)
    kb.add_button("ℹ️ Помощь", color=VkKeyboardColor.SECONDARY)
    return kb


def kb_categories_ru(selected: list):
    kb = VkKeyboard(one_time=False)
    cats = list(CATEGORIES_RU.items())
    # 2 per row
    for i, (key, label) in enumerate(cats):
        mark = "✅ " if key in selected else ""
        color = VkKeyboardColor.POSITIVE if key in selected else VkKeyboardColor.SECONDARY
        kb.add_button(f"{mark}{label}", color=color)
        if (i + 1) % 2 == 0 and i + 1 < len(cats):
            kb.add_line()
    kb.add_line()
    kb.add_button("✅ Выбрать все", color=VkKeyboardColor.PRIMARY)
    kb.add_button("❌ Снять все", color=VkKeyboardColor.NEGATIVE)
    kb.add_line()
    kb.add_button("◀️ Назад", color=VkKeyboardColor.SECONDARY)
    return kb


def kb_categories_en(selected: list):
    kb = VkKeyboard(one_time=False)
    cats = list(CATEGORIES_EN.items())
    for i, (key, label) in enumerate(cats):
        mark = "✅ " if key in selected else ""
        color = VkKeyboardColor.POSITIVE if key in selected else VkKeyboardColor.SECONDARY
        kb.add_button(f"{mark}{label}", color=color)
        if (i + 1) % 2 == 0 and i + 1 < len(cats):
            kb.add_line()
    kb.add_line()
    kb.add_button("✅ Select all", color=VkKeyboardColor.PRIMARY)
    kb.add_button("❌ Clear all", color=VkKeyboardColor.NEGATIVE)
    kb.add_line()
    kb.add_button("◀️ Back", color=VkKeyboardColor.SECONDARY)
    return kb


# ─── Helpers ─────────────────────────────────────────────────────────────────

def get_user(user_id: str) -> dict:
    uid = str(user_id)
    if uid not in users:
        users[uid] = {
            "lang": "ru",
            "categories": [],
            "active": True,
            "menu": "main"
        }
        save_users()
    return users[uid]


def format_item(item: dict) -> str:
    """Format a parsed order/mention for display."""
    lines = []
    if item.get("source"):
        lines.append(f"📌 {item['source']}")
    if item.get("title"):
        lines.append(f"📝 {item['title']}")
    if item.get("description"):
        desc = item["description"][:300]
        if len(item["description"]) > 300:
            desc += "..."
        lines.append(f"💬 {desc}")
    if item.get("budget"):
        lines.append(f"💰 {item['budget']}")
    if item.get("category"):
        lines.append(f"🏷 {item['category']}")
    if item.get("url"):
        lines.append(f"🔗 {item['url']}")
    if item.get("published"):
        lines.append(f"🕐 {item['published']}")
    return "\n".join(lines)


# ─── Parsing dispatcher ──────────────────────────────────────────────────────

def run_all_parsers(categories: list, lang: str = "ru") -> list:
    """Run all parsers and return merged list of items filtered by categories."""
    items = []
    try:
        if lang == "ru":
            items += parse_fl_ru(categories)
            items += parse_kwork(categories)
            items += parse_freelance_ru(categories)
            items += parse_hh_ru(categories)
            items += parse_rss_sources(RSS_SOURCES["ru"], categories)
            items += parse_vk_groups(VK_GROUPS, categories)
            items += parse_telegram_channels(TELEGRAM_CHANNELS["ru"], categories)
        else:
            items += parse_upwork(categories)
            items += parse_rss_sources(RSS_SOURCES["en"], categories)
            items += parse_telegram_channels(TELEGRAM_CHANNELS["en"], categories)
    except Exception as e:
        logger.error(f"Parser error: {e}")

    # Deduplicate by unique_id
    new_items = []
    for item in items:
        uid = item.get("unique_id", "")
        if uid and uid not in seen_ids:
            seen_ids.add(uid)
            new_items.append(item)

    if new_items:
        save_seen()
    return new_items


# ─── Background worker ───────────────────────────────────────────────────────

def background_parser():
    """Periodically parse all sources and push results to subscribed users."""
    logger.info("Background parser started")
    while True:
        time.sleep(PARSE_INTERVAL * 60)
        logger.info("Starting scheduled parse cycle")
        for uid, udata in list(users.items()):
            if not udata.get("active", True):
                continue
            cats = udata.get("categories", [])
            if not cats:
                continue
            lang = udata.get("lang", "ru")
            try:
                items = run_all_parsers(cats, lang)
                if items:
                    header = "🔔 Новые заказы:" if lang == "ru" else "🔔 New orders:"
                    send_message(int(uid), header)
                    for item in items[:20]:  # max 20 per cycle
                        send_message(int(uid), format_item(item))
                        time.sleep(0.5)
            except Exception as e:
                logger.error(f"Error sending to {uid}: {e}")


# ─── Command handlers ─────────────────────────────────────────────────────────

def handle_start(user_id):
    u = get_user(user_id)
    u["menu"] = "main"
    save_users()
    send_message(
        user_id,
        "👋 Привет! Я бот-парсер заказов с фриланс-бирж, Telegram-каналов, VK-групп и RSS.\n\n"
        "Выбери раздел и категории — и я буду присылать тебе свежие заявки автоматически!\n\n"
        "🇷🇺 Русские источники: fl.ru, kwork, freelance.ru, hh.ru, VK-группы, Telegram, RSS\n"
        "🇺🇸 English sources: Upwork, Telegram EN, RSS EN",
        kb_main_menu()
    )


def handle_ru_categories(user_id):
    u = get_user(user_id)
    u["menu"] = "cats_ru"
    u["lang"] = "ru"
    save_users()
    send_message(
        user_id,
        "🇷🇺 Выбери категории для поиска заказов (нажимай — отмечается ✅):",
        kb_categories_ru(u.get("categories", []))
    )


def handle_en_categories(user_id):
    u = get_user(user_id)
    u["menu"] = "cats_en"
    u["lang"] = "en"
    save_users()
    send_message(
        user_id,
        "🇺🇸 Select categories for order search (tap to toggle ✅):",
        kb_categories_en(u.get("categories", []))
    )


def handle_toggle_category(user_id, text):
    u = get_user(user_id)
    cats = u.get("categories", [])
    lang = u.get("lang", "ru")
    cat_map = CATEGORIES_RU if lang == "ru" else CATEGORIES_EN

    # Find category key by label (strip checkmark prefix)
    clean_text = text.replace("✅ ", "").strip()
    matched_key = None
    for key, label in cat_map.items():
        if label == clean_text:
            matched_key = key
            break

    if matched_key:
        if matched_key in cats:
            cats.remove(matched_key)
        else:
            cats.append(matched_key)
        u["categories"] = cats
        save_users()
        kb = kb_categories_ru(cats) if lang == "ru" else kb_categories_en(cats)
        chosen = [cat_map[k] for k in cats if k in cat_map]
        msg = f"✅ Выбрано ({len(chosen)}): {', '.join(chosen) if chosen else 'ничего'}"
        if lang == "en":
            msg = f"✅ Selected ({len(chosen)}): {', '.join(chosen) if chosen else 'none'}"
        send_message(user_id, msg, kb)


def handle_select_all(user_id):
    u = get_user(user_id)
    lang = u.get("lang", "ru")
    cat_map = CATEGORIES_RU if lang == "ru" else CATEGORIES_EN
    u["categories"] = list(cat_map.keys())
    save_users()
    kb = kb_categories_ru(u["categories"]) if lang == "ru" else kb_categories_en(u["categories"])
    msg = "✅ Все категории выбраны!" if lang == "ru" else "✅ All categories selected!"
    send_message(user_id, msg, kb)


def handle_clear_all(user_id):
    u = get_user(user_id)
    lang = u.get("lang", "ru")
    u["categories"] = []
    save_users()
    kb = kb_categories_ru([]) if lang == "ru" else kb_categories_en([])
    msg = "❌ Все категории сняты" if lang == "ru" else "❌ All categories cleared"
    send_message(user_id, msg, kb)


def handle_my_categories(user_id):
    u = get_user(user_id)
    cats = u.get("categories", [])
    lang = u.get("lang", "ru")
    cat_map = CATEGORIES_RU if lang == "ru" else CATEGORIES_EN
    labels = [cat_map.get(k, k) for k in cats]
    if labels:
        msg = "📋 Твои категории:\n• " + "\n• ".join(labels)
    else:
        msg = "📋 Категории не выбраны. Нажми 🇷🇺 или 🇺🇸 для выбора."
    send_message(user_id, msg, kb_main_menu())


def handle_toggle_subscription(user_id):
    u = get_user(user_id)
    u["active"] = not u.get("active", True)
    save_users()
    if u["active"]:
        send_message(user_id, "🔔 Автоуведомления включены!", kb_main_menu())
    else:
        send_message(user_id, "🔕 Автоуведомления отключены.", kb_main_menu())


def handle_fetch_now(user_id):
    u = get_user(user_id)
    cats = u.get("categories", [])
    lang = u.get("lang", "ru")
    if not cats:
        msg = "⚠️ Сначала выбери категории!" if lang == "ru" else "⚠️ Please select categories first!"
        send_message(user_id, msg, kb_main_menu())
        return

    msg = "🔄 Ищу заказы, подожди..." if lang == "ru" else "🔄 Fetching orders, please wait..."
    send_message(user_id, msg)

    def fetch_and_send():
        items = run_all_parsers(cats, lang)
        if items:
            header = f"🎯 Найдено {len(items)} заказов:" if lang == "ru" else f"🎯 Found {len(items)} orders:"
            send_message(user_id, header)
            for item in items[:15]:
                send_message(user_id, format_item(item))
                time.sleep(0.4)
        else:
            msg2 = "😔 Новых заказов пока нет. Попробуй позже." if lang == "ru" else "😔 No new orders found. Try later."
            send_message(user_id, msg2, kb_main_menu())

    threading.Thread(target=fetch_and_send, daemon=True).start()


def handle_help(user_id):
    send_message(
        user_id,
        "ℹ️ Как пользоваться ботом:\n\n"
        "1️⃣ Нажми 🇷🇺 или 🇺🇸 для выбора языка заказов\n"
        "2️⃣ Выбери интересующие категории (можно несколько)\n"
        "3️⃣ Нажми 🔄 Обновить сейчас — получишь свежие заказы\n"
        "4️⃣ Включи 🔔 Подписку — бот будет присылать заказы автоматически\n\n"
        f"🕐 Автообновление каждые {PARSE_INTERVAL} мин.\n\n"
        "📦 Источники RU: fl.ru, kwork.ru, freelance.ru, hh.ru, VK-группы, Telegram-каналы, RSS\n"
        "📦 Источники EN: Upwork, Telegram EN, RSS EN",
        kb_main_menu()
    )


# ─── Main message router ─────────────────────────────────────────────────────

def route_message(user_id, text: str):
    u = get_user(user_id)
    menu = u.get("menu", "main")
    lang = u.get("lang", "ru")

    # Universal commands
    if text in ["/start", "start", "начать", "старт"]:
        handle_start(user_id)
        return

    if "🇷🇺" in text or "русские" in text.lower():
        handle_ru_categories(user_id)
        return

    if "🇺🇸" in text or "english" in text.lower():
        handle_en_categories(user_id)
        return

    if "мои категории" in text.lower() or "my categories" in text.lower() or "📋" in text:
        handle_my_categories(user_id)
        return

    if "подписка" in text.lower() or "subscription" in text.lower() or "🔔" in text:
        handle_toggle_subscription(user_id)
        return

    if "обновить" in text.lower() or "update" in text.lower() or "fetch" in text.lower() or "🔄" in text:
        handle_fetch_now(user_id)
        return

    if "помощь" in text.lower() or "help" in text.lower() or "ℹ️" in text:
        handle_help(user_id)
        return

    if "◀️" in text or "назад" in text.lower() or "back" in text.lower():
        u["menu"] = "main"
        save_users()
        send_message(user_id, "Главное меню:", kb_main_menu())
        return

    if "выбрать все" in text.lower() or "select all" in text.lower() or "✅ выбр" in text.lower() or "✅ select" in text.lower():
        handle_select_all(user_id)
        return

    if "снять все" in text.lower() or "clear all" in text.lower() or "❌" in text:
        handle_clear_all(user_id)
        return

    # Category toggle
    if menu in ("cats_ru", "cats_en"):
        handle_toggle_category(user_id, text)
        return

    # Default
    send_message(user_id, "Используй кнопки меню 👇", kb_main_menu())


# ─── Entry point ─────────────────────────────────────────────────────────────

def main():
    logger.info("Bot starting...")
    os.makedirs("logs", exist_ok=True)
    os.makedirs("data", exist_ok=True)

    # Start background parser thread
    parser_thread = threading.Thread(target=background_parser, daemon=True)
    parser_thread.start()

    logger.info("Listening for messages...")
    for event in longpoll.listen():
        if event.type == VkEventType.MESSAGE_NEW and event.to_me:
            user_id = event.user_id
            text = (event.text or "").strip()
            logger.info(f"Message from {user_id}: {text!r}")
            try:
                route_message(user_id, text)
            except Exception as e:
                logger.error(f"Handler error: {e}")


if __name__ == "__main__":
    main()
