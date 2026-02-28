# -*- coding: utf-8 -*-
import telebot
from telebot import types
import sqlite3
import aiohttp
import asyncio
import random
import time
import datetime
import logging
import threading
import os
import shutil
import re

# ================== CONFIG ==================
BOT_TOKEN = "8311035050:AAEfGHJEjqi59jifzbdP1rxJQ1LoLwQN3Nw"  # Replace with your valid bot token from @BotFather
OWNER_ID = 5716292610  # Your Telegram user ID from logs
LOG_GROUP_ID = -1002790195961  # Replace with your log group's chat ID or keep as None
FLEE_TIMEOUT = 120  # Seconds (2 minutes) before Pokémon flees

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

bot = telebot.TeleBot(BOT_TOKEN, parse_mode="MarkdownV2")
DB_FILE = "pokemon.db"
REGIONS = ["Kanto", "Johto", "Hoenn", "Sinnoh", "Unova", "Kalos", "Alola", "Galar"]
active_hunts = {}  # Format: {message_id: {"user_id": user_id, "start_time": time.time(), "timer": Timer, "name": pokemon_name}}
pokemon_cache = {}  # Cache for Pokémon ID:name pairs
last_api_call = 0  # Track last Telegram API call

# Mega Pokémon list (ID, name, base_id for sprites)
MEGA_POKEMON = [
    (3, "Venusaur-Mega", 3), (6, "Charizard-Mega-X", 6), (6, "Charizard-Mega-Y", 6), (9, "Blastoise-Mega", 9),
    (65, "Alakazam-Mega", 65), (94, "Gengar-Mega", 94), (115, "Kangaskhan-Mega", 115), (127, "Pinsir-Mega", 127),
    (130, "Gyarados-Mega", 130), (142, "Aerodactyl-Mega", 142), (150, "Mewtwo-Mega-X", 150), (150, "Mewtwo-Mega-Y", 150),
    (181, "Ampharos-Mega", 181), (208, "Steelix-Mega", 208), (212, "Scizor-Mega", 212), (214, "Heracross-Mega", 214),
    (229, "Houndoom-Mega", 229), (248, "Tyranitar-Mega", 248), (254, "Sceptile-Mega", 254), (257, "Blaziken-Mega", 257),
    (260, "Swampert-Mega", 260), (282, "Gardevoir-Mega", 282), (303, "Mawile-Mega", 303), (306, "Aggron-Mega", 306),
    (308, "Medicham-Mega", 308), (310, "Manectric-Mega", 310), (354, "Banette-Mega", 354), (359, "Absol-Mega", 359),
    (445, "Garchomp-Mega", 445), (448, "Lucario-Mega", 448), (460, "Abomasnow-Mega", 460)
]

# ================== MARKDOWNV2 ESCAPING ==================
def escape_markdown_v2(text):
    """Escape special characters for MarkdownV2."""
    special_chars = r'([_\*\[\]\(\)~`>\#\+\-=\|\{\}\.\!])'
    return re.sub(special_chars, r'\\\1', str(text))

# ================== DB INIT ==================
def init_db():
    try:
        conn = sqlite3.connect(DB_FILE)
        cur = conn.cursor()
        cur.execute("""
            CREATE TABLE IF NOT EXISTS users(
                user_id INTEGER PRIMARY KEY,
                tries_left INTEGER DEFAULT 300,
                region TEXT DEFAULT 'Kanto',
                last_reset DATE
            )
        """)
        cur.execute("""
            CREATE TABLE IF NOT EXISTS pokemons(
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                name TEXT NOT NULL,
                region TEXT NOT NULL
            )
        """)
        cur.execute("""
            CREATE TABLE IF NOT EXISTS groups(
                group_id INTEGER PRIMARY KEY
            )
        """)
        cur.execute("CREATE INDEX IF NOT EXISTS idx_user_id ON users(user_id)")
        cur.execute("CREATE INDEX IF NOT EXISTS idx_pokemon_user_id ON pokemons(user_id)")
        conn.commit()
        logger.info("Database initialized successfully")
    except Exception as e:
        logger.error(f"Database initialization failed: {e}")
        raise
    finally:
        conn.close()

# ================== GROUP TRACKING ==================
def add_group(group_id):
    try:
        logger.info(f"Attempting to add group {group_id}")
        conn = sqlite3.connect(DB_FILE)
        cur = conn.cursor()
        cur.execute("INSERT OR IGNORE INTO groups(group_id) VALUES (?)", (group_id,))
        conn.commit()
        logger.info(f"Successfully added group {group_id} to database")
    except Exception as e:
        logger.error(f"Error adding group {group_id}: {e}")
    finally:
        conn.close()

def remove_group(group_id):
    try:
        logger.info(f"Attempting to remove group {group_id}")
        conn = sqlite3.connect(DB_FILE)
        cur = conn.cursor()
        cur.execute("DELETE FROM groups WHERE group_id=?", (group_id,))
        conn.commit()
        logger.info(f"Successfully removed group {group_id} from database")
    except Exception as e:
        logger.error(f"Error removing group {group_id}: {e}")
    finally:
        conn.close()

def get_all_groups():
    try:
        conn = sqlite3.connect(DB_FILE)
        cur = conn.cursor()
        cur.execute("SELECT group_id FROM groups ORDER BY group_id")
        rows = cur.fetchall()
        group_ids = [row[0] for row in rows]
        logger.info(f"Fetched {len(group_ids)} groups: {group_ids}")
        conn.close()
        return group_ids
    except Exception as e:
        logger.error(f"Error fetching all groups: {e}")
        return []

# ================== HELPERS ==================
def get_user(user_id):
    try:
        conn = sqlite3.connect(DB_FILE)
        cur = conn.cursor()
        cur.execute("SELECT user_id, tries_left, region, last_reset FROM users WHERE user_id=?", (user_id,))
        row = cur.fetchone()
        conn.close()
        return row
    except Exception as e:
        logger.error(f"Error fetching user {user_id}: {e}")
        return None

def add_user_if_new(user_id):
    existed = get_user(user_id) is not None
    if not existed:
        try:
            conn = sqlite3.connect(DB_FILE)
            cur = conn.cursor()
            cur.execute("INSERT INTO users(user_id, tries_left, region, last_reset) VALUES (?, ?, ?, ?)",
                        (user_id, 300, "Kanto", str(datetime.date.today())))
            conn.commit()
            logger.info(f"New user added: {user_id}")
        except Exception as e:
            logger.error(f"Error adding user {user_id}: {e}")
        finally:
            conn.close()
    return not existed

def update_user_tries(user_id):
    try:
        conn = sqlite3.connect(DB_FILE)
        cur = conn.cursor()
        cur.execute("SELECT tries_left, region, last_reset FROM users WHERE user_id=?", (user_id,))
        row = cur.fetchone()
        if not row:
            return None, None
        tries_left, region, last_reset = row
        today_str = str(datetime.date.today())
        if last_reset != today_str:
            tries_left = 300
            cur.execute("UPDATE users SET tries_left=?, last_reset=? WHERE user_id=?", (tries_left, today_str, user_id))
            conn.commit()
            logger.info(f"Daily reset for user {user_id}")
        if tries_left > 0:
            cur.execute("UPDATE users SET tries_left = tries_left - 1 WHERE user_id=?", (user_id,))
            conn.commit()
        conn.close()
        return tries_left, region
    except Exception as e:
        logger.error(f"Error updating user tries for {user_id}: {e}")
        return None, None

