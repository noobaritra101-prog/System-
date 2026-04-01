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
import gym  # 🏅 NEW: Import the Gym module!

from api_utils import escape_md

# Setup File Logging for /log command
file_handler = logging.FileHandler('bot.log')
file_handler.setFormatter(logging.Formatter('%(asctime)s - %(levelname)s - %(message)s'))
logger.addHandler(file_handler)

bot = telebot.TeleBot(BOT_TOKEN, parse_mode="MarkdownV2")
active_hunts = {}  

# Initialize Handlers from modules
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
        # Route to admin module first. If it handled it, stop processing.
        if admin.handle_admin_callback(bot, call, active_hunts): return
            
        # Route logic
        if call.data.startswith("tr_"): return trade.handle_trade_callback(bot, call)
        elif call.data == "ignore": return bot.answer_callback_query(call.id)
        elif call.data.startswith("pvp_"): return pvp.handle_pvp_callback(bot, call)
        elif call.data.startswith("task"): return tasks.handle_task_callback(bot, call)
        elif call.data.startswith("gym_"): return gym.handle_gym_callback(bot, call) # 🏅 NEW: Route Gym clicks!
        
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

        # --- RELEASE CONFIRMATION ROUTING ---
        elif call.data.startswith("relc_"):
            parts = call.data.split("_", 3)
            action, uid, name = parts[1], int(parts[2]), parts[3]
            
            if call.from_user.id != uid: 
                return bot.answer_callback_query(call.id, "❌ Not your Pokémon!", show_alert=True)
            
            if action == "N":
                bot.answer_callback_query(call.id, "Release Cancelled.")
                try: bot.delete_message(call.message.chat.id, call.message.message_id)
                except: pass
                return
                
            if action == "Y":
                bot.answer_callback_query(call.id, "Releasing...")
                if db.delete_pokemon(uid, name):
                    small_name = commands.to_small_caps(name.title())
                    text = f"🌿 *{escape_md(small_name)} Wᴀs Rᴇʟᴇᴀsᴇᴅ Bᴀᴄᴋ Iɴᴛᴏ Tʜᴇ Wɪʟᴅ\\.*"
                    try: bot.edit_message_text(text, call.message.chat.id, call.message.message_id, parse_mode="MarkdownV2")
                    except: pass
                else:
                    try: bot.edit_message_text(escape_md(f"❌ You don't have a {name.title()}."), call.message.chat.id, call.message.message_id, parse_mode="MarkdownV2")
                    except: pass

        # --- DID YOU MEAN ENGINE ROUTING ---
        elif call.data.startswith("dym_dex_"):
            parts = call.data.split("_", 3)
            uid, name = int(parts[2]), parts[3]
            if call.from_user.id != uid: return bot.answer_callback_query(call.id, "❌ Not your menu!", show_alert=True)
            bot.answer_callback_query(call.id, "Loading Pokédex...")
            try: bot.delete_message(call.message.chat.id, call.message.message_id)
            except: pass
            
            text = commands.get_dex_text(name, "info")
            poke_id = commands.get_pokemon_id_sync(name)
            img_url = commands.official_shiny_artwork_url(poke_id)
            kb = types.InlineKeyboardMarkup(row_width=2).add(types.InlineKeyboardButton("✅ ℹ️ Info", callback_data="ignore"), types.InlineKeyboardButton("📊 Stats", callback_data=f"dex_stats_{name}"))
            try: bot.send_photo(call.message.chat.id, img_url, caption=text, reply_markup=kb, parse_mode="MarkdownV2")
            except: pass

        elif call.data.startswith("dym_ins_"):
            parts = call.data.split("_", 3)
            uid, name = int(parts[2]), parts[3]
            if call.from_user.id != uid: return bot.answer_callback_query(call.id, "❌ Not your menu!", show_alert=True)
            bot.answer_callback_query(call.id, "Inspecting...")
            try: bot.delete_message(call.message.chat.id, call.message.message_id)
            except: pass
            
            poke_id = commands.get_pokemon_id_sync(name)
            if poke_id:
                try: bot.send_photo(call.message.chat.id, commands.official_shiny_artwork_url(poke_id), caption=f"✨ *{escape_md(name.title())}* \\(Shiny\\)", parse_mode="MarkdownV2")
                except: pass

        elif call.data.startswith("dym_rel_"):
            parts = call.data.split("_", 3)
            uid, name = int(parts[2]), parts[3].title()
            if call.from_user.id != uid: return bot.answer_callback_query(call.id, "❌ Not your menu!", show_alert=True)
            bot.answer_callback_query(call.id, "")
            
            small_name = commands.to_small_caps(name)
            text = (f"⚠️ *Cᴏɴғɪʀᴍ Rᴇʟᴇᴀsᴇ*\n\n"
                    f"*Aʀᴇ Yᴏᴜ Sᴜʀᴇ Yᴏᴜ Wᴀɴᴛ Tᴏ Rᴇʟᴇᴀsᴇ*\n"
                    f"*{escape_md(small_name)}?*\n\n"
                    f"*Tʜɪs Aᴄᴛɪᴏɴ Cᴀɴɴᴏᴛ Bᴇ Uɴᴅᴏɴᴇ\\.*")
            
            kb = types.InlineKeyboardMarkup(row_width=2)
            kb.add(
                types.InlineKeyboardButton("✅ Cᴏɴғɪʀᴍ", callback_data=f"relc_Y_{uid}_{name[:32]}"),
                types.InlineKeyboardButton("❌ Cᴀɴᴄᴇʟ", callback_data=f"relc_N_{uid}_{name[:32]}")
            )
            
            try: bot.edit_message_text(text, call.message.chat.id, call.message.message_id, reply_markup=kb, parse_mode="MarkdownV2")
            except: pass
        
        # --- DYNAMIC LEADERBOARD ROUTING ---
        elif call.data.startswith("flex_"):
            parts = call.data.split("_")
            mode = parts[1] 
            owner_id = int(parts[2])
            
            if call.from_user.id != owner_id: 
                return bot.answer_callback_query(call.id, "❌ You cannot use someone else's flex menu!", show_alert=True)
                
            bot.answer_callback_query(call.id, "🔄 Refreshing Leaderboard...")
            return commands.send_leaderboard(bot, call.message.chat.id, owner_id, call.message.message_id, mode)
        
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
            
            hunt_data = active_hunts.pop(call.message.message_id, None)
            if not hunt_data: return bot.answer_callback_query(call.id, "💨 The Pokémon already fled!", show_alert=True)
            
            try: bot.answer_callback_query(call.id, "")
            except: pass
            
            if "timer" in hunt_data: hunt_data["timer"].cancel()
            
            catcher_id = call.from_user.id
            db.add_user_if_new(catcher_id)
            db.add_caught_pokemon(catcher_id, name.title(), "Event")
            try: tasks.check_and_update_catch(catcher_id, name.title())
            except: pass
            
            try: bot.edit_message_caption(caption=f"🎉 *{escape_md(commands.clean_name(call.from_user.first_name))}* was the fastest and caught the ✨ *{escape_md(name.title())}*\\!", chat_id=call.message.chat.id, message_id=call.message.message_id, parse_mode="MarkdownV2")
            except: pass

        elif call.data.startswith("catch_"):
            parts = call.data.split("_", 3)
            uid, pid, name = int(parts[1]), int(parts[2]), parts[3]
            if call.from_user.id != uid: return bot.answer_callback_query(call.id, "Hands off! This scout is not yours.")
            
            hunt_data = active_hunts.pop(call.message.message_id, None)
            if not hunt_data: return bot.answer_callback_query(call.id, "💨 The Pokémon already fled!", show_alert=True)
            
            try: bot.answer_callback_query(call.id, "")
            except: pass
            
            if "timer" in hunt_data: hunt_data["timer"].cancel()
            threading.Thread(target=commands.process_catch, args=(bot, call, uid, pid, name)).start()

        elif call.data.startswith("run_"):
            parts = call.data.split("_", 2)
            uid, name = int(parts[1]), parts[2]
            if call.from_user.id != uid: return bot.answer_callback_query(call.id, "This scout is not yours.")
            
            hunt_data = active_hunts.pop(call.message.message_id, None)
            if not hunt_data: return bot.answer_callback_query(call.id, "💨 The Pokémon already fled!", show_alert=True)
            
            try: bot.answer_callback_query(call.id, "")
            except: pass
            
            if "timer" in hunt_data: hunt_data["timer"].cancel()
            try: bot.edit_message_caption(caption=f"💨 Tʜᴇ Wɪʟᴅ ✨ {escape_md(commands.to_small_caps(name.title()))} Fʟᴇᴅ\\!", chat_id=call.message.chat.id, message_id=call.message.message_id, parse_mode="MarkdownV2")
            except: pass

        elif call.data.startswith("mypoke_") or call.data.startswith("plist_"):
            parts = call.data.split("_")
            action, uid, page_idx = parts[0], int(parts[1]), int(parts[2])
            
            if action == "mypoke" and call.from_user.id != uid: return bot.answer_callback_query(call.id, "This is not your bag.")
            if action == "plist" and not admin.is_owner(bot, call): return
            
            text, kb = commands.generate_pokemon_list_ui(uid, page_idx, action_prefix=action, is_admin=(action=="plist"))
            
            try: bot.edit_message_text(text, call.message.chat.id, call.message.message_id, reply_markup=kb, parse_mode="MarkdownV2")
            except Exception as e:
                err_msg = str(e).lower()
                if "message is not modified" not in err_msg:
                    if "429" in err_msg or "too many requests" in err_msg:
                        time.sleep(1.5)
                        try: bot.edit_message_text(text, call.message.chat.id, call.message.message_id, reply_markup=kb, parse_mode="MarkdownV2")
                        except: pass

    except KeyError:
        # 🛡️ ULTIMATE ANTI-CRASH SHIELD
        pass
    except Exception as e: 
        logger.error(f"Callback error: {e}")

# ================== RUN ==================
if __name__ == "__main__":
    db.init_db()
    logger.info("Bot is starting...")
    bot.delete_webhook()
    bot.infinity_polling(skip_pending=True)
