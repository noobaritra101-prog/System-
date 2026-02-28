# main.py
# -*- coding: utf-8 -*-
import telebot
from telebot import types
import asyncio
import time
import datetime
import threading
import os
import shutil
import sqlite3
import random

# Import from our modular files
from config import BOT_TOKEN, OWNER_ID, LOG_GROUP_ID, FLEE_TIMEOUT, REGIONS, DB_FILE, logger
import database as db
from api_utils import (
    escape_md, 
    fetch_random_pokemon_id_and_name, 
    official_shiny_artwork_url, 
    default_pokemon_image, 
    get_species_catch_rate_sync,
    get_pokemon_stats_sync,
    generate_random_team
)

bot = telebot.TeleBot(BOT_TOKEN, parse_mode="MarkdownV2")
active_hunts = {}  
pvp_battles = {}
pending_challenges = {} # Stores P1 names while waiting for P2 to accept
last_api_call = 0  

# ================== GAME LOGIC & UI Helpers ==================
def render_pvp_ui(bot_instance, chat_id, battle_id):
    if battle_id not in pvp_battles: return
    b = pvp_battles[battle_id]
    
    p1_poke = b["p1_team"][b["p1_idx"]]
    p2_poke = b["p2_team"][b["p2_idx"]]
    
    # Generate Team Icons (🔴 alive, 💀 dead)
    p1_team_ui = "".join(["🔴" if i >= b["p1_idx"] else "💀" for i in range(6)])
    p2_team_ui = "".join(["🔴" if i >= b["p2_idx"] else "💀" for i in range(6)])
    
    p1_status = "⏳ Waiting\\.\\.\\." if b["p1_action"] is None else "✅ Ready\\!"
    p2_status = "⏳ Waiting\\.\\.\\." if b["p2_action"] is None else "✅ Ready\\!"

    ui_text = (
        f"{b['log']}\n"
        f"━━━━━━━━━━━━━━\n"
        f"🟦 *Player 1: {escape_md(b['p1_name'])}* [{p1_team_ui}]\n"
        f"🛡️ *{escape_md(p1_poke['name'])}* \\| ❤️ {p1_poke['hp']}/{p1_poke['max_hp']} HP\n"
        f"Status: {p1_status}\n\n"
        f"🆚\n\n"
        f"🟥 *Player 2: {escape_md(b['p2_name'])}* [{p2_team_ui}]\n"
        f"🛡️ *{escape_md(p2_poke['name'])}* \\| ❤️ {p2_poke['hp']}/{p2_poke['max_hp']} HP\n"
        f"Status: {p2_status}\n"
    )
    
    kb = types.InlineKeyboardMarkup()
    
    # Player 1 Move Buttons (2x2 Grid)
    if b["p1_action"] is None:
        kb.row(
            types.InlineKeyboardButton(f"🟦 {p1_poke['moves'][0]}", callback_data=f"p_move_{battle_id}_p1_0"),
            types.InlineKeyboardButton(f"🟦 {p1_poke['moves'][1]}", callback_data=f"p_move_{battle_id}_p1_1")
        )
        kb.row(
            types.InlineKeyboardButton(f"🟦 {p1_poke['moves'][2]}", callback_data=f"p_move_{battle_id}_p1_2"),
            types.InlineKeyboardButton(f"🟦 {p1_poke['moves'][3]}", callback_data=f"p_move_{battle_id}_p1_3")
        )
    
    # Player 2 Move Buttons (2x2 Grid)
    if b["p2_action"] is None:
        kb.row(
            types.InlineKeyboardButton(f"🟥 {p2_poke['moves'][0]}", callback_data=f"p_move_{battle_id}_p2_0"),
            types.InlineKeyboardButton(f"🟥 {p2_poke['moves'][1]}", callback_data=f"p_move_{battle_id}_p2_1")
        )
        kb.row(
            types.InlineKeyboardButton(f"🟥 {p2_poke['moves'][2]}", callback_data=f"p_move_{battle_id}_p2_2"),
            types.InlineKeyboardButton(f"🟥 {p2_poke['moves'][3]}", callback_data=f"p_move_{battle_id}_p2_3")
        )
        
    try:
        bot_instance.edit_message_text(ui_text, chat_id, battle_id, reply_markup=kb, parse_mode="MarkdownV2")
    except Exception as e:
        logger.error(f"UI Update error: {e}")

def auto_flee(message_id, chat_id, pokemon_name):
    if message_id not in active_hunts:
        return
    try:
        bot.edit_message_caption(
            caption=f"💨 The wild ✨ *{escape_md(pokemon_name.capitalize())}* fled\\!",
            chat_id=chat_id, message_id=message_id, reply_markup=None, parse_mode="MarkdownV2"
        )
    except Exception as e:
        logger.error(f"Error in auto-flee: {e}")
    active_hunts.pop(message_id, None)