def add_caught_pokemon(user_id, name, region):
    try:
        conn = sqlite3.connect(DB_FILE)
        cur = conn.cursor()
        cur.execute("INSERT INTO pokemons(user_id, name, region) VALUES (?, ?, ?)", (user_id, name, region))
        conn.commit()
        logger.info(f"Added Pokémon {name} for user {user_id} in {region}")
        conn.close()
    except Exception as e:
        logger.error(f"Error adding Pokémon {name} for {user_id}: {e}")

def list_user_pokemon_names(user_id):
    try:
        conn = sqlite3.connect(DB_FILE)
        cur = conn.cursor()
        cur.execute("SELECT name FROM pokemons WHERE user_id=? ORDER BY id DESC", (user_id,))
        rows = cur.fetchall()
        conn.close()
        return [r[0].capitalize() for r in rows]
    except Exception as e:
        logger.error(f"Error listing Pokémon for {user_id}: {e}")
        return []

def delete_pokemon(user_id, pokemon_name):
    try:
        conn = sqlite3.connect(DB_FILE)
        cur = conn.cursor()
        cur.execute("DELETE FROM pokemons WHERE user_id=? AND name=?", (user_id, pokemon_name.capitalize()))
        deleted = cur.rowcount
        conn.commit()
        conn.close()
        logger.info(f"Deleted Pokémon {pokemon_name} for user {user_id}")
        return deleted > 0
    except Exception as e:
        logger.error(f"Error deleting Pokémon {pokemon_name} for {user_id}: {e}")
        return False

def get_all_users():
    try:
        conn = sqlite3.connect(DB_FILE)
        cur = conn.cursor()
        cur.execute("SELECT user_id FROM users ORDER BY user_id")
        rows = cur.fetchall()
        conn.close()
        return [row[0] for row in rows]
    except Exception as e:
        logger.error(f"Error fetching all users: {e}")
        return []

async def fetch_random_pokemon_id_and_name():
    if random.random() < 0.05:
        poke_id, name, base_id = random.choice(MEGA_POKEMON)
        logger.info(f"Selected Mega Pokémon: {name} (ID: {poke_id}, Base ID: {base_id})")
        return poke_id, name, base_id
    poke_id = random.randint(1, 898)
    if poke_id in pokemon_cache:
        logger.info(f"Cache hit for Pokémon ID {poke_id}: {pokemon_cache[poke_id]}")
        return poke_id, pokemon_cache[poke_id], poke_id
    async with aiohttp.ClientSession() as session:
        url = f"https://pokeapi.co/api/v2/pokemon/{poke_id}"
        try:
            start_time = time.time()
            async with session.get(url, timeout=15) as response:
                if response.status != 200:
                    logger.error(f"PokeAPI error: Status {response.status} for ID {poke_id}")
                    return None, None, None
                data = await response.json()
                name = data["name"].capitalize()
                pokemon_cache[poke_id] = name
                logger.info(f"Fetched Pokémon: {name} (ID: {poke_id}, Time: {time.time() - start_time:.2f}s)")
                return poke_id, name, poke_id
        except Exception as e:
            logger.error(f"PokeAPI request failed for ID {poke_id}: {e}")
            return None, None, None

def official_shiny_artwork_url(poke_id):
    return f"https://raw.githubusercontent.com/PokeAPI/sprites/master/sprites/pokemon/other/official-artwork/shiny/{poke_id}.png"

def default_pokemon_image():
    return "https://raw.githubusercontent.com/PokeAPI/sprites/master/sprites/pokemon/other/official-artwork/1.png"

async def get_species_catch_rate(poke_id):
    async with aiohttp.ClientSession() as session:
        url = f"https://pokeapi.co/api/v2/pokemon-species/{poke_id}"
        try:
            async with session.get(url, timeout=15) as response:
                if response.status != 200:
                    logger.error(f"PokeAPI species error: Status {response.status} for ID {poke_id}")
                    return 127
                data = await response.json()
                return data.get("capture_rate", 127) or 127
        except Exception as e:
            logger.error(f"PokeAPI species request failed for ID {poke_id}: {e}")
            return 127

def auto_flee(message_id, chat_id, pokemon_name):
    if message_id not in active_hunts:
        return
    try:
        bot.edit_message_caption(
            caption=escape_markdown_v2(f"The shiny {pokemon_name.capitalize()} fled!"),
            chat_id=chat_id,
            message_id=message_id,
            reply_markup=None,
            parse_mode="MarkdownV2"
        )
        logger.info(f"Auto-flee triggered for Pokémon {pokemon_name} in chat {chat_id} (message {message_id})")
    except Exception as e:
        logger.error(f"Error in auto-flee for message {message_id}: {e}")
    active_hunts.pop(message_id, None)

async def start_scout(chat_id, user_id, reply_to_id=None):
    global last_api_call
    start_time = time.time()
    logger.info(f"Starting scout for user {user_id} in chat {chat_id}")

    # Check user and update tries
    user = get_user(user_id)
    if not user:
        bot.send_message(chat_id, escape_markdown_v2("Please /start the bot first."), reply_to_message_id=reply_to_id, parse_mode="MarkdownV2")
        logger.info(f"Scout failed: User {user_id} not found (Time: {time.time() - start_time:.2f}s)")
        return
    tries_left, region = update_user_tries(user_id)
    if tries_left is None:
        bot.send_message(chat_id, escape_markdown_v2("Error checking your profile. Try again."), reply_to_message_id=reply_to_id, parse_mode="MarkdownV2")
        logger.info(f"Scout failed: User {user_id} profile error (Time: {time.time() - start_time:.2f}s)")
        return
    if tries_left <= 0:
        bot.send_message(chat_id, escape_markdown_v2("You have no scouts left today. Come back tomorrow."), reply_to_message_id=reply_to_id, parse_mode="MarkdownV2")
        logger.info(f"Scout failed: User {user_id} out of tries (Time: {time.time() - start_time:.2f}s)")
        return
    if any(hunt["user_id"] == user_id for hunt in active_hunts.values()):
        bot.send_message(chat_id, escape_markdown_v2("You already have an active scout. Complete it first."), reply_to_message_id=reply_to_id, parse_mode="MarkdownV2")
        logger.info(f"Scout failed: User {user_id} has active hunt (Time: {time.time() - start_time:.2f}s)")
        return

    # Fetch Pokémon
    poke_id, name, base_id = await fetch_random_pokemon_id_and_name()
    if not poke_id:
        bot.send_message(chat_id, escape_markdown_v2("Failed to fetch Pokémon. Try again."), reply_to_message_id=reply_to_id, parse_mode="MarkdownV2")
        logger.info(f"Scout failed: Pokémon fetch error for user {user_id} (Time: {time.time() - start_time:.2f}s)")
        return

    # Use base_id for image
    img_url = official_shiny_artwork_url(base_id)
    caption = escape_markdown_v2(f"A wild shiny {name} appeared in {region}!\nWhat will you do?")
    kb = types.InlineKeyboardMarkup()
    kb.add(
        types.InlineKeyboardButton("Catch", callback_data=f"catch_{user_id}_{poke_id}_{name[:16]}"),
        types.InlineKeyboardButton("Run", callback_data=f"run_{user_id}_{name[:16]}")
    )

    # Dynamic rate limit delay
    current_time = time.time()
    if current_time - last_api_call < 0.2:
        await asyncio.sleep(0.2)
    last_api_call = current_time

    try:
        sent = bot.send_photo(
            chat_id,
            img_url,
            caption=caption,
            reply_to_message_id=reply_to_id,
            reply_markup=kb,
            parse_mode="MarkdownV2"
        )
        # Start auto-flee timer
        timer = threading.Timer(FLEE_TIMEOUT, auto_flee, args=(sent.message_id, chat_id, name))
        timer.start()
        active_hunts[sent.message_id] = {
            "user_id": user_id,
            "start_time": time.time(),
            "timer": timer,
            "name": name
        }
        logger.info(f"Scout completed for user {user_id} in chat {chat_id}: {name} (Time: {time.time() - start_time:.2f}s)")
    except Exception as e:
        logger.error(f"Failed to send scout photo for {user_id}: {e}")
        try:
            sent = bot.send_photo(
                chat_id,
                default_pokemon_image(),
                caption=escape_markdown_v2(f"{caption}\n(Note: Image unavailable, showing default)"),
                reply_to_message_id=reply_to_id,
                reply_markup=kb,
                parse_mode="MarkdownV2"
            )
            timer = threading.Timer(FLEE_TIMEOUT, auto_flee, args=(sent.message_id, chat_id, name))
            timer.start()
            active_hunts[sent.message_id] = {
                "user_id": user_id,
                "start_time": time.time(),
                "timer": timer,
                "name": name
            }
            logger.info(f"Scout completed with default image for user {user_id} (Time: {time.time() - start_time:.2f}s)")
        except Exception as e2:
            logger.error(f"Failed to send default image for {user_id}: {e2}")
            bot.send_message(chat_id, escape_markdown_v2("Error displaying Pokémon. Try again."), reply_to_message_id=reply_to_id, parse_mode="MarkdownV2")
            logger.info(f"Scout failed: Image send error for user {user_id} (Time: {time.time() - start_time:.2f}s)")

