# gym.py
import time
import random
import threading
import requests
from telebot import types
import database as db
from config import logger
from api_utils import escape_md
from commands import clean_name, to_small_caps, safe_send
from pvp import TYPE_CHART, TYPE_EMOJIS, get_hp_bar, format_types, get_type_multiplier, apply_nature, STATUS_EMOJIS

GYM_LOCKED = False  # The Global Admin Lock
gym_battles = {}

GYM_LEADERS = {
    "Brock": {"name": "Brock", "gym_name": "Pewter City Gym", "badge": "Boulder Badge", "icon": "🪨", "type": "Rock", "team": ["Geodude", "Graveler", "Onix"]},
    "Misty": {"name": "Misty", "gym_name": "Cerulean City Gym", "badge": "Cascade Badge", "icon": "🌊", "type": "Water", "team": ["Staryu", "Psyduck", "Starmie"]},
    "Surge": {"name": "Lt. Surge", "gym_name": "Vermilion City Gym", "badge": "Thunder Badge", "icon": "⚡", "type": "Electric", "team": ["Voltorb", "Pikachu", "Raichu"]},
    "Erika": {"name": "Erika", "gym_name": "Celadon City Gym", "badge": "Rainbow Badge", "icon": "🌈", "type": "Grass", "team": ["Victreebel", "Tangela", "Vileplume"]},
    "Koga": {"name": "Koga", "gym_name": "Fuchsia City Gym", "badge": "Soul Badge", "icon": "☠️", "type": "Poison", "team": ["Koffing", "Muk", "Weezing"]},
    "Sabrina": {"name": "Sabrina", "gym_name": "Saffron City Gym", "badge": "Marsh Badge", "icon": "🔮", "type": "Psychic", "team": ["Kadabra", "Mr. Mime", "Alakazam"]},
    "Blaine": {"name": "Blaine", "gym_name": "Cinnabar Island Gym", "badge": "Volcano Badge", "icon": "🔥", "type": "Fire", "team": ["Growlithe", "Ponyta", "Arcanine"]},
    "Giovanni": {"name": "Giovanni", "gym_name": "Viridian City Gym", "badge": "Earth Badge", "icon": "🌍", "type": "Ground", "team": ["Dugtrio", "Nidoqueen", "Rhydon"]}
}

ASH_ROSTER = ["Pikachu", "Charizard", "Bulbasaur", "Squirtle", "Snorlax", "Pidgeot", "Muk", "Tauros", "Kingler"]

# --- API MOVE MATCHER & CACHE ---
MOVE_CACHE = {}

def clean_api_name(name):
    return name.lower().replace(". ", "-").replace(" ", "-").replace("'", "")

def fetch_api_moves(pokemon_name):
    api_name = clean_api_name(pokemon_name)
    try:
        resp = requests.get(f"https://pokeapi.co/api/v2/pokemon/{api_name}", timeout=5)
        if resp.status_code != 200: return []
            
        all_moves = resp.json().get("moves", [])
        random.shuffle(all_moves)
        
        final_moves = []
        for m in all_moves:
            if len(final_moves) >= 4: break
            url = m["move"]["url"]
            
            if url in MOVE_CACHE:
                if MOVE_CACHE[url].get("power", 0) > 80:
                    final_moves.append(MOVE_CACHE[url])
                continue
                
            m_resp = requests.get(url, timeout=5)
            if m_resp.status_code != 200: continue
            m_data = m_resp.json()
            
            power = m_data.get("power")
            if not power or power <= 80:
                MOVE_CACHE[url] = {"power": power or 0} 
                continue
                
            acc = m_data.get("accuracy") or 100
            m_type = m_data["type"]["name"].title()
            name_formatted = m_data["name"].replace("-", " ").title()
            
            move_dict = {"name": name_formatted, "type": m_type, "power": power, "acc": acc}
            MOVE_CACHE[url] = move_dict
            final_moves.append(move_dict)
            
        return final_moves
    except Exception as e:
        logger.error(f"API Fetch Error: {e}")
        return []

