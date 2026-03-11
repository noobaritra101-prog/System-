# database.py
import psycopg2
from psycopg2 import pool
from psycopg2.extras import execute_values, DictCursor
import datetime
import random
from contextlib import contextmanager
from config import DATABASE_URL, logger
from api_utils import pokemon_name_to_id_cache, LEGENDARY_NAMES

# ==================== CONNECTION POOLING ====================
try:
    db_pool = pool.SimpleConnectionPool(1, 20, DATABASE_URL)
    if db_pool:
        logger.info("✅ High-Speed PostgreSQL Connection Pool initialized!")
except Exception as e:
    logger.error(f"❌ Failed to create connection pool: {e}")

@contextmanager
def get_db_connection():
    """Yields a fast connection from the pool and automatically returns it."""
    conn = db_pool.getconn()
    try:
        yield conn
    finally:
        db_pool.putconn(conn)

# ==================== INITIALIZATION ====================
def init_db():
    with get_db_connection() as conn:
        with conn.cursor() as cur:
            # 1. Create Core Tables
            cur.execute('''
                CREATE TABLE IF NOT EXISTS users (
                    user_id BIGINT PRIMARY KEY,
                    tries_left INTEGER DEFAULT 300,
                    region TEXT DEFAULT 'Kanto',
                    last_reset DATE,
                    pvp_mode TEXT DEFAULT 'Mix',
                    pvp_size INTEGER DEFAULT 6,
                    pvp_switch BOOLEAN DEFAULT TRUE,
                    wins INTEGER DEFAULT 0,
                    losses INTEGER DEFAULT 0
                )
            ''')
            cur.execute('''
                CREATE TABLE IF NOT EXISTS pokemons (
                    id SERIAL PRIMARY KEY,
                    user_id BIGINT,
                    name TEXT,
                    region TEXT,
                    catch_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            ''')
            cur.execute('''
                CREATE TABLE IF NOT EXISTS groups (
                    group_id BIGINT PRIMARY KEY
                )
            ''')
            
            # --- AUTO-REPAIR THE BAD TASKS TABLE ---
            try:
                # Check if our table has the correct advanced columns
                cur.execute("SELECT target_p1 FROM daily_tasks LIMIT 1")
            except psycopg2.errors.UndefinedColumn:
                # If it doesn't, it's the broken generic table. We safely drop it to rebuild it!
                conn.rollback()
                cur.execute("DROP TABLE IF EXISTS daily_tasks")
                conn.commit()
            except psycopg2.errors.UndefinedTable:
                conn.rollback()

            # Create Advanced Daily Tasks Table
            cur.execute('''
                CREATE TABLE IF NOT EXISTS daily_tasks (
                    user_id BIGINT PRIMARY KEY,
                    task_date DATE,
                    target_p1 TEXT,
                    target_p2 TEXT,
                    target_pvp INTEGER,
                    target_catch INTEGER,
                    prog_p1 BOOLEAN DEFAULT FALSE,
                    prog_p2 BOOLEAN DEFAULT FALSE,
                    prog_pvp INTEGER DEFAULT 0,
                    prog_catch INTEGER DEFAULT 0,
                    reward_poke TEXT,
                    claimed BOOLEAN DEFAULT FALSE
                )
            ''')
            conn.commit()
            
            # 2. Auto-Updater for Core Tables
            updates = [
                ("users", "pvp_mode", "TEXT DEFAULT 'Mix'"),
                ("users", "pvp_size", "INTEGER DEFAULT 6"),
                ("users", "pvp_switch", "BOOLEAN DEFAULT TRUE"),
                ("users", "wins", "INTEGER DEFAULT 0"),
                ("users", "losses", "INTEGER DEFAULT 0"),
                ("pokemons", "catch_date", "TIMESTAMP DEFAULT CURRENT_TIMESTAMP")
            ]
            for table, col, dtype in updates:
                try:
                    cur.execute(f"ALTER TABLE {table} ADD COLUMN {col} {dtype}")
                    conn.commit()
                except psycopg2.errors.DuplicateColumn:
                    conn.rollback()
                    
    logger.info("✅ Database verified and patched successfully.")

