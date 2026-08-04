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
    """One-time migration: give every existing Pokémon (caught before IVs/nature existed)
    a random IV spread and a random nature."""
    backfilled = 0
    for p in data["pokemons"]:
        changed = False
        if "ivs" not in p or not p["ivs"]:
            p["ivs"] = _random_ivs()
            changed = True
        if "nature" not in p or not p["nature"]:
            p["nature"] = _random_nature()
            changed = True
        if changed:
            backfilled += 1
    if backfilled:
        logger.info(f"🎲 Backfilled random IVs/Nature for {backfilled} existing Pokémon.")


def _save():
    """Atomically write the in-memory data to disk."""
    tmp_path = f"{DATA_FILE}.tmp"
    try:
        with open(tmp_path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False)
        os.replace(tmp_path, DATA_FILE)
    except Exception as e:
        logger.error(f"❌ Failed to save {DATA_FILE}: {e}")


def init_db():
    with _lock:
        _load()
        _save()
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
            _save()
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
            _save()
            return tries, region
        return 0, region


def update_user_region(user_id, region):
    uid = str(user_id)
    with _lock:
        u = data["users"].get(uid)
        if u:
            u["region"] = region
            _save()


def reset_user(user_id):
    uid = str(user_id)
    with _lock:
        u = data["users"].get(uid)
        if u:
            u["tries_left"] = 2500
            u["last_reset"] = _today_str()
            _save()


def get_all_users():
    with _lock:
        return [int(uid) for uid in data["users"].keys()]


# ================== POKEMON MANAGEMENT ==================
def add_caught_pokemon(user_id, name, region, source="Wild"):
    """Adds a caught Pokémon with a fresh random IV spread + nature and returns the created
    record (id, name, region, ivs, nature, iv_percent) so callers don't need to re-scan
    the whole pokemons list just to find what was caught."""
    try:
        with _lock:
            pid = data["next_pokemon_id"]
            data["next_pokemon_id"] = pid + 1
            ivs = _random_ivs()
            nature = _random_nature()
            record = {"id": pid, "user_id": user_id, "name": name, "region": region, "ivs": ivs, "nature": nature}
            data["pokemons"].append(record)
            _save()
            return {"id": pid, "name": name, "region": region, "ivs": ivs, "nature": nature, "iv_percent": iv_percentage(ivs)}
    except Exception:
        logger.exception(f"❌ add_caught_pokemon failed for user_id={user_id} name={name}")
        return None


def _user_matches(p, user_id):
    """Compares a pokemon record's user_id against the caller's user_id, tolerant of
    str/int mismatches (legacy records migrated from Postgres may have stored the
    id as a string, while live code passes Telegram's int id)."""
    pu = p.get("user_id")
    return pu == user_id or str(pu) == str(user_id)


def get_pokemon_ivs(user_id, name):
    """Returns the IV dict for the oldest matching catch, or None.
    ⚡ Filters this user's catches first instead of sorting the entire
    (all-users) pokemons list — sorting the global list here was blocking
    the shared lock for a long time on accounts with a large collection."""
    try:
        with _lock:
            name_lower = (name or "").lower()
            matches = [p for p in data["pokemons"] if _user_matches(p, user_id) and p.get("name", "").lower() == name_lower]
            if not matches:
                return None
            oldest = min(matches, key=lambda p: p.get("id", 0))
            return dict(oldest.get("ivs") or {})
    except Exception:
        logger.exception(f"❌ get_pokemon_ivs failed for user_id={user_id} name={name}")
        return None


def get_pokemon_details(user_id, name):
    """Returns {'ivs': {...}, 'nature': str} for the oldest matching catch, or None.
    Used by /inspect, which needs both IVs and nature together."""
    try:
        with _lock:
            name_lower = (name or "").lower()
            matches = [p for p in data["pokemons"] if _user_matches(p, user_id) and p.get("name", "").lower() == name_lower]
            if not matches:
                return None
            oldest = min(matches, key=lambda p: p.get("id", 0))
            return {
                "ivs": dict(oldest.get("ivs") or {}),
                "nature": oldest.get("nature") or "Hardy",
            }
    except Exception:
        logger.exception(f"❌ get_pokemon_details failed for user_id={user_id} name={name}")
        return None


def get_user_pokemon(user_id):
    """Full records (id, name, region, ivs, iv_percent) for a user, oldest first."""
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


def delete_pokemon(user_id, name):
    """⚡ Filters this user's catches first instead of sorting the entire
    (all-users) pokemons list, for the same reason as get_pokemon_ivs above."""
    try:
        with _lock:
            name_lower = (name or "").lower()
            matches = [p for p in data["pokemons"] if _user_matches(p, user_id) and p.get("name", "").lower() == name_lower]
            if not matches:
                return False
            oldest = min(matches, key=lambda p: p.get("id", 0))
            data["pokemons"].remove(oldest)
            _save()
            return True
    except Exception:
        logger.exception(f"❌ delete_pokemon failed for user_id={user_id} name={name}")
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
        _save()


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
        _save()


# ================== 🏅 BADGE SYSTEM & GYM IMAGES ==================
def add_badge(user_id, badge_name):
    uid = str(user_id)
    with _lock:
        badges = data["user_badges"].setdefault(uid, [])
        if badge_name not in badges:
            badges.append(badge_name)
            _save()


def get_user_badges(user_id):
    uid = str(user_id)
    with _lock:
        return list(data["user_badges"].get(uid, []))


