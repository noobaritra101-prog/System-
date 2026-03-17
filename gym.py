# gym.py
import time
import random
import threading
import requests
from telebot import types
import database as db
from config import logger, OWNER_ID
from api_utils import escape_md
from commands import clean_name, to_small_caps, safe_send
from pvp import TYPE_CHART, TYPE_EMOJIS, get_hp_bar, format_types, get_type_multiplier, apply_nature, STATUS_EMOJIS
from gym_data import GYM_LEADERS, ASH_KANTO_ROSTER, ASH_JOHTO_ROSTER, ASH_HOENN_ROSTER, AUTHENTIC_MOVES

GYM_LOCKED = False  
gym_battles = {}

# --- API DATA FETCHERS & CACHE ---
POKEMON_CACHE = {}
MOVE_CACHE = {}

def fetch_pokemon_stats_from_api(name):
    api_name = name.lower().replace(" ", "-").replace("'", "")
    if api_name in POKEMON_CACHE:
        return POKEMON_CACHE[api_name]
    
    try:
        resp = requests.get(f"https://pokeapi.co/api/v2/pokemon/{api_name}", timeout=5)
        if resp.status_code == 200:
            data = resp.json()
            
            # Extract Types
            types_list = [t["type"]["name"].title() for t in data.get("types", [])]
            types_str = "/".join(types_list) if types_list else "Normal"
            
            # Extract Base Stats
            stats = {s["stat"]["name"]: s["base_stat"] for s in data.get("stats", [])}
            base_hp = stats.get("hp", 80)
            base_atk = stats.get("attack", 80)
            base_def = stats.get("defense", 80)
            base_spd = stats.get("speed", 80)
            
            # Convert to Level 100 Stats
            hp = (2 * base_hp) + 110
            atk = (2 * base_atk) + 5
            dfn = (2 * base_def) + 5
            spd = (2 * base_spd) + 5
            
            result = {"hp": hp, "atk": atk, "def": dfn, "spd": spd, "type": types_str}
            POKEMON_CACHE[api_name] = result
            return result
    except Exception as e:
        logger.error(f"API Pokemon Fetch Error for {name}: {e}")
        
    return {"hp": 250, "atk": 150, "def": 150, "spd": 150, "type": "Normal"}

def fetch_move_data_from_api(move_name):
    api_name = move_name.lower().replace(" ", "-").replace("'", "")
    if api_name in MOVE_CACHE:
        return MOVE_CACHE[api_name]
        
    try:
        resp = requests.get(f"https://pokeapi.co/api/v2/move/{api_name}", timeout=5)
        if resp.status_code == 200:
            data = resp.json()
            power = data.get("power") or 0
            acc = data.get("accuracy") or 100
            m_type = data["type"]["name"].title()
            
            display_name = move_name.title().replace("-", " ")
            
            result = {"name": display_name, "type": m_type, "power": power, "acc": acc}
            MOVE_CACHE[api_name] = result
            return result
    except Exception as e:
        logger.error(f"API Move Fetch Error for {move_name}: {e}")
        
    return {"name": move_name.title(), "type": "Normal", "power": 40, "acc": 100}

def build_mock_pokemon(name):
    s = fetch_pokemon_stats_from_api(name)
    p = {
        "name": name, "max_hp": s["hp"], "hp": s["hp"],
        "atk": s["atk"], "def": s["def"], "spd": s["spd"], "types": s["type"],
        "status": None, "is_mega": False, "can_mega": False
    }
    
    move_names = AUTHENTIC_MOVES.get(name, ["Tackle", "Growl", "Scratch", "Bite"])
    p["moves"] = [fetch_move_data_from_api(m_name) for m_name in move_names]
    
    return p

