# gym_data.py

GYM_LEADERS = {
    "Brock": {"name": "Brock", "region": "Kanto", "gym_name": "Pewter City Gym", "badge": "Boulder Badge", "icon": "🪨", "type": "Rock", "team": ["Geodude", "Graveler", "Onix"]},
    "Misty": {"name": "Misty", "region": "Kanto", "gym_name": "Cerulean City Gym", "badge": "Cascade Badge", "icon": "🌊", "type": "Water", "team": ["Staryu", "Psyduck", "Starmie"]},
    "Surge": {"name": "Lt. Surge", "region": "Kanto", "gym_name": "Vermilion City Gym", "badge": "Thunder Badge", "icon": "⚡", "type": "Electric", "team": ["Voltorb", "Pikachu", "Raichu"]},
    "Erika": {"name": "Erika", "region": "Kanto", "gym_name": "Celadon City Gym", "badge": "Rainbow Badge", "icon": "🌈", "type": "Grass", "team": ["Victreebel", "Tangela", "Vileplume"]},
    "Koga": {"name": "Koga", "region": "Kanto", "gym_name": "Fuchsia City Gym", "badge": "Soul Badge", "icon": "☠️", "type": "Poison", "team": ["Koffing", "Muk", "Weezing"]},
    "Sabrina": {"name": "Sabrina", "region": "Kanto", "gym_name": "Saffron City Gym", "badge": "Marsh Badge", "icon": "🔮", "type": "Psychic", "team": ["Kadabra", "Mr. Mime", "Alakazam"]},
    "Blaine": {"name": "Blaine", "region": "Kanto", "gym_name": "Cinnabar Island Gym", "badge": "Volcano Badge", "icon": "🔥", "type": "Fire", "team": ["Growlithe", "Ponyta", "Arcanine"]},
    "Giovanni": {"name": "Giovanni", "region": "Kanto", "gym_name": "Viridian City Gym", "badge": "Earth Badge", "icon": "🌍", "type": "Ground", "team": ["Dugtrio", "Nidoqueen", "Rhydon"]},

    "Falkner": {"name": "Falkner", "region": "Johto", "gym_name": "Violet City Gym", "badge": "Zephyr Badge", "icon": "🕊", "type": "Flying", "team": ["Pidgey", "Pidgeotto"]},
    "Bugsy": {"name": "Bugsy", "region": "Johto", "gym_name": "Azalea Town Gym", "badge": "Hive Badge", "icon": "🐞", "type": "Bug", "team": ["Metapod", "Kakuna", "Scyther"]},
    "Whitney": {"name": "Whitney", "region": "Johto", "gym_name": "Goldenrod City Gym", "badge": "Plain Badge", "icon": "🐄", "type": "Normal", "team": ["Clefairy", "Miltank"]},
    "Morty": {"name": "Morty", "region": "Johto", "gym_name": "Ecruteak City Gym", "badge": "Fog Badge", "icon": "👻", "type": "Ghost", "team": ["Gastly", "Haunter", "Haunter", "Gengar"]},
    "Chuck": {"name": "Chuck", "region": "Johto", "gym_name": "Cianwood City Gym", "badge": "Storm Badge", "icon": "🥊", "type": "Fighting", "team": ["Primeape", "Poliwrath"]},
    "Jasmine": {"name": "Jasmine", "region": "Johto", "gym_name": "Olivine City Gym", "badge": "Mineral Badge", "icon": "🔩", "type": "Steel", "team": ["Magnemite", "Magnemite", "Steelix"]},
    "Pryce": {"name": "Pryce", "region": "Johto", "gym_name": "Mahogany Town Gym", "badge": "Glacier Badge", "icon": "❄️", "type": "Ice", "team": ["Seel", "Dewgong", "Piloswine"]},
    "Clair": {"name": "Clair", "region": "Johto", "gym_name": "Blackthorn City Gym", "badge": "Rising Badge", "icon": "🐉", "type": "Dragon", "team": ["Dragonair", "Dragonair", "Gyarados", "Kingdra"]}
}

ASH_KANTO_ROSTER = ["Pikachu", "Charizard", "Bulbasaur", "Squirtle", "Snorlax", "Pidgeot", "Muk", "Tauros", "Kingler"]
ASH_JOHTO_ROSTER = ["Pikachu", "Bayleef", "Cyndaquil", "Totodile", "Noctowl", "Heracross", "Phanpy"]

