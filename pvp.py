# pvp.py
import time
import random
import threading
import asyncio
import copy
import traceback
from telebot import types
import database as db
from api_utils import escape_md, generate_random_team, get_pokemon_id_sync, official_shiny_artwork_url, get_pokemon_stats_sync
from config import logger, MEGA_POKEMON, LOG_GROUP_ID

pvp_battles = {}
pending_challenges = {} 

# --- BATTLE DATA ---
NATURES = ["Adamant", "Jolly", "Modest", "Timid", "Bold", "Calm", "Careful", "Impish"]

TYPE_EMOJIS = {
    'Normal': '🔘', 'Fire': '🔥', 'Water': '💧', 'Electric': '⚡', 'Grass': '🌿', 
    'Ice': '🧊', 'Fighting': '🥊', 'Poison': '☣️', 'Ground': '⛰️', 'Flying': '🪽', 
    'Psychic': '🔮', 'Bug': '🐛', 'Rock': '🪨', 'Ghost': '👻', 'Dragon': '🐉', 
    'Dark': '🌑', 'Steel': '🔩', 'Fairy': '🧚‍♀️'
}

# ⚡ UPDATED FORMAT: Status effects rearranged to [PSN ☠️]
STATUS_EMOJIS = {
    "BRN": "BRN 🔥", "PAR": "PAR ⚡", "PSN": "PSN ☠️", 
    "FRZ": "FRZ 🧊", "SLP": "SLP 💤"
}

TYPE_CHART = {
    'Normal': {'Rock': 0.5, 'Steel': 0.5, 'Ghost': 0.0},
    'Fire': {'Fire': 0.5, 'Water': 0.5, 'Grass': 2.0, 'Ice': 2.0, 'Bug': 2.0, 'Rock': 0.5, 'Dragon': 0.5, 'Steel': 2.0},
    'Water': {'Fire': 2.0, 'Water': 0.5, 'Grass': 0.5, 'Ground': 2.0, 'Rock': 2.0, 'Dragon': 0.5},
    'Electric': {'Water': 2.0, 'Electric': 0.5, 'Grass': 0.5, 'Ground': 0.0, 'Flying': 2.0, 'Dragon': 0.5},
    'Grass': {'Fire': 0.5, 'Water': 2.0, 'Grass': 0.5, 'Poison': 0.5, 'Ground': 2.0, 'Flying': 0.5, 'Bug': 0.5, 'Rock': 2.0, 'Dragon': 0.5, 'Steel': 0.5},
    'Ice': {'Fire': 0.5, 'Water': 0.5, 'Grass': 2.0, 'Ice': 0.5, 'Ground': 2.0, 'Flying': 2.0, 'Dragon': 2.0, 'Steel': 0.5},
    'Fighting': {'Normal': 2.0, 'Ice': 2.0, 'Poison': 0.5, 'Flying': 0.5, 'Psychic': 0.5, 'Bug': 0.5, 'Rock': 2.0, 'Ghost': 0.0, 'Dark': 2.0, 'Steel': 2.0, 'Fairy': 0.5},
    'Poison': {'Grass': 2.0, 'Poison': 0.5, 'Ground': 0.5, 'Rock': 0.5, 'Ghost': 0.5, 'Steel': 0.0, 'Fairy': 2.0},
    'Ground': {'Fire': 2.0, 'Electric': 2.0, 'Grass': 0.5, 'Poison': 2.0, 'Flying': 0.0, 'Bug': 0.5, 'Rock': 2.0, 'Steel': 2.0},
    'Flying': {'Electric': 0.5, 'Grass': 2.0, 'Fighting': 2.0, 'Bug': 2.0, 'Rock': 0.5, 'Steel': 0.5},
    'Psychic': {'Fighting': 2.0, 'Poison': 2.0, 'Psychic': 0.5, 'Dark': 0.0, 'Steel': 0.5},
    'Bug': {'Fire': 0.5, 'Grass': 2.0, 'Fighting': 0.5, 'Poison': 0.5, 'Flying': 0.5, 'Psychic': 2.0, 'Ghost': 0.5, 'Dark': 2.0, 'Steel': 0.5, 'Fairy': 0.5},
    'Rock': {'Fire': 2.0, 'Ice': 2.0, 'Fighting': 0.5, 'Ground': 0.5, 'Flying': 2.0, 'Bug': 2.0, 'Steel': 0.5},
    'Ghost': {'Normal': 0.0, 'Psychic': 2.0, 'Ghost': 2.0, 'Dark': 0.5},
    'Dragon': {'Dragon': 2.0, 'Steel': 0.5, 'Fairy': 0.0},
    'Dark': {'Fighting': 0.5, 'Psychic': 2.0, 'Ghost': 2.0, 'Dark': 0.5, 'Fairy': 0.5},
    'Steel': {'Fire': 0.5, 'Water': 0.5, 'Electric': 0.5, 'Ice': 2.0, 'Rock': 2.0, 'Steel': 0.5, 'Fairy': 2.0},
    'Fairy': {'Fire': 0.5, 'Fighting': 2.0, 'Poison': 0.5, 'Dragon': 2.0, 'Dark': 2.0, 'Steel': 0.5}
}

# --- INTELLIGENT THREADED RATE LIMIT SHIELDS ---
def safe_answer(bot, call_id, text="", show_alert=False):
    try: bot.answer_callback_query(call_id, text, show_alert=show_alert)
    except Exception: pass

_edit_lock = threading.Lock()
_edit_generation = {}  # message_id -> generation counter, so a stale retry can't clobber a newer render

def _bump_generation(message_id):
    with _edit_lock:
        gen = _edit_generation.get(message_id, 0) + 1
        _edit_generation[message_id] = gen
        return gen

def _is_current(message_id, generation):
    with _edit_lock:
        return _edit_generation.get(message_id) == generation

def clear_edit_tracking(message_id):
    """Call when a battle/message is done, so the generation dict doesn't grow forever."""
    with _edit_lock:
        _edit_generation.pop(message_id, None)

def _threaded_edit(bot, text, chat_id, message_id, reply_markup, retry_after, generation):
    time.sleep(retry_after)
    if not _is_current(message_id, generation):
        return  # a newer render already went out while we were waiting — drop this stale one
    _do_edit(bot, text, chat_id, message_id, reply_markup, generation)

def _do_edit(bot, text, chat_id, message_id, reply_markup, generation):
    try:
        bot.edit_message_text(text, chat_id, message_id, reply_markup=reply_markup, parse_mode="MarkdownV2")
    except Exception as e:
        err_str = str(e).lower()
        if "message is not modified" in err_str: return

        if "429" in err_str or "too many requests" in err_str:
            retry_after = 3
            if hasattr(e, 'result_json') and e.result_json and 'parameters' in e.result_json:
                retry_after = e.result_json['parameters'].get('retry_after', 3)
            elif "retry after" in err_str:
                try: retry_after = int(err_str.split("retry after ")[1].split()[0])
                except: pass

            logger.warning(f"Telegram Limit Hit (429). Threading background UI retry in {retry_after}s...")
            # Keep retrying (with the latest retry_after) instead of giving up after one attempt.
            threading.Thread(
                target=_threaded_edit,
                args=(bot, text, chat_id, message_id, reply_markup, retry_after, generation),
                daemon=True,
            ).start()
        else:
            logger.error(f"UI Update error: {e}")

def safe_edit(bot, text, chat_id, message_id, reply_markup=None):
    # Every call supersedes any retry threads still in flight for this message,
    # so a slow 429 retry can never overwrite a more recent battle state.
    generation = _bump_generation(message_id)
    _do_edit(bot, text, chat_id, message_id, reply_markup, generation)

