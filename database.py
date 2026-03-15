# database.py
import psycopg2
import psycopg2.extras
from psycopg2 import pool
from contextlib import contextmanager
import datetime
import random
import csv
import io
from config import DATABASE_URL, logger

# ================== CONNECTION POOL ==================
db_pool = None

def init_db():
    global db_pool
    try:
        db_pool = pool.SimpleConnectionPool(1, 20, DATABASE_URL)
        if db_pool:
            logger.info("✅ Connection pool created successfully")
            
        with get_conn() as conn:
            with conn.cursor() as cur:
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
                cur.execute("""
                    CREATE TABLE IF NOT EXISTS pvp_settings (
                        user_id BIGINT PRIMARY KEY,
                        mode TEXT DEFAULT 'Mix',
                        size INTEGER DEFAULT 6,
                        can_switch BOOLEAN DEFAULT TRUE
                    )
                """)
                
                cur.execute("SELECT column_name FROM information_schema.columns WHERE table_name='pvp_settings' AND column_name='size'")
                if not cur.fetchone():
                    cur.execute("ALTER TABLE pvp_settings ADD COLUMN size INTEGER DEFAULT 6")
                    logger.info("🔧 Migrated: Added 'size' column to pvp_settings")
                    
                cur.execute("SELECT column_name FROM information_schema.columns WHERE table_name='pvp_settings' AND column_name='can_switch'")
                if not cur.fetchone():
                    cur.execute("ALTER TABLE pvp_settings ADD COLUMN can_switch BOOLEAN DEFAULT TRUE")
                    logger.info("🔧 Migrated: Added 'can_switch' column to pvp_settings")

                cur.execute("""
                    CREATE TABLE IF NOT EXISTS battle_stats (
                        user_id BIGINT PRIMARY KEY,
                        wins INTEGER DEFAULT 0,
                        losses INTEGER DEFAULT 0
                    )
                """)
                
                # 🏅 Badge Tracking Table
                cur.execute("""
                    CREATE TABLE IF NOT EXISTS user_badges (
                        user_id BIGINT, 
                        badge TEXT, 
                        PRIMARY KEY (user_id, badge)
                    )
                """)
                
                # 🖼️ Gym Images Table
                cur.execute("""
                    CREATE TABLE IF NOT EXISTS gym_images (
                        leader_name TEXT PRIMARY KEY, 
                        file_id TEXT
                    )
                """)

                cur.execute("""
                    CREATE TABLE IF NOT EXISTS tasks (
                        user_id BIGINT,
                        task_type TEXT,
                        target TEXT,
                        progress INTEGER DEFAULT 0,
                        goal INTEGER,
                        reward_type TEXT,
                        reward_amount INTEGER,
                        completed BOOLEAN DEFAULT FALSE,
                        last_reset DATE,
                        PRIMARY KEY (user_id, task_type)
                    )
                """)
                conn.commit()

                try:
                    cur.execute("ALTER TABLE tasks DROP CONSTRAINT tasks_pkey")
                    cur.execute("ALTER TABLE tasks ADD PRIMARY KEY (user_id, task_type)")
                    conn.commit()
                except Exception:
                    conn.rollback() 
                
                cur.execute("CREATE INDEX IF NOT EXISTS idx_pokemons_user_id ON pokemons(user_id)")
                conn.commit()
    except Exception as e:
        logger.error(f"❌ Database initialization error: {e}")

@contextmanager
def get_conn():
    conn = db_pool.getconn()
    try: yield conn
    finally: db_pool.putconn(conn)

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
def add_caught_pokemon(user_id, name, region, source="Wild"):
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

