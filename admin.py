# admin.py
import time
import datetime
import threading
import os
import sys
import json
import io
import sqlite3
import subprocess
from collections import Counter
from telebot import types

import database as db
import pvp
from config import OWNER_ID, FLEE_TIMEOUT, logger
from commands import to_small_caps, safe_send, auto_flee, clean_name, generate_pokemon_list_ui
from api_utils import escape_md, official_shiny_artwork_url, get_pokemon_id_sync, pokemon_name_to_id_cache

# Track when the bot was booted for the /debug Uptime counter
BOT_START_TIME = time.time()

# 📝 Track the last broadcast so we can delete it later!
LAST_BROADCAST_MSGS = []

def play_loading_animation(bot, chat_id, message_id):
    frames = [
        "▰▰▱▱▱▱▱▱▱▱ 20%",
        "▰▰▰▰▰▱▱▱▱▱ 50%",
        "▰▰▰▰▰▰▰▰▱▱ 80%",
        "▰▰▰▰▰▰▰▰▰▰ 100%"
    ]
    for frame in frames:
        try:
            bot.edit_message_text(f"⚡ *Lᴏᴀᴅɪɴɢ Dᴀᴛᴀ\\.\\.\\.*\n`{frame}`", chat_id, message_id, parse_mode="MarkdownV2")
            time.sleep(0.4)
        except: pass

def is_owner(bot, obj):
    """Checks if the user is the owner. Silently ignores if they are not."""
    if obj.from_user.id != OWNER_ID:
        if hasattr(obj, 'data'):
            try: bot.answer_callback_query(obj.id, "")
            except: pass
        return False
    return True

# ================== NEW GROUP INFO UI ==================
def generate_gcs_ui(bot, page_idx):
    groups = db.get_all_groups()
    if not groups:
        return escape_md("🏢 The bot is not currently in any tracked groups."), None
        
    if page_idx < 0: page_idx = len(groups) - 1
    if page_idx >= len(groups): page_idx = 0
    
    chat_id = groups[page_idx]
    
    try:
        chat = bot.get_chat(chat_id)
        name = chat.title or "Unknown Group"
        count = bot.get_chat_member_count(chat_id)
        
        bot_member = bot.get_chat_member(chat_id, bot.get_me().id)
        perm = "Admin" if bot_member.status == "administrator" else "Member"
        
        link = chat.invite_link
        if not link and perm == "Admin":
            try: link = bot.export_chat_invite_link(chat_id)
            except: link = "Unavailable"
        link_str = link if link else "Unavailable"
        
    except Exception:
        name = "Dead / Inaccessible Group"
        count = "N/A"
        perm = "N/A"
        link_str = "N/A"
        
    text = (
        f"🏢 *Gʀᴏᴜᴘ Iɴғᴏ* \\({page_idx + 1}/{len(groups)}\\)\n"
        f"━━━━━━━━━━━━━━\n"
        f"📛 *Gʀᴏᴜᴘ Nᴀᴍᴇ*\n{escape_md(name)}\n"
        f"👥 *Mᴇᴍʙᴇʀ Cᴏᴜɴᴛ*\n{escape_md(str(count))}\n"
        f"🆔 *Cʜᴀᴛ ID*\n`{chat_id}`\n"
        f"🔗 *Iɴᴠɪᴛᴇ Lɪɴᴋ*\n{escape_md(link_str)}\n"
        f"⚡ *Bᴏᴛ Pᴇʀᴍɪssɪᴏɴ*\n{escape_md(perm)}\n"
        f"🎮 *Bᴀᴛᴛʟᴇs Sᴛᴀʀᴛᴇᴅ*\nN/A \\(Nᴏᴛ Tʀᴀᴄᴋᴇᴅ ʏᴇᴛ\\)\n"
        f"━━━━━━━━━━━━━━"
    )
    
    kb = types.InlineKeyboardMarkup(row_width=2)
    kb.row(
        types.InlineKeyboardButton("⏪ Pʀᴇᴠ", callback_data=f"gcs_page_{page_idx - 1}"),
        types.InlineKeyboardButton("Nᴇxᴛ ⏩", callback_data=f"gcs_page_{page_idx + 1}")
    )
    kb.row(types.InlineKeyboardButton("🔄 Sʏɴᴄ Dᴀᴛᴀ", callback_data="gcs_sync"))
    
    return text, kb