# ==================== USER PROFILE ====================
def add_user_if_new(user_id):
    with get_db_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT user_id FROM users WHERE user_id = %s", (user_id,))
            if not cur.fetchone():
                cur.execute("INSERT INTO users (user_id, tries_left, last_reset) VALUES (%s, %s, %s)", 
                            (user_id, 300, datetime.date.today()))
                conn.commit()
                return True
            return False

def get_user(user_id):
    with get_db_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT user_id, tries_left, region, last_reset FROM users WHERE user_id = %s", (user_id,))
            return cur.fetchone()

def update_user_tries(user_id):
    with get_db_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT tries_left, region, last_reset FROM users WHERE user_id = %s", (user_id,))
            row = cur.fetchone()
            if not row:
                return None, None
                
            tries_left, region, last_reset = row
            today = datetime.date.today()
            
            if last_reset != today:
                tries_left = 300
                cur.execute("UPDATE users SET tries_left = %s, last_reset = %s WHERE user_id = %s", 
                            (tries_left, today, user_id))
            
            if tries_left > 0:
                tries_left -= 1
                cur.execute("UPDATE users SET tries_left = %s WHERE user_id = %s", (tries_left, user_id))
                
            conn.commit()
            return tries_left, region

def update_user_region(user_id, region):
    with get_db_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("UPDATE users SET region = %s WHERE user_id = %s", (region, user_id))
            conn.commit()

def reset_user(user_id):
    with get_db_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("UPDATE users SET tries_left = 300, last_reset = %s WHERE user_id = %s", 
                        (datetime.date.today(), user_id))
            conn.commit()

# ==================== POKEMON INVENTORY ====================
def add_caught_pokemon(user_id, name, region):
    with get_db_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("INSERT INTO pokemons (user_id, name, region) VALUES (%s, %s, %s)", 
                        (user_id, name, region))
            conn.commit()

def list_user_pokemon_names(user_id):
    with get_db_connection() as conn:
        with conn.cursor() as cur:
            try:
                cur.execute("SELECT name FROM pokemons WHERE user_id = %s ORDER BY catch_date ASC", (user_id,))
            except psycopg2.errors.UndefinedColumn:
                conn.rollback()
                cur.execute("SELECT name FROM pokemons WHERE user_id = %s", (user_id,))
            return [row[0] for row in cur.fetchall()]

