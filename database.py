import sqlite3
import json
from datetime import datetime
from globals import user_configs

def ensure_column_exists(cursor, table, column, definition):
    cursor.execute(f"PRAGMA table_info({table})")
    columns = [row[1] for row in cursor.fetchall()]
    if column not in columns:
        cursor.execute(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")

def init_db():
    conn = sqlite3.connect("hexabot.db", check_same_thread=False)
    cursor = conn.cursor()

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS owners (
            owner_id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT UNIQUE NOT NULL,
            passkey TEXT NOT NULL
        )
    """)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS users (
            user_id INTEGER PRIMARY KEY,
            owner_id INTEGER,
            session TEXT,
            poke_list TEXT,
            ball TEXT,
            total_matched INTEGER DEFAULT 0,
            total_caught INTEGER DEFAULT 0,
            total_fled INTEGER DEFAULT 0,
            total_tms INTEGER DEFAULT 0,
            total_megastones INTEGER DEFAULT 0,
            total_shinies INTEGER DEFAULT 0,
            start_time TEXT,
            notification_status INTEGER DEFAULT 0,
            group_id INTEGER DEFAULT 0,
            catch_log TEXT DEFAULT '{}',
            smode INTEGER DEFAULT 0,
            sball TEXT,
            shiny_caught INTEGER DEFAULT 0,
            shiny_fled INTEGER DEFAULT 0,
            hunting_mode TEXT DEFAULT 'LIST',
            FOREIGN KEY(owner_id) REFERENCES owners(owner_id)
        )
    """)
    conn.commit()
    
    # Create the default Master Admin account if it doesn't exist
    cursor.execute("SELECT * FROM owners WHERE username = 'admin'")
    if not cursor.fetchone():
        cursor.execute("INSERT INTO owners (username, passkey) VALUES ('admin', 'admin123')")
        conn.commit()

    return conn

db = init_db()

def update_stat(user_id, column):
    cursor = db.cursor()
    cursor.execute(f"UPDATE users SET {column} = {column} + 1 WHERE user_id = ?", (user_id,))
    db.commit()
    
    if user_id in user_configs:
        val = user_configs[user_id]['stats'].get(column, 0)
        user_configs[user_id]['stats'][column] = int(val) + 1

def reset_stats(user_id):
    cursor = db.cursor()
    now = datetime.now().isoformat()
    cursor.execute("""UPDATE users SET 
                      total_matched=0, total_caught=0, total_fled=0, 
                      total_tms=0, total_megastones=0, total_shinies=0, 
                      shiny_caught=0, shiny_fled=0, start_time=? 
                      WHERE user_id = ?""", (now, user_id))
    db.commit()
    if user_id in user_configs:
        user_configs[user_id]['stats'].update({
            'total_matched': 0, 'total_caught': 0, 'total_fled': 0,
            'total_tms': 0, 'total_megastones': 0, 'total_shinies': 0,
            'shiny_caught': 0, 'shiny_fled': 0, 'start_time': now
        })