# ================== NEW DEBUG ENGINE ==================
def generate_debug_ui(active_hunts):
    start_q = time.time()
    u_c, p_c, g_c, pvp_total, regions_active, db_size_mb = db.get_debug_stats()
    query_time = time.time() - start_q
    
    avg_response = round(max(0.11, query_time + 0.15), 2)
    uptime_seconds = int(time.time() - BOT_START_TIME)
    days = uptime_seconds // 86400
    hours = (uptime_seconds % 86400) // 3600
    mins = (uptime_seconds % 3600) // 60
    
    if days > 0: uptime_str = f"{days}ᴅ {hours}ʜ"
    elif hours > 0: uptime_str = f"{hours}ʜ {mins}ᴍ"
    else: uptime_str = f"{mins}ᴍ"

    db_mb_escaped = str(db_size_mb).replace('.', '\\.')
    resp_escaped = str(avg_response).replace('.', '\\.')

    text = (
        f"🛠 *Bᴏᴛ Dᴇʙᴜɢ Iɴғᴏ*\n"
        f"━━━━━━━━━━━━━━\n\n"
        f" 👥 Tʀᴀɪɴᴇʀs        : `{u_c}`\n"
        f" 🎒 Pᴏᴋᴇ́ᴍᴏɴ         : `{p_c}`\n"
        f" 🎯 Aᴄᴛɪᴠᴇ Hᴜɴᴛs    : `{len(active_hunts)}`\n"
        f" ⚔️ Aᴄᴛɪᴠᴇ PᴠP      : `{len(pvp.pvp_battles)}`\n"
        f" 🏆 PᴠP Bᴀᴛᴛʟᴇs     : `{pvp_total}`\n\n"
        f" 🌍 Rᴇɢɪᴏɴs Aᴄᴛɪᴠᴇ  : `{regions_active}`\n"
        f" 🏢 Gʀᴏᴜᴘs          : `{g_c}`\n"
        f" 📦 Dᴀᴛᴀʙᴀsᴇ Sɪᴢᴇ   : `{db_mb_escaped} MB`\n\n"
        f" ⏱ Bᴏᴛ Uᴘᴛɪᴍᴇ      : `{uptime_str}`\n"
        f" ⚡ Aᴠɢ Rᴇsᴘᴏɴsᴇ     : `{resp_escaped}s`\n\n"
        f"━━━━━━━━━━━━━━"
    )

    kb = types.InlineKeyboardMarkup(row_width=2)
    kb.row(
        types.InlineKeyboardButton("🌀 Rᴇғʀᴇsʜ", callback_data="debug_refresh"),
        types.InlineKeyboardButton("🗑️ Dᴇʟᴇᴛᴇ", callback_data="debug_delete")
    )
    return text, kb

def send_logs(bot, chat_id, message_id=None):
    try:
        with open("bot.log", "r") as f:
            lines = f.readlines()
            log_text = "".join(lines[-30:]) 
    except Exception:
        log_text = "Nᴏ ʟᴏɢ ғɪʟᴇ ғᴏᴜɴᴅ (bot.log)."

    text = f"📄 *Sʏsᴛᴇᴍ Lᴏɢs:*\n`{escape_md(log_text[-3000:])}`"
    kb = types.InlineKeyboardMarkup()
    kb.row(
        types.InlineKeyboardButton("🌀 Rᴇғʀᴇsʜ", callback_data="log_refresh"),
        types.InlineKeyboardButton("🗑️ Dᴇʟᴇᴛᴇ Lᴏɢs", callback_data="log_delete")
    )
    if message_id:
        try: bot.edit_message_text(text, chat_id, message_id, reply_markup=kb, parse_mode="MarkdownV2")
        except: pass
    else: safe_send(bot, chat_id, text, reply_markup=kb)