# --- HELPERS ---
def clean_name(name):
    if not name: return "Trainer"
    return name.replace('\n', ' ').replace('\r', '').replace('*', '').replace('_', '').strip()

def get_faster_player(b):
    p1_spd = b["p1_team"][b["p1_idx"]]["spd"]
    if b["p1_team"][b["p1_idx"]].get("status") == "PAR": p1_spd = int(p1_spd * 0.5)

    p2_spd = b["p2_team"][b["p2_idx"]]["spd"]
    if b["p2_team"][b["p2_idx"]].get("status") == "PAR": p2_spd = int(p2_spd * 0.5)

    return "p1" if p1_spd >= p2_spd else "p2"

def challenge_timeout(bot, chat_id, message_id):
    chal = pending_challenges.pop(message_id, None)
    if chal:
        p1_name = escape_md(chal["name"])
        p1_id = chal["p1_id"]
        mention = f"[{p1_name}](tg://user?id={p1_id})"
        safe_edit(bot, f"*{mention}’s Cʜᴀʟʟᴇɴɢᴇ Hᴀs Exᴘɪʀᴇᴅ ⏳*", chat_id, message_id)

def end_battle(battle_id, bot=None, chat_id=None):
    b = pvp_battles.pop(battle_id, None)
    clear_edit_tracking(battle_id)
    if b:
        if "timer" in b and b["timer"]: b["timer"].cancel()
        if bot and "tracked_msgs" in b:
            for item in b["tracked_msgs"]:
                try:
                    if isinstance(item, tuple): bot.delete_message(item[0], item[1])
                    elif chat_id: bot.delete_message(chat_id, item)
                except: pass

def battle_timeout(bot, chat_id, battle_id):
    b = pvp_battles.get(battle_id)
    if b:
        turn = b["current_turn"]
        if turn == "processing": return 
        
        loser_name = b.get(turn + "_name", "Player")
        winner_name = b["p2_name"] if turn == "p1" else b["p1_name"]
        loser_id = b[turn + "_id"]
        winner_id = b["p2_id"] if turn == "p1" else b["p1_id"]
        
        pvp_battles.pop(battle_id, None)
        clear_edit_tracking(battle_id)
        
        try: db.update_battle_stats(loser_id, is_win=False)
        except Exception as e: logger.error(f"Stat Save Error: {e}")
        
        loser_mention = f"[{escape_md(loser_name)}](tg://user?id={loser_id})"
        win_mention = f"[{escape_md(winner_name)}](tg://user?id={winner_id})"
        
        text = f"⏳ *{loser_mention} ʀᴀɴ ᴏᴜᴛ ᴏғ ᴛɪᴍᴇ\\!*\n\n🏆 *{win_mention} ᴅᴇғᴇᴀᴛᴇᴅ {loser_mention} ɪɴ ᴛʜᴇ ʙᴀᴛᴛʟᴇ\\!*"
        safe_edit(bot, text, chat_id, battle_id)
        
        if LOG_GROUP_ID:
            try: bot.send_message(LOG_GROUP_ID, f"⏳ *Timeout:* {win_mention} ᴅᴇғᴇᴀᴛᴇᴅ {loser_mention} ɪɴ ᴛʜᴇ ʙᴀᴛᴛʟᴇ\\!", parse_mode="MarkdownV2")
            except: pass
            
        end_battle(battle_id, bot, chat_id)

def get_type_multiplier(move_type, defender_types_str):
    multiplier = 1.0
    defender_types = defender_types_str.split("/")
    for def_type in defender_types:
        if move_type in TYPE_CHART and def_type in TYPE_CHART[move_type]:
            multiplier *= TYPE_CHART[move_type][def_type]
    return multiplier

def is_in_battle(user_id):
    for b in pvp_battles.values():
        if user_id in (b["p1_id"], b["p2_id"]): return True
    return False

def is_in_pending_challenge(user_id):
    for chal in pending_challenges.values():
        if chal["p1_id"] == user_id or chal["p2_id"] == user_id: return True
    return False

def get_hp_bar(current, maximum, length=10):
    if maximum <= 0: return "▒" * length
    filled = int(round((current / maximum) * length))
    if current > 0 and filled == 0: filled = 1
    return escape_md("█" * filled + "▒" * (length - filled))

def format_types(types_str):
    types_list = types_str.split('/')
    formatted = [f"{t} {TYPE_EMOJIS.get(t, '')}".strip() for t in types_list]
    return " / ".join(formatted)

def get_form_icon(name, is_mega):
    if not is_mega: return ""
    if "Primal" in name: return " 🌋"
    if "Zacian" in name: return " 🗡️"
    if "Zamazenta" in name: return " 🛡️"
    if "Shadow Rider" in name: return " 🐎"
    if "Ash-Greninja" in name: return " 💧"
    if "Arceus (" in name: return " ✨"
    return " 💎"

def apply_nature(p, n):
    if n == "Adamant": p["atk"] = int(p["atk"] * 1.1)
    elif n == "Jolly": p["spd"] = int(p["spd"] * 1.1)
    elif n == "Modest": p["atk"] = int(p["atk"] * 0.9)
    elif n == "Timid": 
        p["spd"] = int(p["spd"] * 1.1)
        p["atk"] = int(p["atk"] * 0.9)
    elif n == "Bold":
        p["def"] = int(p["def"] * 1.1)
        p["atk"] = int(p["atk"] * 0.9)
    elif n == "Calm": p["atk"] = int(p["atk"] * 0.9)
    elif n == "Impish": p["def"] = int(p["def"] * 1.1)
    return p

# --- UI RENDERERS ---
def update_challenge_message(bot, chat_id, message_id, chal):
    p1_name = escape_md(chal["name"])
    p2_name = escape_md(chal["p2_name"])
    p1_id = chal["p1_id"]
    p2_id = chal["p2_id"]
    size = chal["size"]
    
    mode_str = chal["mode"]
    if mode_str == "Mix": mode_text = "Mɪx"
    elif mode_str == "6ls": mode_text = "6ʟs"
    elif mode_str == "0ls": mode_text = "0ʟs"
    else: mode_text = escape_md(mode_str)
    
    sw_text = "Oɴ" if chal["can_switch"] else "Oғғ"
    status_text = "Oɴ" if chal.get("status_effects", True) else "Oғғ"
    
    act_mention = f"[{p1_name}](tg://user?id={p1_id})"
    def_mention = f"[{p2_name}](tg://user?id={p2_id})"
    
    text = (f"*{act_mention} ᴄʜᴀʟʟᴇɴɢᴇᴅ {def_mention} ᴛᴏ ᴀ {size} ᴠ {size} Rᴀɴᴅᴏᴍ Bᴀᴛᴛʟᴇ ❗❗*\n\n"
            f"⚙️ Mᴏᴅᴇ: {mode_text}\n"
            f"🔄 Sᴡɪᴛᴄʜɪɴɢ: {sw_text}\n"
            f"✨ Sᴛᴀᴛᴜs Eғғᴇᴄᴛs: {status_text}")
    
    kb = types.InlineKeyboardMarkup()
    kb.add(types.InlineKeyboardButton("⚙️ Sᴇᴛᴛɪɴɢs", callback_data=f"pvp_settings_{chal['p1_id']}"))
    kb.add(
        types.InlineKeyboardButton("✔️ Aᴄᴄᴇᴘᴛ", callback_data=f"pvp_accept_{chal['p1_id']}_{chal['p2_id']}"),
        types.InlineKeyboardButton("✖️ Dᴇᴄʟɪɴᴇ", callback_data=f"pvp_decline_{chal['p1_id']}_{chal['p2_id']}")
    )
    safe_edit(bot, text, chat_id, message_id, reply_markup=kb)