def build_mock_pokemon(name):
    p = {
        "name": name, "max_hp": random.randint(280, 350), "hp": 0,
        "atk": random.randint(200, 300), "def": random.randint(180, 260), "spd": random.randint(200, 320),
        "status": None, "is_mega": False, "can_mega": False
    }
    p["hp"] = p["max_hp"]
    
    if name in ["Pikachu", "Raichu", "Voltorb"]: p["types"] = "Electric"
    elif name in ["Charizard"]: p["types"] = "Fire/Flying" 
    elif name in ["Growlithe", "Ponyta", "Arcanine"]: p["types"] = "Fire"
    elif name in ["Squirtle", "Staryu", "Psyduck", "Kingler"]: p["types"] = "Water"
    elif name in ["Starmie"]: p["types"] = "Water/Psychic" 
    elif name in ["Bulbasaur", "Victreebel", "Vileplume"]: p["types"] = "Grass/Poison" 
    elif name in ["Tangela"]: p["types"] = "Grass"
    elif name in ["Geodude", "Graveler", "Onix", "Rhydon"]: p["types"] = "Rock/Ground"
    elif name in ["Koffing", "Muk", "Weezing"]: p["types"] = "Poison" 
    elif name in ["Nidoqueen"]: p["types"] = "Poison/Ground"
    elif name in ["Kadabra", "Mr. Mime", "Alakazam"]: p["types"] = "Psychic"
    elif name in ["Pidgeot"]: p["types"] = "Normal/Flying"
    elif name in ["Snorlax", "Tauros"]: p["types"] = "Normal"
    elif name == "Dugtrio": p["types"] = "Ground"
    else: p["types"] = "Normal"

    p["moves"] = fetch_api_moves(name)
    return p

# --- SMART AI LOGIC ---
def get_ai_action(b):
    ai_team = b["ai_team"]
    ai_idx = b["ai_idx"]
    ai_poke = ai_team[ai_idx]
    player_poke = b["player_team"][b["player_idx"]]
    
    player_primary_type = player_poke["types"].split("/")[0]
    current_weakness = get_type_multiplier(player_primary_type, ai_poke["types"])
    
    if current_weakness >= 2.0:
        for i, bench_poke in enumerate(ai_team):
            if i != ai_idx and bench_poke["hp"] > 0:
                bench_weakness = get_type_multiplier(player_primary_type, bench_poke["types"])
                if bench_weakness < 1.0: return "switch", i  
                    
    best_move_idx = 0
    highest_dmg = -1
    for i, mv in enumerate(ai_poke["moves"]):
        mult = get_type_multiplier(mv["type"], player_poke["types"])
        stab = 1.5 if mv["type"] in ai_poke["types"] else 1.0
        pow = mv.get("power", 0)
        expected_dmg = pow * mult * stab
        if expected_dmg > highest_dmg:
            highest_dmg = expected_dmg
            best_move_idx = i
            
    return "move", best_move_idx

# --- MENU UIs ---
def render_main_menu(bot, chat_id, uid, message_id=None):
    text = (
        f"✦━━━━━━━━━━━━━━━━✦\n"
        f"🏟 𝙿𝙾𝙺𝙴𝙼𝙾𝙽 𝙻𝙴𝙰𝙶𝚄𝙴 𝙶𝚈𝙼𝚂\n"
        f"✦━━━━━━━━━━━━━━━━✦\n\n"
        f"🌍 Sᴇʟᴇᴄᴛ ᴀ Rᴇɢɪᴏɴ\n"
        f"ᴛᴏ ᴄʜᴀʟʟᴇɴɢᴇ ɪᴛs ɢʏᴍs\\.\n\n"
        f"━━━━━━━━━━━━"
    )
    
    kb = types.InlineKeyboardMarkup(row_width=2)
    kb.row(types.InlineKeyboardButton("Kᴀɴᴛᴏ", callback_data=f"gym_region_{uid}_Kanto"),
           types.InlineKeyboardButton("Jᴏʜᴛᴏ", callback_data=f"gym_region_{uid}_Johto"))
    kb.row(types.InlineKeyboardButton("Hᴏᴇɴɴ", callback_data=f"gym_region_{uid}_Hoenn"),
           types.InlineKeyboardButton("Sɪɴɴᴏʜ", callback_data=f"gym_region_{uid}_Sinnoh"))
    kb.row(types.InlineKeyboardButton("Uɴᴏᴠᴀ", callback_data=f"gym_region_{uid}_Unova"),
           types.InlineKeyboardButton("Kᴀʟᴏs", callback_data=f"gym_region_{uid}_Kalos"))
    kb.row(types.InlineKeyboardButton("Aʟᴏʟᴀ", callback_data=f"gym_region_{uid}_Alola"),
           types.InlineKeyboardButton("Gᴀʟᴀʀ", callback_data=f"gym_region_{uid}_Galar"))
    kb.row(types.InlineKeyboardButton("⬅️ Bᴀᴄᴋ", callback_data=f"gym_close_{uid}"))
    
    if message_id:
        try: bot.edit_message_text(text, chat_id, message_id, reply_markup=kb, parse_mode="MarkdownV2")
        except: 
            try: bot.delete_message(chat_id, message_id)
            except: pass
            bot.send_message(chat_id, text, reply_markup=kb, parse_mode="MarkdownV2")
    else:
        bot.send_message(chat_id, text, reply_markup=kb, parse_mode="MarkdownV2")