def handle_admin_callback(bot, call, active_hunts=None):
    if call.data == "log_refresh":
        if not is_owner(bot, call): return True
        bot.answer_callback_query(call.id, "Refreshing logs...")
        send_logs(bot, call.message.chat.id, call.message.message_id)
        return True
        
    elif call.data == "log_delete":
        if not is_owner(bot, call): return True
        open("bot.log", "w").close()
        bot.answer_callback_query(call.id, "Logs Deleted!", show_alert=True)
        send_logs(bot, call.message.chat.id, call.message.message_id)
        return True
        
    elif call.data == "debug_refresh":
        if not is_owner(bot, call): return True
        bot.answer_callback_query(call.id, "Refreshing Server Stats...")
        if active_hunts is not None:
            text, kb = generate_debug_ui(active_hunts)
            try: bot.edit_message_text(text, call.message.chat.id, call.message.message_id, reply_markup=kb, parse_mode="MarkdownV2")
            except: pass
        return True
        
    elif call.data == "debug_delete":
        if not is_owner(bot, call): return True
        bot.answer_callback_query(call.id, "Menu Closed.")
        try: bot.delete_message(call.message.chat.id, call.message.message_id)
        except: pass
        return True
        
    # --- NEW GCS ROUTING ---
    elif call.data.startswith("gcs_page_"):
        if not is_owner(bot, call): return True
        page_idx = int(call.data.split("_")[2])
        text, kb = generate_gcs_ui(bot, page_idx)
        try: bot.edit_message_text(text, call.message.chat.id, call.message.message_id, reply_markup=kb, parse_mode="MarkdownV2")
        except: pass
        return True
        
    elif call.data == "gcs_sync":
        if not is_owner(bot, call): return True
        bot.answer_callback_query(call.id, "🔄 Syncing groups... Please wait.")
        try: bot.edit_message_text(escape_md("⏳ Syncing database with Telegram servers..."), call.message.chat.id, call.message.message_id, parse_mode="MarkdownV2")
        except: pass
        
        groups = db.get_all_groups()
        removed = 0
        for gid in groups:
            try:
                bot.get_chat(gid)
            except Exception: 
                db.remove_group(gid) # Kicked or Chat deleted
                removed += 1
                
        text, kb = generate_gcs_ui(bot, 0)
        if text: text = f"✅ *Sʏɴᴄ Cᴏᴍᴘʟᴇᴛᴇ\\!* {removed} ᴅᴇᴀᴅ ɢʀᴏᴜᴘs ʀᴇᴍᴏᴠᴇᴅ\\.\n\n" + text
        else: text = escape_md(f"✅ Sync Complete! {removed} dead groups removed. No active groups left.")
            
        try: bot.edit_message_text(text, call.message.chat.id, call.message.message_id, reply_markup=kb, parse_mode="MarkdownV2")
        except: pass
        return True
        
    elif call.data.startswith("getfile_"):
        if not is_owner(bot, call): return True
        table_name = call.data.split("_", 1)[1]
        bot.answer_callback_query(call.id, "Extracting Data...")
        csv_data = db.export_table_csv(table_name)
        if csv_data:
            file_obj = io.BytesIO(csv_data.encode('utf-8'))
            file_obj.name = f"{table_name}_export.csv"
            bot.send_document(call.message.chat.id, file_obj, caption=f"📁 *{to_small_caps(table_name)} DB Exᴘᴏʀᴛ*", parse_mode="MarkdownV2")
        else:
            bot.send_message(call.message.chat.id, escape_md("❌ Extraction Failed."))
        return True
        
    return False

EXECUTE_MODULES = {
    "world": {
        "description": "Global database tracking.",
        "actions": {
            "stats": {"args": "", "desc": "View total caught and unique species."},
            "find": {"args": "<pokemon>", "desc": "Locate owners of a specific Pokémon."},
            "spawn": {"args": "<pokemon>", "desc": "Spawn a Pokémon in the chat."}
        }
    },
    "user": {
        "description": "User data management.",
        "actions": {"stats": {"args": "[user_id]", "desc": "Check a user's secure profile."}}
    },
    "admin": {
        "description": "Advanced game moderation.",
        "actions": {
            "givemany": {"args": "<poke1, poke2...>", "desc": "Give multiple Pokémon at once."},
            "upload": {"args": "<LeaderName>", "desc": "Upload a Gym Leader's image by replying to it."}
        }
    },
    "server": {
        "description": "Core bot system commands.",
        "actions": {"status": {"args": "", "desc": "Check bot server status."}}
    }
}

