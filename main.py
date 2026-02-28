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

# Import from our modular files
from config import BOT_TOKEN, OWNER_ID, LOG_GROUP_ID, FLEE_TIMEOUT, REGIONS, DB_FILE, logger
import database as db
from api_utils import (
    escape_markdown_v2, 
    fetch_random_pokemon_id_and_name, 
    official_shiny_artwork_url, 
    default_pokemon_image, 
    get_species_catch_rate
)

bot = telebot.TeleBot(BOT_TOKEN, parse_mode="MarkdownV2")
active_hunts = {}  # Format: {message_id: {"user_id": user_id, "start_time": time.time(), "timer": Timer, "name": pokemon_name}}
last_api_call = 0  

# ================== GAME LOGIC ==================
def auto_flee(message_id, chat_id, pokemon_name):
    if message_id not in active_hunts:
        return
    try:
        bot.edit_message_caption(
            caption=escape_markdown_v2(f"The shiny {pokemon_name.capitalize()} fled!"),
            chat_id=chat_id,
            message_id=message_id,
            reply_markup=None,
            parse_mode="MarkdownV2"
        )
    except Exception as e:
        logger.error(f"Error in auto-flee for message {message_id}: {e}")
    active_hunts.pop(message_id, None)

async def start_scout(chat_id, user_id, reply_to_id=None):
    global last_api_call
    user = db.get_user(user_id)
    if not user:
        bot.send_message(chat_id, escape_markdown_v2("Please /start the bot first."), reply_to_message_id=reply_to_id, parse_mode="MarkdownV2")
        return
        
    tries_left, region = db.update_user_tries(user_id)
    if tries_left is None:
        bot.send_message(chat_id, escape_markdown_v2("Error checking your profile. Try again."), reply_to_message_id=reply_to_id, parse_mode="MarkdownV2")
        return
    if tries_left <= 0:
        bot.send_message(chat_id, escape_markdown_v2("You have no scouts left today. Come back tomorrow."), reply_to_message_id=reply_to_id, parse_mode="MarkdownV2")
        return
    if any(hunt["user_id"] == user_id for hunt in active_hunts.values()):
        bot.send_message(chat_id, escape_markdown_v2("You already have an active scout. Complete it first."), reply_to_message_id=reply_to_id, parse_mode="MarkdownV2")
        return

    poke_id, name, base_id = await fetch_random_pokemon_id_and_name()
    if not poke_id:
        bot.send_message(chat_id, escape_markdown_v2("Failed to fetch Pokémon. Try again."), reply_to_message_id=reply_to_id, parse_mode="MarkdownV2")
        return

    img_url = official_shiny_artwork_url(base_id)
    caption = escape_markdown_v2(f"A wild shiny {name} appeared in {region}!\nWhat will you do?")
    kb = types.InlineKeyboardMarkup()
    kb.add(
        types.InlineKeyboardButton("Catch", callback_data=f"catch_{user_id}_{poke_id}_{name[:16]}"),
        types.InlineKeyboardButton("Run", callback_data=f"run_{user_id}_{name[:16]}")
    )

    current_time = time.time()
    if current_time - last_api_call < 0.2:
        await asyncio.sleep(0.2)
    last_api_call = current_time

    try:
        sent = bot.send_photo(
            chat_id, img_url, caption=caption, reply_to_message_id=reply_to_id,
            reply_markup=kb, parse_mode="MarkdownV2"
        )
        timer = threading.Timer(FLEE_TIMEOUT, auto_flee, args=(sent.message_id, chat_id, name))
        timer.start()
        active_hunts[sent.message_id] = {
            "user_id": user_id, "start_time": time.time(),
            "timer": timer, "name": name
        }
    except Exception as e:
        logger.error(f"Failed to send scout photo for {user_id}: {e}")
        try:
            sent = bot.send_photo(
                chat_id, default_pokemon_image(), caption=escape_markdown_v2(f"{caption}\n(Note: Image unavailable)"),
                reply_to_message_id=reply_to_id, reply_markup=kb, parse_mode="MarkdownV2"
            )
            timer = threading.Timer(FLEE_TIMEOUT, auto_flee, args=(sent.message_id, chat_id, name))
            timer.start()
            active_hunts[sent.message_id] = {"user_id": user_id, "start_time": time.time(), "timer": timer, "name": name}
        except Exception:
            bot.send_message(chat_id, escape_markdown_v2("Error displaying Pokémon. Try again."), reply_to_message_id=reply_to_id, parse_mode="MarkdownV2")

