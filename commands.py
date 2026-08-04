# commands.py
import time
import threading
import random
import difflib
import requests
import io
import concurrent.futures
from telebot import types

import database as db
import pvp
import tasks
import trade
from config import LOG_GROUP_ID, FLEE_TIMEOUT, REGIONS, logger
from api_utils import (escape_md, fetch_random_pokemon_id_and_name_sync, official_shiny_artwork_url, 
                       get_species_catch_rate_sync, get_pokemon_stats_sync, get_pokemon_id_sync, 
                       get_pokemon_moveset_sync, get_pokemon_relearn_moves_sync, get_pokemon_evolution_sync,
                       REGION_DEX, LEGENDARY_NAMES, pokemon_name_to_id_cache)

TYPE_EMOJIS = {
    'Normal': '🔘', 'Fire': '🔥', 'Water': '💧', 'Electric': '⚡', 'Grass': '🌿', 
    'Ice': '🧊', 'Fighting': '🥊', 'Poison': '☣️', 'Ground': '⛰️', 'Flying': '🪽', 
    'Psychic': '🔮', 'Bug': '🐛', 'Rock': '🪨', 'Ghost': '👻', 'Dragon': '🐉', 
    'Dark': '🌑', 'Steel': '🔩', 'Fairy': '🧚‍♀️'
}

# ⚡ CACHE FOR EXPLORE SPEED ⚡
local_type_cache = {}

# ⚡ SMART RAM CACHE FOR INSTANT IMAGES ⚡
IMAGE_CACHE = {}

# ⚡ PERSISTENT THREAD POOL — reused across all calls, never re-created ⚡
_TYPE_EXECUTOR = concurrent.futures.ThreadPoolExecutor(max_workers=20)

# ================== /mypokemon SORT / DISPLAY / PAGESIZE ==================
SORT_OPTIONS = [
    (1, "order_caught", "Order caught"),
    (2, "dex_number", "Pokedex number"),
    (3, "level", "Level"),
    (4, "iv_points", "IV points"),
    (5, "ev_points", "EV points"),
    (6, "name", "Name"),
    (7, "nature", "Nature"),
    (8, "type", "Type"),
    (9, "catch_rate", "Catch rate"),
    (10, "stat_hp", "HP points"),
    (11, "stat_atk", "Attack points"),
    (12, "stat_def", "Defense points"),
    (13, "stat_spa", "Sp Attack points"),
    (14, "stat_spd", "Sp Defense points"),
    (15, "stat_spe", "Speed points"),
    (16, "stat_total", "Total stats points"),
]
DISPLAY_OPTIONS = [
    (1, "none", "None"),
    (2, "level", "Level"),
    (3, "iv_points", "IV points"),
    (4, "ev_points", "EV points"),
    (5, "nature", "Nature"),
    (6, "type", "Type"),
    (7, "type_symbol", "Type symbol"),
    (8, "catch_rate", "Catch rate"),
    (9, "stat_hp", "HP points"),
    (10, "stat_atk", "Attack points"),
    (11, "stat_def", "Defense points"),
    (12, "stat_spa", "Sp Attack points"),
    (13, "stat_spd", "Sp Defense points"),
    (14, "stat_spe", "Speed points"),
    (15, "stat_total", "Total stats points"),
]
PAGE_SIZES = [10, 15, 20, 25]

SORT_BY_NUM = {str(num): key for num, key, _ in SORT_OPTIONS}
SORT_LABELS = {key: label for _, key, label in SORT_OPTIONS}
DISPLAY_BY_NUM = {str(num): key for num, key, _ in DISPLAY_OPTIONS}
DISPLAY_LABELS = {key: label for _, key, label in DISPLAY_OPTIONS}

_STAT_SORT_KEYS = {
    "stat_hp": "hp", "stat_atk": "atk", "stat_def": "def",
    "stat_spa": "spa", "stat_spd": "spd", "stat_spe": "spe",
}
_STAT_ORDER = ["hp", "atk", "def", "spa", "spd", "spe"]
_REVERSE_STAT_MAP = {"hp": "Hp", "atk": "Attack", "def": "Defense", "spa": "Special attack", "spd": "Special defense", "spe": "Speed"}

_SPECIES_CACHE = {}
_EMPTY_SPECIES_INFO = {"dex": 0, "types": [], "catch_rate": 0, "stats": {}}

_NEEDS_SPECIES_SORT = {"dex_number", "type", "catch_rate"}
_NEEDS_SPECIES_DISPLAY = {"type", "type_symbol", "catch_rate"}


def get_species_info(name):
    lname = (name or "").lower()
    if lname in _SPECIES_CACHE:
        return _SPECIES_CACHE[lname]
    info = dict(_EMPTY_SPECIES_INFO)
    try:
        poke_id = get_pokemon_id_sync(lname)
        if poke_id:
            info["dex"] = poke_id
            types_list, stats = get_pokemon_stats_sync(lname)
            info["types"] = types_list or []
            info["stats"] = stats or {}
            info["catch_rate"] = get_species_catch_rate_sync(poke_id) or 0
    except Exception:
        pass
    _SPECIES_CACHE[lname] = info
    return info


def _stat_points(entry, info, short_key):
    base = info["stats"].get(_REVERSE_STAT_MAP.get(short_key, ""))
    if base is None:
        return 0
    return db.calc_level_100_stat(base, entry["ivs"].get(short_key, 0), short_key, entry["nature"])


def _stat_total(entry, info):
    return sum(_stat_points(entry, info, k) for k in _STAT_ORDER)


def _prewarm_species_cache(entries):
    unique_names = list({e["name"].lower() for e in entries if e.get("name")})
    if unique_names:
        list(_TYPE_EXECUTOR.map(get_species_info, unique_names))


def sort_pokemon_entries(entries, sort_by, sort_dir):
    if sort_by in _NEEDS_SPECIES_SORT or sort_by.startswith("stat_"):
        _prewarm_species_cache(entries)

    def key_fn(e):
        info = _SPECIES_CACHE.get(e["name"].lower(), _EMPTY_SPECIES_INFO)
        if sort_by == "dex_number": return info["dex"]
        if sort_by == "level": return 100
        if sort_by == "iv_points": return sum(e["ivs"].get(k, 0) for k in _STAT_ORDER)
        if sort_by == "ev_points": return 0
        if sort_by == "name": return e["name"].lower()
        if sort_by == "nature": return e["nature"].lower()
        if sort_by == "type": return info["types"][0].lower() if info["types"] else ""
        if sort_by == "catch_rate": return info["catch_rate"]
        if sort_by == "stat_total": return _stat_total(e, info)
        if sort_by in _STAT_SORT_KEYS: return _stat_points(e, info, _STAT_SORT_KEYS[sort_by])
        return e["id"]

    entries.sort(key=key_fn, reverse=(sort_dir == "desc"))
    return entries


def build_display_suffix(entry, info, display):
    if display == "none": return ""
    if display == "level": return "Lv 100"
    if display == "iv_points": return f"{sum(entry['ivs'].get(k, 0) for k in _STAT_ORDER)} IV"
    if display == "ev_points": return "0 EVs"
    if display == "nature": return f"{entry['nature']}"
    if display == "type":
        return f"{'/'.join(info['types'])}" if info["types"] else "Unknown"
    if display == "type_symbol":
        return f"{'/'.join(info['types'])}" if info["types"] else ""
    if display == "catch_rate": return f"CR {info['catch_rate']}"
    if display == "stat_total": return f"{_stat_total(entry, info)}"
    if display in _STAT_SORT_KEYS: return f"{_stat_points(entry, info, _STAT_SORT_KEYS[display])}"
    return ""


def build_sort_menu(uid):
    settings = db.get_list_settings(uid)
    sort_by, sort_dir = settings.get("sort_by", "order_caught"), settings.get("sort_dir", "asc")

    text = "How would you like to sort your pokemon?\n\n"
    text += "\n".join(f"{num}\\. {escape_md(label)}" for num, key, label in SORT_OPTIONS if num <= 9)
    text += "\n\nSort by pokemon stat points:\n" + escape_md("—" * 21) + "\n"
    text += "\n".join(f"{num}\\. {escape_md(label)}" for num, key, label in SORT_OPTIONS if num > 9)
    text += (f"\n\nCurrently sorting by: {escape_md(SORT_LABELS.get(sort_by, 'Order caught'))}\n"
             f"Direction: {escape_md('Descending' if sort_dir == 'desc' else 'Ascending')}")

    kb = types.InlineKeyboardMarkup(row_width=4)
    row = []
    for num, key, label in SORT_OPTIONS:
        row.append(types.InlineKeyboardButton(str(num), callback_data=f"srt_{uid}_{num}"))
        if len(row) == 4: kb.row(*row); row = []
    if row: kb.row(*row)
    kb.row(types.InlineKeyboardButton("Change Direction", callback_data=f"srtdir_{uid}"))
    return text, kb


def build_display_menu(uid):
    settings = db.get_list_settings(uid)
    display, show_numbering = settings.get("display", "none"), settings.get("show_numbering", True)

    text = "Which pokemon detail would you like to display?\n\n"
    text += "\n".join(f"{num}\\. {escape_md(label)}" for num, key, label in DISPLAY_OPTIONS if num <= 8)
    text += "\n\nDisplay pokemon stat points:\n" + escape_md("—" * 21) + "\n"
    text += "\n".join(f"{num}\\. {escape_md(label)}" for num, key, label in DISPLAY_OPTIONS if num > 8)
    text += (f"\n\nCurrently displaying: {escape_md(DISPLAY_LABELS.get(display, 'None'))}\n"
             f"Show pokemon numbering: {escape_md('Yes' if show_numbering else 'No')}")

    kb = types.InlineKeyboardMarkup(row_width=4)
    row = []
    for num, key, label in DISPLAY_OPTIONS:
        row.append(types.InlineKeyboardButton(str(num), callback_data=f"dsp_{uid}_{num}"))
        if len(row) == 4: kb.row(*row); row = []
    if row: kb.row(*row)
    kb.row(types.InlineKeyboardButton("Toggle Numbering", callback_data=f"dspnum_{uid}"))
    return text, kb


def build_pagesize_menu(uid):
    settings = db.get_list_settings(uid)
    page_size = settings.get("page_size", 20)
    text = f"How many pokemon would you like to see per page?\n\nCurrent page size: {page_size}"
    kb = types.InlineKeyboardMarkup(row_width=4)
    kb.row(*[types.InlineKeyboardButton(str(s), callback_data=f"pgsz_{uid}_{s}") for s in PAGE_SIZES])
    return text, kb

