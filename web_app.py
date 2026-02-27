import asyncio
import json
import os
from datetime import datetime, timezone, timedelta
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from telethon import TelegramClient
from telethon.sessions import StringSession
from telethon.errors import SessionPasswordNeededError

# --- LOCAL IMPORTS ---
from config import API_ID, API_HASH, HEXA_ID, logger, DEFAULT_LIST, BOT_TOKEN
from globals import user_clients, user_configs, otp_flows
from database import db, reset_stats
from utils import master_bot, send_hunt_with_retry
from userbot import run_userbot

# --- BACKGROUND TASKS ---
background_tasks = set()

async def monitor_hunting_status():
    logger.info("🛡️ Watchdog Monitor: STARTED")
    while True:
        await asyncio.sleep(60)
        now_utc = datetime.now(timezone.utc)
        for uid, config in list(user_configs.items()):
            if not config.get('hunting'): continue
            client = user_clients.get(uid)
            if not client: continue
            
            try:
                last_msgs = await client.get_messages(HEXA_ID, limit=1)
                if not last_msgs or (now_utc - last_msgs[0].date).total_seconds() > 600:
                    logger.warning(f"🛡️ Watchdog: Bot {uid} is stuck. Kickstarting...")
                    config['mode'] = 'SEARCHING'
                    await client.send_message(HEXA_ID, "/hunt")
            except Exception as e:
                pass

async def auto_daily_reset():
    ist_tz = timezone(timedelta(hours=5, minutes=30))
    while True:
        now_ist = datetime.now(ist_tz)
        target = now_ist.replace(hour=5, minute=0, second=0, microsecond=0)
        if now_ist >= target: target += timedelta(days=1)
        wait_seconds = (target - now_ist).total_seconds()
        
        await asyncio.sleep(wait_seconds + 5) 
        logger.info("♻️ PERFORMING DAILY STAT RESET (5 AM IST)...")
        for uid in list(user_configs.keys()):
            reset_stats(uid)

# --- SERVER LIFESPAN (Boot Sequence) ---
@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("🌐 Server Booting... Loading Database.")
    
    cursor = db.cursor()
    cursor.execute("""
        SELECT user_id, owner_id, session, poke_list, ball, total_matched, total_caught, 
               total_fled, total_tms, total_megastones, total_shinies, start_time, 
               notification_status, group_id, catch_log, smode, sball, shiny_caught, 
               shiny_fled, hunting_mode FROM users
    """)
    
    for row in cursor.fetchall():
        uid, sess = row[0], row[2]
        user_configs[uid] = {
            'owner_id': row[1],
            'list': json.loads(row[3]) if row[3] else list(DEFAULT_LIST),
            'ball': row[4],
            'stats': {
                'total_matched': row[5], 'total_caught': row[6], 'total_fled': row[7],
                'total_tms': row[8], 'total_megastones': row[9], 'total_shinies': row[10],
                'shiny_caught': row[17] or 0, 'shiny_fled': row[18] or 0, 'start_time': row[11]
            },
            'notification_status': row[12], 'group_id': row[13],
            'catch_log': json.loads(row[14]) if row[14] else {},
            'smode': bool(row[15]), 'sball': row[16],
            'hunting_mode': row[19] or 'LIST',
            'hunting': False, 'mode': 'SEARCHING', 'shiny_encounter': False
        }
        
        if sess:
            task = asyncio.create_task(run_userbot(uid, sess))
            background_tasks.add(task)
            task.add_done_callback(background_tasks.discard)

    # 2. Start Master Bot & Background Tasks (FIXED HERE)
    await master_bot.start(bot_token=BOT_TOKEN)
    
    t1 = asyncio.create_task(auto_daily_reset())
    t2 = asyncio.create_task(monitor_hunting_status())
    background_tasks.update([t1, t2])
    
    logger.info("✅ API and Bots Online.")
    yield 
    
    logger.info("🛑 Shutting down bots...")
    await master_bot.disconnect()
    for client in user_clients.values():
        await client.disconnect()