# ================== COMMANDS ==================
@bot.message_handler(commands=["start"])
def cmd_start(message):
    start_time = time.time()
    is_new = add_user_if_new(message.from_user.id)
    # Save group if /start is used in a group
    logger.info(f"Processing /start in chat {message.chat.id}, type: {message.chat.type}")
    if message.chat.type in ["group", "supergroup"]:
        add_group(message.chat.id)
        logger.info(f"Group {message.chat.id} saved via /start")
    kb = types.InlineKeyboardMarkup()
    kb.add(
        types.InlineKeyboardButton("Main Group ✨", url="https://t.me/sexagamechat"),
        types.InlineKeyboardButton("Owner ✨", url="https://t.me/Dark_monarchx")
    )
    bot.reply_to(message, escape_markdown_v2("Welcome! Use /scout to search for shiny Pokémon.\nUse /travel to change region."), reply_markup=kb, parse_mode="MarkdownV2")
    if is_new and LOG_GROUP_ID is not None:
        first = message.from_user.first_name or ""
        username = f"@{message.from_user.username}" if message.from_user.username else ""
        try:
            bot.send_message(
                LOG_GROUP_ID,
                escape_markdown_v2(f"New Trainer: {first} {username} (ID: {message.from_user.id}) started the bot in chat {message.chat.id}."),
                parse_mode="MarkdownV2"
            )
            logger.info(f"Sent start notification for user {message.from_user.id} to log group {LOG_GROUP_ID} (Time: {time.time() - start_time:.2f}s)")
        except Exception as e:
            logger.error(f"Failed to send start notification to log group {LOG_GROUP_ID}: {str(e)}")
    logger.info(f"Start command completed for user {message.from_user.id} (Time: {time.time() - start_time:.2f}s)")

@bot.message_handler(commands=["getid"])
def cmd_getid(message):
    bot.reply_to(message, escape_markdown_v2(f"Chat ID: {message.chat.id}\nChat Type: {message.chat.type}"), parse_mode="MarkdownV2")
    logger.info(f"Chat ID requested: {message.chat.id}, type: {message.chat.type}")

@bot.message_handler(commands=["profile"])
def cmd_profile(message):
    user = get_user(message.from_user.id)
    if not user:
        bot.reply_to(message, escape_markdown_v2("Please /start the bot first."), parse_mode="MarkdownV2")
        return
    tries_left, region = update_user_tries(message.from_user.id)
    if tries_left is None:
        bot.reply_to(message, escape_markdown_v2("Error checking your profile."), parse_mode="MarkdownV2")
        return
    count = len(list_user_pokemon_names(message.from_user.id))
    bot.reply_to(
        message,
        escape_markdown_v2(f"𝐓𝐫𝐚𝐢𝐧𝐞𝐫 𝐏𝐫𝐨𝐟𝐢𝐥𝐞\n➥𝐑𝐞𝐠𝐢𝐨𝐧: {region}\n➥𝐓𝐨𝐭𝐚𝐥 𝐏ó𝐤𝐞𝐦𝐨𝐧𝐬: {count}\n➥𝐃𝐚𝐢𝐥𝐲 𝐬𝐜𝐨𝐮𝐭 𝐋𝐞𝐟𝐭: {tries_left}"),
        parse_mode="MarkdownV2"
    )

@bot.message_handler(commands=["travel"])
def cmd_travel(message):
    user = get_user(message.from_user.id)
    if not user:
        bot.reply_to(message, escape_markdown_v2("Please /start the bot first."), parse_mode="MarkdownV2")
        return
    kb = types.InlineKeyboardMarkup()
    for r in REGIONS:
        kb.add(types.InlineKeyboardButton(r, callback_data=f"travel_{message.from_user.id}_{r}"))
    bot.reply_to(message, escape_markdown_v2("Choose a region:"), reply_markup=kb, parse_mode="MarkdownV2")

@bot.message_handler(commands=["scout"])
def cmd_scout(message):
    asyncio.run(start_scout(message.chat.id, message.from_user.id, message.message_id))

@bot.message_handler(commands=["mypokemon"])
def cmd_mypokemon(message):
    user_id = message.from_user.id
    user = get_user(user_id)
    if not user:
        bot.reply_to(message, escape_markdown_v2("Please /start the bot first."), parse_mode="MarkdownV2")
        return
    names = list_user_pokemon_names(user_id)
    if not names:
        bot.reply_to(message, escape_markdown_v2("You don't have any Pokémon yet."), parse_mode="MarkdownV2")
        return
    page_size = 20
    pages = [names[i:i + page_size] for i in range(0, len(names), page_size)]
    def get_page_text(page_idx):
        page = pages[page_idx]
        return escape_markdown_v2(f"𝕐𝕠𝕦𝕣 ℙ𝕠𝕜é𝕞𝕠𝕟 (Page {page_idx + 1}/{len(pages)}):\n" + "\n".join(f"➥ {n}" for n in page))
    def make_kb(current_page, uid, num_pages):
        kb = types.InlineKeyboardMarkup(row_width=4)
        prev_page = max(0, current_page - 1)
        next_page = min(num_pages - 1, current_page + 1)
        kb.add(
            types.InlineKeyboardButton("<<", callback_data=f"mypoke_{uid}_0"),
            types.InlineKeyboardButton("<", callback_data=f"mypoke_{uid}_{prev_page}"),
            types.InlineKeyboardButton(">", callback_data=f"mypoke_{uid}_{next_page}"),
            types.InlineKeyboardButton(">>", callback_data=f"mypoke_{uid}_{num_pages - 1}")
        )
        return kb
    kb = make_kb(0, user_id, len(pages)) if len(pages) > 1 else None
    bot.reply_to(message, get_page_text(0), reply_markup=kb, parse_mode="MarkdownV2")

