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
import json 
import io 
from collections import Counter

from config import BOT_TOKEN, OWNER_ID, LOG_GROUP_ID, FLEE_TIMEOUT, REGIONS, logger
import database as db
import pvp 
import tasks 
import trade 
from api_utils import (
    escape_md, 
    fetch_random_pokemon_id_and_name_sync, 
    official_shiny_artwork_url, 
    get_species_catch_rate_sync,
    get_pokemon_stats_sync,
    get_pokemon_id_sync,
    REGION_DEX,
    pokemon_name_to_id_cache,
    LEGENDARY_NAMES
)

bot = telebot.TeleBot(BOT_TOKEN, parse_mode="MarkdownV2")
active_hunts = {}  

TYPE_EMOJIS = {
    'Normal': '🔘', 'Fire': '🔥', 'Water': '💧', 'Electric': '⚡', 'Grass': '🌿', 
    'Ice': '🧊', 'Fighting': '🥊', 'Poison': '☣️', 'Ground': '⛰️', 'Flying': '🪽', 
    'Psychic': '🔮', 'Bug': '🐛', 'Rock': '🪨', 'Ghost': '👻', 'Dragon': '🐉', 
    'Dark': '🌑', 'Steel': '🔩', 'Fairy': '🧚‍♀️'
}

# --- TEXT HELPERS ---
def to_small_caps(text):
    """Converts regular text into the premium small-caps font."""
    small_caps_map = {
        'a': 'ᴀ', 'b': 'ʙ', 'c': 'ᴄ', 'd': 'ᴅ', 'e': 'ᴇ', 'f': 'ғ', 'g': 'ɢ',
        'h': 'ʜ', 'i': 'ɪ', 'j': 'ᴊ', 'k': 'ᴋ', 'l': 'ʟ', 'm': 'ᴍ', 'n': 'ɴ',
        'o': 'ᴏ', 'p': 'ᴘ', 'q': 'ǫ', 'r': 'ʀ', 's': 's', 't': 'ᴛ', 'u': 'ᴜ',
        'v': 'ᴠ', 'w': 'ᴡ', 'x': 'x', 'y': 'ʏ', 'z': 'ᴢ'
    }
    return "".join(char if char.isupper() else small_caps_map.get(char.lower(), char) for char in text)

def safe_send(chat_id, text, reply_to_id=None, reply_markup=None):
    """Safely sends messages and automatically handles Telegram Rate Limits (429)"""
    try:
        return bot.send_message(chat_id, text, reply_to_message_id=reply_to_id, reply_markup=reply_markup, parse_mode="MarkdownV2")
    except Exception as e:
        if "429" in str(e) or "Too Many Requests" in str(e):
            time.sleep(2.5) 
            try: return bot.send_message(chat_id, text, reply_to_message_id=reply_to_id, reply_markup=reply_markup, parse_mode="MarkdownV2")
            except: pass
        return None

# ================== GAME LOGIC ==================
def auto_flee(message_id, chat_id, pokemon_name):
    if message_id not in active_hunts: return
    try:
        # Added escape_md to prevent parsing errors on hyphens (e.g. Ho-Oh)
        fled_cap = f"💨 Tʜᴇ Wɪʟᴅ ✨ {escape_md(to_small_caps(pokemon_name.title()))} Fʟᴇᴅ\\!"
        bot.edit_message_caption(
            caption=fled_cap,
            chat_id=chat_id, message_id=message_id, reply_markup=None, parse_mode="MarkdownV2"
        )
    except Exception as e:
        if "message is not modified" not in str(e).lower():
            logger.error(f"Error in auto-flee: {e}")
    active_hunts.pop(message_id, None)

def start_scout(chat_id, user_id, reply_to_id=None):
    if not db.get_user(user_id):
        return safe_send(chat_id, escape_md("⚠️ Please /start the bot first."), reply_to_id)
        
    if pvp.is_in_battle(user_id):
        return safe_send(chat_id, escape_md("⚔️ You cannot scout while engaged in a PvP battle!"), reply_to_id)
        
    tries_left, region = db.update_user_tries(user_id)
    if tries_left is None:
        return safe_send(chat_id, escape_md("⚠️ Error checking your profile."), reply_to_id)
    if tries_left <= 0:
        return safe_send(chat_id, escape_md("💤 You have no scouts left today. Rest and come back tomorrow!"), reply_to_id)
        
    # --- OVERRIDE PREVIOUS SCOUT ---
    to_cancel = []
    for msg_id, hunt in list(active_hunts.items()):
        if hunt["user_id"] == user_id:
            to_cancel.append((msg_id, hunt))
            
    for msg_id, hunt in to_cancel:
        hunt["timer"].cancel()
        active_hunts.pop(msg_id, None)
        # We no longer edit the message here! This saves API calls and speeds up the bot.
        # The button will just say "Fled" when clicked via the callback handler below.

    poke_id, name, base_id = fetch_random_pokemon_id_and_name_sync(region)
    if not poke_id:
        return safe_send(chat_id, escape_md("❌ Failed to find a Pokémon. Try again."), reply_to_id)

    img_url = official_shiny_artwork_url(base_id)
    
    # Premium Small Caps UI with Markdown Escaping
    p_name = escape_md(to_small_caps(name.title()))
    p_reg = escape_md(to_small_caps(region))
    caption = f"A Wɪʟᴅ ✨ {p_name} Aᴘᴘᴇᴀʀᴇᴅ ɪɴ {p_reg}\\!\n\n🎒 Wʜᴀᴛ Wɪʟʟ Yᴏᴜ Dᴏ, Tʀᴀɪɴᴇʀ?"
    
    kb = types.InlineKeyboardMarkup()
    kb.add(
        types.InlineKeyboardButton("🎯 Cᴀᴛᴄʜ", callback_data=f"catch_{user_id}_{poke_id}_{name[:16]}"),
        types.InlineKeyboardButton("🏃 Rᴜɴ", callback_data=f"run_{user_id}_{name[:16]}")
    )

    try:
        sent = bot.send_photo(chat_id, img_url, caption=caption, reply_to_message_id=reply_to_id, reply_markup=kb, parse_mode="MarkdownV2")
        timer = threading.Timer(FLEE_TIMEOUT, auto_flee, args=(sent.message_id, chat_id, name))
        timer.start()
        active_hunts[sent.message_id] = {"user_id": user_id, "chat_id": chat_id, "start_time": time.time(), "timer": timer, "name": name}
    except Exception as e: 
        if "429" in str(e):
            time.sleep(2) 
            try:
                sent = bot.send_photo(chat_id, img_url, caption=caption, reply_to_message_id=reply_to_id, reply_markup=kb, parse_mode="MarkdownV2")
                timer = threading.Timer(FLEE_TIMEOUT, auto_flee, args=(sent.message_id, chat_id, name))
                timer.start()
                active_hunts[sent.message_id] = {"user_id": user_id, "chat_id": chat_id, "start_time": time.time(), "timer": timer, "name": name}
            except: pass
        else:
            logger.error(f"Failed to send scout photo: {e}")