def render_region_menu(bot, chat_id, message_id, uid, region):
    if region != "Kanto":
        bot.answer_callback_query(message_id, "🚧 This region is currently under construction!", show_alert=True)
        return

    text = (
        f"✦━━━━━━━━━━━━━━━━✦\n"
        f"🏟 Kᴀɴᴛᴏ Gʏᴍ Cʜᴀʟʟᴇɴɢᴇ\n"
        f"✦━━━━━━━━━━━━━━━━✦\n\n"
        f"🪨 Bᴏᴜʟᴅᴇʀ Bᴀᴅɢᴇ\n"
        f"🌊 Cᴀsᴄᴀᴅᴇ Bᴀᴅɢᴇ\n"
        f"⚡ Tʜᴜɴᴅᴇʀ Bᴀᴅɢᴇ\n"
        f"🌈 Rᴀɪɴʙᴏᴡ Bᴀᴅɢᴇ\n"
        f"☠️ Sᴏᴜʟ Bᴀᴅɢᴇ\n"
        f"🔮 Mᴀʀsʜ Bᴀᴅɢᴇ\n"
        f"🔥 Vᴏʟᴄᴀɴᴏ Bᴀᴅɢᴇ\n"
        f"🌍 Eᴀʀᴛʜ Bᴀᴅɢᴇ\n\n"
        f"━━━━━━━━━━━━\n"
        f"⚔️ Sᴇʟᴇᴄᴛ ᴀ Gʏᴍ Lᴇᴀᴅᴇʀ ᴛᴏ ᴄʜᴀʟʟᴇɴɢᴇ\\."
    )
    
    kb = types.InlineKeyboardMarkup(row_width=2)
    kb.row(types.InlineKeyboardButton("Bʀᴏᴄᴋ", callback_data=f"gym_info_{uid}_Brock"),
           types.InlineKeyboardButton("Mɪsᴛʏ", callback_data=f"gym_info_{uid}_Misty"))
    kb.row(types.InlineKeyboardButton("Lᴛ\\. Sᴜʀɢᴇ", callback_data=f"gym_info_{uid}_Surge"),
           types.InlineKeyboardButton("Eʀɪᴋᴀ", callback_data=f"gym_info_{uid}_Erika"))
    kb.row(types.InlineKeyboardButton("Kᴏɢᴀ", callback_data=f"gym_info_{uid}_Koga"),
           types.InlineKeyboardButton("Sᴀʙʀɪɴᴀ", callback_data=f"gym_info_{uid}_Sabrina"))
    kb.row(types.InlineKeyboardButton("Bʟᴀɪɴᴇ", callback_data=f"gym_info_{uid}_Blaine"),
           types.InlineKeyboardButton("Gɪᴏᴠᴀɴɴɪ", callback_data=f"gym_info_{uid}_Giovanni"))
    kb.row(types.InlineKeyboardButton("⬅ Bᴀᴄᴋ", callback_data=f"gym_main_{uid}"))
    
    try: bot.edit_message_text(text, chat_id, message_id, reply_markup=kb, parse_mode="MarkdownV2")
    except: 
        try: bot.delete_message(chat_id, message_id)
        except: pass
        bot.send_message(chat_id, text, reply_markup=kb, parse_mode="MarkdownV2")