def render_settings_ui(bot, chat_id, message_id, chal):
    text = f"⚙️ *Bᴀᴛᴛʟᴇ Sᴇᴛᴛɪɴɢs*\n\nCᴏɴғɪɢᴜʀᴇ ᴛʜᴇ ʀᴜʟᴇs ғᴏʀ ᴛʜɪs ᴍᴀᴛCH:"
    kb = types.InlineKeyboardMarkup(row_width=3)
    
    m_0 = "✅ 0ʟs" if chal['mode'] == "0ls" else "0ʟs"
    m_6 = "✅ 6ʟs" if chal['mode'] == "6ls" else "6ʟs"
    m_m = "✅ Mɪx" if chal['mode'] == "Mix" else "Mɪx"
    kb.row(types.InlineKeyboardButton(m_0, callback_data=f"pvp_setm_{chal['p1_id']}_0ls"),
           types.InlineKeyboardButton(m_6, callback_data=f"pvp_setm_{chal['p1_id']}_6ls"),
           types.InlineKeyboardButton(m_m, callback_data=f"pvp_setm_{chal['p1_id']}_Mix"))
    
    sz_btns = [types.InlineKeyboardButton(f"✅ {s}" if chal['size'] == s else str(s), callback_data=f"pvp_sets_{chal['p1_id']}_{s}") for s in range(1, 7)]
    kb.add(*sz_btns)
    
    sw_lbl = "🔄 Sᴡɪᴛᴄʜ: Oɴ" if chal['can_switch'] else "🚫 Sᴡɪᴛᴄʜ: Oғғ"
    kb.row(types.InlineKeyboardButton(sw_lbl, callback_data=f"pvp_setsw_{chal['p1_id']}"))
    
    status_lbl = "Sᴛᴀᴛᴜs Eғғᴇᴄᴛs: 🟢 Oɴ" if chal.get("status_effects", True) else "Sᴛᴀᴛᴜs Eғғᴇᴄᴛs: 🔴 Oғғ"
    kb.row(types.InlineKeyboardButton(status_lbl, callback_data=f"pvp_setstatus_{chal['p1_id']}"))
    
    kb.row(types.InlineKeyboardButton("💾 Sᴀᴠᴇ Sᴇᴛᴛɪɴɢs", callback_data=f"pvp_setsave_{chal['p1_id']}"))
    kb.row(types.InlineKeyboardButton("🔙 Bᴀᴄᴋ", callback_data=f"pvp_setback_{chal['p1_id']}"))
    
    safe_edit(bot, text, chat_id, message_id, reply_markup=kb)

def render_pvp_ui(bot, chat_id, battle_id):
    if battle_id not in pvp_battles: return
    b = pvp_battles[battle_id]
    turn = b["current_turn"]
    if turn == "processing": return
    
    if "timer" in b and b["timer"]: b["timer"].cancel()
    b["timer"] = threading.Timer(60.0, battle_timeout, args=(bot, chat_id, battle_id))
    b["timer"].start()
    
    active_name, active_poke = (b["p1_name"], b["p1_team"][b["p1_idx"]]) if turn == "p1" else (b["p2_name"], b["p2_team"][b["p2_idx"]])
    def_name, def_poke = (b["p2_name"], b["p2_team"][b["p2_idx"]]) if turn == "p1" else (b["p1_name"], b["p1_team"][b["p1_idx"]])
    
    act_id = b["p1_id"] if turn == "p1" else b["p2_id"]
    def_id = b["p2_id"] if turn == "p1" else b["p1_id"]
    
    act_mention = f"[{escape_md(active_name)}](tg://user?id={act_id})"
    def_mention = f"[{escape_md(def_name)}](tg://user?id={def_id})"
    
    # ⚡ UPDATED FORMAT: Removed the BOLD Markdown `*` wrapping around the entire battle log.
    log_content = f"{escape_md(b['log'].strip())}" if b['log'] else "Tʜᴇ ʙᴀᴛᴛʟᴇ ʙᴇɢɪɴs\\!"
    
    # ⚡ UPDATED FORMAT: Safely wrap status brackets so escape_md prints them out correctly as [PSN ☠️]
    act_status = f"\n \\[{STATUS_EMOJIS.get(active_poke['status'], '')}\\]" if active_poke.get('status') else ""
    def_status = f"\n \\[{STATUS_EMOJIS.get(def_poke['status'], '')}\\]" if def_poke.get('status') else ""
    
    act_mega = get_form_icon(active_poke['name'], active_poke.get("is_mega"))
    def_mega = get_form_icon(def_poke['name'], def_poke.get("is_mega"))

    ui_text = (
        f"{log_content}\n\n"
        f"*{def_mention}'s {escape_md(def_poke['name'])}{def_mega}*\n"
        f" \\[{escape_md(format_types(def_poke['types']))}\\]\n"
        f"  ⤷ Lv\\. 100  •  HP {int(def_poke['hp'])}/{int(def_poke['max_hp'])}\n"
        f"`{get_hp_bar(def_poke['hp'], def_poke['max_hp'])}`{escape_md(def_status)}\n\n"
        f"Current turn: {act_mention}\n"
        f"*{act_mention}'s {escape_md(active_poke['name'])}{act_mega} \\[{escape_md(format_types(active_poke['types']))}\\]*\n"
        f"  ⤷ Lv\\. 100  •  HP {int(active_poke['hp'])}/{int(active_poke['max_hp'])}\n"
        f"`{get_hp_bar(active_poke['hp'], active_poke['max_hp'])}`{escape_md(act_status)}\n\n"
    )

    kb = types.InlineKeyboardMarkup(row_width=2)
    
    if b["state"] == "menu":
        moves_block = ""
        move_buttons = []
        
        for i, m in enumerate(active_poke["moves"]):
            m_name = escape_md(m['name'])
            m_type = m['type']
            m_emoji = TYPE_EMOJIS.get(m_type, '')
            m_type_display = escape_md(f"{m_type} {m_emoji}".strip())
            m_pow = m.get('power', 0)
            m_acc = m.get('acc', 100)
            
            moves_block += f" *{m_name} \\[{m_type_display}\\]*\n  ⤷ Power: {m_pow}, Accuracy: {m_acc}\n"
            move_buttons.append(types.InlineKeyboardButton(f"{m['name']}", callback_data=f"pvp_move_{battle_id}_{turn}_{i}"))
            
        ui_text += moves_block
        
        if len(move_buttons) == 4:
            kb.row(move_buttons[0], move_buttons[1])
            kb.row(move_buttons[2], move_buttons[3])
        else:
            for btn in move_buttons: kb.add(btn)
        
        if active_poke.get("can_mega") and not active_poke.get("is_mega"):
            if active_poke["name"] in ["Groudon", "Kyogre"]: btn_lbl = "🌋 Primal Reversion"
            elif active_poke["name"] == "Zacian": btn_lbl = "🗡️ Crowned Form"
            elif active_poke["name"] == "Zamazenta": btn_lbl = "🛡️ Crowned Form"
            elif active_poke["name"] == "Calyrex": btn_lbl = "🐎 Mount Spectrier"
            elif active_poke["name"] == "Greninja": btn_lbl = "💧 Form Change"
            else: btn_lbl = "💎 Mega Evolve"
            
            kb.row(types.InlineKeyboardButton(btn_lbl, callback_data=f"pvp_mega_{battle_id}_{turn}"))
            
        kb.row(types.InlineKeyboardButton("🔄 Sᴡɪᴛᴄʜ", callback_data=f"pvp_swmenu_{battle_id}_{turn}"),
               types.InlineKeyboardButton("🏃 Rᴜɴ", callback_data=f"pvp_confirmrun_{battle_id}_{turn}"))
               
    elif b["state"] == "mega_xy_choice":
        ui_text += f" Choose a Mega Evolution form:\n"
        kb.row(types.InlineKeyboardButton("Mega Form X", callback_data=f"pvp_mega_{battle_id}_{turn}_X"),
               types.InlineKeyboardButton("Mega Form Y", callback_data=f"pvp_mega_{battle_id}_{turn}_Y"))
        kb.row(types.InlineKeyboardButton("🔙 Bᴀᴄᴋ", callback_data=f"pvp_back_{battle_id}_{turn}"))

    elif b["state"] == "mega_lucario_choice":
        ui_text += f" Choose a Mega Evolution form:\n"
        kb.row(types.InlineKeyboardButton("Standard Mega", callback_data=f"pvp_mega_{battle_id}_{turn}_Standard"),
               types.InlineKeyboardButton("Mega Form Z", callback_data=f"pvp_mega_{battle_id}_{turn}_Z"))
        kb.row(types.InlineKeyboardButton("🔙 Bᴀᴄᴋ", callback_data=f"pvp_back_{battle_id}_{turn}"))

    elif b["state"] == "mega_greninja_choice":
        ui_text += f" Choose a Form Change:\n"
        kb.row(types.InlineKeyboardButton("Mega Greninja", callback_data=f"pvp_mega_{battle_id}_{turn}_Mega"),
               types.InlineKeyboardButton("Ash-Greninja", callback_data=f"pvp_mega_{battle_id}_{turn}_Ash"))
        kb.row(types.InlineKeyboardButton("🔙 Bᴀᴄᴋ", callback_data=f"pvp_back_{battle_id}_{turn}"))

    elif b["state"] in ["switch_menu", "force_switch"]:
        if b["state"] == "switch_menu":
            ui_text += f"\n🔄 *Wʜɪᴄʜ Pᴏᴋᴇ́ᴍᴏɴ Wɪʟʟ Yᴏᴜ Sᴡɪᴛᴄʜ Tᴏ?*\n"
        else:
            ui_text += f"\n *Cʜᴏᴏsᴇ A Pᴏᴋᴇ́ᴍᴏɴ Tᴏ Sᴇɴᴅ Oᴜᴛ\\!*\n"
            
        btns = [types.InlineKeyboardButton(f"{i+1}" if p['hp'] > 0 else f"✖️ {i+1}", callback_data=f"pvp_dosw_{battle_id}_{turn}_{i}") for i, p in enumerate(b[turn + "_team"])]
        
        for i in range(0, len(btns), 2):
            if i + 1 < len(btns): kb.add(btns[i], btns[i+1])
            else: kb.add(btns[i])
        
        kb.row(types.InlineKeyboardButton("📋 Vɪᴇᴡ Tᴇᴀᴍ", callback_data=f"pvp_viewteam_{battle_id}_{turn}"))
        if b["state"] == "switch_menu": 
            kb.row(types.InlineKeyboardButton("🔙 Bᴀᴄᴋ", callback_data=f"pvp_back_{battle_id}_{turn}"))
            
    elif b["state"] == "run_confirm":
        ui_text += f" *⚠️ Aʀᴇ ʏᴏᴜ sᴜʀᴇ ʏᴏᴜ ᴡᴀɴᴛ ᴛᴏ ғʟᴇᴇ ᴛʜᴇ ʙᴀᴛᴛʟᴇ?*\n"
        kb.row(types.InlineKeyboardButton("✅ Cᴏɴғɪʀᴍ Fʟᴇᴇ", callback_data=f"pvp_run_{battle_id}_{turn}"),
               types.InlineKeyboardButton("❌ Cᴀɴᴄᴇʟ", callback_data=f"pvp_back_{battle_id}_{turn}"))

    safe_edit(bot, ui_text, chat_id, battle_id, reply_markup=kb)

