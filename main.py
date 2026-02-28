# main.py
# -*- coding: utf-8 -*-
import telebot
from telebot import types
import asyncio
import time
import datetime
import threading
import os
import sqlite3
import random

# Import from our modular files
from config import BOT_TOKEN, OWNER_ID, LOG_GROUP_ID, FLEE_TIMEOUT, REGIONS, logger
import database as db
from api_utils import (
    escape_md, 
    fetch_random_pokemon_id_and_name_sync, 
    official_shiny_artwork_url, 
    get_species_catch_rate_sync,
    get_pokemon_stats_sync,
    generate_random_team
)

bot = telebot.TeleBot(BOT_TOKEN, parse_mode="MarkdownV2")
active_hunts = {}  
pvp_battles = {}
pending_challenges = {} 
last_api_call = 0  

# ================== GAME LOGIC & UI Helpers ==================
def is_in_battle(user_id):
    """Checks if a user is currently in an active PvP battle."""
    for b in pvp_battles.values():
        if user_id in (b["p1_id"], b["p2_id"]):
            return True
    return False

def get_hp_bar(current, maximum, length=10):
    """Generates the ▰▰▰▱▱ HP bar."""
    if maximum <= 0: return "▱" * length
    filled = int((current / maximum) * length)
    filled = max(0, min(length, filled))
    return "▰" * filled + "▱" * (length - filled)

def render_pvp_ui(bot_instance, chat_id, battle_id):
    if battle_id not in pvp_battles: return
    b = pvp_battles[battle_id]
    
    turn = b["current_turn"] # "p1" or "p2"
    
    p1_poke = b["p1_team"][b["p1_idx"]]
    p2_poke = b["p2_team"][b["p2_idx"]]
    
    p1_hp_bar = get_hp_bar(p1_poke["hp"], p1_poke["max_hp"])
    p2_hp_bar = get_hp_bar(p2_poke["hp"], p2_poke["max_hp"])
    
    active_player_name = b[turn + "_name"]
    active_poke = b[turn + "_team"][b[turn + "_idx"]]
    
    # Format moves for the text block
    moves_text = "\n".join([f"🔹 {escape_md(m['name'])} \\| Acc: {m['acc']}% \\| Pw: {m['power']}" for m in active_poke["moves"]])

    ui_text = (
        f"{escape_md(p1_poke['name'])} vs {escape_md(p2_poke['name'])}\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"👤 *{escape_md(b['p1_name'])}*\n"
        f"🛡️ {escape_md(p1_poke['name'])} \\({escape_md(p1_poke['types'])}\\)\n"
        f"🌟 Level 100\n"
        f"HP {p1_hp_bar}\n"
        f"❤️ {p1_poke['hp']}/{p1_poke['max_hp']}\n\n"
        f"🆚\n\n"
        f"👤 *{escape_md(b['p2_name'])}*\n"
        f"🛡️ {escape_md(p2_poke['name'])} \\({escape_md(p2_poke['types'])}\\)\n"
        f"🌟 Level 100\n"
        f"HP {p2_hp_bar}\n"
        f"❤️ {p2_poke['hp']}/{p2_poke['max_hp']}\n"
        f"━━━━━━━━━━━━━━━━━\n"
        f"🎯 *Current Turn* \\- {escape_md(active_player_name)}\n\n"
        f"*Moves Details:*\n"
        f"{moves_text}"
    )
    
    # Inline Buttons ONLY for the current turn player
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
        bot_instance.edit_message_text(ui_text, chat_id, battle_id, reply_markup=kb, parse_mode="MarkdownV2")
    except Exception as e:
        logger.error(f"UI Update error: {e}")

def auto_flee(message_id, chat_id, pokemon_name):
    if message_id not in active_hunts: return
    try:
        bot.edit_message_caption(
            caption=f"💨 The wild ✨ *{escape_md(pokemon_name.capitalize())}* fled\\!",
            chat_id=chat_id, message_id=message_id, reply_markup=None, parse_mode="MarkdownV2"
        )
    except Exception as e:
        logger.error(f"Error in auto-flee: {e}")
    active_hunts.pop(message_id, None)