def render_gym_info(bot, chat_id, message_id, uid, leader_key):
    leader = GYM_LEADERS[leader_key]
    team_str = "\n".join([f"• {escape_md(to_small_caps(p))}" for p in leader["team"]])
    
    text = (
        f"✦━━━━━━━━━━━━━━━━✦\n"
        f"🏟 *{escape_md(to_small_caps(leader['gym_name']))}*\n"
        f"✦━━━━━━━━━━━━━━━━✦\n\n"
        f"👤 Lᴇᴀᴅᴇʀ : {escape_md(to_small_caps(leader['name']))}\n"
        f"🏅 Bᴀᴅɢᴇ  : {leader['icon']} {escape_md(to_small_caps(leader['badge']))}\n"
        f"🧬 Tʏᴘᴇ   : {leader['icon']} {escape_md(to_small_caps(leader['type']))}\n\n"
        f"━━━━━━━━━━━━\n\n"
        f"🎮 Pᴏᴋᴇ́ᴍᴏɴ Tᴇᴀᴍ\n"
        f"{team_str}\n\n"
        f"━━━━━━━━━━━━\n"
        f"⚔️ Dᴏ ʏᴏᴜ ᴡᴀɴᴛ ᴛᴏ ᴄʜᴀʟʟᴇɴɢᴇ ᴛʜɪs ɢʏᴍ?"
    )
    
    kb = types.InlineKeyboardMarkup(row_width=2)
    kb.row(types.InlineKeyboardButton("✅ Cʜᴀʟʟᴇɴɢᴇ", callback_data=f"gym_start_{uid}_{leader_key}"),
           types.InlineKeyboardButton("❌ Cᴀɴᴄᴇʟ", callback_data=f"gym_region_{uid}_Kanto"))
           
    file_id = db.get_gym_image(leader_key)
    try: bot.delete_message(chat_id, message_id)
    except: pass
    
    if file_id:
        try: bot.send_photo(chat_id, file_id, caption=text, reply_markup=kb, parse_mode="MarkdownV2")
        except Exception: bot.send_message(chat_id, text, reply_markup=kb, parse_mode="MarkdownV2")
    else: bot.send_message(chat_id, text, reply_markup=kb, parse_mode="MarkdownV2")

