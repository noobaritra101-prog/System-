import os
import json
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, filters, ContextTypes

# --- HARDCODED DATA ---
TOKEN = "8225501991:AAEWMGWhCwt9FD16_FyM0GFr8Yzh1GUwQlE"
NETLIFY_URL = "https://inspiring-mousse-213572.netlify.app/"
SESSION_FILE = 'temp.json'

# 1. Start Command (The Website Button)
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    keyboard = [
        [InlineKeyboardButton("🌐 Open Login Website", url=NETLIFY_URL)]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await update.message.reply_text(
        f"Welcome {update.effective_user.first_name}!\n\n"
        "Please click the button below to log in securely using your phone number and OTP.",
        reply_markup=reply_markup
    )

# 2. Export Command
async def export_json(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if os.path.exists(SESSION_FILE):
        await update.message.reply_document(document=open(SESSION_FILE, 'rb'), caption="Backup of temp.json")
    else:
        await update.message.reply_text("temp.json not found yet. Try logging in on the website first!")

# 3. Import Message Handler
async def import_json(update: Update, context: ContextTypes.DEFAULT_TYPE):
    file = await update.message.document.get_file()
    await file.download_to_drive(SESSION_FILE)
    await update.message.reply_text("✅ temp.json imported successfully and is now active.")

if __name__ == '__main__':
    app = ApplicationBuilder().token(TOKEN).build()
    
    # Add the handlers
    app.add_handler(CommandHandler('start', start))
    app.add_handler(CommandHandler('export', export_json))
    app.add_handler(MessageHandler(filters.Document.FileExtension("json"), import_json))
    
    print("Bot is running...")
    print(f"Website linked: {NETLIFY_URL}")
    app.run_polling()