def start_scout(chat_id, user_id, reply_to_id=None):
    global last_api_call
    if not db.get_user(user_id):
        return bot.send_message(chat_id, escape_md("⚠️ Please /start the bot first."), reply_to_message_id=reply_to_id)
        
    if is_in_battle(user_id):
        return bot.send_message(chat_id, escape_md("⚔️ You cannot scout while engaged in a PvP battle!"), reply_to_message_id=reply_to_id)
        
    tries_left, region = db.update_user_tries(user_id)
    if tries_left is None:
        return bot.send_message(chat_id, escape_md("⚠️ Error checking your profile."), reply_to_message_id=reply_to_id)
    if tries_left <= 0:
        return bot.send_message(chat_id, escape_md("💤 You have no scouts left today. Rest and come back tomorrow!"), reply_to_message_id=reply_to_id)
    if any(hunt["user_id"] == user_id for hunt in active_hunts.values()):
        return bot.send_message(chat_id, escape_md("⏳ You already have an active scout. Complete it first!"), reply_to_message_id=reply_to_id)

    poke_id, name, base_id = fetch_random_pokemon_id_and_name_sync()
    if not poke_id:
        return bot.send_message(chat_id, escape_md("❌ Failed to find a Pokémon. Try again."), reply_to_message_id=reply_to_id)

    img_url = official_shiny_artwork_url(base_id)
    caption = f"🌍 A wild ✨ *{escape_md(name)}* appeared in *{escape_md(region)}*\\!\n\n🎒 What will you do?"
    
    kb = types.InlineKeyboardMarkup()
    kb.add(
        types.InlineKeyboardButton("🔴 Catch", callback_data=f"catch_{user_id}_{poke_id}_{name[:16]}"),
        types.InlineKeyboardButton("🏃‍♂️ Run", callback_data=f"run_{user_id}_{name[:16]}")
    )

    current_time = time.time()
    if current_time - last_api_call < 0.2: time.sleep(0.2)
    last_api_call = current_time

    try:
        sent = bot.send_photo(chat_id, img_url, caption=caption, reply_to_message_id=reply_to_id, reply_markup=kb, parse_mode="MarkdownV2")
        timer = threading.Timer(FLEE_TIMEOUT, auto_flee, args=(sent.message_id, chat_id, name))
        timer.start()
        active_hunts[sent.message_id] = {"user_id": user_id, "start_time": time.time(), "timer": timer, "name": name}
    except Exception as e: logger.error(f"Failed to send scout photo: {e}")

# ================== USER COMMANDS ==================
@bot.message_handler(commands=["start"])
def cmd_start(message):
    is_new = db.add_user_if_new(message.from_user.id)
    if message.chat.type in ["group", "supergroup"]: db.add_group(message.chat.id)
    kb = types.InlineKeyboardMarkup()
    kb.add(types.InlineKeyboardButton("Main Group ✨", url="https://t.me/sexagamechat"), types.InlineKeyboardButton("Owner 👑", url="https://t.me/Dark_monarchx"))
    bot.reply_to(message, "🌟 *Welcome to the Pokémon Safari* 🌟\n\n🔎 /scout \\- Search for shiny Pokémon\n🌍 /travel \\- Change region\n📱 /pokedex `<name>` \\- Check stats\n🥊 /pvp \\- Reply to a user to battle", reply_markup=kb, parse_mode="MarkdownV2")

@bot.message_handler(commands=["profile"])
def cmd_profile(message):
    user = db.get_user(message.from_user.id)
    if not user: return bot.reply_to(message, escape_md("⚠️ Please /start the bot first."))
    tries_left, region = db.update_user_tries(message.from_user.id)
    count = len(db.list_user_pokemon_names(message.from_user.id))
    bot.reply_to(message, f"👤 *Trainer Profile*\n━━━━━━━━━━━━━━\n🌍 *Region:* {escape_md(region)}\n🏆 *Pokémon:* {count}\n🔋 *Scouts Left:* {tries_left}/300", parse_mode="MarkdownV2")

@bot.message_handler(commands=["travel"])
def cmd_travel(message):
    if not db.get_user(message.from_user.id): return bot.reply_to(message, escape_md("⚠️ Please /start the bot first."))
    kb = types.InlineKeyboardMarkup()
    for r in REGIONS: kb.add(types.InlineKeyboardButton(f"✈️ {r}", callback_data=f"travel_{message.from_user.id}_{r}"))
    bot.reply_to(message, "*Choose a region to travel to:*", reply_markup=kb, parse_mode="MarkdownV2")

