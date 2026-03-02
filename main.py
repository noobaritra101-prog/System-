# main.py
# -*- coding: utf-8 -*-
import telebot
from telebot import types
import time
import datetime
import threading
import os
import sqlite3
import random

# Import from our modular files
from config import BOT_TOKEN, OWNER_ID, LOG_GROUP_ID, FLEE_TIMEOUT, REGIONS, logger
import database as db
import pvp 
import tasks # <-- Tasks Engine
from api_utils import (
    escape_md, 
    fetch_random_pokemon_id_and_name_sync, 
    official_shiny_artwork_url, 
    get_species_catch_rate_sync,
    get_pokemon_stats_sync,
    get_pokemon_id_sync
)

bot = telebot.TeleBot(BOT_TOKEN, parse_mode="MarkdownV2")
active_hunts = {}  

# ================== GAME LOGIC ==================
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
    if not db.get_user(user_id):
        return bot.send_message(chat_id, escape_md("⚠️ Please /start the bot first."), reply_to_message_id=reply_to_id)
        
    if pvp.is_in_battle(user_id):
        return bot.send_message(chat_id, escape_md("⚔️ You cannot scout while engaged in a PvP battle!"), reply_to_message_id=reply_to_id)
        
    tries_left, region = db.update_user_tries(user_id)
    if tries_left is None:
        return bot.send_message(chat_id, escape_md("⚠️ Error checking your profile."), reply_to_message_id=reply_to_id)
    if tries_left <= 0:
        return bot.send_message(chat_id, escape_md("💤 You have no scouts left today. Rest and come back tomorrow!"), reply_to_message_id=reply_to_id)
    if any(hunt["user_id"] == user_id for hunt in active_hunts.values()):
        return bot.send_message(chat_id, escape_md("⏳ You already have an active scout. Complete it first!"), reply_to_message_id=reply_to_id)

    # Assigns poke_id based on the user's specific region!
    poke_id, name, base_id = fetch_random_pokemon_id_and_name_sync(region)
    
    if not poke_id:
        return bot.send_message(chat_id, escape_md("❌ Failed to find a Pokémon. Try again."), reply_to_message_id=reply_to_id)

    # 1. Update Daily Task Progress for Scouting
    tasks.add_progress(user_id, "scout")

    img_url = official_shiny_artwork_url(base_id)
    caption = f"🌍 A wild ✨ *{escape_md(name)}* appeared in *{escape_md(region)}*\\!\n\n🎒 What will you do?"
    
    kb = types.InlineKeyboardMarkup()
    kb.add(
        types.InlineKeyboardButton("🔴 Catch", callback_data=f"catch_{user_id}_{poke_id}_{name[:16]}"),
        types.InlineKeyboardButton("🏃‍♂️ Run", callback_data=f"run_{user_id}_{name[:16]}")
    )

    try:
        sent = bot.send_photo(chat_id, img_url, caption=caption, reply_to_message_id=reply_to_id, reply_markup=kb, parse_mode="MarkdownV2")
        timer = threading.Timer(FLEE_TIMEOUT, auto_flee, args=(sent.message_id, chat_id, name))
        timer.start()
        active_hunts[sent.message_id] = {"user_id": user_id, "start_time": time.time(), "timer": timer, "name": name}
    except Exception as e: logger.error(f"Failed to send scout photo: {e}")

def process_catch(call, uid, pid, name):
    """Background process for throwing a Pokeball without blocking the bot"""
    try:
        bot.edit_message_caption(caption="🔴 *Throwing Pokéball\\.\\.\\.*", chat_id=call.message.chat.id, message_id=call.message.message_id, parse_mode="MarkdownV2")
        time.sleep(1.5) 
        catch_rate = get_species_catch_rate_sync(pid)
        if random.random() < max(0.05, min(0.95, catch_rate / 255.0)):
            poke_name_capped = name.capitalize()
            db.add_caught_pokemon(uid, poke_name_capped, db.get_user(uid)[2])
            
            # Update Daily Task Progress
            tasks.check_and_update_catch(uid, poke_name_capped)
            
            # Add LIVE log to admin group
            if LOG_GROUP_ID:
                try: 
                    u_name = call.from_user.first_name
                    bot.send_message(LOG_GROUP_ID, f"🟢 *Catch Log:* [{escape_md(u_name)}](tg://user?id={uid}) caught a ✨ Shiny {escape_md(poke_name_capped)}\\!", parse_mode="MarkdownV2")
                except: pass
            
            bot.edit_message_caption(caption=f"✨ *Gotcha\\!* Shiny *{escape_md(poke_name_capped)}* was caught\\!\n\nUse /inspect `{escape_md(poke_name_capped)}` to view it\\.", chat_id=call.message.chat.id, message_id=call.message.message_id, parse_mode="MarkdownV2")
        else:
            bot.edit_message_caption(caption=f"💨 Oh no\\! Shiny *{escape_md(name.capitalize())}* broke free and fled\\!", chat_id=call.message.chat.id, message_id=call.message.message_id, parse_mode="MarkdownV2")
    except Exception as e:
        logger.error(f"Catch error: {e}")

