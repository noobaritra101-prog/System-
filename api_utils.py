# api_utils.py
import aiohttp
import urllib.request
import json
import random
import re
import asyncio
from config import logger, MEGA_POKEMON

pokemon_cache = {}

def escape_md(text):
    """Safely escape text for MarkdownV2 without breaking formatting."""
    special_chars = r'([_\*\[\]\(\)~`>\#\+\-=\|\{\}\.\!])'
    return re.sub(special_chars, r'\\\1', str(text))

def fetch_random_pokemon_id_and_name_sync():
    """Ultra-fast synchronous fetch for /scout to avoid asyncio overhead."""
    if random.random() < 0.05:
        poke_id, name, base_id = random.choice(MEGA_POKEMON)
        return poke_id, name, base_id
    
    poke_id = random.randint(1, 898)
    if poke_id in pokemon_cache:
        return poke_id, pokemon_cache[poke_id], poke_id
        
    try:
        url = f"https://pokeapi.co/api/v2/pokemon/{poke_id}"
        req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
        with urllib.request.urlopen(req, timeout=5) as response:
            data = json.loads(response.read().decode())
            name = data["name"].capitalize()
            pokemon_cache[poke_id] = name
            return poke_id, name, poke_id
    except Exception as e:
        logger.error(f"PokeAPI sync request failed: {e}")
        return None, None, None

def official_shiny_artwork_url(poke_id):
    return f"https://raw.githubusercontent.com/PokeAPI/sprites/master/sprites/pokemon/other/official-artwork/shiny/{poke_id}.png"

def get_species_catch_rate_sync(poke_id):
    """Synchronous API call to prevent deadlocks in the callback thread."""
    try:
        url = f"https://pokeapi.co/api/v2/pokemon-species/{poke_id}"
        req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
        with urllib.request.urlopen(req, timeout=5) as response:
            data = json.loads(response.read().decode())
            return data.get("capture_rate", 127) or 127
    except Exception as e:
        logger.error(f"Catch rate fetch failed for {poke_id}: {e}")
        return 127

def get_pokemon_stats_sync(pokemon_name):
    """Synchronous API call to fetch types and base stats for the Pokédex."""
    try:
        url = f"https://pokeapi.co/api/v2/pokemon/{pokemon_name.lower()}"
        req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
        with urllib.request.urlopen(req, timeout=5) as response:
            data = json.loads(response.read().decode())
            types = [t["type"]["name"].capitalize() for t in data["types"]]
            stats = {s["stat"]["name"].replace("-", " ").capitalize(): s["base_stat"] for s in data["stats"]}
            return types, stats
    except Exception as e:
        logger.error(f"Stats fetch failed for {pokemon_name}: {e}")
        return None, None

async def fetch_move_type(session, url):
    """Fetches the element type of a specific move."""
    try:
        async with session.get(url, timeout=5) as response:
            if response.status == 200:
                data = await response.json()
                return data["type"]["name"].capitalize()
    except: pass
    return "Normal"

async def fetch_random_pvp_pokemon():
    """Fetches a random Pokémon, its stats, types, and 4 detailed moves for PvP."""
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
                
                # Pick 4 random moves from their actual movepool
                all_moves = data.get("moves", [])
                selected_moves = random.sample(all_moves, min(4, len(all_moves)))
                
                async def build_move(m):
                    m_name = m["move"]["name"].replace("-", " ").capitalize()
                    m_type = await fetch_move_type(session, m["move"]["url"])
                    return {
                        "name": m_name,
                        "power": random.randint(50, 110),
                        "acc": random.choice([80, 85, 90, 95, 100, 100]),
                        "type": m_type
                    }
                    
                moves = await asyncio.gather(*(build_move(m) for m in selected_moves))
                while len(moves) < 4: 
                    moves.append({"name": "Tackle", "power": 40, "acc": 100, "type": "Normal"})
                
                hp = int(stats.get("hp", 50)) * 3 
                
                return {
                    "name": name,
                    "types": types,
                    "hp": hp,
                    "max_hp": hp,
                    "atk": stats.get("attack", 50),
                    "def": stats.get("defense", 50),
                    "spd": stats.get("speed", 50),
                    "moves": moves
                }
        except Exception as e:
            logger.error(f"PvP Fetch Error: {e}")
            return None

async def generate_random_team():
    """Fetches 6 random Pokémon simultaneously for a PvP team."""
    tasks = [fetch_random_pvp_pokemon() for _ in range(6)]
    team = await asyncio.gather(*tasks)
    return [p for p in team if p is not None]