async def start_scout(chat_id, user_id, reply_to_id=None):
    global last_api_call
    user = db.get_user(user_id)
    if not user:
        bot.send_message(chat_id, escape_md("⚠️ Please /start the bot first."), reply_to_message_id=reply_to_id)
        return
        
    tries_left, region = db.update_user_tries(user_id)
    if tries_left is None:
        bot.send_message(chat_id, escape_md("⚠️ Error checking your profile."), reply_to_message_id=reply_to_id)
        return
    if tries_left <= 0:
        bot.send_message(chat_id, escape_md("💤 You have no scouts left today. Rest and come back tomorrow!"), reply_to_message_id=reply_to_id)
        return
    if any(hunt["user_id"] == user_id for hunt in active_hunts.values()):
        bot.send_message(chat_id, escape_md("⏳ You already have an active scout. Complete it first!"), reply_to_message_id=reply_to_id)
        return

    poke_id, name, base_id = await fetch_random_pokemon_id_and_name()
    if not poke_id:
        bot.send_message(chat_id, escape_md("❌ Failed to find a Pokémon. Try again."), reply_to_message_id=reply_to_id)
        return

    img_url = official_shiny_artwork_url(base_id)
    caption = f"🌍 A wild ✨ *{escape_md(name)}* appeared in *{escape_md(region)}*\\!\n\n🎒 What will you do?"
    
    kb = types.InlineKeyboardMarkup()
    kb.add(
        types.InlineKeyboardButton("🔴 Catch", callback_data=f"catch_{user_id}_{poke_id}_{name[:16]}"),
        types.InlineKeyboardButton("🏃‍♂️ Run", callback_data=f"run_{user_id}_{name[:16]}")
    )

    current_time = time.time()
    if current_time - last_api_call < 0.2:
        await asyncio.sleep(0.2)
    last_api_call = current_time

    try:
        sent = bot.send_photo(chat_id, img_url, caption=caption, reply_to_message_id=reply_to_id, reply_markup=kb, parse_mode="MarkdownV2")
        timer = threading.Timer(FLEE_TIMEOUT, auto_flee, args=(sent.message_id, chat_id, name))
        timer.start()
        active_hunts[sent.message_id] = {"user_id": user_id, "start_time": time.time(), "timer": timer, "name": name}
    except Exception as e:
        logger.error(f"Failed to send scout photo: {e}")

# ================== USER COMMANDS ==================
@bot.message_handler(commands=["start"])
def cmd_start(message):
    is_new = db.add_user_if_new(message.from_user.id)
    if message.chat.type in ["group", "supergroup"]:
        db.add_group(message.chat.id)
        
    kb = types.InlineKeyboardMarkup()
    kb.add(
        types.InlineKeyboardButton("Main Group ✨", url="https://t.me/sexagamechat"),
        types.InlineKeyboardButton("Owner 👑", url="https://t.me/Dark_monarchx")
    )
    text = "🌟 *Welcome to the Pokémon Safari* 🌟\n\n🔎 Use /scout to search for shiny Pokémon\\.\n🌍 Use /travel to change your region\\.\n📱 Use /pokedex `<name>` to check stats\\.\n🥊 Reply to a user with /pvp to battle\\!"
    bot.reply_to(message, text, reply_markup=kb, parse_mode="MarkdownV2")
    
    if is_new and LOG_GROUP_ID is not None:
        first = message.from_user.first_name or ""
        username = f"@{message.from_user.username}" if message.from_user.username else ""
        try:
            bot.send_message(LOG_GROUP_ID, escape_md(f"🔔 New Trainer: {first} {username} (ID: {message.from_user.id}) started the bot in chat {message.chat.id}."))
        except Exception as e:
            logger.error(f"Failed to send start notification: {str(e)}")

@bot.message_handler(commands=["getid"])
def cmd_getid(message):
    bot.reply_to(message, escape_md(f"🆔 Chat ID: {message.chat.id}\n📁 Chat Type: {message.chat.type}"))

@bot.message_handler(commands=["profile"])
def cmd_profile(message):
    user = db.get_user(message.from_user.id)
    if not user:
        return bot.reply_to(message, escape_md("⚠️ Please /start the bot first."))
    tries_left, region = db.update_user_tries(message.from_user.id)
    count = len(db.list_user_pokemon_names(message.from_user.id))
    
    profile_text = (
        f"👤 *Trainer Profile*\n"
        f"━━━━━━━━━━━━━━\n"
        f"🌍 *Region:* {escape_md(region)}\n"
        f"🏆 *Pokémon Caught:* {count}\n"
        f"🔋 *Scouts Left:* {tries_left}/300"
    )
    bot.reply_to(message, profile_text, parse_mode="MarkdownV2")

