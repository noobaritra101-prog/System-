# api_utils.py
import aiohttp
import urllib.request
import json
import random
import re
from config import logger, MEGA_POKEMON

pokemon_cache = {}

def escape_md(text):
    """Safely escape text for MarkdownV2 without breaking formatting."""
    special_chars = r'([_\*\[\]\(\)~`>\#\+\-=\|\{\}\.\!])'
    return re.sub(special_chars, r'\\\1', str(text))

async def fetch_random_pokemon_id_and_name():
    if random.random() < 0.05:
        poke_id, name, base_id = random.choice(MEGA_POKEMON)
        return poke_id, name, base_id
    
    poke_id = random.randint(1, 898)
    if poke_id in pokemon_cache:
        return poke_id, pokemon_cache[poke_id], poke_id
        
    async with aiohttp.ClientSession() as session:
        url = f"https://pokeapi.co/api/v2/pokemon/{poke_id}"
        try:
            async with session.get(url, timeout=15) as response:
                if response.status != 200:
                    return None, None, None
                data = await response.json()
                name = data["name"].capitalize()
                pokemon_cache[poke_id] = name
                return poke_id, name, poke_id
        except Exception as e:
            logger.error(f"PokeAPI request failed: {e}")
            return None, None, None

def official_shiny_artwork_url(poke_id):
    return f"https://raw.githubusercontent.com/PokeAPI/sprites/master/sprites/pokemon/other/official-artwork/shiny/{poke_id}.png"

def default_pokemon_image():
    return "https://raw.githubusercontent.com/PokeAPI/sprites/master/sprites/pokemon/other/official-artwork/1.png"

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