def render_gym_ui(bot, chat_id, battle_id):
    if battle_id not in gym_battles: return
    b = gym_battles[battle_id]
    if b["state"] == "ended": return

    player_poke = b["player_team"][b["player_idx"]]
    ai_poke = b["ai_team"][b["ai_idx"]]
    leader = GYM_LEADERS[b["leader"]]
    player_mention = f"[{escape_md(b['player_name'])}](tg://user?id={b['player_id']})"
    
    log_content = f"*{escape_md(b['log'].strip())}*" if b['log'] else "*Tʜᴇ Gʏᴍ Bᴀᴛᴛʟᴇ Bᴇɢɪɴs\\!*"

    ui_text = (
        f"{log_content}\n\n"
        f"*{leader['icon']} Gʏᴍ Lᴇᴀᴅᴇʀ {leader['name']}'s {escape_md(ai_poke['name'])}*\n"
        f" *\\[{escape_md(format_types(ai_poke['types']))}\\] Lv\\. 100  •  HP {int(ai_poke['hp'])}/{int(ai_poke['max_hp'])}*\n"
        f"`{get_hp_bar(ai_poke['hp'], ai_poke['max_hp'])}`\n\n"
        f"Current turn: {player_mention} \\(Asʜ's Tᴇᴀᴍ\\)\n"
        f"*{player_mention}'s {escape_md(player_poke['name'])} \\[{escape_md(format_types(player_poke['types']))}\\]*\n"
        f"*Lv\\. 100  •  HP {int(player_poke['hp'])}/{int(player_poke['max_hp'])}*\n"
        f"`{get_hp_bar(player_poke['hp'], player_poke['max_hp'])}`\n\n"
    )

    kb = types.InlineKeyboardMarkup(row_width=2)
    
    if b["state"] == "menu":
        moves_block = ""
        move_buttons = []
        for i, m in enumerate(player_poke["moves"]):
            m_type_display = escape_md(f"{m['type']} {TYPE_EMOJIS.get(m['type'], '')}".strip())
            moves_block += f" *{escape_md(m['name'])} \\[{m_type_display}\\]*\n *Power: {m.get('power', 0)}, Accuracy: {m.get('acc', 100)}*\n"
            move_buttons.append(types.InlineKeyboardButton(f"{m['name']}", callback_data=f"gym_move_{battle_id}_{i}"))
            
        ui_text += moves_block
        if len(move_buttons) == 4:
            kb.row(move_buttons[0], move_buttons[1])
            kb.row(move_buttons[2], move_buttons[3])
        else:
            for btn in move_buttons: kb.add(btn)
            
        kb.row(types.InlineKeyboardButton("🔄 Sᴡɪᴛᴄʜ", callback_data=f"gym_swmenu_{battle_id}"),
               types.InlineKeyboardButton("🏃 Rᴜɴ", callback_data=f"gym_run_{battle_id}"))
               
    elif b["state"] in ["switch_menu", "force_switch"]:
        if b["state"] == "switch_menu": ui_text += f"\n🔄 *Wʜɪᴄʜ Pᴏᴋᴇ́ᴍᴏɴ Wɪʟʟ Yᴏᴜ Sᴡɪᴛᴄʜ Tᴏ?*\n"
        else: ui_text += f"\n💀 *Cʜᴏᴏsᴇ A Pᴏᴋᴇ́ᴍᴏɴ Tᴏ Sᴇɴᴅ Oᴜᴛ\\!*\n"
            
        btns = [types.InlineKeyboardButton(f"{p['name']}" if p['hp'] > 0 else f"✖️ {p['name']}", callback_data=f"gym_dosw_{battle_id}_{i}") for i, p in enumerate(b["player_team"])]
        for i in range(0, len(btns), 2):
            if i + 1 < len(btns): kb.add(btns[i], btns[i+1])
            else: kb.add(btns[i])
            
        if b["state"] == "switch_menu": kb.row(types.InlineKeyboardButton("🔙 Bᴀᴄᴋ", callback_data=f"gym_back_{battle_id}"))

    try: bot.edit_message_text(ui_text, chat_id, battle_id, reply_markup=kb, parse_mode="MarkdownV2")
    except: pass