def get_cached_image_payload(poke_id, img_url):
    if poke_id in IMAGE_CACHE:
        return io.BytesIO(IMAGE_CACHE[poke_id])
    try:
        img_data = requests.get(img_url, timeout=1.5).content
        IMAGE_CACHE[poke_id] = img_data
        return io.BytesIO(img_data)
    except:
        return img_url

def clean_name(name):
    if not name: return "Trainer"
    return name.replace('\n', ' ').replace('\r', '').replace('*', '').replace('_', '').strip()

def to_small_caps(text):
    small_caps_map = {
        'a': 'ᴀ', 'b': 'ʙ', 'c': 'ᴄ', 'd': 'ᴅ', 'e': 'ᴇ', 'f': 'ғ', 'g': 'ɢ',
        'h': 'ʜ', 'i': 'ɪ', 'j': 'ᴊ', 'k': 'ᴋ', 'l': 'ʟ', 'm': 'ᴍ', 'n': 'ɴ',
        'o': 'ᴏ', 'p': 'ᴘ', 'q': 'ǫ', 'r': 'ʀ', 's': 's', 't': 'ᴛ', 'u': 'ᴜ',
        'v': 'ᴠ', 'w': 'ᴡ', 'x': 'x', 'y': 'ʏ', 'z': 'ᴢ'
    }
    return "".join(char if char.isupper() else small_caps_map.get(char.lower(), char) for char in text)

def safe_send(bot, chat_id, text, reply_to_id=None, reply_markup=None):
    try: return bot.send_message(chat_id, text, reply_to_message_id=reply_to_id, reply_markup=reply_markup, parse_mode="MarkdownV2")
    except Exception as e:
        if "429" in str(e) or "Too Many Requests" in str(e):
            time.sleep(2.5) 
            try: return bot.send_message(chat_id, text, reply_to_message_id=reply_to_id, reply_markup=reply_markup, parse_mode="MarkdownV2")
            except: pass
        return None

# ================== DID YOU MEAN ENGINE ==================
def generate_did_you_mean(wrong_name, valid_list, action_prefix, uid):
    wrong_lower = (wrong_name or "").lower().strip()
    valid_lower_map = {n.lower(): n for n in valid_list if n}

    matched_names = []
    # 1. Prefix and Substring match first
    for l_name, orig_name in valid_lower_map.items():
        if l_name.startswith(wrong_lower) or wrong_lower in l_name:
            if orig_name not in matched_names:
                matched_names.append(orig_name)

    # 2. Difflib close matches for typos
    close_keys = difflib.get_close_matches(wrong_lower, valid_lower_map.keys(), n=6, cutoff=0.4)
    for k in close_keys:
        orig = valid_lower_map[k]
        if orig not in matched_names:
            matched_names.append(orig)

    wrong_name_smallcaps = to_small_caps(wrong_name.title())
    
    if not matched_names:
        if action_prefix == "dym_dex": return f"❌ *Nᴏ Pᴏᴋᴇ́ᴍᴏɴ Nᴀᴍᴇᴅ \"{escape_md(wrong_name_smallcaps)}\" Fᴏᴜɴᴅ\\.*", None
        else: return f"❌ *Yᴏᴜ ᴅᴏɴ'ᴛ ᴏᴡɴ ᴀ \"{escape_md(wrong_name_smallcaps)}\"\\.*", None

    matched_names = matched_names[:6]

    if action_prefix == "dym_dex": text = f"❌ *Nᴏ Pᴏᴋᴇ́ᴍᴏɴ Nᴀᴍᴇᴅ \"{escape_md(wrong_name_smallcaps)}\" Fᴏᴜɴᴅ\\.*\n\n💡 *Dɪᴅ Yᴏᴜ Mᴇᴀɴ:*\n"
    else: text = f"❌ *Yᴏᴜ ᴅᴏɴ'ᴛ ᴏᴡɴ ᴀ \"{escape_md(wrong_name_smallcaps)}\"\\.*\n\n💡 *Dɪᴅ Yᴏᴜ Mᴇᴀɴ:*\n"
    
    kb = types.InlineKeyboardMarkup(row_width=2)
    btns = []
    for actual_name in matched_names:
        display_name = to_small_caps(actual_name.title())
        text += f"• {escape_md(display_name)}\n"
        btns.append(types.InlineKeyboardButton(actual_name.title(), callback_data=f"{action_prefix}_{uid}_{actual_name[:20]}"))
    
    for i in range(0, len(btns), 2):
        if i + 1 < len(btns): kb.add(btns[i], btns[i+1])
        else: kb.add(btns[i])
    return text, kb


# ================== /mypokemon UI GENERATOR ==================
def generate_pokemon_list_ui(uid, page_idx, action_prefix="mypoke", is_admin=False):
    entries = db.list_user_pokemon_full(uid)
    if not entries: return escape_md("No Pokemon found."), None

    settings = db.get_list_settings(uid)
    sort_by = settings.get("sort_by", "order_caught")
    sort_dir = settings.get("sort_dir", "asc")
    display = settings.get("display", "none")
    show_numbering = settings.get("show_numbering", True)
    page_size = settings.get("page_size", 20)

    if display in _NEEDS_SPECIES_DISPLAY or display.startswith("stat_"):
        _prewarm_species_cache(entries)
    entries = sort_pokemon_entries(entries, sort_by, sort_dir)

    total_poke = len(entries)
    pages = [entries[i:i + page_size] for i in range(0, len(entries), page_size)] or [[]]

    if page_idx < 0: page_idx = 0
    if page_idx >= len(pages): page_idx = len(pages) - 1

    text = f"Pokemon \\(UID: {uid}\\)\n\n" if is_admin else ""

    page_entries = pages[page_idx]
    for i, entry in enumerate(page_entries):
        info = _SPECIES_CACHE.get(entry["name"].lower(), _EMPTY_SPECIES_INFO)
        detail = build_display_suffix(entry, info, display)
        
        name_str = f"*{escape_md(entry['name'])}*"
        if detail:
            line_content = f"{name_str} \\- {escape_md(detail)}"
        else:
            line_content = name_str

        if show_numbering:
            item_num = (page_idx * page_size) + i + 1
            text += f"{item_num}\\. {line_content}\n"
        else:
            text += f"{line_content}\n"

    sort_arrow = "↓" if sort_dir == "desc" else "↑"
    text += (f"\nTotal Pokemon: {total_poke}\n"
             f"/sort by: {escape_md(SORT_LABELS.get(sort_by, 'Order caught'))} {sort_arrow}\n"
             f"/display: {escape_md(DISPLAY_LABELS.get(display, 'None'))}\n"
             f"/pagesize: {page_size}\n━━━━━━━━━━━━━━━━")

    kb = None
    if len(pages) > 1:
        p_prev1, p_next1 = max(0, page_idx - 1), min(len(pages) - 1, page_idx + 1)
        p_prev5, p_next5 = max(0, page_idx - 5), min(len(pages) - 1, page_idx + 5)
        p_prev10, p_next10 = max(0, page_idx - 10), min(len(pages) - 1, page_idx + 10)
        kb = types.InlineKeyboardMarkup(row_width=3)
        kb.row(
            types.InlineKeyboardButton("«", callback_data=f"{action_prefix}_{uid}_{p_prev1}"),
            types.InlineKeyboardButton(f"« {page_idx + 1}/{len(pages)} »", callback_data="ignore"),
            types.InlineKeyboardButton("»", callback_data=f"{action_prefix}_{uid}_{p_next1}")
        )
        kb.row(
            types.InlineKeyboardButton("« 5x", callback_data=f"{action_prefix}_{uid}_{p_prev5}"),
            types.InlineKeyboardButton("5x »", callback_data=f"{action_prefix}_{uid}_{p_next5}")
        )
        kb.row(
            types.InlineKeyboardButton("« 10x", callback_data=f"{action_prefix}_{uid}_{p_prev10}"),
            types.InlineKeyboardButton("10x »", callback_data=f"{action_prefix}_{uid}_{p_next10}")
        )
    return text, kb


# ================== MULTI-COPY INSPECT SELECTION UI ==================
def generate_inspect_multi_ui(uid, name, page_idx=0):
    entries = db.get_user_pokemon_by_name(uid, name)
    if not entries:
        return None, None

    settings = db.get_list_settings(uid)
    sort_by = settings.get("sort_by", "order_caught")
    sort_dir = settings.get("sort_dir", "asc")
    display = settings.get("display", "none")
    show_numbering = settings.get("show_numbering", True)
    page_size = settings.get("page_size", 20)

    if display in _NEEDS_SPECIES_DISPLAY or display.startswith("stat_"):
        _prewarm_species_cache(entries)
    entries = sort_pokemon_entries(entries, sort_by, sort_dir)

    pages = [entries[i:i + page_size] for i in range(0, len(entries), page_size)] or [[]]

    if page_idx < 0: page_idx = 0
    if page_idx >= len(pages): page_idx = len(pages) - 1

    disp_name = entries[0]["name"].capitalize() if entries else name.capitalize()
    text = f"✨ *Select a {escape_md(disp_name)} to Inspect*\n\n"

    page_entries = pages[page_idx]
    for i, entry in enumerate(page_entries):
        info = _SPECIES_CACHE.get(entry["name"].lower(), _EMPTY_SPECIES_INFO)
        detail = build_display_suffix(entry, info, display)
        if display == "none":
            detail = entry["nature"]

        name_str = f"*{escape_md(entry['name'])}*"
        if detail:
            line_content = f"{name_str} \\- {escape_md(detail)}"
        else:
            line_content = name_str

        if show_numbering:
            item_num = (page_idx * page_size) + i + 1
            text += f"{item_num}\\. {line_content}\n"
        else:
            text += f"{line_content}\n"

    text += "\nCheck stats of which pokemon?"

    kb = types.InlineKeyboardMarkup(row_width=5)
    
    num_btns = []
    for i, entry in enumerate(page_entries):
        item_num = (page_idx * page_size) + i + 1
        num_btns.append(types.InlineKeyboardButton(str(item_num), callback_data=f"inspsel_{uid}_{entry['id']}"))
    
    for i in range(0, len(num_btns), 5):
        kb.row(*num_btns[i:i+5])

    if len(pages) > 1:
        p_prev1, p_next1 = max(0, page_idx - 1), min(len(pages) - 1, page_idx + 1)
        kb.row(
            types.InlineKeyboardButton("«", callback_data=f"insplst_{uid}_{name[:16]}_{p_prev1}"),
            types.InlineKeyboardButton(f"« {page_idx + 1}/{len(pages)} »", callback_data="ignore"),
            types.InlineKeyboardButton("»", callback_data=f"insplst_{uid}_{name[:16]}_{p_next1}")
        )

    return text, kb


