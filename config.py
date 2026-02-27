import logging
import sys

# --- TELEGRAM CREDENTIALS ---
API_ID = 1747534              # Replace with your API ID
API_HASH = "5a2684512006853f2e48aca9652d83ea"     # Replace with your API Hash
BOT_TOKEN = "8225501991:AAEWMGWhCwt9FD16_FyM0GFr8Yzh1GUwQlE"   # Replace with Master Bot Token
OWNER_ID = 5716292610           # Your personal Telegram User ID (Master Admin)
HEXA_ID = "HeXamonbot"         # The target bot username/ID

# --- DEFAULT SETTINGS ---
DEFAULT_LIST = ["Mewtwo", "Rayquaza", "Arceus"]
LOG_FILE = "hexabot.log"

# --- LOGGING SETUP ---
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - [%(levelname)s] - %(message)s",
    handlers=[
        logging.FileHandler(LOG_FILE),
        logging.StreamHandler(sys.stdout)
    ]
)
logger = logging.getLogger("HexaBot")
