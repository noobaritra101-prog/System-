# pvp.py
import time
import random
import threading
import asyncio
from telebot import types
import database as db
from api_utils import escape_md, generate_random_team
from config import logger, MEGA_POKEMON

pvp_battles = {}
pending_challenges = {} 

# --- BATTLE DATA ---
NATURES = ["Adamant", "Jolly", "Modest", "Timid", "Bold", "Calm", "Careful", "Impish"]

TYPE_EMOJIS = {
    'Normal': '⚪', 'Fire': '🔥', 'Water': '💧', 'Electric': '⚡', 'Grass': '🌿', 
    'Ice': '❄️', 'Fighting': '🥊', 'Poison': '☠️', 'Ground': '🪨', 'Flying': '🪽', 
    'Psychic': '🔮', 'Bug': '🐛', 'Rock': '🗿', 'Ghost': '👻', 'Dragon': '🐉', 
    'Dark': '🌑', 'Steel': '⚙️', 'Fairy': '✨'
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

# --- TIMEOUT LOGIC ---
def challenge_timeout(bot, chat_id, message_id):
    chal = pending_challenges.pop(message_id, None)
    if chal:
        try:
            bot.edit_message_text("⏳ *Challenge expired\\.*", chat_id, message_id, parse_mode="MarkdownV2")
        except Exception: pass

def battle_timeout(bot, chat_id, battle_id):
    b = pvp_battles.get(battle_id)
    if b:
        turn = b["current_turn"]
        loser_name = b[turn + "_name"]
        winner_name = b["p2_name"] if turn == "p1" else b["p1_name"]
        
        pvp_battles.pop(battle_id, None)
        try:
            bot.edit_message_text(
                f"⏳ *{escape_md(loser_name)} ran out of time\\!*\n\n🏆 *{escape_md(winner_name)} WINS THE BATTLE\\!*", 
                chat_id, battle_id, parse_mode="MarkdownV2"
            )
        except Exception: pass

def end_battle(battle_id):
    b = pvp_battles.pop(battle_id, None)
    if b and "timer" in b and b["timer"]:
        b["timer"].cancel()

# --- HELPER FUNCTIONS ---
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
    """Prevents users from sending/receiving multiple challenges at once."""
    for chal in pending_challenges.values():
        if chal["p1_id"] == user_id or chal["p2_id"] == user_id:
            return True
    return False

def get_hp_bar(current, maximum, length=14):
    if maximum <= 0: return "░" * length
    filled = int((current / maximum) * length)
    filled = max(0, min(length, filled))
    return escape_md("█" * filled + "░" * (length - filled))

# --- UI RENDERER ---
def render_pvp_ui(bot, chat_id, battle_id):
    if battle_id not in pvp_battles: return
    b = pvp_battles[battle_id]
    turn = b["current_turn"]
    
    # 60 Second Turn Timer Reset
    if "timer" in b and b["timer"]:
        b["timer"].cancel()
    b["timer"] = threading.Timer(60.0, battle_timeout, args=(bot, chat_id, battle_id))
    b["timer"].start()
    
    if turn == "p1":
        active_name, active_poke = b["p1_name"], b["p1_team"][b["p1_idx"]]
        def_name, def_poke = b["p2_name"], b["p2_team"][b["p2_idx"]]
    else:
        active_name, active_poke = b["p2_name"], b["p2_team"][b["p2_idx"]]
        def_name, def_poke = b["p1_name"], b["p1_team"][b["p1_idx"]]
    
    log_content = escape_md(b['log']) if b['log'] else "The battle begins\\!"
    
    act_types = escape_md(active_poke['types'].replace('/', ' / '))
    def_types = escape_md(def_poke['types'].replace('/', ' / '))
    
    act_status = f" \\[{escape_md(active_poke.get('status', ''))}\\]" if active_poke.get('status') else ""
    def_status = f" \\[{escape_md(def_poke.get('status', ''))}\\]" if def_poke.get('status') else ""

    act_mega_icon = " 💎" if active_poke.get("is_mega") else ""
    def_mega_icon = " 💎" if def_poke.get("is_mega") else ""

    ui_text = (
        f"{log_content}\n\n\n"
        f"*{escape_md(def_name)}*'s {escape_md(def_poke['name'])}{def_mega_icon} \\[{def_types}\\]{def_status}\n"
        f"Lv\\. 100  •  HP {def_poke['hp']}/{def_poke['max_hp']}\n"
        f"{get_hp_bar(def_poke['hp'], def_poke['max_hp'])}\n\n"
        f"Current turn: *{escape_md(active_name)}*\n"
        f"*{escape_md(active_name)}*'s {escape_md(active_poke['name'])}{act_mega_icon} \\[{act_types}\\]{act_status}\n"
        f"Lv\\. 100  •  HP {active_poke['hp']}/{active_poke['max_hp']}\n"
        f"{get_hp_bar(active_poke['hp'], active_poke['max_hp'])}\n\n"
    )

    kb = types.InlineKeyboardMarkup(row_width=2)
    
    if b["state"] == "menu":
        moves_block = ""
        for m in active_poke["moves"]:
            moves_block += f" {escape_md(m['name'])} \\[{escape_md(m['type'])}\\]\n Power: {m['power']}, Accuracy: {m['acc']}\n"
        ui_text += moves_block
        
        moves = active_poke["moves"]
        kb.add(
            types.InlineKeyboardButton(f"{moves[0]['name']}", callback_data=f"pvp_move_{battle_id}_{turn}_0"),
            types.InlineKeyboardButton(f"{moves[1]['name']}", callback_data=f"pvp_move_{battle_id}_{turn}_1"),
            types.InlineKeyboardButton(f"{moves[2]['name']}", callback_data=f"pvp_move_{battle_id}_{turn}_2"),
            types.InlineKeyboardButton(f"{moves[3]['name']}", callback_data=f"pvp_move_{battle_id}_{turn}_3")
        )
        
        if active_poke.get("can_mega") and not active_poke.get("is_mega"):
            kb.row(types.InlineKeyboardButton("💎 Mega Evolve", callback_data=f"pvp_mega_{battle_id}_{turn}"))
            
        kb.row(
            types.InlineKeyboardButton("🔄 Switch", callback_data=f"pvp_swmenu_{battle_id}_{turn}"),
            types.InlineKeyboardButton("🏃 Run", callback_data=f"pvp_confirmrun_{battle_id}_{turn}")
        )

    elif b["state"] in ["switch_menu", "force_switch"]:
        ui_text += f" 🔄 Choose a Pokémon to switch into:\n" if b["state"] == "switch_menu" else f" 💀 Choose a replacement Pokémon:\n"
        
        buttons = []
        for i in range(6):
            p = b[turn + "_team"][i]
            icon = "🔴" if p["hp"] > 0 else "💀"
            buttons.append(types.InlineKeyboardButton(f"{icon} {i+1}", callback_data=f"pvp_dosw_{battle_id}_{turn}_{i}"))
        
        kb.add(buttons[0], buttons[1], buttons[2])
        kb.add(buttons[3], buttons[4], buttons[5])
        
        kb.row(types.InlineKeyboardButton("📋 View Team", callback_data=f"pvp_viewteam_{battle_id}_{turn}"))
        if b["state"] == "switch_menu":
            kb.row(types.InlineKeyboardButton("🔙 Back", callback_data=f"pvp_back_{battle_id}_{turn}"))

    elif b["state"] == "run_confirm":
        ui_text += f" ⚠️ Are you sure you want to flee the battle?\n"
        kb.row(
            types.InlineKeyboardButton("✅ Confirm Flee", callback_data=f"pvp_run_{battle_id}_{turn}"),
            types.InlineKeyboardButton("❌ Cancel", callback_data=f"pvp_back_{battle_id}_{turn}")
        )

    try:
        bot.edit_message_text(ui_text, chat_id, battle_id, reply_markup=kb, parse_mode="MarkdownV2")
    except Exception as e:
        logger.error(f"UI Update error: {e}")

# --- COMMAND AND CALLBACK HANDLERS ---
def handle_pvp_command(bot, message):
    if not message.reply_to_message: return bot.reply_to(message, escape_md("⚠️ Reply to a user to challenge them!"))
    p1_id, p2_id = message.from_user.id, message.reply_to_message.from_user.id
    if p1_id == p2_id: return bot.reply_to(message, escape_md("❌ You can't challenge yourself!"))
    
    # Check if either player is already busy
    if is_in_battle(p1_id) or is_in_battle(p2_id): 
        return bot.reply_to(message, escape_md("❌ Someone is already in a battle!"))
    if is_in_pending_challenge(p1_id) or is_in_pending_challenge(p2_id): 
        return bot.reply_to(message, escape_md("❌ Someone already has a pending challenge!"))

    kb = types.InlineKeyboardMarkup()
    kb.add(
        types.InlineKeyboardButton("⚔️ Accept", callback_data=f"pvp_accept_{p1_id}_{p2_id}"),
        types.InlineKeyboardButton("❌ Decline", callback_data=f"pvp_decline_{p1_id}_{p2_id}")
    )
    p1_name = escape_md(message.from_user.first_name)
    p2_name = escape_md(message.reply_to_message.from_user.first_name)
    
    sent = bot.reply_to(message, f"🥊 *{p1_name}* challenged *{p2_name}* to a 6v6 Random Battle\\!\n\n_You have 60 seconds to accept\\._", reply_markup=kb, parse_mode="MarkdownV2")
    
    # Start Challenge Timer
    timer = threading.Timer(60.0, challenge_timeout, args=(bot, message.chat.id, sent.message_id))
    timer.start()
    pending_challenges[sent.message_id] = {"name": message.from_user.first_name, "timer": timer, "p1_id": p1_id, "p2_id": p2_id}

def handle_pvp_callback(bot, call):
    try:
        parts = call.data.split("_")
        action = parts[1]
        
        # --- PRE-BATTLE ACTIONS ---
        if action == "accept":
            p1_id, p2_id = int(parts[2]), int(parts[3])
            if call.from_user.id != p2_id: return bot.answer_callback_query(call.id, "❌ Not your challenge!", show_alert=True)
            
            battle_id = call.message.message_id
            chal_data = pending_challenges.pop(battle_id, None)
            if not chal_data: return bot.answer_callback_query(call.id, "This challenge has expired!")
            chal_data["timer"].cancel() 
            
            bot.answer_callback_query(call.id, "Preparing the arena...")
            chat_id = call.message.chat.id
            p1_name = chal_data["name"]
            p2_name = call.from_user.first_name
            
            def setup_battle():
                t1 = asyncio.run(generate_random_team())
                t2 = asyncio.run(generate_random_team())
                if len(t1) < 6 or len(t2) < 6: return bot.edit_message_text("❌ Connection Error. Try again.", chat_id, battle_id)
                
                for team in [t1, t2]:
                    for p in team:
                        p["nature"] = random.choice(NATURES)
                        p["can_mega"] = any(m[1].split("-")[0].lower() == p["name"].lower() for m in MEGA_POKEMON)
                        p["is_mega"] = False

                first_turn = "p1" if t1[0]['spd'] >= t2[0]['spd'] else "p2"
                fast_name = p1_name if first_turn == "p1" else p2_name
                log = f"⚡ {fast_name}'s speed allows them to move first!"
                
                pvp_battles[battle_id] = {
                    "p1_id": p1_id, "p1_name": p1_name, "p1_team": t1, "p1_idx": 0,
                    "p2_id": p2_id, "p2_name": p2_name, "p2_team": t2, "p2_idx": 0,
                    "current_turn": first_turn, "state": "menu", "log": log,
                    "next_turn_after_switch": None, "timer": None
                }
                render_pvp_ui(bot, chat_id, battle_id)
            threading.Thread(target=setup_battle).start()
            return

        elif action == "decline":
            if call.from_user.id != int(parts[3]): return bot.answer_callback_query(call.id, "❌ Only the challenged player can decline.", show_alert=True)
            chal_data = pending_challenges.pop(call.message.message_id, None)
            if chal_data: chal_data["timer"].cancel()
            bot.edit_message_text("❌ *Challenge declined\\.*", call.message.chat.id, call.message.message_id, parse_mode="MarkdownV2")
            return


        # --- IN-BATTLE ACTIONS ---
        if action in ["viewteam", "mega", "confirmrun", "run", "swmenu", "back", "dosw", "move"]:
            battle_id = int(parts[2])
            b = pvp_battles.get(battle_id)
            if not b: return bot.answer_callback_query(call.id, "This battle has already ended.")
            
            turn = parts[3]
            
            # Security Check: Reject if the clicker does not own these buttons
            if call.from_user.id != b[turn + "_id"]:
                if action == "viewteam":
                    return bot.answer_callback_query(call.id, "❌ You cannot view your opponent's team!", show_alert=True)
                else:
                    return bot.answer_callback_query(call.id, "❌ These are not your buttons!", show_alert=True)
            
            # Action Routing
            if action == "viewteam":
                team_str = ""
                for i, p in enumerate(b[turn + "_team"]):
                    emojis = [TYPE_EMOJIS.get(t.strip(), '⚪') for t in p['types'].split('/')]
                    emoji_str = "/".join(emojis)
                    status = "💀" if p["hp"] <= 0 else ("💤" if p.get("status")=="SLP" else "🟢")
                    name_display = f"Mega {p['name']}" if p.get("is_mega") else p['name']
                    team_str += f"{i+1}. {name_display} [{emoji_str}] - {p['nature']} {status}\n"
                bot.answer_callback_query(call.id, team_str, show_alert=True)

            elif action == "mega":
                p = b[turn + "_team"][b[turn + "_idx"]]
                p["is_mega"] = True
                p["name"] = f"Mega {p['name']}"
                p["atk"] = int(p["atk"] * 1.3)
                p["def"] = int(p["def"] * 1.2)
                p["spd"] = int(p["spd"] * 1.2)
                b["log"] = f"💎 {p['name']} reacted to its Mega Stone!"
                render_pvp_ui(bot, call.message.chat.id, call.message.message_id)

            elif action == "confirmrun":
                b["state"] = "run_confirm"
                render_pvp_ui(bot, call.message.chat.id, call.message.message_id)

            elif action == "run":
                runner_name = b[turn + "_name"]
                end_battle(battle_id)
                bot.edit_message_text(f"🏃‍♂️ *{escape_md(runner_name)} fled the battle\\!*", call.message.chat.id, call.message.message_id, parse_mode="MarkdownV2")

            elif action == "swmenu":
                b["state"] = "switch_menu"
                render_pvp_ui(bot, call.message.chat.id, call.message.message_id)

            elif action == "back":
                b["state"] = "menu"
                render_pvp_ui(bot, call.message.chat.id, call.message.message_id)

            elif action == "dosw":
                idx = int(parts[4])
                p = b[turn + "_team"][idx]
                if p["hp"] <= 0: return bot.answer_callback_query(call.id, "That Pokémon is fainted!")
                if idx == b[turn + "_idx"]: return bot.answer_callback_query(call.id, "That Pokémon is already out!")
                
                old_name = b[turn+"_team"][b[turn+"_idx"]]["name"]
                b[turn+"_idx"] = idx
                b["log"] = f"🔄 {old_name} switched out, {p['name']} took the field!"
                
                if b["state"] == "force_switch":
                    b["current_turn"] = b["next_turn_after_switch"]
                else:
                    b["current_turn"] = "p2" if turn == "p1" else "p1"
                    
                b["state"] = "menu"
                render_pvp_ui(bot, call.message.chat.id, call.message.message_id)

            elif action == "move":
                m_idx = int(parts[4])
                atk_team = b[turn + "_team"]
                atk_p = atk_team[b[turn + "_idx"]]
                
                defender = "p2" if turn == "p1" else "p1"
                def_team = b[defender + "_team"]
                def_p = def_team[b[defender + "_idx"]]
                
                move = atk_p["moves"][m_idx]
                b["log"] = ""
                can_attack = True
                
                if atk_p.get("status") == "PAR" and random.random() < 0.25:
                    can_attack = False; b["log"] += f"⚡ {atk_p['name']} is paralyzed! It can't move!\n"
                elif atk_p.get("status") == "SLP":
                    atk_p["sleep_turns"] -= 1
                    if atk_p["sleep_turns"] <= 0: atk_p["status"] = None; b["log"] += f"💤 {atk_p['name']} woke up!\n"
                    else: can_attack = False; b["log"] += f"💤 {atk_p['name']} is fast asleep.\n"
                elif atk_p.get("status") == "FRZ":
                    if random.random() < 0.20: atk_p["status"] = None; b["log"] += f"🧊 {atk_p['name']} thawed out!\n"
                    else: can_attack = False; b["log"] += f"🧊 {atk_p['name']} is frozen solid!\n"

                if can_attack:
                    if random.randint(1, 100) > move["acc"]:
                        b["log"] += f"💨 {atk_p['name']}'s {move['name']} missed!\n"
                    else:
                        stab = 1.5 if move["type"] in atk_p["types"] else 1.0
                        type_mult = get_type_multiplier(move["type"], def_p["types"])
                        
                        if type_mult == 0:
                            b["log"] += f"💨 {move['name']} had no effect on {def_p['name']}!\n"
                        else:
                            is_crit = random.randint(1, 16) == 1
                            crit_mult = 1.5 if is_crit else 1.0
                            
                            dmg = max(1, int(((atk_p["atk"] / def_p["def"]) * move["power"] * stab * type_mult * crit_mult) / 2))
                            def_p["hp"] = max(0, def_p["hp"] - dmg)
                            b["log"] += f"⚔️ {atk_p['name']} used {move['name']}! ({dmg} DMG)\n"
                            
                            if is_crit: b["log"] += "🎯 A critical hit!\n"
                            if type_mult > 1: b["log"] += "🔥 It's super effective!\n"
                            elif type_mult < 1: b["log"] += "🛡️ It's not very effective...\n"
                            
                            if not def_p.get("status") and move.get("status_chance", 0) > 0 and def_p["hp"] > 0:
                                if random.randint(1, 100) <= move["status_chance"]:
                                    def_p["status"] = move["status_type"]
                                    if move["status_type"] == "SLP": def_p["sleep_turns"] = random.randint(1, 3)
                                    b["log"] += f"🦠 {def_p['name']} was {move['status_type']}!\n"

                if atk_p["hp"] > 0:
                    if atk_p.get("status") == "BRN":
                        burn_dmg = max(1, atk_p["max_hp"] // 16)
                        atk_p["hp"] = max(0, atk_p["hp"] - burn_dmg)
                        b["log"] += f"🔥 {atk_p['name']} is hurt by its burn!\n"
                    elif atk_p.get("status") == "PSN":
                        psn_dmg = max(1, atk_p["max_hp"] // 8)
                        atk_p["hp"] = max(0, atk_p["hp"] - psn_dmg)
                        b["log"] += f"☠️ {atk_p['name']} is hurt by poison!\n"

                def check_faints(t_name, t_team, t_idx):
                    if t_team[t_idx]["hp"] <= 0:
                        t_team[t_idx]["hp"] = 0
                        b["log"] += f"\n💀 {t_team[t_idx]['name']} fainted!"
                        t_team[t_idx]["status"] = None 
                        if sum(1 for p in t_team if p["hp"] > 0) == 0: return "game_over"
                        return "fainted"
                    return "alive"

                def_state = check_faints(defender, def_team, b[defender + "_idx"])
                if def_state == "game_over":
                    bot.edit_message_text(f"{escape_md(b['log'])}\n\n🏆 *{escape_md(b[turn + '_name'])} WINS THE BATTLE\\!*", call.message.chat.id, battle_id, parse_mode="MarkdownV2")
                    end_battle(battle_id)
                    return
                elif def_state == "fainted":
                    b["state"] = "force_switch"; b["current_turn"] = defender; b["next_turn_after_switch"] = defender
                    render_pvp_ui(bot, call.message.chat.id, battle_id)
                    return

                atk_state = check_faints(turn, atk_team, b[turn + "_idx"])
                if atk_state == "game_over":
                    bot.edit_message_text(f"{escape_md(b['log'])}\n\n🏆 *{escape_md(b[defender + '_name'])} WINS THE BATTLE\\!*", call.message.chat.id, battle_id, parse_mode="MarkdownV2")
                    end_battle(battle_id)
                    return
                elif atk_state == "fainted":
                    b["state"] = "force_switch"; b["current_turn"] = turn; b["next_turn_after_switch"] = defender
                    render_pvp_ui(bot, call.message.chat.id, battle_id)
                    return

                b["current_turn"] = defender
                render_pvp_ui(bot, call.message.chat.id, battle_id)

    except Exception as e:
        logger.error(f"PvP Callback error: {e}")
