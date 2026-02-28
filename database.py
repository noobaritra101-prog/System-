# database.py
import psycopg2
import datetime
from config import DATABASE_URL, logger

def get_conn():
    return psycopg2.connect(DATABASE_URL)

def init_db():
    try:
        conn = get_conn()
        cur = conn.cursor()
        cur.execute("""
            CREATE TABLE IF NOT EXISTS users(
                user_id BIGINT PRIMARY KEY,
                tries_left INTEGER DEFAULT 300,
                region VARCHAR(50) DEFAULT 'Kanto',
                last_reset DATE
            )
        """)
        cur.execute("""
            CREATE TABLE IF NOT EXISTS pokemons(
                id SERIAL PRIMARY KEY,
                user_id BIGINT NOT NULL,
                name VARCHAR(100) NOT NULL,
                region VARCHAR(50) NOT NULL
            )
        """)
        cur.execute("""
            CREATE TABLE IF NOT EXISTS groups(
                group_id BIGINT PRIMARY KEY
            )
        """)
        cur.execute("CREATE INDEX IF NOT EXISTS idx_user_id ON users(user_id)")
        cur.execute("CREATE INDEX IF NOT EXISTS idx_pokemon_user_id ON pokemons(user_id)")
        conn.commit()
        logger.info("PostgreSQL Database initialized successfully")
    except Exception as e:
        logger.error(f"Database initialization failed: {e}")
        raise
    finally:
        conn.close()

def add_group(group_id):
    try:
        conn = get_conn()
        cur = conn.cursor()
        cur.execute("INSERT INTO groups(group_id) VALUES (%s) ON CONFLICT (group_id) DO NOTHING", (group_id,))
        conn.commit()
    except Exception as e:
        logger.error(f"Error adding group {group_id}: {e}")
    finally:
        conn.close()

def remove_group(group_id):
    try:
        conn = get_conn()
        cur = conn.cursor()
        cur.execute("DELETE FROM groups WHERE group_id=%s", (group_id,))
        conn.commit()
    except Exception as e:
        logger.error(f"Error removing group {group_id}: {e}")
    finally:
        conn.close()

def get_all_groups():
    try:
        conn = get_conn()
        cur = conn.cursor()
        cur.execute("SELECT group_id FROM groups ORDER BY group_id")
        rows = cur.fetchall()
        conn.close()
        return [row[0] for row in rows]
    except Exception as e:
        logger.error(f"Error fetching all groups: {e}")
        return []

def get_user(user_id):
    try:
        conn = get_conn()
        cur = conn.cursor()
        cur.execute("SELECT user_id, tries_left, region, last_reset FROM users WHERE user_id=%s", (user_id,))
        row = cur.fetchone()
        conn.close()
        return row
    except Exception as e:
        logger.error(f"Error fetching user {user_id}: {e}")
        return None

def add_user_if_new(user_id):
    existed = get_user(user_id) is not None
    if not existed:
        try:
            conn = get_conn()
            cur = conn.cursor()
            cur.execute("INSERT INTO users(user_id, tries_left, region, last_reset) VALUES (%s, %s, %s, %s)",
                        (user_id, 300, "Kanto", str(datetime.date.today())))
            conn.commit()
            logger.info(f"New user added: {user_id}")
        except Exception as e:
            logger.error(f"Error adding user {user_id}: {e}")
        finally:
            conn.close()
    return not existed

def update_user_tries(user_id):
    try:
        conn = get_conn()
        cur = conn.cursor()
        cur.execute("SELECT tries_left, region, last_reset FROM users WHERE user_id=%s", (user_id,))
        row = cur.fetchone()
        if not row:
            return None, None
        tries_left, region, last_reset = row
        today_str = str(datetime.date.today())
        
        # Postgres returns datetime.date objects, so check properly
        if str(last_reset) != today_str:
            tries_left = 300
            cur.execute("UPDATE users SET tries_left=%s, last_reset=%s WHERE user_id=%s", (tries_left, today_str, user_id))
            conn.commit()
        if tries_left > 0:
            cur.execute("UPDATE users SET tries_left = tries_left - 1 WHERE user_id=%s", (user_id,))
            conn.commit()
        conn.close()
        return tries_left, region
    except Exception as e:
        logger.error(f"Error updating user tries for {user_id}: {e}")
        return None, None

def add_caught_pokemon(user_id, name, region):
    try:
        conn = get_conn()
        cur = conn.cursor()
        cur.execute("INSERT INTO pokemons(user_id, name, region) VALUES (%s, %s, %s)", (user_id, name, region))
        conn.commit()
        conn.close()
    except Exception as e:
        logger.error(f"Error adding Pokémon {name} for {user_id}: {e}")

def list_user_pokemon_names(user_id):
    try:
        conn = get_conn()
        cur = conn.cursor()
        cur.execute("SELECT name FROM pokemons WHERE user_id=%s ORDER BY id DESC", (user_id,))
        rows = cur.fetchall()
        conn.close()
        return [r[0].capitalize() for r in rows]
    except Exception as e:
        logger.error(f"Error listing Pokémon for {user_id}: {e}")
        return []

def delete_pokemon(user_id, pokemon_name):
    try:
        conn = get_conn()
        cur = conn.cursor()
        cur.execute("DELETE FROM pokemons WHERE user_id=%s AND name=%s", (user_id, pokemon_name.capitalize()))
        deleted = cur.rowcount
        conn.commit()
        conn.close()
        return deleted > 0
    except Exception as e:
        logger.error(f"Error deleting Pokémon {pokemon_name} for {user_id}: {e}")
        return False

def get_all_users():
    try:
        conn = get_conn()
        cur = conn.cursor()
        cur.execute("SELECT user_id FROM users ORDER BY user_id")
        rows = cur.fetchall()
        conn.close()
        return [row[0] for row in rows]
    except Exception as e:
        logger.error(f"Error fetching all users: {e}")
        return []

def get_top_trainers(limit=5):
    try:
        conn = get_conn()
        cur = conn.cursor()
        cur.execute("""
            SELECT user_id, COUNT(*) as c
            FROM pokemons
            GROUP BY user_id
            ORDER BY c DESC
            LIMIT %s
        """, (limit,))
        rows = cur.fetchall()
        conn.close()
        return rows
    except Exception as e:
        logger.error(f"Error fetching top trainers: {e}")
        return []
