# database.py
import asyncpg
import asyncio
import threading
import datetime
import random
from config import DATABASE_URL, logger

# Dedicated event loop for database operations
db_loop = asyncio.new_event_loop()
pool = None

def _run_db_loop(loop):
    asyncio.set_event_loop(loop)
    loop.run_forever()

# Start the background database thread
db_thread = threading.Thread(target=_run_db_loop, args=(db_loop,), daemon=True)
db_thread.start()

def run_sync(coro):
    """Bridge: Runs an async function synchronously safely from main.py, pvp.py, or trade.py."""
    return asyncio.run_coroutine_threadsafe(coro, db_loop).result()

# --- 5:30 AM IST RESET LOGIC ---
def get_logical_date():
    """Returns today's date, but only rolls over at 5:30 AM IST."""
    # Convert server time to precise IST (UTC + 5:30)
    ist_now = datetime.datetime.utcnow() + datetime.timedelta(hours=5, minutes=30)
    reset_time = datetime.time(5, 30)
    
    # If it is currently before 5:30 AM, it counts as "yesterday"
    if ist_now.time() < reset_time:
        return (ist_now - datetime.timedelta(days=1)).date()
    return ist_now.date()

# ================== ASYNC INTERNAL FUNCTIONS ==================
async def _init_db():
    global pool
    # statement_cache_size=0 is required for Supabase PgBouncer compatibility
    pool = await asyncpg.create_pool(DATABASE_URL, min_size=1, max_size=10, statement_cache_size=0)
    async with pool.acquire() as conn:
        await conn.execute("CREATE TABLE IF NOT EXISTS users(user_id BIGINT PRIMARY KEY, tries_left INTEGER DEFAULT 300, region VARCHAR(50) DEFAULT 'Kanto', last_reset DATE)")
        await conn.execute("CREATE TABLE IF NOT EXISTS pokemons(id SERIAL PRIMARY KEY, user_id BIGINT NOT NULL, name VARCHAR(100) NOT NULL, region VARCHAR(50) NOT NULL)")
        await conn.execute("CREATE TABLE IF NOT EXISTS groups(group_id BIGINT PRIMARY KEY)")
        
        await conn.execute("CREATE TABLE IF NOT EXISTS pvp_settings(user_id BIGINT PRIMARY KEY, mode VARCHAR(10) DEFAULT 'Mix', team_size INTEGER DEFAULT 6, can_switch BOOLEAN DEFAULT TRUE)")
        await conn.execute("ALTER TABLE pvp_settings ADD COLUMN IF NOT EXISTS can_switch BOOLEAN DEFAULT TRUE")
        
        # Dynamic Tasks Table
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS user_tasks(
                user_id BIGINT PRIMARY KEY, last_reset DATE,
                target_p1 VARCHAR(50), target_p2 VARCHAR(50),
                target_pvp INTEGER, target_catch INTEGER,
                prog_p1 BOOLEAN DEFAULT FALSE, prog_p2 BOOLEAN DEFAULT FALSE,
                prog_pvp INTEGER DEFAULT 0, prog_catch INTEGER DEFAULT 0,
                claimed BOOLEAN DEFAULT FALSE, reward_poke VARCHAR(50)
            )
        """)
        
        await conn.execute("CREATE INDEX IF NOT EXISTS idx_user_id ON users(user_id)")
        await conn.execute("CREATE INDEX IF NOT EXISTS idx_pokemon_user_id ON pokemons(user_id)")
    logger.info("✅ asyncpg Database initialized with 5:30 AM Reset")

# --- DYNAMIC DAILY TASKS SYSTEM ---
async def _get_daily_tasks(user_id):
    today = get_logical_date() # <--- Using 5:30 AM Reset!
    async with pool.acquire() as conn:
        row = await conn.fetchrow("SELECT * FROM user_tasks WHERE user_id=$1", user_id)
        
        # If no tasks exist, or if the date has rolled over past 5:30 AM, generate new ones!
        if not row or row['last_reset'] != today:
            from api_utils import LEGENDARY_NAMES, pokemon_cache
            
            # Filter to non-legendary pokemon for targets and rewards
            available = [name for name in pokemon_cache.values() if name not in LEGENDARY_NAMES]
            if len(available) < 3: 
                available = ["Pikachu", "Eevee", "Bulbasaur", "Charmander", "Squirtle", "Pidgey", "Snorlax", "Gengar", "Lucario"]
            
            t_p1, t_p2, reward = random.sample(available, 3)
            t_pvp = random.randint(1, 6)
            t_catch = random.randint(15, 40)
            
            await conn.execute("""
                INSERT INTO user_tasks (user_id, last_reset, target_p1, target_p2, target_pvp, target_catch, prog_p1, prog_p2, prog_pvp, prog_catch, claimed, reward_poke)
                VALUES ($1, $2, $3, $4, $5, $6, FALSE, FALSE, 0, 0, FALSE, $7)
                ON CONFLICT (user_id) DO UPDATE SET
                last_reset = EXCLUDED.last_reset, target_p1 = EXCLUDED.target_p1, target_p2 = EXCLUDED.target_p2, target_pvp = EXCLUDED.target_pvp, target_catch = EXCLUDED.target_catch, prog_p1 = FALSE, prog_p2 = FALSE, prog_pvp = 0, prog_catch = 0, claimed = FALSE, reward_poke = EXCLUDED.reward_poke
            """, user_id, today, t_p1, t_p2, t_pvp, t_catch, reward)
            
            return {'target_p1': t_p1, 'target_p2': t_p2, 'target_pvp': t_pvp, 'target_catch': t_catch, 'prog_p1': False, 'prog_p2': False, 'prog_pvp': 0, 'prog_catch': 0, 'claimed': False, 'reward_poke': reward}
        return dict(row)

async def _update_task_catch(user_id, pokemon_name):
    row = await _get_daily_tasks(user_id)
    if row['claimed']: return
    async with pool.acquire() as conn:
        await conn.execute("UPDATE user_tasks SET prog_catch = prog_catch + 1 WHERE user_id=$1", user_id)
        if pokemon_name.lower() == row['target_p1'].lower() and not row['prog_p1']:
            await conn.execute("UPDATE user_tasks SET prog_p1 = TRUE WHERE user_id=$1", user_id)
        if pokemon_name.lower() == row['target_p2'].lower() and not row['prog_p2']:
            await conn.execute("UPDATE user_tasks SET prog_p2 = TRUE WHERE user_id=$1", user_id)

async def _update_task_pvp(user_id):
    row = await _get_daily_tasks(user_id)
    if row['claimed']: return
    async with pool.acquire() as conn:
        await conn.execute("UPDATE user_tasks SET prog_pvp = prog_pvp + 1 WHERE user_id=$1", user_id)

async def _claim_daily_reward(user_id):
    row = await _get_daily_tasks(user_id)
    if row['claimed']: return False, None
    if row['prog_p1'] and row['prog_p2'] and row['prog_pvp'] >= row['target_pvp'] and row['prog_catch'] >= row['target_catch']:
        async with pool.acquire() as conn:
            await conn.execute("UPDATE user_tasks SET claimed=TRUE WHERE user_id=$1", user_id)
        await _add_caught_pokemon(user_id, f"{row['reward_poke']} (Shiny)", "Daily Task")
        return True, row['reward_poke']
    return False, None

# --- EXISTING DB FUNCTIONS ---
async def _get_pvp_settings(user_id):
    async with pool.acquire() as conn:
        row = await conn.fetchrow("SELECT mode, team_size, can_switch FROM pvp_settings WHERE user_id=$1", user_id)
        return (row['mode'], row['team_size'], row['can_switch']) if row else ('Mix', 6, True)

async def _update_pvp_settings(user_id, mode, size, can_switch):
    async with pool.acquire() as conn: await conn.execute("INSERT INTO pvp_settings(user_id, mode, team_size, can_switch) VALUES ($1, $2, $3, $4) ON CONFLICT (user_id) DO UPDATE SET mode = EXCLUDED.mode, team_size = EXCLUDED.team_size, can_switch = EXCLUDED.can_switch", user_id, mode, size, can_switch)

async def _add_group(group_id):
    async with pool.acquire() as conn: await conn.execute("INSERT INTO groups(group_id) VALUES ($1) ON CONFLICT (group_id) DO NOTHING", group_id)

async def _remove_group(group_id):
    async with pool.acquire() as conn: await conn.execute("DELETE FROM groups WHERE group_id=$1", group_id)

async def _get_all_groups():
    async with pool.acquire() as conn: return [r['group_id'] for r in await conn.fetch("SELECT group_id FROM groups ORDER BY group_id")]

async def _get_user(user_id):
    async with pool.acquire() as conn: return await conn.fetchrow("SELECT user_id, tries_left, region, last_reset FROM users WHERE user_id=$1", user_id)

async def _add_user_if_new(user_id):
    async with pool.acquire() as conn:
        if not await conn.fetchrow("SELECT 1 FROM users WHERE user_id=$1", user_id):
            await conn.execute("INSERT INTO users(user_id, tries_left, region, last_reset) VALUES ($1, $2, $3, $4)", user_id, 300, "Kanto", get_logical_date())
            return True
        return False

async def _update_user_tries(user_id):
    async with pool.acquire() as conn:
        row = await conn.fetchrow("SELECT tries_left, region, last_reset FROM users WHERE user_id=$1", user_id)
        if not row: return None, None
        tries_left, region, last_reset = row['tries_left'], row['region'], row['last_reset']
        today = get_logical_date() # <--- Using 5:30 AM Reset!
        if last_reset != today:
            tries_left = 300
            await conn.execute("UPDATE users SET tries_left=$1, last_reset=$2 WHERE user_id=$3", tries_left, today, user_id)
        if tries_left > 0: await conn.execute("UPDATE users SET tries_left = tries_left - 1 WHERE user_id=$1", user_id)
        return tries_left, region

async def _add_caught_pokemon(user_id, name, region):
    async with pool.acquire() as conn: await conn.execute("INSERT INTO pokemons(user_id, name, region) VALUES ($1, $2, $3)", user_id, name, region)

async def _list_user_pokemon_names(user_id):
    async with pool.acquire() as conn: return [r['name'].capitalize() for r in await conn.fetch("SELECT name FROM pokemons WHERE user_id=$1 ORDER BY id DESC", user_id)]

async def _delete_pokemon(user_id, pokemon_name):
    async with pool.acquire() as conn:
        status = await conn.execute("DELETE FROM pokemons WHERE id IN (SELECT id FROM pokemons WHERE user_id=$1 AND name=$2 LIMIT 1)", user_id, pokemon_name.capitalize())
        return int(status.split()[-1]) > 0

async def _get_all_users():
    async with pool.acquire() as conn: return [r['user_id'] for r in await conn.fetch("SELECT user_id FROM users ORDER BY user_id")]

async def _get_top_trainers(limit=5):
    async with pool.acquire() as conn: return [(r['user_id'], r['c']) for r in await conn.fetch("SELECT user_id, COUNT(*) as c FROM pokemons GROUP BY user_id ORDER BY c DESC LIMIT $1", limit)]

async def _get_user_rank(user_id):
    async with pool.acquire() as conn:
        return await conn.fetchval("SELECT rank FROM (SELECT user_id, RANK() OVER (ORDER BY COUNT(*) DESC) as rank FROM pokemons GROUP BY user_id) sub WHERE user_id=$1", user_id) or "N/A"

async def _reset_user(user_id):
    async with pool.acquire() as conn: await conn.execute("UPDATE users SET tries_left=300, last_reset=$1 WHERE user_id=$2", get_logical_date(), user_id)

async def _update_user_region(user_id, region):
    async with pool.acquire() as conn: await conn.execute("UPDATE users SET region=$1 WHERE user_id=$2", region, user_id)

async def _get_debug_stats():
    async with pool.acquire() as conn: return await conn.fetchval("SELECT COUNT(*) FROM users"), await conn.fetchval("SELECT COUNT(*) FROM pokemons"), await conn.fetchval("SELECT COUNT(*) FROM groups")

async def _restore_sqlite_data(users, pokemons, groups):
    async with pool.acquire() as conn:
        await conn.executemany("INSERT INTO users(user_id, tries_left, region, last_reset) VALUES ($1, $2, $3, $4) ON CONFLICT (user_id) DO UPDATE SET tries_left = EXCLUDED.tries_left, region = EXCLUDED.region, last_reset = EXCLUDED.last_reset", users)
        if groups: await conn.executemany("INSERT INTO groups(group_id) VALUES ($1) ON CONFLICT (group_id) DO NOTHING", groups)
        if pokemons: await conn.executemany("INSERT INTO pokemons(user_id, name, region) VALUES ($1, $2, $3)", pokemons)

# --- EXPORT SYSTEM ---
async def _export_all_data():
    async with pool.acquire() as conn:
        users = [dict(r) for r in await conn.fetch("SELECT * FROM users")]
        pokemons = [dict(r) for r in await conn.fetch("SELECT * FROM pokemons")]
        groups = [dict(r) for r in await conn.fetch("SELECT * FROM groups")]
        pvp = [dict(r) for r in await conn.fetch("SELECT * FROM pvp_settings")]
        tasks = [dict(r) for r in await conn.fetch("SELECT * FROM user_tasks")]
        
        return {
            "users": users,
            "pokemons": pokemons,
            "groups": groups,
            "pvp_settings": pvp,
            "user_tasks": tasks
        }

# ================== SYNC EXPOSED API ==================
def init_db(): run_sync(_init_db())
def add_group(group_id): run_sync(_add_group(group_id))
def remove_group(group_id): run_sync(_remove_group(group_id))
def get_all_groups(): return run_sync(_get_all_groups())
def get_user(user_id): return run_sync(_get_user(user_id))
def add_user_if_new(user_id): return run_sync(_add_user_if_new(user_id))
def update_user_tries(user_id): return run_sync(_update_user_tries(user_id))
def add_caught_pokemon(user_id, name, region): run_sync(_add_caught_pokemon(user_id, name, region))
def list_user_pokemon_names(user_id): return run_sync(_list_user_pokemon_names(user_id))
def delete_pokemon(user_id, pokemon_name): return run_sync(_delete_pokemon(user_id, pokemon_name))
def get_all_users(): return run_sync(_get_all_users())
def get_top_trainers(limit=5): return run_sync(_get_top_trainers(limit))
def get_user_rank(user_id): return run_sync(_get_user_rank(user_id))
def reset_user(user_id): run_sync(_reset_user(user_id))
def update_user_region(user_id, region): run_sync(_update_user_region(user_id, region))
def get_debug_stats(): return run_sync(_get_debug_stats())
def restore_sqlite_data(users, pokemons, groups): run_sync(_restore_sqlite_data(users, pokemons, groups))
def get_pvp_settings(user_id): return run_sync(_get_pvp_settings(user_id))
def update_pvp_settings(user_id, mode, size, can_switch): run_sync(_update_pvp_settings(user_id, mode, size, can_switch))

# --- NEW TASKS EXPOSED ---
def get_daily_tasks(user_id): return run_sync(_get_daily_tasks(user_id))
def update_task_catch(user_id, pokemon_name): run_sync(_update_task_catch(user_id, pokemon_name))
def update_task_pvp(user_id): run_sync(_update_task_pvp(user_id))
def claim_daily_reward(user_id): return run_sync(_claim_daily_reward(user_id))

# --- EXPORT DATA EXPOSED ---
def export_all_data(): return run_sync(_export_all_data())
