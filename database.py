# database.py
import asyncpg
import asyncio
import threading
import datetime
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
    """Bridge: Runs an async function synchronously safely from main.py or pvp.py."""
    return asyncio.run_coroutine_threadsafe(coro, db_loop).result()

# ================== ASYNC INTERNAL FUNCTIONS ==================
async def _init_db():
    global pool
    # statement_cache_size=0 is required for Supabase PgBouncer compatibility
    pool = await asyncpg.create_pool(
        DATABASE_URL, 
        min_size=1, 
        max_size=10,
        statement_cache_size=0 
    )
    async with pool.acquire() as conn:
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS users(
                user_id BIGINT PRIMARY KEY,
                tries_left INTEGER DEFAULT 300,
                region VARCHAR(50) DEFAULT 'Kanto',
                last_reset DATE
            )
        """)
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS pokemons(
                id SERIAL PRIMARY KEY,
                user_id BIGINT NOT NULL,
                name VARCHAR(100) NOT NULL,
                region VARCHAR(50) NOT NULL
            )
        """)
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS groups(
                group_id BIGINT PRIMARY KEY
            )
        """)
        
        # Create the pvp_settings table if it doesn't exist
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS pvp_settings(
                user_id BIGINT PRIMARY KEY, 
                mode VARCHAR(10) DEFAULT 'Mix', 
                team_size INTEGER DEFAULT 6,
                can_switch BOOLEAN DEFAULT TRUE
            )
        """)
        
        # 💥 THE FIX: Force PostgreSQL to add the missing column if the table already existed!
        await conn.execute("""
            ALTER TABLE pvp_settings 
            ADD COLUMN IF NOT EXISTS can_switch BOOLEAN DEFAULT TRUE
        """)
        
        await conn.execute("CREATE INDEX IF NOT EXISTS idx_user_id ON users(user_id)")
        await conn.execute("CREATE INDEX IF NOT EXISTS idx_pokemon_user_id ON pokemons(user_id)")
    logger.info("asyncpg Database initialized with Settings Support")

async def _get_pvp_settings(user_id):
    async with pool.acquire() as conn:
        row = await conn.fetchrow("SELECT mode, team_size, can_switch FROM pvp_settings WHERE user_id=$1", user_id)
        if row: 
            return row['mode'], row['team_size'], row['can_switch']
        return 'Mix', 6, True

async def _update_pvp_settings(user_id, mode, size, can_switch):
    async with pool.acquire() as conn:
        await conn.execute("""
            INSERT INTO pvp_settings(user_id, mode, team_size, can_switch) VALUES ($1, $2, $3, $4)
            ON CONFLICT (user_id) DO UPDATE SET 
                mode = EXCLUDED.mode, 
                team_size = EXCLUDED.team_size, 
                can_switch = EXCLUDED.can_switch
        """, user_id, mode, size, can_switch)

async def _add_group(group_id):
    async with pool.acquire() as conn:
        await conn.execute("INSERT INTO groups(group_id) VALUES ($1) ON CONFLICT (group_id) DO NOTHING", group_id)

async def _remove_group(group_id):
    async with pool.acquire() as conn:
        await conn.execute("DELETE FROM groups WHERE group_id=$1", group_id)

async def _get_all_groups():
    async with pool.acquire() as conn:
        rows = await conn.fetch("SELECT group_id FROM groups ORDER BY group_id")
        return [r['group_id'] for r in rows]

async def _get_user(user_id):
    async with pool.acquire() as conn:
        return await conn.fetchrow("SELECT user_id, tries_left, region, last_reset FROM users WHERE user_id=$1", user_id)

async def _add_user_if_new(user_id):
    async with pool.acquire() as conn:
        row = await conn.fetchrow("SELECT 1 FROM users WHERE user_id=$1", user_id)
        if not row:
            await conn.execute("INSERT INTO users(user_id, tries_left, region, last_reset) VALUES ($1, $2, $3, $4)",
                               user_id, 300, "Kanto", datetime.date.today())
            return True
        return False