@bot.message_handler(commands=["scout"])
def cmd_scout(message):
    start_scout(message.chat.id, message.from_user.id, message.message_id)

@bot.message_handler(commands=["pokedex"])
def cmd_pokedex(message):
    parts = message.text.split(maxsplit=1)
    if len(parts) < 2: return bot.reply_to(message, escape_md("📝 Usage: /pokedex <pokemon_name>"))
    types_list, stats = get_pokemon_stats_sync(parts[1].strip())
    if not stats: return bot.reply_to(message, f"❌ Could not find data for *{escape_md(parts[1])}*\\.", parse_mode="MarkdownV2")
    stats_str = "\n".join([f"🔸 *{escape_md(k)}:* {v}" for k, v in stats.items()])
    bot.reply_to(message, f"📱 *Pokédex Data: {escape_md(parts[1].capitalize())}*\n🧬 *Type:* {escape_md(' | '.join(types_list))}\n\n📊 *Base Stats:*\n{stats_str}", parse_mode="MarkdownV2")

@bot.message_handler(commands=["mypokemon"])
def cmd_mypokemon(message):
    user_id = message.from_user.id
    if not db.get_user(user_id): return bot.reply_to(message, escape_md("⚠️ Please /start the bot first."))
    names = db.list_user_pokemon_names(user_id)
    if not names: return bot.reply_to(message, escape_md("🎒 You don't have any Pokémon yet."))
    pages = [names[i:i + 20] for i in range(0, len(names), 20)]
    def make_kb(uid, num_pages):
        kb = types.InlineKeyboardMarkup(row_width=4)
        kb.add(types.InlineKeyboardButton("<<", callback_data=f"mypoke_{uid}_0"), types.InlineKeyboardButton(">>", callback_data=f"mypoke_{uid}_{num_pages - 1}"))
        return kb
    bot.reply_to(message, f"🎒 *Your Pokémon* \\(Page 1/{len(pages)}\\):\n\n" + "\n".join(f"➥ {escape_md(n)}" for n in pages[0]), reply_markup=make_kb(user_id, len(pages)) if len(pages) > 1 else None, parse_mode="MarkdownV2")

@bot.message_handler(commands=["release"])
def cmd_release(message):
    if not db.get_user(message.from_user.id): return bot.reply_to(message, escape_md("⚠️ Please /start the bot first."))
    parts = message.text.split(maxsplit=1)
    if len(parts) < 2: return bot.reply_to(message, escape_md("📝 Usage: /release <pokemon_name>"))
    poke_name = parts[1].strip().capitalize()
    if db.delete_pokemon(message.from_user.id, poke_name): bot.reply_to(message, escape_md(f"👋 You released {poke_name} back into the wild."))
    else: bot.reply_to(message, escape_md(f"❌ You don't have a {poke_name} to release."))

@bot.message_handler(commands=["flex", "top"])
def cmd_flex(message):
    rows = db.get_top_trainers(5)
    if not rows: return bot.reply_to(message, escape_md("📉 No trainers on the leaderboard yet."))
    lines = [f"{rank}\\. 👤 *User {uid}* — {cnt} Pokémon" for rank, (uid, cnt) in enumerate(rows, start=1)]
    bot.reply_to(message, "🏆 *Top Trainers Leaderboard:*\n\n" + "\n".join(lines), parse_mode="MarkdownV2")

@bot.message_handler(commands=["pvp"])
def cmd_pvp(message):
    if not message.reply_to_message: return bot.reply_to(message, escape_md("⚠️ You must reply to another player's message to challenge them!"))
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

@bot.message_handler(commands=["getid"])
def cmd_getid(message):
    bot.reply_to(message, escape_md(f"🆔 Chat ID: {message.chat.id}\n📁 Chat Type: {message.chat.type}"))


# ================== ADMIN COMMANDS ==================
def is_owner(message):
    if message.from_user.id != OWNER_ID:
        bot.reply_to(message, escape_md("🚫 This command is for owner-sama only."))
        return False
    return True