def process_catch(call, uid, pid, name):
    chat_id = call.message.chat.id
    msg_id = call.message.message_id
    
    try:
        # --- COMPRESSED ANIMATION FOR MAXIMUM SPEED ---
        try:
            bot.edit_message_caption(caption="🔴 *Yᴏᴜ ᴛʜʀᴇᴡ ᴀ Pᴏᴋᴇ́ʙᴀʟʟ\\!*", chat_id=chat_id, message_id=msg_id, parse_mode="MarkdownV2")
        except Exception as e:
            if "429" in str(e): time.sleep(1)
            
        time.sleep(0.7) # Single, ultra-fast suspense delay
        
        # --- OUTCOME ---
        catch_rate = get_species_catch_rate_sync(pid)
        if random.random() < max(0.05, min(0.95, catch_rate / 255.0)):
            poke_name_capped = name.title()
            db.add_caught_pokemon(uid, poke_name_capped, db.get_user(uid)[2])
            
            # Wrapped tasks in a try/except so a task error NEVER breaks the catch animation again!
            try: 
                tasks.check_and_update_catch(uid, poke_name_capped)
            except Exception as e: 
                logger.error(f"Ignored task error during catch: {e}")
            
            if LOG_GROUP_ID:
                try: 
                    u_name = call.from_user.first_name
                    bot.send_message(LOG_GROUP_ID, f"🟢 *Catch Log:* [{escape_md(u_name)}](tg://user?id={uid}) caught a ✨ Shiny {escape_md(poke_name_capped)}\\!", parse_mode="MarkdownV2")
                except: pass
            
            cap = f"✨ *Gᴏᴛᴄʜᴀ\\!* Sʜɪɴʏ *{escape_md(to_small_caps(poke_name_capped))}* ᴡᴀs ᴄᴀᴜɢʜᴛ\\!\n\nUse /inspect `{escape_md(poke_name_capped)}` to view it\\."
            try: bot.edit_message_caption(caption=cap, chat_id=chat_id, message_id=msg_id, parse_mode="MarkdownV2")
            except Exception as e: pass
        else:
            cap = f"💨 *Oʜ ɴᴏ\\!* Tʜᴇ Wɪʟᴅ ✨ {escape_md(to_small_caps(name.title()))} ʙʀᴏᴋᴇ ғʀᴇᴇ ᴀɴᴅ ғʟᴇᴅ\\!"
            try: bot.edit_message_caption(caption=cap, chat_id=chat_id, message_id=msg_id, parse_mode="MarkdownV2")
            except Exception as e: pass
            
    except Exception as e:
        logger.error(f"Catch error: {e}")

# ================== POKEDEX HELPER ==================
def get_dex_text(name, page="info"):
    poke_id = get_pokemon_id_sync(name)
    if not poke_id: return None
    
    types_list, stats = get_pokemon_stats_sync(name)
    if not stats: return None
    
    if page == "info":
        catch_rate = get_species_catch_rate_sync(poke_id)
        if catch_rate <= 45: prob = "Very Low"
        elif catch_rate <= 90: prob = "Low"
        elif catch_rate <= 150: prob = "Medium"
        else: prob = "High"
        
        region_found = "Unknown"
        for r, (min_id, max_id) in REGION_DEX.items():
            if min_id <= poke_id <= max_id:
                region_found = r
                break
                
        types_str = " / ".join([f"{t} {TYPE_EMOJIS.get(t, '')}" for t in types_list])
        
        text = (
            f"📱 *Pokédex Data*\n"
            f"━━━━━━━━━━━━━━\n"
            f"🔢 *Pokédex No\\.:* {poke_id}\n"
            f"📛 *Name:* {escape_md(name.capitalize())}\n"
            f"🧬 *Types:* \\[{escape_md(types_str)}\\]\n"
            f"🎯 *Catch probability:* {prob}\n"
            f"🌍 *Regions found:* {escape_md(region_found)}"
        )
        return text
    else:
        stats_str = "\n".join([f"🔸 *{escape_md(k)}:* {v}" for k, v in stats.items()])
        total_stats = sum(stats.values())
        text = (
            f"📊 *Base Stats: {escape_md(name.capitalize())}*\n"
            f"━━━━━━━━━━━━━━\n"
            f"{stats_str}\n"
            f"━━━━━━━━━━━━━━\n"
            f"📈 *Total:* {total_stats}"
        )
        return text

# ================== USER COMMANDS ==================
@bot.message_handler(commands=["start"])
def cmd_start(message):
    is_new = db.add_user_if_new(message.from_user.id)
    if message.chat.type in ["group", "supergroup"]: db.add_group(message.chat.id)
    
    kb = types.InlineKeyboardMarkup(row_width=2)
    kb.row(
        types.InlineKeyboardButton("Oᴡɴᴇʀ ⚡", url="https://t.me/monarch_sama"),
        types.InlineKeyboardButton("Mᴀɪɴ Gʀᴏᴜᴘ ⚡", url="https://t.me/sexagamechat")
    )
    
    user_name = escape_md(message.from_user.first_name)
    text = (
        f"Hҽყ {user_name}\n\n"
        f"*Wᴇʟᴄσɱᴇ ᴛσ Sᴇxᴀ ✨*\n"
        f"*Tʜᴇ Sʜɪɴʏ Pᴏᴋᴇ́ᴍᴏɴ Aᴅᴠᴇɴᴛᴜʀᴇ*\n\n"
        f"━━━━━━━━━━━━━━━\n"
        f"*🔎 Hᴜɴᴛ • 🎯 Cᴀᴛᴄʜ • 💎 Fʟᴇx*\n"
        f"━━━━━━━━━━━━━━━\n"
        f"*🌍 Yᴏᴜʀ Jᴏᴜʀɴᴇʏ Bᴇɢɪɴs Nᴏᴡ*"
    )
    
    safe_send(message.chat.id, text, reply_to_id=message.message_id, reply_markup=kb)
    
    if is_new and LOG_GROUP_ID is not None:
        try: bot.send_message(LOG_GROUP_ID, escape_md(f"🔔 New Trainer: {message.from_user.first_name} (ID: {message.from_user.id}) started the bot."))
        except Exception: pass

