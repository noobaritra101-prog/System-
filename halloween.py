"""
halloween.py — Halloween 🎃 event for Anime Nexus
=================================================
Imports ONLY from config (never from deck.py / handlers.py) so both of
those files can import this one without a circular import.

What it adds
  • Candies 🍬               — event currency. Earned from the daily quests (/haunt)
                               and /treat (candies) + /trick (shards).
  • Halloween edition cards  — any global card with "🎃" in its name, or
                               event == "halloween". Flex / inline captions get the
                               "This is a halloween (🎃) edition card !" line.
  • Login event              — ONE 7-night event, claimed in halloween.html by watching ads
                               (Adsgram): night 1 = 1 ad -> 1,000 shards ... night 7 = 3 ads ->
                               random Halloween card + 3,000 shards (see LOGIN_EVENT).
                               /hwlogin shows the calendar and tonight's ad progress.
  • /haunt                   — 5 daily quests + haunt-day progress (candy income for /hwstore).
  • /treat                   — COMMUNITY command (group chats), once per UTC day: a bag of mixed
                               candies 🍬🍭🍫🍪🍩🍰. 🍬 is the main currency; 🍭🍫🍪🍩🍰 convert to 🍬 or shards at /candies.
  • /trick                   — COMMUNITY command (group chats), once per UTC day: Nexus Shards 💠.
                               /treat and /trick have separate daily limits. Nothing is ever taken away.
                               (/trickortreat just explains the two commands.)
  • /hwstore, /candies       — spend candies. The Mystery Halloween Card is the last item.
  • /hwapp                   — opens halloween.html as a Telegram Mini App (HW_WEBAPP_URL).
  • Web API                  — get_router() returns a FastAPI router used by halloween.html:
                               POST /halloween/state | /halloween/login | /halloween/buy
                               mount once:  app.include_router(halloween.get_router(), prefix="/api")
  • Admin controls
        /halloween on [days]     start (default 9 days) — or resume if paused
        /halloween pause         freeze the event; remaining time is kept
        /halloween status        state, day number, card counts
        /halloween off           end the event now
        /hcard on <db-id>        mark an existing card as a Halloween card
        /hcard off <db-id>       remove the mark
        /hcard list              list all Halloween cards
  • Halloween cards are locked: they can't be sold in the Offline Store, gifted,
    traded or burned (see hw_locked()).
  • Marking: upload the card as usual (/add_card), then /hcard on <db-id>.

Hooks (small edits in deck.py / handlers.py):
  halloween_flex_line(global_card)        -> caption suffix
  maybe_halloween_drop(db, pool, rarity)  -> kept as a no-op: drops are NOT boosted any more
  award_seize_candies(db, user, card)     -> kept as a no-op (returns 0): /seize gives no candies
  hw_locked(db, card_id) / hw_lock_text(action) -> block gift/trade/burn/sell
  quest_progress(user_id, key, amount=1, db=None)  -> bump a daily quest
      keys: shards, versus_play, versus_win, guess, scramble, seize, mines,
            airdrop, roll, throw, burn, trade, store_buy
  importing this module registers the commands on main_router.
"""
import asyncio
import hashlib
import hmac
import json
import random
import time
from urllib.parse import parse_qsl
from datetime import datetime, timedelta, timezone
from html import escape as _esc

from aiogram import F
from aiogram.enums import ParseMode
from aiogram.filters import Command, CommandObject
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message, WebAppInfo

from config import (
    bot, main_router, ADMIN_IDS, ensure_user, load_db, save_db,
    format_rarity, is_ghost_banned, is_shadow_banned,
)

# ==========================================
# SETTINGS
# ==========================================
HW_EMOJI = "🎃"
HW_EVENT_KEY = "halloween"
DEFAULT_EVENT_DAYS = 9          # event length in UTC days (day 1 = the day it is started)

CANDY = "🍬"

# Candy types: (emoji, name, value in 🍬, drop weight).
#   🍬 Candy is the MAIN currency: the store only spends 🍬. A 🍬 piece is worth exactly 1 🍬 and goes straight to the balance.
#   🍭🍫🍪🍩🍰 are collectible items kept in the player's candy bag; they can be converted to 🍬 or to
#   Nexus Shards at /candies (1 🍬 of value = CONVERT_SHARDS_PER_CANDY shards, same rate as the store exchange).
# Average bag (3 pieces) ~ 26 🍬 per daily /treat once the items are converted (quests add ~300/day).
CANDY_TYPES = [
    ("🍬", "Candy",     1, 40),
    ("🍭", "Lollipop",  8, 25),
    ("🍫", "Chocolate", 12, 16),
    ("🍪", "Cookie",    15, 10),
    ("🍩", "Donut",     25, 6),
    ("🍰", "Cake",      50, 3),
]

# The ONE login event: 7 nights, each claimed in halloween.html after watching `ads` rewarded ads.
#   "shards": Nexus Shards   "card": random NON-Halloween card of that rarity
#   "hwcard": random Halloween card (Basic/Elite only, so the store's Divine stays special)
LOGIN_EVENT = (
    {"ads": 1, "shards": 1000},
    {"ads": 1, "card": "Basic 🃏"},
    {"ads": 2, "shards": 1500},
    {"ads": 2, "card": "Elite ⚓"},
    {"ads": 2, "shards": 2000},
    {"ads": 2, "card": "Divine ❄️"},
    {"ads": 3, "shards": 3000, "hwcard": ("Basic 🃏", "Elite ⚓")},
)
# Adsgram reward postback (create a rewarded block in the Adsgram dashboard and set its reward URL to):
#   https://<your-worker>/api/halloween/ads/reward?userid=[userId]&secret=<HW_AD_SECRET>
HW_AD_SECRET = ""                # any random string; use the same one in the URL above

# /treat and /trick — community (group chat) commands, each usable once per UTC day (separate limits)
TOT_COMMUNITY_ONLY = True        # False = also allow them in private chats
TREAT_BAG_SIZE = 3               # /treat: a bag holds this many candy pieces (each rolled separately)
TRICK_SHARD_RANGE = (100, 300)   # /trick: shards, rounded to steps of 50
CONVERT_SHARDS_PER_CANDY = 5     # converting a candy item to shards: value x this (100 🍬 = 500 shards)
COLLECTOR_BONUS = 100            # one-time bonus candies for collecting every candy type at least once

# Mini App (halloween.html)
HW_WEBAPP_URL = ""               # https URL where halloween.html is hosted (optional; /hwapp private-chat web_app button)
HW_MINIAPP_LINK = "https://t.me/Animenx_bot/Halloween"   # direct Mini App link (works in groups and private chats)
HW_REQUIRE_INITDATA = True       # verify Telegram initData on every web API call

# Pricing is tuned to the quest income: a full-clear day pays ~300 candies (5 quests ~210 + 100 bonus).
#   Divine 1,800 = 6 full days, Mystery Halloween 2,100 = 7 full days (max 1 per player).
# Store: key -> (label, price in candies, per-user limit, kind, value)
#   kind: "shards" | "card" (value = rarity or None) | "hwcard" (value = rarity tuple)
STORE_ITEMS = {
    "sh500":  ("💠 500 Nexus Shards (exchange)",      100,  5, "shards", 500),                 # candies -> shards
    "elite":  ("⚓ Random Elite Card",                 450,  3, "card",   "Elite ⚓"),
    "divine": ("❄️ Random Divine Card",               1800,  1, "card",   "Divine ❄️"),          # non-Halloween; ~6 full quest days
    "hwcard": ("🎁 Mystery Halloween Card (🎃)",      2100,  1, "hwcard", ("Basic 🃏", "Elite ⚓")),   # ~7 full quest days; max 1; always last
}
# Items that stay locked until the player has enough haunt days (see /haunt).
STORE_REQ_HAUNT_DAYS = {}