# --- INITIALIZE FASTAPI & CORS ---
app = FastAPI(lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["https://clinquant-sherbet-949751.netlify.app", "http://localhost:8000"], 
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

class LoginRequest(BaseModel):
    username: str
    passkey: str

class OTPRequest(BaseModel):
    phone: str
    owner_id: int

class VerifyRequest(BaseModel):
    phone: str
    code: str
    password: str = None 
    owner_id: int

@app.get("/")
async def root():
    return {"status": "HexaBot Backend API is running safely."}

@app.post("/api/auth")
async def login(data: LoginRequest):
    cursor = db.cursor()
    cursor.execute("SELECT owner_id, username FROM owners WHERE username=? AND passkey=?", (data.username.lower(), data.passkey))
    user = cursor.fetchone()
    if not user: raise HTTPException(status_code=401, detail="Invalid credentials")
    return {"owner_id": user[0], "username": user[1], "is_admin": user[1] == 'admin'}

@app.post("/api/telegram/send_code")
async def send_telegram_code(data: OTPRequest):
    try:
        client = TelegramClient(StringSession(), API_ID, API_HASH)
        await client.connect()
        sent = await client.send_code_request(data.phone)
        otp_flows[data.phone] = {'client': client, 'hash': sent.phone_code_hash}
        return {"status": "Code sent. Awaiting verification."}
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))

@app.post("/api/telegram/verify_code")
async def verify_telegram_code(data: VerifyRequest):
    flow = otp_flows.get(data.phone)
    if not flow: raise HTTPException(status_code=400, detail="Flow expired or invalid.")
    
    client = flow['client']
    try:
        if data.password:
            await client.sign_in(password=data.password)
        else:
            await client.sign_in(data.phone, data.code, phone_code_hash=flow['hash'])
            
        me = await client.get_me()
        user_id = me.id
        sess_str = client.session.save()
        now = datetime.now().isoformat()
        
        cursor = db.cursor()
        cursor.execute("""
            INSERT OR REPLACE INTO users 
            (user_id, owner_id, session, poke_list, start_time, hunting_mode) 
            VALUES (?, ?, ?, ?, ?, 'LIST')
        """, (user_id, data.owner_id, sess_str, json.dumps(DEFAULT_LIST), now))
        db.commit()
        
        user_configs[user_id] = {
            'owner_id': data.owner_id, 'list': list(DEFAULT_LIST), 'ball': None,
            'stats': {'total_matched': 0, 'total_caught': 0, 'total_fled': 0, 'total_tms': 0, 'total_megastones': 0, 'total_shinies': 0, 'shiny_caught': 0, 'shiny_fled': 0, 'start_time': now},
            'notification_status': 0, 'group_id': 0, 'catch_log': {},
            'smode': False, 'sball': None, 'hunting_mode': 'LIST', 'hunting': False, 'mode': 'SEARCHING', 'shiny_encounter': False
        }
        
        task = asyncio.create_task(run_userbot(user_id, sess_str))
        background_tasks.add(task)
        task.add_done_callback(background_tasks.discard)
        
        del otp_flows[data.phone]
        return {"status": "Success! Bot connected.", "bot_id": user_id}

    except SessionPasswordNeededError:
        return {"status": "2FA_REQUIRED", "message": "Please provide your Two-Step Verification Password."}
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))

@app.get("/api/bot/{bot_id}/status")
async def web_get_status(bot_id: int):
    if bot_id not in user_configs:
        raise HTTPException(status_code=404, detail="Bot not found")
    return {
        "hunting": user_configs[bot_id].get('hunting', False),
        "stats": user_configs[bot_id].get('stats', {})
    }

@app.post("/api/bot/{bot_id}/start")
async def web_start_hunt(bot_id: int):
    if bot_id not in user_configs or bot_id not in user_clients:
        raise HTTPException(status_code=404, detail="Bot offline or not found")
        
    user_configs[bot_id]['hunting'] = True
    user_configs[bot_id]['mode'] = 'SEARCHING'
    
    client = user_clients[bot_id]
    asyncio.create_task(send_hunt_with_retry(client, HEXA_ID, bot_id))
    return {"status": "Hunting Started"}

@app.post("/api/bot/{bot_id}/stop")
async def web_stop_hunt(bot_id: int):
    if bot_id in user_configs:
        user_configs[bot_id]['hunting'] = False
        return {"status": "Hunting Stopped"}
    raise HTTPException(status_code=404, detail="Bot not found")


# ==========================================
# STACKHOST / KOYEB BYPASS BLOCK
# ==========================================
if __name__ == "__main__":
    import uvicorn
    port = int(os.environ.get("PORT", 8000))
    uvicorn.run("web_app:app", host="0.0.0.0", port=port)