@bot.message_handler(commands=["restore"])
def cmd_restore(message):
    if not is_owner(message): return
    bot.reply_to(message, escape_md("📥 Send me the old SQLite (.db) file to migrate it into the cloud PostgreSQL database. Max size: 20MB."))

@bot.message_handler(content_types=["document"])
def handle_restore_file(message):
    if not is_owner(message): return
    if not message.document.file_name.endswith((".db", ".sqlite", ".db3")):
        return bot.reply_to(message, escape_md("❌ Invalid file. I need the old SQLite database to migrate."))
    
    status_msg = bot.reply_to(message, escape_md("🔄 Downloading local SQLite file..."))
    try:
        file_info = bot.get_file(message.document.file_id)
        data = bot.download_file(file_info.file_path)
        temp_file = f"temp_migrate_{int(time.time())}.db"
        with open(temp_file, "wb") as f: f.write(data)
        
        bot.edit_message_text(escape_md("📦 Extracting data from SQLite..."), chat_id=message.chat.id, message_id=status_msg.message_id)
        conn = sqlite3.connect(temp_file)
        cur = conn.cursor()
        
        cur.execute("SELECT user_id, tries_left, region, last_reset FROM users")
        users_data = [(r[0], r[1], r[2], datetime.datetime.strptime(r[3], "%Y-%m-%d").date()) for r in cur.fetchall()]
        
        cur.execute("SELECT user_id, name, region FROM pokemons")
        pokemons_data = cur.fetchall()
        
        cur.execute("SELECT group_id FROM groups")
        groups_data = cur.fetchall()
        conn.close()
        
        bot.edit_message_text(escape_md(f"☁️ Injecting {len(users_data)} Users, {len(pokemons_data)} Pokémons into Supabase PostgreSQL..."), chat_id=message.chat.id, message_id=status_msg.message_id)
        db.restore_sqlite_data(users_data, pokemons_data, groups_data)
        
        os.remove(temp_file) 
        bot.edit_message_text(escape_md("✅ Migration Complete! Your local data is now securely in the cloud."), chat_id=message.chat.id, message_id=status_msg.message_id)
    except Exception as e:
        logger.error(f"Restore error: {e}")
        bot.edit_message_text(escape_md(f"❌ Error during migration: {str(e)}"), chat_id=message.chat.id, message_id=status_msg.message_id)

@bot.message_handler(commands=["backup"])
def cmd_backup(message):
    if not is_owner(message): return
    bot.reply_to(message, escape_md("☁️ You are on a cloud database now! Backups are handled automatically via Supabase."))

@bot.message_handler(commands=["plist"])
def cmd_plist(message):
    if not is_owner(message): return
    parts = message.text.split(maxsplit=1)
    if len(parts) < 2: return bot.reply_to(message, escape_md("📝 Usage: /plist <user_id>"))
    try:
        uid = int(parts[1])
        names = db.list_user_pokemon_names(uid)
        if not names: return bot.reply_to(message, escape_md(f"User {uid} has no Pokémon."))
        page_size = 20
        pages = [names[i:i + page_size] for i in range(0, len(names), page_size)]
        
        def make_kb(uid, num_pages):
            kb = types.InlineKeyboardMarkup(row_width=4)
            kb.add(
                types.InlineKeyboardButton("<<", callback_data=f"plist_{uid}_0"),
                types.InlineKeyboardButton(">>", callback_data=f"plist_{uid}_{num_pages - 1}")
            )
            return kb
        bot.reply_to(message, f"🎒 *Pokémon for User {uid}* \\(Page 1/{len(pages)}\\):\n\n" + "\n".join(f"\\- {escape_md(n)}" for n in pages[0]), reply_markup=make_kb(uid, len(pages)) if len(pages) > 1 else None, parse_mode="MarkdownV2")
    except Exception as e: bot.reply_to(message, escape_md(f"Error: {str(e)}"))

@bot.message_handler(commands=["take"])
def cmd_take(message):
    if not is_owner(message): return
    parts = message.text.split(maxsplit=2)
    if len(parts) < 3: return bot.reply_to(message, escape_md("📝 Usage: /take <user_id> <pokemon_name>"))
    try:
        uid, poke_name = int(parts[1]), parts[2].strip().capitalize()
        if db.delete_pokemon(uid, poke_name): bot.reply_to(message, escape_md(f"✅ Removed {poke_name} from user {uid}."))
        else: bot.reply_to(message, escape_md(f"❌ User {uid} does not have {poke_name}."))
    except Exception as e: bot.reply_to(message, escape_md(f"Error: {str(e)}"))