# --- COMMAND HANDLERS ---
def handle_myteam_command(bot, message):
    user_id = message.from_user.id
    battle_to_show = None
    turn = None
    
    for b_id, b in pvp_battles.items():
        if b["p1_id"] == user_id:
            battle_to_show = b
            turn = "p1"
            break
        elif b["p2_id"] == user_id:
            battle_to_show = b
            turn = "p2"
            break
    
    if not battle_to_show:
        return bot.reply_to(message, escape_md("You are not currently in a PvP battle."), parse_mode="MarkdownV2")
        
    lines = ["🎒 *Yᴏᴜʀ Cᴜʀʀᴇɴᴛ PᴠP Tᴇᴀᴍ:*\n"]
    for i, p in enumerate(battle_to_show[turn + '_team']):
        types_raw = p['types'].split('/')
        type_str = " / ".join([f"{t.strip()} {TYPE_EMOJIS.get(t.strip(), '')}" for t in types_raw])
        
        status_icon = '💀' if p['hp'] <= 0 else ('💤' if p.get('status') == 'SLP' else ('🧊' if p.get('status') == 'FRZ' else ('🔥' if p.get('status') == 'BRN' else ('☠️' if p.get('status') == 'PSN' else ('⚡' if p.get('status') == 'PAR' else '')))))
        
        lines.append(f"*{i+1}\\. {escape_md(p['name'])} \\[{escape_md(type_str)}\\]* {status_icon}")
        lines.append(f"🌿 *Nᴀᴛᴜʀᴇ:* {escape_md(p['nature'])}")
        lines.append(f"⚔️ *Mᴏᴠᴇs:*")
        
        for m in p['moves']:
            m_name = escape_md(m['name'])
            m_type = f"{m['type']} {TYPE_EMOJIS.get(m['type'], '')}"
            m_type_md = escape_md(m_type)
            pow_str = escape_md(str(m.get('power', 0)))
            acc_str = escape_md(str(m.get('acc', 100)))
            lines.append(f"  \\- {m_name} \\[{m_type_md}\\] \\(Pow: {pow_str}, Acc: {acc_str}\\)")
        lines.append("") 
    
    team_text = "\n".join(lines)
    
    try:
        sent_msg = bot.send_message(user_id, team_text, parse_mode="MarkdownV2")
        battle_to_show.setdefault("tracked_msgs", []).append((user_id, sent_msg.message_id))
        bot.reply_to(message, escape_md("✅ Detailed team sent to your DMs! It will auto-delete when the battle ends."), parse_mode="MarkdownV2")
    except Exception as e:
        logger.error(f"Myteam DM error: {e}")
        bot.reply_to(message, escape_md("❌ Please start the bot in DM first to receive your team list!"), parse_mode="MarkdownV2")

