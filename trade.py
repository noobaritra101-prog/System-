# trade.py
from telebot import types
import database as db
from api_utils import escape_md

active_trades = {}

def render_trade_state(bot, chat_id, trade_id, page=0):
    t = active_trades.get(trade_id)
    if not t: return

    status = t["status"]

    if status == "p1_choosing":
        render_trade_box(bot, chat_id, trade_id, "p1", page)

    elif status == "p2_choosing":
        render_trade_box(bot, chat_id, trade_id, "p2", page)

    elif status == "confirming":
        p1_rdy = "✅ Ready" if t['p1_confirm'] else "⏳ Pending"
        p2_rdy = "✅ Ready" if t['p2_confirm'] else "⏳ Pending"

        text = (
            "🔄 *Finalize Trade*\n"
            "━━━━━━━━━━━━━━\n"
            f"👤 *{escape_md(t['p1_name'])}* offers:\n"
            f"🔸 {escape_md(t['p1_offer'])} \\({p1_rdy}\\)\n\n"
            f"👤 *{escape_md(t['p2_name'])}* offers:\n"
            f"🔸 {escape_md(t['p2_offer'])} \\({p2_rdy}\\)\n"
            "━━━━━━━━━━━━━━\n"
            "_Both players must confirm to complete the trade\\._"
        )

        kb = types.InlineKeyboardMarkup(row_width=2)
        kb.row(
            types.InlineKeyboardButton(f"✅ {t['p1_name']} Confirm", callback_data=f"tr_rdy_{trade_id}_p1"),
            types.InlineKeyboardButton(f"✅ {t['p2_name']} Confirm", callback_data=f"tr_rdy_{trade_id}_p2")
        )
        kb.row(types.InlineKeyboardButton("❌ Cancel Trade", callback_data=f"tr_cancel_{trade_id}"))

        try: bot.edit_message_text(text, chat_id, trade_id, reply_markup=kb, parse_mode="MarkdownV2")
        except Exception: pass

def render_trade_box(bot, chat_id, trade_id, player_str, page):
    t = active_trades.get(trade_id)
    if not t: return
    
    uid = t[player_str + "_id"]
    inv = db.list_user_pokemon_names(uid)
    t[player_str + "_inv"] = inv  
        
    if not inv:
        active_trades.pop(trade_id, None)
        bot.edit_message_text(f"❌ *Trade Cancelled:* {escape_md(t[player_str + '_name'])} has no Pokémon to trade\\!", chat_id, trade_id, parse_mode="MarkdownV2")
        return
        
    ITEMS_PER_PAGE = 10
    pages = [inv[i:i + ITEMS_PER_PAGE] for i in range(0, len(inv), ITEMS_PER_PAGE)]
    if page >= len(pages): page = len(pages) - 1
    if page < 0: page = 0
    
    current_page = pages[page]
    
    text = (
        "🔄 *Pokémon Trade Center*\n"
        "━━━━━━━━━━━━━━\n"
        f"It is *{escape_md(t[player_str + '_name'])}*'s turn to choose\\!\n\n"
        f"🎒 *PC Box* \\(Page {page+1}/{len(pages)}\\)\n"
    )
    for i, poke in enumerate(current_page):
        text += f"`[{i+1}]` {escape_md(poke)}\n"
        
    kb = types.InlineKeyboardMarkup(row_width=5)
    
    # Generate [1] [2] [3] buttons
    btns = [types.InlineKeyboardButton(str(i+1), callback_data=f"tr_pick_{trade_id}_{player_str}_{page}_{i}") for i in range(len(current_page))]
    for i in range(0, len(btns), 5): kb.add(*btns[i:i+5])
        
    # Navigation buttons
    nav = []
    if page > 0: nav.append(types.InlineKeyboardButton("⏪ Prev", callback_data=f"tr_box_{trade_id}_{player_str}_{page-1}"))
    nav.append(types.InlineKeyboardButton("❌ Cancel", callback_data=f"tr_cancel_{trade_id}"))
    if page < len(pages) - 1: nav.append(types.InlineKeyboardButton("Next ⏩", callback_data=f"tr_box_{trade_id}_{player_str}_{page+1}"))
    kb.row(*nav)
    
    try: bot.edit_message_text(text, chat_id, trade_id, reply_markup=kb, parse_mode="MarkdownV2")
    except Exception: pass

def handle_trade_command(bot, message):
    if not message.reply_to_message:
        return bot.reply_to(message, escape_md("⚠️ Reply to a user to trade with them!"))
    
    p1_id, p2_id = message.from_user.id, message.reply_to_message.from_user.id
    if p1_id == p2_id:
        return bot.reply_to(message, escape_md("❌ You can't trade with yourself!"))
        
    p1_name = message.from_user.first_name
    p2_name = message.reply_to_message.from_user.first_name
    
    text = f"🔄 *{escape_md(p1_name)}* wants to trade Pokémon with *{escape_md(p2_name)}*\\!\n\n_Waiting for {escape_md(p2_name)} to accept\\.\\.\\._"
    kb = types.InlineKeyboardMarkup()
    kb.add(
        types.InlineKeyboardButton("✅ Accept", callback_data=f"tr_acc_{p1_id}_{p2_id}"),
        types.InlineKeyboardButton("❌ Decline", callback_data=f"tr_dec_{p1_id}_{p2_id}")
    )
    
    sent = bot.reply_to(message, text, reply_markup=kb, parse_mode="MarkdownV2")
    
    active_trades[sent.message_id] = {
        "p1_id": p1_id, "p1_name": p1_name, "p1_offer": None, "p1_confirm": False, "p1_inv": None,
        "p2_id": p2_id, "p2_name": p2_name, "p2_offer": None, "p2_confirm": False, "p2_inv": None,
        "status": "pending"
    }

