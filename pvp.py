# pvp.py
import time
import random
import threading
import asyncio
import copy
from telebot import types
import database as db
from api_utils import escape_md, generate_random_team, get_pokemon_id_sync, official_shiny_artwork_url
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

STATUS_EMOJIS = {
    "BRN": "🔥 BRN", "PAR": "⚡ PAR", "PSN": "☠️ PSN", 
    "FRZ": "🧊 FRZ", "SLP": "💤 SLP"
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

FORM_TYPE_CHANGES = {
    "Mega Charizard X": "Fire/Dragon",
    "Mega Mewtwo X": "Psychic/Fighting",
    "Mega Gyarados": "Water/Dark",
    "Mega Sceptile": "Grass/Dragon",
    "Mega Altaria": "Dragon/Fairy",
    "Mega Ampharos": "Electric/Dragon",
    "Mega Pinsir": "Bug/Flying",
    "Mega Aggron": "Steel",
    "Mega Lopunny": "Normal/Fighting",
    "Mega Audino": "Normal/Fairy",
    "Mega Meganium": "Grass/Fairy", # <-- Custom type for your custom Mega!
    "Primal Groudon": "Ground/Fire",
    "Crowned Zacian": "Fairy/Steel",
    "Crowned Zamazenta": "Fighting/Steel",
    "Shadow Rider Calyrex": "Psychic/Ghost"
}

MEGA_STAT_BUFFS = {
    "Mega Charizard X": {"atk": 46, "def": 33, "spd": 0},
    "Mega Charizard Y": {"atk": 20, "def": 0, "spd": 0},
    "Mega Mewtwo X": {"atk": 80, "def": 10, "spd": 0},
    "Mega Mewtwo Y": {"atk": 40, "def": -20, "spd": 10},
    "Primal Groudon": {"atk": 30, "def": 20, "spd": 0},
    "Primal Kyogre": {"atk": 50, "def": 0, "spd": 0},
    "Crowned Zacian": {"atk": 20, "def": 0, "spd": 10},
    "Crowned Zamazenta": {"atk": -10, "def": 25, "spd": -10},
    "Shadow Rider Calyrex": {"atk": 0, "def": 0, "spd": 70},
    "Ash-Greninja": {"atk": 50, "def": 0, "spd": 10},
    "Mega Dragonite": {"atk": 40, "def": 20, "spd": 20}, # <-- Custom buff!
    "Mega Meganium": {"atk": 10, "def": 40, "spd": 30} # <-- Custom buff!
}

# --- HELPERS ---
def safe_answer(bot, call_id, text, show_alert=False):
    try: bot.answer_callback_query(call_id, text, show_alert=show_alert)
    except Exception: pass

def get_faster_player(b):
    p1_spd = b["p1_team"][b["p1_idx"]]["spd"]
    p2_spd = b["p2_team"][b["p2_idx"]]["spd"]
    return "p1" if p1_spd >= p2_spd else "p2"

def challenge_timeout(bot, chat_id, message_id):
    chal = pending_challenges.pop(message_id, None)
    if chal:
        try: bot.edit_message_text("⏳ *Challenge expired\\.*", chat_id, message_id, parse_mode="MarkdownV2")
        except Exception: pass

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
        
        # --- BATTLE STATS: Timeout Loss ---
        db.update_battle_stats(winner_id, is_win=True)
        db.update_battle_stats(loser_id, is_win=False)
        
        try: bot.edit_message_text(f"⏳ *{escape_md(loser_name)} ran out of time\\!*\n\n🏆 *{escape_md(winner_name)} WINS THE BATTLE\\!*", chat_id, battle_id, parse_mode="MarkdownV2")
        except Exception: pass

def end_battle(battle_id):
    b = pvp_battles.pop(battle_id, None)
    if b and "timer" in b and b["timer"]: b["timer"].cancel()

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

def get_hp_bar(current, maximum, length=14):
    if maximum <= 0: return "░" * length
    filled = int(round((current / maximum) * length))
    if current > 0 and filled == 0: filled = 1
    return escape_md("█" * filled + "░" * (length - filled))

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
    size = chal["size"]
    mode = chal["mode"]
    sw_text = "ON" if chal["can_switch"] else "OFF"
    
    text = (f"🥊 *{p1_name}* challenged *{p2_name}* to a {size}v{size} Random Battle\\!\n\n"
            f"⚙️ *Mode:* {mode}\n"
            f"🔄 *Switching:* {sw_text}\n\n"
            f"_You have 60 seconds to accept\\._")
    
    kb = types.InlineKeyboardMarkup()
    kb.add(types.InlineKeyboardButton("⚙️ Settings", callback_data=f"pvp_settings_{chal['p1_id']}"))
    kb.add(
        types.InlineKeyboardButton("⚔️ Accept", callback_data=f"pvp_accept_{chal['p1_id']}_{chal['p2_id']}"),
        types.InlineKeyboardButton("❌ Decline", callback_data=f"pvp_decline_{chal['p1_id']}_{chal['p2_id']}")
    )
    try: bot.edit_message_text(text, chat_id, message_id, reply_markup=kb, parse_mode="MarkdownV2")
    except Exception as e: 
        if "message is not modified" not in str(e).lower(): pass

def render_settings_ui(bot, chat_id, message_id, chal):
    text = f"⚙️ *Battle Settings*\n\nConfigure the rules for this match:"
    kb = types.InlineKeyboardMarkup(row_width=3)
    
    m_0, m_6, m_m = ("✅ 0ls" if chal['mode'] == "0ls" else "0ls"), ("✅ 6ls" if chal['mode'] == "6ls" else "6ls"), ("✅ Mix" if chal['mode'] == "Mix" else "Mix")
    kb.row(types.InlineKeyboardButton(m_0, callback_data=f"pvp_setm_{chal['p1_id']}_0ls"),
           types.InlineKeyboardButton(m_6, callback_data=f"pvp_setm_{chal['p1_id']}_6ls"),
           types.InlineKeyboardButton(m_m, callback_data=f"pvp_setm_{chal['p1_id']}_Mix"))
    
    sz_btns = [types.InlineKeyboardButton(f"✅ {s}" if chal['size'] == s else str(s), callback_data=f"pvp_sets_{chal['p1_id']}_{s}") for s in range(1, 7)]
    kb.add(*sz_btns)
    
    sw_lbl = "🔄 Switch: ON" if chal['can_switch'] else "🚫 Switch: OFF"
    kb.row(types.InlineKeyboardButton(sw_lbl, callback_data=f"pvp_setsw_{chal['p1_id']}"))
    kb.row(types.InlineKeyboardButton("💾 Save as Default", callback_data=f"pvp_setsave_{chal['p1_id']}"))
    kb.row(types.InlineKeyboardButton("🔙 Back", callback_data=f"pvp_setback_{chal['p1_id']}"))
    try: bot.edit_message_text(text, chat_id, message_id, reply_markup=kb, parse_mode="MarkdownV2")
    except Exception as e: 
        if "message is not modified" not in str(e).lower(): pass

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
    
    log_content = escape_md(b['log'].strip()) if b['log'] else "The battle begins\\!"
    
    act_status = f" \\[{STATUS_EMOJIS.get(active_poke['status'], '')}\\]" if active_poke.get('status') else ""
    def_status = f" \\[{STATUS_EMOJIS.get(def_poke['status'], '')}\\]" if def_poke.get('status') else ""
    
    act_mega = get_form_icon(active_poke['name'], active_poke.get("is_mega"))
    def_mega = get_form_icon(def_poke['name'], def_poke.get("is_mega"))

    ui_text = (
        f"{log_content}\n\n"
        f"*{escape_md(def_name)}*'s {escape_md(def_poke['name'])}{def_mega} \\[{escape_md(format_types(def_poke['types']))}\\]\n"
        f"Lv\\. 100  •  HP {int(def_poke['hp'])}/{int(def_poke['max_hp'])}\n"
        f"`{get_hp_bar(def_poke['hp'], def_poke['max_hp'])}`{escape_md(def_status)}\n\n"
        f"Current turn: *{escape_md(active_name)}*\n"
        f"*{escape_md(active_name)}*'s {escape_md(active_poke['name'])}{act_mega} \\[{escape_md(format_types(active_poke['types']))}\\]\n"
        f"Lv\\. 100  •  HP {int(active_poke['hp'])}/{int(active_poke['max_hp'])}\n"
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
            
            moves_block += f" {m_name} \\[{m_type_display}\\]\n Power: {m_pow}, Accuracy: {m_acc}\n"
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
            elif active_poke["name"] == "Greninja": btn_lbl = "💧 Bond Phenomenon"
            else: btn_lbl = "💎 Mega Evolve"
            
            kb.row(types.InlineKeyboardButton(btn_lbl, callback_data=f"pvp_mega_{battle_id}_{turn}"))
            
        kb.row(types.InlineKeyboardButton("🔄 Switch", callback_data=f"pvp_swmenu_{battle_id}_{turn}"),
               types.InlineKeyboardButton("🏃 Run", callback_data=f"pvp_confirmrun_{battle_id}_{turn}"))
               
    elif b["state"] == "mega_xy_choice":
        ui_text += f" Choose a Mega Evolution form:\n"
        kb.row(types.InlineKeyboardButton("Mega Form X", callback_data=f"pvp_mega_{battle_id}_{turn}_X"),
               types.InlineKeyboardButton("Mega Form Y", callback_data=f"pvp_mega_{battle_id}_{turn}_Y"))
        kb.row(types.InlineKeyboardButton("🔙 Back", callback_data=f"pvp_back_{battle_id}_{turn}"))

    elif b["state"] in ["switch_menu", "force_switch"]:
        ui_text += f" 🔄 Choose a Pokémon to switch into:\n" if b["state"] == "switch_menu" else f" 💀 Choose a replacement Pokémon:\n"
        btns = [types.InlineKeyboardButton(f"{'🔴' if p['hp'] > 0 else '💀'} {i+1}", callback_data=f"pvp_dosw_{battle_id}_{turn}_{i}") for i, p in enumerate(b[turn + "_team"])]
        for i in range(0, len(btns), 3): kb.add(*btns[i:i+3])
        
        kb.row(types.InlineKeyboardButton("📋 View Team", callback_data=f"pvp_viewteam_{battle_id}_{turn}"))
        if b["state"] == "switch_menu": 
            kb.row(types.InlineKeyboardButton("🔙 Back", callback_data=f"pvp_back_{battle_id}_{turn}"))
            
    elif b["state"] == "run_confirm":
        ui_text += f" ⚠️ Are you sure you want to flee the battle?\n"
        kb.row(types.InlineKeyboardButton("✅ Confirm Flee", callback_data=f"pvp_run_{battle_id}_{turn}"),
               types.InlineKeyboardButton("❌ Cancel", callback_data=f"pvp_back_{battle_id}_{turn}"))

    try: 
        bot.edit_message_text(ui_text, chat_id, battle_id, reply_markup=kb, parse_mode="MarkdownV2")
    except Exception as e: 
        err_msg = str(e).lower()
        if "message is not modified" in err_msg: pass 
        elif "429" in err_msg or "too many requests" in err_msg:
            time.sleep(1.5)
            try: bot.edit_message_text(ui_text, chat_id, battle_id, reply_markup=kb, parse_mode="MarkdownV2")
            except: pass
        else: logger.error(f"UI Update error: {e}")

# --- COMMAND HANDLER (WITH NEW PROTECTIONS) ---
def handle_pvp_command(bot, message):
    if not message.reply_to_message: 
        return bot.reply_to(message, escape_md("⚠️ Reply to a user to challenge them!"))
        
    target = message.reply_to_message
    
    # 1. Anti-Bot and Anti-Channel Protection
    if target.from_user.is_bot or target.sender_chat:
        return bot.reply_to(message, escape_md("❌ You cannot challenge bots or channels!"))
        
    p1_id = message.from_user.id
    p2_id = target.from_user.id
    
    # 2. Block Self-Challenge
    if p1_id == p2_id: 
        return bot.reply_to(message, escape_md("❌ You can't challenge yourself!"))
        
    # 3. Ensure Challenger is registered
    if not db.get_user(p1_id):
        return bot.reply_to(message, escape_md("⚠️ You need to /start the bot first!"))
        
    # 4. Ensure Target is registered
    if not db.get_user(p2_id):
        return bot.reply_to(message, escape_md(f"❌ {target.from_user.first_name} hasn't registered yet! They need to /start the bot to play."))
    
    if is_in_battle(p1_id) or is_in_battle(p2_id): 
        return bot.reply_to(message, escape_md("❌ Someone is already in a battle!"))

    to_remove = []
    for mid, c in list(pending_challenges.items()):
        if p1_id in [c["p1_id"], c["p2_id"]]:
            c["timer"].cancel()
            to_remove.append(mid)
            try: bot.edit_message_text("❌ *Challenge cancelled because a new one was started\\.*", c["chat_id"], mid, parse_mode="MarkdownV2")
            except: pass
    for mid in to_remove: pending_challenges.pop(mid, None)

    if is_in_pending_challenge(p2_id): 
        return bot.reply_to(message, escape_md("❌ That user already has a pending challenge!"))

    mode, size, can_switch = db.get_pvp_settings(p1_id)
    sent = bot.reply_to(message, escape_md("🔄 Loading challenge..."), parse_mode="MarkdownV2")
    
    timer = threading.Timer(60.0, challenge_timeout, args=(bot, message.chat.id, sent.message_id))
    timer.start()
    
    chal = {"name": message.from_user.first_name, "p2_name": target.from_user.first_name,
            "timer": timer, "p1_id": p1_id, "p2_id": p2_id, "chat_id": message.chat.id, 
            "mode": mode, "size": size, "can_switch": can_switch}
    
    pending_challenges[sent.message_id] = chal
    update_challenge_message(bot, message.chat.id, sent.message_id, chal)

# --- CALLBACK HANDLER ---
def handle_pvp_callback(bot, call):
    try:
        parts = call.data.split("_")
        action = parts[1]
        
        if action == "settings":
            chal = pending_challenges.get(call.message.message_id)
            if chal and call.fromuser.id == chal["p1_id"]: render_settings_ui(bot, call.message.chat.id, call.message.message_id, chal)
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
        elif action == "setsave":
            chal = pending_challenges.get(call.message.message_id)
            if chal and call.from_user.id == chal["p1_id"]: 
                db.update_pvp_settings(chal["p1_id"], chal["mode"], chal["size"], chal["can_switch"])
                safe_answer(bot, call.id, "✅ Defaults Saved!", show_alert=True)
            return
        elif action == "setback":
            chal = pending_challenges.get(call.message.message_id)
            if chal and call.from_user.id == chal["p1_id"]: 
                update_challenge_message(bot, call.message.chat.id, call.message.message_id, chal)
            return

        if action == "accept":
            p1_id, p2_id = int(parts[2]), int(parts[3])
            if call.from_user.id != p2_id: return safe_answer(bot, call.id, "❌ Not your challenge!", show_alert=True)
            
            battle_id = call.message.message_id
            chal_data = pending_challenges.pop(battle_id, None)
            
            if not chal_data: return safe_answer(bot, call.id, "This challenge has expired or was already answered!")
            
            chal_data["timer"].cancel()
            safe_answer(bot, call.id, "Preparing the arena...")

            if LOG_GROUP_ID:
                try: bot.send_message(LOG_GROUP_ID, f"⚔️ *Battle Started:* [{escape_md(chal_data['name'])}](tg://user?id={chal_data['p1_id']}) 🆚 [{escape_md(chal_data['p2_name'])}](tg://user?id={chal_data['p2_id']})", parse_mode="MarkdownV2")
                except: pass
            
            def setup():
                bot.edit_message_text("🔄 *Drafting Teams\\.\\.\\.*", call.message.chat.id, battle_id, parse_mode="MarkdownV2")
                
                t1_draft = asyncio.run(generate_random_team(chal_data["mode"], chal_data["size"]))
                t2_draft = asyncio.run(generate_random_team(chal_data["mode"], chal_data["size"]))
                
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

                        if base_hp <= 1: p["max_hp"] = 1 # Shedinja exception
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
                        
                        special_forms = ["Charizard", "Mewtwo", "Groudon", "Kyogre", "Zacian", "Zamazenta", "Calyrex", "Greninja"]
                        p["can_mega"] = any(m[1].split("-")[0].lower() == p["name"].lower() for m in MEGA_POKEMON) or p["name"] in special_forms
                        p["is_mega"] = False
                        
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
            threading.Thread(target=setup).start()
            return

        elif action == "decline":
            p1_id, p2_id = int(parts[2]), int(parts[3])
            if call.from_user.id != p2_id: return safe_answer(bot, call.id, "❌ Only the challenged player can decline.", show_alert=True)
            chal_data = pending_challenges.pop(call.message.message_id, None)
            if chal_data: 
                chal_data["timer"].cancel()
                bot.edit_message_text("❌ *Challenge declined\\.*", call.message.chat.id, call.message.message_id, parse_mode="MarkdownV2")
            return

        # IN-BATTLE ACTIONS
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
                if time.time() - b.get("processing_start", 0) > 5:
                    b["current_turn"] = button_turn
                    actual_turn = button_turn
                else:
                    return safe_answer(bot, call.id, "⏳ Processing previous move...")

            if action != "viewteam":
                now = time.time()
                if now - b.get("last_edit", 0) < 1.2:
                    return safe_answer(bot, call.id, "⏳ Please don't click so fast!")
                b["last_edit"] = now

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
                        b["log"] += f"{atk['name']}'s {mv['name']} missed!\n"
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
                                def_stat = max(1, dfn["def"])
                                
                                # --- OFFICIAL POKEMON DAMAGE FORMULA ---
                                # Level = 100. (2 * 100 / 5) + 2 = 42
                                base_damage = ((42 * mv_pow * (atk["atk"] / def_stat)) / 50) + 2
                                
                                # Official RNG damage roll (85% to 100%)
                                rand_roll = random.uniform(0.85, 1.00)
                                
                                dmg = max(1, int(base_damage * mult * stab * crit * rand_roll))
                                dfn["hp"] = max(0, dfn["hp"] - dmg)
                                
                                b["log"] += f"{atk['name']} used {mv['name']}! ({dmg} DMG)\n"
                                if crit > 1: b["log"] += "A critical hit!\n"
                                if mult > 1: b["log"] += "It's super effective!\n"
                                elif mult < 1: b["log"] += "It's not very effective...\n"
                            else:
                                b["log"] += f"{atk['name']} used {mv['name']}!\n"
                            
                            if not dfn.get("status") and mv.get("status_chance", 0) > 0 and dfn["hp"] > 0:
                                if random.randint(1, 100) <= mv["status_chance"]:
                                    dfn["status"] = mv["status_type"]
                                    if mv["status_type"] == "SLP": dfn["sleep_turns"] = random.randint(1, 3)
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
                    b["log"] += f"{dfn['name']} fainted!\n"
                    if all(p["hp"] <= 0 for p in b[defender + "_team"]):
                        bot.edit_message_text(f"{escape_md(b['log'].strip())}\n\n🏆 *{escape_md(b[actual_turn+'_name'])} WINS\\!*", call.message.chat.id, battle_id, parse_mode="MarkdownV2")
                        if LOG_GROUP_ID:
                            try: bot.send_message(LOG_GROUP_ID, f"🏆 *Battle Ended:* [{escape_md(b[actual_turn+'_name'])}](tg://user?id={b[actual_turn+'_id']}) won a PvP match\\!", parse_mode="MarkdownV2")
                            except: pass
                        
                        # --- BATTLE STATS: Attacker Wins! ---
                        db.update_task_pvp(b[actual_turn + "_id"])
                        db.update_battle_stats(b[actual_turn + "_id"], is_win=True)
                        db.update_battle_stats(b[defender + "_id"], is_win=False)
                        
                        return end_battle(battle_id)
                    b["state"] = "force_switch"; b["current_turn"] = defender
                elif atk["hp"] <= 0:
                    atk["hp"] = 0; atk["status"] = None
                    b["log"] += f"{atk['name']} fainted from status effect!\n"
                    if all(p["hp"] <= 0 for p in b[actual_turn + "_team"]):
                        bot.edit_message_text(f"{escape_md(b['log'].strip())}\n\n🏆 *{escape_md(b[defender+'_name'])} WINS\\!*", call.message.chat.id, battle_id, parse_mode="MarkdownV2")
                        if LOG_GROUP_ID:
                            try: bot.send_message(LOG_GROUP_ID, f"🏆 *Battle Ended:* [{escape_md(b[defender+'_name'])}](tg://user?id={b[defender+'_id']}) won a PvP match\\!", parse_mode="MarkdownV2")
                            except: pass
                        
                        # --- BATTLE STATS: Defender Wins! ---
                        db.update_task_pvp(b[defender + "_id"])
                        db.update_battle_stats(b[defender + "_id"], is_win=True)
                        db.update_battle_stats(b[actual_turn + "_id"], is_win=False)
                        
                        return end_battle(battle_id)
                    b["state"] = "force_switch"; b["current_turn"] = actual_turn
                else:
                    b["current_turn"] = defender
                
                render_pvp_ui(bot, call.message.chat.id, battle_id)

            elif action == "dosw":
                idx = int(parts[4])
                p = b[actual_turn+"_team"][idx]
                if p["hp"] <= 0: return safe_answer(bot, call.id, "Pokemon is fainted!")
                if idx == b[actual_turn+"_idx"]: return safe_answer(bot, call.id, "Already out!")
                
                b["current_turn"] = "processing"
                b["processing_start"] = time.time()
                old_name = b[actual_turn+"_team"][b[actual_turn+"_idx"]]["name"]
                b[actual_turn+"_idx"] = idx
                
                if b["state"] == "switch_menu":
                    b["log"] = f"🔄 {old_name} was withdrawn!\n{p['name']} took the field!"
                    b["state"] = "menu"
                    b["current_turn"] = "p2" if actual_turn == "p1" else "p1"
                else:
                    b["log"] += f"\n🔄 {p['name']} took the field!"
                    b["state"] = "menu"
                    b["current_turn"] = get_faster_player(b)
                    
                render_pvp_ui(bot, call.message.chat.id, battle_id)

            elif action == "swmenu":
                if not b["can_switch"]: return safe_answer(bot, call.id, "🚫 Switching is disabled!", show_alert=True)
                b["state"] = "switch_menu"; render_pvp_ui(bot, call.message.chat.id, battle_id)
                
            elif action == "mega":
                p = b[actual_turn+"_team"][b[actual_turn+"_idx"]]
                if p.get("is_mega"): return safe_answer(bot, call.id, "Already transformed!")
                
                old_name = p['name']
                
                if old_name in ["Charizard", "Mewtwo"] and len(parts) == 4:
                    b["state"] = "mega_xy_choice"
                    render_pvp_ui(bot, call.message.chat.id, battle_id)
                    return
                    
                xy_choice = parts[4] if len(parts) == 5 and old_name in ["Charizard", "Mewtwo"] else ""
                
                if old_name in ["Groudon", "Kyogre"]:
                    new_name = f"Primal {old_name}"
                    action_verb = "underwent Primal Reversion"
                    search_name = f"{old_name.lower()}-primal"
                    icon = "🌋"
                elif old_name in ["Zacian", "Zamazenta"]:
                    new_name = f"Crowned {old_name}"
                    action_verb = "took on its Crowned Form"
                    search_name = f"{old_name.lower()}-crowned"
                    icon = "🗡️" if old_name == "Zacian" else "🛡️"
                elif old_name == "Calyrex":
                    new_name = "Shadow Rider Calyrex"
                    action_verb = "mounted Spectrier"
                    search_name = "calyrex-shadow"
                    icon = "🐎"
                elif old_name == "Greninja":
                    new_name = "Ash-Greninja"
                    action_verb = "activated the Bond Phenomenon"
                    search_name = "greninja-ash"
                    icon = "💧"
                else:
                    new_name = f"Mega {old_name}" + (f" {xy_choice}" if xy_choice else "")
                    action_verb = "Mega Evolved"
                    search_name = f"{old_name.lower()}-mega" + (f"-{xy_choice.lower()}" if xy_choice else "")
                    icon = "💎"

                buffs = MEGA_STAT_BUFFS.get(new_name, {"atk": 30, "def": 30, "spd": 20})
                new_base_atk = p["base_atk"] + buffs["atk"]
                new_base_def = p["base_def"] + buffs["def"]
                new_base_spd = p["base_spd"] + buffs["spd"]
                
                p["atk"] = int((2 * new_base_atk) + 31 + 21 + 5)
                p["def"] = int((2 * new_base_def) + 31 + 21 + 5)
                p["spd"] = int((2 * new_base_spd) + 31 + 21 + 5)
                
                p = apply_nature(p, p["nature"])

                p["is_mega"] = True
                p["name"] = new_name
                if new_name in FORM_TYPE_CHANGES: p["types"] = FORM_TYPE_CHANGES[new_name]
                
                b["log"] = f"{old_name} {action_verb} into {new_name}!"
                b["state"] = "menu"
                render_pvp_ui(bot, call.message.chat.id, battle_id)
                
                def send_mega_image():
                    try:
                        poke_id = get_pokemon_id_sync(search_name)
                        if poke_id:
                            img_url = official_shiny_artwork_url(poke_id)
                            caption = f"{icon} *{escape_md(old_name)}* \\.\\.\\. {escape_md(action_verb)} into *{escape_md(new_name)}*\\!"
                            try: bot.send_photo(call.message.chat.id, img_url, caption=caption, parse_mode="MarkdownV2")
                            except Exception as e:
                                if "429" in str(e) or "Too Many Requests" in str(e):
                                    time.sleep(3)
                                    try: bot.send_photo(call.message.chat.id, img_url, caption=caption, parse_mode="MarkdownV2")
                                    except: pass
                    except Exception as e: logger.error(f"Mega Image Error: {e}")
                
                threading.Thread(target=send_mega_image, daemon=True).start()
                
            elif action == "confirmrun": 
                b["state"] = "run_confirm"; render_pvp_ui(bot, call.message.chat.id, battle_id)
                
            elif action == "run": 
                end_battle(battle_id)
                bot.edit_message_text(f"🏃 *{escape_md(b[actual_turn+'_name'])} fled\\!*", call.message.chat.id, battle_id, parse_mode="MarkdownV2")
                if LOG_GROUP_ID:
                    try: bot.send_message(LOG_GROUP_ID, f"🏃 *Battle Ended:* [{escape_md(b[actual_turn+'_name'])}](tg://user?id={b[actual_turn+'_id']}) fled from battle\\.", parse_mode="MarkdownV2")
                    except: pass
                
                # --- BATTLE STATS: Fleeing is a Loss ---
                runner_id = b[actual_turn + "_id"]
                winner_id = b["p2_id"] if actual_turn == "p1" else b["p1_id"]
                db.update_battle_stats(runner_id, is_win=False)
                db.update_battle_stats(winner_id, is_win=True)
                
            elif action == "back": 
                b["state"] = "menu"; render_pvp_ui(bot, call.message.chat.id, battle_id)
                
            elif action == "viewteam":
                lines = []
                for i, p in enumerate(b[actual_turn + '_team']):
                    emojis = "/".join([TYPE_EMOJIS.get(t.strip(), '⚪') for t in p['types'].split('/')])
                    status_icon = '💀' if p['hp'] <= 0 else ('💤' if p.get('status') == 'SLP' else ('🧊' if p.get('status') == 'FRZ' else ('🔥' if p.get('status') == 'BRN' else ('☠️' if p.get('status') == 'PSN' else ('⚡' if p.get('status') == 'PAR' else '🟢')))))
                    lines.append(f"{i+1}. {p['name']} [{emojis}] - {p['nature']} {status_icon}")
                
                safe_answer(bot, call.id, "\n".join(lines), show_alert=True)

    except Exception as e: 
        logger.error(f"PvP Callback Error: {e}")