def delete_pokemon(user_id, name):
    with get_db_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                DELETE FROM pokemons 
                WHERE id IN (
                    SELECT id FROM pokemons 
                    WHERE user_id = %s AND name = %s 
                    LIMIT 1
                )
            """, (user_id, name))
            deleted = cur.rowcount > 0
            conn.commit()
            return deleted

# ==================== DAILY TASKS (ADVANCED VERSION) ====================
def _ensure_daily_tasks(cur, user_id):
    """Helper to reset tasks automatically at midnight and generate specific targets."""
    today = datetime.date.today()
    cur.execute("SELECT task_date FROM daily_tasks WHERE user_id = %s", (user_id,))
    row = cur.fetchone()
    
    if not row or row[0] != today:
        # Generate new randomized task goals!
        all_pokes = list(pokemon_name_to_id_cache.keys())
        if not all_pokes: all_pokes = ["Pikachu", "Eevee", "Charmander", "Squirtle"]
        
        t_p1 = random.choice(all_pokes).title()
        t_p2 = random.choice(all_pokes).title()
        t_pvp = random.randint(1, 3) # Win 1 to 3 matches
        t_catch = random.randint(5, 15) # Catch 5 to 15 pokemon
        
        # FIX: We convert LEGENDARY_NAMES to a list so random.choice() can read it!
        reward = random.choice(list(LEGENDARY_NAMES)) if LEGENDARY_NAMES else "Mewtwo"
        
        if not row:
            cur.execute("""
                INSERT INTO daily_tasks (user_id, task_date, target_p1, target_p2, target_pvp, target_catch, reward_poke)
                VALUES (%s, %s, %s, %s, %s, %s, %s)
            """, (user_id, today, t_p1, t_p2, t_pvp, t_catch, reward))
        else:
            cur.execute("""
                UPDATE daily_tasks 
                SET task_date = %s, target_p1 = %s, target_p2 = %s, target_pvp = %s, target_catch = %s, 
                    prog_p1 = FALSE, prog_p2 = FALSE, prog_pvp = 0, prog_catch = 0, 
                    reward_poke = %s, claimed = FALSE
                WHERE user_id = %s
            """, (today, t_p1, t_p2, t_pvp, t_catch, reward, user_id))

def get_daily_tasks(user_id):
    with get_db_connection() as conn:
        with conn.cursor(cursor_factory=DictCursor) as cur:
            _ensure_daily_tasks(cur, user_id)
            cur.execute("SELECT * FROM daily_tasks WHERE user_id = %s", (user_id,))
            row = cur.fetchone()
            conn.commit()
            if row:
                return dict(row) # This returns the exact dictionary structure your tasks.py expects!
            return None

def update_task_catch(user_id, pokemon_name):
    with get_db_connection() as conn:
        with conn.cursor() as cur:
            _ensure_daily_tasks(cur, user_id)
            cur.execute("SELECT target_p1, target_p2, prog_p1, prog_p2 FROM daily_tasks WHERE user_id = %s", (user_id,))
            row = cur.fetchone()
            if row:
                t_p1, t_p2, p_p1, p_p2 = row
                
                # Check if they caught one of the specific target pokemon!
                if pokemon_name.lower() == t_p1.lower() and not p_p1:
                    cur.execute("UPDATE daily_tasks SET prog_p1 = TRUE WHERE user_id = %s", (user_id,))
                if pokemon_name.lower() == t_p2.lower() and not p_p2:
                    cur.execute("UPDATE daily_tasks SET prog_p2 = TRUE WHERE user_id = %s", (user_id,))
                    
                # Always tick up their overall catch count
                cur.execute("UPDATE daily_tasks SET prog_catch = prog_catch + 1 WHERE user_id = %s", (user_id,))
            conn.commit()

def update_task_pvp(user_id):
    with get_db_connection() as conn:
        with conn.cursor() as cur:
            _ensure_daily_tasks(cur, user_id)
            cur.execute("UPDATE daily_tasks SET prog_pvp = prog_pvp + 1 WHERE user_id = %s", (user_id,))
            conn.commit()

def claim_daily_reward(user_id):
    """Marks task as claimed and inserts the reward Pokemon directly into inventory."""
    with get_db_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT reward_poke, claimed FROM daily_tasks WHERE user_id = %s", (user_id,))
            row = cur.fetchone()
            if row and not row[1]:
                reward = row[0]
                cur.execute("UPDATE daily_tasks SET claimed = TRUE WHERE user_id = %s", (user_id,))
                
                # Get user's region to spawn the reward properly
                cur.execute("SELECT region FROM users WHERE user_id = %s", (user_id,))
                user_reg = cur.fetchone()
                reg = user_reg[0] if user_reg else "Reward"
                
                # Add the pokemon to their bag!
                cur.execute("INSERT INTO pokemons (user_id, name, region) VALUES (%s, %s, %s)", (user_id, reward, reg))
                conn.commit()
                return True, reward
            return False, None

# ==================== PVP & BATTLE STATS ====================
def get_battle_stats(user_id):
    with get_db_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT wins, losses FROM users WHERE user_id = %s", (user_id,))
            row = cur.fetchone()
            return (row[0], row[1]) if row else (0, 0)

def update_battle_stats(user_id, is_win):
    with get_db_connection() as conn:
        with conn.cursor() as cur:
            if is_win:
                cur.execute("UPDATE users SET wins = wins + 1 WHERE user_id = %s", (user_id,))
            else:
                cur.execute("UPDATE users SET losses = losses + 1 WHERE user_id = %s", (user_id,))
            conn.commit()

def get_pvp_settings(user_id):
    with get_db_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT pvp_mode, pvp_size, pvp_switch FROM users WHERE user_id = %s", (user_id,))
            row = cur.fetchone()
            return (row[0], row[1], row[2]) if row else ("Mix", 6, True)

def update_pvp_settings(user_id, mode, size, can_switch):
    with get_db_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("UPDATE users SET pvp_mode = %s, pvp_size = %s, pvp_switch = %s WHERE user_id = %s", 
                        (mode, size, can_switch, user_id))
            conn.commit()

# ==================== LEADERBOARD & GLOBAL STATS ====================
def get_top_trainers(limit=5):
    with get_db_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT user_id, COUNT(*) as count 
                FROM pokemons 
                GROUP BY user_id 
                ORDER BY count DESC 
                LIMIT %s
            """, (limit,))
            return cur.fetchall()