async def _update_user_tries(user_id):
    async with pool.acquire() as conn:
        row = await conn.fetchrow("SELECT tries_left, region, last_reset FROM users WHERE user_id=$1", user_id)
        if not row: return None, None
        
        tries_left, region, last_reset = row['tries_left'], row['region'], row['last_reset']
        today = datetime.date.today()
        
        if last_reset != today:
            tries_left = 300
            await conn.execute("UPDATE users SET tries_left=$1, last_reset=$2 WHERE user_id=$3", tries_left, today, user_id)
        
        if tries_left > 0:
            await conn.execute("UPDATE users SET tries_left = tries_left - 1 WHERE user_id=$1", user_id)
            
        return tries_left, region

async def _add_caught_pokemon(user_id, name, region):
    async with pool.acquire() as conn:
        await conn.execute("INSERT INTO pokemons(user_id, name, region) VALUES ($1, $2, $3)", user_id, name, region)

async def _list_user_pokemon_names(user_id):
    async with pool.acquire() as conn:
        rows = await conn.fetch("SELECT name FROM pokemons WHERE user_id=$1 ORDER BY id DESC", user_id)
        return [r['name'].capitalize() for r in rows]

async def _delete_pokemon(user_id, pokemon_name):
    async with pool.acquire() as conn:
        status = await conn.execute("DELETE FROM pokemons WHERE id IN (SELECT id FROM pokemons WHERE user_id=$1 AND name=$2 LIMIT 1)", 
                                    user_id, pokemon_name.capitalize())
        return int(status.split()[-1]) > 0

async def _get_all_users():
    async with pool.acquire() as conn:
        rows = await conn.fetch("SELECT user_id FROM users ORDER BY user_id")
        return [r['user_id'] for r in rows]

async def _get_top_trainers(limit=5):
    async with pool.acquire() as conn:
        rows = await conn.fetch("SELECT user_id, COUNT(*) as c FROM pokemons GROUP BY user_id ORDER BY c DESC LIMIT $1", limit)
        return [(r['user_id'], r['c']) for r in rows]

async def _reset_user(user_id):
    async with pool.acquire() as conn:
        await conn.execute("UPDATE users SET tries_left=300, last_reset=$1 WHERE user_id=$2", datetime.date.today(), user_id)

async def _update_user_region(user_id, region):
    async with pool.acquire() as conn:
        await conn.execute("UPDATE users SET region=$1 WHERE user_id=$2", region, user_id)

async def _get_debug_stats():
    async with pool.acquire() as conn:
        u_c = await conn.fetchval("SELECT COUNT(*) FROM users")
        p_c = await conn.fetchval("SELECT COUNT(*) FROM pokemons")
        g_c = await conn.fetchval("SELECT COUNT(*) FROM groups")
        return u_c, p_c, g_c

async def _restore_sqlite_data(users, pokemons, groups):
    async with pool.acquire() as conn:
        await conn.executemany("INSERT INTO users(user_id, tries_left, region, last_reset) VALUES ($1, $2, $3, $4) ON CONFLICT (user_id) DO UPDATE SET tries_left = EXCLUDED.tries_left, region = EXCLUDED.region, last_reset = EXCLUDED.last_reset", users)
        if groups: await conn.executemany("INSERT INTO groups(group_id) VALUES ($1) ON CONFLICT (group_id) DO NOTHING", groups)
        if pokemons: await conn.executemany("INSERT INTO pokemons(user_id, name, region) VALUES ($1, $2, $3)", pokemons)

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
def reset_user(user_id): run_sync(_reset_user(user_id))
def update_user_region(user_id, region): run_sync(_update_user_region(user_id, region))
def get_debug_stats(): return run_sync(_get_debug_stats())
def restore_sqlite_data(users, pokemons, groups): run_sync(_restore_sqlite_data(users, pokemons, groups))

# PvP Settings Sync Bridge
def get_pvp_settings(user_id): 
    return run_sync(_get_pvp_settings(user_id))

def update_pvp_settings(user_id, mode, size, can_switch): 
    run_sync(_update_pvp_settings(user_id, mode, size, can_switch))
