# config.py
import logging

# ================== CONFIG ==================
BOT_TOKEN = "8311035050:AAEfGHJEjqi59jifzbdP1rxJQ1LoLwQN3Nw"
OWNER_ID = 5716292610
LOG_GROUP_ID = -1002790195961
FLEE_TIMEOUT = 120

# NEW POSTGRESQL URL
DATABASE_URL = "postgresql://postgres.cywehetfjxedufhpktfz:ncXUOSyHOdgyenTb@aws-1-ap-northeast-1.pooler.supabase.com:6543/postgres"

REGIONS = ["Kanto", "Johto", "Hoenn", "Sinnoh", "Unova", "Kalos", "Alola", "Galar"]

# ==================== MEGA EVOLUTION REGISTRY ====================
MEGA_POKEMON = [
    (3, "Venusaur-Mega", 3), (6, "Charizard-Mega-X", 6), (6, "Charizard-Mega-Y", 6), (9, "Blastoise-Mega", 9),
    (15, "Beedrill-Mega", 15), (18, "Pidgeot-Mega", 18), (65, "Alakazam-Mega", 65), (80, "Slowbro-Mega", 80),
    (94, "Gengar-Mega", 94), (115, "Kangaskhan-Mega", 115), (127, "Pinsir-Mega", 127), (130, "Gyarados-Mega", 130),
    (142, "Aerodactyl-Mega", 142), (149, "Dragonite-Mega", 149), (150, "Mewtwo-Mega-X", 150), (150, "Mewtwo-Mega-Y", 150),
    (154, "Meganium-Mega", 154), (181, "Ampharos-Mega", 181), (208, "Steelix-Mega", 208), (212, "Scizor-Mega", 212),
    (214, "Heracross-Mega", 214), (229, "Houndoom-Mega", 229), (248, "Tyranitar-Mega", 248), (254, "Sceptile-Mega", 254),
    (257, "Blaziken-Mega", 257), (260, "Swampert-Mega", 260), (282, "Gardevoir-Mega", 282), (302, "Sableye-Mega", 302),
    (303, "Mawile-Mega", 303), (306, "Aggron-Mega", 306), (308, "Medicham-Mega", 308), (310, "Manectric-Mega", 310),
    (319, "Sharpedo-Mega", 319), (323, "Camerupt-Mega", 323), (334, "Altaria-Mega", 334), (354, "Banette-Mega", 354),
    (359, "Absol-Mega", 359), (362, "Glalie-Mega", 362), (373, "Salamence-Mega", 373), (376, "Metagross-Mega", 376),
    (380, "Latias-Mega", 380), (381, "Latios-Mega", 381), (384, "Rayquaza-Mega", 384), (428, "Lopunny-Mega", 428),
    (445, "Garchomp-Mega", 445), (448, "Lucario-Mega", 448), (460, "Abomasnow-Mega", 460), (475, "Gallade-Mega", 475),
    (531, "Audino-Mega", 531), (658, "Greninja-Mega", 658), (719, "Diancie-Mega", 719)
]

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger("pokemon_bot")