def handle_trade_callback(bot, call):
    parts = call.data.split("_")
    action = parts[1]
    
    # Accept / Decline Phase
    if action == "acc":
        if call.from_user.id != int(parts[3]): return bot.answer_callback_query(call.id, "❌ Not your trade request!", show_alert=True)
        trade_id = call.message.message_id
        if trade_id not in active_trades: return bot.answer_callback_query(call.id, "Trade expired.", show_alert=True)
        
        # Start Step 1: P1 Choosing
        active_trades[trade_id]["status"] = "p1_choosing"
        return render_trade_state(bot, call.message.chat.id, trade_id, 0)
        
    elif action == "dec":
        if call.from_user.id != int(parts[3]): return bot.answer_callback_query(call.id, "❌ Not your trade request!", show_alert=True)
        trade_id = call.message.message_id
        active_trades.pop(trade_id, None)
        return bot.edit_message_text("❌ *Trade declined\\.*", call.message.chat.id, trade_id, parse_mode="MarkdownV2")
        
    # Active Phases
    trade_id = int(parts[2])
    t = active_trades.get(trade_id)
    if not t: return bot.answer_callback_query(call.id, "Trade session ended.", show_alert=True)
        
    if action == "box":
        player_str, page = parts[3], int(parts[4])
        if call.from_user.id != t[player_str + "_id"]: return bot.answer_callback_query(call.id, "❌ Not your turn/box!", show_alert=True)
        render_trade_state(bot, call.message.chat.id, trade_id, page)
        
    elif action == "pick":
        player_str, page, idx = parts[3], int(parts[4]), int(parts[5])
        
        if call.from_user.id != t[player_str + "_id"]: 
            return bot.answer_callback_query(call.id, "❌ It is not your turn!", show_alert=True)
            
        inv = t.get(player_str + "_inv", [])
        abs_idx = (page * 10) + idx
        
        if abs_idx < len(inv):
            t[player_str + "_offer"] = inv[abs_idx]
            
            # Step 2: Switch to P2 choosing
            if player_str == "p1":
                t["status"] = "p2_choosing"
                render_trade_state(bot, call.message.chat.id, trade_id, 0)
                
            # Step 3: Move to Final Confirm Hub
            elif player_str == "p2":
                t["status"] = "confirming"
                render_trade_state(bot, call.message.chat.id, trade_id)
            
    elif action == "rdy":
        if t["status"] != "confirming": return
        
        player_str = parts[3]
        if call.from_user.id != t[player_str + "_id"]: return bot.answer_callback_query(call.id, "❌ Not your button!", show_alert=True)
            
        t[player_str + "_confirm"] = True
        
        # Execute trade if BOTH are ready
        if t["p1_confirm"] and t["p2_confirm"]:
            p1_id, p1_off, p2_id, p2_off = t["p1_id"], t["p1_offer"], t["p2_id"], t["p2_offer"]
            
            # Double check they still own it
            if db.delete_pokemon(p1_id, p1_off) and db.delete_pokemon(p2_id, p2_off):
                db.add_caught_pokemon(p1_id, p2_off, "Trade")
                db.add_caught_pokemon(p2_id, p1_off, "Trade")
                success_text = (f"🎉 *TRADE SUCCESSFUL\\!* 🎉\n━━━━━━━━━━━━━━\n"
                                f"👤 {escape_md(t['p1_name'])} received: ✨ {escape_md(p2_off)}\n"
                                f"👤 {escape_md(t['p2_name'])} received: ✨ {escape_md(p1_off)}\n━━━━━━━━━━━━━━")
                active_trades.pop(trade_id, None)
                bot.edit_message_text(success_text, call.message.chat.id, trade_id, parse_mode="MarkdownV2")
            else:
                # Refund if a database error occurred
                active_trades.pop(trade_id, None)
                bot.edit_message_text("❌ *Trade Failed:* Someone doesn't own the Pokémon they offered anymore\\!", call.message.chat.id, trade_id, parse_mode="MarkdownV2")
        else:
            # Re-render hub to show "Ready" status
            render_trade_state(bot, call.message.chat.id, trade_id)
            
    elif action == "cancel":
        if call.from_user.id not in [t["p1_id"], t["p2_id"]]: return bot.answer_callback_query(call.id, "❌ Not your trade!", show_alert=True)
        active_trades.pop(trade_id, None)
        bot.edit_message_text("❌ *Trade Cancelled\\.*", call.message.chat.id, trade_id, parse_mode="MarkdownV2")