def resolve_turn(bot, chat_id, battle_id, player_action, player_val):
    b = gym_battles[battle_id]
    b["log"] = ""
    
    ai_action, ai_val = get_ai_action(b)
    
    if player_action == "switch":
        old_name = b["player_team"][b["player_idx"]]["name"]
        b["player_idx"] = player_val
        b["log"] += f"🔄 You withdrew {old_name} and sent out {b['player_team'][player_val]['name']}!\n"
    if ai_action == "switch":
        old_name = b["ai_team"][b["ai_idx"]]["name"]
        b["ai_idx"] = ai_val
        b["log"] += f"🔄 Gym Leader withdrew {old_name} and sent out {b['ai_team'][ai_val]['name']}!\n"

    player_poke = b["player_team"][b["player_idx"]]
    ai_poke = b["ai_team"][b["ai_idx"]]

    moves_to_execute = []
    if player_action == "move" and ai_action == "move":
        # ⚡ SPEED ADVANTAGE LOGIC
        if player_poke["spd"] >= ai_poke["spd"]: 
            b["log"] += f"⚡ {player_poke['name']}'s speed allows it to strike first!\n"
            moves_to_execute = [("player", player_val), ("ai", ai_val)]
        else: 
            b["log"] += f"⚡ Gym Leader's {ai_poke['name']} is faster and strikes first!\n"
            moves_to_execute = [("ai", ai_val), ("player", player_val)]
    elif player_action == "move": moves_to_execute = [("player", player_val)]
    elif ai_action == "move": moves_to_execute = [("ai", ai_val)]

    for actor, val in moves_to_execute:
        if actor == "player":
            atk, dfn = player_poke, ai_poke
            mv = atk["moves"][val]
        else:
            atk, dfn = ai_poke, player_poke
            mv = atk["moves"][val]
            
        if atk["hp"] <= 0: continue 
        
        mult = get_type_multiplier(mv["type"], dfn["types"])
        if mult == 0: b["log"] += f"{atk['name']} used {mv['name']}... It had no effect!\n"
        else:
            pow = mv.get("power", 0)
            if pow > 0:
                stab = 1.5 if mv["type"] in atk["types"] else 1.0
                crit = 1.5 if random.random() < 0.06 else 1.0
                dmg = max(1, int(((42 * pow * (atk["atk"] / max(1, dfn["def"]))) / 50 + 2) * mult * stab * crit * random.uniform(0.85, 1.0)))
                dfn["hp"] = max(0, dfn["hp"] - dmg)
                
                # 💥 DYNAMIC ATTACK LOG WITH EMOJIS
                b["log"] += f"💥 {atk['name']} used {mv['name']}! ({dmg} DMG)\n"
                if mult > 1: b["log"] += "It's super effective!\n"
                elif mult < 1: b["log"] += "It's not very effective...\n"
                if crit > 1: b["log"] += "A critical hit!\n"
            else:
                b["log"] += f"⚡ {atk['name']} used {mv['name']}!\n"

        if dfn["hp"] <= 0:
            b["log"] += f"💀 {dfn['name']} fainted!\n"
            break

    # 🏆 VICTORY ROUTING
    if ai_poke["hp"] <= 0:
        if all(p["hp"] <= 0 for p in b["ai_team"]):
            leader = GYM_LEADERS[b["leader"]]
            db.add_badge(b["player_id"], f"{leader['icon']} {leader['badge']}")
            b["state"] = "ended"
            
            player_mention = f"[{escape_md(b['player_name'])}](tg://user?id={b['player_id']})"
            
            win_text = f"*{escape_md(b['log'].strip())}*\n\n{player_mention} *defeated Gym Leader {escape_md(leader['name'])}*\\!\n🏅 *You earned the {leader['icon']} {escape_md(leader['badge'])}*\\!"
            bot.edit_message_text(win_text, chat_id, battle_id, parse_mode="MarkdownV2")
            return
        else:
            for i, p in enumerate(b["ai_team"]):
                if p["hp"] > 0:
                    b["ai_idx"] = i
                    b["log"] += f"\nGym Leader sent out {p['name']}!"
                    break

    # ❌ DEFEAT ROUTING
    if player_poke["hp"] <= 0:
        if all(p["hp"] <= 0 for p in b["player_team"]):
            b["state"] = "ended"
            loss_text = f"*{escape_md(b['log'].strip())}*\n\n❌ *All your Pokémon fainted\\. You whited out\\!*"
            bot.edit_message_text(loss_text, chat_id, battle_id, parse_mode="MarkdownV2")
            return
        else:
            b["state"] = "force_switch"
    
    if b["state"] != "force_switch": b["state"] = "menu"
    render_gym_ui(bot, chat_id, battle_id)

def setup_gym_battle(bot, call, leader_key, user_id, chat_id, battle_id):
    try:
        leader = GYM_LEADERS[leader_key]
        player_roster = random.sample(ASH_ROSTER, 3)
        
        player_team = [build_mock_pokemon(n) for n in player_roster]
        ai_team = [build_mock_pokemon(n) for n in leader["team"]]
        
        gym_battles[battle_id] = {
            "player_id": user_id, "player_name": clean_name(call.from_user.first_name),
            "player_team": player_team, "player_idx": 0,
            "leader": leader_key, "ai_team": ai_team, "ai_idx": 0,
            "state": "menu", "log": "", "last_edit": time.time()
        }
        render_gym_ui(bot, chat_id, battle_id)
    except Exception as e:
        logger.error(f"Gym Setup Error: {e}")
        try: bot.edit_message_text("❌ Failed to load Gym Battle API data.", chat_id, battle_id)
        except: pass

def handle_gym_command(bot, message):
    if GYM_LOCKED:
        return safe_send(bot, message.chat.id, escape_md("🔒 The Pokemon League Gyms are currently locked by the Admins!"))
        
    user_id = message.from_user.id
    if not db.get_user(user_id): return bot.reply_to(message, "⚠️ Please /start the bot first!")
    render_main_menu(bot, message.chat.id, user_id)