@bot.message_handler(commands=["travel"])
def cmd_travel(message):
    if not db.get_user(message.from_user.id):
        return bot.reply_to(message, escape_md("⚠️ Please /start the bot first."))
    kb = types.InlineKeyboardMarkup()
    for r in REGIONS:
        kb.add(types.InlineKeyboardButton(f"✈️ {r}", callback_data=f"travel_{message.from_user.id}_{r}"))
    bot.reply_to(message, "*Choose a region to travel to:*", reply_markup=kb, parse_mode="MarkdownV2")

@bot.message_handler(commands=["scout"])
def cmd_scout(message):
    asyncio.run(start_scout(message.chat.id, message.from_user.id, message.message_id))

@bot.message_handler(commands=["pokedex"])
def cmd_pokedex(message):
    parts = message.text.split(maxsplit=1)
    if len(parts) < 2:
        return bot.reply_to(message, escape_md("📝 Usage: /pokedex <pokemon_name>"))
    
    pokemon_name = parts[1].strip()
    types_list, stats = get_pokemon_stats_sync(pokemon_name)
    
    if not stats:
        return bot.reply_to(message, f"❌ Could not find data for *{escape_md(pokemon_name)}*\\.", parse_mode="MarkdownV2")
    
    types_str = " \\| ".join(types_list)
    stats_str = "\n".join([f"🔸 *{escape_md(k)}:* {v}" for k, v in stats.items()])
    
    dex_text = (
        f"📱 *Pokédex Data: {escape_md(pokemon_name.capitalize())}*\n"
        f"🧬 *Type:* {escape_md(types_str)}\n\n"
        f"📊 *Base Stats:*\n"
        f"{stats_str}"
    )
    bot.reply_to(message, dex_text, parse_mode="MarkdownV2")

@bot.message_handler(commands=["mypokemon"])
def cmd_mypokemon(message):
    user_id = message.from_user.id
    if not db.get_user(user_id):
        return bot.reply_to(message, escape_md("⚠️ Please /start the bot first."))
    names = db.list_user_pokemon_names(user_id)
    if not names:
        return bot.reply_to(message, escape_md("🎒 You don't have any Pokémon yet."))
    
    page_size = 20
    pages = [names[i:i + page_size] for i in range(0, len(names), page_size)]
    
    def get_page_text(page_idx):
        poke_list = "\n".join(f"➥ {escape_md(n)}" for n in pages[page_idx])
        return f"🎒 *Your Pokémon* \\(Page {page_idx + 1}/{len(pages)}\\):\n\n{poke_list}"
    
    def make_kb(current_page, uid, num_pages):
        kb = types.InlineKeyboardMarkup(row_width=4)
        kb.add(
            types.InlineKeyboardButton("<<", callback_data=f"mypoke_{uid}_0"),
            types.InlineKeyboardButton("<", callback_data=f"mypoke_{uid}_{max(0, current_page - 1)}"),
            types.InlineKeyboardButton(">", callback_data=f"mypoke_{uid}_{min(num_pages - 1, current_page + 1)}"),
            types.InlineKeyboardButton(">>", callback_data=f"mypoke_{uid}_{num_pages - 1}")
        )
        return kb
        
    kb = make_kb(0, user_id, len(pages)) if len(pages) > 1 else None
    bot.reply_to(message, get_page_text(0), reply_markup=kb, parse_mode="MarkdownV2")

@bot.message_handler(commands=["inspect"])
def cmd_inspect(message):
    user = db.get_user(message.from_user.id)
    if not user:
        return bot.reply_to(message, escape_md("⚠️ Please /start the bot first."))
    parts = message.text.split(maxsplit=1)
    if len(parts) < 2:
        return bot.reply_to(message, escape_md("📝 Usage: /inspect <pokemon_name>"))
    
    name = parts[1].strip().lower()
    names = [n.lower() for n in db.list_user_pokemon_names(message.from_user.id)]
    if name not in names:
        return bot.reply_to(message, escape_md("❌ You don't own this Pokémon."))
        
    async def fetch_pokemon_image():
        import aiohttp
        async with aiohttp.ClientSession() as session:
            try:
                async with session.get(f"https://pokeapi.co/api/v2/pokemon/{name}", timeout=15) as response:
                    if response.status != 200: return None
                    data = await response.json()
                    return official_shiny_artwork_url(data["id"])
            except: return None

    img_url = asyncio.run(fetch_pokemon_image())
    if not img_url:
        return bot.reply_to(message, escape_md(f"⚠️ Couldn't fetch info for {name}."))
    bot.send_photo(message.chat.id, img_url, caption=f"✨ *{escape_md(name.capitalize())}* \\(Shiny\\)", parse_mode="MarkdownV2")

