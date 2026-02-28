# pvp.py
import time
import random
import threading
import asyncio
from telebot import types
import database as db
from api_utils import escape_md, generate_random_team
from config import logger

pvp_battles = {}
pending_challenges = {} 

# --- TYPE EFFECTIVENESS CHART ---
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

def get_hp_bar(current, maximum, length=14):
    if maximum <= 0: return "░" * length
    filled = int((current / maximum) * length)
    filled = max(0, min(length, filled))
    # Using full blocks and light shades for a clean look
    return escape_md("█" * filled + "░" * (length - filled))

def render_pvp_ui(bot, chat_id, battle_id):
    if battle_id not in pvp_battles: return
    b = pvp_battles[battle_id]
    turn = b["current_turn"]
    
    # Determine active vs defending player based on turn
    if turn == "p1":
        active_name, active_poke = b["p1_name"], b["p1_team"][b["p1_idx"]]
        def_name, def_poke = b["p2_name"], b["p2_team"][b["p2_idx"]]
    else:
        active_name, active_poke = b["p2_name"], b["p2_team"][b["p2_idx"]]
        def_name, def_poke = b["p1_name"], b["p1_team"][b["p1_idx"]]
    
    log_content = b['log'] if b['log'] else "The battle begins!"
    safe_log = escape_md(log_content)
    
    # Replace slashes with spaced slashes for aesthetic [Dark / Flying]
    def_types = escape_md(def_poke['types'].replace('/', ' / '))
    act_types = escape_md(active_poke['types'].replace('/', ' / '))

    ui_text = (
        f"{safe_log}\n\n"
        f"*{escape_md(def_name)}*'s {escape_md(def_poke['name'])} \\[{def_types}\\]\n"
        f"Lv\\. 100  •  HP {def_poke['hp']}/{def_poke['max_hp']}\n"
        f"{get_hp_bar(def_poke['hp'], def_poke['max_hp'])}\n\n"
        f"Current turn: *{escape_md(active_name)}*\n"
        f"*{escape_md(active_name)}*'s {escape_md(active_poke['name'])} \\[{act_types}\\]\n"
        f"Lv\\. 100  •  HP {active_poke['hp']}/{active_poke['max_hp']}\n"
        f"{get_hp_bar(active_poke['hp'], active_poke['max_hp'])}\n\n"
    )

    if b["state"] == "menu":
        moves_block = ""
        for m in active_poke["moves"]:
            m_name = escape_md(m['name'])
            m_type = escape_md(m['type'])
            # Using MarkdownV2 blockquote syntax (\>) and bolding the move name
            moves_block += f"\\ *{m_name}* \\[{m_type}\\]\n\\ Power: {m['power']}, Accuracy: {m['acc']}\n"
        ui_text += moves_block
    elif b["state"] == "switch_menu":
        ui_text += f"\\ 🔄 Choose a Pokémon to switch into:\n"
    elif b["state"] == "force_switch":
        ui_text += f"\\ 💀 Your Pokémon fainted\\! Choose a replacement:\n"
    
    # Inline Keyboard Setup
    kb = types.InlineKeyboardMarkup(row_width=2)
    if b["state"] == "menu":
        moves = active_poke["moves"]
        kb.add(
            types.InlineKeyboardButton(f"{moves[0]['name']}", callback_data=f"pvp_move_{battle_id}_{turn}_0"),
            types.InlineKeyboardButton(f"{moves[1]['name']}", callback_data=f"pvp_move_{battle_id}_{turn}_1"),
            types.InlineKeyboardButton(f"{moves[2]['name']}", callback_data=f"pvp_move_{battle_id}_{turn}_2"),
            types.InlineKeyboardButton(f"{moves[3]['name']}", callback_data=f"pvp_move_{battle_id}_{turn}_3")
        )
        kb.row(types.InlineKeyboardButton("🔄 Switch", callback_data=f"pvp_switchmenu_{battle_id}_{turn}"))
    
    elif b["state"] in ["switch_menu", "force_switch"]:
        team = b[turn + "_team"]
        for i, poke in enumerate(team):
            if poke["hp"] > 0 and i != b[turn + "_idx"]:
                kb.row(types.InlineKeyboardButton(f"🔄 {poke['name']} ({poke['hp']}/{poke['max_hp']})", callback_data=f"pvp_doswitch_{battle_id}_{turn}_{i}"))
        
        if b["state"] == "switch_menu":
            kb.row(types.InlineKeyboardButton("🔙 Back", callback_data=f"pvp_back_{battle_id}_{turn}"))
            
    kb.row(types.InlineKeyboardButton("🏃‍♂️ Run", callback_data=f"pvp_run_{battle_id}"))
        
    try:
        bot.edit_message_text(ui_text, chat_id, battle_id, reply_markup=kb, parse_mode="MarkdownV2")
    except Exception as e:
        logger.error(f"UI Update error: {e}")