# ================== COMMANDS ==================
@bot.message_handler(commands=["start"])
def cmd_start(message):
    is_new = db.add_user_if_new(message.from_user.id)
    if message.chat.type in ["group", "supergroup"]:
        db.add_group(message.chat.id)
        
    kb = types.InlineKeyboardMarkup()
    kb.add(
        types.InlineKeyboardButton("Main Group ✨", url="https://t.me/sexagamechat"),
        types.InlineKeyboardButton("Owner ✨", url="https://t.me/Dark_monarchx")
    )
    bot.reply_to(message, escape_markdown_v2("Welcome! Use /scout to search for shiny Pokémon.\nUse /travel to change region."), reply_markup=kb, parse_mode="MarkdownV2")
    
    if is_new and LOG_GROUP_ID is not None:
        first = message.from_user.first_name or ""
        username = f"@{message.from_user.username}" if message.from_user.username else ""
        try:
            bot.send_message(LOG_GROUP_ID, escape_markdown_v2(f"New Trainer: {first} {username} (ID: {message.from_user.id}) started the bot in chat {message.chat.id}."), parse_mode="MarkdownV2")
        except Exception as e:
            logger.error(f"Failed to send start notification to log group: {str(e)}")

@bot.message_handler(commands=["getid"])
def cmd_getid(message):
    bot.reply_to(message, escape_markdown_v2(f"Chat ID: {message.chat.id}\nChat Type: {message.chat.type}"), parse_mode="MarkdownV2")

@bot.message_handler(commands=["profile"])
def cmd_profile(message):
    user = db.get_user(message.from_user.id)
    if not user:
        bot.reply_to(message, escape_markdown_v2("Please /start the bot first."), parse_mode="MarkdownV2")
        return
    tries_left, region = db.update_user_tries(message.from_user.id)
    count = len(db.list_user_pokemon_names(message.from_user.id))
    bot.reply_to(message, escape_markdown_v2(f"𝐓𝐫𝐚𝐢𝐧𝐞𝐫 𝐏𝐫𝐨𝐟𝐢𝐥𝐞\n➥𝐑𝐞𝐠𝐢𝐨𝐧: {region}\n➥𝐓𝐨𝐭𝐚𝐥 𝐏ó𝐤𝐞𝐦𝐨𝐧𝐬: {count}\n➥𝐃𝐚𝐢𝐥𝐲 𝐬𝐜𝐨𝐮𝐭 𝐋𝐞𝐟𝐭: {tries_left}"), parse_mode="MarkdownV2")

@bot.message_handler(commands=["travel"])
def cmd_travel(message):
    if not db.get_user(message.from_user.id):
        bot.reply_to(message, escape_markdown_v2("Please /start the bot first."), parse_mode="MarkdownV2")
        return
    kb = types.InlineKeyboardMarkup()
    for r in REGIONS:
        kb.add(types.InlineKeyboardButton(r, callback_data=f"travel_{message.from_user.id}_{r}"))
    bot.reply_to(message, escape_markdown_v2("Choose a region:"), reply_markup=kb, parse_mode="MarkdownV2")

@bot.message_handler(commands=["scout"])
def cmd_scout(message):
    asyncio.run(start_scout(message.chat.id, message.from_user.id, message.message_id))

