import logging
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ApplicationBuilder, CommandHandler, ContextTypes

# Use your actual token from @BotFather
BOT_TOKEN = "8225501991:AAEWMGWhCwt9FD16_FyM0GFr8Yzh1GUwQlE"
NETLIFY_URL = "inspiring-mousse-213572.netlify.app"

logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    keyboard = [[InlineKeyboardButton("🚀 Open Login Site", url=NETLIFY_URL)]]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await update.message.reply_text(
        "To continue, please authenticate on our website:",
        reply_markup=reply_markup
    )

if __name__ == '__main__':
    app = ApplicationBuilder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler('start', start))
    print("Bot is polling...")
    app.run_polling()