def handle_pvp_command(bot, message):
    if not message.reply_to_message: 
        return bot.reply_to(message, escape_md("⚠️ You must reply to another player's message to challenge them!"))
    p1_id, p2_id = message.from_user.id, message.reply_to_message.from_user.id
    if p1_id == p2_id: return bot.reply_to(message, escape_md("❌ You can't challenge yourself!"))
    if is_in_battle(p1_id) or is_in_battle(p2_id): return bot.reply_to(message, escape_md("❌ One of the players is already in a battle!"))

    kb = types.InlineKeyboardMarkup()
    kb.add(
        types.InlineKeyboardButton("⚔️ Accept", callback_data=f"pvp_accept_{p1_id}_{p2_id}"),
        types.InlineKeyboardButton("❌ Decline", callback_data=f"pvp_decline_{p1_id}_{p2_id}")
    )
    # Safely escape names for the initial challenge message
    p1_name = escape_md(message.from_user.first_name)
    p2_name = escape_md(message.reply_to_message.from_user.first_name)
    
    sent = bot.reply_to(message, f"🥊 *{p1_name}* challenged *{p2_name}* to a 6v6 Random Battle\\!\n\nDo you accept?", reply_markup=kb, parse_mode="MarkdownV2")
    pending_challenges[sent.message_id] = message.from_user.first_name