# ================== GAME LOGIC ==================
def auto_flee(bot, message_id, chat_id, pokemon_name, active_hunts):
    active_hunts.pop(message_id, None)

def start_scout(bot, chat_id, user_id, active_hunts, reply_to_id=None):
    if not db.get_user(user_id): return safe_send(bot, chat_id, escape_md("⚠️ Please /start the bot first."), reply_to_id)
    if pvp.is_in_battle(user_id): return safe_send(bot, chat_id, escape_md("⚔️ You cannot scout while engaged in a PvP battle!"), reply_to_id)
        
    tries_left, region = db.update_user_tries(user_id)
    if tries_left is None: return safe_send(bot, chat_id, escape_md("⚠️ Error checking your profile."), reply_to_id)
    if tries_left <= 0: return safe_send(bot, chat_id, escape_md("💤 You have no scouts left today. Rest and come back tomorrow!"), reply_to_id)
        
    to_cancel = [msg_id for msg_id, hunt in active_hunts.items() if hunt["user_id"] == user_id]
    for msg_id in to_cancel:
        hunt = active_hunts.pop(msg_id, None)
        if hunt:
            hunt["timer"].cancel()

    poke_id, name, base_id = fetch_random_pokemon_id_and_name_sync(region)
    if not poke_id: return safe_send(bot, chat_id, escape_md("❌ Failed to find a Pokémon. Try again."), reply_to_id)

    img_url = official_shiny_artwork_url(base_id)
    caption = f"A wild ✨ {escape_md(name.title())} has appeared\\!"
    kb = types.InlineKeyboardMarkup().add(
        types.InlineKeyboardButton("Catch", callback_data=f"catch_{user_id}_{poke_id}_{name[:16]}")
    )

    photo_payload = get_cached_image_payload(base_id, img_url)

    try:
        sent = bot.send_photo(chat_id, photo_payload, caption=caption, reply_to_message_id=reply_to_id, reply_markup=kb, parse_mode="MarkdownV2")
        timer = threading.Timer(FLEE_TIMEOUT, auto_flee, args=(bot, sent.message_id, chat_id, name, active_hunts))
        timer.start()
        active_hunts[sent.message_id] = {"user_id": user_id, "chat_id": chat_id, "start_time": time.time(), "timer": timer, "name": name}
    except Exception as e: 
        if "429" in str(e):
            time.sleep(2) 
            try:
                if isinstance(photo_payload, io.BytesIO): photo_payload.seek(0)
                sent = bot.send_photo(chat_id, photo_payload, caption=caption, reply_to_message_id=reply_to_id, reply_markup=kb, parse_mode="MarkdownV2")
                timer = threading.Timer(FLEE_TIMEOUT, auto_flee, args=(bot, sent.message_id, chat_id, name, active_hunts))
                timer.start()
                active_hunts[sent.message_id] = {"user_id": user_id, "chat_id": chat_id, "start_time": time.time(), "timer": timer, "name": name}
            except: pass

def process_catch(bot, call, uid, pid, name):
    chat_id = call.message.chat.id
    msg_id = call.message.message_id
    try:
        try: bot.edit_message_caption(caption="🔴 *You threw a Poké Ball\\!*", chat_id=chat_id, message_id=msg_id, parse_mode="MarkdownV2")
        except: pass

        catch_rate = get_species_catch_rate_sync(pid)
        if random.random() < max(0.05, min(0.95, catch_rate / 255.0)):
            poke_name_capped = name.title()
            caught_record = db.add_caught_pokemon(uid, poke_name_capped, db.get_user(uid)[2])
            iv_pct = caught_record["iv_percent"] if caught_record else 0.0
            iv_pct_str = escape_md(str(iv_pct))
            identifier = caught_record["id"] if caught_record else poke_name_capped
            try: tasks.check_and_update_catch(uid, poke_name_capped)
            except Exception: logger.exception(f"check_and_update_catch failed for uid={uid}")
            
            if LOG_GROUP_ID:
                try: 
                    c_name = clean_name(call.from_user.first_name)
                    log_msg = f"🟢 【Catch】 [{escape_md(c_name)}](tg://user?id={uid}) caught ✨ Shiny {escape_md(poke_name_capped)} \\(IV: {iv_pct_str}%\\)"
                    bot.send_message(LOG_GROUP_ID, log_msg, parse_mode="MarkdownV2")
                except Exception: logger.exception("LOG_GROUP_ID catch log failed")
            
            caught_caption = f"You caught a wild *{escape_md(poke_name_capped)}*\\."
            kb = types.InlineKeyboardMarkup().add(
                types.InlineKeyboardButton("View stats", callback_data=f"insp_i_{uid}_{identifier}"),
                types.InlineKeyboardButton("Release", callback_data=f"insprel_{uid}_{identifier}")
            )
            try: bot.edit_message_caption(caption=caught_caption, chat_id=chat_id, message_id=msg_id, reply_markup=kb, parse_mode="MarkdownV2")
            except Exception: logger.exception(f"edit_message_caption (catch success) failed for uid={uid}")
        else:
            try: bot.edit_message_caption(caption=f"💨 *Oh no\\!* The wild ✨ {escape_md(name.title())} broke free and fled\\!", chat_id=chat_id, message_id=msg_id, parse_mode="MarkdownV2")
            except Exception: logger.exception(f"edit_message_caption (flee) failed for uid={uid}")
    except Exception:
        logger.exception(f"❌ process_catch failed entirely for uid={uid} name={name}")

def get_dex_text(name, page="info"):
    poke_id = get_pokemon_id_sync(name)
    if not poke_id: return None
    types_list, stats = get_pokemon_stats_sync(name)
    if not stats: return None
    
    if page == "info":
        catch_rate = get_species_catch_rate_sync(poke_id)
        prob = "Very Low" if catch_rate <= 45 else ("Low" if catch_rate <= 90 else ("Medium" if catch_rate <= 150 else "High"))
        region_found = next((r for r, (min_id, max_id) in REGION_DEX.items() if min_id <= poke_id <= max_id), "Unknown")
        types_str = " / ".join([f"{t} {TYPE_EMOJIS.get(t, '')}" for t in types_list])
        return (f"📱 *Pokédex Data*\n━━━━━━━━━━━━━━\n🔢 *Pokédex No\\.:* {poke_id}\n📛 *Name:* {escape_md(name.capitalize())}\n"
                f"🧬 *Types:* \\[{escape_md(types_str)}\\]\n🎯 *Catch probability:* {prob}\n🌍 *Regions found:* {escape_md(region_found)}")
    else:
        stats_str = "\n".join([f"🔸 *{escape_md(k)}:* {v}" for k, v in stats.items()])
        return (f"📊 *Base Stats: {escape_md(name.capitalize())}*\n━━━━━━━━━━━━━━\n{stats_str}\n━━━━━━━━━━━━━━\n📈 *Total:* {sum(stats.values())}")

# ================== /inspect ENGINE ==================
INSPECT_PAGES = [("i", "Info"), ("s", "Stats"), ("v", "IV & EV"), ("e", "Evolve"), ("m", "Move Set")]
IV_ORDER = ["hp", "atk", "def", "spa", "spd", "spe"]
STAT_KEY_MAP = {"Hp": "hp", "Attack": "atk", "Defense": "def", "Special attack": "spa", "Special defense": "spd", "Speed": "spe"}
STAT_LABELS = {"hp": "HP", "atk": "Attack", "def": "Defense", "spa": "Sp. Attack", "spd": "Sp. Defense", "spe": "Speed"}
_ROW2_PAGES = {"e", "m"}

def build_inspect_keyboard(user_id, identifier, active_page):
    kb = types.InlineKeyboardMarkup(row_width=3)
    row1, row2 = [], []
    for code, label in INSPECT_PAGES:
        btn = types.InlineKeyboardButton(label, callback_data="ignore" if code == active_page else f"insp_{code}_{user_id}_{identifier}")
        (row2 if code in _ROW2_PAGES else row1).append(btn)
    kb.row(*row1)
    kb.row(*row2)
    kb.row(
        types.InlineKeyboardButton("Relearner", callback_data="ignore" if active_page == "r" else f"insp_r_{user_id}_{identifier}"),
        types.InlineKeyboardButton("Release", callback_data=f"insprel_{user_id}_{identifier}")
    )
    return kb