def get_user_rank(user_id):
    with get_db_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                WITH RankedUsers AS (
                    SELECT user_id, COUNT(*) as count,
                    RANK() OVER(ORDER BY COUNT(*) DESC) as rank
                    FROM pokemons
                    GROUP BY user_id
                )
                SELECT rank FROM RankedUsers WHERE user_id = %s
            """, (user_id,))
            row = cur.fetchone()
            return row[0] if row else "Unranked"

def get_all_users():
    with get_db_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT user_id FROM users")
            return [row[0] for row in cur.fetchall()]

def get_all_groups():
    with get_db_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT group_id FROM groups")
            return [row[0] for row in cur.fetchall()]

def add_group(group_id):
    with get_db_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("INSERT INTO groups (group_id) VALUES (%s) ON CONFLICT DO NOTHING", (group_id,))
            conn.commit()

def remove_group(group_id):
    with get_db_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM groups WHERE group_id = %s", (group_id,))
            conn.commit()

def get_debug_stats():
    with get_db_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT COUNT(*) FROM users")
            u_count = cur.fetchone()[0]
            cur.execute("SELECT COUNT(*) FROM pokemons")
            p_count = cur.fetchone()[0]
            cur.execute("SELECT COUNT(*) FROM groups")
            g_count = cur.fetchone()[0]
            return u_count, p_count, g_count

# ==================== CLOUD EXPORT & MIGRATE ====================
def export_all_data():
    with get_db_connection() as conn:
        with conn.cursor() as cur:
            try:
                cur.execute("SELECT user_id, tries_left, region, last_reset::text, pvp_mode, pvp_size, pvp_switch, wins, losses FROM users")
                users = [{"user_id": r[0], "tries_left": r[1], "region": r[2], "last_reset": r[3], "pvp_mode": r[4], "pvp_size": r[5], "pvp_switch": r[6], "wins": r[7], "losses": r[8]} for r in cur.fetchall()]
            except Exception:
                conn.rollback()
                cur.execute("SELECT user_id, tries_left, region, last_reset::text FROM users")
                users = [{"user_id": r[0], "tries_left": r[1], "region": r[2], "last_reset": r[3], "pvp_mode": "Mix", "pvp_size": 6, "pvp_switch": True, "wins": 0, "losses": 0} for r in cur.fetchall()]

            try:
                cur.execute("SELECT user_id, name, region, catch_date::text FROM pokemons")
                pokemons = [{"user_id": r[0], "name": r[1], "region": r[2], "catch_date": r[3]} for r in cur.fetchall()]
            except Exception:
                conn.rollback()
                cur.execute("SELECT user_id, name, region FROM pokemons")
                pokemons = [{"user_id": r[0], "name": r[1], "region": r[2], "catch_date": str(datetime.datetime.now())} for r in cur.fetchall()]

            cur.execute("SELECT group_id FROM groups")
            groups = [{"group_id": r[0]} for r in cur.fetchall()]
            
            return {"users": users, "pokemons": groups, "groups": groups}

def restore_sqlite_data(users_data, pokemons_data, groups_data):
    with get_db_connection() as conn:
        with conn.cursor() as cur:
            if users_data:
                execute_values(cur, "INSERT INTO users (user_id, tries_left, region, last_reset) VALUES %s ON CONFLICT (user_id) DO NOTHING", users_data)
            if pokemons_data:
                execute_values(cur, "INSERT INTO pokemons (user_id, name, region) VALUES %s", pokemons_data)
            if groups_data:
                execute_values(cur, "INSERT INTO groups (group_id) VALUES %s ON CONFLICT (group_id) DO NOTHING", groups_data)
            conn.commit()
