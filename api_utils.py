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

# PERFECTED API-FORMAT LIST: Lowercase and hyphenated exactly as the API outputs them
LEGENDARY_NAMES = {
    "articuno", "zapdos", "moltres", "mewtwo", "mew", "raikou", "entei", "suicune", 
    "lugia", "ho-oh", "celebi", "regirock", "regice", "registeel", "latias", "latios", 
    "kyogre", "groudon", "rayquaza", "jirachi", "deoxys", "deoxys-normal", "uxie", "mesprit", "azelf", 
    "dialga", "palkia", "heatran", "regigigas", "giratina", "giratina-altered", "cresselia", "phione", 
    "manaphy", "darkrai", "shaymin", "shaymin-land", "arceus", "victini", "cobalion", "terrakion", 
    "virizion", "tornadus", "tornadus-incarnate", "thundurus", "thundurus-incarnate", "reshiram", "zekrom", "landorus", "landorus-incarnate", "kyurem", 
    "keldeo", "keldeo-ordinary", "meloetta", "meloetta-aria", "genesect", "xerneas", "yveltal", "zygarde", "zygarde-50", "diancie", 
    "hoopa", "hoopa-confined", "volcanion", "type-null", "silvally", "tapu-koko", "tapu-lele", "tapu-bulu", 
    "tapu-fini", "cosmog", "cosmoem", "solgaleo", "lunala", "nihilego", "buzzwole", 
    "pheromosa", "xurkitree", "celesteela", "kartana", "guzzlord", "necrozma", "magearna", 
    "marshadow", "poipole", "naganadel", "stakataka", "blacephalon", "zeraora", "meltan", 
    "melmetal", "zacian", "zacian-hero", "zamazenta", "zamazenta-hero", "eternatus", "kubfu", "urshifu", "urshifu-single-strike", "zarude", 
    "regieleki", "regidrago", "glastrier", "spectrier", "calyrex", "enamorus", "enamorus-incarnate"
}

# --- REGION BOUNDARIES (Generations 1 to 8) ---
REGION_DEX = {
    "Kanto": (1, 151),
    "Johto": (152, 251),
    "Hoenn": (252, 386),
    "Sinnoh": (387, 493),
    "Unova": (494, 649),
    "Kalos": (650, 721),
    "Alola": (722, 809),
    "Galar": (810, 898)
}

# ⚡ TYPE EMOJI MAP — duplicated here so build_cache can seed commands.local_type_cache
_TYPE_EMOJIS = {
    'Normal': '🔘', 'Fire': '🔥', 'Water': '💧', 'Electric': '⚡', 'Grass': '🌿', 
    'Ice': '🧊', 'Fighting': '🥊', 'Poison': '☣️', 'Ground': '⛰️', 'Flying': '🪽', 
    'Psychic': '🔮', 'Bug': '🐛', 'Rock': '🪨', 'Ghost': '👻', 'Dragon': '🐉', 
    'Dark': '🌑', 'Steel': '🔩', 'Fairy': '🧚‍♀️'
}

def build_cache():
    """
    ⚡ OPTIMIZED: Fetches all 898 Pokémon names/IDs AND their types in one pass.
    Types are written directly into commands.local_type_cache so /mypokemon is
    instant even on the very first call after startup.
    """
    try:
        url = "https://pokeapi.co/api/v2/pokemon?limit=898"
        req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
        with urllib.request.urlopen(req, timeout=10) as response:
            data = json.loads(response.read().decode())
            for i, result in enumerate(data['results'], start=1):
                name = result['name'].capitalize()
                pokemon_cache[i] = name
                pokemon_name_to_id_cache[name.lower()] = i
        logger.info("✅ Pokémon name/ID cache built! /scout is now instant.")
    except Exception as e:
        logger.error(f"Failed to build name cache: {e}")
        return

    # ⚡ Phase 2: Pre-warm the type cache used by /mypokemon
    # Fetch types for the 151 most commonly caught Pokémon (Kanto) synchronously,
    # then do the rest of the dex in a low-priority background pass.
    def _seed_type_cache():
        try:
            # Import here to avoid circular import at module load time
            import commands as _cmd

            # Seed the entire dex in batches — PokeAPI bulk endpoint gives types too
            bulk_url = "https://pokeapi.co/api/v2/pokemon?limit=898&offset=0"
            req2 = urllib.request.Request(bulk_url, headers={'User-Agent': 'Mozilla/5.0'})
            with urllib.request.urlopen(req2, timeout=10) as r:
                bulk = json.loads(r.read().decode())

            seeded = 0
            for entry in bulk['results']:
                raw_name = entry['name']
                cap_name = raw_name.capitalize()
                lower_name = raw_name.lower()

                # Skip if already cached
                if lower_name in _cmd.local_type_cache:
                    continue

                try:
                    detail_url = f"https://pokeapi.co/api/v2/pokemon/{lower_name}"
                    req3 = urllib.request.Request(detail_url, headers={'User-Agent': 'Mozilla/5.0'})
                    with urllib.request.urlopen(req3, timeout=5) as r2:
                        pdata = json.loads(r2.read().decode())
                        types_list = [t["type"]["name"].capitalize() for t in pdata["types"]]
                        emojis = "/ ".join([_TYPE_EMOJIS.get(t, '') for t in types_list if t]).strip()
                        _cmd.local_type_cache[lower_name] = f"【{emojis}】" if emojis else ""
                        seeded += 1
                except Exception:
                    _cmd.local_type_cache[lower_name] = ""

            logger.info(f"✅ Type cache pre-warmed for {seeded} Pokémon.")
        except Exception as e:
            logger.error(f"Type cache pre-warm failed: {e}")

    threading.Thread(target=_seed_type_cache, daemon=True).start()


