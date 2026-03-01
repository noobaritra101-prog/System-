# tasks.py
from telebot import types
import database as db
from api_utils import escape_md

def render_tasks_ui(bot, chat_id, user_id, message_id=None):
    t = db.get_daily_tasks(user_id)
    
    # 1. Cap progress at the maximum target
    p1_done = 1 if t['prog_p1'] else 0
    p2_done = 1 if t['prog_p2'] else 0
    pvp_done = min(t['prog_pvp'], t['target_pvp'])
    catch_done = min(t['prog_catch'], t['target_catch'])
    
    # 2. Calculate percentages (Each task is worth 25%)
    p1_pct = 25 if p1_done else 0
    p2_pct = 25 if p2_done else 0
    pvp_pct = (pvp_done / t['target_pvp']) * 25 if t['target_pvp'] > 0 else 25
    catch_pct = (catch_done / t['target_catch']) * 25 if t['target_catch'] > 0 else 25
    
    total_pct = int(p1_pct + p2_pct + pvp_pct + catch_pct)
    
    # 3. Generate visual progress bar (10 blocks total)
    filled_blocks = int(total_pct / 10)
    empty_blocks = 10 - filled_blocks
    progress_bar = "▰" * filled_blocks + "▱" * empty_blocks
    
    # 4. Generate Task Icons
    p1_icon = "✅" if p1_done else "☒"
    p2_icon = "✅" if p2_done else "☒"
    pvp_icon = "✅" if pvp_done >= t['target_pvp'] else "☒"
    catch_icon = "✅" if catch_done >= t['target_catch'] else "☒"
    
    # 5. Build the UI Text
    text = (
        "━━━━━━━━━━━━━━\n"
        "📅 *Your Daily Tasks*\n"
        "━━━━━━━━━━━━━━\n"
        f"• Catch a wild {escape_md(t['target_p1'])} 【{p1_icon}】\n"
        f"• Win {t['target_pvp']} PvP match{'es' if t['target_pvp']>1 else ''} \\({pvp_done}/{t['target_pvp']}\\) 【{pvp_icon}】\n"
        f"• Catch a wild {escape_md(t['target_p2'])} 【{p2_icon}】\n"
        f"• Catch {t['target_catch']} Pokémon \\({catch_done}/{t['target_catch']}\\) 【{catch_icon}】\n"
        "━━━━━━━━━━━━━━\n"
        "*Completion %*\n"
        f"{progress_bar} 【{total_pct}%】\n"
        "━━━━━━━━━━━━━━\n"
        f"🎁 *Reward:* ✨ Shiny {escape_md(t['reward_poke'])}"
    )
    
    # 6. Build the Buttons
    kb = types.InlineKeyboardMarkup(row_width=2)
    btn_refresh = types.InlineKeyboardButton("Refresh 🌀", callback_data=f"taskrefresh_{user_id}")
    
    if t["claimed"]:
        btn_claim = types.InlineKeyboardButton("Claimed ✅", callback_data=f"taskclaim_{user_id}")
    elif total_pct >= 100:
        btn_claim = types.InlineKeyboardButton("Claim 🎁", callback_data=f"taskclaim_{user_id}")
    else:
        btn_claim = types.InlineKeyboardButton("Claim 🔒", callback_data=f"taskclaim_{user_id}")
        
    kb.add(btn_refresh, btn_claim)
    
    # 7. Send or Edit Message
    if message_id:
        try: bot.edit_message_text(text, chat_id, message_id, reply_markup=kb, parse_mode="MarkdownV2")
        except: pass
    else:
        bot.send_message(chat_id, text, reply_markup=kb, parse_mode="MarkdownV2")


def handle_task_callback(bot, call):
    action = call.data.split("_")[0]
    user_id = int(call.data.split("_")[1])
    
    if call.from_user.id != user_id:
        return bot.answer_callback_query(call.id, "❌ Not your tasks!", show_alert=True)
        
    if action == "taskrefresh":
        bot.answer_callback_query(call.id, "🔄 Refreshing progress...")
        render_tasks_ui(bot, call.message.chat.id, user_id, call.message.message_id)
        
    elif action == "taskclaim":
        t = db.get_daily_tasks(user_id)
        if t["claimed"]:
            return bot.answer_callback_query(call.id, "❌ You already claimed today's reward!", show_alert=True)
            
        pvp_done = min(t['prog_pvp'], t['target_pvp'])
        catch_done = min(t['prog_catch'], t['target_catch'])
        all_done = (t['prog_p1'] and t['prog_p2'] and pvp_done >= t['target_pvp'] and catch_done >= t['target_catch'])
        
        if not all_done:
            return bot.answer_callback_query(call.id, "🔒 You haven't completed all tasks yet!", show_alert=True)
            
        success, reward = db.claim_daily_reward(user_id)
        if success:
            bot.answer_callback_query(call.id, f"🎉 You claimed a Shiny {reward}!", show_alert=True)
            render_tasks_ui(bot, call.message.chat.id, user_id, call.message.message_id)
        else:
            bot.answer_callback_query(call.id, "❌ Error claiming reward.", show_alert=True)

def check_and_update_catch(user_id, pokemon_name):
    """Called from main.py whenever a Pokémon is successfully caught."""
    db.update_task_catch(user_id, pokemon_name)

def add_pvp_win(user_id):
    """Called from pvp.py whenever the user wins a battle."""
    db.update_task_pvp(user_id)
