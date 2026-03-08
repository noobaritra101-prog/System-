# pvp.py
import time
import random
import threading
import asyncio
from telebot import types
import database as db
from api_utils import escape_md, generate_random_team
from config import logger, MEGA_POKEMON, LOG_GROUP_ID
import tasks 

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
    "BRN": "🔥 BRN", "PAR": "⚡ PAR", "PSN": "☣️ PSN", 
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

# --- HELPERS ---
def format_types(types_str):
    """Turns 'Psychic/Fairy' into 'Psychic 🔮 / Fairy 🧚‍♀️'"""
    types_list = types_str.split('/')
    formatted = [f"{t} {TYPE_EMOJIS.get(t, '')}".strip() for t in types_list]
    return " / ".join(formatted)

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
        pvp_battles.pop(battle_id, None)
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
    """Creates the ██████████░░░░ health bar"""
    if maximum <= 0: return "░" * length
    filled = int(round((current / maximum) * length))
    if current > 0 and filled == 0: filled = 1
    return escape_md("█" * filled + "░" * (length - filled))

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
    bot.edit_message_text(text, chat_id, message_id, reply_markup=kb, parse_mode="MarkdownV2")

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
    bot.edit_message_text(text, chat_id, message_id, reply_markup=kb, parse_mode="MarkdownV2")

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
    
    log_content = escape_md(b['log']) if b['log'] else "The battle begins\\!"
    
    # Render Status
    act_status = f" \\[{STATUS_EMOJIS.get(active_poke['status'], '')}\\]" if active_poke.get('status') else ""
    def_status = f" \\[{STATUS_EMOJIS.get(def_poke['status'], '')}\\]" if def_poke.get('status') else ""
    
    # Render Mega
    act_mega = " 💎" if active_poke.get("is_mega") else ""
    def_mega = " 💎" if def_poke.get("is_mega") else ""

    ui_text = (
        f"{log_content}\n\n\n"
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
        for i, m in enumerate(active_poke["moves"]):
            m_name = escape_md(m['name'])
            m_type = m['type']
            m_emoji = TYPE_EMOJIS.get(m_type, '')
            # Appends the emoji directly inside the brackets! Example: [Ground ⛰️]
            m_type_display = escape_md(f"{m_type} {m_emoji}".strip())
            
            m_pow = m.get('power', 0)
            m_acc = m.get('acc', 100)
            
            moves_block += f" {m_name} \\[{m_type_display}\\]\n Power: {m_pow}, Accuracy: {m_acc}\n"
            
            # Button still has the 1️⃣ 2️⃣ icons for easy clicking
            icon = ["1️⃣", "2️⃣", "3️⃣", "4️⃣"][i] if i < 4 else "🔹"
            kb.insert(types.InlineKeyboardButton(f"{icon} {m['name']}", callback_data=f"pvp_move_{battle_id}_{turn}_{i}"))
            
        ui_text += moves_block
        
        if active_poke.get("can_mega") and not active_poke.get("is_mega"):
            kb.row(types.InlineKeyboardButton("💎 Mega Evolve", callback_data=f"pvp_mega_{battle_id}_{turn}"))
            
        kb.row(types.InlineKeyboardButton("🔄 Switch", callback_data=f"pvp_swmenu_{battle_id}_{turn}"),
               types.InlineKeyboardButton("🏃 Run", callback_data=f"pvp_confirmrun_{battle_id}_{turn}"))
               
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

    try: bot.edit_message_text(ui_text, chat_id, battle_id, reply_markup=kb, parse_mode="MarkdownV2")
    except Exception as e: logger.error(f"UI Update error: {e}")

# --- COMMAND HANDLER ---
def handle_pvp_command(bot, message):
    if not message.reply_to_message: return bot.reply_to(message, escape_md("⚠️ Reply to a user to challenge them!"))
    p1_id, p2_id = message.from_user.id, message.reply_to_message.from_user.id
    if p1_id == p2_id: return bot.reply_to(message, escape_md("❌ You can't challenge yourself!"))
    
    if is_in_battle(p1_id) or is_in_battle(p2_id): 
        return bot.reply_to(message, escape_md("❌ Someone is already in a battle!"))

    # AUTO-SOLVE CONFLICTS: Clear old pending challenges for the sender
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
    
    chal = {"name": message.from_user.first_name, "p2_name": message.reply_to_message.from_user.first_name,
            "timer": timer, "p1_id": p1_id, "p2_id": p2_id, "chat_id": message.chat.id, 
            "mode": mode, "size": size, "can_switch": can_switch}
    
    pending_challenges[sent.message_id] = chal
    update_challenge_message(bot, message.chat.id, sent.message_id, chal)

# --- CALLBACK HANDLER ---
def handle_pvp_callback(bot, call):
    try:
        parts = call.data.split("_")
        action = parts[1]
        
        # --- SETTINGS MENU ---
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
        elif action == "setsave":
            chal = pending_challenges.get(call.message.message_id)
            if chal and call.from_user.id == chal["p1_id"]: 
                db.update_pvp_settings(chal["p1_id"], chal["mode"], chal["size"], chal["can_switch"])
                bot.answer_callback_query(call.id, "✅ Defaults Saved!", show_alert=True)
            return
        elif action == "setback":
            chal = pending_challenges.get(call.message.message_id)
            if chal and call.from_user.id == chal["p1_id"]: 
                update_challenge_message(bot, call.message.chat.id, call.message.message_id, chal)
            return

        # --- PRE-BATTLE ---
        if action == "accept":
            p1_id, p2_id = int(parts[2]), int(parts[3])
            
            if call.from_user.id != p2_id: 
                return bot.answer_callback_query(call.id, "❌ Not your challenge!", show_alert=True)
            
            battle_id = call.message.message_id
            chal_data = pending_challenges.pop(battle_id, None)
            
            if not chal_data: 
                return bot.answer_callback_query(call.id, "This challenge has expired or was already answered!")
            
            chal_data["timer"].cancel()
            bot.answer_callback_query(call.id, "Preparing the arena...")

            if LOG_GROUP_ID:
                try: bot.send_message(LOG_GROUP_ID, f"⚔️ *Battle Started:* [{escape_md(chal_data['name'])}](tg://user?id={chal_data['p1_id']}) 🆚 [{escape_md(chal_data['p2_name'])}](tg://user?id={chal_data['p2_id']})", parse_mode="MarkdownV2")
                except: pass
            
            def setup():
                bot.edit_message_text("🔄 *Drafting Teams\\.\\.\\.*", call.message.chat.id, battle_id, parse_mode="MarkdownV2")
                t1 = asyncio.run(generate_random_team(chal_data["mode"], chal_data["size"]))
                t2 = asyncio.run(generate_random_team(chal_data["mode"], chal_data["size"]))
                
                for team in [t1, t2]:
                    for p in team: 
                        n = random.choice(NATURES)
                        p["nature"] = n
                        p["can_mega"] = any(m[1].split("-")[0].lower() == p["name"].lower() for m in MEGA_POKEMON)
                        p["is_mega"] = False
                        
                        if n in ["Adamant", "Modest"]: 
                            p["atk"] = int(p["atk"] * 1.1); p["def"] = int(p["def"] * 0.9)
                        elif n in ["Bold", "Impish"]: 
                            p["def"] = int(p["def"] * 1.1); p["atk"] = int(p["atk"] * 0.9)
                        elif n in ["Calm", "Careful"]: 
                            p["def"] = int(p["def"] * 1.1); p["spd"] = int(p["spd"] * 0.9)
                        elif n in ["Jolly", "Timid"]: 
                            p["spd"] = int(p["spd"] * 1.1); p["atk"] = int(p["atk"] * 0.9)
                
                pvp_battles[battle_id] = {
                    "p1_id": chal_data["p1_id"], "p1_name": chal_data["name"], "p1_team": t1, "p1_idx": 0,
                    "p2_id": chal_data["p2_id"], "p2_name": chal_data["p2_name"], "p2_team": t2, "p2_idx": 0,
                    "can_switch": chal_data["can_switch"], "state": "menu", "log": "", "timer": None
                }
                
                pvp_battles[battle_id]["current_turn"] = get_faster_player(pvp_battles[battle_id])
                faster_name = pvp_battles[battle_id][pvp_battles[battle_id]['current_turn'] + '_name']
                pvp_battles[battle_id]["log"] = f"⚡ {faster_name}'s speed allows them to move first!"
                
                render_pvp_ui(bot, call.message.chat.id, battle_id)
            threading.Thread(target=setup).start()
            return

        elif action == "decline":
            p1_id, p2_id = int(parts[2]), int(parts[3])
            
            if call.from_user.id != p2_id: 
                return bot.answer_callback_query(call.id, "❌ Only the challenged player can decline.", show_alert=True)
                
            chal_data = pending_challenges.pop(call.message.message_id, None)
            if chal_data: 
                chal_data["timer"].cancel()
                bot.edit_message_text("❌ *Challenge declined\\.*", call.message.chat.id, call.message.message_id, parse_mode="MarkdownV2")
            return

        # --- IN-BATTLE ACTIONS ---
        elif action in ["move", "dosw", "mega", "swmenu", "confirmrun", "run", "back", "viewteam"]:
            battle_id = int(parts[2])
            b = pvp_battles.get(battle_id)
            if not b: return bot.answer_callback_query(call.id, "This battle has ended.")
            turn = parts[3]
            
            if call.from_user.id != b[turn + "_id"]: 
                if action == "viewteam": return bot.answer_callback_query(call.id, "❌ Cannot view opponent's team!", show_alert=True)
                return bot.answer_callback_query(call.id, "❌ Not your buttons!", show_alert=True)
            if action != "viewteam" and b["current_turn"] != turn: 
                return bot.answer_callback_query(call.id, "⏳ Wait for your turn!")

            if action == "move":
                b["current_turn"] = "processing"
                atk = b[turn + "_team"][b[turn + "_idx"]]
                defender = "p2" if turn == "p1" else "p1"
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
                    if random.randint(1, 100) > mv["acc"]:
                        b["log"] += f"💨 {atk['name']}'s {mv['name']} missed!\n"
                    else:
                        mult = get_type_multiplier(mv["type"], dfn["types"])
                        if mult == 0:
                            b["log"] += f"💨 {mv['name']} had no effect on {dfn['name']}!\n"
                        else:
                            stab = 1.5 if mv["type"] in atk["types"] else 1.0
                            crit = 1.5 if random.random() < 0.06 else 1.0
                            dmg = max(1, int(((atk["atk"]/dfn["def"]) * mv["power"] * mult * stab * crit)/2))
                            dfn["hp"] = max(0, dfn["hp"] - dmg)
                            
                            b["log"] += f"⚔️ {atk['name']} used {mv['name']}! ({dmg} DMG)\n"
                            if crit > 1: b["log"] += "🎯 A critical hit!\n"
                            if mult > 1: b["log"] += "🔥 It's super effective!\n"
                            elif mult < 1: b["log"] += "🛡️ It's not very effective...\n"
                            
                            if not dfn.get("status") and mv.get("status_chance", 0) > 0 and dfn["hp"] > 0:
                                if random.randint(1, 100) <= mv["status_chance"]:
                                    dfn["status"] = mv["status_type"]
                                    if mv["status_type"] == "SLP": dfn["sleep_turns"] = random.randint(1, 3)
                                    b["log"] += f"🦠 {dfn['name']} was {mv['status_type']}!\n"

                if atk["hp"] > 0:
                    if atk.get("status") == "BRN":
                        dmg = max(1, atk["max_hp"] // 16); atk["hp"] = max(0, atk["hp"] - dmg)
                        b["log"] += f"🔥 {atk['name']} is hurt by its burn!\n"
                    elif atk.get("status") == "PSN":
                        dmg = max(1, atk["max_hp"] // 8); atk["hp"] = max(0, atk["hp"] - dmg)
                        b["log"] += f"☠️ {atk['name']} is hurt by poison!\n"

                if dfn["hp"] <= 0:
                    dfn["hp"] = 0; dfn["status"] = None
                    b["log"] += f"\n💀 {dfn['name']} fainted!"
                    if all(p["hp"] <= 0 for p in b[defender + "_team"]):
                        bot.edit_message_text(f"{escape_md(b['log'])}\n\n🏆 *{escape_md(b[turn+'_name'])} WINS\\!*", call.message.chat.id, battle_id, parse_mode="MarkdownV2")
                        if LOG_GROUP_ID:
                            try: bot.send_message(LOG_GROUP_ID, f"🏆 *Battle Ended:* [{escape_md(b[turn+'_name'])}](tg://user?id={b[turn+'_id']}) won a PvP match\\!", parse_mode="MarkdownV2")
                            except: pass
                        tasks.update_task_pvp(b[turn + "_id"])
                        return end_battle(battle_id)
                    b["state"] = "force_switch"; b["current_turn"] = defender
                elif atk["hp"] <= 0:
                    atk["hp"] = 0; atk["status"] = None
                    b["log"] += f"\n💀 {atk['name']} fainted from status effect!"
                    if all(p["hp"] <= 0 for p in b[turn + "_team"]):
                        bot.edit_message_text(f"{escape_md(b['log'])}\n\n🏆 *{escape_md(b[defender+'_name'])} WINS\\!*", call.message.chat.id, battle_id, parse_mode="MarkdownV2")
                        if LOG_GROUP_ID:
                            try: bot.send_message(LOG_GROUP_ID, f"🏆 *Battle Ended:* [{escape_md(b[defender+'_name'])}](tg://user?id={b[defender+'_id']}) won a PvP match\\!", parse_mode="MarkdownV2")
                            except: pass
                        tasks.update_task_pvp(b[defender + "_id"])
                        return end_battle(battle_id)
                    b["state"] = "force_switch"; b["current_turn"] = turn
                else:
                    b["current_turn"] = defender
                
                render_pvp_ui(bot, call.message.chat.id, battle_id)

            elif action == "dosw":
                idx = int(parts[4])
                p = b[turn+"_team"][idx]
                if p["hp"] <= 0: return bot.answer_callback_query(call.id, "Pokemon is fainted!")
                if idx == b[turn+"_idx"]: return bot.answer_callback_query(call.id, "Already out!")
                
                b["current_turn"] = "processing"
                old_name = b[turn+"_team"][b[turn+"_idx"]]["name"]
                b[turn+"_idx"] = idx
                b["log"] = f"🔄 {old_name} returned, {p['name']} took the field!"
                
                b["state"] = "menu"
                b["current_turn"] = get_faster_player(b)
                render_pvp_ui(bot, call.message.chat.id, battle_id)

            elif action == "swmenu":
                if not b["can_switch"]: return bot.answer_callback_query(call.id, "🚫 Switching is disabled!", show_alert=True)
                b["state"] = "switch_menu"; render_pvp_ui(bot, call.message.chat.id, battle_id)
                
            elif action == "mega":
                p = b[turn+"_team"][b[turn+"_idx"]]
                if p.get("is_mega"): return bot.answer_callback_query(call.id, "Already Mega Evolved!")
                p.update({"is_mega": True, "atk": int(p["atk"]*1.3), "def": int(p["def"]*1.2), "spd": int(p["spd"]*1.2), "name": f"Mega {p['name']}"})
                b["log"] = f"💎 {p['name']} Mega Evolved!"
                render_pvp_ui(bot, call.message.chat.id, battle_id)
                
            elif action == "confirmrun": 
                b["state"] = "run_confirm"; render_pvp_ui(bot, call.message.chat.id, battle_id)
                
            elif action == "run": 
                end_battle(battle_id)
                bot.edit_message_text(f"🏃 *{escape_md(b[turn+'_name'])} fled\\!*", call.message.chat.id, battle_id, parse_mode="MarkdownV2")
                if LOG_GROUP_ID:
                    try: bot.send_message(LOG_GROUP_ID, f"🏃 *Battle Ended:* [{escape_md(b[turn+'_name'])}](tg://user?id={b[turn+'_id']}) fled from battle\\.", parse_mode="MarkdownV2")
                    except: pass
                
            elif action == "back": 
                b["state"] = "menu"; render_pvp_ui(bot, call.message.chat.id, battle_id)
                
            elif action == "viewteam":
                lines = []
                for i, p in enumerate(b[turn + '_team']):
                    emojis = "/".join([TYPE_EMOJIS.get(t.strip(), '⚪') for t in p['types'].split('/')])
                    status_icon = '💀' if p['hp'] <= 0 else ('💤' if p.get('status') == 'SLP' else ('🧊' if p.get('status') == 'FRZ' else ('🔥' if p.get('status') == 'BRN' else ('☠️' if p.get('status') == 'PSN' else ('⚡' if p.get('status') == 'PAR' else '🟢')))))
                    lines.append(f"{i+1}. {p['name']} [{emojis}] - {p['nature']} {status_icon}")
                
                bot.answer_callback_query(call.id, "\n".join(lines), show_alert=True)

    except Exception as e: 
        logger.error(f"PvP Callback Error: {e}")
