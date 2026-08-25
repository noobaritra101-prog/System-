# database.py
# -*- coding: utf-8 -*-
"""
JSON-backed data layer.

This module keeps the exact same function names/signatures the rest of the
bot (admin.py, main.py, pvp.py, tasks.py, trade.py, commands.py, gym.py)
already calls, so no other file needs to change. Internally it just reads
and writes a single JSON file instead of talking to Postgres.
"""
import os
import csv
import io
import json
import random
import datetime
import threading
import time

from config import DATA_FILE, logger

_lock = threading.RLock()

IV_STATS = ["hp", "atk", "def", "spa", "spd", "spe"]  # HP, Attack, Defense, Sp.Atk, Sp.Def, Speed

# nature_name -> (boosted_stat_key, lowered_stat_key); (None, None) for the 5 neutral natures.
# HP is never boosted/lowered by nature (matches the mainline games).
NATURES = {
    "Hardy": (None, None), "Lonely": ("atk", "def"), "Brave": ("atk", "spe"), "Adamant": ("atk", "spa"), "Naughty": ("atk", "spd"),
    "Bold": ("def", "atk"), "Docile": (None, None), "Relaxed": ("def", "spe"), "Impish": ("def", "spa"), "Lax": ("def", "spd"),
    "Timid": ("spe", "atk"), "Hasty": ("spe", "def"), "Serious": (None, None), "Jolly": ("spe", "spa"), "Naive": ("spe", "spd"),
    "Modest": ("spa", "atk"), "Mild": ("spa", "def"), "Quiet": ("spa", "spe"), "Bashful": (None, None), "Rash": ("spa", "spd"),
    "Calm": ("spd", "atk"), "Gentle": ("spd", "def"), "Sassy": ("spd", "spe"), "Careful": ("spd", "spa"), "Quirky": (None, None),
}


# ================== /mypokemon LIST SETTINGS ==================
DEFAULT_LIST_SETTINGS = {
    "sort_by": "order_caught",
    "sort_dir": "asc",
    "display": "none",
    "show_numbering": True,
    "page_size": 20,
}


def _random_ivs():
    return {stat: random.randint(0, 31) for stat in IV_STATS}


def _random_nature():
    return random.choice(list(NATURES.keys()))


def nature_effect(nature):
    """Returns (boosted_stat_key, lowered_stat_key) for a nature name, or (None, None) if unknown/neutral."""
    return NATURES.get(nature, (None, None))


def iv_percentage(ivs):
    """0-100 summary of a 6-stat IV spread, mainline-game style (31 per stat = 100%)."""
    if not ivs:
        return 0.0
    return round(sum(ivs.get(s, 0) for s in IV_STATS) / (31 * 6) * 100, 2)


