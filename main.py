# main.py
# -*- coding: utf-8 -*-
import telebot
from telebot import types
import time
import threading
import logging

from config import BOT_TOKEN, OWNER_ID, logger
import database as db
import pvp 
import tasks 
import trade 
import commands 
import admin 

from api_utils import escape_md

# Setup File Logging for /log command
file_handler = logging.FileHandler('bot.log')
file_handler.setFormatter(logging.Formatter('%(asctime)s - %(levelname)s - %(message)s'))
logger.addHandler(file_handler)

bot = telebot.TeleBot(BOT_TOKEN, parse_mode="MarkdownV2")
active_hunts = {}  

# Initialize Handlers
commands.register_user_handlers(bot, active_hunts)
admin.register_admin_handlers(bot, active_hunts)

# ================== GROUP TRACKING ==================
@bot.chat_member_handler()
def handle_chat_member_update(update):
    new_status = update.new_chat_member.status
    if new_status in ["member", "administrator"] and update.chat.type in ["group", "supergroup"]:
        db.add_group(update.chat.id)
    elif new_status in ["kicked", "left"]:
        db.remove_group(update.chat.id)

# ================== MASTER CALLBACK ROUTER ==================
@bot.callback_query_handler(func=lambda c: True)
def cb_handler(call):
    try:
        # Route to admin module if handled
        if admin.handle_admin_callback(bot, call): return
            
        # Route logic
        if call.data.startswith("tr_"): return trade.handle_trade_callback(bot, call)
        elif call.data == "ignore": return bot.answer_callback_query(call.id)
        elif call.data.startswith("pvp_"): return pvp.handle_pvp_callback(bot, call)
        elif call.data.startswith("task"): return tasks.handle_task_callback(bot, call)
        
        elif call.data.startswith("dex_"):
            parts = call.data.split("_", 2)
            page = parts[1]
            name = parts[2]
            text = commands.get_dex_text(name, page)
            if text:
                kb = types.InlineKeyboardMarkup(row_width=2)
                if page == "info": kb.add(types.InlineKeyboardButton("✅ ℹ️ Info", callback_data="ignore"), types.InlineKeyboardButton("📊 Stats", callback_data=f"dex_stats_{name}"))
                else: kb.add(types.InlineKeyboardButton("ℹ️ Info", callback_data=f"dex_info_{name}"), types.InlineKeyboardButton("✅ 📊 Stats", callback_data="ignore"))
                try: bot.edit_message_caption(caption=text, chat_id=call.message.chat.id, message_id=call.message.message_id, reply_markup=kb, parse_mode="MarkdownV2")
                except: pass
            return

        elif call.data.startswith("refresh_flex_"):
            owner_id = int(call.data.split("_")[2])
            if call.from_user.id != owner_id: return bot.answer_callback_query(call.id, "❌ You cannot refresh someone else's flex menu!", show_alert=True)
            bot.answer_callback_query(call.id, "🔄 Refreshing Leaderboard...")
            return commands.send_leaderboard(bot, call.message.chat.id, owner_id, call.message.message_id)
        
        elif call.data.startswith("travel_cancel_"):
            if call.from_user.id != int(call.data.split("_")[2]): return bot.answer_callback_query(call.id, "Not your menu.")
            try: bot.delete_message(call.message.chat.id, call.message.message_id)
            except: pass
            return
            
        elif call.data.startswith("travel_"):
            uid, region = int(call.data.split("_")[1]), call.data.split("_")[2]
            if call.from_user.id != uid: return bot.answer_callback_query(call.id, "Not your menu.")
            db.update_user_region(uid, region)
            try: bot.edit_message_text(f"✈️ Tʀᴀᴠᴇʟʟᴇᴅ ᴛᴏ *{escape_md(commands.to_small_caps(region))}*\\.", call.message.chat.id, call.message.message_id, parse_mode="MarkdownV2")
            except: pass

        elif call.data.startswith("gcatch_"):
            parts = call.data.split("_", 2)
            pid, name = int(parts[1]), parts[2]
            if call.message.message_id not in active_hunts: return bot.answer_callback_query(call.id, "💨 The Pokémon already fled!", show_alert=True)
            try: bot.answer_callback_query(call.id, "")
            except: pass
            hunt_data = active_hunts.pop(call.message.message_id, None)
            if hunt_data and "timer" in hunt_data: hunt_data["timer"].cancel()
            catcher_id = call.from_user.id
            db.add_user_if_new(catcher_id)
            db.add_caught_pokemon(catcher_id, name.title(), "Event")
            try: tasks.check_and_update_catch(catcher_id, name.title())
            except: pass
            try: bot.edit_message_caption(caption=f"🎉 *{escape_md(call.from_user.first_name)}* was the fastest and caught the ✨ *{escape_md(name.title())}*\\!", chat_id=call.message.chat.id, message_id=call.message.message_id, parse_mode="MarkdownV2")
            except: pass

        elif call.data.startswith("catch_"):
            parts = call.data.split("_", 3)
            uid, pid, name = int(parts[1]), int(parts[2]), parts[3]
            if call.from_user.id != uid: return bot.answer_callback_query(call.id, "Hands off! This scout is not yours.")
            if call.message.message_id not in active_hunts: return bot.answer_callback_query(call.id, "💨 The Pokémon already fled!", show_alert=True)
            try: bot.answer_callback_query(call.id, "")
            except: pass
            active_hunts.pop(call.message.message_id)["timer"].cancel()
            threading.Thread(target=commands.process_catch, args=(bot, call, uid, pid, name)).start()

        elif call.data.startswith("run_"):
            uid, name = int(call.data.split("_")[1]), call.data.split("_")[2]
            if call.from_user.id != uid: return bot.answer_callback_query(call.id, "This scout is not yours.")
            if call.message.message_id not in active_hunts: return bot.answer_callback_query(call.id, "💨 The Pokémon already fled!", show_alert=True)
            try: bot.answer_callback_query(call.id, "")
            except: pass
            active_hunts.pop(call.message.message_id)["timer"].cancel()
            try: bot.edit_message_caption(caption=f"💨 Tʜᴇ Wɪʟᴅ ✨ {escape_md(commands.to_small_caps(name.title()))} Fʟᴇᴅ\\!", chat_id=call.message.chat.id, message_id=call.message.message_id, parse_mode="MarkdownV2")
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
            try: bot.edit_message_text(text, call.message.chat.id, call.message.message_id, reply_markup=kb if len(pages)>1 else None, parse_mode="MarkdownV2")
            except Exception as e:
                err_msg = str(e).lower()
                if "message is not modified" not in err_msg:
                    if "429" in err_msg or "too many requests" in err_msg:
                        time.sleep(1.5)
                        try: bot.edit_message_text(text, call.message.chat.id, call.message.message_id, reply_markup=kb if len(pages)>1 else None, parse_mode="MarkdownV2")
                        except: pass

    except Exception as e: logger.error(f"Callback error: {e}")

# ================== RUN ==================
if __name__ == "__main__":
    db.init_db()
    logger.info("Bot is starting...")
    bot.delete_webhook()
    bot.infinity_polling(skip_pending=True)