@bot.message_handler(commands=["release"])
def cmd_release(message):
    user = db.get_user(message.from_user.id)
    if not user:
        return bot.reply_to(message, escape_md("⚠️ Please /start the bot first."))
    parts = message.text.split(maxsplit=1)
    if len(parts) < 2:
        return bot.reply_to(message, escape_md("📝 Usage: /release <pokemon_name>"))
        
    poke_name = parts[1].strip().capitalize()
    if db.delete_pokemon(message.from_user.id, poke_name):
        bot.reply_to(message, escape_md(f"👋 You released {poke_name} back into the wild."))
    else:
        bot.reply_to(message, escape_md(f"❌ You don't have a {poke_name} to release."))

@bot.message_handler(commands=["flex", "top"])
def cmd_flex(message):
    rows = db.get_top_trainers(5)
    if not rows:
        return bot.reply_to(message, escape_md("📉 No trainers on the leaderboard yet."))
    lines = [f"{rank}\\. 👤 *User {uid}* — {cnt} Pokémon" for rank, (uid, cnt) in enumerate(rows, start=1)]
    bot.reply_to(message, "🏆 *Top Trainers Leaderboard:*\n\n" + "\n".join(lines), parse_mode="MarkdownV2")

@bot.message_handler(commands=["pvp"])
def cmd_pvp(message):
    if not message.reply_to_message:
        return bot.reply_to(message, escape_md("⚠️ You must reply to another player's message to challenge them!"))
    
    p1_id = message.from_user.id
    p2_id = message.reply_to_message.from_user.id
    p2_name = message.reply_to_message.from_user.first_name

    if p1_id == p2_id:
        return bot.reply_to(message, escape_md("❌ You can't challenge yourself!"))

    kb = types.InlineKeyboardMarkup()
    kb.add(
        types.InlineKeyboardButton("⚔️ Accept Challenge", callback_data=f"pvp_accept_{p1_id}_{p2_id}"),
        types.InlineKeyboardButton("❌ Decline", callback_data=f"pvp_decline_{p1_id}_{p2_id}")
    )
    
    sent = bot.reply_to(message, f"🥊 *{escape_md(message.from_user.first_name)}* challenged *{escape_md(p2_name)}* to a 6v6 Random Battle\\!\n\nDo you accept?", reply_markup=kb, parse_mode="MarkdownV2")
    
    # Store the challenger's name safely so we can use it during the loading phase
    pending_challenges[sent.message_id] = message.from_user.first_name

# ================== ADMIN COMMANDS ==================
def is_owner(message):
    if message.from_user.id != OWNER_ID:
        bot.reply_to(message, escape_md("🚫 This command is for owner-sama only."))
        return False
    return True

@bot.message_handler(commands=["plist"])
def cmd_plist(message):
    if not is_owner(message): return
    parts = message.text.split(maxsplit=1)
    if len(parts) < 2:
        return bot.reply_to(message, escape_md("📝 Usage: /plist <user_id>"))
    try:
        uid = int(parts[1])
        names = db.list_user_pokemon_names(uid)
        if not names:
            return bot.reply_to(message, escape_md(f"User {uid} has no Pokémon."))
        page_size = 20
        pages = [names[i:i + page_size] for i in range(0, len(names), page_size)]
        
        def make_kb(current_page, num_pages):
            kb = types.InlineKeyboardMarkup(row_width=4)
            kb.add(
                types.InlineKeyboardButton("<<", callback_data=f"plist_{uid}_0"),
                types.InlineKeyboardButton("<", callback_data=f"plist_{uid}_{max(0, current_page - 1)}"),
                types.InlineKeyboardButton(">", callback_data=f"plist_{uid}_{min(num_pages - 1, current_page + 1)}"),
                types.InlineKeyboardButton(">>", callback_data=f"plist_{uid}_{num_pages - 1}")
            )
            return kb
            
        text = f"🎒 *Pokémon for User {uid}* \\(Page 1/{len(pages)}\\):\n" + "\n".join(f"\\- {escape_md(n)}" for n in pages[0])
        bot.reply_to(message, text, reply_markup=make_kb(0, len(pages)) if len(pages) > 1 else None, parse_mode="MarkdownV2")
    except Exception as e:
        bot.reply_to(message, escape_md(f"Error: {str(e)}"))