def handle_gym_callback(bot, call):
    parts = call.data.split("_")
    action = parts[1]
    
    # Entrance Security
    if GYM_LOCKED and action in ["main", "region", "info", "start"]:
        return bot.answer_callback_query(call.id, "🔒 The Gyms are currently locked by the Admins!", show_alert=True)
    
    # Verify User ID for Menus
    if action in ["main", "close"]:
        uid = int(parts[2])
        if call.from_user.id != uid: return bot.answer_callback_query(call.id, "❌ Not your menu!", show_alert=True)
            
        if action == "close":
            bot.answer_callback_query(call.id, "Menu closed.")
            try: bot.delete_message(call.message.chat.id, call.message.message_id)
            except: pass
            return
            
        elif action == "main":
            bot.answer_callback_query(call.id, "")
            render_main_menu(bot, call.message.chat.id, uid, call.message.message_id)
            return
            
    elif action in ["region", "info", "start"]:
        uid = int(parts[2])
        param = parts[3]
        if call.from_user.id != uid: return bot.answer_callback_query(call.id, "❌ Not your menu!", show_alert=True)
            
        if action == "region":
            bot.answer_callback_query(call.id, "")
            render_region_menu(bot, call.message.chat.id, call.message.message_id, uid, param)
            return

        elif action == "info":
            bot.answer_callback_query(call.id, f"Viewing {param}...")
            render_gym_info(bot, call.message.chat.id, call.message.message_id, uid, param)
            return
        
        elif action == "start":
            leader = GYM_LEADERS[param]
            bot.answer_callback_query(call.id, f"Challenging {leader['name']}...")
            
            try: bot.delete_message(call.message.chat.id, call.message.message_id)
            except: pass
            
            sent_msg = bot.send_message(call.message.chat.id, "🔄 *Dʀᴀғᴛɪɴɢ Oғғɪᴄɪᴀʟ Tᴇᴀᴍs\\.\\.\\.*", parse_mode="MarkdownV2")
            battle_id = sent_msg.message_id
            
            threading.Thread(target=setup_gym_battle, args=(bot, call, param, uid, call.message.chat.id, battle_id)).start()
            return

    # In-Battle Actions Security
    battle_id = int(parts[2])
    b = gym_battles.get(battle_id)
    if not b: return bot.answer_callback_query(call.id, "Battle expired.")
    if call.from_user.id != b["player_id"]: return bot.answer_callback_query(call.id, "❌ Not your battle!", show_alert=True)
    
    now = time.time()
    if now - b.get("last_edit", 0) < 1.5: return safe_send(bot, call.id, "⏳ Whoa, slow down Trainer! Wait a second.", show_alert=True)
    b["last_edit"] = now
    bot.answer_callback_query(call.id, "")

    if action == "move":
        move_idx = int(parts[3])
        resolve_turn(bot, call.message.chat.id, battle_id, "move", move_idx)
        
    elif action == "swmenu":
        b["state"] = "switch_menu"
        render_gym_ui(bot, call.message.chat.id, battle_id)
        
    elif action == "dosw":
        poke_idx = int(parts[3])
        if b["player_team"][poke_idx]["hp"] <= 0: return bot.answer_callback_query(call.id, "Pokemon is fainted!", show_alert=True)
        if poke_idx == b["player_idx"]: return bot.answer_callback_query(call.id, "Already in battle!", show_alert=True)
        
        if b["state"] == "force_switch":
            b["player_idx"] = poke_idx
            b["state"] = "menu"
            b["log"] = f"You sent out {b['player_team'][poke_idx]['name']}!"
            render_gym_ui(bot, call.message.chat.id, battle_id)
        else:
            resolve_turn(bot, call.message.chat.id, battle_id, "switch", poke_idx)
            
    elif action == "back":
        b["state"] = "menu"
        render_gym_ui(bot, call.message.chat.id, battle_id)
        
    elif action == "run":
        b["state"] = "ended"
        bot.edit_message_text("🏃 *You fled from the Gym Battle\\!*", call.message.chat.id, battle_id, parse_mode="MarkdownV2")
