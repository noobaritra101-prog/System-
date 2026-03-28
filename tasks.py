# tasks.py
import threading
import random
from telebot import types
import database as db
from api_utils import escape_md

def to_small_caps(text):
    small_caps_map = {
        'a': 'ᴀ', 'b': 'ʙ', 'c': 'ᴄ', 'd': 'ᴅ', 'e': 'ᴇ', 'f': 'ғ', 'g': 'ɢ',
        'h': 'ʜ', 'i': 'ɪ', 'j': 'ᴊ', 'k': 'ᴋ', 'l': 'ʟ', 'm': 'ᴍ', 'n': 'ɴ',
        'o': 'ᴏ', 'p': 'ᴘ', 'q': 'ǫ', 'r': 'ʀ', 's': 's', 't': 'ᴛ', 'u': 'ᴜ',
        'v': 'ᴠ', 'w': 'ᴡ', 'x': 'x', 'y': 'ʏ', 'z': 'ᴢ'
    }
    return "".join(char if char.isupper() else small_caps_map.get(char.lower(), char) for char in text)

def safe_answer(bot, call_id, text, show_alert=False):
    try: bot.answer_callback_query(call_id, text, show_alert=show_alert)
    except: pass

def render_tasks_ui(bot, chat_id, user_id, message_id=None):
    def process_ui(msg_id):
        tasks_list = db.get_daily_tasks(user_id)
        
        if not tasks_list:
            try: bot.edit_message_text("❌ No tasks available today.", chat_id, msg_id)
            except: pass
            return

        # Extract the 3 tasks from the new database format
        catch_task = next((t for t in tasks_list if t['task_type'] == 'catch'), None)
        pvp_task = next((t for t in tasks_list if t['task_type'] == 'pvp'), None)
        spec_task = next((t for t in tasks_list if t['task_type'] == 'catch_specific'), None)

        # 1. Cap progress
        spec_done = 1 if spec_task['progress'] >= spec_task['goal'] else 0
        pvp_done = min(pvp_task['progress'], pvp_task['goal'])
        catch_done = min(catch_task['progress'], catch_task['goal'])
        
        # 2. Calculate percentages (3 tasks = 33.3% each)
        spec_pct = 33.4 if spec_done else 0
        pvp_pct = (pvp_done / pvp_task['goal']) * 33.3 if pvp_task['goal'] > 0 else 33.3
        catch_pct = (catch_done / catch_task['goal']) * 33.3 if catch_task['goal'] > 0 else 33.3
        
        total_pct = int(spec_pct + pvp_pct + catch_pct)
        if total_pct > 99: total_pct = 100
        
        # 3. Generate visual progress bar (10 blocks total)
        filled_blocks = int(total_pct / 10)
        empty_blocks = 10 - filled_blocks
        progress_bar = "▰" * filled_blocks + "▱" * empty_blocks
        
        # 4. Generate Task Icons
        spec_icon = "✅" if spec_done else "☒"
        pvp_icon = "✅" if pvp_done >= pvp_task['goal'] else "☒"
        catch_icon = "✅" if catch_done >= catch_task['goal'] else "☒"
        
        # 5. Build the Sleek UI Text
        text = (
            "━━━━━━━━━━━━━━\n"
            f"📅 *{to_small_caps('Your Daily Tasks')}*\n"
            "━━━━━━━━━━━━━━\n"
            f"• Cᴀᴛᴄʜ ᴀ ᴡɪʟᴅ {escape_md(to_small_caps(spec_task['target']))} 【{spec_icon}】\n"
            f"• Wɪɴ {pvp_task['goal']} PᴠP ᴍᴀᴛᴄʜ{'ᴇs' if pvp_task['goal']>1 else ''} \\({pvp_done}/{pvp_task['goal']}\\) 【{pvp_icon}】\n"
            f"• Cᴀᴛᴄʜ {catch_task['goal']} Pᴏᴋᴇ́ᴍᴏɴ \\({catch_done}/{catch_task['goal']}\\) 【{catch_icon}】\n"
            "━━━━━━━━━━━━━━\n"
            f"🎁 *Rᴇᴡᴀʀᴅ:* ✨ Sʜɪɴʏ Mʏsᴛᴇʀʏ Bᴏx"
        )
        
        # 6. Build the Buttons
        all_claimed = all(t['completed'] for t in tasks_list)
        
        kb = types.InlineKeyboardMarkup(row_width=2)
        
        # 📍 The new Progress Bar button now uses "prog" instead of "refresh"
        btn_progress = types.InlineKeyboardButton(f"{progress_bar} 【{total_pct}%】", callback_data=f"task_prog_{user_id}_{total_pct}")
        
        btn_refresh = types.InlineKeyboardButton("Rᴇғʀᴇsʜ 🌀", callback_data=f"task_refresh_{user_id}")
        
        if all_claimed:
            btn_claim = types.InlineKeyboardButton("Cʟᴀɪᴍᴇᴅ ✅", callback_data=f"task_claim_{user_id}")
        elif total_pct >= 100:
            btn_claim = types.InlineKeyboardButton("Cʟᴀɪᴍ 🎁", callback_data=f"task_claim_{user_id}")
        else:
            btn_claim = types.InlineKeyboardButton("Cʟᴀɪᴍ 🔒", callback_data=f"task_claim_{user_id}")
            
        kb.add(btn_progress)
        kb.add(btn_refresh, btn_claim)
        
        # 7. Edit the message instantly
        try: bot.edit_message_text(text, chat_id, msg_id, reply_markup=kb, parse_mode="MarkdownV2")
        except: pass

    # INSTANT RESPONSE LOGIC
    if message_id:
        # Existing message (from a button click)
        threading.Thread(target=process_ui, args=(message_id,)).start()
    else:
        # Brand new command: Send loading message instantly, then build in background!
        try:
            sent_msg = bot.send_message(chat_id, "🔄 *Lᴏᴀᴅɪɴɢ ʏᴏᴜʀ ᴛᴀsᴋs\\.\\.\\.*", parse_mode="MarkdownV2")
            threading.Thread(target=process_ui, args=(sent_msg.message_id,)).start()
        except: pass