@bot.message_handler(commands=["inspect"])
def cmd_inspect(message):
    user = get_user(message.from_user.id)
    if not user:
        bot.reply_to(message, escape_markdown_v2("Please /start the bot first."), parse_mode="MarkdownV2")
        return
    parts = message.text.split(maxsplit=1)
    if len(parts) < 2:
        bot.reply_to(message, escape_markdown_v2("Usage: /inspect <pokemon_name>"), parse_mode="MarkdownV2")
        return
    name = parts[1].strip().lower()
    names = [n.lower() for n in list_user_pokemon_names(message.from_user.id)]
    if name not in names:
        bot.reply_to(message, escape_markdown_v2("You don't own this Pokémon."), parse_mode="MarkdownV2")
        return
    async def fetch_pokemon_image():
        async with aiohttp.ClientSession() as session:
            url = f"https://pokeapi.co/api/v2/pokemon/{name}"
            try:
                async with session.get(url, timeout=15) as response:
                    if response.status != 200:
                        return None
                    data = await response.json()
                    pid = data["id"]
                    return official_shiny_artwork_url(pid)
            except Exception as e:
                logger.error(f"Error inspecting Pokémon {name}: {e}")
                return None
    img_url = asyncio.run(fetch_pokemon_image())
    if not img_url:
        bot.reply_to(message, escape_markdown_v2(f"Couldn't fetch info for {name}."), parse_mode="MarkdownV2")
        return
    bot.send_photo(message.chat.id, img_url, caption=escape_markdown_v2(f"{name.capitalize()} (Shiny)"), parse_mode="MarkdownV2")

@bot.message_handler(commands=["flex"])
def cmd_flex(message):
    try:
        conn = sqlite3.connect(DB_FILE)
        cur = conn.cursor()
        cur.execute("""
            SELECT user_id, COUNT(*) as c
            FROM pokemons
            GROUP BY user_id
            ORDER BY c DESC
            LIMIT 5
        """)
        rows = cur.fetchall()
        conn.close()
        if not rows:
            bot.reply_to(message, escape_markdown_v2("No trainers yet."), parse_mode="MarkdownV2")
            return
        lines = []
        for rank, (uid, cnt) in enumerate(rows, start=1):
            lines.append(f"{rank}\\. User {uid} — {cnt} Pokémon")
        bot.reply_to(message, escape_markdown_v2("*Top Trainers:*\n" + "\n".join(lines)), parse_mode="MarkdownV2")
    except Exception as e:
        logger.error(f"Error in flex command: {e}")
        bot.reply_to(message, escape_markdown_v2("Error fetching top trainers."), parse_mode="MarkdownV2")

@bot.message_handler(commands=["plist"])
def cmd_plist(message):
    if message.from_user.id != OWNER_ID:
        bot.reply_to(message, escape_markdown_v2("𝚃𝚑𝚒𝚜 𝚌𝚘𝚖𝚖𝚊𝚗𝚍 𝚒𝚜 𝚏𝚘𝚛 𝚘𝚠𝚗𝚎𝚛 -𝚜𝚊𝚖𝚊 𝚘𝚗𝚕𝚢."), parse_mode="MarkdownV2")
        return
    parts = message.text.split(maxsplit=1)
    if len(parts) < 2:
        bot.reply_to(message, escape_markdown_v2("Usage: /plist <user_id>"), parse_mode="MarkdownV2")
        return
    try:
        user_id = int(parts[1])
        if not get_user(user_id):
            bot.reply_to(message, escape_markdown_v2("User has not started the bot."), parse_mode="MarkdownV2")
            return
        names = list_user_pokemon_names(user_id)
        if not names:
            bot.reply_to(message, escape_markdown_v2(f"User {user_id} has no Pokémon."), parse_mode="MarkdownV2")
            return
        page_size = 20
        pages = [names[i:i + page_size] for i in range(0, len(names), page_size)]
        def get_page_text(page_idx):
            page = pages[page_idx]
            return escape_markdown_v2(f"*Pokémon for User {user_id} (Page {page_idx + 1}/{len(pages)}):*\n" + "\n".join(f"- {n}" for n in page))
        def make_kb(current_page, uid, num_pages):
            kb = types.InlineKeyboardMarkup(row_width=4)
            prev_page = max(0, current_page - 1)
            next_page = min(num_pages - 1, current_page + 1)
            kb.add(
                types.InlineKeyboardButton("<<", callback_data=f"plist_{uid}_0"),
                types.InlineKeyboardButton("<", callback_data=f"plist_{uid}_{prev_page}"),
                types.InlineKeyboardButton(">", callback_data=f"plist_{uid}_{next_page}"),
                types.InlineKeyboardButton(">>", callback_data=f"plist_{uid}_{num_pages - 1}")
            )
        kb = make_kb(0, user_id, len(pages)) if len(pages) > 1 else None
        bot.reply_to(message, get_page_text(0), reply_markup=kb, parse_mode="MarkdownV2")
    except Exception as e:
        logger.error(f"Error in plist command: {e}")
        bot.reply_to(message, escape_markdown_v2("Error fetching Pokémon list."), parse_mode="MarkdownV2")

@bot.message_handler(commands=["take"])
def cmd_take(message):
    if message.from_user.id != OWNER_ID:
        bot.reply_to(message, escape_markdown_v2("𝚃𝚑𝚒𝚜 𝚌𝚘𝚖𝚖𝚊𝚗𝚍 𝚒𝚜 𝚏𝚘𝚛 𝚘𝚠𝚗𝚎𝚛 -𝚜𝚊𝚖𝚊 𝚘𝚗𝚕𝚢."), parse_mode="MarkdownV2")
        return
    parts = message.text.split(maxsplit=2)
    if len(parts) < 3:
        bot.reply_to(message, escape_markdown_v2("Usage: /take <user_id> <pokemon_name>"), parse_mode="MarkdownV2")
        return
    try:
        uid = int(parts[1])
        poke_name = parts[2].strip().capitalize()
        if not get_user(uid):
            bot.reply_to(message, escape_markdown_v2("User has not started the bot."), parse_mode="MarkdownV2")
            return
        if delete_pokemon(uid, poke_name):
            bot.reply_to(message, escape_markdown_v2(f"Removed {poke_name} from user {uid}."), parse_mode="MarkdownV2")
        else:
            bot.reply_to(message, escape_markdown_v2(f"User {uid} does not have {poke_name}."), parse_mode="MarkdownV2")
    except Exception as e:
        logger.error(f"Error in take command: {e}")
        bot.reply_to(message, escape_markdown_v2(f"Error taking Pokémon: {str(e)}"), parse_mode="MarkdownV2")

@bot.message_handler(commands=["bcast"])
def cmd_bcast(message):
    if message.from_user.id != OWNER_ID:
        bot.reply_to(message, escape_markdown_v2("𝚃𝚑𝚒𝚜 𝚌𝚘𝚖𝚖𝚊𝚗𝚍 𝚒𝚜 𝚏𝚘𝚛 𝚘𝚠𝚗𝚎𝚛 -𝚜𝚊𝚖𝚊 𝚘𝚗𝚕𝚢."), parse_mode="MarkdownV2")
        return
    if not message.reply_to_message:
        bot.reply_to(message, escape_markdown_v2("Please reply to a message to forward to all users."), parse_mode="MarkdownV2")
        return
    users = get_all_users()
    success = 0
    failed = 0
    global last_api_call
    for user_id in users:
        try:
            current_time = time.time()
            if current_time - last_api_call < 0.2:
                time.sleep(0.2)
            bot.forward_message(user_id, message.chat.id, message.reply_to_message.message_id)
            last_api_call = time.time()
            success += 1
        except Exception as e:
            logger.error(f"Failed to forward to user {user_id}: {e}")
            failed += 1
    bot.reply_to(message, escape_markdown_v2(f"Message forwarded to {success} users, failed for {failed} users."), parse_mode="MarkdownV2")