def build_inspect_page(user_id, identifier, page_code="i"):
    details = db.get_pokemon_details(user_id, identifier)
    if not details: return None, None
    
    name = details["name"]
    poke_id = get_pokemon_id_sync(name)
    if not poke_id: return None, None
    types_list, base_stats = get_pokemon_stats_sync(name)
    if not base_stats: return None, None

    if page_code == "r":
        return build_relearner_page(user_id, identifier, 0)

    ivs, nature = details["ivs"], details["nature"]

    actual = {}
    for label_key, short_key in STAT_KEY_MAP.items():
        base = base_stats.get(label_key, 0)
        actual[short_key] = db.calc_level_100_stat(base, ivs.get(short_key, 0), short_key, nature)

    header = f"✨ *{escape_md(name.capitalize())}* \\(Shiny\\)\n\n"
    evo_targets = []

    if page_code == "s":
        boost, lower = db.nature_effect(nature)
        lines = []
        for key in IV_ORDER:
            suffix = " \\(\\+\\)" if key == boost else (" \\(\\-\\)" if key == lower else "")
            lines.append(f"{escape_md(STAT_LABELS[key])}: {actual[key]}{suffix}")
        caption = header + "\n".join(lines)

    elif page_code == "e":
        evo = get_pokemon_evolution_sync(name)
        evo_targets = evo["into"] if evo else []
        if not evo:
            caption = header + escape_md("⚠️ Couldn't load evolution data right now — try again shortly.")
        else:
            lines = []
            if evo["from"]:
                lines.append(f"Evolves from: {escape_md(evo['from'])}")
            if evo["into"]:
                for nxt in evo["into"]:
                    lvl = f" \\(Lv\\. {nxt['min_level']}\\)" if nxt.get("min_level") else ""
                    lines.append(f"Evolves into: {escape_md(nxt['name'])}{lvl}")
            else:
                lines.append(escape_md("This Pokémon does not evolve."))
            caption = header + "\n".join(lines)

    elif page_code == "m":
        moves = db.get_pokemon_custom_moves(user_id, identifier) or get_pokemon_moveset_sync(name)
        if not moves:
            caption = header + escape_md("⚠️ Couldn't load move data right now — try again shortly.")
        else:
            blocks = []
            for m in moves:
                emoji = TYPE_EMOJIS.get(m["type"], "")
                m_name = escape_md(m['name'])
                m_type = escape_md(m['type'])
                m_cat = escape_md(m['category'].capitalize())
                m_pow = m['power']
                m_acc = m['acc']
                blocks.append(f"*{m_name}* \\[{m_type} {emoji}\\]\nPower: {m_pow}, Accuracy: {m_acc} \\({m_cat}\\)")
            caption = header + "\n".join(blocks)

    elif page_code == "v":
        total_iv = sum(ivs.get(k, 0) for k in IV_ORDER)
        rows = [(STAT_LABELS[k], ivs.get(k, 0)) for k in IV_ORDER]
        table = "Points         IV |  EV\n" + ("—" * 23) + "\n"
        for label, val in rows:
            table += f"{label:<14} {val:>2} |   0\n"
        table += ("—" * 23) + "\n"
        table += f"{'Total':<14} {total_iv:>2} |   0"
        caption = header + f"```\n{table}\n```"

    else:  # info
        types_str = " ".join([f"\\[{escape_md(t)} {TYPE_EMOJIS.get(t, '')}\\]" for t in types_list])
        caption = (header + f"Lv\\. 100 \\| Nature: {escape_md(nature)} ✨\n"
                   f"Types: {types_str}\n"
                   f"Exp\\. 1,000,000\nTo Next Lv\\. 0\nEXP ██████████")

    kb = build_inspect_keyboard(user_id, identifier, page_code)
    if page_code == "e" and evo_targets:
        stable_id = details["id"]
        evo_row = [
            types.InlineKeyboardButton(
                f"Evolve into {nxt['name']}" if len(evo_targets) > 1 else "Evolve",
                callback_data=f"evo_{user_id}_{stable_id}_{nxt['name'][:16]}"
            )
            for nxt in evo_targets
        ]
        kb.keyboard.insert(max(len(kb.keyboard) - 1, 0), evo_row)
    return caption, kb


# ================== MOVE RELEARNER ==================
RELEARN_PAGE_SIZE = 8

def build_relearner_page(user_id, identifier, list_page=0):
    details = db.get_pokemon_details(user_id, identifier)
    name = details["name"] if details else str(identifier)
    moves = get_pokemon_relearn_moves_sync(name)
    header = f"*{escape_md(name.capitalize())}* \\(Shiny\\)\n\nMove Relearner\n\n"

    if not moves:
        caption = header + escape_md("Couldn't load learnable moves right now — try again shortly.")
        kb = types.InlineKeyboardMarkup().add(types.InlineKeyboardButton("Back", callback_data=f"insp_i_{user_id}_{identifier}"))
        return caption, kb

    pages = [moves[i:i + RELEARN_PAGE_SIZE] for i in range(0, len(moves), RELEARN_PAGE_SIZE)]
    if list_page < 0: list_page = 0
    if list_page >= len(pages): list_page = len(pages) - 1
    page_moves = pages[list_page]

    blocks = []
    for i, m in enumerate(page_moves, start=1):
        emoji = TYPE_EMOJIS.get(m["type"], "")
        blocks.append(f"{i}\\. {escape_md(m['name'])} \\[{emoji}\\]  \\[{escape_md(m['category'])}\\]\nPower: {m['power']}        Accuracy: {m['acc']}")
    caption = header + "\n\n".join(blocks)
    if len(pages) > 1:
        caption += f"\n\nPage {list_page + 1} / {len(pages)}"

    kb = types.InlineKeyboardMarkup(row_width=3)
    num_buttons = [types.InlineKeyboardButton(str(i + 1), callback_data=f"rels_{list_page}_{i}_{user_id}_{identifier}") for i in range(len(page_moves))]
    for i in range(0, len(num_buttons), 3):
        kb.row(*num_buttons[i:i + 3])

    nav_row = []
    if list_page > 0:
        nav_row.append(types.InlineKeyboardButton("Previous", callback_data=f"relp_{list_page - 1}_{user_id}_{identifier}"))
    if list_page < len(pages) - 1:
        nav_row.append(types.InlineKeyboardButton("Next", callback_data=f"relp_{list_page + 1}_{user_id}_{identifier}"))
    if nav_row:
        kb.row(*nav_row)

    kb.row(types.InlineKeyboardButton("Back", callback_data=f"insp_i_{user_id}_{identifier}"))
    return caption, kb


def build_relearn_slot_page(user_id, identifier, list_page, move_idx):
    details = db.get_pokemon_details(user_id, identifier)
    name = details["name"] if details else str(identifier)
    moves = get_pokemon_relearn_moves_sync(name)
    pages = [moves[i:i + RELEARN_PAGE_SIZE] for i in range(0, len(moves), RELEARN_PAGE_SIZE)]
    if not pages or list_page < 0 or list_page >= len(pages): return None, None
    page_moves = pages[list_page]
    if move_idx < 0 or move_idx >= len(page_moves): return None, None
    new_move = page_moves[move_idx]

    current_moves = db.get_pokemon_custom_moves(user_id, identifier) or get_pokemon_moveset_sync(name)
    if not current_moves: return None, None

    n_emoji = TYPE_EMOJIS.get(new_move["type"], "")
    header = (f"*{escape_md(name.capitalize())}* \\(Shiny\\)\n\n"
              f"Learn {escape_md(new_move['name'])} \\[{n_emoji}\\]?\n\n"
              f"Select a current move to forget:\n\n")
    lines = []
    for i, m in enumerate(current_moves, start=1):
        m_emoji = TYPE_EMOJIS.get(m.get("type", "Normal"), "")
        lines.append(f"{i}\\. {escape_md(m['name'])} \\[{m_emoji}\\]  Power: {m['power']}, Accuracy: {m['acc']}")
    caption = header + "\n".join(lines)

    kb = types.InlineKeyboardMarkup(row_width=3)
    num_buttons = [types.InlineKeyboardButton(str(i + 1), callback_data=f"relr_{list_page}_{move_idx}_{i - 1}_{user_id}_{identifier}") for i in range(1, len(current_moves) + 1)]
    for i in range(0, len(num_buttons), 3):
        kb.row(*num_buttons[i:i + 3])
    kb.row(types.InlineKeyboardButton("Back", callback_data=f"relp_{list_page}_{user_id}_{identifier}"))
    return caption, kb


def send_leaderboard(bot, chat_id, user_id, message_id=None, mode="catch"):
    if mode == "catch":
        top_players = db.get_top_trainers(5)
        title = "🏆 *Tᴏᴘ Tʀᴀɪɴᴇʀs \\(Cᴏʟʟᴇᴄᴛɪᴏɴ\\)*\n\n"
        user_rank = db.get_user_rank(user_id)
        score_label = "Pᴏᴋᴇ́ᴍᴏɴ"
    else:
        top_players = db.get_top_pvp_players(5)
        title = "⚔️ *Tᴏᴘ Tʀᴀɪɴᴇʀs \\(PᴠP Wɪɴs\\)*\n\n"
        user_rank = db.get_user_pvp_rank(user_id)
        score_label = "Wɪɴs"

    text = title
    for i, (uid, count) in enumerate(top_players):
        try: name = clean_name(bot.get_chat(uid).first_name)
        except: name = "Trainer"
        text += f"{i+1}\\. *{escape_md(name)}* — {count} {score_label}\n"
    
    text += f"\nYᴏᴜʀ Rᴀɴᴋ — *{user_rank}*"
    
    kb = types.InlineKeyboardMarkup(row_width=2)
    if mode == "catch": kb.add(types.InlineKeyboardButton("⚔️ Tᴏᴘ PᴠP Wɪɴɴᴇʀs", callback_data=f"flex_pvp_{user_id}"))
    else: kb.add(types.InlineKeyboardButton("🏆 Tᴏᴘ Cᴀᴛᴄʜᴇʀs", callback_data=f"flex_catch_{user_id}"))
    kb.add(types.InlineKeyboardButton("REFRESH 🌀", callback_data=f"flex_{mode}_{user_id}"))
    
    if message_id:
        try: bot.edit_message_text(text, chat_id, message_id, reply_markup=kb, parse_mode="MarkdownV2")
        except: pass
    else: safe_send(bot, chat_id, text, reply_markup=kb)

