import asyncio
import json
import google.generativeai as genai
from aiogram import Bot
from playwright.async_api import async_playwright

# --- CONFIGURATION ---
TELEGRAM_TOKEN = "8312508827:AAG2QmJa1Zcwx68npE3LAnWX_oawQygK2T8"
GROUP_ID = -1003531986896 
GEMINI_KEY = "AIzaSyAFD1Xs_J7q9aU0A72WC0Ljjn1uqKuQ5m0"

genai.configure(api_key=GEMINI_KEY)
model = genai.GenerativeModel('gemini-1.5-flash')
bot = Bot(token=TELEGRAM_TOKEN)

# --- UTILS: PROGRESS BAR ---
def get_progress_bar(current, total):
    percent = (current / total) * 100
    filled_length = int(10 * current // total)
    bar = "🟢" * filled_length + "⚪" * (10 - filled_length)
    return f"{bar} {percent:.1f}%"

# --- 1. IMAGE SCRAPER ---
async def get_image(hero_name):
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page()
        url = f"https://www.pinterest.com/search/pins/?q={hero_name} marvel portrait fanart"
        await page.goto(url)
        try:
            await page.wait_for_selector("img", timeout=5000)
            img_src = await page.evaluate('document.querySelector("img").src')
        except:
            img_src = "https://via.placeholder.com/600x800?text=No+Image+Found"
        await browser.close()
        return img_src

# --- 2. DATA GENERATOR ---
async def get_hero_stats(hero_name):
    prompt = f"Create a JSON RPG profile for the Marvel character: {hero_name}. Include 4 moves with descriptions. Return ONLY raw JSON."
    response = await asyncio.to_thread(model.generate_content, prompt, generation_config={"response_mime_type": "application/json"})
    return json.loads(response.text)

# --- 3. THE SENDER & TRACKER ---
async def process_and_track(hero_name, progress_msg_id, current_index, total_count, done_list):
    # Update progress: Telling the group what is being created NOW
    status_text = (
        f"⏳ **DATABASE CREATION IN PROGRESS**\n"
        f"Progress: {get_progress_bar(current_index, total_count)}\n\n"
        f"🏗 **Currently Creating:** `{hero_name}`\n"
        f"✅ **Done:** {', '.join(done_list) if done_list else 'None yet'}"
    )
    await bot.edit_message_text(chat_id=GROUP_ID, message_id=progress_msg_id, text=status_text, parse_mode="Markdown")

    # Generate the Hero Card
    image_url, stats = await asyncio.gather(get_image(hero_name), get_hero_stats(hero_name))

    caption = (
        f"🛡 **NEW CHARACTER: {hero_name}**\n"
        f"━━━━━━━━━━━━━━━\n"
        f"❤️ **HP:** {stats['hp_range']['actual']} | ⚔️ **ATK:** {stats['atk_range']['actual']}\n\n"
        f"🔥 **MOVESET:**\n"
    )
    for m in stats['moves']:
        caption += f"• **{m['name']}**: {m['dmg']} DMG\n"

    await bot.send_photo(chat_id=GROUP_ID, photo=image_url, caption=caption, parse_mode="Markdown")
    done_list.append(hero_name)

# --- 4. START COMMAND HANDLER ---
async def start_creation():
    heroes = ["Spider-Man", "Wolverine", "Storm", "Dr. Doom", "Captain America"]
    total = len(heroes)
    done_list = []

    # Initial Progress Message
    progress_msg = await bot.send_message(GROUP_ID, "🚀 Starting Marvel Database Creation...")
    
    for i, hero in enumerate(heroes):
        await process_and_track(hero, progress_msg.message_id, i, total, done_list)
        await asyncio.sleep(2)

    # Final Update
    await bot.edit_message_text(
        chat_id=GROUP_ID, 
        message_id=progress_msg.message_id, 
        text=f"✅ **DATABASE COMPLETE!**\nTotal Heroes: {total}\nFinal List: {', '.join(done_list)}",
        parse_mode="Markdown"
    )

if __name__ == "__main__":
    asyncio.run(start_creation())