@bot.message_handler(commands=["gcast"])
def cmd_gcast(message):
    if message.from_user.id != OWNER_ID:
        bot.reply_to(message, escape_markdown_v2("𝚃𝚑𝚒𝚜 𝚌𝚘𝚖𝚖𝚊𝚗𝚍 𝚒𝚜 𝚏𝚘𝚛 𝚘𝚠𝚗𝚎𝚛 -𝚜𝚊𝚖𝚊 𝚘𝚗𝚕𝚢."), parse_mode="MarkdownV2")
        return
    if not message.reply_to_message:
        bot.reply_to(message, escape_markdown_v2("Please reply to a message to forward to all groups."), parse_mode="MarkdownV2")
        return
    groups = get_all_groups()
    success = 0
    failed = 0
    global last_api_call
    for group_id in groups:
        try:
            current_time = time.time()
            if current_time - last_api_call < 0.2:
                time.sleep(0.2)
            bot.forward_message(group_id, message.chat.id, message.reply_to_message.message_id)
            last_api_call = time.time()
            success += 1
        except Exception as e:
            logger.error(f"Failed to forward to group {group_id}: {e}")
            failed += 1
    bot.reply_to(message, escape_markdown_v2(f"Message forwarded to {success} groups, failed for {failed} groups."), parse_mode="MarkdownV2")

@bot.message_handler(commands=["gcs"])
def cmd_gcs(message):
    if message.from_user.id != OWNER_ID:
        bot.reply_to(message, escape_markdown_v2("𝚃𝚑𝚒𝚜 𝚌𝚘𝚖𝚖𝚊𝚗𝚍 𝚒𝚜 𝚏𝚘𝚛 𝚘𝚠𝚗𝚎𝚛 -𝚜𝚊𝚖𝚊 𝚘𝚗𝚕𝚢."), parse_mode="MarkdownV2")
        return
    groups = get_all_groups()
    if not groups:
        bot.reply_to(message, escape_markdown_v2("The bot is not in any groups."), parse_mode="MarkdownV2")
        return
    text = escape_markdown_v2(f"*Groups ({len(groups)}):*\n" + "\n".join(f"- {gid}" for gid in groups))
    bot.reply_to(message, text, parse_mode="MarkdownV2")

@bot.message_handler(commands=["allusers"])
def cmd_allusers(message):
    if message.from_user.id != OWNER_ID:
        bot.reply_to(message, escape_markdown_v2("𝚃𝚑𝚒𝚜 𝚌𝚘𝚖𝚖𝚊𝚗𝚍 𝚒𝚜 𝚏𝚘𝚛 𝚘𝚠𝚗𝚎𝚛 -𝚜𝚊𝚖𝚊 𝚘𝚗𝚕𝚢."), parse_mode="MarkdownV2")
        return
    users = get_all_users()
    if not users:
        bot.reply_to(message, escape_markdown_v2("No registered trainers."), parse_mode="MarkdownV2")
        return
    page_size = 20
    pages = [users[i:i + page_size] for i in range(0, len(users), page_size)]
    def get_page_text(page_idx):
        page = pages[page_idx]
        return escape_markdown_v2(f"*Users (Page {page_idx + 1}/{len(pages)}):*\n" + "\n".join(f"- {uid}" for uid in page))
    def make_kb(current_page, num_pages):
        kb = types.InlineKeyboardMarkup(row_width=4)
        prev_page = max(0, current_page - 1)
        next_page = min(num_pages - 1, current_page + 1)
        kb.add(
            types.InlineKeyboardButton("<<", callback_data=f"allusers_0"),
            types.InlineKeyboardButton("<", callback_data=f"allusers_{prev_page}"),
            types.InlineKeyboardButton(">", callback_data=f"allusers_{next_page}"),
            types.InlineKeyboardButton(">>", callback_data=f"allusers_{num_pages - 1}")
        )
        return kb
    kb = make_kb(0, len(pages)) if len(pages) > 1 else None
    bot.reply_to(message, get_page_text(0), reply_markup=kb, parse_mode="MarkdownV2")

@bot.message_handler(commands=["leave"])
def cmd_leave(message):
    if message.from_user.id != OWNER_ID:
        bot.reply_to(message, escape_markdown_v2("𝚃𝚑𝚒𝚜 𝚌𝚘𝚖𝚖𝚊𝚗𝚍 𝚒𝚜 𝚏𝚘𝚛 𝚘𝚠𝚗𝚎𝚛 -𝚜𝚊𝚖𝚊 𝚘𝚗𝚕𝚢."), parse_mode="MarkdownV2")
        return
    parts = message.text.split(maxsplit=1)
    if len(parts) < 2:
        bot.reply_to(message, escape_markdown_v2("Usage: /leave <group_id>"), parse_mode="MarkdownV2")
        return
    try:
        group_id = int(parts[1])
        bot.leave_chat(group_id)
        remove_group(group_id)
        bot.reply_to(message, escape_markdown_v2(f"Left group {group_id}."), parse_mode="MarkdownV2")
        logger.info(f"Bot left group {group_id}")
    except Exception as e:
        logger.error(f"Error leaving group {group_id}: {e}")
        bot.reply_to(message, escape_markdown_v2(f"Error leaving group: {str(e)}"), parse_mode="MarkdownV2")

@bot.message_handler(commands=["release"])
def cmd_release(message):
    user = get_user(message.from_user.id)
    if not user:
        bot.reply_to(message, escape_markdown_v2("Please /start the bot first."), parse_mode="MarkdownV2")
        return
    parts = message.text.split(maxsplit=1)
    if len(parts) < 2:
        bot.reply_to(message, escape_markdown_v2("Usage: /release <pokemon_name>"), parse_mode="MarkdownV2")
        return
    poke_name = parts[1].strip().capitalize()
    if delete_pokemon(message.from_user.id, poke_name):
        bot.reply_to(message, escape_markdown_v2(f"You released {poke_name}."), parse_mode="MarkdownV2")
    else:
        bot.reply_to(message, escape_markdown_v2(f"You don't have {poke_name}."), parse_mode="MarkdownV2")

@bot.message_handler(commands=["give"])
def cmd_give(message):
    if message.from_user.id != OWNER_ID:
        bot.reply_to(message, escape_markdown_v2("𝚃𝚑𝚒𝚜 𝚌𝚘𝚖𝚖𝚊𝚗𝚍 𝚒𝚜 𝚏𝚘𝚛 𝚘𝚠𝚗𝚎𝚛 -𝚜𝚊𝚖𝚊 𝚘𝚗𝚕𝚢."), parse_mode="MarkdownV2")
        return
    parts = message.text.split(maxsplit=2)
    if len(parts) < 3:
        bot.reply_to(message, escape_markdown_v2("Usage: /give <user_id> <pokemon_name>"), parse_mode="MarkdownV2")
        return
    try:
        uid = int(parts[1])
        poke_name = parts[2].strip().capitalize()
        if not get_user(uid):
            bot.reply_to(message, escape_markdown_v2("Target user has not started the bot."), parse_mode="MarkdownV2")
            return
        add_caught_pokemon(uid, poke_name, "Gift")
        bot.reply_to(message, escape_markdown_v2(f"Gave {poke_name} to {uid}."), parse_mode="MarkdownV2")
    except Exception as e:
        logger.error(f"Error in give command: {e}")
        bot.reply_to(message, escape_markdown_v2(f"Error giving Pokémon: {str(e)}"), parse_mode="MarkdownV2")