def handle_pvp_command(bot, message):
    if not message.reply_to_message: 
        return bot.reply_to(message, escape_md("⚠️ Reply to a user to challenge them!"))
        
    target = message.reply_to_message
    
    if target.from_user.is_bot or target.sender_chat:
        err_msg = "❌ *Iɴᴠᴀʟɪᴅ Tᴀʀɢᴇᴛ\\!*\n*Yᴏᴜ Cᴀɴ Oɴʟʏ Cʜᴀʟʟᴇɴɢᴇ Rᴇᴀʟ Tʀᴀɪɴᴇʀs\\.*"
        return bot.reply_to(message, err_msg, parse_mode="MarkdownV2")
        
    p1_id = message.from_user.id
    p2_id = target.from_user.id
    
    if p1_id == p2_id: 
        return bot.reply_to(message, escape_md("❌ You can't challenge yourself!"))
        
    if not db.get_user(p1_id):
        return bot.reply_to(message, escape_md("⚠️ You need to /start the bot first!"))
        
    if not db.get_user(p2_id):
        target_name = escape_md(clean_name(target.from_user.first_name))
        err_msg = f"*🛰️ [{target_name}](tg://user?id={p2_id}) hasn't registered yet\\!*\n*They need to /start the bot to play❗❗*"
        
        kb = types.InlineKeyboardMarkup()
        bot_username = bot.get_me().username
        kb.add(types.InlineKeyboardButton("Start me ❗", url=f"https://t.me/{bot_username}?start=1"))
        
        return bot.reply_to(message, err_msg, reply_markup=kb, parse_mode="MarkdownV2")
    
    if is_in_battle(p1_id) or is_in_battle(p2_id): 
        err_msg = "❌ *Cʜᴀʟʟᴇɴɢᴇ Fᴀɪʟᴇᴅ\\!*\n*Oɴᴇ Oғ Tʜᴇ Tʀᴀɪɴᴇʀs Iꜱ Aʟʀᴇᴀᴅʏ Iɴ A Bᴀᴛᴛʟᴇ\\.*"
        return bot.reply_to(message, err_msg, parse_mode="MarkdownV2")

    to_remove = []
    for mid, c in list(pending_challenges.items()):
        if p1_id in [c["p1_id"], c["p2_id"]]:
            c["timer"].cancel()
            to_remove.append(mid)
            err_msg = "❌ *Cʜᴀʟʟᴇɴɢᴇ Cᴀɴᴄᴇʟʟᴇᴅ\\!*\n*A Nᴇᴡ Cʜᴀʟʟᴇɴɢᴇ Wᴀs Sᴛᴀʀᴛᴇᴅ\\.*"
            safe_edit(bot, err_msg, c["chat_id"], mid)
            
    for mid in to_remove: pending_challenges.pop(mid, None)

    if is_in_pending_challenge(p2_id): 
        err_msg = "❌ *Cʜᴀʟʟᴇɴɢᴇ Fᴀɪʟᴇᴅ\\!*\n*Oɴᴇ Oғ Tʜᴇ Tʀᴀɪɴᴇʀs Iꜱ Aʟʀᴇᴀᴅʏ Iɴ A Bᴀᴛᴛʟᴇ\\.*"
        return bot.reply_to(message, err_msg, parse_mode="MarkdownV2")

    mode, size, can_switch, status_effects = db.get_pvp_settings(p1_id)
    sent = bot.reply_to(message, escape_md("🔄 Loading challenge..."), parse_mode="MarkdownV2")
    
    timer = threading.Timer(60.0, challenge_timeout, args=(bot, message.chat.id, sent.message_id))
    timer.start()
    
    chal = {"name": clean_name(message.from_user.first_name), "p2_name": clean_name(target.from_user.first_name),
            "timer": timer, "p1_id": p1_id, "p2_id": p2_id, "chat_id": message.chat.id, 
            "mode": mode, "size": size, "can_switch": can_switch, "status_effects": status_effects}
    
    pending_challenges[sent.message_id] = chal
    update_challenge_message(bot, message.chat.id, sent.message_id, chal)

