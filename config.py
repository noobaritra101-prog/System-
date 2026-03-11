# config.py
import logging

# ================== CONFIG ==================
BOT_TOKEN = "8311035050:AAEfGHJEjqi59jifzbdP1rxJQ1LoLwQN3Nw"
OWNER_ID = 5716292610
LOG_GROUP_ID = -1002790195961
FLEE_TIMEOUT = 120

# POSTGRESQL URL
DATABASE_URL = "postgresql://postgres.cywehetfjxedufhpktfz:ncXUOSyHOdgyenTb@aws-1-ap-northeast-1.pooler.supabase.com:6543/postgres"

REGIONS = ["Kanto", "Johto", "Hoenn", "Sinnoh", "Unova", "Kalos", "Alola", "Galar"]

# ==================== MEGA EVOLUTION REGISTRY ====================
MEGA_POKEMON = [
    (3, "Venusaur-Mega", 3), (6, "Charizard-Mega-X", 6), (6, "Charizard-Mega-Y", 6), (9, "Blastoise-Mega", 9),
    (15, "Beedrill-Mega", 15), (18, "Pidgeot-Mega", 18), (26, "Raichu-Mega-X", 26), (26, "Raichu-Mega-Y", 26),
    (65, "Alakazam-Mega", 65), (71, "Victreebel-Mega", 71), (80, "Slowbro-Mega", 80), (94, "Gengar-Mega", 94),
    (115, "Kangaskhan-Mega", 115), (121, "Starmie-Mega", 121), (127, "Pinsir-Mega", 127), (130, "Gyarados-Mega", 130),
    (142, "Aerodactyl-Mega", 142), (149, "Dragonite-Mega", 149), (150, "Mewtwo-Mega-X", 150), (150, "Mewtwo-Mega-Y", 150),
    (154, "Meganium-Mega", 154), (160, "Feraligatr-Mega", 160), (181, "Ampharos-Mega", 181), (208, "Steelix-Mega", 208),
    (212, "Scizor-Mega", 212), (214, "Heracross-Mega", 214), (227, "Skarmory-Mega", 227), (229, "Houndoom-Mega", 229),
    (248, "Tyranitar-Mega", 248), (254, "Sceptile-Mega", 254), (257, "Blaziken-Mega", 257), (260, "Swampert-Mega", 260),
    (282, "Gardevoir-Mega", 282), (302, "Sableye-Mega", 302), (303, "Mawile-Mega", 303), (306, "Aggron-Mega", 306),
    (308, "Medicham-Mega", 308), (310, "Manectric-Mega", 310), (319, "Sharpedo-Mega", 319), (323, "Camerupt-Mega", 323),
    (334, "Altaria-Mega", 334), (354, "Banette-Mega", 354), (358, "Chimecho-Mega", 358), (359, "Absol-Mega", 359), 
    (362, "Glalie-Mega", 362), (373, "Salamence-Mega", 373), (376, "Metagross-Mega", 376), (380, "Latias-Mega", 380), 
    (381, "Latios-Mega", 381), (384, "Rayquaza-Mega", 384), (428, "Lopunny-Mega", 428), (445, "Garchomp-Mega", 445), 
    (448, "Lucario-Mega", 448), (448, "Lucario-Mega-Z", 448), (460, "Abomasnow-Mega", 460), (475, "Gallade-Mega", 475), 
    (500, "Emboar-Mega", 500), (530, "Excadrill-Mega", 530), (531, "Audino-Mega", 531), (545, "Scolipede-Mega", 545), 
    (560, "Scrafty-Mega", 560), (604, "Eelektross-Mega", 604), (609, "Chandelure-Mega", 609), (623, "Golurk-Mega", 623), 
    (652, "Chesnaught-Mega", 652), (655, "Delphox-Mega", 655), (658, "Greninja-Mega", 658), (687, "Malamar-Mega", 687), 
    (689, "Barbaracle-Mega", 689), (701, "Hawlucha-Mega", 701), (718, "Zygarde-Mega", 718), (719, "Diancie-Mega", 719),
    (768, "Golisopod-Mega", 768), (780, "Drampa-Mega", 780), (801, "Magearna-Mega", 801), (807, "Zeraora-Mega", 807),
    (870, "Falinks-Mega", 870)
]

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger("pokemon_bot")
