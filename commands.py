# commands.py
import time
import threading
import random
from telebot import types

import database as db
import pvp
import tasks
import trade
from config import LOG_GROUP_ID, FLEE_TIMEOUT, REGIONS, logger
from api_utils import (escape_md, fetch_random_pokemon_id_and_name_sync, official_shiny_artwork_url, 
                       get_species_catch_rate_sync, get_pokemon_stats_sync, get_pokemon_id_sync, 
                       REGION_DEX, LEGENDARY_NAMES)

TYPE_EMOJIS = {
    'Normal': '🔘', 'Fire': '🔥', 'Water': '💧', 'Electric': '⚡', 'Grass': '🌿', 
    'Ice': '🧊', 'Fighting': '🥊', 'Poison': '☣️', 'Ground': '⛰️', 'Flying': '🪽', 
    'Psychic': '🔮', 'Bug': '🐛', 'Rock': '🪨', 'Ghost': '👻', 'Dragon': '🐉', 
    'Dark': '🌑', 'Steel': '🔩', 'Fairy': '🧚‍♀️'
}

def to_small_caps(text):
    small_caps_map = {
        'a': 'ᴀ', 'b': 'ʙ', 'c': 'ᴄ', 'd': 'ᴅ', 'e': 'ᴇ', 'f': 'ғ', 'g': 'ɢ',
        'h': 'ʜ', 'i': 'ɪ', 'j': 'ᴊ', 'k': 'ᴋ', 'l': 'ʟ', 'm': 'ᴍ', 'n': 'ɴ',
        'o': 'ᴏ', 'p': 'ᴘ', 'q': 'ǫ', 'r': 'ʀ', 's': 's', 't': 'ᴛ', 'u': 'ᴜ',
        'v': 'ᴠ', 'w': 'ᴡ', 'x': 'x', 'y': 'ʏ', 'z': 'ᴢ'
    }
    return "".join(char if char.isupper() else small_caps_map.get(char.lower(), char) for char in text)

def safe_send(bot, chat_id, text, reply_to_id=None, reply_markup=None):
    try: return bot.send_message(chat_id, text, reply_to_message_id=reply_to_id, reply_markup=reply_markup, parse_mode="MarkdownV2")
    except Exception as e:
        if "429" in str(e) or "Too Many Requests" in str(e):
            time.sleep(2.5) 
            try: return bot.send_message(chat_id, text, reply_to_message_id=reply_to_id, reply_markup=reply_markup, parse_mode="MarkdownV2")
            except: pass
        return None

# ================== GAME LOGIC ==================
def auto_flee(bot, message_id, chat_id, pokemon_name, active_hunts):
    if message_id not in active_hunts: return
    try:
        fled_cap = f"💨 Tʜᴇ Wɪʟᴅ ✨ {escape_md(to_small_caps(pokemon_name.title()))} Fʟᴇᴅ\\!"
        bot.edit_message_caption(caption=fled_cap, chat_id=chat_id, message_id=message_id, reply_markup=None, parse_mode="MarkdownV2")
    except: pass
    active_hunts.pop(message_id, None)