TREAT_LINES = [
    "A neighbour hands you a full-size candy bar!",
    "You found a bowl of candy left unattended...",
    "Someone dressed as a ghost gives you a bag of sweets!",
]
TRICK_LINES = [
    "A skeleton jumps out! You drop your candy... but find a few shards.",
    "The porch light flickers and the door never opens. A small consolation falls out.",
    "A bat swoops past and drops something shiny.",
]


# ==========================================
# HELPERS (importable from deck.py / handlers.py)
# ==========================================
def is_halloween_card(global_card: dict) -> bool:
    if not isinstance(global_card, dict):
        return False
    return global_card.get("event") == HW_EVENT_KEY or HW_EMOJI in str(global_card.get("name", ""))


def halloween_flex_line(global_card: dict) -> str:
    """Caption suffix for flex/inline captions ('' for normal cards)."""
    if is_halloween_card(global_card):
        return f"\n\n<b><i>This is a halloween ({HW_EMOJI}) edition card !</i></b>"
    return ""


def _state(db: dict) -> dict:
    return db.setdefault("settings", {}).setdefault(HW_EVENT_KEY, {})


def event_seconds_left(db: dict) -> int:
    st = _state(db)
    ends = st.get("ends_at", 0)
    if not st.get("active") or not ends:
        return 0
    left = int(ends - time.time())
    if left <= 0:
        st["active"] = False
        st.pop("ends_at", None)
        save_db()
        return 0
    return left


def event_active(db: dict) -> bool:
    return event_seconds_left(db) > 0


def hw_locked(db: dict, card_id) -> bool:
    """True if this card is a Halloween card (can't be sold offline, gifted, traded or burned)."""
    return is_halloween_card(db.get("global_cards", {}).get(card_id))


def hw_lock_text(action: str) -> str:
    return f"{HW_EMOJI} <b>Halloween cards cannot be {action}.</b>"


def event_day(db: dict):
    """(current day number, total days) of the running event, or None. Paused time doesn't count."""
    st = _state(db)
    sd, total = st.get("start_date"), st.get("days")
    if not (sd and total):
        return None
    try:
        d0 = datetime.strptime(sd, "%Y-%m-%d").replace(tzinfo=timezone.utc).timestamp()
    except ValueError:
        return None
    ref = st.get("paused_at") or time.time()
    n = int((ref - d0 - st.get("paused_total", 0)) // 86400) + 1
    return max(1, min(n, int(total))), int(total)


def _halloween_pool(db: dict, rarity: str | None = None) -> dict:
    out = {}
    for cid, c in db.get("global_cards", {}).items():
        if not is_halloween_card(c):
            continue
        if rarity and format_rarity(c.get("rarity", "")) != rarity:
            continue
        out[cid] = c
    return out


def maybe_halloween_drop(db: dict, pool: dict, target_rarity: str) -> dict:
    """Kept so the hook in trigger_drop keeps working. Drops are NOT boosted any more:
    the pool is returned unchanged."""
    return pool


def _fmt_left(sec: int) -> str:
    d, r = divmod(sec, 86400)
    h, r = divmod(r, 3600)
    m = r // 60
    return f"{d}d {h}h {m}m" if d else f"{h}h {m}m"


def _is_admin(message: Message) -> bool:
    return message.from_user.id in ADMIN_IDS


# ==========================================
# ADMIN COMMANDS
# ==========================================
def _hw_status_text(db: dict) -> str:
    st = _state(db)
    left = event_seconds_left(db)
    dn = event_day(db)
    if st.get("paused_at"):
        rem = max(0, int(st.get("ends_at", 0) - st["paused_at"]))
        state = f"⏸ PAUSED — {_fmt_left(rem)} left when resumed"
    elif left:
        state = f"▶️ ON — {_fmt_left(left)} left" + (f" (Day {dn[0]}/{dn[1]})" if dn else "")
    else:
        state = "⏹ OFF"
    pool = _halloween_pool(db)
    divines = sum(1 for c in pool.values() if format_rarity(c.get("rarity", "")) == HAUNT_REWARD_RARITY)
    return (f"{HW_EMOJI} <b>Halloween event:</b> {state}\n"
            f"<b>Halloween cards:</b> {len(pool)}  (Divine: {divines})")


def _miniapp_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(
        text=f"{HW_EMOJI} Open Halloween Mini App", url=HW_MINIAPP_LINK)]])


@main_router.message(Command("halloween"))
async def halloween_cmd(message: Message, command: CommandObject):
    """/halloween on [days] | pause | status | off"""
    if not _is_admin(message):
        return
    parts = (command.args or "").split()
    sub = parts[0].lower() if parts else "status"
    db = load_db()
    st = _state(db)
    now = time.time()

    if sub == "status":
        await message.reply(f"{_hw_status_text(db)}\n\n{HW_EMOJI} Mini app: {HW_MINIAPP_LINK}",
                            reply_markup=_miniapp_kb(), parse_mode=ParseMode.HTML)
        return

    if sub == "pause":
        if not st.get("active"):
            await message.reply(f"{HW_EMOJI} The event isn't running, nothing to pause.", parse_mode=ParseMode.HTML)
            return
        st["active"] = False
        st["paused_at"] = now
        save_db()
        await message.reply(
            f"⏸ <b>Event paused.</b> Quests, candies and the store are frozen and the remaining time is kept.\n"
            f"Use <code>/halloween on</code> to resume.", parse_mode=ParseMode.HTML)
        return

    if sub in ("off", "stop", "end"):
        st["active"] = False
        st.pop("paused_at", None)
        save_db()
        await message.reply("⏹ Halloween event ended.", parse_mode=ParseMode.HTML)
        return

    if sub == "on":
        if st.get("paused_at"):                                   # resume
            dur = now - st.pop("paused_at")
            st["ends_at"] = st.get("ends_at", now) + dur
            st["paused_total"] = st.get("paused_total", 0) + dur
            st["active"] = True
            save_db()
            await message.reply(f"▶️ <b>Event resumed.</b>\n{_hw_status_text(db)}", parse_mode=ParseMode.HTML)
            return
        if event_active(db):
            await message.reply(f"{HW_EMOJI} Already running.\n{_hw_status_text(db)}", parse_mode=ParseMode.HTML)
            return
        days = DEFAULT_EVENT_DAYS
        if len(parts) > 1 and parts[1].isdigit():
            days = max(1, min(60, int(parts[1])))
        day0 = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
        st["active"] = True
        st["event_id"] = int(now)                 # new id => everyone's haunt progress starts fresh
        st["start_date"] = day0.strftime("%Y-%m-%d")
        st["days"] = days
        st["paused_total"] = 0
        st["ends_at"] = (day0 + timedelta(days=days)).timestamp()   # end of the last UTC day
        st.pop("paused_at", None)
        save_db()
        last_day = (day0 + timedelta(days=days - 1)).strftime("%Y-%m-%d")
        await message.reply(
            f"🎃 <b>Halloween event started!</b> <b>{days}</b> days — today is Day 1, "
            f"last day is <b>{last_day}</b> (UTC).\n"
            f"Players: <code>/hwlogin</code> 7-night login event, <code>/haunt</code> daily quests, "
            f"<code>/treat</code> + <code>/trick</code> (group), <code>/hwstore</code>, <code>/hwapp</code>.\n"
            f"Clear your daily quests to earn candies: ~6 days for a Divine, ~7 days for a Halloween card.\n\n"
            f"{HW_EMOJI} Mini app: {HW_MINIAPP_LINK}",
            reply_markup=_miniapp_kb(), parse_mode=ParseMode.HTML,
        )
        return

    await message.reply("Usage: <code>/halloween on [days]</code> | <code>pause</code> | <code>status</code> | <code>off</code>",
                        parse_mode=ParseMode.HTML)