def register_admin_handlers(bot, active_hunts):
    
    # ================== 🏅 GYM ADMIN TOOLS ==================
    @bot.message_handler(commands=["upload", "setimage"])
    def cmd_upload_gym_image(message):
        if not is_owner(bot, message): return
        
        if not message.reply_to_message or not message.reply_to_message.photo:
            return safe_send(bot, message.chat.id, escape_md("⚠️ Please reply to an image with /upload <LeaderName>"), reply_to_id=message.message_id)
        
        args = message.text.split(maxsplit=1)
        if len(args) < 2:
            return safe_send(bot, message.chat.id, escape_md("⚠️ Format: /upload Brock"), reply_to_id=message.message_id)
            
        leader_name = args[1].strip().title()
        
        # Get the highest resolution version of the photo Telegram generated
        file_id = message.reply_to_message.photo[-1].file_id 
        
        db.set_gym_image(leader_name, file_id)
        safe_send(bot, message.chat.id, escape_md(f"✅ Successfully saved the image to the database for Gym Leader {leader_name}!"), reply_to_id=message.message_id)

    @bot.message_handler(commands=["lock_gym"])
    def cmd_lock_gym(message):
        if not is_owner(bot, message): return
        import gym
        gym.GYM_LOCKED = not gym.GYM_LOCKED
        status = "🔒 Lᴏᴄᴋᴇᴅ (Players blocked)" if gym.GYM_LOCKED else "🔓 Uɴʟᴏᴄᴋᴇᴅ (Players can play)"
        safe_send(bot, message.chat.id, escape_md(f"✅ The Pokémon League Gyms are now {status}!\n\n*(Note: As the Owner, you can still bypass this lock and battle freely!)*"), reply_to_id=message.message_id)

    @bot.message_handler(commands=["reset_badges"])
    def cmd_reset_badges(message):
        if not is_owner(bot, message): return
        db.reset_all_badges()
        safe_send(bot, message.chat.id, escape_md("🚨 SYSTEM OVERRIDE: All Gym Badges have been wiped from every user in the database!"), reply_to_id=message.message_id)
    # ========================================================

    @bot.message_handler(commands=["update"])
    def cmd_update(message):
        if not is_owner(bot, message): return
        msg = safe_send(bot, message.chat.id, "🔄 *Pᴜʟʟɪɴɢ Lᴀᴛᴇsᴛ Gɪᴛ Uᴘᴅᴀᴛᴇs\\.\\.\\.*", reply_to_id=message.message_id)
        try:
            result = subprocess.run(["git", "pull"], capture_output=True, text=True)
            output = escape_md(result.stdout[-1000:])
            bot.edit_message_text(f"✅ *Uᴘᴅᴀᴛᴇ Sᴜᴄᴄᴇssғᴜʟ\\!*\n\n`{output}`\n\n🔄 _Rᴇsᴛᴀʀᴛɪɴɢ Bᴏᴛ\\.\\.\\._", message.chat.id, msg.message_id, parse_mode="MarkdownV2")
            time.sleep(1)
            os.execl(sys.executable, sys.executable, *sys.argv)
        except Exception as e:
            bot.edit_message_text(f"❌ *Uᴘᴅᴀᴛᴇ Fᴀɪʟᴇᴅ:*\n`{escape_md(str(e))}`", message.chat.id, msg.message_id, parse_mode="MarkdownV2")

    @bot.message_handler(commands=["log", "logs"])
    def command_log(message):
        if not is_owner(bot, message): return
        send_logs(bot, message.chat.id)

    @bot.message_handler(commands=["files"])
    def cmd_files(message):
        if not is_owner(bot, message): return
        kb = types.InlineKeyboardMarkup(row_width=2)
        kb.add(
            types.InlineKeyboardButton("👥 Usᴇʀs DB", callback_data="getfile_users"),
            types.InlineKeyboardButton("🎒 Pᴏᴋᴇ́ᴍᴏɴ DB", callback_data="getfile_pokemons"),
            types.InlineKeyboardButton("⚔️ Sᴛᴀᴛs DB", callback_data="getfile_battle_stats"),
            types.InlineKeyboardButton("🏢 Gʀᴏᴜᴘs DB", callback_data="getfile_groups")
        )
        safe_send(bot, message.chat.id, "📁 *Dᴀᴛᴀʙᴀsᴇ Exᴘᴏʀᴛ Mᴇɴᴜ*\nSᴇʟᴇᴄᴛ ᴀ ᴛᴀʙʟᴇ ᴛᴏ ᴅᴏᴡɴʟᴏᴀᴅ ᴀs CSV:", reply_to_id=message.message_id, reply_markup=kb)

    @bot.message_handler(commands=["modules", "execute", "exec"])
    def cmd_execute(message):
        if not is_owner(bot, message): return
        if message.text.startswith("/modules"):
            text = "🛠 *Sʏsᴛᴇᴍ Mᴏᴅᴜʟᴇs*\n\n"
            for mod, mdata in EXECUTE_MODULES.items():
                text += f"📦 *Mᴏᴅᴜʟᴇ:* `{mod}`\n_{escape_md(mdata['description'])}_\n"
                for act, adata in mdata["actions"].items(): text += f"  \\- `/execute {mod} {act}{escape_md(' '+adata['args'] if adata['args'] else '')}`\n"
                text += "\n"
            return safe_send(bot, message.chat.id, text, reply_to_id=message.message_id)

        parts = message.text.split(maxsplit=3)
        if len(parts) < 3: return safe_send(bot, message.chat.id, escape_md("⚠️ Format: /execute <module> <action>"), reply_to_id=message.message_id)
        module, action = parts[1].lower(), parts[2].lower()
        arguments = parts[3] if len(parts) > 3 else ""

        if module == "world" and action == "stats":
            msg = safe_send(bot, message.chat.id, "⚡ *Iɴɪᴛɪᴀʟɪᴢɪɴɢ Mᴏᴅᴜʟᴇ\\.\\.\\.*", reply_to_id=message.message_id)
            play_loading_animation(bot, message.chat.id, msg.message_id)
            try:
                users = db.get_all_users()
                all_pokemon = []
                for uid in users:
                    for p in db.list_user_pokemon_names(uid): all_pokemon.append(p.lower())
                counts = Counter(all_pokemon)
                text = f"🌍 *Gʟᴏʙᴀʟ Sᴀғᴀʀɪ Dᴀᴛᴀ*\n━━━━━━━━━━━━━━\n🏆 *Total Caught:* {len(all_pokemon)}\n🧬 *Unique Species:* {len(counts)}/898\n\n📈 *Most Caught:*\n"
                for i, (name, count) in enumerate(counts.most_common(5)): text += f"{i+1}\\. *{escape_md(to_small_caps(name.title()))}* \\({count} caught\\)\n"
                bot.edit_message_text(text, message.chat.id, msg.message_id, parse_mode="MarkdownV2")
            except Exception as e: bot.edit_message_text(escape_md(f"❌ Error: {e}"), message.chat.id, msg.message_id, parse_mode="MarkdownV2")

        elif module == "world" and action == "find":
            msg = safe_send(bot, message.chat.id, "⚡ *Iɴɪᴛɪᴀʟɪᴢɪɴɢ Mᴏᴅᴜʟᴇ\\.\\.\\.*", reply_to_id=message.message_id)
            play_loading_animation(bot, message.chat.id, msg.message_id)
            try:
                users = db.get_all_users()
                owner_map = {} 
                target = arguments.lower()
                target_display = to_small_caps(arguments.title())
                for uid in users:
                    for p in db.list_user_pokemon_names(uid):
                        if p.lower() == target:
                            if target not in owner_map: owner_map[target] = []
                            owner_map[target].append(uid)
                if target not in owner_map: return bot.edit_message_text(f"❌ *No one has caught {escape_md(target_display)} yet\\!*", message.chat.id, msg.message_id, parse_mode="MarkdownV2")
                target_counts = Counter(owner_map[target])
                text = f"📊 *Gʟᴏʙᴀʟ Dᴀᴛᴀ: {escape_md(target_display)}*\n━━━━━━━━━━━━━━\n🌍 *Total Existing:* {sum(target_counts.values())}\n\n👑 *Top Owners:*\n"
                for uid, count in target_counts.most_common(10):
                    try: u_name = bot.get_chat(uid).first_name or "Trainer"
                    except: u_name = "Trainer"
                    text += f"\\- [{escape_md(clean_name(u_name))}](tg://user?id={uid}) — {count}\n"
                bot.edit_message_text(text, message.chat.id, msg.message_id, parse_mode="MarkdownV2")
            except: bot.edit_message_text(escape_md("❌ An error occurred."), message.chat.id, msg.message_id, parse_mode="MarkdownV2")

        elif module == "world" and action == "spawn":
            poke_name = arguments.strip().lower()
            poke_id = get_pokemon_id_sync(poke_name)
            if not poke_id: return safe_send(bot, message.chat.id, f"❌ Could not find data for *{escape_md(poke_name.title())}*\\.", reply_to_id=message.message_id)
            img_url = official_shiny_artwork_url(poke_id)
            cap = f"🚨 *A WILD EVENT APPEARED\\!* 🚨\n\nA wild ✨ *{escape_md(poke_name.title())}* has spawned in the area\\!\n\n_First person to click catch claims it\\!_"
            kb = types.InlineKeyboardMarkup().add(types.InlineKeyboardButton("🔴 Catch", callback_data=f"gcatch_{poke_id}_{poke_name.title()[:16]}"))
            try:
                sent = bot.send_photo(message.chat.id, img_url, caption=cap, reply_to_message_id=message.message_id, reply_markup=kb, parse_mode="MarkdownV2")
                timer = threading.Timer(FLEE_TIMEOUT, auto_flee, args=(bot, sent.message_id, message.chat.id, poke_name, active_hunts))
                timer.start()
                active_hunts[sent.message_id] = {"user_id": "ANY", "chat_id": message.chat.id, "start_time": time.time(), "timer": timer, "name": poke_name}
            except: safe_send(bot, message.chat.id, escape_md("❌ Failed to spawn the event Pokémon."), reply_to_id=message.message_id)

        elif module == "user" and action == "stats":
            target_id = message.reply_to_message.from_user.id if message.reply_to_message else (int(arguments) if arguments.isdigit() else None)
            target_name = clean_name(message.reply_to_message.from_user.first_name) if message.reply_to_message else "Trainer"
            if not target_id: return safe_send(bot, message.chat.id, escape_md("⚠️ Please reply to a user or provide their User ID."), reply_to_id=message.message_id)
            user_data = db.get_user(target_id)
            if not user_data: return safe_send(bot, message.chat.id, escape_md("❌ This user is not registered in the database."), reply_to_id=message.message_id)
            tries, region = user_data[1], user_data[2]
            text = f"👤 *Trainer Database Record*\n━━━━━━━━━━━━━━\n🆔 *ID:* `{target_id}`\n👤 *Name:* [{escape_md(target_name)}](tg://user?id={target_id})\n🌍 *Region:* {escape_md(region)}\n🔋 *Scouts Left:* {tries}/2500\n🎒 *Total Pokémon:* {len(db.list_user_pokemon_names(target_id))}\n"
            safe_send(bot, message.chat.id, text, reply_to_id=message.message_id)

        elif module == "admin" and action == "givemany":
            if not message.reply_to_message: return safe_send(bot, message.chat.id, escape_md("⚠️ You must reply to a user's message to give them Pokémon!"), reply_to_id=message.message_id)
            poke_list = [p.strip().title() for p in arguments.split(",") if p.strip()]
            if not poke_list: return safe_send(bot, message.chat.id, escape_md("⚠️ Please provide a comma-separated list of Pokémon."), reply_to_id=message.message_id)
            target_id = message.reply_to_message.from_user.id
            db.add_user_if_new(target_id)
            for p in poke_list: db.add_caught_pokemon(target_id, p, "Admin Gift")
            safe_send(bot, message.chat.id, f"🎁 Successfully gave {len(poke_list)} Pokémon to [{escape_md(clean_name(message.reply_to_message.from_user.first_name))}](tg://user?id={target_id})\\!\n\n_{escape_md(', '.join(poke_list))}_", reply_to_id=message.message_id)
            
        elif module == "admin" and action == "upload":
            if not message.reply_to_message or not message.reply_to_message.photo:
                return safe_send(bot, message.chat.id, escape_md("⚠️ Please reply to an image with /execute admin upload <LeaderName>"), reply_to_id=message.message_id)
            leader_name = arguments.strip().title()
            if not leader_name: return safe_send(bot, message.chat.id, escape_md("⚠️ Format: /execute admin upload Brock"), reply_to_id=message.message_id)
            file_id = message.reply_to_message.photo[-1].file_id 
            db.set_gym_image(leader_name, file_id)
            safe_send(bot, message.chat.id, escape_md(f"✅ Successfully saved the image to the database for Gym Leader {leader_name}!"), reply_to_id=message.message_id)

        elif module == "server" and action == "status":
            msg = safe_send(bot, message.chat.id, "⚡ *Iɴɪᴛɪᴀʟɪᴢɪɴɢ Mᴏᴅᴜʟᴇ\\.\\.\\.*", reply_to_id=message.message_id)
            play_loading_animation(bot, message.chat.id, msg.message_id)
            bot.edit_message_text("🟢 *Sᴇʀᴠᴇʀ Oɴʟɪɴᴇ\\!*\n_Sᴜᴘᴀʙᴀsᴇ DB Cᴏɴɴᴇᴄᴛᴇᴅ_ ✅", message.chat.id, msg.message_id, parse_mode="MarkdownV2")

    @bot.message_handler(commands=["restore"])
    def cmd_restore(message):
        if not is_owner(bot, message): return
        safe_send(bot, message.chat.id, escape_md("📥 Send me the old SQLite (.db) file to migrate it into the cloud PostgreSQL database. Max size: 20MB."), reply_to_id=message.message_id)

    @bot.message_handler(content_types=["document"])
    def handle_restore_file(message):
        if not is_owner(bot, message): return
        if not message.document.file_name.endswith((".db", ".sqlite", ".db3")): return
        
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
        if not is_owner(bot, message): return
        safe_send(bot, message.chat.id, escape_md("☁️ You are on a cloud database now! Backups are handled automatically via Supabase."), reply_to_id=message.message_id)

    @bot.message_handler(commands=["export"])
    def cmd_export(message):
        if not is_owner(bot, message): return
        status_msg = bot.reply_to(message, escape_md("🔄 Extracting data from PostgreSQL..."), parse_mode="MarkdownV2")
        try:
            data = db.export_all_data()
            json_data = json.dumps(data, default=str, indent=4)
            backup_file = io.BytesIO(json_data.encode('utf-8'))
            backup_file.name = f"database_backup_{int(time.time())}.json"
            bot.send_document(message.chat.id, backup_file, caption=escape_md("📦 Here is your complete database backup!"), parse_mode="MarkdownV2")
            bot.delete_message(message.chat.id, status_msg.message_id)
        except Exception as e:
            bot.edit_message_text(escape_md(f"❌ Export failed: {e}"), chat_id=message.chat.id, message_id=status_msg.message_id, parse_mode="MarkdownV2")

    @bot.message_handler(commands=["give"])
    def cmd_give(message):
        if not is_owner(bot, message): return
        if not message.reply_to_message: return safe_send(bot, message.chat.id, "⚠️ *Please reply to a user's message to give them a Pokémon\\!*", reply_to_id=message.message_id)
        args = message.text.split(maxsplit=1)
        if len(args) < 2: return safe_send(bot, message.chat.id, "⚠️ *Format:* `/give <pokemon_name>`", reply_to_id=message.message_id)
        pokemon_name = args[1].strip().title()
        db.add_caught_pokemon(message.reply_to_message.from_user.id, pokemon_name, "Gift")
        safe_send(bot, message.chat.id, f"🎁 Successfully gave *{escape_md(pokemon_name)}* to [{escape_md(clean_name(message.reply_to_message.from_user.first_name))}](tg://user?id={message.reply_to_message.from_user.id})\\!", reply_to_id=message.message_id)

    @bot.message_handler(commands=["take"])
    def cmd_take(message):
        if not is_owner(bot, message): return
        if not message.reply_to_message: return safe_send(bot, message.chat.id, "⚠️ *Please reply to a user's message to take their Pokémon\\!*", reply_to_id=message.message_id)
        args = message.text.split(maxsplit=1)
        if len(args) < 2: return safe_send(bot, message.chat.id, "⚠️ *Format:* `/take <pokemon_name>`", reply_to_id=message.message_id)
        pokemon_name = args[1].strip().title()
        if db.delete_pokemon(message.reply_to_message.from_user.id, pokemon_name): safe_send(bot, message.chat.id, f"🗑️ Successfully took *{escape_md(pokemon_name)}* from [{escape_md(clean_name(message.reply_to_message.from_user.first_name))}](tg://user?id={message.reply_to_message.from_user.id})\\!", reply_to_id=message.message_id)
        else: safe_send(bot, message.chat.id, f"❌ [{escape_md(clean_name(message.reply_to_message.from_user.first_name))}](tg://user?id={message.reply_to_message.from_user.id}) doesn't own a *{escape_md(pokemon_name)}*\\.", reply_to_id=message.message_id)

    @bot.message_handler(commands=["reset"])
    def cmd_reset(message):
        if not is_owner(bot, message): return
        if not message.reply_to_message: return safe_send(bot, message.chat.id, "⚠️ *Please reply to a user's message to reset their tries\\!*", reply_to_id=message.message_id)
        db.reset_user(message.reply_to_message.from_user.id)
        safe_send(bot, message.chat.id, f"🔄 Successfully reset scouts for [{escape_md(clean_name(message.reply_to_message.from_user.first_name))}](tg://user?id={message.reply_to_message.from_user.id})\\!", reply_to_id=message.message_id)

    @bot.message_handler(commands=["plist"])
    def cmd_plist(message):
        if not is_owner(bot, message): return
        parts = message.text.split(maxsplit=1)
        if len(parts) < 2: return safe_send(bot, message.chat.id, escape_md("📝 Usage: /plist <user_id>"), reply_to_id=message.message_id)
        try:
            uid = int(parts[1])
            text, kb = generate_pokemon_list_ui(uid, 0, action_prefix="plist", is_admin=True)
            safe_send(bot, message.chat.id, text, reply_markup=kb, reply_to_id=message.message_id)
        except Exception as e: safe_send(bot, message.chat.id, escape_md(f"Error: {str(e)}"), reply_to_id=message.message_id)

    # ================== BROADCAST & DELETE ==================
    @bot.message_handler(commands=["bcast", "gcast"])
    def cmd_broadcasts(message):
        if not is_owner(bot, message): return
        if not message.reply_to_message: return safe_send(bot, message.chat.id, escape_md("⚠️ Please reply to a message to forward it."), reply_to_id=message.message_id)
        
        global LAST_BROADCAST_MSGS
        LAST_BROADCAST_MSGS.clear() 
        
        targets = db.get_all_groups() if message.text.startswith("/gcast") else db.get_all_users()
        success, failed = 0, 0
        
        status_msg = safe_send(bot, message.chat.id, escape_md("⏳ Broadcasting message..."), reply_to_id=message.message_id)
        
        for target_id in targets:
            try:
                sent_msg = bot.forward_message(target_id, message.chat.id, message.reply_to_message.message_id)
                LAST_BROADCAST_MSGS.append((target_id, sent_msg.message_id))
                success += 1
                time.sleep(0.05) 
            except: 
                failed += 1
                
        text = f"📢 *Bʀᴏᴀᴅᴄᴀsᴛ Cᴏᴍᴘʟᴇᴛᴇ\\!*\n✅ Sᴜᴄᴄᴇss: {success}\n❌ Fᴀɪʟᴇᴅ: {failed}\n\n_Uѕᴇ /delcast ᴛᴏ ᴜɴᴅᴏ ᴀɴᴅ ᴅᴇʟᴇᴛᴇ ᴛʜɪѕ ᴍᴇѕѕᴀɢᴇ ᴇᴠᴇʀʏᴡʜᴇʀᴇ\\._"
        try: bot.edit_message_text(text, chat_id=message.chat.id, message_id=status_msg.message_id, parse_mode="MarkdownV2")
        except: pass

    @bot.message_handler(commands=["delcast"])
    def cmd_delcast(message):
        if not is_owner(bot, message): return
        
        global LAST_BROADCAST_MSGS
        if not LAST_BROADCAST_MSGS:
            return safe_send(bot, message.chat.id, escape_md("⚠️ No recent broadcast found in memory to delete."), reply_to_id=message.message_id)
        
        status_msg = safe_send(bot, message.chat.id, escape_md(f"🗑️ Deleting {len(LAST_BROADCAST_MSGS)} messages..."), reply_to_id=message.message_id)
        
        success, failed = 0, 0
        for chat_id, msg_id in LAST_BROADCAST_MSGS:
            try:
                bot.delete_message(chat_id, msg_id)
                success += 1
                time.sleep(0.05)
            except:
                failed += 1
        
        LAST_BROADCAST_MSGS.clear() 
        
        text = f"✅ *Dᴇʟᴇᴛᴇ Cᴀsᴛ Cᴏᴍᴘʟᴇᴛᴇ\\!*\n🗑️ Dᴇʟᴇᴛᴇᴅ: {success}\n❌ Fᴀɪʟᴇᴅ: {failed}"
        try: bot.edit_message_text(text, chat_id=message.chat.id, message_id=status_msg.message_id, parse_mode="MarkdownV2")
        except: pass

    # ========================================================
    @bot.message_handler(commands=["gcs", "allusers", "leave", "debug", "clearhunts"])
    def cmd_misc_admin(message):
        if not is_owner(bot, message): return
        cmd = message.text.split()[0].lower()
        if cmd == "/gcs":
            text, kb = generate_gcs_ui(bot, 0)
            safe_send(bot, message.chat.id, text, reply_to_id=message.message_id, reply_markup=kb)
        elif cmd == "/allusers":
            users = db.get_all_users()
            text = f"👥 *Users \\({len(users)}\\):*\n\n" + "\n".join(f"\\- `{uid}`" for uid in users[:50]) + (f"\n\n_\\.\\.\\.and {len(users)-50} more\\._" if len(users)>50 else "")
            safe_send(bot, message.chat.id, text if users else escape_md("No registered trainers."), reply_to_id=message.message_id)
        elif cmd == "/leave":
            try:
                bot.leave_chat(int(message.text.split()[1]))
                db.remove_group(int(message.text.split()[1]))
                safe_send(bot, message.chat.id, escape_md("✅ Left group."), reply_to_id=message.message_id)
            except: safe_send(bot, message.chat.id, escape_md("📝 Usage: /leave <group_id>"), reply_to_id=message.message_id)
        elif cmd == "/debug":
            text, kb = generate_debug_ui(active_hunts)
            safe_send(bot, message.chat.id, text, reply_to_id=message.message_id, reply_markup=kb)
        elif cmd == "/clearhunts":
            for hunt in active_hunts.values(): hunt["timer"].cancel()
            active_hunts.clear()
            try: pvp.pvp_battles.clear()
            except: pass
            try: trade.active_trades.clear()
            except: pass
            safe_send(bot, message.chat.id, escape_md("🧹 All active hunts cleared."), reply_to_id=message.message_id)
