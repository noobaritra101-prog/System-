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

# --- TYPE EFFECTIVENESS MATRIX ---
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

def get_hp_bar(current, maximum, length=10):
    if maximum <= 0: return "▱" * length
    filled = int((current / maximum) * length)
    filled = max(0, min(length, filled))
    return "▰" * filled + "▱" * (length - filled)

def render_pvp_ui(bot, chat_id, battle_id):
    if battle_id not in pvp_battles: return
    b = pvp_battles[battle_id]
    turn = b["current_turn"]
    
    p1_poke, p2_poke = b["p1_team"][b["p1_idx"]], b["p2_team"][b["p2_idx"]]
    p1_hp_bar, p2_hp_bar = get_hp_bar(p1_poke["hp"], p1_poke["max_hp"]), get_hp_bar(p2_poke["hp"], p2_poke["max_hp"])
    
    active_player_name = b[turn + "_name"]
    active_poke = b[turn + "_team"][b[turn + "_idx"]]
    
    p1_status = f" \\[{p1_poke['status']}\\]" if p1_poke["status"] else ""
    p2_status = f" \\[{p2_poke['status']}\\]" if p2_poke["status"] else ""

    moves_text = "\n".join([f"\\> 🔹 {escape_md(m['name'])} \\| Acc: {m['acc']}% \\| Pw: {m['power']} \\({escape_md(m['type'])}\\)" for m in active_poke["moves"]])
    log_text = escape_md(b['log']) if b['log'] else "⚔️ *Battle Started\\!*"

    # NEW BLOCKQUOTE UI
    ui_text = (
        f"*{escape_md(p1_poke['name'])} vs {escape_md(p2_poke['name'])}*\n"
        f"{log_text}\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"\\> 👤 *{escape_md(b['p1_name'])}*\n"
        f"\\> 🛡️ {escape_md(p1_poke['name'])} \\({escape_md(p1_poke['types'])}\\){escape_md(p1_status)}\n"
        f"\\> 🌟 Level 100 {p1_hp_bar}\n"
        f"\\> ❤️ {p1_poke['hp']}/{p1_poke['max_hp']}\n"
        f"\\> ━━━━━━━━━━━━━━━\n"
        f"\\> 👤 *{escape_md(b['p2_name'])}*\n"
        f"\\> 🛡️ {escape_md(p2_poke['name'])} \\({escape_md(p2_poke['types'])}\\){escape_md(p2_status)}\n"
        f"\\> 🌟 Level 100 {p2_hp_bar}\n"
        f"\\> ❤️ {p2_poke['hp']}/{p2_poke['max_hp']}\n"
        f"━━━━━━━━━━━━━━━━━\n"
        f"🎯 Current Turn \\- *{escape_md(active_player_name)}*\n\n"
        f"\\> *Moves Details:*\n"
        f"{moves_text}"
    )
    
    kb = types.InlineKeyboardMarkup(row_width=2)
    moves = active_poke["moves"]
    
    kb.add(
        types.InlineKeyboardButton(f"⚔️ {moves[0]['name']}", callback_data=f"pvp_move_{battle_id}_{turn}_0"),
        types.InlineKeyboardButton(f"⚔️ {moves[1]['name']}", callback_data=f"pvp_move_{battle_id}_{turn}_1"),
        types.InlineKeyboardButton(f"⚔️ {moves[2]['name']}", callback_data=f"pvp_move_{battle_id}_{turn}_2"),
        types.InlineKeyboardButton(f"⚔️ {moves[3]['name']}", callback_data=f"pvp_move_{battle_id}_{turn}_3")
    )
    kb.add(
        types.InlineKeyboardButton("🔄 Switch", callback_data=f"pvp_switch_{battle_id}_{turn}"),
        types.InlineKeyboardButton("🏃‍♂️ Run", callback_data=f"pvp_run_{battle_id}_{turn}")
    )
        
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
    sent = bot.reply_to(message, f"🥊 *{escape_md(message.from_user.first_name)}* challenged *{escape_md(message.reply_to_message.from_user.first_name)}* to a 6v6 Random Battle\\!\n\nDo you accept?", reply_markup=kb, parse_mode="MarkdownV2")
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
                        "current_turn": "p1", "log": ""
                    }
                    render_pvp_ui(bot, chat_id, battle_id)
                except Exception as e: logger.error(f"PvP Setup Error: {e}")
            threading.Thread(target=setup_battle).start()

        elif call.data.startswith("pvp_decline_"):
            if call.from_user.id != int(call.data.split("_")[3]): return bot.answer_callback_query(call.id, "Only the challenged player can decline.")
            bot.edit_message_text("❌ *Challenge declined\\.*", call.message.chat.id, call.message.message_id, parse_mode="MarkdownV2")

        elif call.data.startswith("pvp_"):
            parts = call.data.split("_")
            action, battle_id, player_num = parts[1], int(parts[2]), parts[3]
            
            if battle_id not in pvp_battles: return bot.answer_callback_query(call.id, "This battle is over.")
            b = pvp_battles[battle_id]
            
            if call.from_user.id != b[player_num + "_id"]: return bot.answer_callback_query(call.id, "These are not your buttons!")
            if b["current_turn"] != player_num: return bot.answer_callback_query(call.id, "It is not your turn!")

            atk_team = b[player_num + "_team"]
            atk_poke = atk_team[b[player_num + "_idx"]]
            defender = "p2" if player_num == "p1" else "p1"
            def_team = b[defender + "_team"]
            def_poke = def_team[b[defender + "_idx"]]

            if action == "run":
                bot.answer_callback_query(call.id, "You fled!")
                bot.edit_message_text(f"🏃‍♂️ *{escape_md(b[player_num + '_name'])} ran away from the battle\\!*", call.message.chat.id, battle_id, parse_mode="MarkdownV2")
                pvp_battles.pop(battle_id, None)
                return
            
            elif action == "switch":
                next_idx = -1
                for i in range(b[player_num + "_idx"] + 1, 6):
                    if atk_team[i]["hp"] > 0: next_idx = i; break
                if next_idx == -1: 
                    for i in range(0, b[player_num + "_idx"]):
                        if atk_team[i]["hp"] > 0: next_idx = i; break
                            
                if next_idx == -1: return bot.answer_callback_query(call.id, "You have no other Pokémon left to switch to!")
                
                b[player_num + "_idx"] = next_idx
                b["log"] = f"🔄 *{escape_md(b[player_num + '_name'])}* switched to *{escape_md(atk_team[next_idx]['name'])}*\\!"
                
                # Reset status of switching pokemon (Optional, but authentic to main games usually except for baton pass)
                b["current_turn"] = defender
                render_pvp_ui(bot, call.message.chat.id, battle_id)
                return

            elif action == "move":
                move_idx = int(parts[4])
                move_data = atk_poke["moves"][move_idx]
                b["log"] = ""
                can_attack = True
                
                # Pre-Turn Status Checks
                if atk_poke["status"] == "PAR":
                    if random.random() < 0.25:
                        can_attack = False
                        b["log"] += f"⚡ *{escape_md(atk_poke['name'])}* is paralyzed\\! It can't move\\!\n"
                elif atk_poke["status"] == "SLP":
                    atk_poke["sleep_turns"] -= 1
                    if atk_poke["sleep_turns"] <= 0:
                        atk_poke["status"] = None
                        b["log"] += f"💤 *{escape_md(atk_poke['name'])}* woke up\\!\n"
                    else:
                        can_attack = False
                        b["log"] += f"💤 *{escape_md(atk_poke['name'])}* is fast asleep\\.\n"
                elif atk_poke["status"] == "FRZ":
                    if random.random() < 0.20:
                        atk_poke["status"] = None
                        b["log"] += f"🧊 *{escape_md(atk_poke['name'])}* thawed out\\!\n"
                    else:
                        can_attack = False
                        b["log"] += f"🧊 *{escape_md(atk_poke['name'])}* is frozen solid\\!\n"

                if can_attack:
                    if random.randint(1, 100) > move_data["acc"]:
                        b["log"] += f"💨 *{escape_md(atk_poke['name'])}* used {escape_md(move_data['name'])}, but it missed\\!\n"
                    else:
                        # Damage Calculation
                        stab = 1.5 if move_data["type"] in atk_poke["types"] else 1.0
                        type_mult = get_type_multiplier(move_data["type"], def_poke["types"])
                        
                        if type_mult == 0:
                            b["log"] += f"💨 *{escape_md(move_data['name'])}* had no effect on *{escape_md(def_poke['name'])}*\\!\n"
                        else:
                            dmg = max(1, int(((atk_poke["atk"] / def_poke["def"]) * move_data["power"] * stab * type_mult) / 2))
                            def_poke["hp"] -= dmg
                            b["log"] += f"⚔️ *{escape_md(atk_poke['name'])}* used {escape_md(move_data['name'])}\\! \\({dmg} DMG\\)\n"
                            
                            if type_mult > 1: b["log"] += "🔥 It's super effective\\!\n"
                            elif type_mult < 1: b["log"] += "🛡️ It's not very effective\\.\\.\\.\n"
                            
                            # Apply Status to Defender
                            if not def_poke["status"] and move_data["status_chance"] > 0:
                                if random.randint(1, 100) <= move_data["status_chance"]:
                                    def_poke["status"] = move_data["status_type"]
                                    if move_data["status_type"] == "SLP": def_poke["sleep_turns"] = random.randint(1, 3)
                                    b["log"] += f"🦠 *{escape_md(def_poke['name'])}* was inflicted with {escape_md(move_data['status_type'])}\\!\n"

                # Post-Turn Status Damage (Burn / Poison)
                if atk_poke["hp"] > 0:
                    if atk_poke["status"] == "BRN":
                        burn_dmg = max(1, atk_poke["max_hp"] // 16)
                        atk_poke["hp"] -= burn_dmg
                        b["log"] += f"🔥 *{escape_md(atk_poke['name'])}* is hurt by its burn\\!\n"
                    elif atk_poke["status"] == "PSN":
                        psn_dmg = max(1, atk_poke["max_hp"] // 8)
                        atk_poke["hp"] -= psn_dmg
                        b["log"] += f"☠️ *{escape_md(atk_poke['name'])}* is hurt by poison\\!\n"

                # Check Faints
                def check_faints(t_name, t_team, t_idx, enemy_name):
                    if t_team[t_idx]["hp"] <= 0:
                        b["log"] += f"\n💀 *{escape_md(t_team[t_idx]['name'])} fainted\\!*"
                        t_team[t_idx]["status"] = None # clear status on death
                        b[t_name + "_idx"] += 1
                        if b[t_name + "_idx"] >= 6: return True
                        b["log"] += f"\n🔄 *{escape_md(b[t_name + '_name'])}* sent out *{escape_md(t_team[b[t_name + '_idx']]['name'])}*\\!"
                    return False

                # Did attacker die to status?
                if check_faints(player_num, atk_team, b[player_num + "_idx"], b[defender + "_name"]):
                    b["log"] += f"\n\n🏆 *{escape_md(b[defender + '_name'])} WINS THE BATTLE\\!*"
                    bot.edit_message_text(b["log"], call.message.chat.id, battle_id, parse_mode="MarkdownV2")
                    pvp_battles.pop(battle_id, None)
                    return
                
                # Did defender die to attack?
                if check_faints(defender, def_team, b[defender + "_idx"], b[player_num + "_name"]):
                    b["log"] += f"\n\n🏆 *{escape_md(b[player_num + '_name'])} WINS THE BATTLE\\!*"
                    bot.edit_message_text(b["log"], call.message.chat.id, battle_id, parse_mode="MarkdownV2")
                    pvp_battles.pop(battle_id, None)
                    return

                b["current_turn"] = defender
                render_pvp_ui(bot, call.message.chat.id, battle_id)

    except Exception as e:
        logger.error(f"PvP Callback error: {e}")
