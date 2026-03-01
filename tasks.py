# tasks.py
from telebot import types
import database as db
from api_utils import escape_md

def render_tasks_ui(bot, chat_id, user_id, message_id=None):
    t = db.get_daily_tasks(user_id)
    
    # Calculate visual progress
    p1_icon = "✅" if t['prog_p1'] else "❌"
    p2_icon = "✅" if t['prog_p2'] else "❌"
    pvp_done = min(t['prog_pvp'], t['target_pvp'])
    pvp_icon = "✅" if pvp_done >= t['target_pvp'] else "❌"
    catch_done = min(t['prog_catch'], t['target_catch'])
    catch_icon = "✅" if catch_done >= t['target_catch'] else "❌"
    
    # Check if all tasks are complete
    all_done = (t['prog_p1'] and t['prog_p2'] and pvp_done >= t['target_pvp'] and catch_done >= t['target_catch'])
    
    text = "📅 *Your Daily Tasks*\n━━━━━━━━━━━━━━\n"
    text += f"{p1_icon} Catch a wild {escape_md(t['target_p1'])}\n"
    text += f"{pvp_icon} Win {t['target_pvp']} PvP match{'es' if t['target_pvp']>1 else ''} \\({pvp_done}/{t['target_pvp']}\\)\n"
    text += f"{p2_icon} Catch a wild {escape_md(t['target_p2'])}\n"
    text += f"{catch_icon} Catch {t['target_catch']} Pokémon \\({catch_done}/{t['target_catch']}\\)\n\n"
    text += f"🎁 *Reward:* ✨ Shiny {escape_md(t['reward_poke'])}\n"
    
    kb = types.InlineKeyboardMarkup()
    if all_done and not t["claimed"]:
        kb.add(types.InlineKeyboardButton("🎁 Claim Reward", callback_data=f"taskclaim_{user_id}"))
    elif t["claimed"]:
        text += "\n✅ _You have claimed today's reward\\!_"
        
    if message_id:
        try: bot.edit_message_text(text, chat_id, message_id, reply_markup=kb, parse_mode="MarkdownV2")
        except: pass
    else:
        bot.send_message(chat_id, text, reply_markup=kb, parse_mode="MarkdownV2")

def handle_task_callback(bot, call):
    user_id = int(call.data.split("_")[1])
    if call.from_user.id != user_id:
        return bot.answer_callback_query(call.id, "❌ Not your tasks!", show_alert=True)
        
    success, reward = db.claim_daily_reward(user_id)
    if success:
        bot.answer_callback_query(call.id, f"🎉 You claimed a Shiny {reward}!", show_alert=True)
        render_tasks_ui(bot, call.message.chat.id, user_id, call.message.message_id)
    else:
        bot.answer_callback_query(call.id, "❌ Tasks not finished or already claimed.", show_alert=True)
        
def check_and_update_catch(user_id, pokemon_name):
    """Called from main.py whenever a Pokémon is successfully caught."""
    db.update_task_catch(user_id, pokemon_name)

def add_pvp_win(user_id):
    """Called from pvp.py whenever the user wins a battle."""
    db.update_task_pvp(user_id)