# --- CALLBACK HANDLER ---
def handle_pvp_callback(bot, call):
    try:
        parts = call.data.split("_")
        action = parts[1]
        
        if action == "settings":
            chal = pending_challenges.get(call.message.message_id)
            if chal and call.from_user.id == chal["p1_id"]: render_settings_ui(bot, call.message.chat.id, call.message.message_id, chal)
            return
        elif action == "setm":
            chal = pending_challenges.get(call.message.message_id)
            if chal and call.from_user.id == chal["p1_id"]: 
                chal["mode"] = parts[3]; render_settings_ui(bot, call.message.chat.id, call.message.message_id, chal)
            return
        elif action == "sets":
            chal = pending_challenges.get(call.message.message_id)
            if chal and call.from_user.id == chal["p1_id"]: 
                chal["size"] = int(parts[3]); render_settings_ui(bot, call.message.chat.id, call.message.message_id, chal)
            return
        elif action == "setsw":
            chal = pending_challenges.get(call.message.message_id)
            if chal and call.from_user.id == chal["p1_id"]: 
                chal["can_switch"] = not chal["can_switch"]; render_settings_ui(bot, call.message.chat.id, call.message.message_id, chal)
            return
        elif action == "setstatus":
            chal = pending_challenges.get(call.message.message_id)
            if chal and call.from_user.id == chal["p1_id"]: 
                chal["status_effects"] = not chal.get("status_effects", True)
                render_settings_ui(bot, call.message.chat.id, call.message.message_id, chal)
            return
        elif action == "setsave":
            chal = pending_challenges.get(call.message.message_id)
            if chal and call.from_user.id == chal["p1_id"]: 
                db.update_pvp_settings(chal["p1_id"], chal["mode"], chal["size"], chal["can_switch"], chal.get("status_effects", True))
                safe_answer(bot, call.id, "✅ Defaults Saved!", show_alert=True)
            return
        elif action == "setback":
            chal = pending_challenges.get(call.message.message_id)
            if chal and call.from_user.id == chal["p1_id"]: 
                update_challenge_message(bot, call.message.chat.id, call.message.message_id, chal)
            return

        elif action == "decline":
            p1_id, p2_id = int(parts[2]), int(parts[3])
            if call.from_user.id != p2_id: return safe_answer(bot, call.id, "❌ Not your challenge!", show_alert=True)
            
            battle_id = call.message.message_id
            chal_data = pending_challenges.pop(battle_id, None)
            
            if chal_data: chal_data["timer"].cancel()
            safe_edit(bot, "❌ *Cʜᴀʟʟᴇɴɢᴇ Dᴇᴄʟɪɴᴇᴅ\\.*", call.message.chat.id, battle_id)
            safe_answer(bot, call.id, "Challenge declined.")
            return

        if action == "accept":
            p1_id, p2_id = int(parts[2]), int(parts[3])
            if call.from_user.id != p2_id: return safe_answer(bot, call.id, "❌ Not your challenge!", show_alert=True)
            
            battle_id = call.message.message_id
            chal_data = pending_challenges.pop(battle_id, None)
            
            if not chal_data: return safe_answer(bot, call.id, "This challenge has expired or was already answered!")
            
            chal_data["timer"].cancel()
            safe_answer(bot, call.id, "Preparing the arena...", show_alert=False)

            if LOG_GROUP_ID:
                try: 
                    log_msg = f"⚔️ 【PᴠP】 {escape_md(chal_data['name'])} 🆚 {escape_md(chal_data['p2_name'])}"
                    bot.send_message(LOG_GROUP_ID, log_msg, parse_mode="MarkdownV2")
                except: pass
            
            def setup():
                try:
                    safe_edit(bot, "🔄 *Drafting Teams\\.\\.\\.*", call.message.chat.id, battle_id)
                    
                    t1_draft = asyncio.run(generate_random_team(chal_data["mode"], chal_data["size"]))
                    t2_draft = asyncio.run(generate_random_team(chal_data["mode"], chal_data["size"]))
                    
                    # 🛡️ FIX: Safety check if PokeAPI completely timed out and returned None
                    if not t1_draft or not t2_draft:
                        logger.error("PvP Fetch Error: generate_random_team returned None.")
                        safe_edit(bot, "❌ *Aᴘɪ ᴛɪᴍᴇᴏᴜᴛ\\. Tʜᴇ sᴇʀᴠᴇʀ ᴄᴏᴜʟᴅ ɴᴏᴛ ɢᴇɴᴇʀᴀᴛᴇ ᴛᴇᴀᴍs ғᴀsᴛ ᴇɴᴏᴜɢʜ\\. Pʟᴇᴀsᴇ ᴛʀʏ ᴀɢᴀɪɴ\\.*", call.message.chat.id, battle_id)
                        return

                    t1_final, t2_final = [], []
                    
                    for draft_team, final_team in [(t1_draft, t1_final), (t2_draft, t2_final)]:
                        for p_cached in draft_team: 
                            p = copy.deepcopy(p_cached) 
                            
                            base_hp = p.get("max_hp", 50)
                            base_atk = p.get("atk", 50)
                            base_def = p.get("def", 50)
                            base_spd = p.get("spd", 50)

                            p["base_atk"] = base_atk
                            p["base_def"] = base_def
                            p["base_spd"] = base_spd

                            if base_hp <= 1: p["max_hp"] = 1 
                            else: p["max_hp"] = int((2 * base_hp) + 31 + 21 + 110) 
                                
                            p["hp"] = p["max_hp"]
                            p["atk"] = int((2 * base_atk) + 31 + 21 + 5)
                            p["def"] = int((2 * base_def) + 31 + 21 + 5)
                            p["spd"] = int((2 * base_spd) + 31 + 21 + 5)

                            n = random.choice(NATURES)
                            p["nature"] = n
                            p = apply_nature(p, n)
                            
                            if p["name"] == "Arceus":
                                arc_type = random.choice(list(TYPE_CHART.keys()))
                                if arc_type != 'Normal':
                                    p["name"] = f"Arceus ({arc_type})"
                                    p["types"] = arc_type
                                    for m in p["moves"]:
                                        if m["name"].lower() in ["judgment", "judgement"]: m["type"] = arc_type
                            
                            custom_megas = [
                                "Pyroar", "Malamar", "Dragalge", "Eelektross", "Froslass", 
                                "Clefable", "Chimecho", "Staraptor", "Heatran", "Darkrai", 
                                "Meowstic", "Crabominable", "Dragonite", "Meganium", 
                                "Emboar", "Falinks", "Zeraora"
                            ]
                            special_forms = ["Charizard", "Mewtwo", "Raichu", "Lucario", "Greninja", "Groudon", "Kyogre", "Zacian", "Zamazenta", "Calyrex"] + custom_megas
                            
                            p["can_mega"] = any(m[1].split("-")[0].lower() == p["name"].lower() for m in MEGA_POKEMON) or p["name"] in special_forms
                            p["is_mega"] = False
                            
                            for m in p["moves"]:
                                if "status_chance" not in m:
                                    m["status_chance"] = 0
                                    m["status_type"] = None
                                if not chal_data.get("status_effects", True):
                                    m["status_chance"] = 0
                                    m["status_type"] = None
                            
                            final_team.append(p)
                            
                    pvp_battles[battle_id] = {
                        "p1_id": chal_data["p1_id"], "p1_name": chal_data["name"], "p1_team": t1_final, "p1_idx": 0,
                        "p2_id": chal_data["p2_id"], "p2_name": chal_data["p2_name"], "p2_team": t2_final, "p2_idx": 0,
                        "can_switch": chal_data["can_switch"], "state": "menu", "log": "", "timer": None,
                        "last_edit": 0, "processing_start": 0
                    }
                    
                    pvp_battles[battle_id]["current_turn"] = get_faster_player(pvp_battles[battle_id])
                    faster_name = pvp_battles[battle_id][pvp_battles[battle_id]['current_turn'] + '_name']
                    pvp_battles[battle_id]["log"] = f"⚡ {faster_name}'s speed allows them to move first!"
                    
                    render_pvp_ui(bot, call.message.chat.id, battle_id)
                except Exception as e:
                    logger.error(f"PvP Fetch Error:\n{traceback.format_exc()}")
                    safe_edit(bot, "❌ *Fᴀɪʟᴇᴅ ᴛᴏ ʟᴏᴀᴅ Pᴏᴋᴇ́ᴍᴏɴ ᴅᴀᴛᴀ\\. Pʟᴇᴀsᴇ ᴛʀʏ ᴄʜᴀʟʟᴇɴɢɪɴɢ ᴀɢᴀɪɴ\\.*", call.message.chat.id, battle_id)
                    
            threading.Thread(target=setup).start()
            return

        elif action in ["move", "dosw", "mega", "swmenu", "confirmrun", "run", "back", "viewteam"]:
            battle_id = int(parts[2])
            b = pvp_battles.get(battle_id)
            if not b: return safe_answer(bot, call.id, "This battle has ended.")
            
            button_turn = parts[3] 
            actual_turn = b["current_turn"]
            
            if actual_turn in ["p1", "p2"] and button_turn != actual_turn:
                if call.from_user.id == b[actual_turn + "_id"]:
                    render_pvp_ui(bot, call.message.chat.id, battle_id)
                    return safe_answer(bot, call.id, "🔄 Syncing battle state...", show_alert=False)

            if call.from_user.id != b[button_turn + "_id"]: 
                if action == "viewteam": return safe_answer(bot, call.id, "❌ Cannot view opponent's team!", show_alert=True)
                return safe_answer(bot, call.id, "❌ Not your buttons!", show_alert=True)

            if actual_turn == "processing": 
                if time.time() - b.get("processing_start", 0) > 0.8:
                    b["current_turn"] = button_turn
                    actual_turn = button_turn
                else:
                    return safe_answer(bot, call.id, "⏳ Processing...", show_alert=False)

            if action != "viewteam":
                now = time.time()
                if now - b.get("last_edit", 0) < 0.5:
                    return safe_answer(bot, call.id, "⏳ Too fast!", show_alert=False)
                    
                if action == "swmenu" and not b["can_switch"]:
                    return safe_answer(bot, call.id, "🚫 Switching is disabled!", show_alert=True)
                if action == "mega" and b[actual_turn+"_team"][b[actual_turn+"_idx"]].get("is_mega"):
                    return safe_answer(bot, call.id, "Already transformed!", show_alert=True)
                if action == "dosw":
                    idx = int(parts[4])
                    p = b[actual_turn+"_team"][idx]
                    if p["hp"] <= 0: return safe_answer(bot, call.id, "Pokemon is fainted!", show_alert=True)
                    if idx == b[actual_turn+"_idx"]: return safe_answer(bot, call.id, "Already out!", show_alert=True)
                    
                b["last_edit"] = now
                safe_answer(bot, call.id, "")

            if action == "move":
                b["current_turn"] = "processing"
                b["processing_start"] = time.time()
                atk = b[actual_turn + "_team"][b[actual_turn + "_idx"]]
                defender = "p2" if actual_turn == "p1" else "p1"
                dfn = b[defender + "_team"][b[defender + "_idx"]]
                
                mv = atk["moves"][int(parts[4])]
                b["log"] = ""
                can_attack = True
                
                if atk.get("status") == "PAR" and random.random() < 0.25:
                    can_attack = False; b["log"] += f"⚡ {atk['name']} is paralyzed! It can't move!\n"
                elif atk.get("status") == "SLP":
                    atk["sleep_turns"] -= 1
                    if atk["sleep_turns"] <= 0: atk["status"] = None; b["log"] += f"💤 {atk['name']} woke up!\n"
                    else: can_attack = False; b["log"] += f"💤 {atk['name']} is fast asleep.\n"
                elif atk.get("status") == "FRZ":
                    if random.random() < 0.20: atk["status"] = None; b["log"] += f"🧊 {atk['name']} thawed out!\n"
                    else: can_attack = False; b["log"] += f"🧊 {atk['name']} is frozen solid!\n"

                if can_attack:
                    mv_acc = mv.get("acc")
                    if mv_acc is None: mv_acc = 100
                    
                    if random.randint(1, 100) > mv_acc:
                        b["log"] += f"{atk['name']} used {mv['name']}! It missed!\n"
                    else:
                        mult = get_type_multiplier(mv["type"], dfn["types"])
                        if mult == 0:
                            b["log"] += f"{mv['name']} had no effect on {dfn['name']}!\n"
                        else:
                            stab = 1.5 if mv["type"] in atk["types"] else 1.0
                            crit = 1.5 if random.random() < 0.06 else 1.0
                            
                            mv_pow = mv.get("power")
                            if mv_pow is None: mv_pow = 0
                            
                            if mv_pow > 0:
                                eff_atk = atk["atk"]
                                if atk.get("status") == "BRN":
                                    eff_atk = int(eff_atk * 0.5)

                                def_stat = max(1, dfn["def"])
                                
                                base_damage = ((42 * mv_pow * (eff_atk / def_stat)) / 50) + 2
                                rand_roll = random.uniform(0.85, 1.00)
                                dmg = max(1, int(base_damage * mult * stab * crit * rand_roll))
                                dfn["hp"] = max(0, dfn["hp"] - dmg)
                                
                                # ⚡ UPDATED FORMAT: Stripped the Bold Markdown from the attack log
                                b["log"] += f"{atk['name']} used {mv['name']}! It dealt {dmg} damage!\n"
                                if crit > 1: b["log"] += "A critical hit!\n"
                                if mult > 1: b["log"] += "It's super effective!\n"
                                elif mult < 1: b["log"] += "It's not very effective...\n"
                            else:
                                b["log"] += f"{atk['name']} used {mv['name']}!\n"
                            
                            if not dfn.get("status") and mv.get("status_chance", 0) > 0 and dfn["hp"] > 0:
                                if random.randint(1, 100) <= mv["status_chance"]:
                                    dfn["status"] = mv["status_type"]
                                    if mv["status_type"] == "SLP": 
                                        dfn["sleep_turns"] = random.randint(1, 3)
                                    b["log"] += f"{dfn['name']} was inflicted with {mv['status_type']}!\n"

                if atk["hp"] > 0:
                    if atk.get("status") == "BRN":
                        dmg = max(1, atk["max_hp"] // 16); atk["hp"] = max(0, atk["hp"] - dmg)
                        b["log"] += f"🔥 {atk['name']} is hurt by its burn!\n"
                    elif atk.get("status") == "PSN":
                        dmg = max(1, atk["max_hp"] // 8); atk["hp"] = max(0, atk["hp"] - dmg)
                        b["log"] += f"☠️ {atk['name']} is hurt by poison!\n"

                if dfn["hp"] <= 0:
                    dfn["hp"] = 0; dfn["status"] = None
                    b["log"] += f"💀 {dfn['name']} fainted!\n"
                    
                    if all(p["hp"] <= 0 for p in b[defender + "_team"]):
                        winner_name = b[actual_turn+'_name']
                        loser_name = b[defender+'_name']
                        win_mention = f"[{escape_md(winner_name)}](tg://user?id={b[actual_turn+'_id']})"
                        loser_mention = f"[{escape_md(loser_name)}](tg://user?id={b[defender+'_id']})"
                        
                        safe_edit(bot, f"{escape_md(b['log'].strip())}\n\n🏆 *{win_mention} ᴅᴇғᴇᴀᴛᴇᴅ {loser_mention} ɪɴ ᴛʜᴇ ʙᴀᴛᴛʟᴇ\\!*", call.message.chat.id, battle_id)
                        
                        if LOG_GROUP_ID:
                            try: bot.send_message(LOG_GROUP_ID, f"🏆 【Rᴇsᴜʟᴛ】 {win_mention} ᴅᴇғᴇᴀᴛᴇᴅ {loser_mention}", parse_mode="MarkdownV2")
                            except: pass
                        
                        try: db.update_task_pvp(b[actual_turn + "_id"])
                        except Exception as e: logger.error(f"Task PvP Error: {e}")
                        
                        try: db.update_battle_stats(b[actual_turn + "_id"], is_win=True)
                        except Exception as e: logger.error(f"Stat Save Error: {e}")
                        
                        try: db.update_battle_stats(b[defender + "_id"], is_win=False)
                        except Exception as e: logger.error(f"Stat Save Error: {e}")
                        
                        return end_battle(battle_id, bot, call.message.chat.id)
                        
                    b["state"] = "force_switch"; b["current_turn"] = defender
                    
                elif atk["hp"] <= 0:
                    atk["hp"] = 0; atk["status"] = None
                    b["log"] += f"💀 {atk['name']} fainted from status effect!\n"
                    
                    if all(p["hp"] <= 0 for p in b[actual_turn + "_team"]):
                        winner_name = b[defender+'_name']
                        loser_name = b[actual_turn+'_name']
                        win_mention = f"[{escape_md(winner_name)}](tg://user?id={b[defender+'_id']})"
                        loser_mention = f"[{escape_md(loser_name)}](tg://user?id={b[actual_turn+'_id']})"
                        
                        safe_edit(bot, f"{escape_md(b['log'].strip())}\n\n🏆 *{win_mention} ᴅᴇғᴇᴀᴛᴇᴅ {loser_mention} ɪɴ ᴛʜᴇ ʙᴀᴛᴛʟᴇ\\!*", call.message.chat.id, battle_id)
                        
                        if LOG_GROUP_ID:
                            try: bot.send_message(LOG_GROUP_ID, f"🏆 【Rᴇsᴜʟᴛ】 {win_mention} ᴅᴇғᴇᴀᴛᴇᴅ {loser_mention}", parse_mode="MarkdownV2")
                            except: pass
                        
                        try: db.update_task_pvp(b[defender + "_id"])
                        except Exception as e: logger.error(f"Task PvP Error: {e}")
                        
                        try: db.update_battle_stats(b[defender + "_id"], is_win=True)
                        except Exception as e: logger.error(f"Stat Save Error: {e}")
                        
                        try: db.update_battle_stats(b[actual_turn + "_id"], is_win=False)
                        except Exception as e: logger.error(f"Stat Save Error: {e}")
                        
                        return end_battle(battle_id, bot, call.message.chat.id)
                        
                    b["state"] = "force_switch"; b["current_turn"] = actual_turn
                else:
                    b["current_turn"] = defender
                
                render_pvp_ui(bot, call.message.chat.id, battle_id)

            elif action == "dosw":
                idx = int(parts[4])
                p = b[actual_turn+"_team"][idx]
                
                b["current_turn"] = "processing"
                b["processing_start"] = time.time()
                old_name = b[actual_turn+"_team"][b[actual_turn+"_idx"]]["name"]
                
                b[actual_turn+"_idx"] = idx
                
                if b["state"] == "switch_menu":
                    b["log"] = f"🔄 {old_name} was withdrawn!\n🔄 {p['name']} took the field!"
                    b["state"] = "menu"
                    b["current_turn"] = "p2" if actual_turn == "p1" else "p1"
                else:
                    b["log"] += f"\n🔄 {p['name']} took the field!"
                    b["state"] = "menu"
                    b["current_turn"] = get_faster_player(b)
                    
                render_pvp_ui(bot, call.message.chat.id, battle_id)

            elif action == "swmenu":
                b["state"] = "switch_menu"; render_pvp_ui(bot, call.message.chat.id, battle_id)
                
            elif action == "mega":
                p = b[actual_turn+"_team"][b[actual_turn+"_idx"]]
                old_name = p['name']
                
                if old_name in ["Charizard", "Mewtwo", "Raichu"] and len(parts) == 4:
                    b["state"] = "mega_xy_choice"; render_pvp_ui(bot, call.message.chat.id, battle_id); return
                
                if old_name == "Lucario" and len(parts) == 4:
                    b["state"] = "mega_lucario_choice"; render_pvp_ui(bot, call.message.chat.id, battle_id); return

                if old_name == "Greninja" and len(parts) == 4:
                    b["state"] = "mega_greninja_choice"; render_pvp_ui(bot, call.message.chat.id, battle_id); return
                    
                xy_choice = parts[4] if len(parts) == 5 and old_name in ["Charizard", "Mewtwo", "Raichu"] else ""
                z_choice = parts[4] if len(parts) == 5 and old_name == "Lucario" else ""
                gren_choice = parts[4] if len(parts) == 5 and old_name == "Greninja" else ""
                
                if old_name in ["Groudon", "Kyogre"]:
                    new_name = f"Primal {old_name}"
                    action_verb = "Underwent Primal Reversion"
                    search_name = f"{old_name.lower()}-primal"
                    icon = "🌋"
                elif old_name in ["Zacian", "Zamazenta"]:
                    new_name = f"Crowned {old_name}"
                    action_verb = "Took on its Crowned Form"
                    search_name = f"{old_name.lower()}-crowned"
                    icon = "🗡️" if old_name == "Zacian" else "🛡️"
                elif old_name == "Calyrex":
                    new_name = "Shadow Rider Calyrex"
                    action_verb = "Mounted Spectrier"
                    search_name = "calyrex-shadow"
                    icon = "🐎"
                elif old_name == "Greninja":
                    if gren_choice == "Ash":
                        new_name = "Ash-Greninja"
                        action_verb = "Activated the Bond Phenomenon"
                        search_name = "greninja-ash"
                        icon = "💧"
                    else:
                        new_name = "Mega Greninja"
                        action_verb = "Mega Evolved"
                        search_name = "greninja-mega"
                        icon = "💎"
                else:
                    if z_choice == "Standard" or (not z_choice and not xy_choice):
                        new_name = f"Mega {old_name}"
                        search_name = f"{old_name.lower()}-mega"
                    elif z_choice == "Z":
                        new_name = f"Mega {old_name} Z"
                        search_name = f"{old_name.lower()}-mega-z"
                    else:
                        new_name = f"Mega {old_name}" + (f" {xy_choice}" if xy_choice else "")
                        search_name = f"{old_name.lower()}-mega" + (f"-{xy_choice.lower()}" if xy_choice else "")
                    
                    action_verb = "Mega Evolved"
                    icon = "💎"

                # --- FETCH REAL STATS FROM API ---
                types_list, new_base_stats = get_pokemon_stats_sync(search_name)
                if new_base_stats:
                    p["base_atk"] = new_base_stats.get("atk", new_base_stats.get("Attack", new_base_stats.get("attack", p["base_atk"])))
                    p["base_def"] = new_base_stats.get("def", new_base_stats.get("Defense", new_base_stats.get("defense", p["base_def"])))
                    p["base_spd"] = new_base_stats.get("spd", new_base_stats.get("Speed", new_base_stats.get("speed", p["base_spd"])))
                    if types_list:
                        p["types"] = "/".join(types_list)
                
                # Recalculate Final Stats
                p["atk"] = int((2 * p["base_atk"]) + 31 + 21 + 5)
                p["def"] = int((2 * p["base_def"]) + 31 + 21 + 5)
                p["spd"] = int((2 * p["base_spd"]) + 31 + 21 + 5)
                
                p = apply_nature(p, p["nature"])
                p["is_mega"] = True
                p["name"] = new_name
                
                b["log"] = f"{icon} {old_name} {action_verb.lower()} into {new_name}!"
                b["state"] = "menu"
                render_pvp_ui(bot, call.message.chat.id, battle_id)
                
                def send_mega_image():
                    try:
                        poke_id = get_pokemon_id_sync(search_name)
                        if poke_id:
                            img_url = official_shiny_artwork_url(poke_id)
                            cap_text = f"{icon} {old_name}... {action_verb} into {new_name}!"
                            caption = f"*{escape_md(cap_text)}*"
                            try: bot.send_photo(call.message.chat.id, img_url, caption=caption, parse_mode="MarkdownV2", reply_to_message_id=battle_id)
                            except Exception as e:
                                if "429" in str(e) or "Too Many Requests" in str(e):
                                    time.sleep(3)
                                    try: bot.send_photo(call.message.chat.id, img_url, caption=caption, parse_mode="MarkdownV2", reply_to_message_id=battle_id)
                                    except: pass
                    except Exception as e: logger.error(f"Mega Image Error: {e}")
                
                threading.Thread(target=send_mega_image, daemon=True).start()
                
            elif action == "confirmrun": 
                b["state"] = "run_confirm"; render_pvp_ui(bot, call.message.chat.id, battle_id)
                
            elif action == "run": 
                runner_id = b[actual_turn + "_id"]
                runner_name = escape_md(b[actual_turn+'_name'])
                runner_mention = f"[{runner_name}](tg://user?id={runner_id})"
                
                winner_id = b["p2_id"] if actual_turn == "p1" else b["p1_id"]
                winner_name = b["p2_name"] if actual_turn == "p1" else b["p1_name"]
                win_mention = f"[{escape_md(winner_name)}](tg://user?id={winner_id})"
                
                safe_edit(bot, f"🏃 *{runner_mention} ғʟᴇᴅ\\!*\n\n🏆 *{win_mention} ᴅᴇғᴇᴀᴛᴇᴅ {runner_mention} ɪɴ ᴛʜᴇ ʙᴀᴛᴛʟᴇ\\!*", call.message.chat.id, battle_id)
                
                if LOG_GROUP_ID:
                    try: bot.send_message(LOG_GROUP_ID, f"🏃 *Forfeit:* {win_mention} ᴅᴇғᴇᴀᴛᴇᴅ {runner_mention} ɪɴ ᴛʜᴇ ʙᴀᴛᴛʟᴇ\\!", parse_mode="MarkdownV2")
                    except: pass
                
                # Runner gets a loss, but winner gets NO POINTS for a forfeit.
                try: db.update_battle_stats(runner_id, is_win=False)
                except Exception as e: logger.error(f"Stat Save Error: {e}")
                
                end_battle(battle_id, bot, call.message.chat.id)
                
            elif action == "back": 
                b["state"] = "menu"; render_pvp_ui(bot, call.message.chat.id, battle_id)
                
            elif action == "viewteam":
                lines = []
                for i, p in enumerate(b[button_turn + '_team']):
                    emojis = "".join([TYPE_EMOJIS.get(t.strip(), '⚪') for t in p['types'].split('/')])
                    status_icon = '💀' if p['hp'] <= 0 else ('💤' if p.get('status') == 'SLP' else ('🧊' if p.get('status') == 'FRZ' else ('🔥' if p.get('status') == 'BRN' else ('☠️' if p.get('status') == 'PSN' else ('⚡' if p.get('status') == 'PAR' else '🟢')))))
                    lines.append(f"{i+1}. {p['name']} [{emojis}] - {p['nature']} {status_icon}")
                
                safe_answer(bot, call.id, "\n".join(lines), show_alert=True)

    except Exception as e: 
        logger.error(f"PvP Callback Error: {e}")