@bot.message_handler(commands=["reset"])
def cmd_reset(message):
    if message.from_user.id != OWNER_ID:
        bot.reply_to(message, escape_markdown_v2("𝚃𝚑𝚒𝚜 𝚌𝚘𝚖𝚖𝚊𝚗𝚍 𝚒𝚜 𝚏𝚘𝚛 𝚘𝚠𝚗𝚎𝚛 -𝚜𝚊𝚖𝚊 𝚘𝚗𝚕𝚢."), parse_mode="MarkdownV2")
        return
    parts = message.text.split(maxsplit=1)
    if len(parts) < 2:
        bot.reply_to(message, escape_markdown_v2("Usage: /reset <user_id>"), parse_mode="MarkdownV2")
        return
    try:
        uid = int(parts[1])
        if not get_user(uid):
            bot.reply_to(message, escape_markdown_v2("User has not started the bot."), parse_mode="MarkdownV2")
            return
        conn = sqlite3.connect(DB_FILE)
        cur = conn.cursor()
        cur.execute("UPDATE users SET tries_left=300, last_reset=? WHERE user_id=?", (str(datetime.date.today()), uid))
        conn.commit()
        conn.close()
        bot.reply_to(message, escape_markdown_v2(f"Reset scouts for {uid}."), parse_mode="MarkdownV2")
    except Exception as e:
        logger.error(f"Error in reset command: {e}")
        bot.reply_to(message, escape_markdown_v2(f"Error resetting user: {str(e)}"), parse_mode="MarkdownV2")

@bot.message_handler(commands=["backup"])
def cmd_backup(message):
    if message.from_user.id != OWNER_ID:
        bot.reply_to(message, escape_markdown_v2("𝚃𝚑𝚒𝚜 𝚌𝚘𝚖𝚖𝚊𝚗𝚍 𝚒𝚜 𝚏𝚘𝚛 𝚘𝚠𝚗𝚎𝚛 -𝚜𝚊𝚖𝚊 𝚘𝚗𝚕𝚢."), parse_mode="MarkdownV2")
        return
    try:
        if not os.path.exists(DB_FILE):
            bot.reply_to(message, escape_markdown_v2("No database file found."), parse_mode="MarkdownV2")
            return
        with open(DB_FILE, "rb") as f:
            bot.send_document(OWNER_ID, f, caption=escape_markdown_v2("Backup database"), parse_mode="MarkdownV2")
        logger.info("Backup sent successfully")
    except Exception as e:
        logger.error(f"Error in backup command: {e}")
        bot.reply_to(message, escape_markdown_v2(f"Error creating backup: {str(e)}"), parse_mode="MarkdownV2")

@bot.message_handler(commands=["restore"])
def cmd_restore(message):
    if message.from_user.id != OWNER_ID:
        bot.reply_to(message, escape_markdown_v2("𝚃𝚑𝚒𝚜 𝚌𝚘𝚖𝚖𝚊𝚗𝚍 𝚒𝚜 𝚏𝚘𝚛 𝚘𝚠𝚗𝚎𝚛 -𝚜𝚊𝚖𝚊 𝚘𝚗𝚕𝚢."), parse_mode="MarkdownV2")
        return
    bot.reply_to(message, escape_markdown_v2("Send me the *.db file to restore (owner only). Max size: 20MB."), parse_mode="MarkdownV2")
    logger.info(f"Restore command initiated by user {message.from_user.id}")

@bot.message_handler(content_types=["document"])
def handle_restore_file(message):
    if message.from_user.id != OWNER_ID:
        bot.reply_to(message, escape_markdown_v2("𝚃𝚑𝚒𝚜 𝚌𝚘𝚖𝚖𝚊𝚗𝚍 𝚒𝚜 𝚏𝚘𝚛 𝚘𝚠𝚗𝚎𝚛 -𝚜𝚊𝚖𝚊 𝚘𝚗𝚕𝚢."), parse_mode="MarkdownV2")
        return
    if not message.document.file_name.endswith((".db", ".sqlite", ".db3")):
        bot.reply_to(message, escape_markdown_v2("Please upload a file with a .db, .sqlite, or .db3 extension."), parse_mode="MarkdownV2")
        return
    try:
        # Check file size (Telegram bot API limit is 20MB)
        if message.document.file_size > 20 * 1024 * 1024:
            bot.reply_to(message, escape_markdown_v2("File is too large. Maximum size is 20MB."), parse_mode="MarkdownV2")
            logger.error(f"File too large: {message.document.file_size} bytes")
            return
        
        # Backup existing database
        if os.path.exists(DB_FILE):
            backup_file = f"{DB_FILE}.backup_{int(time.time())}"
            shutil.copy(DB_FILE, backup_file)
            logger.info(f"Backed up existing database to {backup_file}")
        
        # Download and save new database
        file_info = bot.get_file(message.document.file_id)
        logger.info(f"Downloaded file info: {file_info.file_path}, size: {message.document.file_size} bytes")
        data = bot.download_file(file_info.file_path)
        logger.info(f"Downloaded {len(data)} bytes")
        with open(DB_FILE, "wb") as f:
            f.write(data)
            logger.info(f"Successfully wrote {DB_FILE}")
        
        # Verify database integrity
        conn = sqlite3.connect(DB_FILE)
        cur = conn.cursor()
        cur.execute("SELECT name FROM sqlite_master WHERE type='table'")
        tables = [row[0] for row in cur.fetchall()]
        
        # Check for required tables and create groups table if missing
        expected_tables = ["users", "pokemons", "groups"]
        if not all(t in tables for t in ["users", "pokemons"]):
            conn.close()
            bot.reply_to(message, escape_markdown_v2(f"Error: Invalid database schema. Missing required tables: users or pokemons. Found: {', '.join(tables)}"), parse_mode="MarkdownV2")
            logger.error(f"Invalid database schema: Missing users or pokemons. Found tables: {tables}")
            return
        if "groups" not in tables:
            cur.execute("CREATE TABLE groups(group_id INTEGER PRIMARY KEY)")
            conn.commit()
            logger.info("Created missing groups table in restored database")
        
        conn.close()
        bot.reply_to(message, escape_markdown_v2("Database restored successfully."), parse_mode="MarkdownV2")
        logger.info("Database restored successfully")
    except Exception as e:
        logger.error(f"Error restoring database: {type(e).__name__}: {str(e)}")
        bot.reply_to(message, escape_markdown_v2(f"Error restoring database: {str(e)}"), parse_mode="MarkdownV2")

@bot.message_handler(commands=["debug"])
def cmd_debug(message):
    if message.from_user.id != OWNER_ID:
        bot.reply_to(message, escape_markdown_v2("𝚃𝚑𝚒𝚜 𝚌𝚘𝚖𝚖𝚊𝚗𝚍 𝚒𝚜 𝚏𝚘𝚛 𝚘𝚠𝚗𝚎𝚛 -𝚜𝚊𝚖𝚊 𝚘𝚗𝚕𝚢."), parse_mode="MarkdownV2")
        return
    try:
        conn = sqlite3.connect(DB_FILE)
        cur = conn.cursor()
        cur.execute("SELECT COUNT(*) FROM users")
        user_count = cur.fetchone()[0]
        cur.execute("SELECT COUNT(*) FROM pokemons")
        pokemon_count = cur.fetchone()[0]
        cur.execute("SELECT COUNT(*) FROM groups")
        group_count = cur.fetchone()[0]
        conn.close()
        active_hunt_count = len(active_hunts)
        status = escape_markdown_v2(
            f"*Bot Debug Info*\n"
            f"Registered trainers: {user_count}\n"
            f"Total Pokémon caught: {pokemon_count}\n"
            f"Active hunts: {active_hunt_count}\n"
            f"Groups: {group_count}\n"
            f"Log group ID: {LOG_GROUP_ID or 'None'}\n"
            f"Bot running: Yes"
        )
        bot.reply_to(message, status, parse_mode="MarkdownV2")
        logger.info(f"Debug info requested by owner {message.from_user.id}")
    except Exception as e:
        logger.error(f"Error in debug command: {e}")
        bot.reply_to(message, escape_markdown_v2(f"Error fetching debug info: {str(e)}"), parse_mode="MarkdownV2")

