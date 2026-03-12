# tasks.py
from telebot import types
import database as db
import time
import random
from api_utils import escape_md, fetch_random_pokemon_id_and_name_sync

def to_small_caps(text):
    """Converts regular text into the premium small-caps font."""
    small_caps_map = {
        'a': 'ᴀ', 'b': 'ʙ', 'c': 'ᴄ', 'd': 'ᴅ', 'e': 'ᴇ', 'f': 'ғ', 'g': 'ɢ',
        'h': 'ʜ', 'i': 'ɪ', 'j': 'ᴊ', 'k': 'ᴋ', 'l': 'ʟ', 'm': 'ᴍ', 'n': 'ɴ',
        'o': 'ᴏ', 'p': 'ᴘ', 'q': 'ǫ', 'r': 'ʀ', 's': 's', 't': 'ᴛ', 'u': 'ᴜ',
        'v': 'ᴠ', 'w': 'ᴡ', 'x': 'x', 'y': 'ʏ', 'z': 'ᴢ'
    }
    return "".join(char if char.isupper() else small_caps_map.get(char.lower(), char) for char in text)

def check_and_update_catch(user_id, pokemon_name):
    """Called automatically from main.py when a pokemon is caught to update tasks."""
    try:
        db.update_task_catch(user_id)
        db.update_task_specific_catch(user_id, pokemon_name)
    except Exception as e:
        pass # Silently ignore so it never interrupts the catch animation

def render_tasks_ui(bot, chat_id, user_id, message_id=None):
    tasks_list = db.get_daily_tasks(user_id)
    
    if not tasks_list:
        text = "❌ *Nᴏ ᴛᴀsᴋs ᴀᴠᴀɪʟᴀʙʟᴇ ᴛᴏᴅᴀʏ\\.*"
        if message_id:
            try: bot.edit_message_text(text, chat_id, message_id, parse_mode="MarkdownV2")
            except: pass
        else:
            bot.send_message(chat_id, text, parse_mode="MarkdownV2")
        return

    text = "📋 *Yᴏᴜʀ Dᴀɪʟʏ Mɪssɪᴏɴs*\n━━━━━━━━━━━━━━\n\n"
    kb = types.InlineKeyboardMarkup(row_width=3)
    buttons = []

    for i, t in enumerate(tasks_list):
        t_type = t['task_type']
        target = t['target']
        prog = t['progress']
        goal = t['goal']
        completed = t['completed']

        # Cap the visual progress so it doesn't show 15/10
        display_prog = min(prog, goal)

        # Format dynamic descriptions
        if t_type == 'catch': desc = f"Cᴀᴛᴄʜ {goal} Pᴏᴋᴇ́ᴍᴏɴ"
        elif t_type == 'pvp': desc = f"Wɪɴ {goal} PᴠP Bᴀᴛᴛʟᴇs"
        elif t_type == 'catch_specific': desc = f"Cᴀᴛᴄʜ ᴀ {target}"
        else: desc = "Uɴᴋɴᴏᴡɴ Mɪssɪᴏɴ"

        status_icon = "✅" if completed else ("⏳" if prog >= goal else "🏃")
        text += f"*{i+1}\\. {escape_md(to_small_caps(desc))}* {status_icon}\n"
        text += f"  └ Pʀᴏɢʀᴇss: {display_prog}/{goal}\n"
        
        if not completed:
            text += f"  └ Rᴇᴡᴀʀᴅ: {t['reward_amount']} {escape_md(to_small_caps(t['reward_type']).title())}\n\n"
        else:
            text += "  └ Rᴇᴡᴀʀᴅ: Cʟᴀɪᴍᴇᴅ\\!\n\n"

        # Interactive Button logic
        if completed:
            buttons.append(types.InlineKeyboardButton(f"✅ {i+1}", callback_data="ignore"))
        elif prog >= goal:
            buttons.append(types.InlineKeyboardButton(f"🎁 Cʟᴀɪᴍ {i+1}", callback_data=f"task_claim_{user_id}_{t_type}"))
        else:
            buttons.append(types.InlineKeyboardButton(f"❌ {i+1}", callback_data="ignore"))

    # Neatly format buttons
    if len(buttons) == 3:
        kb.row(*buttons)
    else:
        for b in buttons: kb.add(b)
        
    kb.row(types.InlineKeyboardButton("🌀 Rᴇғʀᴇsʜ Mɪssɪᴏɴs", callback_data=f"task_refresh_{user_id}"))

    if message_id:
        try: bot.edit_message_text(text, chat_id, message_id, reply_markup=kb, parse_mode="MarkdownV2")
        except Exception as e: pass
    else:
        bot.send_message(chat_id, text, reply_markup=kb, parse_mode="MarkdownV2")

def handle_task_callback(bot, call):
    parts = call.data.split("_")
    
    if parts[1] == "refresh":
        owner_id = int(parts[2])
        if call.from_user.id != owner_id:
            return bot.answer_callback_query(call.id, "❌ Not your tasks!", show_alert=True)
            
        bot.answer_callback_query(call.id, "🔄 Refreshing tasks...")
        render_tasks_ui(bot, call.message.chat.id, owner_id, call.message.message_id)
        return

    if parts[1] == "claim":
        owner_id = int(parts[2])
        if call.from_user.id != owner_id:
            return bot.answer_callback_query(call.id, "❌ Not your tasks!", show_alert=True)
            
        task_type = parts[3]
        reward = db.claim_task_reward(owner_id, task_type)

        if reward:
            r_type, r_amount = reward
            
            # --- AUTOMATED REWARD DISTRIBUTION LOGIC ---
            if r_type == 'shiny':
                # Give them a random strong Pokemon
                poke_id, name, base_id = fetch_random_pokemon_id_and_name_sync("Galar") 
                if not name: name = "Mewtwo"
                db.add_caught_pokemon(owner_id, name.title(), "Task Reward")
                bot.answer_callback_query(call.id, f"🎉 Claimed! You received a ✨ {name.title()}!", show_alert=True)
                
            elif r_type == 'jackpot':
                # Legendary Jackpot for specific catches
                db.add_caught_pokemon(owner_id, "Arceus", "Task Reward")
                bot.answer_callback_query(call.id, f"🎰 JACKPOT! You received a ✨ Arceus!", show_alert=True)
                
            else:
                bot.answer_callback_query(call.id, f"🎉 You claimed {r_amount} {r_type}!", show_alert=True)
            
            # Re-render UI instantly to show it has been claimed
            render_tasks_ui(bot, call.message.chat.id, owner_id, call.message.message_id)
        else:
            bot.answer_callback_query(call.id, "⚠️ This task is not finished or already claimed!", show_alert=True)