@main_router.message(Command("hcard"))
async def hcard_cmd(message: Message, command: CommandObject):
    """/hcard on <db-id> | off <db-id> | list — manage Halloween cards."""
    if not _is_admin(message):
        return
    parts = (command.args or "").split()
    sub = parts[0].lower() if parts else ""
    db = load_db()
    gc = db.get("global_cards", {})

    if sub == "list":
        cards = sorted(((cid, c) for cid, c in gc.items() if is_halloween_card(c)),
                       key=lambda kv: (str(kv[1].get("rarity", "")), str(kv[1].get("name", "")).lower()))
        if not cards:
            await message.reply(f"{HW_EMOJI} No Halloween cards yet.\nMark one with <code>/hcard on DB-XXXXXX</code>.",
                                parse_mode=ParseMode.HTML)
            return
        divines = sum(1 for _, c in cards if format_rarity(c.get("rarity", "")) == HAUNT_REWARD_RARITY)
        chunks, cur = [], f"<b>「 {HW_EMOJI} HALLOWEEN CARDS 」</b> — {len(cards)} total, {divines} Divine\n━━━━━━━━━━━━━━━━━\n"
        for cid, c in cards:
            line = f"<code>{_esc(str(cid))}</code> — {_esc(str(c.get('name', '?')))} [{format_rarity(c.get('rarity', ''))}]\n"
            if len(cur) + len(line) > 3800:
                chunks.append(cur)
                cur = ""
            cur += line
        chunks.append(cur)
        for chunk in chunks:
            await message.reply(chunk, parse_mode=ParseMode.HTML)
        return

    if sub in ("on", "off") and len(parts) >= 2:
        cid = parts[1].strip().upper()
        card = gc.get(cid)
        if not card:
            await message.reply(f"Card <code>{_esc(cid)}</code> not found.", parse_mode=ParseMode.HTML)
            return
        name = _esc(str(card.get("name", cid)))
        if sub == "on":
            if is_halloween_card(card):
                await message.reply(f"{HW_EMOJI} <b>{name}</b> is already a Halloween card.", parse_mode=ParseMode.HTML)
                return
            card["event"] = HW_EVENT_KEY
            save_db()
            owners = sum(1 for u in db.get("users", {}).values()
                         if (u.get("cards", {}).get(cid) or {}).get("amount", 0) > 0)
            note = (f"\n⚠️ <b>{owners}</b> player(s) already own it and can no longer sell, gift, trade or burn it."
                    if owners else "")
            await message.reply(
                f"{HW_EMOJI} <b>{name}</b> [{format_rarity(card.get('rarity', ''))}] is now a Halloween card.\n"
                f"<i>Locked: no Offline Store sale, gift, trade or burn.</i>{note}",
                parse_mode=ParseMode.HTML)
        else:
            if card.get("event") != HW_EVENT_KEY and HW_EMOJI not in str(card.get("name", "")):
                await message.reply(f"<b>{name}</b> isn't a Halloween card.", parse_mode=ParseMode.HTML)
                return
            card.pop("event", None)
            save_db()
            extra = (f"\n⚠️ The name still contains {HW_EMOJI}, so it still counts as Halloween — "
                     f"rename it with /edit_card too." if HW_EMOJI in str(card.get("name", "")) else "")
            await message.reply(f"✅ Halloween mark removed from <b>{name}</b>.{extra}", parse_mode=ParseMode.HTML)
        return

    await message.reply(
        "<b>Usage:</b>\n<code>/hcard on DB-XXXXXX</code> — mark as Halloween card\n"
        "<code>/hcard off DB-XXXXXX</code> — remove the mark\n<code>/hcard list</code> — all Halloween cards",
        parse_mode=ParseMode.HTML)


# ==========================================
# CANDY + CARD HELPERS
# ==========================================
def candies_of(user: dict) -> int:
    return int(user.get("hw_candies", 0) or 0)


def roll_candy_bag(user: dict) -> tuple:
    """Roll a treat bag. Returns (pieces, direct_candies, collector_bonus).
    🍬 pieces add straight to the balance; other types go into user['hw_candy_stock'] (convertible).
    user['hw_candy_box'] is the lifetime 'found' log used for the Candy Collector bonus."""
    weights = [t[3] for t in CANDY_TYPES]
    picks = random.choices(CANDY_TYPES, weights=weights, k=TREAT_BAG_SIZE)
    pieces = [(e, n, v) for e, n, v, _ in picks]
    box = user.setdefault("hw_candy_box", {})
    stock = user.setdefault("hw_candy_stock", {})
    direct = 0
    for e, _, v in pieces:
        box[e] = box.get(e, 0) + 1
        if e == CANDY:
            direct += v
        else:
            stock[e] = stock.get(e, 0) + 1
    bonus = 0
    if not user.get("hw_collector") and all(box.get(t[0], 0) > 0 for t in CANDY_TYPES):
        user["hw_collector"] = True
        bonus = COLLECTOR_BONUS
    add_candies(user, direct + bonus)
    return pieces, direct, bonus


def _candy_value(emoji: str) -> int:
    return next((t[2] for t in CANDY_TYPES if t[0] == emoji), 0)


def stock_value(user: dict) -> int:
    return sum(_candy_value(e) * n for e, n in (user.get("hw_candy_stock", {}) or {}).items())


def candy_box_text(user: dict) -> str:
    stock = user.get("hw_candy_stock", {}) or {}
    box = user.get("hw_candy_box", {}) or {}
    items = [f"{t[0]}×{stock.get(t[0], 0)} <i>({t[2]}{CANDY} each)</i>" for t in CANDY_TYPES[1:]]
    out = ["<b>Your candy bag</b> <i>(convert to 🍬 or 💠)</i>", "\n".join(items),
           f"Worth <b>{stock_value(user)}</b> {CANDY} or <b>{stock_value(user) * CONVERT_SHARDS_PER_CANDY}</b> 💠"]
    if user.get("hw_collector"):
        out.append("🏅 <b>Candy Collector</b> — every type found!")
    else:
        missing = [t[0] for t in CANDY_TYPES if not box.get(t[0], 0)]
        out.append(f"<i>Find every type for a +{COLLECTOR_BONUS} {CANDY} bonus. Missing: {' '.join(missing)}</i>")
    return "\n".join(out)