@bot.message_handler(commands=["clearhunts"])
def cmd_clearhunts(message):
    if message.from_user.id != OWNER_ID:
        bot.reply_to(message, escape_markdown_v2("𝚃𝚑𝚒𝚜 𝚌𝚘𝚖𝚖𝚊𝚗𝚍 𝚒𝚜 𝚏𝚘𝚛 𝚘𝚠𝚗𝚎𝚛 -𝚜𝚊𝚖𝚊 𝚘𝚗𝚕𝚢."), parse_mode="MarkdownV2")
        return
    global active_hunts
    for hunt in active_hunts.values():
        if "timer" in hunt:
            hunt["timer"].cancel()
    active_hunts.clear()
    bot.reply_to(message, escape_markdown_v2("All active hunts cleared."), parse_mode="MarkdownV2")
    logger.info("Active hunts cleared by owner")

# ================== GROUP TRACKING HANDLER ==================
@bot.chat_member_handler()
def handle_chat_member_update(update):
    logger.info(f"Chat member update received: chat_id={update.chat.id}, type={update.chat.type}, status={update.new_chat_member.status}")
    new_status = update.new_chat_member.status
    chat_id = update.chat.id
    if new_status in ["member", "administrator"] and update.chat.type in ["group", "supergroup"]:
        add_group(chat_id)
        logger.info(f"Bot added to group {chat_id}")
    elif new_status in ["kicked", "left"]:
        remove_group(chat_id)
        logger.info(f"Bot removed from group {chat_id}")