# --- TYPE CHART UTILS ---
TYPE_CHART = {
    "Normal": {"weak": ["Fighting"], "resist": [], "immune": ["Ghost"]},
    "Fire": {"weak": ["Water", "Ground", "Rock"], "resist": ["Fire", "Grass", "Ice", "Bug", "Steel", "Fairy"], "immune": []},
    "Water": {"weak": ["Electric", "Grass"], "resist": ["Fire", "Water", "Ice", "Steel"], "immune": []},
    "Grass": {"weak": ["Fire", "Ice", "Poison", "Flying", "Bug"], "resist": ["Water", "Grass", "Electric", "Ground"], "immune": []},
    "Electric": {"weak": ["Ground"], "resist": ["Electric", "Flying", "Steel"], "immune": []},
    "Ice": {"weak": ["Fire", "Fighting", "Rock", "Steel"], "resist": ["Ice"], "immune": []},
    "Fighting": {"weak": ["Flying", "Psychic", "Fairy"], "resist": ["Bug", "Rock", "Dark"], "immune": []},
    "Poison": {"weak": ["Ground", "Psychic"], "resist": ["Grass", "Fighting", "Poison", "Bug", "Fairy"], "immune": []},
    "Ground": {"weak": ["Water", "Grass", "Ice"], "resist": ["Poison", "Rock"], "immune": ["Electric"]},
    "Flying": {"weak": ["Electric", "Ice", "Rock"], "resist": ["Grass", "Fighting", "Bug"], "immune": ["Ground"]},
    "Psychic": {"weak": ["Bug", "Ghost", "Dark"], "resist": ["Fighting", "Psychic"], "immune": []},
    "Bug": {"weak": ["Fire", "Flying", "Rock"], "resist": ["Grass", "Fighting", "Ground"], "immune": []},
    "Rock": {"weak": ["Water", "Grass", "Fighting", "Ground", "Steel"], "resist": ["Normal", "Fire", "Poison", "Flying"], "immune": []},
    "Ghost": {"weak": ["Ghost", "Dark"], "resist": ["Poison", "Bug"], "immune": ["Normal", "Fighting"]},
    "Dragon": {"weak": ["Ice", "Dragon", "Fairy"], "resist": ["Fire", "Water", "Grass", "Electric"], "immune": []},
    "Dark": {"weak": ["Fighting", "Bug", "Fairy"], "resist": ["Ghost", "Dark"], "immune": ["Psychic"]},
    "Steel": {"weak": ["Fire", "Fighting", "Ground"], "resist": ["Normal", "Grass", "Ice", "Flying", "Psychic", "Bug", "Rock", "Dragon", "Steel", "Fairy"], "immune": ["Poison"]},
    "Fairy": {"weak": ["Poison", "Steel"], "resist": ["Fighting", "Bug", "Dark"], "immune": ["Dragon"]}
}

def get_type_multiplier(attack_type, defend_types_str):
    mult = 1.0
    for def_type in defend_types_str.split('/'):
        dt = TYPE_CHART.get(def_type, {})
        if attack_type in dt.get("immune", []): return 0.0
        if attack_type in dt.get("weak", []): mult *= 2.0
        if attack_type in dt.get("resist", []): mult *= 0.5
    return mult

def get_hp_bar(hp, max_hp):
    if max_hp <= 0: return "░" * 14
    bars = int((hp / max_hp) * 14)
    return ("█" * bars) + ("░" * (14 - bars))

def get_type_display(type_str):
    parts = type_str.split('/')
    formatted_parts = []
    for t in parts:
        emoji = TYPE_EMOJIS.get(t, '')
        formatted_parts.append(f"{t} {emoji}".strip())
    return "/".join(formatted_parts)

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
def render_main_menu(bot, chat_id, uid, message_id=None, reply_to_id=None):
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
    kb.row(types.InlineKeyboardButton("Bᴀᴄᴋ", callback_data=f"gym_close_{uid}"))
    
    if message_id:
        try: bot.edit_message_text(text, chat_id, message_id, reply_markup=kb, parse_mode="MarkdownV2")
        except: 
            try: bot.delete_message(chat_id, message_id)
            except: pass
            bot.send_message(chat_id, text, reply_markup=kb, parse_mode="MarkdownV2")
    else:
        bot.send_message(chat_id, text, reply_markup=kb, parse_mode="MarkdownV2", reply_to_message_id=reply_to_id)