def candy_convert_kb(owner: str, user: dict) -> InlineKeyboardMarkup:
    stock = user.get("hw_candy_stock", {}) or {}
    rows = []
    for i, (e, _, v, _) in enumerate(CANDY_TYPES):
        n = stock.get(e, 0)
        if i == 0 or n <= 0:
            continue
        rows.append([
            InlineKeyboardButton(text=f"{e}×{n} → {n * v}{CANDY}", callback_data=f"hwcv_{owner}_{i}_c"),
            InlineKeyboardButton(text=f"{e}×{n} → {n * v * CONVERT_SHARDS_PER_CANDY}💠", callback_data=f"hwcv_{owner}_{i}_s"),
        ])
    if sum(stock.values()) > 0:
        val = stock_value(user)
        rows.append([
            InlineKeyboardButton(text=f"All → {val}{CANDY}", callback_data=f"hwcv_{owner}_a_c"),
            InlineKeyboardButton(text=f"All → {val * CONVERT_SHARDS_PER_CANDY}💠", callback_data=f"hwcv_{owner}_a_s"),
        ])
    rows.append([InlineKeyboardButton(text="🏪 Store", callback_data=f"hwback_{owner}")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def add_candies(user: dict, n: int) -> None:
    user["hw_candies"] = candies_of(user) + int(n)


def award_seize_candies(db: dict, user: dict, global_card: dict) -> int:
    """Kept so the hook in seize_cmd keeps working. /seize gives no candies any more
    (the 'seize' quest still counts through quest_progress)."""
    return 0


def _grant_card(user: dict, cid: str, card: dict) -> None:
    cards = user.setdefault("cards", {})
    entry = cards.setdefault(cid, {
        "name": card.get("name", "Card"),
        "rarity": card.get("rarity", "Basic 🃏"),
        "amount": 0,
    })
    entry["amount"] = entry.get("amount", 0) + 1


def _pick_card(db: dict, rarities, halloween: bool):
    """Random global card in one of `rarities`; Halloween-only or non-Halloween."""
    if isinstance(rarities, str):
        rarities = (rarities,)
    pool = {
        cid: c for cid, c in db.get("global_cards", {}).items()
        if format_rarity(c.get("rarity", "")) in rarities and is_halloween_card(c) == halloween
    }
    if not pool:
        return None, None
    cid = random.choice(list(pool))
    return cid, pool[cid]


# ==========================================
# PLAYER COMMANDS: /treat (candies) and /trick (shards) — each once per UTC day
# ==========================================
async def _tot_guard(message: Message, date_key: str, cmd: str, done_text: str):
    """Shared checks for /treat and /trick. Returns (db, user, user_id, today) or None (already replied)."""
    uid_int = message.from_user.id
    if is_ghost_banned(uid_int) or is_shadow_banned(uid_int):
        return None
    if TOT_COMMUNITY_ONLY and message.chat.type not in ("group", "supergroup"):
        await message.reply(f"{HW_EMOJI} <code>/{cmd}</code> is a <b>community command</b> — "
                            f"use it in the group chat.", parse_mode=ParseMode.HTML)
        return None
    user_id = str(uid_int)
    db = ensure_user(user_id, message.from_user.first_name, message.from_user.username)
    if not event_active(db):
        await message.reply(f"{HW_EMOJI} The Halloween event isn't running right now.", parse_mode=ParseMode.HTML)
        return None
    user = db["users"][user_id]
    today = _today()
    if user.get(date_key) == today:
        await message.reply(done_text, parse_mode=ParseMode.HTML)
        return None
    return db, user, user_id, today


@main_router.message(Command("treat"))
async def treat_cmd(message: Message):
    g = await _tot_guard(message, "hw_treat_date", "treat",
                         f"{HW_EMOJI} You've already collected your treat today. Come back tomorrow!")
    if not g:
        return
    db, user, user_id, today = g
    pieces, direct, bonus = roll_candy_bag(user)
    user["hw_treat_date"] = today
    save_db()

    lines = [f"<b>「 {HW_EMOJI} TREAT 」</b>", "━━━━━━━━━━━━━━━━━",
             f"<i>{random.choice(TREAT_LINES)}</i>\n",
             f"🎃 You got  {' '.join(e for e, _, _ in pieces)}"]
    if direct:
        lines.append(f"{CANDY} <b>+{direct} Candies</b> added to your balance")
    items = [e for e, _, _ in pieces if e != CANDY]
    if items:
        lines.append(f"🧺 <b>{' '.join(items)}</b> added to your candy bag — convert them at /candies")
    if bonus:
        lines.append(f"🏅 <b>Candy Collector!</b> You found every candy type: {CANDY} +{bonus} bonus!")
    lines.append(f"\n{CANDY} Balance: <b>{candies_of(user)}</b>  •  /candies  •  /hwstore")
    await message.reply("\n".join(lines), parse_mode=ParseMode.HTML)


@main_router.message(Command("trick"))
async def trick_cmd(message: Message):
    g = await _tot_guard(message, "hw_trick_date", "trick",
                         f"{HW_EMOJI} You've already played your trick today. Come back tomorrow!")
    if not g:
        return
    db, user, user_id, today = g
    lo, hi = TRICK_SHARD_RANGE
    shards = random.randint(lo // 50, hi // 50) * 50
    user["nexus_shards"] = user.get("nexus_shards", 0) + shards
    user["hw_trick_date"] = today
    save_db()

    lines = [f"<b>「 👻 TRICK 」</b>", "━━━━━━━━━━━━━━━━━",
             f"<i>{random.choice(TRICK_LINES)}</i>\n",
             f"👻 <b>Trick!</b> +{shards} Nexus Shards 💠 (nothing lost)",
             f"\n💠 Shards: <b>{user['nexus_shards']}</b>"]
    await message.reply("\n".join(lines), parse_mode=ParseMode.HTML)


@main_router.message(Command("trickortreat"))
async def trickortreat_info_cmd(message: Message):
    if is_ghost_banned(message.from_user.id) or is_shadow_banned(message.from_user.id):
        return
    await message.reply(
        f"<b>「 {HW_EMOJI} TRICK OR TREAT 」</b>\n━━━━━━━━━━━━━━━━━\n"
        f"🍬 <code>/treat</code> — a bag of candies 🍬🍭🍫🍪🍩🍰 (once a day)\n"
        f"👻 <code>/trick</code> — Nexus Shards 💠 (once a day)\n\n"
        f"<i>Separate daily limits — do both! Convert candies at /candies.</i>",
        parse_mode=ParseMode.HTML)


@main_router.message(Command("candies"))
async def candies_cmd(message: Message):
    uid_int = message.from_user.id
    if is_ghost_banned(uid_int) or is_shadow_banned(uid_int):
        return
    user_id = str(uid_int)
    db = ensure_user(user_id, message.from_user.first_name, message.from_user.username)
    u = db["users"][user_id]
    await message.reply(
        f"{CANDY} You have <b>{candies_of(u)}</b> Candies <i>(main store currency)</i>.  /hwstore\n\n"
        + candy_box_text(u),
        reply_markup=candy_convert_kb(user_id, u), parse_mode=ParseMode.HTML,
    )


# ==========================================
# CANDY STORE: /hwstore
# ==========================================
def _store_gate(db: dict, user: dict, key: str):
    """Reason text if this store item is still locked for the player, else None."""
    need = STORE_REQ_HAUNT_DAYS.get(key)
    if need:
        have = len(_haunt(db, user)["days"])
        if have < need:
            return f"Locked — finish {need} haunt days first ({have}/{need}). See /haunt."
    return None


def _store_text(db: dict, user: dict) -> str:
    bought = user.get("hw_bought", {})
    lines = [
        f"<b>「 {HW_EMOJI} CANDY STORE 」</b>",
        "━━━━━━━━━━━━━━━━━",
        f"{CANDY} Your Candies: <b>{candies_of(user)}</b>",
        f"⏳ Event ends in: <b>{_fmt_left(event_seconds_left(db))}</b>\n",
    ]
    for key, (label, price, limit, _k, _v) in STORE_ITEMS.items():
        lock = "  🔒" if _store_gate(db, user, key) else ""
        lines.append(f"• {label} — <b>{price}</b> {CANDY}  ({bought.get(key, 0)}/{limit}){lock}")
    lines.append("\n<i>Tap an item to buy it. Collect candies with /haunt quests and /treat (candies) + /trick (shards). Mystery Halloween card: max 1 per player.</i>")
    return "\n".join(lines)


def _store_kb(user_id: str) -> InlineKeyboardMarkup:
    rows, row = [], []
    for key, (label, price, *_rest) in STORE_ITEMS.items():
        row.append(InlineKeyboardButton(text=f"{label.split(' ', 1)[0]} {price}{CANDY}",
                                        callback_data=f"hwbuy_{user_id}_{key}"))
        if len(row) == 2:
            rows.append(row)
            row = []
    if row:
        rows.append(row)
    rows.append([InlineKeyboardButton(text="Close", callback_data=f"hwclose_{user_id}")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def _purchase(db: dict, user: dict, key: str):
    """Validate, charge and grant one store item (used by the bot and the web API).
    Returns (error_text | None, result dict)."""
    item = STORE_ITEMS.get(key)
    if not item:
        return "Item not found.", None
    if not event_active(db):
        return "The store is closed.", None
    label, price, limit, kind, value = item
    bought = user.setdefault("hw_bought", {})
    if bought.get(key, 0) >= limit:
        return "You've reached the limit for this item.", None
    gate = _store_gate(db, user, key)
    if gate:
        return gate, None
    if candies_of(user) < price:
        return f"Not enough candies — you need {price - candies_of(user)} more.", None

    # Work out the prize BEFORE charging, so an empty pool never eats candies.
    card_id, card = None, None
    if kind == "shards":
        prize, name, rarity = f"+{value} Nexus Shards 💠", f"{value} Nexus Shards", ""
    else:
        card_id, card = _pick_card(db, value, halloween=(kind == "hwcard"))
        if not card:
            return "That item is out of stock right now — you weren't charged.", None
        name, rarity = str(card.get("name", "Card")), format_rarity(card.get("rarity", ""))
        prize = f"{_esc(name)} [{rarity}]"

    user["hw_candies"] = candies_of(user) - price
    bought[key] = bought.get(key, 0) + 1
    if kind == "shards":
        user["nexus_shards"] = user.get("nexus_shards", 0) + value
    else:
        _grant_card(user, card_id, card)
    save_db()
    return None, {"label": label, "prize": prize, "card": card, "card_id": card_id,
                  "name": name, "rarity": rarity, "shards": value if kind == "shards" else 0}


@main_router.message(Command("hwstore"))
async def hwstore_cmd(message: Message):
    uid_int = message.from_user.id
    if is_ghost_banned(uid_int) or is_shadow_banned(uid_int):
        return
    user_id = str(uid_int)
    db = ensure_user(user_id, message.from_user.first_name, message.from_user.username)
    if not event_active(db):
        await message.reply(f"{HW_EMOJI} The Halloween store is closed right now.", parse_mode=ParseMode.HTML)
        return
    await message.reply(_store_text(db, db["users"][user_id]),
                        reply_markup=_store_kb(user_id), parse_mode=ParseMode.HTML)


@main_router.callback_query(F.data.startswith("hwcv_"))
async def hwcv_cb(cq: CallbackQuery):
    """Convert candy items from the bag into 🍬 or Nexus Shards."""
    _, owner, which, to = cq.data.split("_", 3)
    if str(cq.from_user.id) != owner:
        await cq.answer("This isn't your menu.", show_alert=True)
        return
    db = ensure_user(owner, cq.from_user.first_name, cq.from_user.username)
    if not event_active(db):
        await cq.answer("The event isn't running right now.", show_alert=True)
        return
    user = db["users"][owner]
    stock = user.setdefault("hw_candy_stock", {})
    if which == "a":
        targets = [t[0] for t in CANDY_TYPES[1:]]
    else:
        try:
            targets = [CANDY_TYPES[int(which)][0]]
        except (ValueError, IndexError):
            await cq.answer("Unknown candy.", show_alert=True)
            return
        if targets[0] == CANDY:
            await cq.answer("🍬 is the main currency — nothing to convert.", show_alert=True)
            return
    value = 0
    for e in targets:
        n = int(stock.get(e, 0) or 0)
        if n > 0:
            value += n * _candy_value(e)
            stock[e] = 0
    if value <= 0:
        await cq.answer("Nothing to convert.", show_alert=True)
        return
    if to == "c":
        add_candies(user, value)
        msg = f"Converted to +{value} 🍬"
    else:
        shards = value * CONVERT_SHARDS_PER_CANDY
        user["nexus_shards"] = user.get("nexus_shards", 0) + shards
        msg = f"Converted to +{shards} 💠 Shards"
    save_db()
    await cq.message.edit_text(
        f"{CANDY} You have <b>{candies_of(user)}</b> Candies <i>(main store currency)</i>.  /hwstore\n\n"
        + candy_box_text(user) + f"\n\n✅ <b>{msg}</b>",
        reply_markup=candy_convert_kb(owner, user), parse_mode=ParseMode.HTML)
    await cq.answer(msg)

@main_router.callback_query(F.data.startswith("hwclose_"))
async def hwclose_cb(cq: CallbackQuery):
    if str(cq.from_user.id) != cq.data.split("_", 1)[1]:
        await cq.answer("This isn't your menu.", show_alert=True)
        return
    try:
        await cq.message.delete()
    except Exception:
        pass
    await cq.answer()


@main_router.callback_query(F.data.startswith("hwbuy_"))
async def hwbuy_cb(cq: CallbackQuery):
    """Step 1: tapped an item -> confirmation screen."""
    _, owner, key = cq.data.split("_", 2)
    if str(cq.from_user.id) != owner:
        await cq.answer("This isn't your menu.", show_alert=True)
        return
    item = STORE_ITEMS.get(key)
    if not item:
        await cq.answer("Item not found.", show_alert=True)
        return
    db = ensure_user(owner, cq.from_user.first_name, cq.from_user.username)
    if not event_active(db):
        await cq.answer("The store is closed.", show_alert=True)
        return
    label, price, limit, *_ = item
    user = db["users"][owner]
    if user.get("hw_bought", {}).get(key, 0) >= limit:
        await cq.answer("You've reached the limit for this item.", show_alert=True)
        return
    gate = _store_gate(db, user, key)
    if gate:
        await cq.answer(gate, show_alert=True)
        return
    if candies_of(user) < price:
        await cq.answer(f"Not enough candies — you need {price - candies_of(user)} more.", show_alert=True)
        return
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=f"✅ Buy for {price}{CANDY}", callback_data=f"hwok_{owner}_{key}")],
        [InlineKeyboardButton(text="⬅️ Back", callback_data=f"hwback_{owner}")],
    ])
    await cq.message.edit_text(
        f"<b>Buy {label}</b> for <b>{price}</b> {CANDY}?\nYou have <b>{candies_of(user)}</b> {CANDY}.",
        reply_markup=kb, parse_mode=ParseMode.HTML)
    await cq.answer()


@main_router.callback_query(F.data.startswith("hwback_"))
async def hwback_cb(cq: CallbackQuery):
    owner = cq.data.split("_", 1)[1]
    if str(cq.from_user.id) != owner:
        await cq.answer("This isn't your menu.", show_alert=True)
        return
    db = ensure_user(owner, cq.from_user.first_name, cq.from_user.username)
    await cq.message.edit_text(_store_text(db, db["users"][owner]),
                               reply_markup=_store_kb(owner), parse_mode=ParseMode.HTML)
    await cq.answer()


@main_router.callback_query(F.data.startswith("hwok_"))
async def hwok_cb(cq: CallbackQuery):
    """Step 2: confirmed -> re-validate, charge, grant."""
    _, owner, key = cq.data.split("_", 2)
    if str(cq.from_user.id) != owner:
        await cq.answer("This isn't your menu.", show_alert=True)
        return
    item = STORE_ITEMS.get(key)
    if not item:
        await cq.answer("Item not found.", show_alert=True)
        return
    db = ensure_user(owner, cq.from_user.first_name, cq.from_user.username)
    if not event_active(db):
        await cq.answer("The store is closed.", show_alert=True)
        return

    user = db["users"][owner]
    err, res = _purchase(db, user, key)
    if err:
        await cq.answer(err, show_alert=True)
        return
    label, prize_text, card = res["label"], res["prize"], res["card"]

    text = (f"<b>「 {HW_EMOJI} PURCHASE COMPLETE 」</b>\n━━━━━━━━━━━━━━━━━\n"
            f"🛍 {label}\n🎁 You got: <b>{prize_text}</b>\n"
            f"{CANDY} Remaining: <b>{candies_of(user)}</b>")
    kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="⬅️ Back to store", callback_data=f"hwback_{owner}")]])
    if card and card.get("file_id"):
        try:
            await cq.message.reply_photo(photo=card["file_id"], caption=text, parse_mode=ParseMode.HTML)
            await cq.message.edit_text(_store_text(db, user), reply_markup=_store_kb(owner), parse_mode=ParseMode.HTML)
            await cq.answer("Purchased!")
            return
        except Exception:
            pass
    await cq.message.edit_text(text, reply_markup=kb, parse_mode=ParseMode.HTML)
    await cq.answer("Purchased!")


