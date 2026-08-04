# backup.py
# -*- coding: utf-8 -*-
"""
Auto-backup for the JSON data store (built for pyTelegramBotAPI / telebot).

Every 20 minutes: sends the current DATA_FILE to LOG_GROUP_ID, pins it,
then deletes the previously pinned backup message.

On startup: if no local DATA_FILE exists yet (fresh deploy / wiped disk),
restores it from the last known backup message in the log group.

Wire-up (in main.py), right before bot.infinity_polling():

    import backup
    backup.restore_database_on_startup(bot)   # BEFORE db.init_db()
    db.init_db()
    backup.start_auto_backup(bot)

The bot must be an admin in LOG_GROUP_ID with "pin messages" and
"delete messages" permissions.
"""
import os
import json
import time
import threading

from config import LOG_GROUP_ID, DATA_FILE, logger
from api_utils import escape_md

STATE_FILE = "backup_state.json"  # tracks the currently-pinned backup message_id
BACKUP_INTERVAL = 1200  # 20 minutes
FIRST_BACKUP_DELAY = 60  # send one shortly after startup, don't wait a full 20 min


def _load_state():
    if os.path.exists(STATE_FILE):
        try:
            with open(STATE_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception as e:
            logger.error(f"❌ Failed to read {STATE_FILE}: {e}")
    return {}


def _save_state(state):
    try:
        with open(STATE_FILE, "w", encoding="utf-8") as f:
            json.dump(state, f)
    except Exception as e:
        logger.error(f"❌ Failed to save {STATE_FILE}: {e}")


def backup_database(bot):
    """Sends + pins a fresh backup, then deletes the previous one."""
    state = _load_state()
    old_message_id = state.get("message_id")

    if not os.path.exists(DATA_FILE):
        logger.warning(f"⚠️ Backup skipped: {DATA_FILE} does not exist yet.")
        return

    try:
        with open(DATA_FILE, "rb") as f:
            # bot-wide default parse_mode is MarkdownV2, and passing parse_mode=None
            # falls back to that default rather than disabling it — so the caption
            # must actually be escaped, not just opted out.
            sent = bot.send_document(
                LOG_GROUP_ID,
                f,
                visible_file_name=DATA_FILE,
                caption=escape_md("🗄️ Auto-backup"),
            )

        bot.pin_chat_message(LOG_GROUP_ID, sent.message_id, disable_notification=True)

        # Only delete the old one after the new one is safely sent + pinned
        if old_message_id and old_message_id != sent.message_id:
            try:
                bot.delete_message(LOG_GROUP_ID, old_message_id)
            except Exception as e:
                logger.warning(f"⚠️ Could not delete previous backup message {old_message_id}: {e}")

        _save_state({"message_id": sent.message_id})
        logger.info(f"✅ Auto-backup sent & pinned (message_id={sent.message_id}).")
    except Exception as e:
        logger.error(f"❌ Auto-backup failed: {e}")


def restore_database_on_startup(bot):
    """Call once before db.init_db(). Restores DATA_FILE from the log group
    only if it's missing/empty locally — never clobbers live data."""
    if os.path.exists(DATA_FILE) and os.path.getsize(DATA_FILE) > 2:
        logger.info(f"ℹ️ Local {DATA_FILE} already present — skipping restore.")
        return

    state = _load_state()
    message_id = state.get("message_id")
    if not message_id:
        logger.info("ℹ️ No known backup message to restore from — starting fresh.")
        return

    forwarded = None
    try:
        # Bots can't fetch an arbitrary message by ID directly; forwarding it
        # to the same chat gives us a Message object (with the document) back.
        forwarded = bot.forward_message(LOG_GROUP_ID, LOG_GROUP_ID, message_id)
        if not forwarded.document:
            logger.error("❌ Restore failed: backup message had no document attached.")
            return

        file_info = bot.get_file(forwarded.document.file_id)
        downloaded = bot.download_file(file_info.file_path)
        with open(DATA_FILE, "wb") as f:
            f.write(downloaded)
        logger.info(f"✅ Restored {DATA_FILE} from log group backup (source message_id={message_id}).")
    except Exception as e:
        logger.error(f"❌ Restore-on-startup failed: {e}")
    finally:
        if forwarded is not None:
            try:
                bot.delete_message(LOG_GROUP_ID, forwarded.message_id)
            except Exception:
                pass


def _backup_loop(bot):
    time.sleep(FIRST_BACKUP_DELAY)
    while True:
        try:
            backup_database(bot)
        except Exception as e:
            logger.error(f"❌ Auto-backup loop error: {e}")
        time.sleep(BACKUP_INTERVAL)


def start_auto_backup(bot):
    """Starts the every-20-min backup loop in a background daemon thread."""
    threading.Thread(target=_backup_loop, args=(bot,), daemon=True).start()
    logger.info("✅ Auto-backup thread started (every 20 min).")