def render_region_menu(bot, chat_id, message_id, uid, region):
    if region == "Kanto":
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
            f"Sᴇʟᴇᴄᴛ ᴀ Gʏᴍ Lᴇᴀᴅᴇʀ ᴛᴏ ᴄʜᴀʟʟᴇɴɢᴇ\\."
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
        kb.row(types.InlineKeyboardButton("Bᴀᴄᴋ", callback_data=f"gym_main_{uid}"))

    elif region == "Johto":
        text = (
            f"✦━━━━━━━━━━━━━━━━✦\n"
            f"🏟 Jᴏʜᴛᴏ Gʏᴍ Cʜᴀʟʟᴇɴɢᴇ\n"
            f"✦━━━━━━━━━━━━━━━━✦\n\n"
            f"🕊 Zᴇᴘʜʏʀ Bᴀᴅɢᴇ\n"
            f"🐞 Hɪᴠᴇ Bᴀᴅɢᴇ\n"
            f"🐄 Pʟᴀɪɴ Bᴀᴅɢᴇ\n"
            f"👻 Fᴏɢ Bᴀᴅɢᴇ\n"
            f"🥊 Sᴛᴏʀᴍ Bᴀᴅɢᴇ\n"
            f"🔩 Mɪɴᴇʀᴀʟ Bᴀᴅɢᴇ\n"
            f"❄️ Gʟᴀᴄɪᴇʀ Bᴀᴅɢᴇ\n"
            f"🐉 Rɪsɪɴɢ Bᴀᴅɢᴇ\n\n"
            f"━━━━━━━━━━━━\n"
            f"Sᴇʟᴇᴄᴛ ᴀ Gʏᴍ Lᴇᴀᴅᴇʀ ᴛᴏ ᴄʜᴀʟʟᴇɴɢᴇ\\."
        )
        kb = types.InlineKeyboardMarkup(row_width=2)
        kb.row(types.InlineKeyboardButton("Fᴀʟᴋɴᴇʀ", callback_data=f"gym_info_{uid}_Falkner"),
               types.InlineKeyboardButton("Bᴜɢsʏ", callback_data=f"gym_info_{uid}_Bugsy"))
        kb.row(types.InlineKeyboardButton("Wʜɪᴛɴᴇʏ", callback_data=f"gym_info_{uid}_Whitney"),
               types.InlineKeyboardButton("Mᴏʀᴛʏ", callback_data=f"gym_info_{uid}_Morty"))
        kb.row(types.InlineKeyboardButton("Cʜᴜᴄᴋ", callback_data=f"gym_info_{uid}_Chuck"),
               types.InlineKeyboardButton("Jᴀsᴍɪɴᴇ", callback_data=f"gym_info_{uid}_Jasmine"))
        kb.row(types.InlineKeyboardButton("Pʀʏᴄᴇ", callback_data=f"gym_info_{uid}_Pryce"),
               types.InlineKeyboardButton("Cʟᴀɪʀ", callback_data=f"gym_info_{uid}_Clair"))
        kb.row(types.InlineKeyboardButton("Bᴀᴄᴋ", callback_data=f"gym_main_{uid}"))

    elif region == "Hoenn":
        text = (
            f"✦━━━━━━━━━━━━━━━━✦\n"
            f"🏟 Hᴏᴇɴɴ Gʏᴍ Cʜᴀʟʟᴇɴɢᴇ\n"
            f"✦━━━━━━━━━━━━━━━━✦\n\n"
            f"🪨 Sᴛᴏɴᴇ Bᴀᴅɢᴇ\n"
            f"🥊 Kɴᴜᴄᴋʟᴇ Bᴀᴅɢᴇ\n"
            f"⚡ Dʏɴᴀᴍᴏ Bᴀᴅɢᴇ\n"
            f"🔥 Hᴇᴀᴛ Bᴀᴅɢᴇ\n"
            f"🌫 Bᴀʟᴀɴᴄᴇ Bᴀᴅɢᴇ\n"
            f"🪶 Fᴇᴀᴛʜᴇʀ Bᴀᴅɢᴇ\n"
            f"🧠 Mɪɴᴅ Bᴀᴅɢᴇ\n"
            f"💧 Rᴀɪɴ Bᴀᴅɢᴇ\n\n"
            f"━━━━━━━━━━━━\n"
            f"Sᴇʟᴇᴄᴛ ᴀ Gʏᴍ Lᴇᴀᴅᴇʀ ᴛᴏ ᴄʜᴀʟʟᴇɴɢᴇ\\."
        )
        kb = types.InlineKeyboardMarkup(row_width=2)
        kb.row(types.InlineKeyboardButton("Rᴏxᴀɴɴᴇ", callback_data=f"gym_info_{uid}_Roxanne"),
               types.InlineKeyboardButton("Bʀᴀᴡʟʏ", callback_data=f"gym_info_{uid}_Brawly"))
        kb.row(types.InlineKeyboardButton("Wᴀᴛᴛsᴏɴ", callback_data=f"gym_info_{uid}_Wattson"),
               types.InlineKeyboardButton("Fʟᴀɴɴᴇʀʏ", callback_data=f"gym_info_{uid}_Flannery"))
        kb.row(types.InlineKeyboardButton("Nᴏʀᴍᴀɴ", callback_data=f"gym_info_{uid}_Norman"),
               types.InlineKeyboardButton("Wɪɴᴏɴᴀ", callback_data=f"gym_info_{uid}_Winona"))
        kb.row(types.InlineKeyboardButton("Tᴀᴛᴇ & Lɪᴢᴀ", callback_data=f"gym_info_{uid}_TateLiza"),
               types.InlineKeyboardButton("Wᴀʟʟᴀᴄᴇ", callback_data=f"gym_info_{uid}_Wallace"))
        kb.row(types.InlineKeyboardButton("Bᴀᴄᴋ", callback_data=f"gym_main_{uid}"))

    else:
        bot.answer_callback_query(message_id, "This region is currently under construction!", show_alert=True)
        return
    
    try: bot.edit_message_text(text, chat_id, message_id, reply_markup=kb, parse_mode="MarkdownV2")
    except: pass