# ================== REGISTRATION ROUTER ==================
def register_user_handlers(bot, active_hunts):
    
    @bot.message_handler(commands=["start"])
    def cmd_start(message):
        def process():
            is_new = db.add_user_if_new(message.from_user.id)
            
            if is_new and LOG_GROUP_ID:
                try:
                    u_name = clean_name(message.from_user.first_name)
                    u_id = message.from_user.id
                    log_msg = f"🌟 【Sᴛᴀʀᴛ】 [{escape_md(u_name)}](tg://user?id={u_id}) ᴇɴᴛᴇʀᴇᴅ ᴛʜᴇ ᴡᴏʀʟᴅ ᴏғ Sᴇxᴀ"
                    bot.send_message(LOG_GROUP_ID, log_msg, parse_mode="MarkdownV2")
                except: pass
                
            if message.chat.type in ["group", "supergroup"]: db.add_group(message.chat.id)
            kb = types.InlineKeyboardMarkup(row_width=2)
            kb.row(types.InlineKeyboardButton("Oᴡɴᴇʀ ⚡", url="https://t.me/monarch_sama"), types.InlineKeyboardButton("Mᴀɪɴ Gʀᴏᴜᴘ ⚡", url="https://t.me/sexagamechat"))
            text = (f"Hҽყ {escape_md(clean_name(message.from_user.first_name))}\n\n*Wᴇʟᴄσɱᴇ ᴛσ Sᴇxᴀ ✨*\n*Tʜᴇ Sʜɪɴʏ Pᴏᴋᴇ́ᴍᴏɴ Aᴅᴠᴇɴᴛᴜʀᴇ*\n\n"
                    f"━━━━━━━━━━━━━━━\n*🔎 Hᴜɴᴛ • 🎯 Cᴀᴛᴄʜ • 💎 Fʟᴇx*\n━━━━━━━━━━━━━━━\n*🌍 Yᴏᴜʀ Jᴏᴜʀɴᴇʏ Bᴇɢɪɴs Nᴏᴡ*")
            safe_send(bot, message.chat.id, text, reply_to_id=message.message_id, reply_markup=kb)
        threading.Thread(target=process).start()

    @bot.message_handler(commands=["open"])
    def cmd_open(message):
        if message.chat.type != "private": return safe_send(bot, message.chat.id, escape_md("⚠️ Only in DMs."), reply_to_id=message.message_id)
        kb = types.ReplyKeyboardMarkup(resize_keyboard=True, row_width=1).add(types.KeyboardButton("🔎 Scout"))
        bot.send_message(message.chat.id, "⌨️ *Mᴇɴᴜ Oᴘᴇɴᴇᴅ\\!*\n/close ᴛᴏ Hɪᴅᴇ", reply_markup=kb, parse_mode="MarkdownV2")

    @bot.message_handler(commands=["close"])
    def cmd_close(message):
        if message.chat.type != "private": return
        bot.send_message(message.chat.id, "⌨️ *Mᴇɴᴜ Cʟᴏsᴇᴅ\\!*\nTʏᴘᴇ /open ᴛᴏ Rᴇᴏᴘᴇɴ\\.", reply_markup=types.ReplyKeyboardRemove(), parse_mode="MarkdownV2")

    @bot.message_handler(func=lambda message: message.text == "🔎 Scout" and message.chat.type == "private")
    def text_scout(message): threading.Thread(target=start_scout, args=(bot, message.chat.id, message.from_user.id, active_hunts, message.message_id)).start()

    @bot.message_handler(commands=["scout"])
    def command_scout(message): threading.Thread(target=start_scout, args=(bot, message.chat.id, message.from_user.id, active_hunts, message.message_id)).start()

    @bot.message_handler(commands=["task", "tasks"])
    def cmd_task(message):
        def process():
            db.add_user_if_new(message.from_user.id)
            tasks.render_tasks_ui(bot, message.chat.id, message.from_user.id)
        threading.Thread(target=process).start()

    @bot.message_handler(commands=["profile", "trainer"])
    def cmd_profile(message):
        def process():
            user_id = message.from_user.id
            if not db.get_user(user_id): return safe_send(bot, message.chat.id, escape_md("⚠️ Please /start the bot first."), reply_to_id=message.message_id)
            
            tries_left, region = db.update_user_tries(user_id)
            names = db.list_user_pokemon_names(user_id)
            rarest_caught = [p for p in names if p in LEGENDARY_NAMES or "Mega" in p or "Primal" in p][0] if names and any(p for p in names if p in LEGENDARY_NAMES or "Mega" in p or "Primal" in p) else (names[-1] if names else "None")
            wins, losses = db.get_battle_stats(user_id)
            
            badges = db.get_user_badges(user_id)
            badge_str = " ".join(badges) if badges else "Nᴏɴᴇ Yᴇᴛ"
            
            total_battles = wins + losses
            win_rate = round((wins / total_battles * 100), 1) if total_battles > 0 else 0.0
                
            u_name = escape_md(to_small_caps(clean_name(message.from_user.first_name)))
            region_str = escape_md(to_small_caps(region))
            rarest_str = escape_md(to_small_caps(rarest_caught))
            
            text = (
                f"*✦━━━━━━━━━━━━━━━━✦*\n"
                f"      *🪪 TʀᴀɪɴᴇR Cᴀʀᴅ 🪪*\n"
                f"*✦━━━━━━━━━━━━━━━━✦*\n\n"
                f"*👤 Nᴀᴍᴇ — {u_name}*\n"
                f"*🆔 Uɪᴅ — `{user_id}`*\n"
                f"*🌍 Cᴜʀʀᴇɴᴛ Rᴇɢɪᴏɴ — {region_str}*\n\n"
                f"*✦━━━━━━━━━━━━━━━━✦*\n"
                f"         *Gʏᴍ Bᴀᴅɢᴇs*\n"
                f"*✦━━━━━━━━━━━━━━━━✦*\n"
                f"   {badge_str}\n\n"
                f"*✦━━━━━━━━━━━━━━━━✦*\n"
                f"         *AᴅᴠᴇɴᴛᴜʀE Sᴛᴀᴛs*\n"
                f"*✦━━━━━━━━━━━━━━━━✦*\n\n"
                f"*🎒 Cᴏʟʟᴇᴄᴛɪᴏɴ — {len(names)} Pᴏᴋᴇ́ᴍᴏɴ*\n"
                f"*⭐ Rᴀʀᴇsᴛ — {rarest_str}*\n"
                f"*🔋 Sᴄᴏᴜᴛs Lᴇғᴛ — {tries_left} / 2500*\n\n"
                f"*✦━━━━━━━━━━━━━━━━✦*\n"
                f"           *Bᴀᴛᴛʟᴇ Rᴇᴄᴏʀᴅ*\n"
                f"*✦━━━━━━━━━━━━━━━━✦*\n\n"
                f"*🏆 Wɪɴs — {wins}*\n"
                f"*❌ Lᴏssᴇs — {losses}*\n"
                f"*📊 Tᴏᴛᴀʟ Bᴀᴛᴛʟᴇs — {total_battles}*\n"
                f"*📈 Wɪɴ Rᴀᴛᴇ — {escape_md(str(win_rate))}%*\n\n"
                f"*✦━━━━━━━━━━━━━━━━✦*"
            )
            safe_send(bot, message.chat.id, text, reply_to_id=message.message_id)
        threading.Thread(target=process).start()

    @bot.message_handler(commands=["travel"])
    def cmd_travel(message):
        def process():
            user_data = db.get_user(message.from_user.id)
            if not user_data: return safe_send(bot, message.chat.id, escape_md("⚠️ Please /start the bot first."), reply_to_id=message.message_id)
            
            current_region = user_data[2] if len(user_data) > 2 else "Kanto"
            kb = types.InlineKeyboardMarkup(row_width=2)
            kb.add(types.InlineKeyboardButton(f"📍 Cᴜʀʀᴇɴᴛ Rᴇɢɪᴏɴ: {to_small_caps(current_region)}", callback_data=f"cur_reg_{current_region}"))
            
            btns = [types.InlineKeyboardButton(f"{to_small_caps(r)}", callback_data=f"travel_{message.from_user.id}_{r}") for r in REGIONS]
            for i in range(0, len(btns), 2):
                if i + 1 < len(btns): kb.add(btns[i], btns[i+1])
                else: kb.add(btns[i])
            kb.add(types.InlineKeyboardButton("Cᴀɴᴄᴇʟ ↩️", callback_data=f"travel_cancel_{message.from_user.id}"))
            safe_send(bot, message.chat.id, "🌍 *Wʜᴇʀᴇ Wᴏᴜʟᴅ Yᴏᴜ Lɪᴋᴇ Tᴏ Tʀᴀᴠᴇʟ, Tʀᴀɪɴᴇʀ?*", reply_to_id=message.message_id, reply_markup=kb)
        threading.Thread(target=process).start()

    @bot.message_handler(commands=["pokedex", "dex"])
    def cmd_pokedex(message):
        def process():
            parts = message.text.split(maxsplit=1)
            if len(parts) < 2: return safe_send(bot, message.chat.id, escape_md("📝 Usage: /pokedex <pokemon_name>"), reply_to_id=message.message_id)
            name_raw = parts[1].strip()
            name = name_raw.lower()
            
            poke_id = get_pokemon_id_sync(name)
            if not poke_id: 
                text, kb = generate_did_you_mean(name_raw, pokemon_name_to_id_cache.keys(), "dym_dex", message.from_user.id)
                return safe_send(bot, message.chat.id, text, reply_to_id=message.message_id, reply_markup=kb)
                
            text = get_dex_text(name, "info")
            img_url = official_shiny_artwork_url(poke_id)
            
            photo_payload = get_cached_image_payload(poke_id, img_url)
            
            kb = types.InlineKeyboardMarkup(row_width=2).add(types.InlineKeyboardButton("✅ ℹ️ Info", callback_data="ignore"), types.InlineKeyboardButton("📊 Stats", callback_data=f"dex_stats_{name}"))
            try: bot.send_photo(message.chat.id, photo_payload, caption=text, reply_markup=kb, parse_mode="MarkdownV2")
            except: pass
        threading.Thread(target=process).start()

    # ================== CALLBACK FOR DID YOU MEAN BUTTONS ==================
    @bot.callback_query_handler(func=lambda call: call.data.startswith("dym_"))
    def cq_did_you_mean(call):
        def process():
            try:
                parts = call.data.split("_", 3)
                if len(parts) < 4:
                    return bot.answer_callback_query(call.id)
                
                _, action, uid_str, name = parts
                if str(call.from_user.id) != uid_str:
                    return bot.answer_callback_query(call.id, "❌ This isn't your menu.", show_alert=True)

                bot.answer_callback_query(call.id)

                if action == "dex":
                    poke_id = get_pokemon_id_sync(name)
                    if poke_id:
                        text = get_dex_text(name, "info")
                        img_url = official_shiny_artwork_url(poke_id)
                        photo_payload = get_cached_image_payload(poke_id, img_url)
                        kb = types.InlineKeyboardMarkup(row_width=2).add(
                            types.InlineKeyboardButton("✅ ℹ️ Info", callback_data="ignore"),
                            types.InlineKeyboardButton("📊 Stats", callback_data=f"dex_stats_{name}")
                        )
                        try:
                            bot.send_photo(call.message.chat.id, photo_payload, caption=text, reply_markup=kb, parse_mode="MarkdownV2")
                        except Exception:
                            safe_send(bot, call.message.chat.id, text, reply_markup=kb)

                elif action == "ins":
                    entries = db.get_user_pokemon_by_name(call.from_user.id, name)
                    if not entries:
                        safe_send(bot, call.message.chat.id, escape_md(f"❌ You don't own a {name.title()}."))
                    elif len(entries) == 1:
                        try: bot.delete_message(call.message.chat.id, call.message.message_id)
                        except: pass
                        caption, kb = build_inspect_page(call.from_user.id, entries[0]["id"], "i")
                        poke_id = get_pokemon_id_sync(entries[0]["name"])
                        if caption and poke_id:
                            photo_payload = get_cached_image_payload(poke_id, official_shiny_artwork_url(poke_id))
                            bot.send_photo(call.message.chat.id, photo_payload, caption=caption, reply_markup=kb, parse_mode="MarkdownV2")
                    else:
                        text, kb = generate_inspect_multi_ui(call.from_user.id, name, 0)
                        try:
                            bot.edit_message_text(text, chat_id=call.message.chat.id, message_id=call.message.message_id, reply_markup=kb, parse_mode="MarkdownV2")
                        except Exception:
                            safe_send(bot, call.message.chat.id, text, reply_markup=kb)

                elif action == "rel":
                    poke_name = name.title()
                    text = (f"⚠️ *Confirm Release*\n\n"
                            f"Are you sure you want to release\n"
                            f"*{escape_md(poke_name)}*?\n\n"
                            f"This action cannot be undone\\.")
                    kb = types.InlineKeyboardMarkup(row_width=2)
                    kb.add(
                        types.InlineKeyboardButton("Confirm", callback_data=f"relc_Y_{call.from_user.id}_{poke_name[:32]}"),
                        types.InlineKeyboardButton("Cancel", callback_data=f"relc_N_{call.from_user.id}_{poke_name[:32]}")
                    )
                    safe_send(bot, call.message.chat.id, text, reply_markup=kb)

            except Exception:
                logger.exception(f"❌ cq_did_you_mean failed: {call.data}")
        threading.Thread(target=process).start()

    @bot.message_handler(commands=["mypokemon", "mypokemons"])
    def cmd_mypokemon(message):
        def process():
            if not db.get_user(message.from_user.id): return safe_send(bot, message.chat.id, escape_md("⚠️ Please /start the bot first."))
            text, kb = generate_pokemon_list_ui(message.from_user.id, 0, action_prefix="mypoke", is_admin=False)
            safe_send(bot, message.chat.id, text, reply_markup=kb, reply_to_id=message.message_id)
        threading.Thread(target=process).start()

    @bot.message_handler(commands=["sort"])
    def cmd_sort(message):
        def process():
            if not db.get_user(message.from_user.id): return safe_send(bot, message.chat.id, escape_md("⚠️ Please /start the bot first."), reply_to_id=message.message_id)
            text, kb = build_sort_menu(message.from_user.id)
            safe_send(bot, message.chat.id, text, reply_markup=kb, reply_to_id=message.message_id)
        threading.Thread(target=process).start()

    @bot.callback_query_handler(func=lambda call: call.data.startswith("srtdir_"))
    def cq_sort_direction(call):
        def process():
            try:
                _, uid_str = call.data.split("_", 1)
                if str(call.from_user.id) != uid_str:
                    return bot.answer_callback_query(call.id, "❌ This isn't your menu.", show_alert=True)
                current = db.get_list_settings(call.from_user.id)
                new_dir = "asc" if current.get("sort_dir") == "desc" else "desc"
                db.update_list_settings(call.from_user.id, sort_dir=new_dir)
                text, kb = build_sort_menu(call.from_user.id)
                try: bot.edit_message_text(text, chat_id=call.message.chat.id, message_id=call.message.message_id, reply_markup=kb, parse_mode="MarkdownV2")
                except Exception: logger.exception(f"cq_sort_direction edit failed: {call.data}")
                bot.answer_callback_query(call.id, "✅ Direction changed.")
            except Exception:
                logger.exception(f"❌ cq_sort_direction failed entirely: {call.data}")
                try: bot.answer_callback_query(call.id, "⚠️ Something went wrong.", show_alert=True)
                except: pass
        threading.Thread(target=process).start()

    @bot.callback_query_handler(func=lambda call: call.data.startswith("srt_"))
    def cq_sort_select(call):
        def process():
            try:
                _, uid_str, num_str = call.data.split("_", 2)
                if str(call.from_user.id) != uid_str:
                    return bot.answer_callback_query(call.id, "❌ This isn't your menu.", show_alert=True)
                sort_by = SORT_BY_NUM.get(num_str)
                if not sort_by:
                    return bot.answer_callback_query(call.id, "⚠️ Invalid option.", show_alert=True)
                db.update_list_settings(call.from_user.id, sort_by=sort_by)
                text, kb = build_sort_menu(call.from_user.id)
                try: bot.edit_message_text(text, chat_id=call.message.chat.id, message_id=call.message.message_id, reply_markup=kb, parse_mode="MarkdownV2")
                except Exception: logger.exception(f"cq_sort_select edit failed: {call.data}")
                bot.answer_callback_query(call.id, "✅ Sort updated.")
            except Exception:
                logger.exception(f"❌ cq_sort_select failed entirely: {call.data}")
                try: bot.answer_callback_query(call.id, "⚠️ Something went wrong.", show_alert=True)
                except: pass
        threading.Thread(target=process).start()

    @bot.message_handler(commands=["display"])
    def cmd_display(message):
        def process():
            if not db.get_user(message.from_user.id): return safe_send(bot, message.chat.id, escape_md("⚠️ Please /start the bot first."), reply_to_id=message.message_id)
            text, kb = build_display_menu(message.from_user.id)
            safe_send(bot, message.chat.id, text, reply_markup=kb, reply_to_id=message.message_id)
        threading.Thread(target=process).start()

    @bot.callback_query_handler(func=lambda call: call.data.startswith("dspnum_"))
    def cq_display_numbering(call):
        def process():
            try:
                _, uid_str = call.data.split("_", 1)
                if str(call.from_user.id) != uid_str:
                    return bot.answer_callback_query(call.id, "❌ This isn't your menu.", show_alert=True)
                current = db.get_list_settings(call.from_user.id)
                db.update_list_settings(call.from_user.id, show_numbering=not current.get("show_numbering", True))
                text, kb = build_display_menu(call.from_user.id)
                try: bot.edit_message_text(text, chat_id=call.message.chat.id, message_id=call.message.message_id, reply_markup=kb, parse_mode="MarkdownV2")
                except Exception: logger.exception(f"cq_display_numbering edit failed: {call.data}")
                bot.answer_callback_query(call.id, "✅ Numbering toggled.")
            except Exception:
                logger.exception(f"❌ cq_display_numbering failed entirely: {call.data}")
                try: bot.answer_callback_query(call.id, "⚠️ Something went wrong.", show_alert=True)
                except: pass
        threading.Thread(target=process).start()

    @bot.callback_query_handler(func=lambda call: call.data.startswith("dsp_"))
    def cq_display_select(call):
        def process():
            try:
                _, uid_str, num_str = call.data.split("_", 2)
                if str(call.from_user.id) != uid_str:
                    return bot.answer_callback_query(call.id, "❌ This isn't your menu.", show_alert=True)
                display = DISPLAY_BY_NUM.get(num_str)
                if not display:
                    return bot.answer_callback_query(call.id, "⚠️ Invalid option.", show_alert=True)
                db.update_list_settings(call.from_user.id, display=display)
                text, kb = build_display_menu(call.from_user.id)
                try: bot.edit_message_text(text, chat_id=call.message.chat.id, message_id=call.message.message_id, reply_markup=kb, parse_mode="MarkdownV2")
                except Exception: logger.exception(f"cq_display_select edit failed: {call.data}")
                bot.answer_callback_query(call.id, "✅ Display updated.")
            except Exception:
                logger.exception(f"❌ cq_display_select failed entirely: {call.data}")
                try: bot.answer_callback_query(call.id, "⚠️ Something went wrong.", show_alert=True)
                except: pass
        threading.Thread(target=process).start()

    @bot.message_handler(commands=["pagesize"])
    def cmd_pagesize(message):
        def process():
            if not db.get_user(message.from_user.id): return safe_send(bot, message.chat.id, escape_md("⚠️ Please /start the bot first."), reply_to_id=message.message_id)
            text, kb = build_pagesize_menu(message.from_user.id)
            safe_send(bot, message.chat.id, text, reply_markup=kb, reply_to_id=message.message_id)
        threading.Thread(target=process).start()

    @bot.callback_query_handler(func=lambda call: call.data.startswith("pgsz_"))
    def cq_pagesize_select(call):
        def process():
            try:
                _, uid_str, size_str = call.data.split("_", 2)
                if str(call.from_user.id) != uid_str:
                    return bot.answer_callback_query(call.id, "❌ This isn't your menu.", show_alert=True)
                size = int(size_str)
                if size not in PAGE_SIZES:
                    return bot.answer_callback_query(call.id, "⚠️ Invalid page size.", show_alert=True)
                db.update_list_settings(call.from_user.id, page_size=size)
                text, kb = build_pagesize_menu(call.from_user.id)
                try: bot.edit_message_text(text, chat_id=call.message.chat.id, message_id=call.message.message_id, reply_markup=kb, parse_mode="MarkdownV2")
                except Exception: logger.exception(f"cq_pagesize_select edit failed: {call.data}")
                bot.answer_callback_query(call.id, "✅ Page size updated.")
            except Exception:
                logger.exception(f"❌ cq_pagesize_select failed entirely: {call.data}")
                try: bot.answer_callback_query(call.id, "⚠️ Something went wrong.", show_alert=True)
                except: pass
        threading.Thread(target=process).start()

    # ================== /inspect COMMAND ==================
    @bot.message_handler(commands=["inspect"])
    def cmd_inspect(message):
        def process():
            try:
                if not db.get_user(message.from_user.id): return
                parts = message.text.split(maxsplit=1)
                if len(parts) < 2: return safe_send(bot, message.chat.id, escape_md("📝 Usage: /inspect <pokemon_name>"), reply_to_id=message.message_id)
                name_raw = parts[1].strip()
                name = name_raw.lower()
                
                user_pokemon = db.list_user_pokemon_names(message.from_user.id)
                user_matches = db.get_user_pokemon_by_name(message.from_user.id, name)

                if not user_matches:
                    text, kb = generate_did_you_mean(name_raw, user_pokemon, "dym_ins", message.from_user.id)
                    return safe_send(bot, message.chat.id, text, reply_to_id=message.message_id, reply_markup=kb)

                if len(user_matches) == 1:
                    target_id = user_matches[0]["id"]
                    caption, kb = build_inspect_page(message.from_user.id, target_id, "i")
                    if caption is None:
                        return safe_send(bot, message.chat.id, escape_md("⚠️ Couldn't load that Pokémon right now."), reply_to_id=message.message_id)

                    poke_id = get_pokemon_id_sync(user_matches[0]["name"])
                    if not poke_id:
                        return safe_send(bot, message.chat.id, escape_md("⚠️ Couldn't find species data."), reply_to_id=message.message_id)

                    photo_payload = get_cached_image_payload(poke_id, official_shiny_artwork_url(poke_id))
                    try: bot.send_photo(message.chat.id, photo_payload, caption=caption, reply_markup=kb, parse_mode="MarkdownV2")
                    except Exception:
                        safe_send(bot, message.chat.id, caption, reply_markup=kb)

                else:
                    text, kb = generate_inspect_multi_ui(message.from_user.id, name, 0)
                    safe_send(bot, message.chat.id, text, reply_markup=kb, reply_to_id=message.message_id)

            except Exception:
                logger.exception(f"❌ /inspect failed entirely for uid={message.from_user.id}")
                safe_send(bot, message.chat.id, escape_md("⚠️ Something went wrong inspecting that Pokémon. Try again in a moment."), reply_to_id=message.message_id)
        threading.Thread(target=process).start()

    @bot.callback_query_handler(func=lambda call: call.data.startswith("inspsel_"))
    def cq_inspect_select(call):
        def process():
            try:
                _, uid_str, poke_id_str = call.data.split("_", 2)
                if str(call.from_user.id) != uid_str:
                    return bot.answer_callback_query(call.id, "❌ This isn't your inspection.", show_alert=True)

                caption, kb = build_inspect_page(call.from_user.id, poke_id_str, "i")
                if not caption:
                    return bot.answer_callback_query(call.id, "⚠️ Couldn't load that Pokémon.", show_alert=True)

                bot.answer_callback_query(call.id)

                # Auto-delete the selection menu message upon choice
                try:
                    bot.delete_message(call.message.chat.id, call.message.message_id)
                except Exception:
                    pass

                details = db.get_pokemon_details(call.from_user.id, poke_id_str)
                poke_id = get_pokemon_id_sync(details["name"]) if details else None

                if poke_id:
                    photo_payload = get_cached_image_payload(poke_id, official_shiny_artwork_url(poke_id))
                    try:
                        bot.send_photo(call.message.chat.id, photo_payload, caption=caption, reply_markup=kb, parse_mode="MarkdownV2")
                    except Exception:
                        safe_send(bot, call.message.chat.id, caption, reply_markup=kb)
                else:
                    safe_send(bot, call.message.chat.id, caption, reply_markup=kb)
            except Exception:
                logger.exception(f"❌ cq_inspect_select failed: {call.data}")
        threading.Thread(target=process).start()

    @bot.callback_query_handler(func=lambda call: call.data.startswith("insplst_"))
    def cq_inspect_list_page(call):
        def process():
            try:
                _, uid_str, name, page_str = call.data.split("_", 3)
                if str(call.from_user.id) != uid_str:
                    return bot.answer_callback_query(call.id, "❌ This isn't your menu.", show_alert=True)

                text, kb = generate_inspect_multi_ui(call.from_user.id, name, int(page_str))
                if text:
                    try:
                        bot.edit_message_text(text, chat_id=call.message.chat.id, message_id=call.message.message_id, reply_markup=kb, parse_mode="MarkdownV2")
                    except Exception:
                        pass
                bot.answer_callback_query(call.id)
            except Exception:
                logger.exception(f"❌ cq_inspect_list_page failed: {call.data}")
        threading.Thread(target=process).start()

    @bot.callback_query_handler(func=lambda call: call.data.startswith("insp_"))
    def cq_inspect_page(call):
        def process():
            try:
                _, page_code, uid_str, identifier = call.data.split("_", 3)
                if str(call.from_user.id) != uid_str:
                    return bot.answer_callback_query(call.id, "❌ This isn't your inspection.", show_alert=True)

                caption, kb = build_inspect_page(call.from_user.id, identifier, page_code)
                if caption is None:
                    return bot.answer_callback_query(call.id, "⚠️ Couldn't load that page.", show_alert=True)

                try:
                    bot.edit_message_caption(caption=caption, chat_id=call.message.chat.id, message_id=call.message.message_id, reply_markup=kb, parse_mode="MarkdownV2")
                except Exception:
                    logger.exception(f"cq_inspect_page edit_message_caption failed: {call.data}")
                bot.answer_callback_query(call.id)
            except Exception:
                logger.exception(f"❌ cq_inspect_page failed entirely: {call.data}")
                try: bot.answer_callback_query(call.id, "⚠️ Something went wrong.", show_alert=True)
                except: pass
        threading.Thread(target=process).start()

    @bot.callback_query_handler(func=lambda call: call.data.startswith("relp_"))
    def cq_relearner_page(call):
        def process():
            try:
                _, page_str, uid_str, identifier = call.data.split("_", 3)
                if str(call.from_user.id) != uid_str:
                    return bot.answer_callback_query(call.id, "❌ This isn't your inspection.", show_alert=True)

                caption, kb = build_relearner_page(call.from_user.id, identifier, int(page_str))
                try:
                    bot.edit_message_caption(caption=caption, chat_id=call.message.chat.id, message_id=call.message.message_id, reply_markup=kb, parse_mode="MarkdownV2")
                except Exception:
                    logger.exception(f"cq_relearner_page edit_message_caption failed: {call.data}")
                bot.answer_callback_query(call.id)
            except Exception:
                logger.exception(f"❌ cq_relearner_page failed entirely: {call.data}")
                try: bot.answer_callback_query(call.id, "⚠️ Something went wrong.", show_alert=True)
                except: pass
        threading.Thread(target=process).start()

    @bot.callback_query_handler(func=lambda call: call.data.startswith("rels_"))
    def cq_relearner_select(call):
        def process():
            try:
                _, page_str, idx_str, uid_str, identifier = call.data.split("_", 4)
                if str(call.from_user.id) != uid_str:
                    return bot.answer_callback_query(call.id, "❌ This isn't your inspection.", show_alert=True)

                caption, kb = build_relearn_slot_page(call.from_user.id, identifier, int(page_str), int(idx_str))
                if caption is None:
                    return bot.answer_callback_query(call.id, "⚠️ That move is no longer available.", show_alert=True)

                try:
                    bot.edit_message_caption(caption=caption, chat_id=call.message.chat.id, message_id=call.message.message_id, reply_markup=kb, parse_mode="MarkdownV2")
                except Exception:
                    logger.exception(f"cq_relearner_select edit_message_caption failed: {call.data}")
                bot.answer_callback_query(call.id)
            except Exception:
                logger.exception(f"❌ cq_relearner_select failed entirely: {call.data}")
                try: bot.answer_callback_query(call.id, "⚠️ Something went wrong.", show_alert=True)
                except: pass
        threading.Thread(target=process).start()

    @bot.callback_query_handler(func=lambda call: call.data.startswith("relr_"))
    def cq_relearner_replace(call):
        def process():
            try:
                _, page_str, idx_str, slot_str, uid_str, identifier = call.data.split("_", 5)
                if str(call.from_user.id) != uid_str:
                    return bot.answer_callback_query(call.id, "❌ This isn't your inspection.", show_alert=True)

                list_page, move_idx, slot = int(page_str), int(idx_str), int(slot_str)
                details = db.get_pokemon_details(call.from_user.id, identifier)
                name = details["name"] if details else str(identifier)
                
                moves = get_pokemon_relearn_moves_sync(name)
                pages = [moves[i:i + RELEARN_PAGE_SIZE] for i in range(0, len(moves), RELEARN_PAGE_SIZE)]
                if not pages or list_page < 0 or list_page >= len(pages) or move_idx < 0 or move_idx >= len(pages[list_page]):
                    return bot.answer_callback_query(call.id, "⚠️ That move is no longer available.", show_alert=True)
                new_move = pages[list_page][move_idx]

                base_moves = db.get_pokemon_custom_moves(call.from_user.id, identifier) or get_pokemon_moveset_sync(name)
                if not base_moves or slot < 0 or slot >= len(base_moves):
                    return bot.answer_callback_query(call.id, "⚠️ Couldn't update that move.", show_alert=True)

                old_move_name = base_moves[slot]["name"]
                updated = db.set_pokemon_move_slot(call.from_user.id, identifier, base_moves, slot, new_move)
                if not updated:
                    return bot.answer_callback_query(call.id, "⚠️ Couldn't save that move.", show_alert=True)

                caption, kb = build_relearner_page(call.from_user.id, identifier, list_page)
                note = f"✅ *Fᴏʀɢᴏᴛ {escape_md(old_move_name)}, ʟᴇᴀʀɴᴇD {escape_md(new_move['name'])}\\!*\n\n"
                caption = note + caption
                try:
                    bot.edit_message_caption(caption=caption, chat_id=call.message.chat.id, message_id=call.message.message_id, reply_markup=kb, parse_mode="MarkdownV2")
                except Exception:
                    logger.exception(f"cq_relearner_replace edit_message_caption failed: {call.data}")
                bot.answer_callback_query(call.id, "✅ Move updated!")
            except Exception:
                logger.exception(f"❌ cq_relearner_replace failed entirely: {call.data}")
                try: bot.answer_callback_query(call.id, "⚠️ Something went wrong.", show_alert=True)
                except: pass
        threading.Thread(target=process).start()

    @bot.callback_query_handler(func=lambda call: call.data.startswith("insprel_"))
    def cq_inspect_release_prompt(call):
        def process():
            try:
                _, uid_str, identifier = call.data.split("_", 2)
                if str(call.from_user.id) != uid_str:
                    return bot.answer_callback_query(call.id, "❌ This isn't your inspection.", show_alert=True)

                details = db.get_pokemon_details(call.from_user.id, identifier)
                name_disp = details["name"].capitalize() if details else "Pokémon"
                
                caption = (f"⚠️ *Confirm Release*\n\n"
                           f"Are you sure you want to release\n"
                           f"*{escape_md(name_disp)}*?\n\n"
                           f"This action cannot be undone\\.")
                kb = types.InlineKeyboardMarkup(row_width=2)
                kb.add(
                    types.InlineKeyboardButton("Confirm", callback_data=f"insprelc_Y_{call.from_user.id}_{identifier}"),
                    types.InlineKeyboardButton("Cancel", callback_data=f"insprelc_N_{call.from_user.id}_{identifier}")
                )
                try:
                    bot.edit_message_caption(caption=caption, chat_id=call.message.chat.id, message_id=call.message.message_id, reply_markup=kb, parse_mode="MarkdownV2")
                except Exception:
                    logger.exception(f"cq_inspect_release_prompt edit_message_caption failed: {call.data}")
                bot.answer_callback_query(call.id)
            except Exception:
                logger.exception(f"❌ cq_inspect_release_prompt failed entirely: {call.data}")
                try: bot.answer_callback_query(call.id, "⚠️ Something went wrong.", show_alert=True)
                except: pass
        threading.Thread(target=process).start()

    @bot.callback_query_handler(func=lambda call: call.data.startswith("insprelc_"))
    def cq_inspect_release_confirm(call):
        def process():
            try:
                _, decision, uid_str, identifier = call.data.split("_", 3)
                if str(call.from_user.id) != uid_str:
                    return bot.answer_callback_query(call.id, "❌ This isn't your inspection.", show_alert=True)

                if decision == "N":
                    caption, kb = build_inspect_page(call.from_user.id, identifier, "i")
                    if caption is None:
                        return bot.answer_callback_query(call.id, "⚠️ Couldn't load that Pokémon.", show_alert=True)
                    try:
                        bot.edit_message_caption(caption=caption, chat_id=call.message.chat.id, message_id=call.message.message_id, reply_markup=kb, parse_mode="MarkdownV2")
                    except Exception:
                        logger.exception(f"cq_inspect_release_confirm(N) edit_message_caption failed: {call.data}")
                    return bot.answer_callback_query(call.id, "❌ Release cancelled.")

                details = db.get_pokemon_details(call.from_user.id, identifier)
                name_disp = details["name"].capitalize() if details else "Pokémon"
                
                ok = db.delete_pokemon(call.from_user.id, identifier)
                caption = f"*{escape_md(name_disp)} was released\\.*" if ok else escape_md("Couldn't release that Pokémon.")
                try:
                    bot.edit_message_caption(caption=caption, chat_id=call.message.chat.id, message_id=call.message.message_id, reply_markup=None, parse_mode="MarkdownV2")
                except Exception:
                    logger.exception(f"cq_inspect_release_confirm(Y) edit_message_caption failed: {call.data}")
                bot.answer_callback_query(call.id, "✅ Released." if ok else "⚠️ Failed.")
            except Exception:
                logger.exception(f"❌ cq_inspect_release_confirm failed entirely: {call.data}")
                try: bot.answer_callback_query(call.id, "⚠️ Something went wrong.", show_alert=True)
                except: pass
        threading.Thread(target=process).start()

    @bot.callback_query_handler(func=lambda call: call.data.startswith("evo_"))
    def cq_evolve_prompt(call):
        def process():
            try:
                _, uid_str, identifier, target_name = call.data.split("_", 3)
                if str(call.from_user.id) != uid_str:
                    return bot.answer_callback_query(call.id, "❌ This isn't your Pokémon.", show_alert=True)

                details = db.get_pokemon_details(call.from_user.id, identifier)
                name_disp = details["name"].capitalize() if details else "Pokémon"

                caption = (f"🌟 *Confirm Evolution*\n\n"
                           f"Evolve *{escape_md(name_disp)}* into\n"
                           f"*{escape_md(target_name)}*?\n\n"
                           f"This action cannot be undone\\.")
                kb = types.InlineKeyboardMarkup(row_width=2)
                kb.add(
                    types.InlineKeyboardButton("Confirm", callback_data=f"evoc_Y_{call.from_user.id}_{identifier}_{target_name}"),
                    types.InlineKeyboardButton("Cancel", callback_data=f"evoc_N_{call.from_user.id}_{identifier}_{target_name}")
                )
                try:
                    bot.edit_message_caption(caption=caption, chat_id=call.message.chat.id, message_id=call.message.message_id, reply_markup=kb, parse_mode="MarkdownV2")
                except Exception:
                    logger.exception(f"cq_evolve_prompt edit_message_caption failed: {call.data}")
                bot.answer_callback_query(call.id)
            except Exception:
                logger.exception(f"❌ cq_evolve_prompt failed entirely: {call.data}")
                try: bot.answer_callback_query(call.id, "⚠️ Something went wrong.", show_alert=True)
                except: pass
        threading.Thread(target=process).start()

    @bot.callback_query_handler(func=lambda call: call.data.startswith("evoc_"))
    def cq_evolve_confirm(call):
        def process():
            try:
                _, decision, uid_str, identifier, target_name = call.data.split("_", 4)
                if str(call.from_user.id) != uid_str:
                    return bot.answer_callback_query(call.id, "❌ This isn't your Pokémon.", show_alert=True)

                # Buttons disappear immediately while the action is processed.
                try:
                    transitional = "🌟 *Evolving\\.\\.\\.*" if decision == "Y" else "❌ *Cancelling\\.\\.\\.*"
                    bot.edit_message_caption(caption=transitional, chat_id=call.message.chat.id, message_id=call.message.message_id, reply_markup=None, parse_mode="MarkdownV2")
                except Exception:
                    logger.exception(f"cq_evolve_confirm transitional edit_message_caption failed: {call.data}")

                if decision == "N":
                    caption, kb = build_inspect_page(call.from_user.id, identifier, "s")
                    if caption is None:
                        return bot.answer_callback_query(call.id, "⚠️ Couldn't load that Pokémon.", show_alert=True)
                    try:
                        bot.edit_message_caption(caption=caption, chat_id=call.message.chat.id, message_id=call.message.message_id, reply_markup=kb, parse_mode="MarkdownV2")
                    except Exception:
                        logger.exception(f"cq_evolve_confirm(N) edit_message_caption failed: {call.data}")
                    return bot.answer_callback_query(call.id, "❌ Evolution cancelled.")

                ok = db.evolve_pokemon(call.from_user.id, identifier, target_name.title())
                if not ok:
                    return bot.answer_callback_query(call.id, "⚠️ Couldn't evolve that Pokémon.", show_alert=True)

                caption, kb = build_inspect_page(call.from_user.id, identifier, "s")
                if caption is None:
                    caption = f"✨ Evolved into *{escape_md(target_name.title())}*\\!"
                    kb = None
                try:
                    bot.edit_message_caption(caption=caption, chat_id=call.message.chat.id, message_id=call.message.message_id, reply_markup=kb, parse_mode="MarkdownV2")
                except Exception:
                    logger.exception(f"cq_evolve_confirm(Y) edit_message_caption failed: {call.data}")
                bot.answer_callback_query(call.id, "✨ Evolved!")
            except Exception:
                logger.exception(f"❌ cq_evolve_confirm failed entirely: {call.data}")
                try: bot.answer_callback_query(call.id, "⚠️ Something went wrong.", show_alert=True)
                except: pass
        threading.Thread(target=process).start()

    @bot.message_handler(commands=["release"])
    def cmd_release(message):
        def process():
            if not db.get_user(message.from_user.id): return
            parts = message.text.split(maxsplit=1)
            if len(parts) < 2: return safe_send(bot, message.chat.id, escape_md("📝 Usage: /release <pokemon_name>"), reply_to_id=message.message_id)
            poke_name_raw = parts[1].strip()
            poke_name = poke_name_raw.title()
            
            user_pokemon = db.list_user_pokemon_names(message.from_user.id)
            if poke_name.lower() not in [n.lower() for n in user_pokemon]:
                text, kb = generate_did_you_mean(poke_name_raw, user_pokemon, "dym_rel", message.from_user.id)
                return safe_send(bot, message.chat.id, text, reply_to_id=message.message_id, reply_markup=kb)
                
            text = (f"⚠️ *Confirm Release*\n\n"
                    f"Are you sure you want to release\n"
                    f"*{escape_md(poke_name)}*?\n\n"
                    f"This action cannot be undone\\.")
            
            kb = types.InlineKeyboardMarkup(row_width=2)
            kb.add(
                types.InlineKeyboardButton("Confirm", callback_data=f"relc_Y_{message.from_user.id}_{poke_name[:32]}"),
                types.InlineKeyboardButton("Cancel", callback_data=f"relc_N_{message.from_user.id}_{poke_name[:32]}")
            )
            safe_send(bot, message.chat.id, text, reply_to_id=message.message_id, reply_markup=kb)
        threading.Thread(target=process).start()

    @bot.message_handler(commands=["pvp"])
    def command_pvp(message): pvp.handle_pvp_command(bot, message)

    @bot.message_handler(commands=["trade"])
    def command_trade(message): 
        db.add_user_if_new(message.from_user.id)
        trade.handle_trade_command(bot, message)

    @bot.message_handler(commands=["gym", "gyms"])
    def command_gym(message): 
        import gym
        gym.handle_gym_command(bot, message)

    @bot.message_handler(commands=["myteam"])
    def cmd_myteam(message):
        user_id = message.from_user.id
        user_team = next((b["p1_team"] if b["p1_id"] == user_id else b["p2_team"] for b in pvp.pvp_battles.values() if user_id in [b["p1_id"], b["p2_id"]]), None)
                
        if not user_team: return safe_send(bot, message.chat.id, escape_md("❌ You are not currently in an active PvP battle!"))
            
        team_text = "🎒 *Your Current PvP Team:*\n\n"
        for i, p in enumerate(user_team):
            emojis = " / ".join([f"{t.strip()} {TYPE_EMOJIS.get(t.strip(), '⚪')}" for t in p.get('types', 'Unknown').split('/')])
            team_text += f"*{i+1}\\. {escape_md(p['name'])}* \\[{escape_md(emojis)}\\]\n🌿 *Nature:* {escape_md(p['nature'])}\n⚔️ *Moves:*\n"
            
            for m in p['moves']: 
                m_type = m.get('type', 'Normal')
                m_emoji = TYPE_EMOJIS.get(m_type, '')
                m_str = escape_md(f"{m_type} {m_emoji}".strip())
                m_pow = m.get('power', 0)
                m_acc = m.get('acc', 100)
                team_text += f"  \\- {escape_md(m['name'])} \\[{m_str}\\] \\(Pow: {m_pow}, Acc: {m_acc}\\)\n"
            team_text += "\n"
            
        try:
            bot.send_message(user_id, team_text, parse_mode="MarkdownV2")
            if message.chat.type != "private":
                kb = types.InlineKeyboardMarkup().add(types.InlineKeyboardButton("Cʜᴇᴄᴋ DMs ❗❗", url=f"https://t.me/{bot.get_me().username}"))
                safe_send(bot, message.chat.id, "📩 *I'ᴠᴇ Sᴇɴᴛ Yᴏᴜʀ Tᴇᴀᴍ Sᴛʀᴀᴛᴇɢʏ Tᴏ Yᴏᴜʀ DMs\\!*", reply_to_id=message.message_id, reply_markup=kb)
        except: safe_send(bot, message.chat.id, escape_md("⚠️ Please send me a private message first!"))

    @bot.message_handler(commands=["flex", "top", "leaderboard"])
    def command_flex(message):
        def process():
            db.add_user_if_new(message.from_user.id)
            send_leaderboard(bot, message.chat.id, message.from_user.id, mode="catch")
        threading.Thread(target=process).start()
        
    @bot.message_handler(commands=["getid"])
    def cmd_getid(message):
        safe_send(bot, message.chat.id, escape_md(f"🆔 Chat ID: {message.chat.id}\n📁 Chat Type: {message.chat.type}"), reply_to_id=message.message_id)