@bot.message_handler(commands=["open"])
def cmd_open(message):
    if message.chat.type != "private":
        return safe_send(message.chat.id, escape_md("⚠️ The /open command only works in private messages (DM)."), reply_to_id=message.message_id)
    kb = types.ReplyKeyboardMarkup(resize_keyboard=True, row_width=1)
    kb.add(types.KeyboardButton("🔎 Scout"))
    bot.send_message(message.chat.id, escape_md("⌨️ Action menu opened! Use /close to hide it."), reply_markup=kb, parse_mode="MarkdownV2")

@bot.message_handler(commands=["close"])
def cmd_close(message):
    if message.chat.type != "private":
        return safe_send(message.chat.id, escape_md("⚠️ The /close command only works in private messages (DM)."), reply_to_id=message.message_id)
    remove_kb = types.ReplyKeyboardRemove()
    bot.send_message(message.chat.id, escape_md("⌨️ Action menu closed! Use /open to bring it back."), reply_markup=remove_kb, parse_mode="MarkdownV2")

@bot.message_handler(func=lambda message: message.text == "🔎 Scout" and message.chat.type == "private")
def text_scout(message):
    threading.Thread(target=start_scout, args=(message.chat.id, message.from_user.id, message.message_id)).start()

@bot.message_handler(commands=["task", "tasks"])
def cmd_task(message):
    db.add_user_if_new(message.from_user.id)
    tasks.render_tasks_ui(bot, message.chat.id, message.from_user.id)

# --- TEXT-BASED TRAINER CARD PROFILE ---
@bot.message_handler(commands=["profile", "trainer"])
def cmd_profile(message):
    user_id = message.from_user.id
    user = db.get_user(user_id)
    
    if not user: 
        return safe_send(message.chat.id, escape_md("⚠️ Please /start the bot first."), reply_to_id=message.message_id)
        
    tries_left, region = db.update_user_tries(user_id)
    names = db.list_user_pokemon_names(user_id)
    count = len(names)
    
    rarest_caught = "None"
    if names:
        rarest_list = [p for p in names if p in LEGENDARY_NAMES or "Mega" in p or "Primal" in p]
        rarest_caught = rarest_list[0] if rarest_list else names[-1]
            
    try: wins, losses = db.get_battle_stats(user_id)
    except Exception: wins, losses = 0, 0 
        
    total_battles = wins + losses
    user_name = escape_md(message.from_user.first_name)
    rarest_md = escape_md(rarest_caught)
    region_md = escape_md(region)
    
    text = (
        "✦─────────────────✦\n"
        "🪪  𝗧𝗥𝗔𝗜𝗡𝗘𝗥 𝗖𝗔𝗥𝗗  🪪\n"
        "✦─────────────────✦\n\n"
        f"👤  {user_name}\n"
        f"🆔  `{user_id}`\n"
        f"🌍  {region_md}\n\n"
        "✦───────────────✦\n"
        "𝗖𝗼𝗹𝗹𝗲𝗰𝘁𝗶𝗼𝗻\n"
        f"🎒  {count} 𝗣𝗼𝗸é𝗺𝗼𝗻\n"
        f"⭐  {rarest_md}  \\(𝗿𝗮𝗿𝗲𝘀𝘁 𝗰𝗮𝘂𝗴𝗵𝘁\\)\n\n"
        "✦───────────────✦\n"
        "𝗦𝗰𝗼𝘂𝘁𝘀\n"
        f"🔋  {tries_left} / 2500 𝗿𝗲𝗺𝗮𝗶𝗻𝗶𝗻𝗴\n\n"
        "✦─────────────────✦\n"
        "𝗕𝗔𝗧𝗧𝗟𝗘 𝗥𝗘𝗖𝗢𝗥𝗗\n"
        "✦─────────────────✦\n\n"
        f"🏆  𝗪𝗶𝗻𝘀          {wins}\n"
        f"❌  𝗟𝗼𝘀𝘀𝗲𝘀        {losses}\n"
        f"📊  𝗧𝗼𝘁𝗮𝗹 𝗕𝗮𝘁𝘁𝗹𝗲𝘀 {total_battles}\n\n"
        "✦─────────────────✦\n"
        f"© 𝗣𝗼𝗸é𝗧𝗿𝗮𝗶𝗻𝗲𝗿 {user_name}"
    )
    
    safe_send(message.chat.id, text, reply_to_id=message.message_id)

@bot.message_handler(commands=["travel"])
def cmd_travel(message):
    if not db.get_user(message.from_user.id): return safe_send(message.chat.id, escape_md("⚠️ Please /start the bot first."), reply_to_id=message.message_id)
    kb = types.InlineKeyboardMarkup()
    for r in REGIONS: kb.add(types.InlineKeyboardButton(f"✈️ {r}", callback_data=f"travel_{message.from_user.id}_{r}"))
    safe_send(message.chat.id, "*Choose a region to travel to:*", reply_to_id=message.message_id, reply_markup=kb)

@bot.message_handler(commands=["scout"])
def cmd_scout(message):
    threading.Thread(target=start_scout, args=(message.chat.id, message.from_user.id, message.message_id)).start()

@bot.message_handler(commands=["pokedex", "dex"])
def cmd_pokedex(message):
    parts = message.text.split(maxsplit=1)
    if len(parts) < 2: return safe_send(message.chat.id, escape_md("📝 Usage: /pokedex <pokemon_name>"), reply_to_id=message.message_id)
    
    name = parts[1].strip().lower()
    poke_id = get_pokemon_id_sync(name)
    if not poke_id: return safe_send(message.chat.id, f"❌ Could not find data for *{escape_md(parts[1])}*\\.", reply_to_id=message.message_id)
    
    text = get_dex_text(name, "info")
    if not text: return safe_send(message.chat.id, f"❌ Error formatting data for *{escape_md(parts[1])}*\\.", reply_to_id=message.message_id)
    
    img_url = official_shiny_artwork_url(poke_id)
    
    kb = types.InlineKeyboardMarkup(row_width=2)
    kb.add(
        types.InlineKeyboardButton("✅ ℹ️ Info", callback_data="ignore"),
        types.InlineKeyboardButton("📊 Stats", callback_data=f"dex_stats_{name}")
    )
    try: bot.send_photo(message.chat.id, img_url, caption=text, reply_markup=kb, parse_mode="MarkdownV2")
    except Exception as e: logger.error(f"Failed to send Pokedex photo: {e}")