def render_gym_info(bot, chat_id, message_id, uid, leader_key):
    leader = GYM_LEADERS[leader_key]
    team_str = "\n".join([f"• {escape_md(to_small_caps(p))}" for p in leader["team"]])
    region = leader.get("region", "Kanto")
    
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
        f"Dᴏ ʏᴏᴜ ᴡᴀɴᴛ ᴛᴏ ᴄʜᴀʟʟᴇɴɢᴇ ᴛʜɪs ɢʏᴍ?"
    )
    
    kb = types.InlineKeyboardMarkup(row_width=2)
    kb.row(types.InlineKeyboardButton("Cʜᴀʟʟᴇɴɢᴇ", callback_data=f"gym_start_{uid}_{leader_key}"),
           types.InlineKeyboardButton("Cᴀɴᴄᴇʟ", callback_data=f"gym_region_{uid}_{region}"))
           
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
    player_mention_link = f"[{escape_md(b['player_name'])}](tg://user?id={b['player_id']})"
    player_name_clean = escape_md(b['player_name'])

    log_text = escape_md(b['log'].strip()) if b['log'] else escape_md("Tʜᴇ Gʏᴍ Bᴀᴛᴛʟᴇ Bᴇɢɪɴs!")
    
    ai_type_display = escape_md(get_type_display(ai_poke['types']))
    player_type_display = escape_md(get_type_display(player_poke['types']))

    ui_text = (
        f"{log_text}\n\n"
        f"{leader['icon']} Gʏᴍ Lᴇᴀᴅᴇʀ {escape_md(leader['name'])}'s {escape_md(ai_poke['name'])}\n"
        f" \\[{ai_type_display}\\] Lv\\. 100  •  HP {int(ai_poke['hp'])}/{int(ai_poke['max_hp'])}\n"
        f"`{get_hp_bar(ai_poke['hp'], ai_poke['max_hp'])}`\n\n"
        f"Current turn: {player_mention_link} \\(Asʜ's Tᴇᴀᴍ\\)\n"
        f"{player_name_clean}'s {escape_md(player_poke['name'])} \\[{player_type_display}\\]\n"
        f"Lv\\. 100  •  HP {int(player_poke['hp'])}/{int(player_poke['max_hp'])}\n"
        f"`{get_hp_bar(player_poke['hp'], player_poke['max_hp'])}`\n"
    )

    kb = types.InlineKeyboardMarkup(row_width=2)
    
    if b["state"] == "menu":
        moves_block = ""
        move_buttons = []
        for i, m in enumerate(player_poke["moves"]):
            m_type_display = escape_md(get_type_display(m['type']))
            moves_block += f"\n {escape_md(m['name'])} \\[{m_type_display}\\]\n Power: {m.get('power', 0)}, Accuracy: {m.get('acc', 100)}"
            move_buttons.append(types.InlineKeyboardButton(f"{m['name']}", callback_data=f"gym_move_{battle_id}_{i}"))
            
        ui_text += moves_block + "\n"
        if len(move_buttons) == 4:
            kb.row(move_buttons[0], move_buttons[1])
            kb.row(move_buttons[2], move_buttons[3])
        else:
            for btn in move_buttons: kb.add(btn)
            
        kb.row(types.InlineKeyboardButton("Sᴡɪᴛᴄʜ", callback_data=f"gym_swmenu_{battle_id}"),
               types.InlineKeyboardButton("Rᴜɴ", callback_data=f"gym_run_{battle_id}"))
               
    elif b["state"] in ["switch_menu", "force_switch"]:
        if b["state"] == "switch_menu": ui_text += f"\n\n*Wʜɪᴄʜ Pᴏᴋᴇ́ᴍᴏɴ Wɪʟʟ Yᴏᴜ Sᴡɪᴛᴄʜ Tᴏ?*\n"
        else: ui_text += f"\n\n*Cʜᴏᴏsᴇ A Pᴏᴋᴇ́ᴍᴏɴ Tᴏ Sᴇɴᴅ Oᴜᴛ\\!*\n"
            
        btns = [types.InlineKeyboardButton(f"{p['name']}" if p['hp'] > 0 else f"X {p['name']}", callback_data=f"gym_dosw_{battle_id}_{i}") for i, p in enumerate(b["player_team"])]
        for i in range(0, len(btns), 2):
            if i + 1 < len(btns): kb.add(btns[i], btns[i+1])
            else: kb.add(btns[i])
            
        if b["state"] == "switch_menu": kb.row(types.InlineKeyboardButton("Bᴀᴄᴋ", callback_data=f"gym_back_{battle_id}"))

    elif b["state"] == "waiting":
        leader_small = escape_md(to_small_caps(leader['name']))
        ui_text += f"\n_Gʏᴍ Lᴇᴀᴅᴇʀ {leader_small} ɪs ᴀᴛᴛᴀᴄᴋɪɴɢ\\.\\.\\.\\.\\._"

    try: bot.edit_message_text(ui_text, chat_id, battle_id, reply_markup=kb, parse_mode="MarkdownV2")
    except: pass

