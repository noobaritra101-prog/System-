import json
import os
from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, filters, ContextTypes

# Use 'temp.json' as the local storage
SESSION_FILE = 'temp.json'

async def export_sessions(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if os.path.exists(SESSION_FILE):
        await update.message.reply_document(document=open(SESSION_FILE, 'rb'), caption="Backup of temp.json")
    else:
        await update.message.reply_text("No session file found.")

async def import_sessions(update: Update, context: ContextTypes.DEFAULT_TYPE):
    file = await update.message.document.get_file()
    await file.download_to_drive(SESSION_FILE)
    await update.message.reply_text("✅ temp.json has been updated and imported.")

if __name__ == '__main__':
    app = ApplicationBuilder().token("8225501991:AAEWMGWhCwt9FD16_FyM0GFr8Yzh1GUwQlE").build()
    
    app.add_handler(CommandHandler('export', export_sessions))
    app.add_handler(MessageHandler(filters.Document.FileExtension("json"), import_sessions))
    
    print("Bot is managing sessions...")
    app.run_polling()
    