@bot.message_handler(commands=["mypokemon", "mypokemons"])
def cmd_mypokemon(message):
    user_id = message.from_user.id
    if not db.get_user(user_id): return safe_send(message.chat.id, escape_md("⚠️ Please /start the bot first."), reply_to_id=message.message_id)
    names = db.list_user_pokemon_names(user_id)
    if not names: return safe_send(message.chat.id, escape_md("🎒 You don't have any Pokémon yet."), reply_to_id=message.message_id)
    pages = [names[i:i + 20] for i in range(0, len(names), 20)]
    def make_kb(uid, num_pages):
        kb = types.InlineKeyboardMarkup(row_width=4)
        kb.add(types.InlineKeyboardButton("<<", callback_data=f"mypoke_{uid}_0"), types.InlineKeyboardButton(">>", callback_data=f"mypoke_{uid}_{num_pages - 1}"))
        return kb
    
    text = f"🎒 *Your Pokémon* \\(Page 1/{len(pages)}\\):\n\n" + "\n".join(f"➥ {escape_md(n)}" for n in pages[0])
    safe_send(message.chat.id, text, reply_to_id=message.message_id, reply_markup=make_kb(user_id, len(pages)) if len(pages) > 1 else None)

@bot.message_handler(commands=["inspect"])
def cmd_inspect(message):
    user = db.get_user(message.from_user.id)
    if not user: return safe_send(message.chat.id, escape_md("⚠️ Please /start the bot first."), reply_to_id=message.message_id)
    parts = message.text.split(maxsplit=1)
    if len(parts) < 2: return safe_send(message.chat.id, escape_md("📝 Usage: /inspect <pokemon_name>"), reply_to_id=message.message_id)
    
    name = parts[1].strip().lower()
    names = [n.lower() for n in db.list_user_pokemon_names(message.from_user.id)]
    if name not in names: return safe_send(message.chat.id, escape_md("❌ You don't own this Pokémon."), reply_to_id=message.message_id)
        
    poke_id = get_pokemon_id_sync(name)
    if not poke_id:
        return safe_send(message.chat.id, escape_md("❌ Error finding Pokémon ID from API."), reply_to_id=message.message_id)

    img_url = official_shiny_artwork_url(poke_id) 
    try: bot.send_photo(message.chat.id, img_url, caption=f"✨ *{escape_md(name.capitalize())}* \\(Shiny\\)", parse_mode="MarkdownV2")
    except Exception as e: logger.error(f"Failed to send inspect photo: {e}")

@bot.message_handler(commands=["release"])
def cmd_release(message):
    if not db.get_user(message.from_user.id): return safe_send(message.chat.id, escape_md("⚠️ Please /start the bot first."), reply_to_id=message.message_id)
    parts = message.text.split(maxsplit=1)
    if len(parts) < 2: return safe_send(message.chat.id, escape_md("📝 Usage: /release <pokemon_name>"), reply_to_id=message.message_id)
    poke_name = parts[1].strip().title()
    if db.delete_pokemon(message.from_user.id, poke_name): safe_send(message.chat.id, escape_md(f"👋 You released {poke_name} back into the wild."), reply_to_id=message.message_id)
    else: safe_send(message.chat.id, escape_md(f"❌ You don't have a {poke_name} to release."), reply_to_id=message.message_id)

@bot.message_handler(commands=["pvp"])
def cmd_pvp(message):
    pvp.handle_pvp_command(bot, message)

@bot.message_handler(commands=["myteam"])
def cmd_myteam(message):
    user_id = message.from_user.id
    
    user_team = None
    for b in pvp.pvp_battles.values():
        if b["p1_id"] == user_id:
            user_team = b["p1_team"]
            break
        elif b["p2_id"] == user_id:
            user_team = b["p2_team"]
            break
            
    if not user_team:
        return safe_send(message.chat.id, escape_md("❌ You are not currently in an active PvP battle!"), reply_to_id=message.message_id)
        
    team_text = "🎒 *Your Current PvP Team:*\n\n"
    for i, p in enumerate(user_team):
        types_str = p.get('types', 'Unknown')
        emojis = " / ".join([f"{t.strip()} {TYPE_EMOJIS.get(t.strip(), '⚪')}" for t in types_str.split('/')])
        
        team_text += f"*{i+1}\\. {escape_md(p['name'])}* \\[{escape_md(emojis)}\\]\n"
        team_text += f"🌿 *Nature:* {escape_md(p['nature'])}\n"
        team_text += f"⚔️ *Moves:*\n"
        for m in p['moves']:
            m_emoji = TYPE_EMOJIS.get(m['type'], '')
            m_pow = m.get('power', 0)
            m_pow_str = str(m_pow) if m_pow > 0 else "\\-"
            m_type_str = escape_md(f"{m['type']} {m_emoji}")
            team_text += f"  \\- {escape_md(m['name'])} \\[{m_type_str}\\] \\(Pow: {m_pow_str}, Acc: {m.get('acc', 100)}\\)\n"
        team_text += "\n"
        
    try:
        bot.send_message(user_id, team_text, parse_mode="MarkdownV2")
        if message.chat.type != "private":
            safe_send(message.chat.id, escape_md("✅ I have secretly sent your team strategy to your DMs!"), reply_to_id=message.message_id)
    except Exception as e:
        if "Forbidden" in str(e) or "chat not found" in str(e).lower():
            safe_send(message.chat.id, escape_md("⚠️ I cannot DM you! Please send me a private message first so I can share your team details privately."), reply_to_id=message.message_id)
        else:
            logger.error(f"Error sending /myteam DM: {e}")

@bot.message_handler(commands=["trade"])
def cmd_trade(message):
    db.add_user_if_new(message.from_user.id)
    trade.handle_trade_command(bot, message)

@bot.message_handler(commands=["getid"])
def cmd_getid(message):
    safe_send(message.chat.id, escape_md(f"🆔 Chat ID: {message.chat.id}\n📁 Chat Type: {message.chat.type}"), reply_to_id=message.message_id)

# ================== DYNAMIC LEADERBOARD ==================
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
        except Exception as e: 
            if "message is not modified" not in str(e).lower(): pass
    else:
        safe_send(chat_id, text, reply_markup=kb)

@bot.message_handler(commands=["flex", "top", "leaderboard"])
def cmd_flex(message):
    db.add_user_if_new(message.from_user.id)
    send_leaderboard(message.chat.id, message.from_user.id)


# ================== ADMIN: EXECUTE FRAMEWORK ==================
def is_owner(message):
    if message.from_user.id != OWNER_ID:
        safe_send(message.chat.id, escape_md("🚫 This command is for owner-sama only."), reply_to_id=message.message_id)
        return False
    return True

