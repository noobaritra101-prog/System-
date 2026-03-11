# database.py
import psycopg2
from psycopg2 import pool
from psycopg2.extras import execute_values, DictCursor
import datetime
from contextlib import contextmanager
from config import DATABASE_URL, logger

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
            # Create Daily Tasks Table
            cur.execute('''
                CREATE TABLE IF NOT EXISTS daily_tasks (
                    user_id BIGINT PRIMARY KEY,
                    task_date DATE,
                    catch_count INTEGER DEFAULT 0,
                    pvp_count INTEGER DEFAULT 0,
                    trade_count INTEGER DEFAULT 0,
                    catch_claimed BOOLEAN DEFAULT FALSE,
                    pvp_claimed BOOLEAN DEFAULT FALSE,
                    trade_claimed BOOLEAN DEFAULT FALSE
                )
            ''')
            conn.commit()
            
            # 2. Auto-Updater: Safely injects new columns if they are missing
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
                    conn.rollback() # Column exists, skip safely
                    
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

# ==================== DAILY TASKS (PATCHED) ====================
def _ensure_daily_tasks(cur, user_id):
    """Helper to reset tasks automatically at midnight."""
    today = datetime.date.today()
    cur.execute("SELECT task_date FROM daily_tasks WHERE user_id = %s", (user_id,))
    row = cur.fetchone()
    if not row:
        cur.execute("INSERT INTO daily_tasks (user_id, task_date) VALUES (%s, %s)", (user_id, today))
    elif row[0] != today:
        cur.execute("""
            UPDATE daily_tasks 
            SET task_date = %s, catch_count = 0, pvp_count = 0, trade_count = 0, 
                catch_claimed = FALSE, pvp_claimed = FALSE, trade_claimed = FALSE 
            WHERE user_id = %s
        """, (today, user_id))

def get_daily_tasks(user_id):
    with get_db_connection() as conn:
        with conn.cursor(cursor_factory=DictCursor) as cur:
            _ensure_daily_tasks(cur, user_id)
            cur.execute("SELECT catch_count, pvp_count, trade_count, catch_claimed, pvp_claimed, trade_claimed FROM daily_tasks WHERE user_id = %s", (user_id,))
            row = cur.fetchone()
            conn.commit()
            if row:
                # FIX: We map our modern database column names to exactly what tasks.py expects!
                return {
                    'prog_c1': row['catch_count'],
                    'prog_p1': row['pvp_count'],
                    'prog_t1': row['trade_count'],
                    'claim_c1': row['catch_claimed'],
                    'claim_p1': row['pvp_claimed'],
                    'claim_t1': row['trade_claimed']
                }
            return None

def update_task_catch(user_id):
    with get_db_connection() as conn:
        with conn.cursor() as cur:
            _ensure_daily_tasks(cur, user_id)
            cur.execute("UPDATE daily_tasks SET catch_count = catch_count + 1 WHERE user_id = %s", (user_id,))
            conn.commit()

def update_task_pvp(user_id):
    with get_db_connection() as conn:
        with conn.cursor() as cur:
            _ensure_daily_tasks(cur, user_id)
            cur.execute("UPDATE daily_tasks SET pvp_count = pvp_count + 1 WHERE user_id = %s", (user_id,))
            conn.commit()

def update_task_trade(user_id):
    with get_db_connection() as conn:
        with conn.cursor() as cur:
            _ensure_daily_tasks(cur, user_id)
            cur.execute("UPDATE daily_tasks SET trade_count = trade_count + 1 WHERE user_id = %s", (user_id,))
            conn.commit()

def claim_task_reward(user_id, task_type):
    # This safely bridges the claim IDs that tasks.py sends to our new column names
    col_map = {
        'c1': 'catch_claimed', 'catch': 'catch_claimed',
        'p1': 'pvp_claimed', 'pvp': 'pvp_claimed',
        't1': 'trade_claimed', 'trade': 'trade_claimed'
    }
    col = col_map.get(task_type)
    if not col: return
    
    with get_db_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(f"UPDATE daily_tasks SET {col} = TRUE WHERE user_id = %s", (user_id,))
            conn.commit()

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
            
            return {"users": users, "pokemons": pokemons, "groups": groups}

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
