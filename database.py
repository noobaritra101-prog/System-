# database.py
import psycopg2
from psycopg2.extras import execute_values
import datetime
from config import DATABASE_URL, logger

def get_conn():
    """Establishes a connection to the Supabase PostgreSQL database."""
    return psycopg2.connect(DATABASE_URL)

def init_db():
    conn = get_conn()
    cur = conn.cursor()
    
    # 1. Create Users Table
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
    
    # Safely inject the new Wins/Losses columns if migrating from an older version
    try:
        cur.execute('ALTER TABLE users ADD COLUMN wins INTEGER DEFAULT 0')
        conn.commit()
    except psycopg2.errors.DuplicateColumn:
        conn.rollback()

    try:
        cur.execute('ALTER TABLE users ADD COLUMN losses INTEGER DEFAULT 0')
        conn.commit()
    except psycopg2.errors.DuplicateColumn:
        conn.rollback()

    # 2. Create Pokemons Table
    cur.execute('''
        CREATE TABLE IF NOT EXISTS pokemons (
            id SERIAL PRIMARY KEY,
            user_id BIGINT,
            name TEXT,
            region TEXT,
            catch_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    
    # Safely inject catch_date if migrating from an older database version
    try:
        cur.execute('ALTER TABLE pokemons ADD COLUMN catch_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP')
        conn.commit()
    except psycopg2.errors.DuplicateColumn:
        conn.rollback()
        
    # 3. Create Groups Table
    cur.execute('''
        CREATE TABLE IF NOT EXISTS groups (
            group_id BIGINT PRIMARY KEY
        )
    ''')

    conn.commit()
    cur.close()
    conn.close()
    logger.info("✅ Database initialized successfully.")

# ==================== USER PROFILE ====================
def add_user_if_new(user_id):
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("SELECT user_id FROM users WHERE user_id = %s", (user_id,))
    if not cur.fetchone():
        cur.execute("INSERT INTO users (user_id, tries_left, last_reset) VALUES (%s, %s, %s)", 
                    (user_id, 300, datetime.date.today()))
        conn.commit()
        is_new = True
    else:
        is_new = False
    cur.close()
    conn.close()
    return is_new

def get_user(user_id):
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("SELECT user_id, tries_left, region, last_reset FROM users WHERE user_id = %s", (user_id,))
    user = cur.fetchone()
    cur.close()
    conn.close()
    return user

def update_user_tries(user_id):
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("SELECT tries_left, region, last_reset FROM users WHERE user_id = %s", (user_id,))
    row = cur.fetchone()
    if not row:
        cur.close()
        conn.close()
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
    cur.close()
    conn.close()
    return tries_left, region

def update_user_region(user_id, region):
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("UPDATE users SET region = %s WHERE user_id = %s", (region, user_id))
    conn.commit()
    cur.close()
    conn.close()

def reset_user(user_id):
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("UPDATE users SET tries_left = 300, last_reset = %s WHERE user_id = %s", 
                (datetime.date.today(), user_id))
    conn.commit()
    cur.close()
    conn.close()

# ==================== POKEMON INVENTORY ====================
def add_caught_pokemon(user_id, name, region):
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("INSERT INTO pokemons (user_id, name, region) VALUES (%s, %s, %s)", 
                (user_id, name, region))
    conn.commit()
    cur.close()
    conn.close()

def list_user_pokemon_names(user_id):
    conn = get_conn()
    cur = conn.cursor()
    # Failsafe in case catch_date is ever strictly missing during a race condition
    try:
        cur.execute("SELECT name FROM pokemons WHERE user_id = %s ORDER BY catch_date ASC", (user_id,))
    except psycopg2.errors.UndefinedColumn:
        conn.rollback()
        cur.execute("SELECT name FROM pokemons WHERE user_id = %s", (user_id,))
    names = [row[0] for row in cur.fetchall()]
    cur.close()
    conn.close()
    return names

def delete_pokemon(user_id, name):
    conn = get_conn()
    cur = conn.cursor()
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
    cur.close()
    conn.close()
    return deleted

# ==================== PVP & BATTLE STATS ====================
def get_battle_stats(user_id):
    """Fetches the Wins and Losses for the Trainer Card."""
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("SELECT wins, losses FROM users WHERE user_id = %s", (user_id,))
    row = cur.fetchone()
    cur.close()
    conn.close()
    if row:
        return row[0], row[1]
    return 0, 0

def update_battle_stats(user_id, is_win):
    """Updates a player's win/loss record after a PvP match."""
    conn = get_conn()
    cur = conn.cursor()
    if is_win:
        cur.execute("UPDATE users SET wins = wins + 1 WHERE user_id = %s", (user_id,))
    else:
        cur.execute("UPDATE users SET losses = losses + 1 WHERE user_id = %s", (user_id,))
    conn.commit()
    cur.close()
    conn.close()

def get_pvp_settings(user_id):
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("SELECT pvp_mode, pvp_size, pvp_switch FROM users WHERE user_id = %s", (user_id,))
    row = cur.fetchone()
    cur.close()
    conn.close()
    if row:
        return row[0], row[1], row[2]
    return "Mix", 6, True

def update_pvp_settings(user_id, mode, size, can_switch):
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("UPDATE users SET pvp_mode = %s, pvp_size = %s, pvp_switch = %s WHERE user_id = %s", 
                (mode, size, can_switch, user_id))
    conn.commit()
    cur.close()
    conn.close()

def update_task_pvp(user_id):
    pass # Hook for tasks.py if needed

# ==================== LEADERBOARD & GLOBAL STATS ====================
def get_top_trainers(limit=5):
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("""
        SELECT user_id, COUNT(*) as count 
        FROM pokemons 
        GROUP BY user_id 
        ORDER BY count DESC 
        LIMIT %s
    """, (limit,))
    results = cur.fetchall()
    cur.close()
    conn.close()
    return results

def get_user_rank(user_id):
    conn = get_conn()
    cur = conn.cursor()
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
    cur.close()
    conn.close()
    return row[0] if row else "Unranked"

def get_all_users():
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("SELECT user_id FROM users")
    users = [row[0] for row in cur.fetchall()]
    cur.close()
    conn.close()
    return users

def get_all_groups():
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("SELECT group_id FROM groups")
    groups = [row[0] for row in cur.fetchall()]
    cur.close()
    conn.close()
    return groups

def add_group(group_id):
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("INSERT INTO groups (group_id) VALUES (%s) ON CONFLICT DO NOTHING", (group_id,))
    conn.commit()
    cur.close()
    conn.close()

def remove_group(group_id):
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("DELETE FROM groups WHERE group_id = %s", (group_id,))
    conn.commit()
    cur.close()
    conn.close()

def get_debug_stats():
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("SELECT COUNT(*) FROM users")
    u_count = cur.fetchone()[0]
    cur.execute("SELECT COUNT(*) FROM pokemons")
    p_count = cur.fetchone()[0]
    cur.execute("SELECT COUNT(*) FROM groups")
    g_count = cur.fetchone()[0]
    cur.close()
    conn.close()
    return u_count, p_count, g_count

# ==================== CLOUD EXPORT & MIGRATE ====================
def export_all_data():
    conn = get_conn()
    cur = conn.cursor()
    try:
        cur.execute("SELECT user_id, tries_left, region, last_reset::text, pvp_mode, pvp_size, pvp_switch, wins, losses FROM users")
        users = [{"user_id": r[0], "tries_left": r[1], "region": r[2], "last_reset": r[3], "pvp_mode": r[4], "pvp_size": r[5], "pvp_switch": r[6], "wins": r[7], "losses": r[8]} for r in cur.fetchall()]
    except Exception as e:
        conn.rollback()
        cur.execute("SELECT user_id, tries_left, region, last_reset::text FROM users")
        users = [{"user_id": r[0], "tries_left": r[1], "region": r[2], "last_reset": r[3], "pvp_mode": "Mix", "pvp_size": 6, "pvp_switch": True, "wins": 0, "losses": 0} for r in cur.fetchall()]

    try:
        cur.execute("SELECT user_id, name, region, catch_date::text FROM pokemons")
        pokemons = [{"user_id": r[0], "name": r[1], "region": r[2], "catch_date": r[3]} for r in cur.fetchall()]
    except Exception as e:
        conn.rollback()
        cur.execute("SELECT user_id, name, region FROM pokemons")
        pokemons = [{"user_id": r[0], "name": r[1], "region": r[2], "catch_date": str(datetime.datetime.now())} for r in cur.fetchall()]

    cur.execute("SELECT group_id FROM groups")
    groups = [{"group_id": r[0]} for r in cur.fetchall()]
    
    cur.close()
    conn.close()
    return {"users": users, "pokemons": pokemons, "groups": groups}

def restore_sqlite_data(users_data, pokemons_data, groups_data):
    conn = get_conn()
    cur = conn.cursor()
    if users_data:
        execute_values(cur, "INSERT INTO users (user_id, tries_left, region, last_reset) VALUES %s ON CONFLICT (user_id) DO NOTHING", users_data)
    if pokemons_data:
        execute_values(cur, "INSERT INTO pokemons (user_id, name, region) VALUES %s", pokemons_data)
    if groups_data:
        execute_values(cur, "INSERT INTO groups (group_id) VALUES %s ON CONFLICT (group_id) DO NOTHING", groups_data)
    conn.commit()
    cur.close()
    conn.close()