# ================== USER COMMANDS ==================
@bot.message_handler(commands=["start"])
def cmd_start(message):
    is_new = db.add_user_if_new(message.from_user.id)
    if message.chat.type in ["group", "supergroup"]: db.add_group(message.chat.id)
    kb = types.InlineKeyboardMarkup()
    kb.add(types.InlineKeyboardButton("Main Group ✨", url="https://t.me/sexagamechat"), types.InlineKeyboardButton("Owner 👑", url="https://t.me/Dark_monarchx"))
    bot.reply_to(message, "🌟 *Welcome to the Pokémon Safari* 🌟\n\n🔎 /scout \\- Search for shiny Pokémon\n🌍 /travel \\- Change region\n📱 /pokedex `<name>` \\- Check stats\n🥊 /pvp \\- Reply to a user to battle\n🏆 /flex \\- View the Global Leaderboard\n📋 /task \\- Daily Rewards\n⌨️ /open \\- Open scout button \\(DM only\\)", reply_markup=kb, parse_mode="MarkdownV2")
    
    if is_new and LOG_GROUP_ID is not None:
        try: bot.send_message(LOG_GROUP_ID, escape_md(f"🔔 New Trainer: {message.from_user.first_name} (ID: {message.from_user.id}) started the bot."))
        except Exception: pass

# --- DM KEYBOARD MENU ---
@bot.message_handler(commands=["open"])
def cmd_open(message):
    if message.chat.type != "private":
        return bot.reply_to(message, escape_md("⚠️ The /open command only works in private messages (DM)."))
    
    kb = types.ReplyKeyboardMarkup(resize_keyboard=True, row_width=1)
    kb.add(types.KeyboardButton("🔎 Scout"))
    bot.send_message(message.chat.id, escape_md("⌨️ Action menu opened! Use /close to hide it."), reply_markup=kb, parse_mode="MarkdownV2")

@bot.message_handler(commands=["close"])
def cmd_close(message):
    if message.chat.type != "private":
        return bot.reply_to(message, escape_md("⚠️ The /close command only works in private messages (DM)."))
    
    remove_kb = types.ReplyKeyboardRemove()
    bot.send_message(message.chat.id, escape_md("⌨️ Action menu closed! Use /open to bring it back."), reply_markup=remove_kb, parse_mode="MarkdownV2")

@bot.message_handler(func=lambda message: message.text == "🔎 Scout" and message.chat.type == "private")
def text_scout(message):
    threading.Thread(target=start_scout, args=(message.chat.id, message.from_user.id, message.message_id)).start()

# --- DAILY TASKS ---
@bot.message_handler(commands=["task", "tasks"])
def cmd_task(message):
    db.add_user_if_new(message.from_user.id)
    tasks.render_tasks_ui(bot, message.chat.id, message.from_user.id)

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
    threading.Thread(target=start_scout, args=(message.chat.id, message.from_user.id, message.message_id)).start()

@bot.message_handler(commands=["pokedex"])
def cmd_pokedex(message):
    parts = message.text.split(maxsplit=1)
    if len(parts) < 2: return bot.reply_to(message, escape_md("📝 Usage: /pokedex <pokemon_name>"))
    types_list, stats = get_pokemon_stats_sync(parts[1].strip())
    if not stats: return bot.reply_to(message, f"❌ Could not find data for *{escape_md(parts[1])}*\\.", parse_mode="MarkdownV2")
    stats_str = "\n".join([f"🔸 *{escape_md(k)}:* {v}" for k, v in stats.items()])
    bot.reply_to(message, f"📱 *Pokédex Data: {escape_md(parts[1].capitalize())}*\n🧬 *Type:* {escape_md(' | '.join(types_list))}\n\n📊 *Base Stats:*\n{stats_str}", parse_mode="MarkdownV2")

@bot.message_handler(commands=["mypokemon", "mypokemons"])
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

