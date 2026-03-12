# database.py
import psycopg2
from psycopg2 import pool
from contextlib import contextmanager
import datetime
from config import DATABASE_URL, logger

# ================== CONNECTION POOL ==================
db_pool = None

def init_db():
    global db_pool
    try:
        # Create a connection pool (Min 1, Max 20 connections for speed)
        db_pool = pool.SimpleConnectionPool(1, 20, DATABASE_URL)
        if db_pool:
            logger.info("✅ Connection pool created successfully")
            
        with get_conn() as conn:
            with conn.cursor() as cur:
                # Core Tables
                cur.execute("""
                    CREATE TABLE IF NOT EXISTS users (
                        user_id BIGINT PRIMARY KEY,
                        tries_left INTEGER DEFAULT 2500,
                        region TEXT DEFAULT 'Kanto',
                        last_reset DATE
                    )
                """)
                cur.execute("""
                    CREATE TABLE IF NOT EXISTS pokemons (
                        id SERIAL PRIMARY KEY,
                        user_id BIGINT,
                        name TEXT,
                        region TEXT
                    )
                """)
                cur.execute("""
                    CREATE TABLE IF NOT EXISTS groups (
                        group_id BIGINT PRIMARY KEY
                    )
                """)
                
                # PvP & Stats Tables
                cur.execute("""
                    CREATE TABLE IF NOT EXISTS pvp_settings (
                        user_id BIGINT PRIMARY KEY,
                        mode TEXT DEFAULT 'Mix',
                        size INTEGER DEFAULT 6,
                        can_switch BOOLEAN DEFAULT TRUE
                    )
                """)
                cur.execute("""
                    CREATE TABLE IF NOT EXISTS battle_stats (
                        user_id BIGINT PRIMARY KEY,
                        wins INTEGER DEFAULT 0,
                        losses INTEGER DEFAULT 0
                    )
                """)
                
                # Tasks Table
                cur.execute("""
                    CREATE TABLE IF NOT EXISTS tasks (
                        user_id BIGINT PRIMARY KEY,
                        task_type TEXT,
                        target TEXT,
                        progress INTEGER DEFAULT 0,
                        goal INTEGER,
                        reward_type TEXT,
                        reward_amount INTEGER,
                        completed BOOLEAN DEFAULT FALSE,
                        last_reset DATE
                    )
                """)
                
                # Speed Indexes
                cur.execute("CREATE INDEX IF NOT EXISTS idx_pokemons_user_id ON pokemons(user_id)")
                conn.commit()
    except Exception as e:
        logger.error(f"❌ Database initialization error: {e}")

@contextmanager
def get_conn():
    """Context manager to safely get and return a connection to the pool."""
    conn = db_pool.getconn()
    try:
        yield conn
    finally:
        db_pool.putconn(conn)

# ================== USER MANAGEMENT ==================
def add_user_if_new(user_id):
    today = datetime.date.today()
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT user_id FROM users WHERE user_id = %s", (user_id,))
            if not cur.fetchone():
                cur.execute("INSERT INTO users (user_id, tries_left, region, last_reset) VALUES (%s, %s, %s, %s)", 
                            (user_id, 2500, 'Kanto', today))
                conn.commit()
                return True
            return False

def get_user(user_id):
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT user_id, tries_left, region, last_reset FROM users WHERE user_id = %s", (user_id,))
            return cur.fetchone()

def update_user_tries(user_id):
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT tries_left, region, last_reset FROM users WHERE user_id = %s", (user_id,))
            row = cur.fetchone()
            if not row: return None, None
            
            tries, region, last_reset = row
            today = datetime.date.today()
            
            if last_reset is None or last_reset < today:
                tries = 2500
                last_reset = today
            
            if tries > 0:
                tries -= 1
                cur.execute("UPDATE users SET tries_left = %s, last_reset = %s WHERE user_id = %s", (tries, last_reset, user_id))
                conn.commit()
                return tries, region
            return 0, region

def update_user_region(user_id, region):
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("UPDATE users SET region = %s WHERE user_id = %s", (region, user_id))
            conn.commit()

def reset_user(user_id):
    today = datetime.date.today()
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("UPDATE users SET tries_left = %s, last_reset = %s WHERE user_id = %s", (2500, today, user_id))
            conn.commit()

def get_all_users():
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT user_id FROM users")
            return [row[0] for row in cur.fetchall()]

# ================== POKEMON MANAGEMENT ==================
def add_caught_pokemon(user_id, name, region):
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("INSERT INTO pokemons (user_id, name, region) VALUES (%s, %s, %s)", (user_id, name, region))
            conn.commit()

def list_user_pokemon_names(user_id):
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT name FROM pokemons WHERE user_id = %s ORDER BY id ASC", (user_id,))
            return [row[0] for row in cur.fetchall()]

def delete_pokemon(user_id, name):
    with get_conn() as conn:
        with conn.cursor() as cur:
            # Delete only one instance of the pokemon using its id
            cur.execute("""
                DELETE FROM pokemons 
                WHERE id = (
                    SELECT id FROM pokemons 
                    WHERE user_id = %s AND name ILIKE %s 
                    LIMIT 1
                ) RETURNING id
            """, (user_id, name))
            deleted = cur.fetchone()
            conn.commit()
            return bool(deleted)