@bot.message_handler(commands=["give"])
def cmd_give(message):
    if not is_owner(message): return
    parts = message.text.split(maxsplit=2)
    if len(parts) < 3: return bot.reply_to(message, escape_md("📝 Usage: /give <user_id> <pokemon_name>"))
    try:
        uid, poke_name = int(parts[1]), parts[2].strip().capitalize()
        db.add_caught_pokemon(uid, poke_name, "Gift")
        bot.reply_to(message, escape_md(f"🎁 Gave {poke_name} to user {uid}."))
    except Exception as e: bot.reply_to(message, escape_md(f"Error: {str(e)}"))

@bot.message_handler(commands=["bcast", "gcast"])
def cmd_broadcasts(message):
    if not is_owner(message): return
    if not message.reply_to_message: return bot.reply_to(message, escape_md("⚠️ Please reply to a message to forward it."))
    targets = db.get_all_groups() if message.text.startswith("/gcast") else db.get_all_users()
    success, failed = 0, 0
    for target_id in targets:
        try:
            bot.forward_message(target_id, message.chat.id, message.reply_to_message.message_id)
            success += 1
            time.sleep(0.1)
        except: failed += 1
    bot.reply_to(message, escape_md(f"📢 Broadcast complete! Success: {success}, Failed: {failed}"))

@bot.message_handler(commands=["gcs"])
def cmd_gcs(message):
    if not is_owner(message): return
    groups = db.get_all_groups()
    if not groups: return bot.reply_to(message, escape_md("The bot is not in any groups."))
    bot.reply_to(message, f"🏢 *Groups \\({len(groups)}\\):*\n\n" + "\n".join(f"\\- `{gid}`" for gid in groups), parse_mode="MarkdownV2")

@bot.message_handler(commands=["allusers"])
def cmd_allusers(message):
    if not is_owner(message): return
    users = db.get_all_users()
    if not users: return bot.reply_to(message, escape_md("No registered trainers."))
    text = f"👥 *Users \\({len(users)}\\):*\n\n" + "\n".join(f"\\- `{uid}`" for uid in users[:50])
    if len(users) > 50: text += f"\n\n_\\.\\.\\.and {len(users)-50} more\\._"
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
    except Exception as e: bot.reply_to(message, escape_md(f"Error: {str(e)}"))

@bot.message_handler(commands=["reset"])
def cmd_reset(message):
    if not is_owner(message): return
    parts = message.text.split(maxsplit=1)
    if len(parts) < 2: return bot.reply_to(message, escape_md("📝 Usage: /reset <user_id>"))
    try:
        db.reset_user(int(parts[1]))
        bot.reply_to(message, escape_md(f"🔄 Reset scouts for user {parts[1]}."))
    except Exception as e: bot.reply_to(message, escape_md(f"Error: {str(e)}"))

