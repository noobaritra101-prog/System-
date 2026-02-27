import asyncio
import json
from telethon import TelegramClient, events
from telethon.sessions import StringSession

from config import API_ID, API_HASH, HEXA_ID, logger
from globals import user_clients, user_configs
from database import db, update_stat
from utils import send_notification, smart_click_with_retry, send_hunt_with_retry, extract_pokemon_name

async def run_userbot(user_id, session_str):
    try:
        client = TelegramClient(StringSession(session_str), API_ID, API_HASH)
        await client.connect()
        user_clients[user_id] = client
        try: await client.get_entity(HEXA_ID) 
        except: await client.send_message(HEXA_ID, "/start")
        logger.info(f"--- Userbot Started: {user_id} ---")
    except Exception as e:
        logger.error(f"FATAL Startup: {e}")
        return

    @client.on(events.NewMessage(chats=HEXA_ID))
    async def msg_handler(event):
        config = user_configs.get(user_id)
        if not config or not config.get('hunting'): return
        
        mode = config.get('mode', 'SEARCHING')
        text = event.raw_text.lower()
        
        if "daily hunt limit reached" in text:
            config['hunting'] = False
            await send_notification(user_id, "🛑 **Daily Hunt Limit Reached!**")
            return

        if "💿 found!" in text:
            update_stat(user_id, 'total_tms')
            await asyncio.sleep(2)
            await send_hunt_with_retry(client, HEXA_ID, user_id)
            return

        if "mega stone" in text or "transform" in text:
            update_stat(user_id, 'total_megastones')
            await asyncio.sleep(2)
            await send_hunt_with_retry(client, HEXA_ID, user_id)
            return

        if mode == 'SEARCHING':
            is_shiny_text = "wild" in text and "✨" in text
            
            if is_shiny_text:
                update_stat(user_id, 'total_shinies')
                pname = extract_pokemon_name(event.raw_text) or "Unknown Shiny"
                if config.get('smode'):
                    config['shiny_encounter'] = True 
                    if event.message.reply_markup:
                        config['mode'] = 'BATTLING'
                        await smart_click_with_retry(client, HEXA_ID, event.message, "Battle")
                    return
                else:
                    config['hunting'] = False
                    await send_notification(user_id, f"✨ **SHINY {pname} DETECTED!**\nSMode is OFF. Catch manually!")
                    return

            if "wild" in text and not is_shiny_text:
                target_found = False
                h_mode = config.get('hunting_mode', 'LIST')
                
                if h_mode == 'CATCHALL': target_found = True
                elif h_mode == 'CATCHNULL': target_found = False
                else: target_found = any(p.lower() in text for p in config['list'])
                
                if target_found:
                    update_stat(user_id, 'total_matched')
                    if event.message.reply_markup:
                        config['mode'] = 'BATTLING'
                        config['shiny_encounter'] = False 
                        await smart_click_with_retry(client, HEXA_ID, event.message, "Battle")
                        return
                else:
                    await asyncio.sleep(2)
                    await send_hunt_with_retry(client, HEXA_ID, user_id)
                    return

        elif mode == 'BATTLING':
            await process_battle_logic(event, user_id, client, config)

    @client.on(events.MessageEdited(chats=HEXA_ID))
    async def edit_handler(event):
        config = user_configs.get(user_id)
        if not config or not config.get('hunting'): return
        if config.get('mode') == 'BATTLING':
            await process_battle_logic(event, user_id, client, config)

    await client.run_until_disconnected()

async def process_battle_logic(event, user_id, client, config):
    text = event.raw_text.lower()
    
    if "caught" in text:
        pname = extract_pokemon_name(event.raw_text)
        if config.get('shiny_encounter'):
            update_stat(user_id, 'shiny_caught')
            update_stat(user_id, 'total_caught')
            config['shiny_encounter'] = False 
            await send_notification(user_id, f"✅ **Shiny {pname} Caught!**")
        else:
            update_stat(user_id, 'total_caught')

        if pname:
            log = config.get('catch_log', {})
            log[pname] = log.get(pname, 0) + 1
            config['catch_log'] = log
            cursor = db.cursor()
            cursor.execute("UPDATE users SET catch_log = ? WHERE user_id = ?", (json.dumps(log), user_id))
            db.commit()

        config['mode'] = 'SEARCHING'
        await asyncio.sleep(2)
        await send_hunt_with_retry(client, HEXA_ID, user_id)
        return

    if "fled" in text:
        if config.get('shiny_encounter'):
            update_stat(user_id, 'shiny_fled')
            update_stat(user_id, 'total_fled')
            config['shiny_encounter'] = False
            await send_notification(user_id, f"❌ **Shiny Fled!**")
        else:
            update_stat(user_id, 'total_fled')
        
        config['mode'] = 'SEARCHING'
        await asyncio.sleep(2)
        await send_hunt_with_retry(client, HEXA_ID, user_id)
        return

    if event.message.reply_markup:
        all_buttons = [b.text for row in event.message.reply_markup.rows for b in row.buttons]
        ball_to_use = config.get('ball') or "Ultra Ball" 
        
        if config.get('shiny_encounter') and config.get('sball'):
            ball_to_use = config.get('sball')
        
        found_btn = next((b for b in all_buttons if ball_to_use.lower() in b.lower()), None)
        if found_btn:
            await smart_click_with_retry(client, HEXA_ID, event.message, found_btn)
            return
        
        found_menu = next((b for b in all_buttons if "poke balls" in b.lower()), None)
        if found_menu:
            await smart_click_with_retry(client, HEXA_ID, event.message, "Poke Balls")
            return