def start_scout(bot, chat_id, user_id, active_hunts, reply_to_id=None):
    if not db.get_user(user_id): return safe_send(bot, chat_id, escape_md("⚠️ Please /start the bot first."), reply_to_id)
    if pvp.is_in_battle(user_id): return safe_send(bot, chat_id, escape_md("⚔️ You cannot scout while engaged in a PvP battle!"), reply_to_id)
        
    tries_left, region = db.update_user_tries(user_id)
    if tries_left is None: return safe_send(bot, chat_id, escape_md("⚠️ Error checking your profile."), reply_to_id)
    if tries_left <= 0: return safe_send(bot, chat_id, escape_md("💤 You have no scouts left today. Rest and come back tomorrow!"), reply_to_id)
        
    to_cancel = [msg_id for msg_id, hunt in active_hunts.items() if hunt["user_id"] == user_id]
    for msg_id in to_cancel:
        hunt = active_hunts.pop(msg_id, None)
        if hunt:
            hunt["timer"].cancel()
            try: bot.edit_message_caption(caption=f"💨 Tʜᴇ Wɪʟᴅ ✨ {escape_md(to_small_caps(hunt['name'].title()))} Fʟᴇᴅ\\!", chat_id=hunt["chat_id"], message_id=msg_id, reply_markup=None, parse_mode="MarkdownV2")
            except: pass

    poke_id, name, base_id = fetch_random_pokemon_id_and_name_sync(region)
    if not poke_id: return safe_send(bot, chat_id, escape_md("❌ Failed to find a Pokémon. Try again."), reply_to_id)

    img_url = official_shiny_artwork_url(base_id)
    caption = f"A Wɪʟᴅ ✨ {escape_md(to_small_caps(name.title()))} Aᴘᴘᴇᴀʀᴇᴅ ɪɴ {escape_md(to_small_caps(region))}\\!\n\n🎒 Wʜᴀᴛ Wɪʟʟ Yᴏᴜ Dᴏ, Tʀᴀɪɴᴇʀ?"
    kb = types.InlineKeyboardMarkup().add(
        types.InlineKeyboardButton("🎯 Cᴀᴛᴄʜ", callback_data=f"catch_{user_id}_{poke_id}_{name[:16]}"),
        types.InlineKeyboardButton("🏃 Rᴜɴ", callback_data=f"run_{user_id}_{name[:16]}")
    )

    try:
        sent = bot.send_photo(chat_id, img_url, caption=caption, reply_to_message_id=reply_to_id, reply_markup=kb, parse_mode="MarkdownV2")
        timer = threading.Timer(FLEE_TIMEOUT, auto_flee, args=(bot, sent.message_id, chat_id, name, active_hunts))
        timer.start()
        active_hunts[sent.message_id] = {"user_id": user_id, "chat_id": chat_id, "start_time": time.time(), "timer": timer, "name": name}
    except Exception as e: 
        if "429" in str(e):
            time.sleep(2) 
            try:
                sent = bot.send_photo(chat_id, img_url, caption=caption, reply_to_message_id=reply_to_id, reply_markup=kb, parse_mode="MarkdownV2")
                timer = threading.Timer(FLEE_TIMEOUT, auto_flee, args=(bot, sent.message_id, chat_id, name, active_hunts))
                timer.start()
                active_hunts[sent.message_id] = {"user_id": user_id, "chat_id": chat_id, "start_time": time.time(), "timer": timer, "name": name}
            except: pass

def process_catch(bot, call, uid, pid, name):
    chat_id = call.message.chat.id
    msg_id = call.message.message_id
    try:
        try: bot.edit_message_caption(caption="🔴 *Yᴏᴜ ᴛʜʀᴇᴡ ᴀ Pᴏᴋᴇ́ʙᴀʟʟ\\!*", chat_id=chat_id, message_id=msg_id, parse_mode="MarkdownV2")
        except: pass
        time.sleep(0.7) 
        
        catch_rate = get_species_catch_rate_sync(pid)
        if random.random() < max(0.05, min(0.95, catch_rate / 255.0)):
            poke_name_capped = name.title()
            db.add_caught_pokemon(uid, poke_name_capped, db.get_user(uid)[2])
            try: tasks.check_and_update_catch(uid, poke_name_capped)
            except: pass
            
            if LOG_GROUP_ID:
                try: bot.send_message(LOG_GROUP_ID, f"🟢 *Catch Log:* [{escape_md(call.from_user.first_name)}](tg://user?id={uid}) caught a ✨ Shiny {escape_md(poke_name_capped)}\\!", parse_mode="MarkdownV2")
                except: pass
            
            try: bot.edit_message_caption(caption=f"✨ *Gᴏᴛᴄʜᴀ\\!* Sʜɪɴʏ *{escape_md(to_small_caps(poke_name_capped))}* ᴡᴀs ᴄᴀᴜɢʜᴛ\\!\n\nUse /inspect `{escape_md(poke_name_capped)}` to view it\\.", chat_id=chat_id, message_id=msg_id, parse_mode="MarkdownV2")
            except: pass
        else:
            try: bot.edit_message_caption(caption=f"💨 *Oʜ ɴᴏ\\!* Tʜᴇ Wɪʟᴅ ✨ {escape_md(to_small_caps(name.title()))} ʙʀᴏᴋᴇ ғʀᴇᴇ ᴀɴᴅ ғʟᴇᴅ\\!", chat_id=chat_id, message_id=msg_id, parse_mode="MarkdownV2")
            except: pass
    except: pass

