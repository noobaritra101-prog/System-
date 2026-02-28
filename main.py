import asyncio
import requests
from aiogram import Bot, Dispatcher, types as tg_types
from aiogram.filters import Command, CommandObject

# --- CONFIGURATION ---
TELEGRAM_TOKEN = "8312508827:AAG2QmJa1Zcwx68npE3LAnWX_oawQygK2T8"
GROUP_ID = -1003531986896 
SUPERHERO_API_TOKEN = "34d58b1bf12ea5155b7a9b7c851f8ea4"

bot = Bot(token=TELEGRAM_TOKEN)
dp = Dispatcher()

# --- UTILS: LOADING BAR GENERATOR ---
def create_loading_bar(current, total):
    size = 10  # Number of segments in the bar
    filled_length = int(size * current // total)
    bar = "🟦" * filled_length + "⬜" * (size - filled_length)
    percent = (current / total) * 100
    return f"|{bar}| {percent:.1f}%"

# --- 1. DATA EXTRACTION ---
def get_hero_by_id(hero_id):
    url = f"https://superheroapi.com/api/{SUPERHERO_API_TOKEN}/{hero_id}"
    try:
        resp = requests.get(url).json()
        if resp.get("response") == "error": return None
        
        ps = resp["powerstats"]
        def clean(val): return int(val) if val != "null" else 50
        
        return {
            "name": resp["name"],
            "image": resp["image"]["url"],
            "hp": clean(ps.get("durability")) * 10,
            "atk": clean(ps.get("strength")),
            "def": clean(ps.get("power")),
            "spd": clean(ps.get("speed")),
            "bio": resp["biography"]["full-name"] or "Unknown"
        }
    except: return None

# --- 2. COMMAND: /view {name} ---
@dp.message(Command("view"))
async def cmd_view(message: tg_types.Message, command: CommandObject):
    if not command.args:
        return await message.reply("Usage: `/view Hulk`")
    
    # Search by name
    search_url = f"https://superheroapi.com/api/{SUPERHERO_API_TOKEN}/search/{command.args}"
    resp = requests.get(search_url).json()
    
    if resp.get("response") == "error":
        return await message.reply("❌ Hero not found.")
    
    hero = resp["results"][0]
    ps = hero["powerstats"]
    def clean(val): return int(val) if val != "null" else 50
    
    caption = (
        f"🛡 **HERO: {hero['name'].upper()}**\n"
        f"━━━━━━━━━━━━━━━\n"
        f"❤️ HP: {clean(ps.get('durability'))*10} | ⚔️ ATK: {clean(ps.get('strength'))}\n"
        f"🛡 DEF: {clean(ps.get('power'))} | ⚡ SPD: {clean(ps.get('speed'))}"
    )
    await bot.send_photo(message.chat.id, hero['image']['url'], caption=caption, parse_mode="Markdown")

# --- 3. COMMAND: /start (The Mass Loader) ---
@dp.message(Command("start"))
async def cmd_start(message: tg_types.Message):
    MAX_HEROES = 731
    status_msg = await message.answer("🚀 **Initializing Database Sync...**")
    
    for hero_id in range(1, MAX_HEROES + 1):
        data = get_hero_by_id(hero_id)
        
        if data:
            try:
                # Post the character card
                caption = (
                    f"🛡 **HERO #{hero_id}: {data['name'].upper()}**\n"
                    f"━━━━━━━━━━━━━━━\n"
                    f"❤️ HP: {data['hp']} | 🛡 DEF: {data['def']}\n"
                    f"⚔️ ATK: {data['atk']} | ⚡ SPD: {data['spd']}\n"
                    f"👤 Bio: {data['bio']}"
                )
                await bot.send_photo(GROUP_ID, data['image'], caption=caption, parse_mode="Markdown")
                
                # Update Loading Bar every 2 heroes
                if hero_id % 2 == 0:
                    bar = create_loading_bar(hero_id, MAX_HEROES)
                    progress_text = (
                        f"⏳ **SYNCING DATABASE**\n"
                        f"{bar}\n"
                        f"📦 **Processed:** `{hero_id}/{MAX_HEROES}`\n"
                        f"👤 **Current:** `{data['name']}`"
                    )
                    await bot.edit_message_text(progress_text, message.chat.id, status_msg.message_id, parse_mode="Markdown")
            
            except Exception as e:
                print(f"Error on ID {hero_id}: {e}")
        
        # Delay to prevent Telegram Flood Error (approx 30 messages per min)
        await asyncio.sleep(2)

    await bot.edit_message_text("🏁 **SYNC COMPLETE: 731 Heroes Loaded.**", message.chat.id, status_msg.message_id)

async def main():
    print("🤖 Bot is active. Type /start in your group.")
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