@bot.message_handler(commands=["inspect"])
def cmd_inspect(message):
    user = db.get_user(message.from_user.id)
    if not user: return bot.reply_to(message, escape_md("⚠️ Please /start the bot first."))
    parts = message.text.split(maxsplit=1)
    if len(parts) < 2: return bot.reply_to(message, escape_md("📝 Usage: /inspect <pokemon_name>"))
    
    name = parts[1].strip().lower()
    names = [n.lower() for n in db.list_user_pokemon_names(message.from_user.id)]
    if name not in names: return bot.reply_to(message, escape_md("❌ You don't own this Pokémon."))
        
    poke_id = get_pokemon_id_sync(name)
    if not poke_id:
        return bot.reply_to(message, escape_md("❌ Error finding Pokémon ID from API."))

    # Task Progress for Inspecting
    tasks.add_progress(message.from_user.id, "inspect")

    img_url = official_shiny_artwork_url(poke_id) 
    bot.send_photo(message.chat.id, img_url, caption=f"✨ *{escape_md(name.capitalize())}* \\(Shiny\\)", parse_mode="MarkdownV2")

@bot.message_handler(commands=["release"])
def cmd_release(message):
    if not db.get_user(message.from_user.id): return bot.reply_to(message, escape_md("⚠️ Please /start the bot first."))
    parts = message.text.split(maxsplit=1)
    if len(parts) < 2: return bot.reply_to(message, escape_md("📝 Usage: /release <pokemon_name>"))
    poke_name = parts[1].strip().capitalize()
    if db.delete_pokemon(message.from_user.id, poke_name): bot.reply_to(message, escape_md(f"👋 You released {poke_name} back into the wild."))
    else: bot.reply_to(message, escape_md(f"❌ You don't have a {poke_name} to release."))

@bot.message_handler(commands=["pvp"])
def cmd_pvp(message):
    pvp.handle_pvp_command(bot, message)

@bot.message_handler(commands=["getid"])
def cmd_getid(message):
    bot.reply_to(message, escape_md(f"🆔 Chat ID: {message.chat.id}\n📁 Chat Type: {message.chat.type}"))


# ================== NEW DYNAMIC LEADERBOARD ==================
def send_leaderboard(chat_id, user_id, message_id=None):
    top_trainers = db.get_top_trainers(5)
    text = "🏆 *Top Trainers Leaderboard:*\n\n"
    
    for i, (uid, count) in enumerate(top_trainers):
        try:
            user_obj = bot.get_chat(uid)
            name = user_obj.first_name if user_obj.first_name else "Trainer"
        except:
            name = "Trainer"
            
        text += f"{i+1}\\. [{escape_md(name)}](tg://user?id={uid}) — {count} Pokémon\n"
        
    rank = db.get_user_rank(user_id)
    text += f"\nYour Rank — *{rank}*"
    
    kb = types.InlineKeyboardMarkup()
    kb.add(types.InlineKeyboardButton("REFRESH 🌀", callback_data=f"refresh_flex_{user_id}"))
    
    if message_id:
        try: bot.edit_message_text(text, chat_id, message_id, reply_markup=kb, parse_mode="MarkdownV2")
        except: pass
    else:
        bot.send_message(chat_id, text, reply_markup=kb, parse_mode="MarkdownV2")

@bot.message_handler(commands=["flex", "top", "leaderboard"])
def cmd_flex(message):
    db.add_user_if_new(message.from_user.id)
    send_leaderboard(message.chat.id, message.from_user.id)


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

# --- REPLY-BASED ADMIN COMMANDS ---
@bot.message_handler(commands=["take"])
def cmd_take(message):
    if not is_owner(message): return
    if not message.reply_to_message:
        return bot.reply_to(message, "⚠️ *Please reply to a user's message to take their Pokémon\\!*", parse_mode="MarkdownV2")
        
    args = message.text.split(maxsplit=1)
    if len(args) < 2:
        return bot.reply_to(message, "⚠️ *Format:* `/take <pokemon_name>`", parse_mode="MarkdownV2")
        
    target_id = message.reply_to_message.from_user.id
    target_name = message.reply_to_message.from_user.first_name
    pokemon_name = args[1].strip().title()
    
    if db.delete_pokemon(target_id, pokemon_name):
        bot.reply_to(message, f"🗑️ Successfully took *{escape_md(pokemon_name)}* from [{escape_md(target_name)}](tg://user?id={target_id})\\!", parse_mode="MarkdownV2")
    else:
        bot.reply_to(message, f"❌ [{escape_md(target_name)}](tg://user?id={target_id}) doesn't own a *{escape_md(pokemon_name)}*\\.", parse_mode="MarkdownV2")

@bot.message_handler(commands=["give"])
def cmd_give(message):
    if not is_owner(message): return
    if not message.reply_to_message:
        return bot.reply_to(message, "⚠️ *Please reply to a user's message to give them a Pokémon\\!*", parse_mode="MarkdownV2")
        
    args = message.text.split(maxsplit=1)
    if len(args) < 2:
        return bot.reply_to(message, "⚠️ *Format:* `/give <pokemon_name>`", parse_mode="MarkdownV2")
        
    target_id = message.reply_to_message.from_user.id
    target_name = message.reply_to_message.from_user.first_name
    pokemon_name = args[1].strip().title()
    
    db.add_caught_pokemon(target_id, pokemon_name, "Gift")
    bot.reply_to(message, f"🎁 Successfully gave *{escape_md(pokemon_name)}* to [{escape_md(target_name)}](tg://user?id={target_id})\\!", parse_mode="MarkdownV2")