# ================== CALLBACKS ==================
@bot.callback_query_handler(func=lambda c: True)
def cb_handler(call):
    try:
        if call.data.startswith("travel_"):
            _, uid_str, region = call.data.split("_", 2)
            uid = int(uid_str)
            if call.from_user.id != uid:
                bot.answer_callback_query(call.id, escape_markdown_v2("This selection is not for you."), parse_mode="MarkdownV2")
                return
            if region not in REGIONS:
                bot.answer_callback_query(call.id, escape_markdown_v2("Invalid region."), parse_mode="MarkdownV2")
                return
            conn = sqlite3.connect(DB_FILE)
            cur = conn.cursor()
            cur.execute("UPDATE users SET region=? WHERE user_id=?", (region, uid))
            conn.commit()
            conn.close()
            bot.edit_message_text(escape_markdown_v2(f"You travelled to {region}."), call.message.chat.id, call.message.message_id, parse_mode="MarkdownV2")
            logger.info(f"User {uid} travelled to {region}")
            return

        if call.data.startswith("catch_"):
            _, uid_str, pid_str, name = call.data.split("_", 3)
            uid = int(uid_str)
            pid = int(pid_str)
            if call.from_user.id != uid:
                bot.answer_callback_query(call.id, escape_markdown_v2("This scout is not yours."), parse_mode="MarkdownV2")
                return
            if call.message.message_id not in active_hunts or active_hunts[call.message.message_id]["user_id"] != uid:
                bot.answer_callback_query(call.id, escape_markdown_v2("This scout has expired."), parse_mode="MarkdownV2")
                return
            if not get_user(uid):
                bot.answer_callback_query(call.id, escape_markdown_v2("Please /start the bot first."), parse_mode="MarkdownV2")
                return
            # Cancel auto-flee timer
            active_hunts[call.message.message_id]["timer"].cancel()
            try:
                bot.edit_message_caption(
                    caption=escape_markdown_v2("Throwing Pokéball..."),
                    chat_id=call.message.chat.id,
                    message_id=call.message.message_id,
                    parse_mode="MarkdownV2"
                )
            except Exception as e:
                logger.error(f"Error updating caption for catch: {e}")
            time.sleep(1.5)
            catch_rate = asyncio.run(get_species_catch_rate(pid))
            success_prob = max(0.05, min(0.95, catch_rate / 255.0))
            success = random.random() < success_prob
            if success:
                add_caught_pokemon(uid, name.capitalize(), get_user(uid)[2])
                try:
                    bot.edit_message_caption(
                        caption=escape_markdown_v2(f"You caught shiny {name.capitalize()}!"),
                        chat_id=call.message.chat.id,
                        message_id=call.message.message_id,
                        parse_mode="MarkdownV2"
                    )
                except Exception as e:
                    logger.error(f"Error updating caption for successful catch: {e}")
            else:
                try:
                    bot.edit_message_caption(
                        caption=escape_markdown_v2(f"Oh no! Shiny {name.capitalize()} escaped!"),
                        chat_id=call.message.chat.id,
                        message_id=call.message.message_id,
                        parse_mode="MarkdownV2"
                    )
                except Exception as e:
                    logger.error(f"Error updating caption for failed catch: {e}")
            active_hunts.pop(call.message.message_id, None)
            return

        if call.data.startswith("run_"):
            _, uid_str, name = call.data.split("_", 2)
            uid = int(uid_str)
            if call.from_user.id != uid:
                bot.answer_callback_query(call.id, escape_markdown_v2("This scout is not yours."), parse_mode="MarkdownV2")
                return
            if call.message.message_id not in active_hunts or active_hunts[call.message.message_id]["user_id"] != uid:
                bot.answer_callback_query(call.id, escape_markdown_v2("This scout has expired."), parse_mode="MarkdownV2")
                return
            # Cancel auto-flee timer
            active_hunts[call.message.message_id]["timer"].cancel()
            try:
                bot.edit_message_caption(
                    caption=escape_markdown_v2(f"You ran away from shiny {name.capitalize()}."),
                    chat_id=call.message.chat.id,
                    message_id=call.message.message_id,
                    parse_mode="MarkdownV2"
                )
            except Exception as e:
                logger.error(f"Error updating caption for run: {e}")
            active_hunts.pop(call.message.message_id, None)
            return

        if call.data.startswith("mypoke_"):
            _, uid_str, page_str = call.data.split("_")
            uid = int(uid_str)
            if call.from_user.id != uid:
                bot.answer_callback_query(call.id, escape_markdown_v2("This is not your list."), parse_mode="MarkdownV2")
                return
            page_idx = int(page_str)
            names = list_user_pokemon_names(uid)
            if not names:
                bot.edit_message_text(escape_markdown_v2("You don't have any Pokémon yet."), call.message.chat.id, call.message.message_id, parse_mode="MarkdownV2")
                return
            page_size = 20
            pages = [names[i:i + page_size] for i in range(0, len(names), page_size)]
            if page_idx < 0 or page_idx >= len(pages):
                return
            text = escape_markdown_v2(f"*𝐘𝐨𝐮𝐫 𝐏𝐨𝐤é𝐦𝐨𝐧 (Page {page_idx + 1}/{len(pages)}):*\n" + "\n".join(f"➥ {n}" for n in pages[page_idx]))
            def make_kb(current_page, num_pages):
                kb = types.InlineKeyboardMarkup(row_width=4)
                prev_page = max(0, current_page - 1)
                next_page = min(num_pages - 1, current_page + 1)
                kb.add(
                    types.InlineKeyboardButton("<<", callback_data=f"mypoke_{uid}_0"),
                    types.InlineKeyboardButton("<", callback_data=f"mypoke_{uid}_{prev_page}"),
                    types.InlineKeyboardButton(">", callback_data=f"mypoke_{uid}_{next_page}"),
                    types.InlineKeyboardButton(">>", callback_data=f"mypoke_{uid}_{num_pages - 1}")
                )
                return kb
            kb = make_kb(page_idx, len(pages)) if len(pages) > 1 else None
            bot.edit_message_text(text, call.message.chat.id, call.message.message_id, reply_markup=kb, parse_mode="MarkdownV2")
            return

        if call.data.startswith("plist_"):
            _, uid_str, page_str = call.data.split("_")
            uid = int(uid_str)
            if call.from_user.id != OWNER_ID:
                bot.answer_callback_query(call.id, escape_markdown_v2("𝚃𝚑𝚒𝚜 𝚌𝚘𝚖𝚖𝚊𝚗𝚍 𝚒𝚜 𝚏𝚘𝚛 𝚘𝚠𝚗𝚎𝚛 -𝚜𝚊𝚖𝚊 𝚘𝚗𝚕𝚢."), parse_mode="MarkdownV2")
                return
            page_idx = int(page_str)
            names = list_user_pokemon_names(uid)
            if not names:
                bot.edit_message_text(escape_markdown_v2(f"User {uid} has no Pokémon."), call.message.chat.id, call.message.message_id, parse_mode="MarkdownV2")
                return
            page_size = 20
            pages = [names[i:i + page_size] for i in range(0, len(names), page_size)]
            if page_idx < 0 or page_idx >= len(pages):
                return
            text = escape_markdown_v2(f"*Pokémon for User {uid} (Page {page_idx + 1}/{len(pages)}):*\n" + "\n".join(f"- {n}" for n in pages[page_idx]))
            def make_kb(current_page, num_pages):
                kb = types.InlineKeyboardMarkup(row_width=4)
                prev_page = max(0, current_page - 1)
                next_page = min(num_pages - 1, current_page + 1)
                kb.add(
                    types.InlineKeyboardButton("<<", callback_data=f"plist_{uid}_0"),
                    types.InlineKeyboardButton("<", callback_data=f"plist_{uid}_{prev_page}"),
                    types.InlineKeyboardButton(">", callback_data=f"plist_{uid}_{next_page}"),
                    types.InlineKeyboardButton(">>", callback_data=f"plist_{uid}_{num_pages - 1}")
                )
                return kb
            kb = make_kb(page_idx, len(pages)) if len(pages) > 1 else None
            bot.edit_message_text(text, call.message.chat.id, call.message.message_id, reply_markup=kb, parse_mode="MarkdownV2")
            return

        if call.data.startswith("allusers_"):
            _, page_str = call.data.split("_")
            if call.from_user.id != OWNER_ID:
                bot.answer_callback_query(call.id, escape_markdown_v2("𝚃𝚑𝚒𝚜 𝚌𝚘𝚖𝚖𝚊𝚗𝚍 𝚒𝚜 𝚏𝚘𝚛 𝚘𝚠𝚗𝚎𝚛 -𝚜𝚊𝚖𝚊 𝚘𝚗𝚕𝚢."), parse_mode="MarkdownV2")
                return
            page_idx = int(page_str)
            users = get_all_users()
            if not users:
                bot.edit_message_text(escape_markdown_v2("No registered trainers."), call.message.chat.id, call.message.message_id, parse_mode="MarkdownV2")
                return
            page_size = 20
            pages = [users[i:i + page_size] for i in range(0, len(users), page_size)]
            if page_idx < 0 or page_idx >= len(pages):
                return
            text = escape_markdown_v2(f"*Users (Page {page_idx + 1}/{len(pages)}):*\n" + "\n".join(f"- {uid}" for uid in pages[page_idx]))
            def make_kb(current_page, num_pages):
                kb = types.InlineKeyboardMarkup(row_width=4)
                prev_page = max(0, current_page - 1)
                next_page = min(num_pages - 1, current_page + 1)
                kb.add(
                    types.InlineKeyboardButton("<<", callback_data=f"allusers_0"),
                    types.InlineKeyboardButton("<", callback_data=f"allusers_{prev_page}"),
                    types.InlineKeyboardButton(">", callback_data=f"allusers_{next_page}"),
                    types.InlineKeyboardButton(">>", callback_data=f"allusers_{num_pages - 1}")
                )
                return kb
            kb = make_kb(page_idx, len(pages)) if len(pages) > 1 else None
            bot.edit_message_text(text, call.message.chat.id, call.message.message_id, reply_markup=kb, parse_mode="MarkdownV2")
            return

        if call.data.startswith("gcs_"):
            _, page_str = call.data.split("_")
            if call.from_user.id != OWNER_ID:
                bot.answer_callback_query(call.id, escape_markdown_v2("𝚃𝚑𝚒𝚜 𝚌𝚘𝚖𝚖𝚊𝚗𝚍 𝚒𝚜 𝚏𝚘𝚛 𝚘𝚠𝚗𝚎𝚛 -𝚜𝚊𝚖𝚊 𝚘𝚗𝚕𝚢."), parse_mode="MarkdownV2")
                return
            page_idx = int(page_str)
            groups = get_all_groups()
            if not groups:
                bot.edit_message_text(escape_markdown_v2("The bot is not in any groups."), call.message.chat.id, call.message.message_id, parse_mode="MarkdownV2")
                return
            page_size = 20
            pages = [groups[i:i + page_size] for i in range(0, len(groups), page_size)]
            if page_idx < 0 or page_idx >= len(pages):
                return
            text = escape_markdown_v2(f"*Groups (Page {page_idx + 1}/{len(pages)}):*\n" + "\n".join(f"- {gid}" for gid in pages[page_idx]))
            def make_kb(current_page, num_pages):
                kb = types.InlineKeyboardMarkup(row_width=4)
                prev_page = max(0, current_page - 1)
                next_page = min(num_pages - 1, current_page + 1)
                kb.add(
                    types.InlineKeyboardButton("<<", callback_data=f"gcs_0"),
                    types.InlineKeyboardButton("<", callback_data=f"gcs_{prev_page}"),
                    types.InlineKeyboardButton(">", callback_data=f"gcs_{next_page}"),
                    types.InlineKeyboardButton(">>", callback_data=f"gcs_{num_pages - 1}")
                )
                return kb
            kb = make_kb(page_idx, len(pages)) if len(pages) > 1 else None
            bot.edit_message_text(text, call.message.chat.id, call.message.message_id, reply_markup=kb, parse_mode="MarkdownV2")
            return

    except Exception as e:
        logger.error(f"Callback handler error: {e}")
        bot.answer_callback_query(call.id, escape_markdown_v2(f"An error occurred: {str(e)}"), parse_mode="MarkdownV2")

# ================== RUN ==================
if __name__ == "__main__":
    init_db()
    logger.info("Bot is starting...")
    try:
        bot.delete_webhook()
        logger.info("Webhook deleted, running in polling mode")
        bot.infinity_polling(skip_pending=True)
    except Exception as e:
        logger.error(f"Polling error: {e}")