def get_dex_text(name, page="info"):
    poke_id = get_pokemon_id_sync(name)
    if not poke_id: return None
    types_list, stats = get_pokemon_stats_sync(name)
    if not stats: return None
    
    if page == "info":
        catch_rate = get_species_catch_rate_sync(poke_id)
        prob = "Very Low" if catch_rate <= 45 else ("Low" if catch_rate <= 90 else ("Medium" if catch_rate <= 150 else "High"))
        region_found = next((r for r, (min_id, max_id) in REGION_DEX.items() if min_id <= poke_id <= max_id), "Unknown")
        types_str = " / ".join([f"{t} {TYPE_EMOJIS.get(t, '')}" for t in types_list])
        return (f"📱 *Pokédex Data*\n━━━━━━━━━━━━━━\n🔢 *Pokédex No\\.:* {poke_id}\n📛 *Name:* {escape_md(name.capitalize())}\n"
                f"🧬 *Types:* \\[{escape_md(types_str)}\\]\n🎯 *Catch probability:* {prob}\n🌍 *Regions found:* {escape_md(region_found)}")
    else:
        stats_str = "\n".join([f"🔸 *{escape_md(k)}:* {v}" for k, v in stats.items()])
        return (f"📊 *Base Stats: {escape_md(name.capitalize())}*\n━━━━━━━━━━━━━━\n{stats_str}\n━━━━━━━━━━━━━━\n📈 *Total:* {sum(stats.values())}")

def send_leaderboard(bot, chat_id, user_id, message_id=None):
    top_trainers = db.get_top_trainers(5)
    text = "🏆 *Top Trainers Leaderboard:*\n\n"
    for i, (uid, count) in enumerate(top_trainers):
        try: name = bot.get_chat(uid).first_name or "Trainer"
        except: name = "Trainer"
        text += f"{i+1}\\. [{escape_md(name)}](tg://user?id={uid}) — {count} Pokémon\n"
    
    kb = types.InlineKeyboardMarkup().add(types.InlineKeyboardButton("REFRESH 🌀", callback_data=f"refresh_flex_{user_id}"))
    text += f"\nYour Rank — *{db.get_user_rank(user_id)}*"
    if message_id:
        try: bot.edit_message_text(text, chat_id, message_id, reply_markup=kb, parse_mode="MarkdownV2")
        except: pass
    else: safe_send(bot, chat_id, text, reply_markup=kb)