@bot.message_handler(commands=["take"])
def cmd_take(message):
    if not is_owner(message): return
    parts = message.text.split(maxsplit=2)
    if len(parts) < 3: return bot.reply_to(message, escape_md("📝 Usage: /take <user_id> <pokemon_name>"))
    try:
        uid, poke_name = int(parts[1]), parts[2].strip().capitalize()
        if db.delete_pokemon(uid, poke_name):
            bot.reply_to(message, escape_md(f"✅ Removed {poke_name} from user {uid}."))
        else:
            bot.reply_to(message, escape_md(f"❌ User {uid} does not have {poke_name}."))
    except Exception as e:
        bot.reply_to(message, escape_md(f"Error: {str(e)}"))

@bot.message_handler(commands=["give"])
def cmd_give(message):
    if not is_owner(message): return
    parts = message.text.split(maxsplit=2)
    if len(parts) < 3: return bot.reply_to(message, escape_md("📝 Usage: /give <user_id> <pokemon_name>"))
    try:
        uid, poke_name = int(parts[1]), parts[2].strip().capitalize()
        db.add_caught_pokemon(uid, poke_name, "Gift")
        bot.reply_to(message, escape_md(f"🎁 Gave {poke_name} to user {uid}."))
    except Exception as e:
        bot.reply_to(message, escape_md(f"Error: {str(e)}"))

@bot.message_handler(commands=["bcast", "gcast"])
def cmd_broadcasts(message):
    if not is_owner(message): return
    if not message.reply_to_message:
        return bot.reply_to(message, escape_md("⚠️ Please reply to a message to forward it."))
        
    is_gcast = message.text.startswith("/gcast")
    targets = db.get_all_groups() if is_gcast else db.get_all_users()
    success, failed = 0, 0
    
    for target_id in targets:
        try:
            bot.forward_message(target_id, message.chat.id, message.reply_to_message.message_id)
            success += 1
            time.sleep(0.1) # Prevent flood limits
        except: failed += 1
        
    bot.reply_to(message, escape_md(f"📢 Broadcast complete! Success: {success}, Failed: {failed}"))

@bot.message_handler(commands=["gcs"])
def cmd_gcs(message):
    if not is_owner(message): return
    groups = db.get_all_groups()
    if not groups: return bot.reply_to(message, escape_md("The bot is not in any groups."))
    text = f"🏢 *Groups \\({len(groups)}\\):*\n" + "\n".join(f"\\- `{gid}`" for gid in groups)
    bot.reply_to(message, text, parse_mode="MarkdownV2")

@bot.message_handler(commands=["allusers"])
def cmd_allusers(message):
    if not is_owner(message): return
    users = db.get_all_users()
    if not users: return bot.reply_to(message, escape_md("No registered trainers."))
    text = f"👥 *Users \\({len(users)}\\):*\n" + "\n".join(f"\\- `{uid}`" for uid in users[:50])
    if len(users) > 50: text += f"\n\n_...and {len(users)-50} more._"
    bot.reply_to(message, text, parse_mode="MarkdownV2")

@bot.message_handler(commands=["leave"])
def cmd_leave(message):
    if not is_owner(message): return
    parts = message.text.split(maxsplit=1)
    if len(parts) < 2: return bot.reply_to(message, escape_md("📝 Usage: /leave <group_id>"))
    try:
        group_id = int(parts[1])
        bot.leave_chat(group_id)
        db.remove_group(group_id)
        bot.reply_to(message, escape_md(f"✅ Left group {group_id}."))
    except Exception as e:
        bot.reply_to(message, escape_md(f"Error: {str(e)}"))

@bot.message_handler(commands=["reset"])
def cmd_reset(message):
    if not is_owner(message): return
    parts = message.text.split(maxsplit=1)
    if len(parts) < 2: return bot.reply_to(message, escape_md("📝 Usage: /reset <user_id>"))
    try:
        uid = int(parts[1])
        conn = sqlite3.connect(DB_FILE)
        cur = conn.cursor()
        cur.execute("UPDATE users SET tries_left=300, last_reset=? WHERE user_id=?", (str(datetime.date.today()), uid))
        conn.commit()
        conn.close()
        bot.reply_to(message, escape_md(f"🔄 Reset scouts for user {uid}."))
    except Exception as e:
        bot.reply_to(message, escape_md(f"Error: {str(e)}"))

@bot.message_handler(commands=["backup"])
def cmd_backup(message):
    if not is_owner(message): return
    if os.path.exists(DB_FILE):
        with open(DB_FILE, "rb") as f:
            bot.send_document(OWNER_ID, f, caption=escape_md("📦 Database Backup"))
    else:
        bot.reply_to(message, escape_md("❌ No database file found."))

@bot.message_handler(commands=["restore"])
def cmd_restore(message):
    if not is_owner(message): return
    bot.reply_to(message, escape_md("📥 Send me the .db file to restore. Max size: 20MB."))

