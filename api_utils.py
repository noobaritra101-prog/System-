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

# --- GUARANTEED STAB MOVES FOR FULLY EVOLVED POKEMON ---
STRONG_STAB_MOVES = {
    'Normal': 'Hyper Voice', 'Fire': 'Flamethrower', 'Water': 'Hydro Pump',
    'Electric': 'Thunderbolt', 'Grass': 'Energy Ball', 'Ice': 'Ice Beam',
    'Fighting': 'Close Combat', 'Poison': 'Sludge Bomb', 'Ground': 'Earthquake',
    'Flying': 'Hurricane', 'Psychic': 'Psychic', 'Bug': 'Bug Buzz',
    'Rock': 'Stone Edge', 'Ghost': 'Shadow Ball', 'Dragon': 'Dragon Pulse',
    'Dark': 'Dark Pulse', 'Steel': 'Flash Cannon', 'Fairy': 'Moonblast'
}

def build_cache():
    """Fetches all 898 Pokemon names/IDs once on startup so /scout is instant."""
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

threading.Thread(target=build_cache, daemon=True).start()

def escape_md(text):
    special_chars = r'([_\*\[\]\(\)~`>\#\+\-=\|\{\}\.\!])'
    return re.sub(special_chars, r'\\\1', str(text))

def fetch_random_pokemon_id_and_name_sync():
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
            pokemon_name_to_id_cache[name.lower()] = poke_id
            return poke_id, name, poke_id
    except Exception as e:
        logger.error(f"PokeAPI sync request failed: {e}")
        return None, None, None

def get_pokemon_id_sync(pokemon_name):
    name_lower = pokemon_name.lower()
    if name_lower in pokemon_name_to_id_cache:
        return pokemon_name_to_id_cache[name_lower]
    try:
        url = f"https://pokeapi.co/api/v2/pokemon/{name_lower}"
        req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
        with urllib.request.urlopen(req, timeout=5) as response:
            data = json.loads(response.read().decode())
            poke_id = data["id"]
            pokemon_name_to_id_cache[name_lower] = poke_id
            pokemon_cache[poke_id] = data["name"].capitalize()
            return poke_id
    except: return None

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
    async with aiohttp.ClientSession() as session:
        while True: # Loop until we find a fully evolved Pokemon
            poke_id = random.randint(1, 898)
            url = f"https://pokeapi.co/api/v2/pokemon/{poke_id}"
            try:
                async with session.get(url, timeout=10) as response:
                    if response.status != 200: continue
                    data = await response.json()
                    
                    # REQUIREMENT 1: Only Fully Evolved Pokemon
                    # Base experience > 150 filters out weak babies and mid-stages!
                    if data.get("base_experience", 0) < 150:
                        continue 

                    name = data["name"].capitalize()
                    stats = {s["stat"]["name"]: s["base_stat"] for s in data["stats"]}
                    
                    types_list = [t["type"]["name"].capitalize() for t in data.get("types", [])]
                    types_str = "/".join(types_list)
                    primary_type = types_list[0]
                    
                    # REQUIREMENT 2: Guaranteed STAB move with 80-120 Power
                    moves = []
                    guaranteed_move_name = STRONG_STAB_MOVES.get(primary_type, "Hyper Beam")
                    moves.append({
                        "name": guaranteed_move_name,
                        "power": random.randint(80, 120),
                        "acc": random.choice([85, 90, 95, 100]),
                        "type": primary_type,
                        "status_type": None,
                        "status_chance": 0
                    })
                    
                    # Fetch 3 other random moves to fill the rest of the slots
                    all_moves = data.get("moves", [])
                    selected_moves = random.sample(all_moves, min(3, len(all_moves)))
                    
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
                        
                    fetched_moves = await asyncio.gather(*(build_move(m) for m in selected_moves))
                    moves.extend(fetched_moves)
                    
                    while len(moves) < 4: 
                        moves.append({"name": "Tackle", "power": 40, "acc": 100, "type": "Normal", "status_type": None, "status_chance": 0})
                    
                    # Shuffle so the guaranteed strong STAB move isn't always in the first button
                    random.shuffle(moves)
                    
                    hp = int(stats.get("hp", 50)) * 3 
                    
                    return {
                        "name": name,
                        "types": types_str,
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
