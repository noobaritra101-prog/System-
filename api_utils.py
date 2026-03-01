# api_utils.py
import aiohttp
import urllib.request
import json
import random
import re
import asyncio
import threading
from config import logger, MEGA_POKEMON

pokemon_cache = {}
pokemon_name_to_id_cache = {}

# --- CACHE BUILDER (MAKES /SCOUT INSTANT) ---
def build_cache():
    """Fetches all 898 Pokemon names/IDs once on startup so /scout has 0 latency."""
    try:
        url = "https://pokeapi.co/api/v2/pokemon?limit=898"
        req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
        with urllib.request.urlopen(req, timeout=10) as response:
            data = json.loads(response.read().decode())
            for i, result in enumerate(data['results'], start=1):
                name = result['name'].capitalize()
                pokemon_cache[i] = name
                pokemon_name_to_id_cache[name.lower()] = i
        logger.info("✅ Pokémon cache built! /scout is now instant.")
    except Exception as e:
        logger.error(f"Failed to build cache: {e}")

# Start caching in the background immediately
threading.Thread(target=build_cache, daemon=True).start()

def escape_md(text):
    """Safely escape text for MarkdownV2 without breaking formatting."""
    special_chars = r'([_\*\[\]\(\)~`>\#\+\-=\|\{\}\.\!])'
    return re.sub(special_chars, r'\\\1', str(text))

def fetch_random_pokemon_id_and_name_sync():
    """Ultra-fast lookup from memory cache."""
    if random.random() < 0.05:
        poke_id, name, base_id = random.choice(MEGA_POKEMON)
        return poke_id, name, base_id
    
    poke_id = random.randint(1, 898)
    
    # 99.9% of the time, this will instantly return from memory
    if poke_id in pokemon_cache:
        return poke_id, pokemon_cache[poke_id], poke_id
        
    # Fallback if cache is still building
    try:
        url = f"https://pokeapi.co/api/v2/pokemon/{poke_id}"
        req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
        with urllib.request.urlopen(req, timeout=5) as response:
            data = json.loads(response.read().decode())
            name = data["name"].capitalize()
            pokemon_cache[poke_id] = name
            pokemon_name_to_id_cache[name.lower()] = poke_id
            return poke_id, name, poke_id
    except Exception as e:
        logger.error(f"PokeAPI sync request failed: {e}")
        return None, None, None

def get_pokemon_id_sync(pokemon_name):
    """Translates a name back to an ID for /inspect."""
    name_lower = pokemon_name.lower()
    if name_lower in pokemon_name_to_id_cache:
        return pokemon_name_to_id_cache[name_lower]
    
    # Fallback
    try:
        url = f"https://pokeapi.co/api/v2/pokemon/{name_lower}"
        req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
        with urllib.request.urlopen(req, timeout=5) as response:
            data = json.loads(response.read().decode())
            poke_id = data["id"]
            pokemon_name_to_id_cache[name_lower] = poke_id
            pokemon_cache[poke_id] = data["name"].capitalize()
            return poke_id
    except:
        return None

def official_shiny_artwork_url(poke_id):
    return f"https://raw.githubusercontent.com/PokeAPI/sprites/master/sprites/pokemon/other/official-artwork/shiny/{poke_id}.png"

def get_species_catch_rate_sync(poke_id):
    try:
        url = f"https://pokeapi.co/api/v2/pokemon-species/{poke_id}"
        req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
        with urllib.request.urlopen(req, timeout=5) as response:
            data = json.loads(response.read().decode())
            return data.get("capture_rate", 127) or 127
    except: return 127

def get_pokemon_stats_sync(pokemon_name):
    try:
        url = f"https://pokeapi.co/api/v2/pokemon/{pokemon_name.lower()}"
        req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
        with urllib.request.urlopen(req, timeout=5) as response:
            data = json.loads(response.read().decode())
            types = [t["type"]["name"].capitalize() for t in data["types"]]
            stats = {s["stat"]["name"].replace("-", " ").capitalize(): s["base_stat"] for s in data["stats"]}
            return types, stats
    except: return None, None

async def fetch_move_type(session, url):
    try:
        async with session.get(url, timeout=5) as response:
            if response.status == 200:
                data = await response.json()
                return data["type"]["name"].capitalize()
    except: pass
    return "Normal"

async def fetch_random_pvp_pokemon():
    poke_id = random.randint(1, 898)
    async with aiohttp.ClientSession() as session:
        url = f"https://pokeapi.co/api/v2/pokemon/{poke_id}"
        try:
            async with session.get(url, timeout=10) as response:
                if response.status != 200: return None
                data = await response.json()
                name = data["name"].capitalize()
                stats = {s["stat"]["name"]: s["base_stat"] for s in data["stats"]}
                types = "/".join([t["type"]["name"].capitalize() for t in data.get("types", [])])
                
                all_moves = data.get("moves", [])
                selected_moves = random.sample(all_moves, min(4, len(all_moves)))
                
                async def build_move(m):
                    m_name = m["move"]["name"].replace("-", " ").capitalize()
                    m_type = await fetch_move_type(session, m["move"]["url"])
                    
                    s_type, s_chance = None, 0
                    if m_type == "Fire": s_type, s_chance = "BRN", 15
                    elif m_type == "Electric": s_type, s_chance = "PAR", 15
                    elif m_type == "Poison": s_type, s_chance = "PSN", 20
                    elif m_type == "Ice": s_type, s_chance = "FRZ", 10
                    elif m_type == "Grass": s_type, s_chance = "SLP", 15
                    
                    return {
                        "name": m_name,
                        "power": random.randint(50, 110),
                        "acc": random.choice([80, 85, 90, 95, 100, 100]),
                        "type": m_type,
                        "status_type": s_type,
                        "status_chance": s_chance
                    }
                    
                moves = await asyncio.gather(*(build_move(m) for m in selected_moves))
                while len(moves) < 4: 
                    moves.append({"name": "Tackle", "power": 40, "acc": 100, "type": "Normal", "status_type": None, "status_chance": 0})
                
                hp = int(stats.get("hp", 50)) * 3 
                
                return {
                    "name": name,
                    "types": types,
                    "hp": hp,
                    "max_hp": hp,
                    "atk": stats.get("attack", 50),
                    "def": stats.get("defense", 50),
                    "spd": stats.get("speed", 50),
                    "moves": moves,
                    "status": None,       
                    "sleep_turns": 0
                }
        except Exception as e:
            logger.error(f"PvP Fetch Error: {e}")
            return None

async def generate_random_team():
    tasks = [fetch_random_pvp_pokemon() for _ in range(6)]
    team = await asyncio.gather(*tasks)
    return [p for p in team if p is not None]