# ==========================================
# DAILY QUESTS
# ==========================================
DAILY_QUEST_COUNT = 5            # quests handed out per player per UTC day
ALL_DONE_BONUS = 100             # extra candies for finishing every quest of the day
QUEST_NOTIFY = True              # DM the player when a quest completes (best effort)

# Haunt = the event-long goal. A "haunt day" counts when the player finishes at least
# HAUNT_DAY_MIN_QUESTS of that day's quests; HAUNT_DAYS_REQUIRED such days unlock the
# Halloween Divine in /hwstore (STORE_REQ_HAUNT_DAYS).
HAUNT_DAYS_REQUIRED = 7
HAUNT_DAY_MIN_QUESTS = DAILY_QUEST_COUNT      # default: all of the day's quests
HAUNT_REWARD_RARITY = "Divine ❄️"             # the Halloween Divine sold in /hwstore

# key -> (text, (min, max) target, step, candy reward)
QUESTS = {
    "shards":      ("Earn {t} shards",                                 (1000, 2000), 100, 60),
    "versus_play": ("Play {t} versus matches",                         (4, 6),         1, 40),
    "guess":       ("Correctly guess {t} cards",                       (10, 20),       1, 50),
    "scramble":    ("Play {t} Scramble games",                         (10, 20),       1, 50),
    "seize":       ("Seize {t} cards",                                 (2, 4),         1, 30),
    "mines":       ("Play {t} Mines games",                            (2, 5),         1, 30),
    "airdrop":     ("Claim your airdrop",                              (1, 1),         1, 40),
    "roll":        ("Use /roll {t} times",                             (11, 15),       1, 40),
    "throw":       ("Use /throw {t} times",                            (12, 18),       1, 40),
    "burn":        ("Burn {t} cards",                                  (2, 5),         1, 30),
    "trade":       ("Complete {t} trades",                             (2, 4),         1, 50),
    "versus_win":  ("Win {t} versus matches",                          (2, 4),         1, 50),
    "store_buy":   ("Buy {t} cards from the online or offline store",  (1, 3),         1, 40),
}