@bot.message_handler(commands=["reset"])
def cmd_reset(message):
    if not is_owner(message): return
    if not message.reply_to_message:
        return bot.reply_to(message, "⚠️ *Please reply to a user's message to reset their tries\\!*", parse_mode="MarkdownV2")
        
    target_id = message.reply_to_message.from_user.id
    target_name = message.reply_to_message.from_user.first_name
    
    db.reset_user(target_id)
    bot.reply_to(message, f"🔄 Successfully reset scouts for [{escape_md(target_name)}](tg://user?id={target_id})\\!", parse_mode="MarkdownV2")

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

@bot.message_handler(commands=["debug"])
def cmd_debug(message):
    if not is_owner(message): return
    try:
        u_c, p_c, g_c = db.get_debug_stats()
        bot.reply_to(message, f"🛠 *Bot Debug Info*\n━━━━━━━━━━━━\n👥 *Trainers:* {u_c}\n🏆 *Pokémon:* {p_c}\n🎯 *Active Hunts:* {len(active_hunts)}\n⚔️ *Active PvP:* {len(pvp.pvp_battles)}\n🏢 *Groups:* {g_c}", parse_mode="MarkdownV2")
    except Exception as e: bot.reply_to(message, escape_md(f"Error: {str(e)}"))

@bot.message_handler(commands=["clearhunts"])
def cmd_clearhunts(message):
    if not is_owner(message): return
    for hunt in active_hunts.values():
        if "timer" in hunt: hunt["timer"].cancel()
    active_hunts.clear()
    pvp.pvp_battles.clear()
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
        # Route PvP callbacks to the dedicated PvP file
        if call.data.startswith("pvp_"):
            return pvp.handle_pvp_callback(bot, call)
            
        # Route to Flex Refresh
        if call.data.startswith("refresh_flex_"):
            owner_id = int(call.data.split("_")[2])
            if call.from_user.id != owner_id:
                return bot.answer_callback_query(call.id, "❌ You cannot refresh someone else's flex menu!", show_alert=True)
            bot.answer_callback_query(call.id, "🔄 Refreshing Leaderboard...")
            return send_leaderboard(call.message.chat.id, owner_id, call.message.message_id)

        # Route to Daily Tasks
        if call.data.startswith("task"):
            return tasks.handle_task_callback(bot, call)

        if call.data.startswith("travel_"):
            parts = call.data.split("_", 2)
            uid, region = int(parts[1]), parts[2]
            if call.from_user.id != uid: return bot.answer_callback_query(call.id, "Not your menu.")
            db.update_user_region(uid, region)
            
            # Task Hook
            tasks.add_progress(uid, "travel")
            
            bot.edit_message_text(f"✈️ Travelled to *{escape_md(region)}*\\.", call.message.chat.id, call.message.message_id, parse_mode="MarkdownV2")

        elif call.data.startswith("catch_"):
            parts = call.data.split("_", 3)
            uid, pid, name = int(parts[1]), int(parts[2]), parts[3]
            if call.from_user.id != uid: return bot.answer_callback_query(call.id, "Hands off! This scout is not yours.")
            if call.message.message_id not in active_hunts: return bot.answer_callback_query(call.id, "This scout has expired.")
            
            active_hunts[call.message.message_id]["timer"].cancel()
            active_hunts.pop(call.message.message_id, None)
            threading.Thread(target=process_catch, args=(call, uid, pid, name)).start()

        elif call.data.startswith("run_"):
            parts = call.data.split("_", 2)
            uid, name = int(parts[1]), parts[2]
            if call.from_user.id != uid: return bot.answer_callback_query(call.id, "This scout is not yours.")
            if call.message.message_id not in active_hunts: return bot.answer_callback_query(call.id, "This scout has expired.")
            
            active_hunts[call.message.message_id]["timer"].cancel()
            active_hunts.pop(call.message.message_id, None)
            bot.edit_message_caption(caption=f"🏃‍♂️ You got away safely from *{escape_md(name.capitalize())}*\\.", chat_id=call.message.chat.id, message_id=call.message.message_id, parse_mode="MarkdownV2")

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

# ================== RUN ==================
if __name__ == "__main__":
    db.init_db()
    logger.info("Bot is starting...")
    bot.delete_webhook()
    bot.infinity_polling(skip_pending=True)