def set_gym_image(leader_name, file_id):
    with _lock:
        data["gym_images"][leader_name] = file_id
        _save()


def get_gym_image(leader_name):
    with _lock:
        return data["gym_images"].get(leader_name)


def delete_gym_image(leader_name):
    """Deletes a faulty image entry, ignoring case (like the old ILIKE)."""
    with _lock:
        target = leader_name.lower()
        keys = [k for k in data["gym_images"].keys() if k.lower() == target]
        for k in keys:
            del data["gym_images"][k]
        if keys:
            _save()


def list_gym_leader_names():
    with _lock:
        return list(data["gym_images"].keys())


def reset_all_badges():
    with _lock:
        data["user_badges"] = {}
        _save()


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
            _save()

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
            _save()
            return t["reward_type"], t["reward_amount"]
        return None


def update_task_pvp(user_id):
    uid = str(user_id)
    with _lock:
        t = data["tasks"].get(uid, {}).get("pvp")
        if t and not t["completed"]:
            t["progress"] += 1
            _save()


def update_task_catch(user_id):
    uid = str(user_id)
    with _lock:
        t = data["tasks"].get(uid, {}).get("catch")
        if t and not t["completed"]:
            t["progress"] += 1
            _save()


def update_task_specific_catch(user_id, pokemon_name):
    uid = str(user_id)
    with _lock:
        t = data["tasks"].get(uid, {}).get("catch_specific")
        if t and not t["completed"] and t["target"].lower() == pokemon_name.lower():
            t["progress"] += 1
            _save()


# ================== GROUP MANAGEMENT ==================
def add_group(group_id):
    with _lock:
        if group_id not in data["groups"]:
            data["groups"].append(group_id)
            _save()


def remove_group(group_id):
    with _lock:
        if group_id in data["groups"]:
            data["groups"].remove(group_id)
            _save()


def get_all_groups():
    with _lock:
        return list(data["groups"])


# ================== CROSS-ACCOUNT TRANSFER ==================
def transfer_user_data(source_uid, target_uid):
    """Moves pokemons, battle_stats and tasks from one user id to another. Returns pokemon count moved."""
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

        _save()
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
                {"user_id": p["user_id"], "name": p["name"], "region": p["region"], "ivs": p.get("ivs") or {}}
                for p in data["pokemons"]
            ],
            "groups": list(data["groups"]),
            "battle_stats": [
                {"user_id": int(uid), "wins": s["wins"], "losses": s["losses"]}
                for uid, s in data["battle_stats"].items()
            ],
        }


def import_backup(backup):
    """
    Loads a JSON backup (in the same shape export_all_data() / the old
    /export command produces) and REPLACES all current data with it.
    Returns a dict with counts of what was imported.
    """
    with _lock:
        new_data = _default_data()

        for u in backup.get("users", []):
            uid = str(u["user_id"])
            new_data["users"][uid] = {
                "tries_left": u.get("tries_left", 2500),
                "region": u.get("region", "Kanto"),
                "last_reset": u.get("last_reset") or _today_str(),
            }

        next_id = 1
        for p in backup.get("pokemons", []):
            new_data["pokemons"].append({
                "id": next_id, "user_id": p["user_id"], "name": p["name"], "region": p.get("region", "Kanto"),
                "ivs": p.get("ivs") or _random_ivs(),
            })
            next_id += 1
        new_data["next_pokemon_id"] = next_id

        for g in backup.get("groups", []):
            gid = g[0] if isinstance(g, (list, tuple)) else g
            if gid not in new_data["groups"]:
                new_data["groups"].append(gid)

        for b in backup.get("battle_stats", []):
            new_data["battle_stats"][str(b["user_id"])] = {"wins": b.get("wins", 0), "losses": b.get("losses", 0)}

        # Carry over anything the backup happens to include for these optional tables
        for uid, badges in backup.get("user_badges", {}).items():
            new_data["user_badges"][uid] = badges
        for leader, file_id in backup.get("gym_images", {}).items():
            new_data["gym_images"][leader] = file_id

        global data
        data = new_data
        _save()

        return {
            "users": len(new_data["users"]),
            "pokemons": len(new_data["pokemons"]),
            "groups": len(new_data["groups"]),
            "battle_stats": len(new_data["battle_stats"]),
        }


def restore_sqlite_data(users_data, pokemons_data, groups_data):
    """Kept for the legacy /restore (.db file) migration path."""
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
            data["pokemons"].append({"id": pid, "user_id": row[0], "name": row[1], "region": row[2], "ivs": _random_ivs()})

        for row in groups_data:
            gid = row[0] if isinstance(row, (list, tuple)) else row
            if gid not in data["groups"]:
                data["groups"].append(gid)

        _save()


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
            writer.writerow(["id", "user_id", "name", "region", "hp", "atk", "def", "spa", "spd", "spe", "iv_percent"])
            for p in data["pokemons"]:
                ivs = p.get("ivs") or {}
                writer.writerow([
                    p["id"], p["user_id"], p["name"], p["region"],
                    ivs.get("hp"), ivs.get("atk"), ivs.get("def"), ivs.get("spa"), ivs.get("spd"), ivs.get("spe"),
                    iv_percentage(ivs),
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
            _save()


def remove_admin(user_id):
    with _lock:
        if user_id in data["admins"]:
            data["admins"].remove(user_id)
            _save()