# --- Execute Logic Functions ---
def execute_world_stats(message):
    loading_text = "🌍 *Gathering Global Safari Data\\.\\.\\.*\n_Scanning all trainers\\.\\.\\._"
    status_msg = safe_send(message.chat.id, loading_text, reply_to_id=message.message_id)
    if not status_msg: return

    try:
        users = db.get_all_users()
        all_pokemon = []
        for uid in users:
            pokes = db.list_user_pokemon_names(uid)
            for p in pokes:
                all_pokemon.append(p.lower())
                
        counts = Counter(all_pokemon)
        total_caught_overall = len(all_pokemon)
        unique_caught = len(counts)
        
        all_possible = set(pokemon_name_to_id_cache.keys())
        caught_set = set(counts.keys())
        uncaught_set = all_possible - caught_set
        
        top_5 = counts.most_common(5)
        
        text = f"🌍 *Global Pokémon World Data*\n"
        text += f"━━━━━━━━━━━━━━\n"
        text += f"🏆 *Total Caught Worldwide:* {total_caught_overall}\n"
        text += f"🧬 *Unique Species Discovered:* {unique_caught}/898\n"
        text += f"👻 *Undiscovered Species:* {len(uncaught_set)}\n\n"
        
        text += f"📈 *Most Caught Pokémon:*\n"
        for i, (name, count) in enumerate(top_5):
            text += f"{i+1}\\. *{escape_md(name.title())}* \\({count} caught\\)\n"
            
        if uncaught_set:
            sample_uncaught = random.sample(list(uncaught_set), min(5, len(uncaught_set)))
            text += f"\n🔍 *Rumored Uncaught Pokémon:*\n"
            for name in sample_uncaught:
                text += f"\\- ||{escape_md(name.title())}||\n"
                
        text += f"\n_Tip: Use_ `/execute world find <pokemon>` _to track a specific Pokémon\\!_"
        bot.edit_message_text(text, message.chat.id, status_msg.message_id, parse_mode="MarkdownV2")
        
    except Exception as e:
        logger.error(f"Execute World Stat Error: {e}")
        try: bot.edit_message_text(escape_md("❌ An error occurred calculating world data."), message.chat.id, status_msg.message_id, parse_mode="MarkdownV2")
        except: pass

def execute_world_find(message, target_pokemon):
    loading_text = f"🌍 *Tracking {escape_md(target_pokemon.title())} globally\\.\\.\\.*"
    status_msg = safe_send(message.chat.id, loading_text, reply_to_id=message.message_id)
    if not status_msg: return

    try:
        users = db.get_all_users()
        owner_map = {} 
        target = target_pokemon.lower()
        target_display = target_pokemon.title()
        
        for uid in users:
            pokes = db.list_user_pokemon_names(uid)
            for p in pokes:
                if p.lower() == target:
                    if target not in owner_map: owner_map[target] = []
                    owner_map[target].append(uid)
                    
        if target not in owner_map:
            text = f"❌ *No one in the world has caught a {escape_md(target_display)} yet\\!*"
            bot.edit_message_text(text, message.chat.id, status_msg.message_id, parse_mode="MarkdownV2")
            return
            
        target_counts = Counter(owner_map[target])
        top_owners = target_counts.most_common(10)
        total_caught = sum(target_counts.values())
        
        text = f"📊 *Global Data: {escape_md(target_display)}*\n"
        text += f"━━━━━━━━━━━━━━\n"
        text += f"🌍 *Total in Existence:* {total_caught}\n\n"
        text += f"👑 *Top Owners:*\n"
        
        displayed_count = 0
        for uid, count in top_owners:
            displayed_count += count
            try:
                user_obj = bot.get_chat(uid)
                u_name = user_obj.first_name if user_obj.first_name else "Trainer"
            except:
                u_name = "Trainer"
            
            text += f"\\- [{escape_md(u_name)}](tg://user?id={uid}) — {count} caught\n"
            time.sleep(0.1) 
            
        leftover = total_caught - displayed_count
        if leftover > 0:
            text += f"\n_\\.\\.\\.and {leftover} more owned by other trainers\\._\n"
            
        bot.edit_message_text(text, message.chat.id, status_msg.message_id, parse_mode="MarkdownV2")
    except Exception as e:
        logger.error(f"Execute World Find Error: {e}")
        try: bot.edit_message_text(escape_md("❌ An error occurred tracking this Pokémon."), message.chat.id, status_msg.message_id, parse_mode="MarkdownV2")
        except: pass

def execute_world_spawn(message, pokemon_name):
    poke_name = pokemon_name.strip().lower()
    poke_id = get_pokemon_id_sync(poke_name)
    if not poke_id:
        return safe_send(message.chat.id, f"❌ Could not find data for *{escape_md(poke_name.title())}*\\.", reply_to_id=message.message_id)

    img_url = official_shiny_artwork_url(poke_id)
    cap = f"🚨 *A WILD EVENT APPEARED\\!* 🚨\n\nA wild ✨ *{escape_md(poke_name.title())}* has spawned in the area\\!\n\n_First person to click catch claims it\\!_"
    
    kb = types.InlineKeyboardMarkup()
    kb.add(types.InlineKeyboardButton("🔴 Catch", callback_data=f"gcatch_{poke_id}_{poke_name.title()[:16]}"))

    try:
        sent = bot.send_photo(message.chat.id, img_url, caption=cap, reply_to_message_id=message.message_id, reply_markup=kb, parse_mode="MarkdownV2")
        timer = threading.Timer(FLEE_TIMEOUT, auto_flee, args=(sent.message_id, message.chat.id, poke_name))
        timer.start()
        active_hunts[sent.message_id] = {"user_id": "ANY", "chat_id": message.chat.id, "start_time": time.time(), "timer": timer, "name": poke_name}
    except Exception as e:
        logger.error(f"Group spawn error: {e}")
        safe_send(message.chat.id, escape_md("❌ Failed to spawn the event Pokémon."), reply_to_id=message.message_id)

def execute_admin_givemany(message, args_str):
    if not message.reply_to_message:
        return safe_send(message.chat.id, escape_md("⚠️ You must reply to a user's message to give them Pokémon!"), reply_to_id=message.message_id)
        
    target_id = message.reply_to_message.from_user.id
    target_name = message.reply_to_message.from_user.first_name
    
    poke_list = [p.strip().title() for p in args_str.split(",") if p.strip()]
    if not poke_list:
        return safe_send(message.chat.id, escape_md("⚠️ Please provide a comma-separated list of Pokémon."), reply_to_id=message.message_id)
        
    db.add_user_if_new(target_id)
    for p in poke_list:
        db.add_caught_pokemon(target_id, p, "Admin Gift")
        
    safe_send(message.chat.id, f"🎁 Successfully gave {len(poke_list)} Pokémon to [{escape_md(target_name)}](tg://user?id={target_id})\\!\n\n_{escape_md(', '.join(poke_list))}_", reply_to_id=message.message_id)