# --- TRUE TURN-BASED COMBAT ENGINE ---
def resolve_action(b, actor, val):
    atk, dfn = (b["player_team"][b["player_idx"]], b["ai_team"][b["ai_idx"]]) if actor == "player" else (b["ai_team"][b["ai_idx"]], b["player_team"][b["player_idx"]])
    if atk["hp"] <= 0: return

    if actor == "switch_player":
        b["player_idx"] = val
        b["log"] += f"You sent out {b['player_team'][val]['name']}!\n"
        return
    if actor == "switch_ai":
        b["ai_idx"] = val
        b["log"] += f"Gym Leader sent out {b['ai_team'][val]['name']}!\n"
        return

    mv = atk["moves"][val]
    mult = get_type_multiplier(mv["type"], dfn["types"])
    
    if mult == 0: 
        b["log"] += f"{atk['name']} used {mv['name']} (0 DMG)\n"
    else:
        pow = mv.get("power", 0)
        if pow > 0:
            stab = 1.5 if mv["type"] in atk["types"] else 1.0
            crit = 1.5 if random.random() < 0.06 else 1.0
            dmg = max(1, int(((42 * pow * (atk["atk"] / max(1, dfn["def"]))) / 50 + 2) * mult * stab * crit * random.uniform(0.85, 1.0)))
            dfn["hp"] = max(0, dfn["hp"] - dmg)
            b["log"] += f"{atk['name']} used {mv['name']} ({dmg} DMG)\n"
        else:
            b["log"] += f"{atk['name']} used {mv['name']}\n"

    if dfn["hp"] <= 0:
        b["log"] += f"{dfn['name']} fainted!\n"