def get_top_pvp_players(limit=5):
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT user_id, wins 
                FROM battle_stats 
                WHERE wins > 0 
                ORDER BY wins DESC 
                LIMIT %s
            """, (limit,))
            return cur.fetchall()

def get_user_pvp_rank(user_id):
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT rank FROM (
                    SELECT user_id, RANK() OVER (ORDER BY wins DESC) as rank 
                    FROM battle_stats 
                    WHERE wins > 0
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

# ================== 🏅 BADGE SYSTEM & GYM IMAGES ==================
def add_badge(user_id, badge_name):
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("INSERT INTO user_badges (user_id, badge) VALUES (%s, %s) ON CONFLICT DO NOTHING", (user_id, badge_name))
            conn.commit()

def get_user_badges(user_id):
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT badge FROM user_badges WHERE user_id = %s", (user_id,))
            return [row[0] for row in cur.fetchall()]

def set_gym_image(leader_name, file_id):
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("INSERT INTO gym_images (leader_name, file_id) VALUES (%s, %s) ON CONFLICT (leader_name) DO UPDATE SET file_id = EXCLUDED.file_id", (leader_name, file_id))
            conn.commit()

def get_gym_image(leader_name):
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT file_id FROM gym_images WHERE leader_name = %s", (leader_name,))
            row = cur.fetchone()
            return row[0] if row else None

def reset_all_badges():
    """Wipes all gym badges from the database (Admin only)"""
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM user_badges")
            conn.commit()

# ================== TASKS MODULE ==================
def get_daily_tasks(user_id):
    today = datetime.date.today()
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT task_type, target, progress, goal, reward_type, reward_amount, completed, last_reset FROM tasks WHERE user_id = %s", (user_id,))
            tasks = cur.fetchall()
            
            if not tasks or tasks[0][7] is None or tasks[0][7] < today:
                cur.execute("DELETE FROM tasks WHERE user_id = %s", (user_id,))
                
                targets = ["Pikachu", "Eevee", "Charmander", "Squirtle", "Bulbasaur", "Snorlax", "Gengar", "Lucario", "Ralts", "Bagon", "Magikarp", "Gible", "Beldum", "Dratini"]
                specific_target = random.choice(targets)
                
                new_tasks = [
                    (user_id, 'catch', 'Any', 0, 10, 'shiny', 1, False, today),
                    (user_id, 'pvp', 'Any', 0, 3, 'shiny', 1, False, today),
                    (user_id, 'catch_specific', specific_target, 0, 1, 'jackpot', 1, False, today)
                ]
                
                psycopg2.extras.execute_batch(cur, """
                    INSERT INTO tasks (user_id, task_type, target, progress, goal, reward_type, reward_amount, completed, last_reset)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                    ON CONFLICT (user_id, task_type) DO NOTHING
                """, new_tasks)
                conn.commit()
                
                cur.execute("SELECT task_type, target, progress, goal, reward_type, reward_amount, completed, last_reset FROM tasks WHERE user_id = %s", (user_id,))
                tasks = cur.fetchall()
                
            return [
                {"task_type": t[0], "target": t[1], "progress": t[2], "goal": t[3], "reward_type": t[4], "reward_amount": t[5], "completed": t[6]} 
                for t in tasks
            ]

def claim_task_reward(user_id, task_type):
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                UPDATE tasks SET completed = TRUE 
                WHERE user_id = %s AND task_type = %s AND progress >= goal AND completed = FALSE
                RETURNING reward_type, reward_amount
            """, (user_id, task_type))
            reward = cur.fetchone()
            conn.commit()
            return reward

def update_task_pvp(user_id):
    with get_conn() as conn:
        with conn.cursor() as cur:
            try:
                cur.execute("UPDATE tasks SET progress = progress + 1 WHERE user_id = %s AND task_type = 'pvp' AND completed = FALSE", (user_id,))
                conn.commit()
            except: conn.rollback()

def update_task_catch(user_id):
    with get_conn() as conn:
        with conn.cursor() as cur:
            try:
                cur.execute("UPDATE tasks SET progress = progress + 1 WHERE user_id = %s AND task_type = 'catch' AND completed = FALSE", (user_id,))
                conn.commit()
            except: conn.rollback()

def update_task_specific_catch(user_id, pokemon_name):
    with get_conn() as conn:
        with conn.cursor() as cur:
            try:
                cur.execute("UPDATE tasks SET progress = progress + 1 WHERE user_id = %s AND task_type = 'catch_specific' AND target ILIKE %s AND completed = FALSE", (user_id, pokemon_name))
                conn.commit()
            except: conn.rollback()

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

# ================== ADMIN TOOLS & EXPORT ==================
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
    with get_conn() as conn:
        with conn.cursor() as cur:
            psycopg2.extras.execute_batch(cur, """
                INSERT INTO users (user_id, tries_left, region, last_reset) 
                VALUES (%s, %s, %s, %s)
                ON CONFLICT (user_id) DO NOTHING
            """, users_data)
            
            psycopg2.extras.execute_batch(cur, """
                INSERT INTO pokemons (user_id, name, region) 
                VALUES (%s, %s, %s)
            """, pokemons_data)
            
            psycopg2.extras.execute_batch(cur, """
                INSERT INTO groups (group_id) 
                VALUES (%s)
                ON CONFLICT (group_id) DO NOTHING
            """, [(g[0],) for g in groups_data])
        conn.commit()

def export_table_csv(table_name):
    allowed_tables = ['users', 'pokemons', 'groups', 'battle_stats']
    if table_name not in allowed_tables: return None
        
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(f"SELECT * FROM {table_name}")
            colnames = [desc[0] for desc in cur.description]
            rows = cur.fetchall()

    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(colnames)
    writer.writerows(rows)
    return output.getvalue()

def get_debug_stats():
    """Calculates all backend data for the /debug panel"""
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT COUNT(*) FROM users")
            u_c = cur.fetchone()[0]
            
            cur.execute("SELECT COUNT(*) FROM pokemons")
            p_c = cur.fetchone()[0]
            
            cur.execute("SELECT COUNT(*) FROM groups")
            g_c = cur.fetchone()[0]
            
            cur.execute("SELECT SUM(wins + losses) FROM battle_stats")
            pvp_sum = cur.fetchone()[0]
            pvp_total = int(pvp_sum / 2) if pvp_sum else 0
            
            cur.execute("SELECT COUNT(DISTINCT region) FROM users")
            regions_active = cur.fetchone()[0] or 0
            
            try:
                cur.execute("SELECT pg_database_size(current_database())")
                db_bytes = cur.fetchone()[0]
                db_size_mb = round(db_bytes / (1024 * 1024), 2) if db_bytes else 0.0
            except:
                db_size_mb = 0.0
                
            return u_c, p_c, g_c, pvp_total, regions_active, db_size_mb