def execute_user_stats(message, args_str):
    target_id = None
    target_name = "Trainer"
    
    if message.reply_to_message:
        target_id = message.reply_to_message.from_user.id
        target_name = message.reply_to_message.from_user.first_name
    elif args_str.isdigit():
        target_id = int(args_str)
    else:
        return safe_send(message.chat.id, escape_md("⚠️ Please reply to a user or provide their User ID."), reply_to_id=message.message_id)

    user_data = db.get_user(target_id)
    if not user_data:
        return safe_send(message.chat.id, escape_md("❌ This user is not registered in the database."), reply_to_id=message.message_id)
        
    tries = user_data[1]
    region = user_data[2]
    pokes = db.list_user_pokemon_names(target_id)
    total_caught = len(pokes)
    
    text = f"👤 *Trainer Database Record*\n"
    text += f"━━━━━━━━━━━━━━\n"
    text += f"🆔 *ID:* `{target_id}`\n"
    text += f"👤 *Name:* [{escape_md(target_name)}](tg://user?id={target_id})\n"
    text += f"🌍 *Region:* {escape_md(region)}\n"
    text += f"🔋 *Scouts Left:* {tries}/2500\n"
    text += f"🎒 *Total Pokémon:* {total_caught}\n"
    
    safe_send(message.chat.id, text, reply_to_id=message.message_id)

# --- The Execute Registry ---
EXECUTE_MODULES = {
    "world": {
        "description": "Global database and entity tracking.",
        "actions": {
            "stats": {"args": "", "desc": "View total caught, unique species, and top 5 most caught."},
            "find": {"args": "<pokemon>", "desc": "Locate all owners of a specific Pokémon."},
            "spawn": {"args": "<pokemon>", "desc": "Spawn a Pokémon in the chat for anyone to catch."}
        }
    },
    "user": {
        "description": "User data management.",
        "actions": {
            "stats": {"args": "[user_id]", "desc": "Check a user's secure profile (reply or ID)."}
        }
    },
    "admin": {
        "description": "Advanced game moderation.",
        "actions": {
            "givemany": {"args": "<poke1, poke2...>", "desc": "Give multiple Pokémon to a user at once (must reply to them)."}
        }
    },
    "system": {
        "description": "Core bot system commands.",
        "actions": {
            "ping": {"args": "", "desc": "Check if the execute framework router is online."}
        }
    }
}

@bot.message_handler(commands=["modules"])
def cmd_modules(message):
    if not is_owner(message): return
    text = "🛠 *System Modules & Actions*\n\n"
    for mod, mdata in EXECUTE_MODULES.items():
        text += f"📦 *Module:* `{mod}`\n_{escape_md(mdata['description'])}_\n"
        for act, adata in mdata["actions"].items():
            args_str = f" {adata['args']}" if adata["args"] else ""
            text += f"  \\- `/execute {mod} {act}{escape_md(args_str)}`\n"
            text += f"    └ {escape_md(adata['desc'])}\n"
        text += "\n"
    safe_send(message.chat.id, text, reply_to_id=message.message_id)

@bot.message_handler(commands=["execute", "exec"])
def cmd_execute(message):
    if not is_owner(message): return
    parts = message.text.split(maxsplit=3)
    if len(parts) < 3:
        return safe_send(message.chat.id, escape_md("⚠️ Format: /execute <module> <action> [arguments]\nUse /modules to view the directory."), reply_to_id=message.message_id)
    
    module = parts[1].lower()
    action = parts[2].lower()
    arguments = parts[3] if len(parts) > 3 else ""

    if module not in EXECUTE_MODULES or action not in EXECUTE_MODULES[module]["actions"]:
        return safe_send(message.chat.id, escape_md(f"❌ Invalid module or action. Use /modules to check valid combinations."), reply_to_id=message.message_id)

    if module == "world":
        if action == "stats":
            threading.Thread(target=execute_world_stats, args=(message,), daemon=True).start()
        elif action == "find":
            if not arguments:
                return safe_send(message.chat.id, escape_md("⚠️ Please provide a Pokémon name. Example: /execute world find Pikachu"), reply_to_id=message.message_id)
            threading.Thread(target=execute_world_find, args=(message, arguments), daemon=True).start()
        elif action == "spawn":
            if not arguments:
                return safe_send(message.chat.id, escape_md("⚠️ Please provide a Pokémon name. Example: /execute world spawn Arceus"), reply_to_id=message.message_id)
            execute_world_spawn(message, arguments)
            
    elif module == "user":
        if action == "stats":
            execute_user_stats(message, arguments)
            
    elif module == "admin":
        if action == "givemany":
            execute_admin_givemany(message, arguments)
            
    elif module == "system":
        if action == "ping":
            safe_send(message.chat.id, escape_md("🏓 Execute framework router is operational!"), reply_to_id=message.message_id)


# ================== OLD ADMIN COMMANDS ==================
@bot.message_handler(commands=["restore"])
def cmd_restore(message):
    if not is_owner(message): return
    safe_send(message.chat.id, escape_md("📥 Send me the old SQLite (.db) file to migrate it into the cloud PostgreSQL database. Max size: 20MB."), reply_to_id=message.message_id)

@bot.message_handler(content_types=["document"])
def handle_restore_file(message):
    if not is_owner(message): return
    if not message.document.file_name.endswith((".db", ".sqlite", ".db3")):
        return safe_send(message.chat.id, escape_md("❌ Invalid file. I need the old SQLite database to migrate."), reply_to_id=message.message_id)
    
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
    safe_send(message.chat.id, escape_md("☁️ You are on a cloud database now! Backups are handled automatically via Supabase."), reply_to_id=message.message_id)

@bot.message_handler(commands=["export"])
def cmd_export(message):
    if not is_owner(message): return
    status_msg = bot.reply_to(message, escape_md("🔄 Extracting data from PostgreSQL..."), parse_mode="MarkdownV2")
    try:
        data = db.export_all_data()
        json_data = json.dumps(data, default=str, indent=4)
        backup_file = io.BytesIO(json_data.encode('utf-8'))
        backup_file.name = f"database_backup_{int(time.time())}.json"
        bot.send_document(message.chat.id, backup_file, caption=escape_md("📦 Here is your complete database backup!"), parse_mode="MarkdownV2")
        bot.delete_message(message.chat.id, status_msg.message_id)
    except Exception as e:
        logger.error(f"Export Error: {e}")
        bot.edit_message_text(escape_md(f"❌ Export failed: {e}"), chat_id=message.chat.id, message_id=status_msg.message_id, parse_mode="MarkdownV2")

