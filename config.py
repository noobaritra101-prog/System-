# config.py
import logging

# ================== CONFIG ==================
BOT_TOKEN = "8311035050:AAEfGHJEjqi59jifzbdP1rxJQ1LoLwQN3Nw"  # Replace with your valid bot token
OWNER_ID = 5716292610  # Your Telegram user ID
LOG_GROUP_ID = -1002790195961  # Replace with your log group's chat ID or keep as None
FLEE_TIMEOUT = 120  # Seconds (2 minutes) before Pokémon flees
DB_FILE = "pokemon.db"

REGIONS = ["Kanto", "Johto", "Hoenn", "Sinnoh", "Unova", "Kalos", "Alola", "Galar"]

# Mega Pokémon list (ID, name, base_id for sprites)
MEGA_POKEMON = [
    (3, "Venusaur-Mega", 3), (6, "Charizard-Mega-X", 6), (6, "Charizard-Mega-Y", 6), (9, "Blastoise-Mega", 9),
    (65, "Alakazam-Mega", 65), (94, "Gengar-Mega", 94), (115, "Kangaskhan-Mega", 115), (127, "Pinsir-Mega", 127),
    (130, "Gyarados-Mega", 130), (142, "Aerodactyl-Mega", 142), (150, "Mewtwo-Mega-X", 150), (150, "Mewtwo-Mega-Y", 150),
    (181, "Ampharos-Mega", 181), (208, "Steelix-Mega", 208), (212, "Scizor-Mega", 212), (214, "Heracross-Mega", 214),
    (229, "Houndoom-Mega", 229), (248, "Tyranitar-Mega", 248), (254, "Sceptile-Mega", 254), (257, "Blaziken-Mega", 257),
    (260, "Swampert-Mega", 260), (282, "Gardevoir-Mega", 282), (303, "Mawile-Mega", 303), (306, "Aggron-Mega", 306),
    (308, "Medicham-Mega", 308), (310, "Manectric-Mega", 310), (354, "Banette-Mega", 354), (359, "Absol-Mega", 359),
    (445, "Garchomp-Mega", 445), (448, "Lucario-Mega", 448), (460, "Abomasnow-Mega", 460)
]

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger("pokemon_bot")