def handle_pvp_callback(bot, call):
    try:
        if call.data.startswith("pvp_accept_"):
            parts = call.data.split("_")
            p1_id, p2_id = int(parts[2]), int(parts[3])
            if call.from_user.id != p2_id: return bot.answer_callback_query(call.id, "Only the challenged player can accept!")
            bot.answer_callback_query(call.id, "Challenge Accepted! Preparing the arena...")
            
            battle_id = call.message.message_id
            chat_id = call.message.chat.id
            p1_name = pending_challenges.pop(battle_id, "Player 1")
            p2_name = call.from_user.first_name

            def setup_battle():
                try:
                    bot.edit_message_text("🔄 *Connecting to the PvP Arena\\.\\.\\.*", chat_id, battle_id, parse_mode="MarkdownV2")
                    p1_team = asyncio.run(generate_random_team())
                    p2_team = asyncio.run(generate_random_team())
                    if len(p1_team) < 6 or len(p2_team) < 6: return bot.edit_message_text("❌ *API Error\\. Try again\\.*", chat_id, battle_id, parse_mode="MarkdownV2")
                    
                    pvp_battles[battle_id] = {
                        "p1_id": p1_id, "p1_name": p1_name, "p1_team": p1_team, "p1_idx": 0, 
                        "p2_id": p2_id, "p2_name": p2_name, "p2_team": p2_team, "p2_idx": 0, 
                        "current_turn": "p1", "next_turn_after_switch": "p1",
                        "state": "menu", "log": ""
                    }
                    render_pvp_ui(bot, chat_id, battle_id)
                except Exception as e: logger.error(f"PvP Setup Error: {e}")
            threading.Thread(target=setup_battle).start()

        elif call.data.startswith("pvp_decline_"):
            if call.from_user.id != int(call.data.split("_")[3]): return bot.answer_callback_query(call.id, "Only the challenged player can decline.")
            bot.edit_message_text("❌ *Challenge declined\\.*", call.message.chat.id, call.message.message_id, parse_mode="MarkdownV2")

        elif call.data.startswith("pvp_"):
            parts = call.data.split("_")
            action = parts[1]
            battle_id = int(parts[2])
            
            if battle_id not in pvp_battles: return bot.answer_callback_query(call.id, "This battle is over.")
            b = pvp_battles[battle_id]

            if action == "run":
                if call.from_user.id == b["p1_id"]: runner = b["p1_name"]
                elif call.from_user.id == b["p2_id"]: runner = b["p2_name"]
                else: return bot.answer_callback_query(call.id, "You are not in this battle!")
                    
                bot.answer_callback_query(call.id, "You fled!")
                bot.edit_message_text(f"🏃‍♂️ *{escape_md(runner)} ran away from the battle\\!*", call.message.chat.id, battle_id, parse_mode="MarkdownV2")
                pvp_battles.pop(battle_id, None)
                return

            player_num = parts[3]
            if call.from_user.id != b[player_num + "_id"]: return bot.answer_callback_query(call.id, "These are not your buttons!")
            if b["current_turn"] != player_num: return bot.answer_callback_query(call.id, "It is not your turn!")

            atk_team = b[player_num + "_team"]
            atk_poke = atk_team[b[player_num + "_idx"]]
            defender = "p2" if player_num == "p1" else "p1"
            def_team = b[defender + "_team"]
            def_poke = def_team[b[defender + "_idx"]]

            if action == "switchmenu":
                b["state"] = "switch_menu"
                render_pvp_ui(bot, call.message.chat.id, battle_id)
                return

            elif action == "back":
                b["state"] = "menu"
                render_pvp_ui(bot, call.message.chat.id, battle_id)
                return

            elif action == "doswitch":
                idx = int(parts[4])
                if atk_team[idx]["hp"] <= 0: return bot.answer_callback_query(call.id, "That Pokémon is fainted!")
                
                b[player_num + "_idx"] = idx
                b["log"] = f"🔄 {b[player_num + '_name']} sent out {atk_team[idx]['name']}!"
                
                if b["state"] == "force_switch":
                    b["current_turn"] = b["next_turn_after_switch"]
                else:
                    b["current_turn"] = defender
                    
                b["state"] = "menu"
                render_pvp_ui(bot, call.message.chat.id, battle_id)
                return

            elif action == "move":
                move_idx = int(parts[4])
                move_data = atk_poke["moves"][move_idx]
                b["log"] = ""
                can_attack = True
                
                # Pre-Turn Status
                if atk_poke["status"] == "PAR" and random.random() < 0.25:
                    can_attack = False
                    b["log"] += f"⚡ {atk_poke['name']} is paralyzed! It can't move!\n"
                elif atk_poke["status"] == "SLP":
                    atk_poke["sleep_turns"] -= 1
                    if atk_poke["sleep_turns"] <= 0:
                        atk_poke["status"] = None
                        b["log"] += f"💤 {atk_poke['name']} woke up!\n"
                    else:
                        can_attack = False
                        b["log"] += f"💤 {atk_poke['name']} is fast asleep.\n"
                elif atk_poke["status"] == "FRZ":
                    if random.random() < 0.20:
                        atk_poke["status"] = None
                        b["log"] += f"🧊 {atk_poke['name']} thawed out!\n"
                    else:
                        can_attack = False
                        b["log"] += f"🧊 {atk_poke['name']} is frozen solid!\n"

                if can_attack:
                    if random.randint(1, 100) > move_data["acc"]:
                        b["log"] += f"💨 {atk_poke['name']} used {move_data['name']}, but it missed!\n"
                    else:
                        stab = 1.5 if move_data["type"] in atk_poke["types"] else 1.0
                        type_mult = get_type_multiplier(move_data["type"], def_poke["types"])
                        
                        if type_mult == 0:
                            b["log"] += f"💨 {move_data['name']} had no effect on {def_poke['name']}!\n"
                        else:
                            dmg = max(1, int(((atk_poke["atk"] / def_poke["def"]) * move_data["power"] * stab * type_mult) / 2))
                            def_poke["hp"] = max(0, def_poke["hp"] - dmg)
                            b["log"] += f"⚔️ {atk_poke['name']} used {move_data['name']}! ({dmg} DMG)\n"
                            
                            if type_mult > 1: b["log"] += "🔥 It's super effective!\n"
                            elif type_mult < 1: b["log"] += "🛡️ It's not very effective...\n"
                            
                            if not def_poke["status"] and move_data["status_chance"] > 0 and def_poke["hp"] > 0:
                                if random.randint(1, 100) <= move_data["status_chance"]:
                                    def_poke["status"] = move_data["status_type"]
                                    if move_data["status_type"] == "SLP": def_poke["sleep_turns"] = random.randint(1, 3)
                                    b["log"] += f"🦠 {def_poke['name']} was inflicted with {move_data['status_type']}!\n"

                # Post-Turn Burn/Poison
                if atk_poke["hp"] > 0:
                    if atk_poke["status"] == "BRN":
                        burn_dmg = max(1, atk_poke["max_hp"] // 16)
                        atk_poke["hp"] = max(0, atk_poke["hp"] - burn_dmg)
                        b["log"] += f"🔥 {atk_poke['name']} is hurt by its burn!\n"
                    elif atk_poke["status"] == "PSN":
                        psn_dmg = max(1, atk_poke["max_hp"] // 8)
                        atk_poke["hp"] = max(0, atk_poke["hp"] - psn_dmg)
                        b["log"] += f"☠️ {atk_poke['name']} is hurt by poison!\n"

                def check_faints(t_name, t_team, t_idx):
                    if t_team[t_idx]["hp"] <= 0:
                        t_team[t_idx]["hp"] = 0
                        b["log"] += f"\n💀 {t_team[t_idx]['name']} fainted!"
                        t_team[t_idx]["status"] = None 
                        alive_count = sum(1 for p in t_team if p["hp"] > 0)
                        if alive_count == 0: return "game_over"
                        return "fainted"
                    return "alive"

                def_state = check_faints(defender, def_team, b[defender + "_idx"])
                if def_state == "game_over":
                    bot.edit_message_text(f"{escape_md(b['log'])}\n\n🏆 *{escape_md(b[player_num + '_name'])} WINS THE BATTLE\\!*", call.message.chat.id, battle_id, parse_mode="MarkdownV2")
                    pvp_battles.pop(battle_id, None)
                    return
                elif def_state == "fainted":
                    b["state"] = "force_switch"
                    b["current_turn"] = defender
                    b["next_turn_after_switch"] = defender
                    render_pvp_ui(bot, call.message.chat.id, battle_id)
                    return

                atk_state = check_faints(player_num, atk_team, b[player_num + "_idx"])
                if atk_state == "game_over":
                    bot.edit_message_text(f"{escape_md(b['log'])}\n\n🏆 *{escape_md(b[defender + '_name'])} WINS THE BATTLE\\!*", call.message.chat.id, battle_id, parse_mode="MarkdownV2")
                    pvp_battles.pop(battle_id, None)
                    return
                elif atk_state == "fainted":
                    b["state"] = "force_switch"
                    b["current_turn"] = player_num
                    b["next_turn_after_switch"] = defender
                    render_pvp_ui(bot, call.message.chat.id, battle_id)
                    return

                b["current_turn"] = defender
                render_pvp_ui(bot, call.message.chat.id, battle_id)

    except Exception as e:
        logger.error(f"PvP Callback error: {e}")