def calc_level_100_stat(base, iv, stat_key, nature, ev=0):
    """Standard mainline-game stat formula, fixed at level 100 (EVs are always 0 in this bot)."""
    level = 100
    if stat_key == "hp":
        return ((2 * base + iv + ev // 4) * level) // 100 + level + 10
    boost, lower = nature_effect(nature)
    mult = 1.1 if boost == stat_key else (0.9 if lower == stat_key else 1.0)
    raw = ((2 * base + iv + ev // 4) * level) // 100 + 5
    return int(raw * mult)


_EMPTY = {
    "users": {},          # str(user_id) -> {tries_left, region, last_reset}
    "pokemons": [],        # [{id, user_id, name, region, ivs, nature}]
    "next_pokemon_id": 1,
    "groups": [],           # [group_id, ...]
    "pvp_settings": {},    # str(user_id) -> {mode, size, can_switch, status_effects}
    "battle_stats": {},    # str(user_id) -> {wins, losses}
    "user_badges": {},     # str(user_id) -> [badge, ...]
    "gym_images": {},      # leader_name -> file_id
    "tasks": {},           # str(user_id) -> {task_type: {...}}
    "admins": [],          # [user_id, ...]  (persisted, for future use)
}

data = None  # populated by init_db()


# ================== LOAD / SAVE ==================
def _default_data():
    import copy
    return copy.deepcopy(_EMPTY)


def _load():
    global data
    if os.path.exists(DATA_FILE):
        try:
            with open(DATA_FILE, "r", encoding="utf-8") as f:
                loaded = json.load(f)
            merged = _default_data()
            merged.update(loaded)
            data = merged
        except Exception as e:
            logger.error(f"❌ Failed to read {DATA_FILE}, starting with fresh data: {e}")
            data = _default_data()
    else:
        data = _default_data()
    _backfill_ivs()


def _backfill_ivs():
    """One-time migration: give every existing Pokémon a random IV spread and nature if missing or default Hardy."""
    backfilled = 0
    pokes = data.get("pokemons", [])
    total_count = len(pokes)
    hardy_count = sum(1 for p in pokes if p.get("nature") == "Hardy")
    
    # If over 30% of pokemons are Hardy (indicates legacy default-fallback issue)
    fix_hardy = (total_count > 1 and hardy_count / total_count > 0.3) or (total_count == 1 and hardy_count == 1)

    for p in pokes:
        changed = False
        if "ivs" not in p or not p["ivs"]:
            p["ivs"] = _random_ivs()
            changed = True
        if "nature" not in p or not p["nature"] or (fix_hardy and p.get("nature") == "Hardy"):
            p["nature"] = _random_nature()
            changed = True
        if changed:
            backfilled += 1
    if backfilled:
        logger.info(f"🎲 Backfilled/randomized IVs & Nature for {backfilled} existing Pokémon.")


def _save():
    """Atomically write the in-memory data to disk. Only called from the
    background flush loop (and once at startup) — never directly from a
    request path, so no command has to block on a full-file rewrite."""
    tmp_path = f"{DATA_FILE}.tmp"
    try:
        with open(tmp_path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False)
        os.replace(tmp_path, DATA_FILE)
    except Exception as e:
        logger.error(f"❌ Failed to save {DATA_FILE}: {e}")


_dirty = False
FLUSH_INTERVAL = 2  # seconds between debounced disk writes


def _mark_dirty():
    """Cheap in-memory flag flip — replaces a synchronous full-file _save()
    on every mutation. The background flush loop below does the actual
    (expensive) disk write, batched, so commands like /scout never block
    on serializing the whole database."""
    global _dirty
    _dirty = True


def _flush_loop():
    while True:
        time.sleep(FLUSH_INTERVAL)
        global _dirty
        do_save = False
        with _lock:
            if _dirty:
                do_save = True
                _dirty = False
        if do_save:
            with _lock:
                _save()


def force_save():
    """Immediate, synchronous save — for graceful shutdown (e.g. on SIGTERM)
    so nothing in the debounce window is lost."""
    global _dirty
    with _lock:
        _save()
        _dirty = False


def init_db():
    with _lock:
        _load()
        _save()
    threading.Thread(target=_flush_loop, daemon=True).start()
    logger.info("✅ JSON data store ready (%s)", DATA_FILE)


# ================== HELPERS ==================
def _today():
    return datetime.date.today()


def _today_str():
    return _today().isoformat()


def _parse_date(s):
    if not s:
        return None
    if isinstance(s, datetime.date):
        return s
    try:
        return datetime.date.fromisoformat(s)
    except Exception:
        return None


def _date_str(d):
    if d is None:
        return None
    if isinstance(d, str):
        return d
    return d.isoformat()


# ================== USER MANAGEMENT ==================
def add_user_if_new(user_id):
    uid = str(user_id)
    with _lock:
        if uid not in data["users"]:
            data["users"][uid] = {"tries_left": 2500, "region": "Kanto", "last_reset": _today_str()}
            _mark_dirty()
            return True
        return False


def get_user(user_id):
    uid = str(user_id)
    with _lock:
        u = data["users"].get(uid)
        if not u:
            return None
        return (user_id, u["tries_left"], u["region"], _parse_date(u.get("last_reset")))


def update_user_tries(user_id):
    uid = str(user_id)
    with _lock:
        u = data["users"].get(uid)
        if not u:
            return None, None

        tries = u["tries_left"]
        region = u["region"]
        last_reset = _parse_date(u.get("last_reset"))
        today = _today()

        if last_reset is None or last_reset < today:
            tries = 2500
            last_reset = today

        if tries > 0:
            tries -= 1
            u["tries_left"] = tries
            u["last_reset"] = _date_str(last_reset)
            _mark_dirty()
            return tries, region
        return 0, region


def update_user_region(user_id, region):
    uid = str(user_id)
    with _lock:
        u = data["users"].get(uid)
        if u:
            u["region"] = region
            _mark_dirty()


def reset_user(user_id):
    uid = str(user_id)
    with _lock:
        u = data["users"].get(uid)
        if u:
            u["tries_left"] = 2500
            u["last_reset"] = _today_str()
            _mark_dirty()


def get_all_users():
    with _lock:
        return [int(uid) for uid in data["users"].keys()]


# ================== POKEMON MANAGEMENT ==================
def add_caught_pokemon(user_id, name, region, source="Wild"):
    try:
        with _lock:
            pid = data["next_pokemon_id"]
            data["next_pokemon_id"] = pid + 1
            ivs = _random_ivs()
            nature = _random_nature()
            record = {"id": pid, "user_id": user_id, "name": name, "region": region, "ivs": ivs, "nature": nature}
            data["pokemons"].append(record)
            _mark_dirty()
            return {"id": pid, "name": name, "region": region, "ivs": ivs, "nature": nature, "iv_percent": iv_percentage(ivs)}
    except Exception:
        logger.exception(f"❌ add_caught_pokemon failed for user_id={user_id} name={name}")
        return None


def _user_matches(p, user_id):
    pu = p.get("user_id")
    return pu == user_id or str(pu) == str(user_id)


def _find_pokemon_record(user_id, identifier):
    """Finds a specific pokemon record for user_id by numeric record id OR species name."""
    if identifier is None:
        return None
    ident_str = str(identifier).strip()
    
    # Check if identifier is numeric record ID
    if ident_str.isdigit():
        target_id = int(ident_str)
        for p in data["pokemons"]:
            if _user_matches(p, user_id) and p.get("id") == target_id:
                return p
    
    # Otherwise search by species name (case-insensitive), returning oldest
    name_lower = ident_str.lower()
    matches = [p for p in data["pokemons"] if _user_matches(p, user_id) and p.get("name", "").lower() == name_lower]
    if not matches:
        return None
    return min(matches, key=lambda p: p.get("id", 0))


def get_pokemon_ivs(user_id, identifier):
    try:
        with _lock:
            rec = _find_pokemon_record(user_id, identifier)
            if not rec:
                return None
            return dict(rec.get("ivs") or {})
    except Exception:
        logger.exception(f"❌ get_pokemon_ivs failed for user_id={user_id} identifier={identifier}")
        return None


def get_pokemon_details(user_id, identifier):
    """Returns {'id', 'name', 'ivs', 'nature'} for a specific Pokémon (by record ID or name)."""
    try:
        with _lock:
            rec = _find_pokemon_record(user_id, identifier)
            if not rec:
                return None
            return {
                "id": rec.get("id"),
                "name": rec.get("name"),
                "ivs": dict(rec.get("ivs") or {}),
                "nature": rec.get("nature") or _random_nature(),
            }
    except Exception:
        logger.exception(f"❌ get_pokemon_details failed for user_id={user_id} identifier={identifier}")
        return None


def get_user_pokemon_by_name(user_id, name):
    """Returns all caught records (id, name, region, ivs, iv_percent, nature) for user_id matching species name."""
    try:
        with _lock:
            name_lower = (name or "").lower()
            rows = [p for p in data["pokemons"] if _user_matches(p, user_id) and p.get("name", "").lower() == name_lower]
            return [
                {
                    "id": p.get("id", 0),
                    "name": p.get("name"),
                    "region": p.get("region"),
                    "ivs": dict(p.get("ivs") or {}),
                    "iv_percent": iv_percentage(p.get("ivs")),
                    "nature": p.get("nature") or "Hardy",
                }
                for p in rows
            ]
    except Exception:
        logger.exception(f"❌ get_user_pokemon_by_name failed for user_id={user_id} name={name}")
        return []


def get_user_pokemon(user_id):
    try:
        with _lock:
            rows = [p for p in data["pokemons"] if _user_matches(p, user_id)]
            rows.sort(key=lambda p: p.get("id", 0))
            return [
                {
                    "id": p.get("id"),
                    "name": p.get("name"),
                    "region": p.get("region"),
                    "ivs": dict(p.get("ivs") or {}),
                    "iv_percent": iv_percentage(p.get("ivs")),
                }
                for p in rows
            ]
    except Exception:
        logger.exception(f"❌ get_user_pokemon failed for user_id={user_id}")
        return []


def list_user_pokemon_names(user_id):
    try:
        with _lock:
            rows = [p for p in data["pokemons"] if _user_matches(p, user_id)]
            rows.sort(key=lambda p: p.get("id", 0))
            return [p.get("name") for p in rows]
    except Exception:
        logger.exception(f"❌ list_user_pokemon_names failed for user_id={user_id}")
        return []


def list_user_pokemon_full(user_id):
    try:
        with _lock:
            rows = [p for p in data["pokemons"] if _user_matches(p, user_id)]
            rows.sort(key=lambda p: p.get("id", 0))
            return [
                {
                    "id": p.get("id", 0),
                    "name": p.get("name"),
                    "ivs": dict(p.get("ivs") or {}),
                    "iv_percent": iv_percentage(p.get("ivs")),
                    "nature": p.get("nature") or "Hardy",
                }
                for p in rows
            ]
    except Exception:
        logger.exception(f"❌ list_user_pokemon_full failed for user_id={user_id}")
        return []


# ================== /mypokemon LIST SETTINGS (accessors) ==================
def get_list_settings(user_id):
    uid = str(user_id)
    with _lock:
        u = data["users"].get(uid)
        if not u:
            return dict(DEFAULT_LIST_SETTINGS)
        settings = u.setdefault("list_settings", {})
        changed = False
        for k, v in DEFAULT_LIST_SETTINGS.items():
            if k not in settings:
                settings[k] = v
                changed = True
        if changed:
            _mark_dirty()
        return dict(settings)


def update_list_settings(user_id, **kwargs):
    uid = str(user_id)
    with _lock:
        u = data["users"].get(uid)
        if not u:
            return None
        settings = u.setdefault("list_settings", dict(DEFAULT_LIST_SETTINGS))
        for k, v in DEFAULT_LIST_SETTINGS.items():
            settings.setdefault(k, v)
        settings.update(kwargs)
        _mark_dirty()
        return dict(settings)


def get_pokemon_custom_moves(user_id, identifier):
    try:
        with _lock:
            rec = _find_pokemon_record(user_id, identifier)
            if not rec:
                return None
            moves = rec.get("moves")
            return [dict(m) for m in moves] if moves else None
    except Exception:
        logger.exception(f"❌ get_pokemon_custom_moves failed for user_id={user_id} identifier={identifier}")
        return None


def set_pokemon_move_slot(user_id, identifier, base_moves, slot_index, new_move):
    try:
        with _lock:
            rec = _find_pokemon_record(user_id, identifier)
            if not rec:
                return None
            current = rec.get("moves") or [dict(m) for m in (base_moves or [])]
            if slot_index < 0 or slot_index >= len(current):
                return None
            current[slot_index] = dict(new_move)
            rec["moves"] = current
            _mark_dirty()
            return [dict(m) for m in current]
    except Exception:
        logger.exception(f"❌ set_pokemon_move_slot failed for user_id={user_id} identifier={identifier}")
        return None


def delete_pokemon(user_id, identifier):
    try:
        with _lock:
            rec = _find_pokemon_record(user_id, identifier)
            if not rec:
                return False
            data["pokemons"].remove(rec)
            _mark_dirty()
            return True
    except Exception:
        logger.exception(f"❌ delete_pokemon failed for user_id={user_id} identifier={identifier}")
        return False


def evolve_pokemon(user_id, identifier, new_name):
    """Renames a caught Pokémon's species to its next evolution, keeping its
    record id, IVs, nature, and region intact."""
    try:
        with _lock:
            rec = _find_pokemon_record(user_id, identifier)
            if not rec:
                return False
            rec["name"] = new_name
            _mark_dirty()
            return True
    except Exception:
        logger.exception(f"❌ evolve_pokemon failed for user_id={user_id} identifier={identifier}")
        return False


# ================== LEADERBOARD ==================
def get_top_trainers(limit=5):
    with _lock:
        counts = {}
        for p in data["pokemons"]:
            counts[p["user_id"]] = counts.get(p["user_id"], 0) + 1
        ranked = sorted(counts.items(), key=lambda kv: kv[1], reverse=True)
        return ranked[:limit]


def get_user_rank(user_id):
    with _lock:
        counts = {}
        for p in data["pokemons"]:
            counts[p["user_id"]] = counts.get(p["user_id"], 0) + 1
        if user_id not in counts:
            return "Unranked"
        ranked = sorted(counts.items(), key=lambda kv: kv[1], reverse=True)
        rank = None
        prev_count = None
        current_rank = 0
        for idx, (uid, c) in enumerate(ranked, start=1):
            if c != prev_count:
                current_rank = idx
                prev_count = c
            if uid == user_id:
                rank = current_rank
                break
        return rank if rank is not None else "Unranked"


def get_top_pvp_players(limit=5):
    with _lock:
        rows = [(int(uid), s["wins"]) for uid, s in data["battle_stats"].items() if s.get("wins", 0) > 0]
        rows.sort(key=lambda kv: kv[1], reverse=True)
        return rows[:limit]


def get_user_pvp_rank(user_id):
    with _lock:
        rows = [(int(uid), s["wins"]) for uid, s in data["battle_stats"].items() if s.get("wins", 0) > 0]
        rows.sort(key=lambda kv: kv[1], reverse=True)
        rank = None
        prev_wins = None
        current_rank = 0
        for idx, (uid, wins) in enumerate(rows, start=1):
            if wins != prev_wins:
                current_rank = idx
                prev_wins = wins
            if uid == user_id:
                rank = current_rank
                break
        return rank if rank is not None else "Unranked"


# ================== PVP & STATS ==================
def get_pvp_settings(user_id):
    uid = str(user_id)
    with _lock:
        s = data["pvp_settings"].get(uid)
        if s:
            return s["mode"], s["size"], s["can_switch"], s["status_effects"]
        return "Mix", 6, True, True


def update_pvp_settings(user_id, mode, size, can_switch, status_effects):
    uid = str(user_id)
    with _lock:
        data["pvp_settings"][uid] = {
            "mode": mode, "size": size, "can_switch": can_switch, "status_effects": status_effects
        }
        _mark_dirty()


def get_battle_stats(user_id):
    uid = str(user_id)
    with _lock:
        s = data["battle_stats"].get(uid)
        if s:
            return s["wins"], s["losses"]
        return 0, 0


def update_battle_stats(user_id, is_win=True):
    uid = str(user_id)
    with _lock:
        s = data["battle_stats"].setdefault(uid, {"wins": 0, "losses": 0})
        if is_win:
            s["wins"] += 1
        else:
            s["losses"] += 1
        _mark_dirty()


# ================== 🏅 BADGE SYSTEM & GYM IMAGES ==================
def add_badge(user_id, badge_name):
    uid = str(user_id)
    with _lock:
        badges = data["user_badges"].setdefault(uid, [])
        if badge_name not in badges:
            badges.append(badge_name)
            _mark_dirty()


def get_user_badges(user_id):
    uid = str(user_id)
    with _lock:
        return list(data["user_badges"].get(uid, []))


def set_gym_image(leader_name, file_id):
    with _lock:
        data["gym_images"][leader_name] = file_id
        _mark_dirty()


def get_gym_image(leader_name):
    with _lock:
        return data["gym_images"].get(leader_name)


def delete_gym_image(leader_name):
    with _lock:
        target = leader_name.lower()
        keys = [k for k in data["gym_images"].keys() if k.lower() == target]
        for k in keys:
            del data["gym_images"][k]
        if keys:
            _mark_dirty()


def list_gym_leader_names():
    with _lock:
        return list(data["gym_images"].keys())


def reset_all_badges():
    with _lock:
        data["user_badges"] = {}
        _mark_dirty()


# ================== TASKS MODULE ==================
def get_daily_tasks(user_id):
    uid = str(user_id)
    today = _today()
    with _lock:
        user_tasks = data["tasks"].get(uid)
        needs_reset = True
        if user_tasks:
            any_task = next(iter(user_tasks.values()), None)
            last_reset = _parse_date(any_task.get("last_reset")) if any_task else None
            needs_reset = (last_reset is None or last_reset < today)

        if needs_reset:
            targets = ["Pikachu", "Eevee", "Charmander", "Squirtle", "Bulbasaur", "Snorlax",
                       "Gengar", "Lucario", "Ralts", "Bagon", "Magikarp", "Gible", "Beldum", "Dratini"]
            specific_target = random.choice(targets)
            user_tasks = {
                "catch": {"target": "Any", "progress": 0, "goal": 10, "reward_type": "shiny",
                          "reward_amount": 1, "completed": False, "last_reset": _date_str(today)},
                "pvp": {"target": "Any", "progress": 0, "goal": 3, "reward_type": "shiny",
                        "reward_amount": 1, "completed": False, "last_reset": _date_str(today)},
                "catch_specific": {"target": specific_target, "progress": 0, "goal": 1, "reward_type": "jackpot",
                                    "reward_amount": 1, "completed": False, "last_reset": _date_str(today)},
            }
            data["tasks"][uid] = user_tasks
            _mark_dirty()

        return [
            {
                "task_type": t_type,
                "target": t["target"],
                "progress": t["progress"],
                "goal": t["goal"],
                "reward_type": t["reward_type"],
                "reward_amount": t["reward_amount"],
                "completed": t["completed"],
            }
            for t_type, t in user_tasks.items()
        ]


def claim_task_reward(user_id, task_type):
    uid = str(user_id)
    with _lock:
        t = data["tasks"].get(uid, {}).get(task_type)
        if t and t["progress"] >= t["goal"] and not t["completed"]:
            t["completed"] = True
            _mark_dirty()
            return t["reward_type"], t["reward_amount"]
        return None


def update_task_pvp(user_id):
    uid = str(user_id)
    with _lock:
        t = data["tasks"].get(uid, {}).get("pvp")
        if t and not t["completed"]:
            t["progress"] += 1
            _mark_dirty()


def update_task_catch(user_id):
    uid = str(user_id)
    with _lock:
        t = data["tasks"].get(uid, {}).get("catch")
        if t and not t["completed"]:
            t["progress"] += 1
            _mark_dirty()


def update_task_specific_catch(user_id, pokemon_name):
    uid = str(user_id)
    with _lock:
        t = data["tasks"].get(uid, {}).get("catch_specific")
        if t and not t["completed"] and t["target"].lower() == pokemon_name.lower():
            t["progress"] += 1
            _mark_dirty()


# ================== GROUP MANAGEMENT ==================
def add_group(group_id):
    with _lock:
        if group_id not in data["groups"]:
            data["groups"].append(group_id)
            _mark_dirty()


def remove_group(group_id):
    with _lock:
        if group_id in data["groups"]:
            data["groups"].remove(group_id)
            _mark_dirty()


def get_all_groups():
    with _lock:
        return list(data["groups"])


# ================== CROSS-ACCOUNT TRANSFER ==================
def transfer_user_data(source_uid, target_uid):
    with _lock:
        poke_count = 0
        for p in data["pokemons"]:
            if p["user_id"] == source_uid:
                p["user_id"] = target_uid
                poke_count += 1

        src, tgt = str(source_uid), str(target_uid)
        if src in data["battle_stats"]:
            s = data["battle_stats"].pop(src)
            t = data["battle_stats"].setdefault(tgt, {"wins": 0, "losses": 0})
            t["wins"] += s.get("wins", 0)
            t["losses"] += s.get("losses", 0)

        if src in data["tasks"]:
            data["tasks"][tgt] = data["tasks"].pop(src)

        _mark_dirty()
        return poke_count


# ================== ADMIN TOOLS & EXPORT ==================
def export_all_data():
    with _lock:
        return {
            "users": [
                {"user_id": int(uid), "tries_left": u["tries_left"], "region": u["region"], "last_reset": u.get("last_reset")}
                for uid, u in data["users"].items()
            ],
            "pokemons": [
                {"id": p["id"], "user_id": p["user_id"], "name": p["name"], "region": p["region"], "ivs": p.get("ivs") or {}, "nature": p.get("nature") or _random_nature()}
                for p in data["pokemons"]
            ],
            "next_pokemon_id": data.get("next_pokemon_id", 1),
            "groups": list(data["groups"]),
            "pvp_settings": dict(data.get("pvp_settings", {})),
            "battle_stats": [
                {"user_id": int(uid), "wins": s["wins"], "losses": s["losses"]}
                for uid, s in data["battle_stats"].items()
            ],
            "user_badges": {uid: list(badges) for uid, badges in data.get("user_badges", {}).items()},
            "gym_images": dict(data.get("gym_images", {})),
            "tasks": {uid: dict(t) for uid, t in data.get("tasks", {}).items()},
            "admins": list(data.get("admins", [])),
        }


def import_backup(backup):
    with _lock:
        new_data = _default_data()

        raw_users = backup.get("users", [])
        if isinstance(raw_users, dict):
            # Raw DB shape: {"<user_id>": {"tries_left":..., "region":..., "last_reset":...}}
            for uid, u in raw_users.items():
                new_data["users"][str(uid)] = {
                    "tries_left": u.get("tries_left", 2500),
                    "region": u.get("region", "Kanto"),
                    "last_reset": u.get("last_reset") or _today_str(),
                }
        else:
            # Export shape: [{"user_id":..., "tries_left":..., "region":..., "last_reset":...}, ...]
            for u in raw_users:
                uid = str(u["user_id"])
                new_data["users"][uid] = {
                    "tries_left": u.get("tries_left", 2500),
                    "region": u.get("region", "Kanto"),
                    "last_reset": u.get("last_reset") or _today_str(),
                }

        # Preserve original Pokemon ids when the backup has them (new export format);
        # fall back to sequential numbering for older exports that lack "id".
        max_id = 0
        next_fallback_id = 1
        for p in backup.get("pokemons", []):
            pid = p.get("id")
            if pid is None:
                pid = next_fallback_id
            next_fallback_id = max(next_fallback_id, pid) + 1
            new_data["pokemons"].append({
                "id": pid, "user_id": p["user_id"], "name": p["name"], "region": p.get("region", "Kanto"),
                "ivs": p.get("ivs") or _random_ivs(),
                "nature": p.get("nature") or _random_nature(),
            })
            max_id = max(max_id, pid)
        new_data["next_pokemon_id"] = max(backup.get("next_pokemon_id", 1), max_id + 1)

        for g in backup.get("groups", []):
            gid = g[0] if isinstance(g, (list, tuple)) else g
            if gid not in new_data["groups"]:
                new_data["groups"].append(gid)

        raw_battle_stats = backup.get("battle_stats", [])
        if isinstance(raw_battle_stats, dict):
            # Raw DB shape: {"<user_id>": {"wins":..., "losses":...}}
            for uid, s in raw_battle_stats.items():
                new_data["battle_stats"][str(uid)] = {"wins": s.get("wins", 0), "losses": s.get("losses", 0)}
        else:
            # Export shape: [{"user_id":..., "wins":..., "losses":...}, ...]
            for b in raw_battle_stats:
                new_data["battle_stats"][str(b["user_id"])] = {"wins": b.get("wins", 0), "losses": b.get("losses", 0)}

        for uid, badges in backup.get("user_badges", {}).items():
            new_data["user_badges"][uid] = badges
        for leader, file_id in backup.get("gym_images", {}).items():
            new_data["gym_images"][leader] = file_id
        for uid, settings in backup.get("pvp_settings", {}).items():
            new_data["pvp_settings"][uid] = settings
        for uid, tasks in backup.get("tasks", {}).items():
            new_data["tasks"][uid] = tasks
        new_data["admins"] = list(backup.get("admins", []))

        global data
        data = new_data
        _mark_dirty()

        return {
            "users": len(new_data["users"]),
            "pokemons": len(new_data["pokemons"]),
            "groups": len(new_data["groups"]),
            "battle_stats": len(new_data["battle_stats"]),
            "user_badges": len(new_data["user_badges"]),
            "tasks": len(new_data["tasks"]),
        }


def restore_sqlite_data(users_data, pokemons_data, groups_data):
    with _lock:
        for row in users_data:
            uid = str(row[0])
            if uid not in data["users"]:
                data["users"][uid] = {
                    "tries_left": row[1], "region": row[2], "last_reset": _date_str(row[3])
                }

        for row in pokemons_data:
            pid = data["next_pokemon_id"]
            data["next_pokemon_id"] = pid + 1
            data["pokemons"].append({"id": pid, "user_id": row[0], "name": row[1], "region": row[2], "ivs": _random_ivs(), "nature": _random_nature()})

        for row in groups_data:
            gid = row[0] if isinstance(row, (list, tuple)) else row
            if gid not in data["groups"]:
                data["groups"].append(gid)

        _mark_dirty()


def export_table_csv(table_name):
    allowed_tables = ['users', 'pokemons', 'groups', 'battle_stats']
    if table_name not in allowed_tables:
        return None

    with _lock:
        output = io.StringIO()
        writer = csv.writer(output)

        if table_name == "users":
            writer.writerow(["user_id", "tries_left", "region", "last_reset"])
            for uid, u in data["users"].items():
                writer.writerow([uid, u["tries_left"], u["region"], u.get("last_reset")])
        elif table_name == "pokemons":
            writer.writerow(["id", "user_id", "name", "region", "hp", "atk", "def", "spa", "spd", "spe", "iv_percent", "nature"])
            for p in data["pokemons"]:
                ivs = p.get("ivs") or {}
                writer.writerow([
                    p["id"], p["user_id"], p["name"], p["region"],
                    ivs.get("hp"), ivs.get("atk"), ivs.get("def"), ivs.get("spa"), ivs.get("spd"), ivs.get("spe"),
                    iv_percentage(ivs), p.get("nature", "Hardy")
                ])
        elif table_name == "groups":
            writer.writerow(["group_id"])
            for g in data["groups"]:
                writer.writerow([g])
        elif table_name == "battle_stats":
            writer.writerow(["user_id", "wins", "losses"])
            for uid, s in data["battle_stats"].items():
                writer.writerow([uid, s["wins"], s["losses"]])

        return output.getvalue()


def get_debug_stats():
    with _lock:
        u_c = len(data["users"])
        p_c = len(data["pokemons"])
        g_c = len(data["groups"])

        pvp_sum = sum(s.get("wins", 0) + s.get("losses", 0) for s in data["battle_stats"].values())
        pvp_total = int(pvp_sum / 2) if pvp_sum else 0

        regions_active = len({u["region"] for u in data["users"].values() if u.get("region")})

        try:
            db_size_mb = round(os.path.getsize(DATA_FILE) / (1024 * 1024), 2) if os.path.exists(DATA_FILE) else 0.0
        except Exception:
            db_size_mb = 0.0

        return u_c, p_c, g_c, pvp_total, regions_active, db_size_mb


def add_admin(user_id):
    with _lock:
        if user_id not in data["admins"]:
            data["admins"].append(user_id)
            _mark_dirty()


def remove_admin(user_id):
    with _lock:
        if user_id in data["admins"]:
            data["admins"].remove(user_id)
            _mark_dirty()