@bot.message_handler(commands=["debug"])
def cmd_debug(message):
    if not is_owner(message): return
    try:
        u_c, p_c, g_c = db.get_debug_stats()
        bot.reply_to(message, f"🛠 *Bot Debug Info*\n━━━━━━━━━━━━\n👥 *Trainers:* {u_c}\n🏆 *Pokémon:* {p_c}\n🎯 *Active Hunts:* {len(active_hunts)}\n⚔️ *Active PvP:* {len(pvp_battles)}\n🏢 *Groups:* {g_c}", parse_mode="MarkdownV2")
    except Exception as e: bot.reply_to(message, escape_md(f"Error: {str(e)}"))

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
        # --- SCOUT CALLBACKS ---
        if call.data.startswith("catch_") or call.data.startswith("run_"):
            parts = call.data.split("_")
            uid = int(parts[1])
            if call.from_user.id != uid: return bot.answer_callback_query(call.id, "This scout is not yours.")
            if call.message.message_id not in active_hunts: return bot.answer_callback_query(call.id, "This scout has expired.")
            
            active_hunts[call.message.message_id]["timer"].cancel()
            
            if call.data.startswith("catch_"):
                pid, name = int(parts[2]), parts[3]
                bot.edit_message_caption(caption="🔴 *Throwing Pokéball\\.\\.\\.*", chat_id=call.message.chat.id, message_id=call.message.message_id, parse_mode="MarkdownV2")
                time.sleep(1.5) 
                if random.random() < max(0.05, min(0.95, get_species_catch_rate_sync(pid) / 255.0)):
                    db.add_caught_pokemon(uid, name.capitalize(), db.get_user(uid)[2])
                    bot.edit_message_caption(caption=f"✨ *Gotcha\\!* Shiny *{escape_md(name.capitalize())}* was caught\\!", chat_id=call.message.chat.id, message_id=call.message.message_id, parse_mode="MarkdownV2")
                else:
                    bot.edit_message_caption(caption=f"💨 Oh no\\! Shiny *{escape_md(name.capitalize())}* broke free and fled\\!", chat_id=call.message.chat.id, message_id=call.message.message_id, parse_mode="MarkdownV2")
            else:
                name = parts[2]
                bot.edit_message_caption(caption=f"🏃‍♂️ You got away safely from *{escape_md(name.capitalize())}*\\.", chat_id=call.message.chat.id, message_id=call.message.message_id, parse_mode="MarkdownV2")
            active_hunts.pop(call.message.message_id, None)

        elif call.data.startswith("travel_"):
            parts = call.data.split("_", 2)
            uid, region = int(parts[1]), parts[2]
            if call.from_user.id != uid: return bot.answer_callback_query(call.id, "Not your menu.")
            db.update_user_region(uid, region)
            bot.edit_message_text(f"✈️ Travelled to *{escape_md(region)}*\\.", call.message.chat.id, call.message.message_id, parse_mode="MarkdownV2")

        # --- PVP SETUP CALLBACKS ---
        elif call.data.startswith("pvp_accept_"):
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
                    
                    # P1 always goes first arbitrarily on turn 1
                    pvp_battles[battle_id] = {
                        "p1_id": p1_id, "p1_name": p1_name, "p1_team": p1_team, "p1_idx": 0, 
                        "p2_id": p2_id, "p2_name": p2_name, "p2_team": p2_team, "p2_idx": 0, 
                        "current_turn": "p1", "log": "⚔️ *Battle Started\\!*"
                    }
                    render_pvp_ui(bot, chat_id, battle_id)
                except Exception as e:
                    logger.error(f"PvP Setup Error: {e}")
            threading.Thread(target=setup_battle).start()

        elif call.data.startswith("pvp_decline_"):
            if call.from_user.id != int(call.data.split("_")[3]): return bot.answer_callback_query(call.id, "Only the challenged player can decline.")
            bot.edit_message_text("❌ *Challenge declined\\.*", call.message.chat.id, call.message.message_id, parse_mode="MarkdownV2")

        # --- PVP ACTION CALLBACKS (Move, Switch, Run) ---
        elif call.data.startswith("pvp_"):
            parts = call.data.split("_")
            action = parts[1] # move, switch, run
            battle_id = int(parts[2])
            player_num = parts[3] # p1 or p2
            
            if battle_id not in pvp_battles: return bot.answer_callback_query(call.id, "This battle is over.")
            b = pvp_battles[battle_id]
            
            # Authorization Checks
            if call.from_user.id != b[player_num + "_id"]:
                return bot.answer_callback_query(call.id, "These are not your buttons!")
            if b["current_turn"] != player_num:
                return bot.answer_callback_query(call.id, "It is not your turn!")

            atk_team = b[player_num + "_team"]
            atk_poke = atk_team[b[player_num + "_idx"]]
            
            defender = "p2" if player_num == "p1" else "p1"
            def_team = b[defender + "_team"]
            def_poke = def_team[b[defender + "_idx"]]

            # RUN
            if action == "run":
                bot.answer_callback_query(call.id, "You fled!")
                bot.edit_message_text(f"🏃‍♂️ *{escape_md(b[player_num + '_name'])} ran away from the battle\\!*", call.message.chat.id, battle_id, parse_mode="MarkdownV2")
                pvp_battles.pop(battle_id, None)
                return
            
            # SWITCH
            elif action == "switch":
                next_idx = -1
                for i in range(b[player_num + "_idx"] + 1, 6):
                    if atk_team[i]["hp"] > 0:
                        next_idx = i; break
                if next_idx == -1: 
                    for i in range(0, b[player_num + "_idx"]):
                        if atk_team[i]["hp"] > 0:
                            next_idx = i; break
                            
                if next_idx == -1:
                    return bot.answer_callback_query(call.id, "You have no other Pokémon left to switch to!")
                
                b[player_num + "_idx"] = next_idx
                new_poke = atk_team[next_idx]
                b["log"] = f"🔄 *{escape_md(b[player_num + '_name'])}* switched to *{escape_md(new_poke['name'])}*\\!"
                b["current_turn"] = defender
                render_pvp_ui(bot, call.message.chat.id, battle_id)
                return

            # MOVE
            elif action == "move":
                move_idx = int(parts[4])
                move_data = atk_poke["moves"][move_idx]
                
                if random.randint(1, 100) > move_data["acc"]:
                    b["log"] = f"💨 *{escape_md(atk_poke['name'])}* used *{escape_md(move_data['name'])}*, but it missed\\!"
                else:
                    dmg = max(1, int(((atk_poke["atk"] / def_poke["def"]) * move_data["power"]) / 2))
                    def_poke["hp"] -= dmg
                    b["log"] = f"⚔️ *{escape_md(atk_poke['name'])}* used *{escape_md(move_data['name'])}*\\! It dealt {dmg} DMG\\."
                    
                    if def_poke["hp"] <= 0:
                        b["log"] += f"\n💀 *{escape_md(def_poke['name'])} fainted\\!*"
                        b[defender + "_idx"] += 1
                        
                        if b[defender + "_idx"] >= 6:
                            b["log"] += f"\n\n🏆 *{escape_md(b[player_num + '_name'])} WINS THE BATTLE\\!*"
                            bot.edit_message_text(b["log"], call.message.chat.id, battle_id, parse_mode="MarkdownV2")
                            pvp_battles.pop(battle_id, None)
                            return
                        else:
                            next_def_poke = def_team[b[defender + "_idx"]]
                            b["log"] += f"\n🔄 *{escape_md(b[defender + '_name'])}* sent out *{escape_md(next_def_poke['name'])}*\\!"

                b["current_turn"] = defender
                render_pvp_ui(bot, call.message.chat.id, battle_id)

        elif call.data.startswith("mypoke_") or call.data.startswith("plist_"):
            parts = call.data.split("_")
            action, uid, page_idx = parts[0], int(parts[1]), int(parts[2])
            if action == "mypoke" and call.from_user.id != uid: return bot.answer_callback_query(call.id, "This is not your bag.")
            if action == "plist" and call.from_user.id != OWNER_ID: return bot.answer_callback_query(call.id, "Owner only.")
            names = db.list_user_pokemon_names(uid)
            if not names: return
            page_size = 20
            pages = [names[i:i + page_size] for i in range(0, len(names), page_size)]
            if page_idx < 0 or page_idx >= len(pages): return
            title = "🎒 *Your Pokémon*" if action == "mypoke" else f"🎒 *Pokémon for User {uid}*"
            text = f"{title} \\(Page {page_idx + 1}/{len(pages)}\\):\n\n" + "\n".join(f"➥ {escape_md(n)}" for n in pages[page_idx])
            kb = types.InlineKeyboardMarkup(row_width=4)
            kb.add(
                types.InlineKeyboardButton("<<", callback_data=f"{action}_{uid}_0"),
                types.InlineKeyboardButton("<", callback_data=f"{action}_{uid}_{max(0, page_idx - 1)}"),
                types.InlineKeyboardButton(">", callback_data=f"{action}_{uid}_{min(len(pages) - 1, page_idx + 1)}"),
                types.InlineKeyboardButton(">>", callback_data=f"{action}_{uid}_{len(pages) - 1}")
            )
            bot.edit_message_text(text, call.message.chat.id, call.message.message_id, reply_markup=kb if len(pages)>1 else None, parse_mode="MarkdownV2")

    except Exception as e:
        logger.error(f"Callback error: {e}")

if __name__ == "__main__":
    db.init_db()
    logger.info("Bot is starting...")
    bot.delete_webhook()
    bot.infinity_polling(skip_pending=True)
