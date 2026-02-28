# api_utils.py
import aiohttp
import random
import re
import asyncio
from config import logger, MEGA_POKEMON

pokemon_cache = {}

def escape_md(text):
    special_chars = r'([_\*\[\]\(\)~`>\#\+\-=\|\{\}\.\!])'
    return re.sub(special_chars, r'\\\1', str(text))

async def fetch_random_pokemon_id_and_name():
    if random.random() < 0.05:
        poke_id, name, base_id = random.choice(MEGA_POKEMON)
        return poke_id, name, base_id
    
    poke_id = random.randint(1, 898)
    if poke_id in pokemon_cache: return poke_id, pokemon_cache[poke_id], poke_id
        
    async with aiohttp.ClientSession() as session:
        try:
            async with session.get(f"https://pokeapi.co/api/v2/pokemon/{poke_id}", timeout=15) as response:
                if response.status != 200: return None, None, None
                data = await response.json()
                name = data["name"].capitalize()
                pokemon_cache[poke_id] = name
                return poke_id, name, poke_id
        except Exception as e:
            logger.error(f"PokeAPI error: {e}")
            return None, None, None

def official_shiny_artwork_url(poke_id):
    return f"https://raw.githubusercontent.com/PokeAPI/sprites/master/sprites/pokemon/other/official-artwork/shiny/{poke_id}.png"

def default_pokemon_image():
    return "https://raw.githubusercontent.com/PokeAPI/sprites/master/sprites/pokemon/other/official-artwork/1.png"

async def get_species_catch_rate_async(poke_id):
    async with aiohttp.ClientSession() as session:
        try:
            async with session.get(f"https://pokeapi.co/api/v2/pokemon-species/{poke_id}", timeout=5) as response:
                if response.status != 200: return 127
                data = await response.json()
                return data.get("capture_rate", 127) or 127
        except: return 127

async def get_pokemon_stats_async(pokemon_name):
    async with aiohttp.ClientSession() as session:
        try:
            async with session.get(f"https://pokeapi.co/api/v2/pokemon/{pokemon_name.lower()}", timeout=5) as response:
                if response.status != 200: return None, None
                data = await response.json()
                types = [t["type"]["name"].capitalize() for t in data["types"]]
                stats = {s["stat"]["name"].replace("-", " ").capitalize(): s["base_stat"] for s in data["stats"]}
                return types, stats
        except: return None, None

async def fetch_random_pvp_pokemon():
    poke_id = random.randint(1, 898)
    async with aiohttp.ClientSession() as session:
        try:
            async with session.get(f"https://pokeapi.co/api/v2/pokemon/{poke_id}", timeout=10) as response:
                if response.status != 200: return None
                data = await response.json()
                name = data["name"].capitalize()
                stats = {s["stat"]["name"]: s["base_stat"] for s in data["stats"]}
                
                all_moves = data.get("moves", [])
                selected_moves = random.sample(all_moves, min(4, len(all_moves)))
                moves = [m["move"]["name"].replace("-", " ").capitalize() for m in selected_moves]
                while len(moves) < 4: moves.append("Tackle")
                
                hp = int(stats.get("hp", 50)) * 3 
                return {
                    "name": name, "hp": hp, "max_hp": hp,
                    "atk": stats.get("attack", 50), "def": stats.get("defense", 50),
                    "spd": stats.get("speed", 50), "moves": moves
                }
        except: return None

async def generate_random_team():
    tasks = [fetch_random_pvp_pokemon() for _ in range(6)]
    team = await asyncio.gather(*tasks)
    return [p for p in team if p is not None]