# ================== LEADERBOARD ==================
def get_top_trainers(limit=5):
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT user_id, COUNT(*) as c 
                FROM pokemons 
                GROUP BY user_id 
                ORDER BY c DESC 
                LIMIT %s
            """, (limit,))
            return cur.fetchall()

def get_user_rank(user_id):
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT rank FROM (
                    SELECT user_id, RANK() OVER (ORDER BY COUNT(*) DESC) as rank 
                    FROM pokemons 
                    GROUP BY user_id
                ) sub 
                WHERE user_id = %s
            """, (user_id,))
            row = cur.fetchone()
            return row[0] if row else "Unranked"

# ================== PVP & STATS ==================
def get_pvp_settings(user_id):
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT mode, size, can_switch FROM pvp_settings WHERE user_id = %s", (user_id,))
            row = cur.fetchone()
            if row: return row[0], row[1], row[2]
            return "Mix", 6, True

def update_pvp_settings(user_id, mode, size, can_switch):
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                INSERT INTO pvp_settings (user_id, mode, size, can_switch) 
                VALUES (%s, %s, %s, %s)
                ON CONFLICT (user_id) DO UPDATE 
                SET mode = EXCLUDED.mode, size = EXCLUDED.size, can_switch = EXCLUDED.can_switch
            """, (user_id, mode, size, can_switch))
            conn.commit()

def get_battle_stats(user_id):
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT wins, losses FROM battle_stats WHERE user_id = %s", (user_id,))
            row = cur.fetchone()
            if row: return row[0], row[1]
            return 0, 0

def update_battle_stats(user_id, is_win=True):
    win_inc = 1 if is_win else 0
    loss_inc = 0 if is_win else 1
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                INSERT INTO battle_stats (user_id, wins, losses) 
                VALUES (%s, %s, %s)
                ON CONFLICT (user_id) DO UPDATE 
                SET wins = battle_stats.wins + EXCLUDED.wins, 
                    losses = battle_stats.losses + EXCLUDED.losses
            """, (user_id, win_inc, loss_inc))
            conn.commit()

def update_task_pvp(user_id):
    """Increments a PvP task if the user currently has one active."""
    with get_conn() as conn:
        with conn.cursor() as cur:
            try:
                cur.execute("""
                    UPDATE tasks 
                    SET progress = progress + 1 
                    WHERE user_id = %s AND task_type = 'pvp' AND completed = FALSE
                """, (user_id,))
                conn.commit()
            except:
                conn.rollback()

# ================== GROUP MANAGEMENT ==================
def add_group(group_id):
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("INSERT INTO groups (group_id) VALUES (%s) ON CONFLICT (group_id) DO NOTHING", (group_id,))
            conn.commit()

def remove_group(group_id):
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM groups WHERE group_id = %s", (group_id,))
            conn.commit()

def get_all_groups():
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT group_id FROM groups")
            return [row[0] for row in cur.fetchall()]

# ================== ADMIN TOOLS ==================
def get_debug_stats():
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT COUNT(*) FROM users")
            u_c = cur.fetchone()[0]
            cur.execute("SELECT COUNT(*) FROM pokemons")
            p_c = cur.fetchone()[0]
            cur.execute("SELECT COUNT(*) FROM groups")
            g_c = cur.fetchone()[0]
            return u_c, p_c, g_c

def export_all_data():
    data = {"users": [], "pokemons": [], "groups": [], "battle_stats": []}
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT user_id, tries_left, region, last_reset FROM users")
            data["users"] = [{"user_id": r[0], "tries_left": r[1], "region": r[2], "last_reset": r[3]} for r in cur.fetchall()]
            
            cur.execute("SELECT user_id, name, region FROM pokemons")
            data["pokemons"] = [{"user_id": r[0], "name": r[1], "region": r[2]} for r in cur.fetchall()]
            
            cur.execute("SELECT group_id FROM groups")
            data["groups"] = [r[0] for r in cur.fetchall()]
            
            cur.execute("SELECT user_id, wins, losses FROM battle_stats")
            data["battle_stats"] = [{"user_id": r[0], "wins": r[1], "losses": r[2]} for r in cur.fetchall()]
    return data

def restore_sqlite_data(users_data, pokemons_data, groups_data):
    """Bulk imports data from old SQLite database to PostgreSQL"""
    with get_conn() as conn:
        with conn.cursor() as cur:
            # Users
            psycopg2.extras.execute_batch(cur, """
                INSERT INTO users (user_id, tries_left, region, last_reset) 
                VALUES (%s, %s, %s, %s)
                ON CONFLICT (user_id) DO NOTHING
            """, users_data)
            
            # Pokemons
            psycopg2.extras.execute_batch(cur, """
                INSERT INTO pokemons (user_id, name, region) 
                VALUES (%s, %s, %s)
            """, pokemons_data)
            
            # Groups
            psycopg2.extras.execute_batch(cur, """
                INSERT INTO groups (group_id) 
                VALUES (%s)
                ON CONFLICT (group_id) DO NOTHING
            """, [(g[0],) for g in groups_data])
            
        conn.commit()