@bot.message_handler(content_types=["document"])
def handle_restore_file(message):
    if not is_owner(message): return
    if not message.document.file_name.endswith((".db", ".sqlite", ".db3")):
        return bot.reply_to(message, escape_md("❌ Invalid file format. Need .db, .sqlite, or .db3"))
    try:
        if os.path.exists(DB_FILE): shutil.copy(DB_FILE, f"{DB_FILE}.backup_{int(time.time())}")
        file_info = bot.get_file(message.document.file_id)
        data = bot.download_file(file_info.file_path)
        with open(DB_FILE, "wb") as f: f.write(data)
        bot.reply_to(message, escape_md("✅ Database restored successfully."))
    except Exception as e:
        bot.reply_to(message, escape_md(f"Error restoring: {str(e)}"))

@bot.message_handler(commands=["debug"])
def cmd_debug(message):
    if not is_owner(message): return
    conn = sqlite3.connect(DB_FILE)
    cur = conn.cursor()
    u_c = cur.execute("SELECT COUNT(*) FROM users").fetchone()[0]
    p_c = cur.execute("SELECT COUNT(*) FROM pokemons").fetchone()[0]
    g_c = cur.execute("SELECT COUNT(*) FROM groups").fetchone()[0]
    conn.close()
    
    status = (
        f"🛠 *Bot Debug Info*\n"
        f"━━━━━━━━━━━━\n"
        f"👥 *Trainers:* {u_c}\n"
        f"🏆 *Pokémon:* {p_c}\n"
        f"🎯 *Active Hunts:* {len(active_hunts)}\n"
        f"⚔️ *Active PvP:* {len(pvp_battles)}\n"
        f"🏢 *Groups:* {g_c}"
    )
    bot.reply_to(message, status, parse_mode="MarkdownV2")

@bot.message_handler(commands=["clearhunts"])
def cmd_clearhunts(message):
    if not is_owner(message): return
    for hunt in active_hunts.values():
        if "timer" in hunt: hunt["timer"].cancel()
    active_hunts.clear()
    pvp_battles.clear()
    bot.reply_to(message, escape_md("🧹 All active hunts and PvP battles cleared."))

# ================== GROUP TRACKING ==================
@bot.chat_member_handler()
def handle_chat_member_update(update):
    new_status = update.new_chat_member.status
    if new_status in ["member", "administrator"] and update.chat.type in ["group", "supergroup"]:
        db.add_group(update.chat.id)
    elif new_status in ["kicked", "left"]:
        db.remove_group(update.chat.id)