@bot.message_handler(commands=["plist"])
def cmd_plist(message):
    if not is_owner(message): return
    parts = message.text.split(maxsplit=1)
    if len(parts) < 2: return safe_send(message.chat.id, escape_md("📝 Usage: /plist <user_id>"), reply_to_id=message.message_id)
    try:
        uid = int(parts[1])
        names = db.list_user_pokemon_names(uid)
        if not names: return safe_send(message.chat.id, escape_md(f"User {uid} has no Pokémon."), reply_to_id=message.message_id)
        page_size = 20
        pages = [names[i:i + page_size] for i in range(0, len(names), page_size)]
        
        def make_kb(uid, num_pages):
            kb = types.InlineKeyboardMarkup(row_width=4)
            kb.add(
                types.InlineKeyboardButton("<<", callback_data=f"plist_{uid}_0"),
                types.InlineKeyboardButton(">>", callback_data=f"plist_{uid}_{num_pages - 1}")
            )
            return kb
        text = f"🎒 *Pokémon for User {uid}* \\(Page 1/{len(pages)}\\):\n\n" + "\n".join(f"\\- {escape_md(n)}" for n in pages[0])
        safe_send(message.chat.id, text, reply_to_id=message.message_id, reply_markup=make_kb(uid, len(pages)) if len(pages) > 1 else None)
    except Exception as e: 
        safe_send(message.chat.id, escape_md(f"Error: {str(e)}"), reply_to_id=message.message_id)

@bot.message_handler(commands=["take"])
def cmd_take(message):
    if not is_owner(message): return
    if not message.reply_to_message:
        return safe_send(message.chat.id, "⚠️ *Please reply to a user's message to take their Pokémon\\!*", reply_to_id=message.message_id)
    args = message.text.split(maxsplit=1)
    if len(args) < 2:
        return safe_send(message.chat.id, "⚠️ *Format:* `/take <pokemon_name>`", reply_to_id=message.message_id)
    target_id = message.reply_to_message.from_user.id
    target_name = message.reply_to_message.from_user.first_name
    pokemon_name = args[1].strip().title()
    
    if db.delete_pokemon(target_id, pokemon_name):
        safe_send(message.chat.id, f"🗑️ Successfully took *{escape_md(pokemon_name)}* from [{escape_md(target_name)}](tg://user?id={target_id})\\!", reply_to_id=message.message_id)
    else:
        safe_send(message.chat.id, f"❌ [{escape_md(target_name)}](tg://user?id={target_id}) doesn't own a *{escape_md(pokemon_name)}*\\.", reply_to_id=message.message_id)

@bot.message_handler(commands=["give"])
def cmd_give(message):
    if not is_owner(message): return
    if not message.reply_to_message:
        return safe_send(message.chat.id, "⚠️ *Please reply to a user's message to give them a Pokémon\\!*", reply_to_id=message.message_id)
    args = message.text.split(maxsplit=1)
    if len(args) < 2:
        return safe_send(message.chat.id, "⚠️ *Format:* `/give <pokemon_name>`", reply_to_id=message.message_id)
    target_id = message.reply_to_message.from_user.id
    target_name = message.reply_to_message.from_user.first_name
    pokemon_name = args[1].strip().title()
    db.add_caught_pokemon(target_id, pokemon_name, "Gift")
    safe_send(message.chat.id, f"🎁 Successfully gave *{escape_md(pokemon_name)}* to [{escape_md(target_name)}](tg://user?id={target_id})\\!", reply_to_id=message.message_id)

@bot.message_handler(commands=["reset"])
def cmd_reset(message):
    if not is_owner(message): return
    if not message.reply_to_message:
        return safe_send(message.chat.id, "⚠️ *Please reply to a user's message to reset their tries\\!*", reply_to_id=message.message_id)
    target_id = message.reply_to_message.from_user.id
    target_name = message.reply_to_message.from_user.first_name
    db.reset_user(target_id)
    safe_send(message.chat.id, f"🔄 Successfully reset scouts for [{escape_md(target_name)}](tg://user?id={target_id})\\!", reply_to_id=message.message_id)

@bot.message_handler(commands=["bcast", "gcast"])
def cmd_broadcasts(message):
    if not is_owner(message): return
    if not message.reply_to_message: return safe_send(message.chat.id, escape_md("⚠️ Please reply to a message to forward it."), reply_to_id=message.message_id)
    targets = db.get_all_groups() if message.text.startswith("/gcast") else db.get_all_users()
    success, failed = 0, 0
    for target_id in targets:
        try:
            bot.forward_message(target_id, message.chat.id, message.reply_to_message.message_id)
            success += 1
            time.sleep(0.1)
        except: failed += 1
    safe_send(message.chat.id, escape_md(f"📢 Broadcast complete! Success: {success}, Failed: {failed}"), reply_to_id=message.message_id)

@bot.message_handler(commands=["gcs"])
def cmd_gcs(message):
    if not is_owner(message): return
    groups = db.get_all_groups()
    if not groups: return safe_send(message.chat.id, escape_md("The bot is not in any groups."), reply_to_id=message.message_id)
    safe_send(message.chat.id, f"🏢 *Groups \\({len(groups)}\\):*\n\n" + "\n".join(f"\\- `{gid}`" for gid in groups), reply_to_id=message.message_id)

@bot.message_handler(commands=["allusers"])
def cmd_allusers(message):
    if not is_owner(message): return
    users = db.get_all_users()
    if not users: return safe_send(message.chat.id, escape_md("No registered trainers."), reply_to_id=message.message_id)
    text = f"👥 *Users \\({len(users)}\\):*\n\n" + "\n".join(f"\\- `{uid}`" for uid in users[:50])
    if len(users) > 50: text += f"\n\n_\\.\\.\\.and {len(users)-50} more\\._"
    safe_send(message.chat.id, text, reply_to_id=message.message_id)

@bot.message_handler(commands=["leave"])
def cmd_leave(message):
    if not is_owner(message): return
    parts = message.text.split(maxsplit=1)
    if len(parts) < 2: return safe_send(message.chat.id, escape_md("📝 Usage: /leave <group_id>"), reply_to_id=message.message_id)
    try:
        group_id = int(parts[1])
        bot.leave_chat(group_id)
        db.remove_group(group_id)
        safe_send(message.chat.id, escape_md(f"✅ Left group {group_id}."), reply_to_id=message.message_id)
    except Exception as e: safe_send(message.chat.id, escape_md(f"Error: {str(e)}"), reply_to_id=message.message_id)

@bot.message_handler(commands=["debug"])
def cmd_debug(message):
    if not is_owner(message): return
    try:
        u_c, p_c, g_c = db.get_debug_stats()
        safe_send(message.chat.id, f"🛠 *Bot Debug Info*\n━━━━━━━━━━━━\n👥 *Trainers:* {u_c}\n🏆 *Pokémon:* {p_c}\n🎯 *Active Hunts:* {len(active_hunts)}\n⚔️ *Active PvP:* {len(pvp.pvp_battles)}\n🏢 *Groups:* {g_c}", reply_to_id=message.message_id)
    except Exception as e: safe_send(message.chat.id, escape_md(f"Error: {str(e)}"), reply_to_id=message.message_id)