@bot.message_handler(commands=["mypokemon"])
def cmd_mypokemon(message):
    user_id = message.from_user.id
    if not db.get_user(user_id):
        bot.reply_to(message, escape_markdown_v2("Please /start the bot first."), parse_mode="MarkdownV2")
        return
    names = db.list_user_pokemon_names(user_id)
    if not names:
        bot.reply_to(message, escape_markdown_v2("You don't have any Pokémon yet."), parse_mode="MarkdownV2")
        return
    
    page_size = 20
    pages = [names[i:i + page_size] for i in range(0, len(names), page_size)]
    
    def get_page_text(page_idx):
        return escape_markdown_v2(f"𝕐𝕠𝕦𝕣 ℙ𝕠𝕜é𝕞𝕠𝕟 (Page {page_idx + 1}/{len(pages)}):\n" + "\n".join(f"➥ {n}" for n in pages[page_idx]))
    
    def make_kb(current_page, uid, num_pages):
        kb = types.InlineKeyboardMarkup(row_width=4)
        prev_page = max(0, current_page - 1)
        next_page = min(num_pages - 1, current_page + 1)
        kb.add(
            types.InlineKeyboardButton("<<", callback_data=f"mypoke_{uid}_0"),
            types.InlineKeyboardButton("<", callback_data=f"mypoke_{uid}_{prev_page}"),
            types.InlineKeyboardButton(">", callback_data=f"mypoke_{uid}_{next_page}"),
            types.InlineKeyboardButton(">>", callback_data=f"mypoke_{uid}_{num_pages - 1}")
        )
        return kb
        
    kb = make_kb(0, user_id, len(pages)) if len(pages) > 1 else None
    bot.reply_to(message, get_page_text(0), reply_markup=kb, parse_mode="MarkdownV2")

@bot.message_handler(commands=["flex", "top"])
def cmd_flex(message):
    rows = db.get_top_trainers(5)
    if not rows:
        bot.reply_to(message, escape_markdown_v2("No trainers yet."), parse_mode="MarkdownV2")
        return
    lines = [f"{rank}\\. User {uid} — {cnt} Pokémon" for rank, (uid, cnt) in enumerate(rows, start=1)]
    bot.reply_to(message, escape_markdown_v2("*Top Trainers:*\n" + "\n".join(lines)), parse_mode="MarkdownV2")