def check_faint_state(bot, chat_id, battle_id):
    b = gym_battles[battle_id]
    ai_poke = b["ai_team"][b["ai_idx"]]
    player_poke = b["player_team"][b["player_idx"]]

    if ai_poke["hp"] <= 0:
        if all(p["hp"] <= 0 for p in b["ai_team"]):
            leader = GYM_LEADERS[b["leader"]]
            badge_icon = leader.get("icon", "")
            db.add_badge(b["player_id"], f"{badge_icon} {leader['badge']}".strip())
            
            b["state"] = "ended"
            player_mention = f"[{escape_md(b['player_name'])}](tg://user?id={b['player_id']})"
            
            win_text = f"{escape_md(b['log'].strip())}\n\n{player_mention} *defeated Gym Leader {escape_md(leader['name'])}*\\!\n🏅 *You earned the {escape_md(badge_icon)} {escape_md(leader['badge'])}*\\!"
            try: bot.edit_message_text(win_text, chat_id, battle_id, parse_mode="MarkdownV2")
            except: pass
            return True
        else:
            for i, p in enumerate(b["ai_team"]):
                if p["hp"] > 0:
                    b["ai_idx"] = i
                    b["log"] += f"\nGym Leader sent out {p['name']}!"
                    break

    if player_poke["hp"] <= 0:
        if all(p["hp"] <= 0 for p in b["player_team"]):
            b["state"] = "ended"
            loss_text = f"{escape_md(b['log'].strip())}\n\n*All your Pokémon fainted\\. You whited out\\!*"
            try: bot.edit_message_text(loss_text, chat_id, battle_id, parse_mode="MarkdownV2")
            except: pass
            return True
        else:
            b["state"] = "force_switch"
            render_gym_ui(bot, chat_id, battle_id)
            return True

    return False

def execute_first_turn(bot, chat_id, battle_id, player_action, player_val):
    b = gym_battles[battle_id]
    b["log"] = ""

    ai_action, ai_val = get_ai_action(b)

    if player_action == "switch":
        resolve_action(b, "switch_player", player_val)
    else:
        resolve_action(b, "player", player_val)

    if check_faint_state(bot, chat_id, battle_id): return 

    b["ai_queued_action"] = ("switch_ai", ai_val) if ai_action == "switch" else ("ai", ai_val)
    b["state"] = "waiting"
    render_gym_ui(bot, chat_id, battle_id)

    threading.Timer(2.0, execute_second_turn, args=(bot, chat_id, battle_id)).start()