# Start the cache builder in the background immediately
threading.Thread(target=build_cache, daemon=True).start()

def escape_md(text):
    """Safely escape text for Telegram MarkdownV2."""
    special_chars = r'([_\*\[\]\(\)~`>\#\+\-=\|\{\}\.\!])'
    return re.sub(special_chars, r'\\\1', str(text))

def fetch_random_pokemon_id_and_name_sync(region="Kanto"):
    """Used for /scout. Ultra-fast lookup restricted by Region!"""
    # 5% chance to encounter a Mega Evolution (appears in all regions)
    if random.random() < 0.05:
        poke_id, name, base_id = random.choice(MEGA_POKEMON)
        return poke_id, name, base_id
    
    # Get the ID boundaries for the user's current region
    min_id, max_id = REGION_DEX.get(region, (1, 898))
    poke_id = random.randint(min_id, max_id)
    
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
                
                if not power: 
                    return None
                
                m_type = data["type"]["name"].capitalize()
                acc = data.get("accuracy") or 100 
                name = data["name"].replace("-", " ").title()
                
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
        while True:
            poke_id = random.randint(1, 898)
            url = f"https://pokeapi.co/api/v2/pokemon/{poke_id}"
            try:
                async with session.get(url, timeout=10) as response:
                    if response.status != 200: continue
                    data = await response.json()
                    
                    raw_api_name = data["name"]
                    name = raw_api_name.replace("-", " ").title()
                    
                    if data.get("base_experience", 0) < 150: 
                        continue 
                    
                    is_legendary = raw_api_name in LEGENDARY_NAMES
                    if force_legendary is True and not is_legendary: 
                        continue
                    if force_legendary is False and is_legendary: 
                        continue

                    stats = {s["stat"]["name"]: s["base_stat"] for s in data["stats"]}
                    types_list = [t["type"]["name"].capitalize() for t in data.get("types", [])]
                    types_str = "/".join(types_list)
                    
                    all_move_urls = [m["move"]["url"] for m in data.get("moves", [])]
                    sample_urls = random.sample(all_move_urls, min(45, len(all_move_urls)))
                    
                    fetched_moves = await asyncio.gather(*(fetch_real_move_data(session, u) for u in sample_urls))
                    valid_moves = [m for m in fetched_moves if m is not None]
                    
                    strong_moves = [m for m in valid_moves if m["power"] >= 80]
                    final_moves = []
                    
                    for p_type in types_list:
                        type_strong_moves = [m for m in strong_moves if m["type"] == p_type]
                        if type_strong_moves:
                            chosen_stab = random.choice(type_strong_moves)
                            final_moves.append(chosen_stab)
                            strong_moves.remove(chosen_stab)
                            valid_moves.remove(chosen_stab)
                        else:
                            type_any_moves = [m for m in valid_moves if m["type"] == p_type]
                            if type_any_moves:
                                chosen_stab = sorted(type_any_moves, key=lambda x: x["power"], reverse=True)[0]
                                final_moves.append(chosen_stab)
                                valid_moves.remove(chosen_stab)
                                if chosen_stab in strong_moves: strong_moves.remove(chosen_stab)

                    random.shuffle(strong_moves)
                    for m in strong_moves:
                        if len(final_moves) >= 4: break
                        if m["name"] not in [fm["name"] for fm in final_moves]:
                            final_moves.append(m)
                            if m in valid_moves: valid_moves.remove(m)
                    
                    if len(final_moves) < 4:
                        valid_moves.sort(key=lambda x: x["power"], reverse=True)
                        for m in valid_moves:
                            if len(final_moves) >= 4: break
                            if m["name"] not in [fm["name"] for fm in final_moves]:
                                final_moves.append(m)
                    
                    while len(final_moves) < 4: 
                        final_moves.append({"name": "Struggle", "power": 50, "acc": 100, "type": "Normal", "status_type": None, "status_chance": 0})
                    
                    random.shuffle(final_moves)
                    
                    return {
                        "name": name,
                        "types": types_str,
                        "hp": stats.get("hp", 50),
                        "max_hp": stats.get("hp", 50),
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
    else:
        leg_count = size // 2
        non_count = size - leg_count
        tasks = [fetch_random_pvp_pokemon(force_legendary=True) for _ in range(leg_count)] + \
                [fetch_random_pvp_pokemon(force_legendary=False) for _ in range(non_count)]
                
    team = await asyncio.gather(*tasks)
    valid_team = [p for p in team if p is not None]
    random.shuffle(valid_team) 
    return valid_team
