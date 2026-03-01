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

# Comprehensive list of Legendary, Mythical, and Ultra Beast Pokémon
LEGENDARY_NAMES = {
    "Articuno", "Zapdos", "Moltres", "Mewtwo", "Mew", "Raikou", "Entei", "Suicune", 
    "Lugia", "Ho-oh", "Celebi", "Regirock", "Regice", "Registeel", "Latias", "Latios", 
    "Kyogre", "Groudon", "Rayquaza", "Jirachi", "Deoxys", "Uxie", "Mesprit", "Azelf", 
    "Dialga", "Palkia", "Heatran", "Regigigas", "Giratina", "Cresselia", "Phione", 
    "Manaphy", "Darkrai", "Shaymin", "Arceus", "Victini", "Cobalion", "Terrakion", 
    "Virizion", "Tornadus", "Thundurus", "Reshiram", "Zekrom", "Landorus", "Kyurem", 
    "Keldeo", "Meloetta", "Genesect", "Xerneas", "Yveltal", "Zygarde", "Diancie", 
    "Hoopa", "Volcanion", "Type: null", "Silvally", "Tapu koko", "Tapu lele", "Tapu bulu", 
    "Tapu fini", "Cosmog", "Cosmoem", "Solgaleo", "Lunala", "Nihilego", "Buzzwole", 
    "Pheromosa", "Xurkitree", "Celesteela", "Kartana", "Guzzlord", "Necrozma", "Magearna", 
    "Marshadow", "Poipole", "Naganadel", "Stakataka", "Blacephalon", "Zeraora", "Meltan", 
    "Melmetal", "Zacian", "Zamazenta", "Eternatus", "Kubfu", "Urshifu", "Zarude", 
    "Regieleki", "Regidrago", "Glastrier", "Spectrier", "Calyrex"
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

# Start the cache builder in the background immediately
threading.Thread(target=build_cache, daemon=True).start()

def escape_md(text):
    """Safely escape text for Telegram MarkdownV2."""
    special_chars = r'([_\*\[\]\(\)~`>\#\+\-=\|\{\}\.\!])'
    return re.sub(special_chars, r'\\\1', str(text))

def fetch_random_pokemon_id_and_name_sync():
    """Used for /scout. Ultra-fast lookup from memory cache."""
    if random.random() < 0.05:
        poke_id, name, base_id = random.choice(MEGA_POKEMON)
        return poke_id, name, base_id
    
    poke_id = random.randint(1, 898)
    
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
    """Translates a text name back to a numeric ID for /inspect."""
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
    except: 
        return None

def official_shiny_artwork_url(poke_id):
    return f"https://raw.githubusercontent.com/PokeAPI/sprites/master/sprites/pokemon/other/official-artwork/shiny/{poke_id}.png"

def get_species_catch_rate_sync(poke_id):
    try:
        url = f"https://pokeapi.co/api/v2/pokemon-species/{poke_id}"
        req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
        with urllib.request.urlopen(req, timeout=5) as response:
            return json.loads(response.read().decode()).get("capture_rate", 127) or 127
    except: 
        return 127

def get_pokemon_stats_sync(pokemon_name):
    try:
        url = f"https://pokeapi.co/api/v2/pokemon/{pokemon_name.lower()}"
        req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
        with urllib.request.urlopen(req, timeout=5) as response:
            data = json.loads(response.read().decode())
            types = [t["type"]["name"].capitalize() for t in data["types"]]
            stats = {s["stat"]["name"].replace("-", " ").capitalize(): s["base_stat"] for s in data["stats"]}
            return types, stats
    except: 
        return None, None

async def fetch_real_move_data(session, url):
    """Fetches authentic power, accuracy, and type for a specific move."""
    try:
        async with session.get(url, timeout=5) as response:
            if response.status == 200:
                data = await response.json()
                power = data.get("power")
                
                # Filter out status moves (0 power)
                if not power: 
                    return None
                
                m_type = data["type"]["name"].capitalize()
                # If accuracy is null (like Swift or Aura Sphere), it never misses (100)
                acc = data.get("accuracy") or 100 
                name = data["name"].replace("-", " ").title()
                
                # Apply balanced status effect chances based on type
                s_type, s_chance = None, 0
                if m_type == "Fire": s_type, s_chance = "BRN", 10
                elif m_type == "Electric": s_type, s_chance = "PAR", 10
                elif m_type == "Poison": s_type, s_chance = "PSN", 20
                elif m_type == "Ice": s_type, s_chance = "FRZ", 10
                elif m_type == "Grass": s_type, s_chance = "SLP", 10
                
                return {
                    "name": name,
                    "power": power,
                    "acc": acc,
                    "type": m_type,
                    "status_type": s_type,
                    "status_chance": s_chance
                }
    except: 
        pass
    return None

async def fetch_random_pvp_pokemon(force_legendary=None):
    """Drafts a fully evolved Pokemon with proper moves, optionally forcing/blocking legendaries."""
    async with aiohttp.ClientSession() as session:
        while True: # Loop until we find a Pokemon that matches the criteria
            poke_id = random.randint(1, 898)
            url = f"https://pokeapi.co/api/v2/pokemon/{poke_id}"
            try:
                async with session.get(url, timeout=10) as response:
                    if response.status != 200: continue
                    data = await response.json()
                    name = data["name"].capitalize()
                    
                    # REQUIREMENT 1: Only Fully Evolved Pokemon (Base XP > 150)
                    if data.get("base_experience", 0) < 150: 
                        continue 
                    
                    # REQUIREMENT 2: Legendary Filtering (0ls vs 6ls)
                    if force_legendary is True and name not in LEGENDARY_NAMES: 
                        continue
                    if force_legendary is False and name in LEGENDARY_NAMES: 
                        continue

                    stats = {s["stat"]["name"]: s["base_stat"] for s in data["stats"]}
                    types_list = [t["type"]["name"].capitalize() for t in data.get("types", [])]
                    types_str = "/".join(types_list)
                    
                    # Fetch authentic moves from their real movepool
                    all_move_urls = [m["move"]["url"] for m in data.get("moves", [])]
                    
                    # Sample up to 35 random moves to increase chances of finding 80+ power moves
                    sample_urls = random.sample(all_move_urls, min(35, len(all_move_urls)))
                    
                    fetched_moves = await asyncio.gather(*(fetch_real_move_data(session, u) for u in sample_urls))
                    valid_moves = [m for m in fetched_moves if m is not None]
                    
                    # Filter for moves specifically 80 power or higher
                    strong_moves = [m for m in valid_moves if m["power"] >= 80]
                    final_moves = []
                    
                    # Step 1: Force a real STAB move with power >= 80
                    strong_stab = [m for m in strong_moves if m["type"] in types_list]
                    if strong_stab:
                        chosen_stab = random.choice(strong_stab)
                        final_moves.append(chosen_stab)
                        strong_moves.remove(chosen_stab)
                        valid_moves.remove(chosen_stab)
                    else:
                        # Fallback: Just grab the strongest real STAB move they have
                        any_stab = [m for m in valid_moves if m["type"] in types_list]
                        if any_stab:
                            chosen_stab = sorted(any_stab, key=lambda x: x["power"], reverse=True)[0]
                            final_moves.append(chosen_stab)
                            valid_moves.remove(chosen_stab)
                            if chosen_stab in strong_moves: strong_moves.remove(chosen_stab)

                    # Step 2: Fill the remaining slots strictly with other 80+ power moves
                    random.shuffle(strong_moves)
                    for m in strong_moves:
                        if len(final_moves) >= 4: break
                        if m["name"] not in [fm["name"] for fm in final_moves]:
                            final_moves.append(m)
                            if m in valid_moves: valid_moves.remove(m)
                    
                    # Step 3: If they don't have enough 80+ power moves, sort the rest by HIGHEST power available
                    if len(final_moves) < 4:
                        valid_moves.sort(key=lambda x: x["power"], reverse=True)
                        for m in valid_moves:
                            if len(final_moves) >= 4: break
                            if m["name"] not in [fm["name"] for fm in final_moves]:
                                final_moves.append(m)
                    
                    # Step 4: Extreme edge case safety net (should rarely happen)
                    while len(final_moves) < 4: 
                        final_moves.append({"name": "Struggle", "power": 50, "acc": 100, "type": "Normal", "status_type": None, "status_chance": 0})
                    
                    # Shuffle moves so the STAB move isn't always button #1
                    random.shuffle(final_moves)
                    
                    hp = int(stats.get("hp", 50)) * 3 
                    
                    return {
                        "name": name,
                        "types": types_str,
                        "hp": hp,
                        "max_hp": hp,
                        "atk": stats.get("attack", 50),
                        "def": stats.get("defense", 50),
                        "spd": stats.get("speed", 50),
                        "moves": final_moves,
                        "status": None,       
                        "sleep_turns": 0
                    }
            except Exception as e:
                logger.error(f"PvP Fetch Error: {e}")
                return None

async def generate_random_team(mode="Mix", size=6):
    """Builds a team based on user settings (0ls, 6ls, Mix) and Team Size."""
    if mode == "0ls":
        tasks = [fetch_random_pvp_pokemon(force_legendary=False) for _ in range(size)]
    elif mode == "6ls":
        tasks = [fetch_random_pvp_pokemon(force_legendary=True) for _ in range(size)]
    else: # Mix Mode
        leg_count = size // 2
        non_count = size - leg_count
        tasks = [fetch_random_pvp_pokemon(force_legendary=True) for _ in range(leg_count)] + \
                [fetch_random_pvp_pokemon(force_legendary=False) for _ in range(non_count)]
                
    team = await asyncio.gather(*tasks)
    valid_team = [p for p in team if p is not None]
    
    # Shuffle the drafted team so the player doesn't know what order they come out
    random.shuffle(valid_team) 
    
    return valid_team