def execute_second_turn(bot, chat_id, battle_id):
    b = gym_battles.get(battle_id)
    if not b or b["state"] == "ended": return
    
    action_type, action_val = b.pop("ai_queued_action")
    resolve_action(b, action_type, action_val)

    if check_faint_state(bot, chat_id, battle_id): return

    b["state"] = "menu"
    render_gym_ui(bot, chat_id, battle_id)

# --- SYSTEM ROUTERS ---
def setup_gym_battle(bot, call, leader_key, user_id, chat_id, battle_id):
    try:
        leader = GYM_LEADERS[leader_key]
        region = leader.get("region", "Kanto")
        
        if region == "Kanto":
            roster = ASH_KANTO_ROSTER
        elif region == "Johto":
            roster = ASH_JOHTO_ROSTER
        else:
            roster = ASH_HOENN_ROSTER
            
        num_pokemon = len(leader["team"])
        num_to_sample = min(num_pokemon, len(roster))
        
        player_roster = random.sample(roster, num_to_sample)
        
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

def handle_gym_command(bot, message):
    user_id = message.from_user.id
    
    if GYM_LOCKED and user_id != OWNER_ID:
        return safe_send(bot, message.chat.id, escape_md("The Pokemon League Gyms are currently locked by the Admins!"))
        
    if not db.get_user(user_id): return bot.reply_to(message, "Please /start the bot first!")
    
    render_main_menu(bot, message.chat.id, user_id, reply_to_id=message.message_id)

def handle_gym_callback(bot, call):
    parts = call.data.split("_")
    action = parts[1]
    
    if GYM_LOCKED and action in ["main", "region", "info", "start"] and call.from_user.id != OWNER_ID:
        return bot.answer_callback_query(call.id, "The Gyms are currently locked by the Admins!", show_alert=True)
    
    if action in ["main", "close"]:
        uid = int(parts[2])
        if call.from_user.id != uid: return bot.answer_callback_query(call.id, "Not your menu!", show_alert=True)
            
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
        if call.from_user.id != uid: return bot.answer_callback_query(call.id, "Not your menu!", show_alert=True)
            
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
            
            sent_msg = bot.send_message(call.message.chat.id, "*Dʀᴀғᴛɪɴɢ Oғғɪᴄɪᴀʟ Tᴇᴀᴍs\\.\\.\\.*", parse_mode="MarkdownV2")
            battle_id = sent_msg.message_id
            
            threading.Thread(target=setup_gym_battle, args=(bot, call, param, uid, call.message.chat.id, battle_id)).start()
            return

    battle_id = int(parts[2])
    b = gym_battles.get(battle_id)
    if not b: return bot.answer_callback_query(call.id, "Battle expired.")
    if call.from_user.id != b["player_id"]: return bot.answer_callback_query(call.id, "Not your battle!", show_alert=True)
    
    if b["state"] == "waiting": return bot.answer_callback_query(call.id, "Waiting for Gym Leader...", show_alert=False)

    now = time.time()
    if now - b.get("last_edit", 0) < 1.0:
        return bot.answer_callback_query(call.id, "Too fast!", show_alert=False)
    b["last_edit"] = now
    bot.answer_callback_query(call.id, "")

    if action == "move":
        move_idx = int(parts[3])
        execute_first_turn(bot, call.message.chat.id, battle_id, "move", move_idx)
        
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
            b["log"] = f"You sent out {b['player_team'][poke_idx]['name']}!\n"
            render_gym_ui(bot, call.message.chat.id, battle_id)
        else:
            execute_first_turn(bot, call.message.chat.id, battle_id, "switch", poke_idx)
            
    elif action == "back":
        b["state"] = "menu"
        render_gym_ui(bot, call.message.chat.id, battle_id)
        
    elif action == "run":
        b["state"] = "ended"
        bot.edit_message_text("*You fled from the Gym Battle\\!*", call.message.chat.id, battle_id, parse_mode="MarkdownV2")