def _today() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


def _roll_quests(user: dict) -> dict:
    """Return today's quest set for this user, creating it on first use."""
    q = user.get("hw_quests")
    if isinstance(q, dict) and q.get("date") == _today():
        return q
    items = []
    for key in random.sample(list(QUESTS), min(DAILY_QUEST_COUNT, len(QUESTS))):
        _text, (lo, hi), step, reward = QUESTS[key]
        target = random.randint(lo // step, hi // step) * step
        items.append({"k": key, "t": target, "p": 0, "r": reward, "done": False})
    q = {"date": _today(), "items": items, "bonus": False}
    user["hw_quests"] = q
    return q


async def _send_quiet(uid: str, text: str) -> None:
    try:
        await bot.send_message(chat_id=int(uid), text=text, parse_mode=ParseMode.HTML)
    except Exception:
        pass


def _notify(uid: str, text: str) -> None:
    if not QUEST_NOTIFY:
        return
    try:
        asyncio.get_running_loop().create_task(_send_quiet(uid, text))
    except RuntimeError:
        pass   # not inside the event loop


def _haunt(db: dict, user: dict) -> dict:
    """Per-event haunt record: {'event': id, 'days': [dates]}."""
    eid = _state(db).get("event_id", 0)
    h = user.get("hw_haunt")
    if not isinstance(h, dict) or h.get("event") != eid:
        h = {"event": eid, "days": []}
        user["hw_haunt"] = h
    return h


def quest_progress(user_id, key: str, amount: int = 1, db: dict | None = None) -> None:
    """Add `amount` to today's quest `key` for this user (no-op if the event is off,
    the user doesn't have that quest today, or it's already done). Safe to call anywhere."""
    try:
        db = db or load_db()
        if not event_active(db) or amount <= 0:
            return
        uid = str(user_id)
        user = db.get("users", {}).get(uid)
        if not user:
            return
        q = _roll_quests(user)
        changed, notes = False, []
        for it in q["items"]:
            if it["k"] != key or it["done"]:
                continue
            it["p"] = min(it["t"], it["p"] + int(amount))
            changed = True
            if it["p"] >= it["t"]:
                it["done"] = True
                add_candies(user, it["r"])
                text = QUESTS[key][0].format(t=it["t"])
                notes.append(f"✅ <b>Quest complete:</b> {text}\n{CANDY} +{it['r']} Candies")
        if changed and sum(1 for i in q["items"] if i["done"]) >= HAUNT_DAY_MIN_QUESTS:
            h = _haunt(db, user)
            if q["date"] not in h["days"]:
                h["days"].append(q["date"])
                notes.append(f"🕯 <b>Haunt day complete!</b> ({len(h['days'])}/{HAUNT_DAYS_REQUIRED} days)")
        if q["items"] and not q["bonus"] and all(i["done"] for i in q["items"]):
            q["bonus"] = True
            add_candies(user, ALL_DONE_BONUS)
            notes.append(f"🎉 <b>All daily quests done!</b> {CANDY} +{ALL_DONE_BONUS} bonus Candies")
        if changed:
            save_db()
        if notes:
            _notify(uid, f"<b>「 {HW_EMOJI} HALLOWEEN QUEST 」</b>\n" + "\n".join(notes) +
                    f"\n\n{CANDY} Balance: <b>{candies_of(user)}</b>")
    except Exception as e:   # a quest bug must never break /roll, /seize, etc.
        print(f"[halloween] quest_progress error: {e}")


def _bar(p: int, t: int, width: int = 8) -> str:
    filled = 0 if t <= 0 else int(width * min(p, t) / t)
    return "▰" * filled + "▱" * (width - filled)


@main_router.message(Command("haunt"))
async def haunt_cmd(message: Message):
    uid_int = message.from_user.id
    if is_ghost_banned(uid_int) or is_shadow_banned(uid_int):
        return
    user_id = str(uid_int)
    db = ensure_user(user_id, message.from_user.first_name, message.from_user.username)
    if not event_active(db):
        await message.reply(f"{HW_EMOJI} The Halloween event isn't running right now.", parse_mode=ParseMode.HTML)
        return

    user = db["users"][user_id]
    q = _roll_quests(user)
    h = _haunt(db, user)
    save_db()

    dn = event_day(db)
    head = f"<b>「 {HW_EMOJI} HAUNT 」</b>" + (f"  —  Day <b>{dn[0]}/{dn[1]}</b>" if dn else "")
    lines = [head, "━━━━━━━━━━━━━━━━━"]
    for it in q["items"]:
        text = QUESTS[it["k"]][0].format(t=it["t"])
        mark = "✅" if it["done"] else "▫️"
        lines.append(f"{mark} <b>{text}</b>\n    {_bar(it['p'], it['t'])} {it['p']}/{it['t']}  •  {CANDY} {it['r']}")
    done = sum(1 for i in q["items"] if i["done"])
    lines.append(f"\n<b>{done}/{len(q['items'])}</b> done today  •  all-done bonus: {CANDY} {ALL_DONE_BONUS}"
                 + (" ✅" if q["bonus"] else ""))

    nd = len(h["days"])
    lines.append("\n<b>🕯 Haunt days</b>")
    lines.append(f"{_bar(min(nd, HAUNT_DAYS_REQUIRED), HAUNT_DAYS_REQUIRED, 10)} {nd}/{HAUNT_DAYS_REQUIRED}"
                 + ("  (today ✅)" if q["date"] in h["days"] else ""))
    lines.append(f"<i>Finish {HAUNT_DAY_MIN_QUESTS} quest(s) in a day to haunt it. "
                 f"Clear quests daily to save up candies for the store!</i>")

    lines.append(f"\n{CANDY} Balance: <b>{candies_of(user)}</b>  •  /hwstore")
    lines.append("<i>Quests reset every day at 00:00 UTC.</i>")
    await message.reply("\n".join(lines), parse_mode=ParseMode.HTML)


# ==========================================
# THE 7-NIGHT LOGIN EVENT (ads -> shards / cards): /hwlogin shows it, halloween.html claims it
# ==========================================
def _gap(a: str, b: str) -> int:
    f = "%Y-%m-%d"
    return (datetime.strptime(b, f) - datetime.strptime(a, f)).days


def _login(db: dict, user: dict) -> dict:
    """Per-event login record: {'event': id, 'streak': nights claimed in a row, 'last': date}."""
    eid = _state(db).get("event_id", 0)
    h = user.get("hw_login")
    if not isinstance(h, dict) or h.get("event") != eid:
        h = {"event": eid, "streak": 0, "last": None}
        user["hw_login"] = h
    return h


def _login_view(db: dict, user: dict):
    """(nights claimed in the current run, can claim tonight?, streak just broke?)"""
    h = _login(db, user)
    today, last, streak = _today(), h.get("last"), int(h.get("streak", 0))
    broken = False
    if last and last != today:
        if streak >= len(LOGIN_EVENT):
            streak = 0                          # finished all 7 nights: a new run starts
        elif streak > 0 and _gap(last, today) > 1:
            streak, broken = 0, True            # missed a night: back to night 1
    return streak, last != today, broken


def _ads_today(user: dict) -> int:
    a = user.get("hw_login_ads")
    return int(a.get("n", 0)) if isinstance(a, dict) and a.get("date") == _today() else 0


def record_ad(db: dict, user: dict) -> int:
    """Count one confirmed rewarded ad toward tonight's login reward. Called from the Adsgram
    reward postback only (never trust the client). Returns the ads counted tonight."""
    if not event_active(db):
        return 0
    streak, can, _broken = _login_view(db, user)
    if not can:
        return _ads_today(user)
    n = min(LOGIN_EVENT[streak]["ads"], _ads_today(user) + 1)
    user["hw_login_ads"] = {"date": _today(), "n": n}
    save_db()
    return n


def _reward_text(day: dict) -> str:
    parts = []
    if day.get("shards"):
        parts.append(f"{day['shards']:,} Nexus Shards 💠")
    if day.get("card"):
        parts.append(f"1 random {day['card']} card")
    if day.get("hwcard"):
        parts.append(f"1 random Halloween {HW_EMOJI} card")
    return " + ".join(parts)


def claim_login(db: dict, user: dict):
    """Claim tonight's reward once enough ads were counted.
    Returns (ok, {'day','shards','cards':[{'name','rarity'}]} | {'error'})."""
    if not event_active(db):
        return False, {"error": "The Halloween event isn't running right now."}
    streak, can, _broken = _login_view(db, user)
    if not can:
        return False, {"error": "Already claimed tonight — come back after 00:00 UTC."}
    day = LOGIN_EVENT[streak]
    seen = _ads_today(user)
    if seen < day["ads"]:
        return False, {"error": f"Watch {day['ads']} ad(s) first ({seen}/{day['ads']})."}

    # Pick the cards BEFORE granting anything, so an empty pool never costs the player.
    picks = []
    if day.get("card"):
        picks.append(_pick_card(db, day["card"], halloween=False))
    if day.get("hwcard"):
        picks.append(_pick_card(db, day["hwcard"], halloween=True))
    if any(c is None for _cid, c in picks):
        return False, {"error": "That reward is out of stock right now. Try again later — your ads are kept."}

    shards = int(day.get("shards", 0))
    if shards:
        user["nexus_shards"] = user.get("nexus_shards", 0) + shards
    cards = []
    for cid, c in picks:
        _grant_card(user, cid, c)
        cards.append({"name": str(c.get("name", "Card")), "rarity": format_rarity(c.get("rarity", ""))})
    h = _login(db, user)
    h["streak"], h["last"] = streak + 1, _today()
    user["hw_login_ads"] = {"date": _today(), "n": 0}
    save_db()
    return True, {"day": streak + 1, "shards": shards, "cards": cards}


def _login_text(db: dict, user: dict) -> str:
    streak, can, broken = _login_view(db, user)
    rows = []
    for i, d in enumerate(LOGIN_EVENT):
        mark = "✅" if i < streak else ("🎁" if i == streak and can else "▫️")
        rows.append(f"{mark} Night {i + 1} — {d['ads']} ad{'s' if d['ads'] > 1 else ''}: {_reward_text(d)}")
    if not can:
        head = "✅ <i>Tonight's reward is claimed. Come back after 00:00 UTC.</i>"
    else:
        need = LOGIN_EVENT[streak]["ads"]
        head = (f"📺 <b>Tonight:</b> watch {need} ad{'s' if need > 1 else ''} "
                f"({min(_ads_today(user), need)}/{need}), then claim — open /hwapp.")
    note = "\n⚠️ <i>You missed a night, so the event restarted at night 1.</i>" if broken else ""
    return f"<b>「 {HW_EMOJI} 7-NIGHT LOGIN EVENT 」</b>\n━━━━━━━━━━━━━━━━━\n{head}\n\n" + "\n".join(rows) + note


@main_router.message(Command("hwlogin"))
async def hwlogin_cmd(message: Message):
    uid_int = message.from_user.id
    if is_ghost_banned(uid_int) or is_shadow_banned(uid_int):
        return
    user_id = str(uid_int)
    db = ensure_user(user_id, message.from_user.first_name, message.from_user.username)
    if not event_active(db):
        await message.reply(f"{HW_EMOJI} The Halloween event isn't running right now.", parse_mode=ParseMode.HTML)
        return
    await message.reply(_login_text(db, db["users"][user_id]), parse_mode=ParseMode.HTML)


@main_router.message(Command("hwapp"))
async def hwapp_cmd(message: Message):
    uid_int = message.from_user.id
    if is_ghost_banned(uid_int) or is_shadow_banned(uid_int):
        return
    await message.reply(f"{HW_EMOJI} <b>Anime Nexus Halloween Event</b>\nLogin calendar, quests and the candy store.",
                        reply_markup=_miniapp_kb(), parse_mode=ParseMode.HTML)


# ==========================================
# WEB API for halloween.html (FastAPI router, same style as /api/deck and /api/store)
# ==========================================
def _verify_init_data(init_data: str):
    """Validate Telegram WebApp initData. Returns the Telegram user dict, or None."""
    try:
        pairs = dict(parse_qsl(init_data, keep_blank_values=True))
        got = pairs.pop("hash", "")
        check = "\n".join(f"{k}={v}" for k, v in sorted(pairs.items()))
        secret = hmac.new(b"WebAppData", bot.token.encode(), hashlib.sha256).digest()
        calc = hmac.new(secret, check.encode(), hashlib.sha256).hexdigest()
        if not hmac.compare_digest(calc, got) or time.time() - int(pairs.get("auth_date", 0)) > 86400:
            return None
        return json.loads(pairs["user"])
    except Exception:
        return None


def _web_view(db: dict, user: dict) -> dict:
    """Everything halloween.html needs to draw itself. The server is the source of truth,
    including store prices and limits."""
    q, h = _roll_quests(user), _haunt(db, user)
    streak, can, broken = _login_view(db, user)
    dn, bought, active = event_day(db), user.get("hw_bought", {}), event_active(db)
    return {
        "event": {"active": active, "day": dn[0] if dn else 0, "total": dn[1] if dn else 0,
                  "seconds_left": event_seconds_left(db)},
        "candies": candies_of(user),
        "shards": int(user.get("nexus_shards", 0) or 0),
        "login": {"streak": streak, "can_claim": bool(can and active), "broken": broken,
                  "ads_needed": LOGIN_EVENT[min(streak, len(LOGIN_EVENT) - 1)]["ads"],
                  "ads_watched": min(_ads_today(user), LOGIN_EVENT[min(streak, len(LOGIN_EVENT) - 1)]["ads"]) if can else 0},
        "quests": {"items": [{"k": i["k"], "text": QUESTS[i["k"]][0].format(t=i["t"]), "t": i["t"],
                              "p": i["p"], "r": i["r"], "done": i["done"]} for i in q["items"]],
                   "bonus": q["bonus"], "bonus_amount": ALL_DONE_BONUS},
        "haunt": {"days": len(h["days"]), "required": HAUNT_DAYS_REQUIRED, "today": q["date"] in h["days"]},
        "store": [{"key": k, "price": v[1], "limit": v[2], "bought": bought.get(k, 0),
                   "locked": _store_gate(db, user, k)} for k, v in STORE_ITEMS.items()],
    }


def get_router():
    """FastAPI router for halloween.html. Mount it once at startup:
           app.include_router(halloween.get_router(), prefix="/api")
       -> POST /api/halloween/state | /api/halloween/login | /api/halloween/buy
       Body: {"user_id": 123, "init_data": "<Telegram.WebApp.initData>", "key": "<store key (buy only)>"}
       Errors are HTTPException(detail=...), like the other mini-app endpoints."""
    from fastapi import APIRouter, HTTPException
    from pydantic import BaseModel

    class Req(BaseModel):
        user_id: int
        init_data: str = ""
        key: str = ""

    router = APIRouter(prefix="/halloween", tags=["halloween"])

    def ctx(req: Req):
        if HW_REQUIRE_INITDATA:
            tg = _verify_init_data(req.init_data)
            if not tg or int(tg.get("id", 0)) != req.user_id:
                raise HTTPException(401, "Open this page from the bot.")
        if is_ghost_banned(req.user_id) or is_shadow_banned(req.user_id):
            raise HTTPException(403, "Not available.")
        db = load_db()
        user = db.get("users", {}).get(str(req.user_id))
        if not user:
            raise HTTPException(404, "Start the bot first, then open this page again.")
        return db, user

    @router.get("/ads/reward")
    async def ad_reward(userid: int = 0, secret: str = ""):
        """Adsgram reward postback: counts one confirmed ad toward tonight's login reward."""
        if HW_AD_SECRET and not hmac.compare_digest(secret, HW_AD_SECRET):
            raise HTTPException(403, "Bad secret.")
        db = load_db()
        user = db.get("users", {}).get(str(userid))
        if not user:
            raise HTTPException(404, "Unknown user.")
        return {"ok": True, "watched": record_ad(db, user)}

    @router.post("/state")
    async def state(req: Req):
        db, user = ctx(req)
        view = _web_view(db, user)
        save_db()                      # persists today's freshly rolled quests
        return {"ok": True, "view": view}

    @router.post("/login")
    async def login(req: Req):
        db, user = ctx(req)
        ok, info = claim_login(db, user)
        if not ok:
            raise HTTPException(400, info["error"])
        return {"ok": True, **info, "view": _web_view(db, user)}

    @router.post("/buy")
    async def buy(req: Req):
        db, user = ctx(req)
        err, res = _purchase(db, user, req.key)
        if err:
            raise HTTPException(400, err)
        return {"ok": True, "name": res["name"], "rarity": res["rarity"], "shards": res["shards"],
                "view": _web_view(db, user)}

    return router