@bot.message_handler(commands=["clearhunts"])
def cmd_clearhunts(message):
    if not is_owner(message): return
    for hunt in active_hunts.values():
        if "timer" in hunt: hunt["timer"].cancel()
    active_hunts.clear()
    pvp.pvp_battles.clear()
    trade.active_trades.clear()
    safe_send(message.chat.id, escape_md("🧹 All active hunts, trades, and PvP battles cleared."), reply_to_id=message.message_id)

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
        # Route Trade Engine callbacks
        if call.data.startswith("tr_"):
            return trade.handle_trade_callback(bot, call)
            
        # Route Pokedex UI clicks
        if call.data == "ignore":
            return bot.answer_callback_query(call.id)
            
        elif call.data.startswith("dex_"):
            parts = call.data.split("_", 2)
            page = parts[1]
            name = parts[2]
            
            text = get_dex_text(name, page)
            if text:
                kb = types.InlineKeyboardMarkup(row_width=2)
                if page == "info":
                    kb.add(
                        types.InlineKeyboardButton("✅ ℹ️ Info", callback_data="ignore"),
                        types.InlineKeyboardButton("📊 Stats", callback_data=f"dex_stats_{name}")
                    )
                else:
                    kb.add(
                        types.InlineKeyboardButton("ℹ️ Info", callback_data=f"dex_info_{name}"),
                        types.InlineKeyboardButton("✅ 📊 Stats", callback_data="ignore")
                    )
                try: bot.edit_message_caption(caption=text, chat_id=call.message.chat.id, message_id=call.message.message_id, reply_markup=kb, parse_mode="MarkdownV2")
                except Exception as e:
                    if "message is not modified" not in str(e).lower(): pass
            return

        # Route PvP callbacks
        if call.data.startswith("pvp_"):
            return pvp.handle_pvp_callback(bot, call)
            
        # Route Flex Refresh
        if call.data.startswith("refresh_flex_"):
            owner_id = int(call.data.split("_")[2])
            if call.from_user.id != owner_id:
                return bot.answer_callback_query(call.id, "❌ You cannot refresh someone else's flex menu!", show_alert=True)
            bot.answer_callback_query(call.id, "🔄 Refreshing Leaderboard...")
            return send_leaderboard(call.message.chat.id, owner_id, call.message.message_id)

        # Route Daily Tasks
        if call.data.startswith("task"):
            return tasks.handle_task_callback(bot, call)

        if call.data.startswith("travel_"):
            parts = call.data.split("_", 2)
            uid, region = int(parts[1]), parts[2]
            if call.from_user.id != uid: return bot.answer_callback_query(call.id, "Not your menu.")
            db.update_user_region(uid, region)
            try: bot.edit_message_text(f"✈️ Travelled to *{escape_md(region)}*\\.", call.message.chat.id, call.message.message_id, parse_mode="MarkdownV2")
            except Exception as e:
                if "message is not modified" not in str(e).lower(): pass

        # --- NEW: GROUP CATCH HANDLER (/execute world spawn) ---
        elif call.data.startswith("gcatch_"):
            parts = call.data.split("_", 2)
            pid, name = int(parts[1]), parts[2]
            
            if call.message.message_id not in active_hunts:
                return bot.answer_callback_query(call.id, "💨 The Pokémon already fled!", show_alert=True)
                
            try: bot.answer_callback_query(call.id, "")
            except: pass
            
            hunt_data = active_hunts.pop(call.message.message_id, None)
            if hunt_data and "timer" in hunt_data:
                hunt_data["timer"].cancel()
                
            catcher_id = call.from_user.id
            catcher_name = call.from_user.first_name
            db.add_user_if_new(catcher_id)
            db.add_caught_pokemon(catcher_id, name.title(), "Event")
            
            # Safe task check
            try: tasks.check_and_update_catch(catcher_id, name.title())
            except: pass
            
            cap = f"🎉 *{escape_md(catcher_name)}* was the fastest and caught the ✨ *{escape_md(name.title())}*\\!"
            try: bot.edit_message_caption(caption=cap, chat_id=call.message.chat.id, message_id=call.message.message_id, parse_mode="MarkdownV2")
            except: pass

        # --- NORMAL CATCH HANDLER ---
        elif call.data.startswith("catch_"):
            parts = call.data.split("_", 3)
            uid, pid, name = int(parts[1]), int(parts[2]), parts[3]
            if call.from_user.id != uid: return bot.answer_callback_query(call.id, "Hands off! This scout is not yours.")
            
            # Critical Fix: Do not allow catching if it was overridden!
            if call.message.message_id not in active_hunts: 
                return bot.answer_callback_query(call.id, "💨 The Pokémon already fled!", show_alert=True)
            
            try: bot.answer_callback_query(call.id, "")
            except: pass
            
            active_hunts[call.message.message_id]["timer"].cancel()
            active_hunts.pop(call.message.message_id, None)
            threading.Thread(target=process_catch, args=(call, uid, pid, name)).start()

        elif call.data.startswith("run_"):
            parts = call.data.split("_", 2)
            uid, name = int(parts[1]), parts[2]
            if call.from_user.id != uid: return bot.answer_callback_query(call.id, "This scout is not yours.")
            
            if call.message.message_id not in active_hunts: 
                return bot.answer_callback_query(call.id, "💨 The Pokémon already fled!", show_alert=True)
            
            try: bot.answer_callback_query(call.id, "")
            except: pass
            
            active_hunts[call.message.message_id]["timer"].cancel()
            active_hunts.pop(call.message.message_id, None)
            
            fled_cap = f"💨 Tʜᴇ Wɪʟᴅ ✨ {escape_md(to_small_caps(name.title()))} Fʟᴇᴅ\\!"
            try: bot.edit_message_caption(caption=fled_cap, chat_id=call.message.chat.id, message_id=call.message.message_id, parse_mode="MarkdownV2")
            except: pass

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
            try: 
                bot.edit_message_text(text, call.message.chat.id, call.message.message_id, reply_markup=kb if len(pages)>1 else None, parse_mode="MarkdownV2")
            except Exception as e:
                err_msg = str(e).lower()
                if "message is not modified" not in err_msg:
                    if "429" in err_msg or "too many requests" in err_msg:
                        time.sleep(1.5)
                        try: bot.edit_message_text(text, call.message.chat.id, call.message.message_id, reply_markup=kb if len(pages)>1 else None, parse_mode="MarkdownV2")
                        except: pass
                    else:
                        logger.error(f"Pagination error: {e}")

    except Exception as e:
        logger.error(f"Callback error: {e}")

# ================== RUN ==================
if __name__ == "__main__":
    db.init_db()
    logger.info("Bot is starting...")
    bot.delete_webhook()
    bot.infinity_polling(skip_pending=True)