# ================== CALLBACKS ==================
@bot.callback_query_handler(func=lambda c: True)
def cb_handler(call):
    try:
        # --- SCOUT & CATCH CALLBACKS ---
        if call.data.startswith("travel_"):
            _, uid_str, region = call.data.split("_", 2)
            if call.from_user.id != int(uid_str):
                return bot.answer_callback_query(call.id, "This selection is not for you.")
                
            conn = sqlite3.connect(DB_FILE)
            cur = conn.cursor()
            cur.execute("UPDATE users SET region=? WHERE user_id=?", (region, int(uid_str)))
            conn.commit()
            conn.close()
            
            bot.edit_message_text(f"✈️ You successfully travelled to *{escape_md(region)}*\\.", call.message.chat.id, call.message.message_id, parse_mode="MarkdownV2")

        elif call.data.startswith("catch_"):
            _, uid_str, pid_str, name = call.data.split("_", 3)
            uid, pid = int(uid_str), int(pid_str)
            
            if call.from_user.id != uid:
                return bot.answer_callback_query(call.id, "Hands off! This scout is not yours.")
            if call.message.message_id not in active_hunts:
                return bot.answer_callback_query(call.id, "This scout has expired.")
                
            active_hunts[call.message.message_id]["timer"].cancel()
            bot.edit_message_caption(caption="🔴 *Throwing Pokéball\\.\\.\\.*", chat_id=call.message.chat.id, message_id=call.message.message_id, parse_mode="MarkdownV2")
            
            time.sleep(1.5) 
            
            catch_rate = get_species_catch_rate_sync(pid)
            success = random.random() < max(0.05, min(0.95, catch_rate / 255.0))
            
            if success:
                db.add_caught_pokemon(uid, name.capitalize(), db.get_user(uid)[2])
                success_text = f"✨ *Gotcha\\!* Shiny *{escape_md(name.capitalize())}* was caught\\!\n\nUse /pokedex `{escape_md(name.capitalize())}` to check its stats\\."
                bot.edit_message_caption(caption=success_text, chat_id=call.message.chat.id, message_id=call.message.message_id, parse_mode="MarkdownV2")
            else:
                fail_text = f"💨 Oh no\\! Shiny *{escape_md(name.capitalize())}* broke free and fled\\!"
                bot.edit_message_caption(caption=fail_text, chat_id=call.message.chat.id, message_id=call.message.message_id, parse_mode="MarkdownV2")
                
            active_hunts.pop(call.message.message_id, None)

        elif call.data.startswith("run_"):
            _, uid_str, name = call.data.split("_", 2)
            uid = int(uid_str)
            
            if call.from_user.id != uid:
                return bot.answer_callback_query(call.id, "This scout is not yours.")
            if call.message.message_id not in active_hunts:
                return bot.answer_callback_query(call.id, "This scout has expired.")
                
            active_hunts[call.message.message_id]["timer"].cancel()
            bot.edit_message_caption(caption=f"🏃‍♂️ You got away safely from *{escape_md(name.capitalize())}*\\.", chat_id=call.message.chat.id, message_id=call.message.message_id, parse_mode="MarkdownV2")
            active_hunts.pop(call.message.message_id, None)

        elif call.data.startswith("mypoke_") or call.data.startswith("plist_"):
            action, uid_str, page_str = call.data.split("_")
            uid, page_idx = int(uid_str), int(page_str)
            
            if action == "mypoke_" and call.from_user.id != uid:
                return bot.answer_callback_query(call.id, "This is not your bag.")
            if action == "plist_" and call.from_user.id != OWNER_ID:
                return bot.answer_callback_query(call.id, "Owner only.")
                
            names = db.list_user_pokemon_names(uid)
            if not names: return
            
            page_size = 20
            pages = [names[i:i + page_size] for i in range(0, len(names), page_size)]
            if page_idx < 0 or page_idx >= len(pages): return
            
            title = "🎒 *Your Pokémon*" if action == "mypoke_" else f"🎒 *Pokémon for User {uid}*"
            text = f"{title} \\(Page {page_idx + 1}/{len(pages)}\\):\n\n" + "\n".join(f"➥ {escape_md(n)}" for n in pages[page_idx])
            
            kb = types.InlineKeyboardMarkup(row_width=4)
            kb.add(
                types.InlineKeyboardButton("<<", callback_data=f"{action}_{uid}_0"),
                types.InlineKeyboardButton("<", callback_data=f"{action}_{uid}_{max(0, page_idx - 1)}"),
                types.InlineKeyboardButton(">", callback_data=f"{action}_{uid}_{min(len(pages) - 1, page_idx + 1)}"),
                types.InlineKeyboardButton(">>", callback_data=f"{action}_{uid}_{len(pages) - 1}")
            )
            bot.edit_message_text(text, call.message.chat.id, call.message.message_id, reply_markup=kb if len(pages)>1 else None, parse_mode="MarkdownV2")

        # --- PvP BATTLE SYSTEM CALLBACKS ---
        elif call.data.startswith("pvp_accept_"):
            _, p1_id_str, p2_id_str = call.data.split("_")
            p1_id, p2_id = int(p1_id_str), int(p2_id_str)
            
            if call.from_user.id != p2_id:
                return bot.answer_callback_query(call.id, "Only the challenged player can accept!")

            # 1. Answer immediately so the Telegram loading circle stops
            bot.answer_callback_query(call.id, "Challenge Accepted! Preparing the arena...")

            battle_id = call.message.message_id
            chat_id = call.message.chat.id
            
            # Extract player names safely
            p1_name = pending_challenges.pop(battle_id, "Player 1")
            p2_name = call.from_user.first_name

            # 2. Run the heavy team fetching logic in a background thread
            def setup_battle():
                try:
                    bot.edit_message_text("🔄 *Connecting to the PvP Arena\\.\\.\\.*", chat_id, battle_id, parse_mode="MarkdownV2")
                    time.sleep(1)

                    bot.edit_message_text(f"🔍 *Choosing 6 random Pokémon for {escape_md(p1_name)}\\.\\.\\.*", chat_id, battle_id, parse_mode="MarkdownV2")
                    p1_team = asyncio.run(generate_random_team())

                    bot.edit_message_text(f"🔍 *Choosing 6 random Pokémon for {escape_md(p2_name)}\\.\\.\\.*", chat_id, battle_id, parse_mode="MarkdownV2")
                    p2_team = asyncio.run(generate_random_team())

                    bot.edit_message_text("⚙️ *Equipping random moves for both teams\\.\\.\\.*", chat_id, battle_id, parse_mode="MarkdownV2")
                    time.sleep(1.5)

                    if len(p1_team) < 6 or len(p2_team) < 6:
                        return bot.edit_message_text("❌ *Error connecting to PokeAPI\\. Try again\\.*", chat_id, battle_id, parse_mode="MarkdownV2")

                    # Initialize battle state
                    pvp_battles[battle_id] = {
                        "p1_id": p1_id, "p1_name": p1_name, "p1_team": p1_team, "p1_idx": 0, "p1_action": None,
                        "p2_id": p2_id, "p2_name": p2_name, "p2_team": p2_team, "p2_idx": 0, "p2_action": None,
                        "log": "⚔️ *Battle started\\! What will you do?*"
                    }
                    
                    # Render the UI
                    render_pvp_ui(bot, chat_id, battle_id)
                except Exception as e:
                    logger.error(f"PvP Setup Error: {e}")
                    bot.edit_message_text("❌ *An error occurred while setting up the battle\\.*", chat_id, battle_id, parse_mode="MarkdownV2")

            # Start the background thread
            threading.Thread(target=setup_battle).start()

        elif call.data.startswith("pvp_decline_"):
            _, p1_id_str, p2_id_str = call.data.split("_")
            if call.from_user.id != int(p2_id_str):
                return bot.answer_callback_query(call.id, "Only the challenged player can decline.")
            bot.edit_message_text("❌ *Challenge declined\\.*", call.message.chat.id, call.message.message_id, parse_mode="MarkdownV2")

        elif call.data.startswith("p_move_"):
            parts = call.data.split("_")
            battle_id = int(parts[2])
            player_num = parts[3] # "p1" or "p2"
            move_idx = int(parts[4])
            
            if battle_id not in pvp_battles:
                return bot.answer_callback_query(call.id, "This battle is over.")
                
            b = pvp_battles[battle_id]
            user_id = call.from_user.id
            
            if (player_num == "p1" and user_id != b["p1_id"]) or (player_num == "p2" and user_id != b["p2_id"]):
                return bot.answer_callback_query(call.id, "These are not your moves!")
                
            if b[f"{player_num}_action"] is not None:
                return bot.answer_callback_query(call.id, "You already locked in your move!")
                
            # Lock in action
            active_poke = b[f"{player_num}_team"][b[f"{player_num}_idx"]]
            b[f"{player_num}_action"] = active_poke["moves"][move_idx]
            bot.answer_callback_query(call.id, f"Locked in {b[f'{player_num}_action']}!")
            
            # Wait for both players to pick their moves
            if b["p1_action"] is None or b["p2_action"] is None:
                render_pvp_ui(bot, call.message.chat.id, battle_id)
                return
                
            # --- RESOLVE TURN ---
            p1_poke = b["p1_team"][b["p1_idx"]]
            p2_poke = b["p2_team"][b["p2_idx"]]
            
            # Determine turn order by Base Speed
            first, second = ("p1", "p2") if p1_poke["spd"] >= p2_poke["spd"] else ("p2", "p1")
            log = f"⚔️ *Turn Resolved\\!*\n\n"
            
            for attacker in [first, second]:
                defender = "p2" if attacker == "p1" else "p1"
                atk_poke = b[f"{attacker}_team"][b[f"{attacker}_idx"]]
                def_poke = b[f"{defender}_team"][b[f"{defender}_idx"]]
                move_used = b[f"{attacker}_action"]
                
                # Deal Damage
                dmg = max(1, int(((atk_poke["atk"] / def_poke["def"]) * random.randint(40, 100)) / 2))
                def_poke["hp"] -= dmg
                log += f"🔹 {escape_md(atk_poke['name'])} used {escape_md(move_used)}\\! Dealt {dmg} DMG\\.\n"
                
                # Check for death
                if def_poke["hp"] <= 0:
                    log += f"💀 *{escape_md(def_poke['name'])} fainted\\!*\n"
                    b[f"{defender}_idx"] += 1
                    
                    # Check for win condition
                    if b[f"{defender}_idx"] >= 6:
                        winner_name = b[f'{attacker}_name']
                        log += f"\n🏆 *{escape_md(winner_name)} Wins the Battle\\!*"
                        bot.edit_message_text(log, call.message.chat.id, battle_id, parse_mode="MarkdownV2")
                        pvp_battles.pop(battle_id, None)
                        return
                    break # Stop turn if someone dies
            
            # Reset actions for the next turn
            b["log"] = log
            b["p1_action"] = None
            b["p2_action"] = None
            render_pvp_ui(bot, call.message.chat.id, battle_id)

    except Exception as e:
        logger.error(f"Callback handler error: {e}")

# ================== RUN ==================
if __name__ == "__main__":
    db.init_db()
    logger.info("Bot is starting...")
    bot.delete_webhook()
    bot.infinity_polling(skip_pending=True)