def handle_task_callback(bot, call):
    parts = call.data.split("_")
    action = parts[1]
    user_id = int(parts[2])
    
    if call.from_user.id != user_id:
        return safe_answer(bot, call.id, "❌ Not your tasks!", show_alert=True)
        
    if action == "refresh":
        safe_answer(bot, call.id, "🔄 Refreshing progress...")
        render_tasks_ui(bot, call.message.chat.id, user_id, call.message.message_id)

    # 📍 NEW: Intercept the progress bar click and show the percentage alert
    elif action == "prog":
        pct = parts[3]
        safe_answer(bot, call.id, f"📊 Your progress is {pct}% completed!", show_alert=True)
        
    elif action == "claim":
        def process_claim():
            tasks_list = db.get_daily_tasks(user_id)
            all_claimed = all(t['completed'] for t in tasks_list)
            
            if all_claimed:
                return safe_answer(bot, call.id, "❌ You already claimed today's reward!", show_alert=True)
                
            all_done = all(t['progress'] >= t['goal'] for t in tasks_list)
            
            if not all_done:
                return safe_answer(bot, call.id, "🔒 You haven't completed all tasks yet!", show_alert=True)
                
            # Complete tasks in DB
            db.claim_task_reward(user_id, 'catch')
            db.claim_task_reward(user_id, 'pvp')
            db.claim_task_reward(user_id, 'catch_specific')
            
            # --- MYSTERY BOX LOGIC ---
            NON_LEGENDARY_POOL = [
                "Charizard", "Lucario", "Gengar", "Dragonite", "Garchomp", 
                "Metagross", "Tyranitar", "Salamence", "Greninja", "Eevee", 
                "Snorlax", "Gyarados", "Arcanine", "Togekiss", "Scizor",
                "Slaking", "Aegislash", "Volcarona", "Blaziken", "Sceptile",
                "Aggron", "Milotic", "Lapras", "Hydreigon", "Goodra"
            ]
            
            LEGENDARY_POOL = [
                "Articuno", "Zapdos", "Moltres", "Mewtwo", "Mew", 
                "Raikou", "Entei", "Suicune", "Lugia", "Ho-Oh", "Celebi",
                "Latias", "Latios", "Kyogre", "Groudon", "Rayquaza", "Jirachi",
                "Dialga", "Palkia", "Giratina", "Cresselia", "Darkrai",
                "Zacian", "Zamazenta" 
            ]
            
            # 10% Chance for Legendary, 90% for Non-Legendary
            if random.random() < 0.10:
                reward_poke = random.choice(LEGENDARY_POOL)
                rarity_tag = "🌟 LEGENDARY"
            else:
                reward_poke = random.choice(NON_LEGENDARY_POOL)
                rarity_tag = "✨ RARE"
                
            # Add to inventory
            db.add_caught_pokemon(user_id, reward_poke, "Task")
            
            # Alert the user
            safe_answer(bot, call.id, f"🎁 BOX OPENED! You claimed a {rarity_tag} Shiny {reward_poke}!", show_alert=True)
            render_tasks_ui(bot, call.message.chat.id, user_id, call.message.message_id)
            
        # Push the claiming logic to the background so the button doesn't hang!
        threading.Thread(target=process_claim).start()

def check_and_update_catch(user_id, pokemon_name):
    try: 
        db.update_task_catch(user_id)
        db.update_task_specific_catch(user_id, pokemon_name)
    except: pass

def add_pvp_win(user_id):
    try: db.update_task_pvp(user_id)
    except: pass