# --- ADMIN COMMANDS ---
@bot.message_handler(commands=["plist", "take", "give", "bcast", "gcast", "gcs", "allusers", "leave", "reset", "backup", "restore", "debug", "clearhunts"])
def admin_commands(message):
    if message.from_user.id != OWNER_ID:
        bot.reply_to(message, escape_markdown_v2("𝚃𝚑𝚒𝚜 𝚌𝚘𝚖𝚖𝚊𝚗𝚍 𝚒𝚜 𝚏𝚘𝚛 𝚘𝚠𝚗𝚎𝚛 -𝚜𝚊𝚖𝚊 𝚘𝚗𝚕𝚢."), parse_mode="MarkdownV2")
        return
        
    cmd = message.text.split()[0].lower()
    
    if cmd == "/debug":
        conn = sqlite3.connect(DB_FILE)
        cur = conn.cursor()
        user_count = cur.execute("SELECT COUNT(*) FROM users").fetchone()[0]
        pokemon_count = cur.execute("SELECT COUNT(*) FROM pokemons").fetchone()[0]
        group_count = cur.execute("SELECT COUNT(*) FROM groups").fetchone()[0]
        conn.close()
        
        status = escape_markdown_v2(
            f"*Bot Debug Info*\nRegistered trainers: {user_count}\nTotal Pokémon caught: {pokemon_count}\n"
            f"Active hunts: {len(active_hunts)}\nGroups: {group_count}\n"
        )
        bot.reply_to(message, status, parse_mode="MarkdownV2")
        
    elif cmd == "/clearhunts":
        for hunt in active_hunts.values():
            if "timer" in hunt:
                hunt["timer"].cancel()
        active_hunts.clear()
        bot.reply_to(message, escape_markdown_v2("All active hunts cleared."), parse_mode="MarkdownV2")
        
    elif cmd == "/backup":
        if os.path.exists(DB_FILE):
            with open(DB_FILE, "rb") as f:
                bot.send_document(OWNER_ID, f, caption=escape_markdown_v2("Backup database"), parse_mode="MarkdownV2")
        else:
            bot.reply_to(message, escape_markdown_v2("No database file found."), parse_mode="MarkdownV2")

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
        if call.data.startswith("travel_"):
            _, uid_str, region = call.data.split("_", 2)
            if call.from_user.id != int(uid_str):
                bot.answer_callback_query(call.id, escape_markdown_v2("This selection is not for you."), parse_mode="MarkdownV2")
                return
                
            conn = sqlite3.connect(DB_FILE)
            cur = conn.cursor()
            cur.execute("UPDATE users SET region=? WHERE user_id=?", (region, int(uid_str)))
            conn.commit()
            conn.close()
            
            bot.edit_message_text(escape_markdown_v2(f"You travelled to {region}."), call.message.chat.id, call.message.message_id, parse_mode="MarkdownV2")

        elif call.data.startswith("catch_"):
            _, uid_str, pid_str, name = call.data.split("_", 3)
            uid, pid = int(uid_str), int(pid_str)
            
            if call.from_user.id != uid:
                bot.answer_callback_query(call.id, escape_markdown_v2("This scout is not yours."), parse_mode="MarkdownV2")
                return
            if call.message.message_id not in active_hunts or active_hunts[call.message.message_id]["user_id"] != uid:
                bot.answer_callback_query(call.id, escape_markdown_v2("This scout has expired."), parse_mode="MarkdownV2")
                return
                
            active_hunts[call.message.message_id]["timer"].cancel()
            bot.edit_message_caption(caption=escape_markdown_v2("Throwing Pokéball..."), chat_id=call.message.chat.id, message_id=call.message.message_id, parse_mode="MarkdownV2")
            
            time.sleep(1.5)
            catch_rate = asyncio.run(get_species_catch_rate(pid))
            success = random.random() < max(0.05, min(0.95, catch_rate / 255.0))
            
            if success:
                db.add_caught_pokemon(uid, name.capitalize(), db.get_user(uid)[2])
                bot.edit_message_caption(caption=escape_markdown_v2(f"You caught shiny {name.capitalize()}!"), chat_id=call.message.chat.id, message_id=call.message.message_id, parse_mode="MarkdownV2")
            else:
                bot.edit_message_caption(caption=escape_markdown_v2(f"Oh no! Shiny {name.capitalize()} escaped!"), chat_id=call.message.chat.id, message_id=call.message.message_id, parse_mode="MarkdownV2")
                
            active_hunts.pop(call.message.message_id, None)

        elif call.data.startswith("run_"):
            _, uid_str, name = call.data.split("_", 2)
            uid = int(uid_str)
            
            if call.from_user.id != uid:
                bot.answer_callback_query(call.id, escape_markdown_v2("This scout is not yours."), parse_mode="MarkdownV2")
                return
            if call.message.message_id not in active_hunts:
                return
                
            active_hunts[call.message.message_id]["timer"].cancel()
            bot.edit_message_caption(caption=escape_markdown_v2(f"You ran away from shiny {name.capitalize()}."), chat_id=call.message.chat.id, message_id=call.message.message_id, parse_mode="MarkdownV2")
            active_hunts.pop(call.message.message_id, None)
            
    except Exception as e:
        logger.error(f"Callback handler error: {e}")

# ================== RUN ==================
if __name__ == "__main__":
    db.init_db()
    logger.info("Bot is starting...")
    bot.delete_webhook()
    bot.infinity_polling(skip_pending=True)
