import asyncio
import re
from telethon import TelegramClient
from config import API_ID, API_HASH, BOT_TOKEN, OWNER_ID, HEXA_ID, logger
from globals import user_configs

# CRITICAL FIX: We define the bot here, but DO NOT start it yet. 
# web_app.py will start it safely inside its event loop.
master_bot = TelegramClient('master_bot', API_ID, API_HASH)

def is_owner(user_id):
    """Checks if the Telegram user is the Master Admin."""
    return user_id == OWNER_ID

def extract_pokemon_name(text):
    """Upgraded Regex to capture Pokémon names safely, including special characters."""
    # Strategy 1: Handle "Appearance" (Priority for Shinies)
    match_appear = re.search(r'wild\s+(.*?)(?:\s*✨|\s*\(|\s+has appeared)', text, re.IGNORECASE)
    if match_appear:
        return match_appear.group(1).strip().title()

    # Strategy 2: Handle "Caught"
    match_caught = re.search(r'caught\s+(?:a\s+)?(?:wild\s+)?([^!]+)', text, re.IGNORECASE)
    if match_caught:
        return match_caught.group(1).strip().title()

    return None

async def send_notification(user_id, message):
    """Sends a Telegram DM (and optionally a group message) to the user."""
    try:
        await master_bot.send_message(user_id, message)
        config = user_configs.get(user_id)
        if config and config.get('notification_status') == 1:
            group_id = config.get('group_id')
            if group_id:
                try:
                    try:
                        user_entity = await master_bot.get_entity(user_id)
                        first_name = user_entity.first_name.replace("[", "").replace("]", "")
                        user_tag = f"[{first_name}](tg://user?id={user_id})"
                    except:
                        user_tag = f"[User](tg://user?id={user_id})"

                    await master_bot.send_message(group_id, f"🔔 **Alert for {user_tag}:**\n{message}")
                except Exception as e:
                    logger.error(f"Failed to send to group {group_id}: {e}")
    except Exception as e:
        logger.error(f"Failed to send notification: {e}")

async def smart_click_with_retry(client, chat_id, message_object, button_text_to_click):
    """Clicks an inline keyboard button and retries if HexaBot lags."""
    attempt = 1
    original_id = message_object.id
    original_text_len = len(message_object.raw_text)
    
    while attempt <= 10:
        try:
            msg_current = await client.get_messages(chat_id, ids=original_id)
            if not msg_current or not msg_current.reply_markup: return

            # Using Telethon's built-in text matching for clicks
            try:
                await msg_current.click(text=button_text_to_click)
            except Exception:
                # Fallback to manual index search if exact match fails
                all_buttons = [b for row in msg_current.reply_markup.rows for b in row.buttons]
                target_index = next((i for i, btn in enumerate(all_buttons) if button_text_to_click.lower() in btn.text.lower()), -1)
                if target_index == -1: return
                await msg_current.click(target_index)

            await asyncio.sleep(5) 

            latest_msgs = await client.get_messages(chat_id, limit=1)
            if latest_msgs and latest_msgs[0].id > original_id: return 

            msg_after = await client.get_messages(chat_id, ids=original_id)
            if not msg_after or len(msg_after.raw_text) != original_text_len: return 
            
            current_buttons = [b.text for row in msg_after.reply_markup.rows for b in row.buttons] if msg_after.reply_markup else []
            if not any(button_text_to_click.lower() in b.lower() for b in current_buttons): return 
            
            logger.info(f"[RETRY CLICK] No update for '{button_text_to_click}'. Clicking again...")
            attempt += 1

        except Exception as e:
            logger.error(f"[ERROR] Click Retry: {e}")
            await asyncio.sleep(5)

async def send_hunt_with_retry(client, chat_id, user_id):
    """Sends /hunt and ensures the game actually responds."""
    try:
        target_id = (await client.get_entity(chat_id)).id if isinstance(chat_id, str) else chat_id
    except Exception as e:
        logger.error(f"[ERROR] Could not resolve bot ID: {e}")
        return

    await client.send_message(chat_id, "/hunt")
    await asyncio.sleep(2)
    
    latest = await client.get_messages(chat_id, limit=1)
    last_msg_id = latest[0].id if latest else 0

    while True: 
        await asyncio.sleep(3)
        try:
            if user_id not in user_configs or not user_configs[user_id].get('hunting'):
                return
            if user_configs[user_id].get('mode') != 'SEARCHING':
                return

            latest = await client.get_messages(chat_id, limit=1)
            if not latest: continue
            
            latest_msg = latest[0]

            if latest_msg.id > last_msg_id:
                if latest_msg.sender_id == target_id:
                    return # Game responded successfully!
                else:
                    last_msg_id = latest_msg.id
                    continue
            
            logger.info(f"[HUNT RETRY] No response for {user_id}. Retrying...")
            await client.send_message(chat_id, "/hunt")
            latest_retry = await client.get_messages(chat_id, limit=1)
            if latest_retry: last_msg_id = latest_retry[0].id
            
        except Exception as e:
             logger.error(f"[ERROR] Hunt Retry: {e}")
             await asyncio.sleep(10)