AUTHENTIC_MOVES = {
    # Kanto Pokemon
    "Pikachu": ["Thunderbolt", "Iron Tail", "Quick Attack", "Volt Tackle"],
    "Charizard": ["Flamethrower", "Seismic Toss", "Slash", "Dragon Rage"],
    "Bulbasaur": ["Vine Whip", "Razor Leaf", "Tackle", "Solar Beam"],
    "Squirtle": ["Water Gun", "Hydro Pump", "Skull Bash", "Bite"],
    "Snorlax": ["Body Slam", "Hyper Beam", "Mega Punch", "Ice Punch"],
    "Pidgeot": ["Gust", "Quick Attack", "Double-Edge", "Hurricane"],
    "Muk": ["Sludge Bomb", "Body Slam", "Poison Jab", "Gunk Shot"],
    "Tauros": ["Horn Attack", "Take Down", "Earthquake", "Zen Headbutt"],
    "Kingler": ["Crabhammer", "Bubble Beam", "Stomp", "Vice Grip"],

    "Geodude": ["Rock Throw", "Tackle", "Magnitude", "Rollout"],
    "Graveler": ["Rock Slide", "Earthquake", "Take Down", "Rock Tomb"],
    "Onix": ["Bind", "Rock Throw", "Slam", "Iron Tail"],
    "Staryu": ["Water Gun", "Rapid Spin", "Swift", "Bubble Beam"],
    "Psyduck": ["Water Gun", "Confusion", "Zen Headbutt", "Surf"],
    "Starmie": ["Bubble Beam", "Swift", "Psychic", "Hydro Pump"],
    "Voltorb": ["Tackle", "Spark", "Thunderbolt", "Rollout"],
    "Raichu": ["Thunderbolt", "Mega Kick", "Quick Attack", "Thunder"],
    "Victreebel": ["Razor Leaf", "Acid", "Sludge Bomb", "Solar Beam"],
    "Tangela": ["Vine Whip", "Bind", "Mega Drain", "Power Whip"],
    "Vileplume": ["Mega Drain", "Petal Dance", "Sludge Bomb", "Solar Beam"],
    "Koffing": ["Sludge", "Tackle", "Smog", "Sludge Bomb"],
    "Weezing": ["Sludge Bomb", "Sludge", "Tackle", "Dark Pulse"],
    "Kadabra": ["Confusion", "Psybeam", "Psychic", "Shadow Ball"],
    "Mr. Mime": ["Confusion", "Psybeam", "Magical Leaf", "Psychic"],
    "Alakazam": ["Psychic", "Psybeam", "Focus Blast", "Shadow Ball"],
    "Growlithe": ["Bite", "Ember", "Take Down", "Flamethrower"],
    "Ponyta": ["Stomp", "Ember", "Take Down", "Fire Spin"],
    "Arcanine": ["Flamethrower", "Bite", "Take Down", "Fire Blast"],
    "Dugtrio": ["Dig", "Slash", "Earthquake", "Magnitude"],
    "Nidoqueen": ["Body Slam", "Double Kick", "Earthquake", "Sludge Bomb"],
    "Rhydon": ["Horn Drill", "Take Down", "Earthquake", "Rock Slide"],

    # Johto Pokemon
    "Bayleef": ["Razor Leaf", "Vine Whip", "Body Slam", "Synthesis"],
    "Cyndaquil": ["Flamethrower", "Swift", "Smokescreen", "Tackle"],
    "Totodile": ["Water Gun", "Bite", "Slash", "Aqua Tail"],
    "Noctowl": ["Air Slash", "Confusion", "Hypnosis", "Sky Attack"],
    "Heracross": ["Megahorn", "Close Combat", "Horn Attack", "Aerial Ace"],
    "Phanpy": ["Rollout", "Earthquake", "Tackle", "Take Down"],
    "Pidgey": ["Gust", "Quick Attack", "Tackle", "Sand Attack"],
    "Pidgeotto": ["Gust", "Quick Attack", "Wing Attack", "Steel Wing"],
    "Metapod": ["Tackle", "String Shot", "Harden", "Bug Bite"],
    "Kakuna": ["Poison Sting", "Tackle", "String Shot", "Harden"],
    "Scyther": ["Fury Cutter", "Slash", "Wing Attack", "X-Scissor"],
    "Clefairy": ["Metronome", "Double Slap", "Moonblast", "Meteor Mash"],
    "Miltank": ["Rollout", "Body Slam", "Stomp", "Zen Headbutt"],
    "Gastly": ["Lick", "Shadow Ball", "Sludge Bomb", "Dark Pulse"],
    "Haunter": ["Shadow Punch", "Shadow Ball", "Sludge Bomb", "Dark Pulse"],
    "Gengar": ["Shadow Ball", "Sludge Bomb", "Focus Blast", "Dazzling Gleam"],
    "Primeape": ["Cross Chop", "Karate Chop", "Seismic Toss", "Close Combat"],
    "Poliwrath": ["Dynamic Punch", "Hydro Pump", "Submission", "Bubble Beam"],
    "Magnemite": ["Thunderbolt", "Spark", "Flash Cannon", "Swift"],
    "Steelix": ["Iron Tail", "Earthquake", "Rock Slide", "Crunch"],
    "Seel": ["Aurora Beam", "Headbutt", "Icy Wind", "Surf"],
    "Dewgong": ["Aurora Beam", "Ice Beam", "Surf", "Signal Beam"],
    "Piloswine": ["Blizzard", "Earthquake", "Ice Fang", "Take Down"],
    "Dragonair": ["Dragon Rage", "Slam", "Dragon Tail", "Aqua Tail"],
    "Gyarados": ["Hydro Pump", "Hyper Beam", "Dragon Breath", "Crunch"],
    "Kingdra": ["Hydro Pump", "Dragon Pulse", "Twister", "Ice Beam"]
}
