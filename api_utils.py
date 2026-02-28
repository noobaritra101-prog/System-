# api_utils.py
import aiohttp
import random
import time
import re
from config import logger, MEGA_POKEMON

pokemon_cache = {}  # Cache for Pokémon ID:name pairs

def escape_markdown_v2(text):
    """Escape special characters for MarkdownV2."""
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
                    logger.error(f"PokeAPI error: Status {response.status} for ID {poke_id}")
                    return None, None, None
                data = await response.json()
                name = data["name"].capitalize()
                pokemon_cache[poke_id] = name
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
                    return 127
                data = await response.json()
                return data.get("capture_rate", 127) or 127
        except Exception as e:
            logger.error(f"PokeAPI species request failed for ID {poke_id}: {e}")
            return 127
