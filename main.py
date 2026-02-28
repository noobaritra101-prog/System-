import asyncio
import json
import requests
from google import genai
from google.genai import types
from aiogram import Bot, Dispatcher, types as tg_types
from aiogram.filters import Command

# --- CONFIGURATION ---
TELEGRAM_TOKEN = "8312508827:AAG2QmJa1Zcwx68npE3LAnWX_oawQygK2T8"
GROUP_ID = -1003531986896 
GEMINI_KEY = "AIzaSyAFD1Xs_J7q9aU0A72WC0Ljjn1uqKuQ5m0"
SUPERHERO_API_TOKEN = "34d58b1bf12ea5155b7a9b7c851f8ea4"

# Initialize modern Clients
client = genai.Client(api_key=GEMINI_KEY)
bot = Bot(token=TELEGRAM_TOKEN)
dp = Dispatcher()

# --- 1. SUPERHERO API FETCH ---
async def fetch_hero_base(name):
    url = f"https://superheroapi.com/api/{SUPERHERO_API_TOKEN}/search/{name}"
    resp = requests.get(url).json()
    if resp.get("response") == "error": return None
    
    hero = resp["results"][0]
    ps = hero["powerstats"]
    
    # RPG Mapping
    return {
        "name": hero["name"],
        "image": hero["image"]["url"],
        "hp": int(ps.get("durability", 50)) * 10,
        "atk": int(ps.get("strength", 50)),
        "def": int(ps.get("power", 50)),
        "spd": int(ps.get("speed", 50)),
        "bio": hero["biography"]["full-name"]
    }

# --- 2. GEMINI MOVE GENERATOR ---
async def generate_moves(hero_name):
    prompt = f"Write 4 RPG moves for {hero_name}. Return ONLY JSON: [{{'name':str, 'desc':str, 'dmg':int, 'cost':int}}]"
    # Using new async SDK call
    response = await client.aio.models.generate_content(
        model='gemini-2.0-flash',
        contents=prompt,
        config=types.GenerateContentConfig(response_mime_type='application/json')
    )
    return json.loads(response.text)

# --- 3. PROCESSING & UPLOAD ---
async def create_and_upload(hero_name, progress_msg, current, total):
    # Fetch data and moves
    base_data = await fetch_hero_base(hero_name)
    if not base_data: return
    
    moves = await generate_moves(hero_name)

    # Format the Stat Card
    caption = (
        f"🛡 **HERO DATABASE: {base_data['name']}**\n"
        f"━━━━━━━━━━━━━━━\n"
        f"👤 **Real Name:** {base_data['bio']}\n"
        f"❤️ **HP:** {base_data['hp']} | 🛡 **DEF:** {base_data['def']}\n"
        f"⚔️ **ATK:** {base_data['atk']} | ⚡ **SPD:** {base_data['spd']}\n\n"
        f"🔥 **COMBAT MOVES:**\n"
    )
    for m in moves:
        caption += f"• **{m['name']}**: {m['dmg']} DMG\n  _{m['desc']}_\n\n"

    # Upload Photo + Stats
    await bot.send_photo(chat_id=GROUP_ID, photo=base_data['image'], caption=caption, parse_mode="Markdown")

# --- 4. COMMAND HANDLER ---
@dp.message(Command("start"))
async def cmd_start(message: tg_types.Message):
    if message.chat.id != GROUP_ID: return
    
    heroes = ["Ghost Rider", "Wolverine", "Magneto", "Jean Grey", "Black Panther"]
    prog = await message.answer("🚀 **Starting Database Upload...**")
    
    for i, hero in enumerate(heroes):
        # Update progress message
        await bot.edit_message_text(f"⏳ Processing: `{hero}` ({i+1}/{len(heroes)})", GROUP_ID, prog.message_id)
        
        await create_and_upload(hero, prog, i, len(heroes))
        await asyncio.sleep(2) # Prevent spam limits

    await bot.edit_message_text(f"✅ **DATABASE COMPLETE!**\nUploaded {len(heroes)} heroes.", GROUP_ID, prog.message_id)

async def main():
    print("🤖 Bot is starting...")
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