# ================== REGISTRATION ROUTER ==================
def register_user_handlers(bot, active_hunts):
    
    @bot.message_handler(commands=["start"])
    def cmd_start(message):
        is_new = db.add_user_if_new(message.from_user.id)
        if message.chat.type in ["group", "supergroup"]: db.add_group(message.chat.id)
        kb = types.InlineKeyboardMarkup(row_width=2)
        kb.row(types.InlineKeyboardButton("Oᴡɴᴇʀ ⚡", url="https://t.me/monarch_sama"), types.InlineKeyboardButton("Mᴀɪɴ Gʀᴏᴜᴘ ⚡", url="https://t.me/sexagamechat"))
        text = (f"Hҽყ {escape_md(message.from_user.first_name)}\n\n*Wᴇʟᴄσɱᴇ ᴛσ Sᴇxᴀ ✨*\n*Tʜᴇ Sʜɪɴʏ Pᴏᴋᴇ́ᴍᴏɴ Aᴅᴠᴇɴᴛᴜʀᴇ*\n\n"
                f"━━━━━━━━━━━━━━━\n*🔎 Hᴜɴᴛ • 🎯 Cᴀᴛᴄʜ • 💎 Fʟᴇx*\n━━━━━━━━━━━━━━━\n*🌍 Yᴏᴜʀ Jᴏᴜʀɴᴇʏ Bᴇɢɪɴs Nᴏᴡ*")
        safe_send(bot, message.chat.id, text, reply_to_id=message.message_id, reply_markup=kb)

    @bot.message_handler(commands=["open"])
    def cmd_open(message):
        if message.chat.type != "private": return safe_send(bot, message.chat.id, escape_md("⚠️ Only in DMs."), reply_to_id=message.message_id)
        kb = types.ReplyKeyboardMarkup(resize_keyboard=True, row_width=1).add(types.KeyboardButton("🔎 Scout"))
        bot.send_message(message.chat.id, "⌨️ *Mᴇɴᴜ Oᴘᴇɴᴇᴅ\\!*\n/close ᴛᴏ Hɪᴅᴇ", reply_markup=kb, parse_mode="MarkdownV2")

    @bot.message_handler(commands=["close"])
    def cmd_close(message):
        if message.chat.type != "private": return
        bot.send_message(message.chat.id, "⌨️ *Mᴇɴᴜ Cʟᴏsᴇᴅ\\!*\nTʏᴘᴇ /open ᴛᴏ Rᴇᴏᴘᴇɴ\\.", reply_markup=types.ReplyKeyboardRemove(), parse_mode="MarkdownV2")

    @bot.message_handler(func=lambda message: message.text == "🔎 Scout" and message.chat.type == "private")
    def text_scout(message): threading.Thread(target=start_scout, args=(bot, message.chat.id, message.from_user.id, active_hunts, message.message_id)).start()

    @bot.message_handler(commands=["scout"])
    def command_scout(message): threading.Thread(target=start_scout, args=(bot, message.chat.id, message.from_user.id, active_hunts, message.message_id)).start()

    @bot.message_handler(commands=["task", "tasks"])
    def cmd_task(message):
        db.add_user_if_new(message.from_user.id)
        tasks.render_tasks_ui(bot, message.chat.id, message.from_user.id)

    @bot.message_handler(commands=["profile", "trainer"])
    def cmd_profile(message):
        user_id = message.from_user.id
        if not db.get_user(user_id): return safe_send(bot, message.chat.id, escape_md("⚠️ Please /start the bot first."), reply_to_id=message.message_id)
        tries_left, region = db.update_user_tries(user_id)
        names = db.list_user_pokemon_names(user_id)
        rarest_caught = [p for p in names if p in LEGENDARY_NAMES or "Mega" in p or "Primal" in p][0] if names and any(p for p in names if p in LEGENDARY_NAMES or "Mega" in p or "Primal" in p) else (names[-1] if names else "None")
        wins, losses = db.get_battle_stats(user_id)
            
        text = (f"✦─────────────────✦\n🪪  𝗧𝗥𝗔𝗜𝗡𝗘𝗥 𝗖𝗔𝗥𝗗  🪪\n✦─────────────────✦\n\n👤  {escape_md(message.from_user.first_name)}\n"
                f"🆔  `{user_id}`\n🌍  {escape_md(region)}\n\n✦───────────────✦\n𝗖𝗼𝗹𝗹𝗲𝗰𝘁𝗶𝗼𝗻\n🎒  {len(names)} 𝗣𝗼𝗸é𝗺𝗼𝗻\n"
                f"⭐  {escape_md(rarest_caught)}  \\(𝗿𝗮𝗿𝗲𝘀𝘁 𝗰𝗮𝘂𝗴𝗵𝘁\\)\n\n✦───────────────✦\n𝗦𝗰𝗼𝘂𝘁𝘀\n🔋  {tries_left} / 2500 𝗿𝗲𝗺𝗮𝗶𝗻𝗶𝗻𝗴\n\n"
                f"✦─────────────────✦\n𝗕𝗔𝗧𝗧𝗟𝗘 𝗥𝗘𝗖𝗢𝗥𝗗\n✦─────────────────✦\n\n🏆  𝗪𝗶𝗻𝘀          {wins}\n❌  𝗟𝗼𝘀𝘀𝗲𝘀        {losses}\n"
                f"📊  𝗧𝗼𝘁𝗮𝗹 𝗕𝗮𝘁𝘁𝗹𝗲𝘀 {wins+losses}\n\n✦─────────────────✦\n© 𝗣𝗼𝗸é𝗧𝗿𝗮𝗶𝗻𝗲𝗿 {escape_md(message.from_user.first_name)}")
        safe_send(bot, message.chat.id, text, reply_to_id=message.message_id)

    @bot.message_handler(commands=["travel"])
    def cmd_travel(message):
        if not db.get_user(message.from_user.id): return safe_send(bot, message.chat.id, escape_md("⚠️ Please /start the bot first."), reply_to_id=message.message_id)
        kb = types.InlineKeyboardMarkup(row_width=2)
        btns = [types.InlineKeyboardButton(f"{to_small_caps(r)}", callback_data=f"travel_{message.from_user.id}_{r}") for r in REGIONS]
        for i in range(0, len(btns), 2):
            if i + 1 < len(btns): kb.add(btns[i], btns[i+1])
            else: kb.add(btns[i])
        kb.add(types.InlineKeyboardButton("Cᴀɴᴄᴇʟ ↩️", callback_data=f"travel_cancel_{message.from_user.id}"))
        safe_send(bot, message.chat.id, "🌍 *Wʜᴇʀᴇ Wᴏᴜʟᴅ Yᴏᴜ Lɪᴋᴇ Tᴏ Tʀᴀᴠᴇʟ, Tʀᴀɪɴᴇʀ?*", reply_to_id=message.message_id, reply_markup=kb)

    @bot.message_handler(commands=["pokedex", "dex"])
    def cmd_pokedex(message):
        parts = message.text.split(maxsplit=1)
        if len(parts) < 2: return safe_send(bot, message.chat.id, escape_md("📝 Usage: /pokedex <pokemon_name>"), reply_to_id=message.message_id)
        name = parts[1].strip().lower()
        poke_id = get_pokemon_id_sync(name)
        if not poke_id: return safe_send(bot, message.chat.id, f"❌ Could not find data for *{escape_md(parts[1])}*\\.", reply_to_id=message.message_id)
        text = get_dex_text(name, "info")
        img_url = official_shiny_artwork_url(poke_id)
        kb = types.InlineKeyboardMarkup(row_width=2).add(types.InlineKeyboardButton("✅ ℹ️ Info", callback_data="ignore"), types.InlineKeyboardButton("📊 Stats", callback_data=f"dex_stats_{name}"))
        try: bot.send_photo(message.chat.id, img_url, caption=text, reply_markup=kb, parse_mode="MarkdownV2")
        except: pass

    @bot.message_handler(commands=["mypokemon", "mypokemons"])
    def cmd_mypokemon(message):
        if not db.get_user(message.from_user.id): return safe_send(bot, message.chat.id, escape_md("⚠️ Please /start the bot first."))
        names = db.list_user_pokemon_names(message.from_user.id)
        if not names: return safe_send(bot, message.chat.id, escape_md("🎒 You don't have any Pokémon yet."))
        pages = [names[i:i + 20] for i in range(0, len(names), 20)]
        kb = types.InlineKeyboardMarkup(row_width=4).add(types.InlineKeyboardButton("<<", callback_data=f"mypoke_{message.from_user.id}_0"), types.InlineKeyboardButton(">>", callback_data=f"mypoke_{message.from_user.id}_{len(pages) - 1}"))
        safe_send(bot, message.chat.id, f"🎒 *Your Pokémon* \\(Page 1/{len(pages)}\\):\n\n" + "\n".join(f"➥ {escape_md(n)}" for n in pages[0]), reply_markup=kb if len(pages)>1 else None)

    @bot.message_handler(commands=["inspect"])
    def cmd_inspect(message):
        if not db.get_user(message.from_user.id): return
        parts = message.text.split(maxsplit=1)
        if len(parts) < 2: return
        name = parts[1].strip().lower()
        if name not in [n.lower() for n in db.list_user_pokemon_names(message.from_user.id)]: return safe_send(bot, message.chat.id, escape_md("❌ You don't own this Pokémon."))
        poke_id = get_pokemon_id_sync(name)
        if poke_id:
            try: bot.send_photo(message.chat.id, official_shiny_artwork_url(poke_id), caption=f"✨ *{escape_md(name.capitalize())}* \\(Shiny\\)", parse_mode="MarkdownV2")
            except: pass

    @bot.message_handler(commands=["release"])
    def cmd_release(message):
        if not db.get_user(message.from_user.id): return
        parts = message.text.split(maxsplit=1)
        if len(parts) < 2: return
        poke_name = parts[1].strip().title()
        if db.delete_pokemon(message.from_user.id, poke_name): safe_send(bot, message.chat.id, escape_md(f"👋 You released {poke_name} back into the wild."))
        else: safe_send(bot, message.chat.id, escape_md(f"❌ You don't have a {poke_name}."))

    @bot.message_handler(commands=["pvp"])
    def command_pvp(message): pvp.handle_pvp_command(bot, message)

    @bot.message_handler(commands=["trade"])
    def command_trade(message): 
        db.add_user_if_new(message.from_user.id)
        trade.handle_trade_command(bot, message)

    @bot.message_handler(commands=["myteam"])
    def cmd_myteam(message):
        user_id = message.from_user.id
        user_team = next((b["p1_team"] if b["p1_id"] == user_id else b["p2_team"] for b in pvp.pvp_battles.values() if user_id in [b["p1_id"], b["p2_id"]]), None)
                
        if not user_team: return safe_send(bot, message.chat.id, escape_md("❌ You are not currently in an active PvP battle!"))
            
        team_text = "🎒 *Your Current PvP Team:*\n\n"
        for i, p in enumerate(user_team):
            emojis = " / ".join([f"{t.strip()} {TYPE_EMOJIS.get(t.strip(), '⚪')}" for t in p.get('types', 'Unknown').split('/')])
            team_text += f"*{i+1}\\. {escape_md(p['name'])}* \\[{escape_md(emojis)}\\]\n🌿 *Nature:* {escape_md(p['nature'])}\n⚔️ *Moves:*\n"
            for m in p['moves']: team_text += f"  \\- {escape_md(m['name'])} \\[{escape_md(f\"{m['type']} {TYPE_EMOJIS.get(m['type'], '')}\")}\\] \\(Pow: {m.get('power', 0)}, Acc: {m.get('acc', 100)}\\)\n"
            team_text += "\n"
            
        try:
            bot.send_message(user_id, team_text, parse_mode="MarkdownV2")
            if message.chat.type != "private":
                kb = types.InlineKeyboardMarkup().add(types.InlineKeyboardButton("Cʜᴇᴄᴋ DMs ❗❗", url=f"https://t.me/{bot.get_me().username}"))
                safe_send(bot, message.chat.id, "📩 *I’ᴠᴇ Sᴇɴᴛ Yᴏᴜʀ Tᴇᴀᴍ Sᴛʀᴀᴛᴇɢʏ Tᴏ Yᴏᴜʀ DMs\\!*", reply_to_id=message.message_id, reply_markup=kb)
        except: safe_send(bot, message.chat.id, escape_md("⚠️ Please send me a private message first!"))

    @bot.message_handler(commands=["flex", "top", "leaderboard"])
    def command_flex(message):
        db.add_user_if_new(message.from_user.id)
        send_leaderboard(bot, message.chat.id, message.from_user.id)
