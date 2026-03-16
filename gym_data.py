# gym_data.py

GYM_LEADERS = {
    "Brock": {"name": "Brock", "gym_name": "Pewter City Gym", "badge": "Boulder Badge", "icon": "🪨", "type": "Rock", "team": ["Geodude", "Graveler", "Onix"]},
    "Misty": {"name": "Misty", "gym_name": "Cerulean City Gym", "badge": "Cascade Badge", "icon": "🌊", "type": "Water", "team": ["Staryu", "Psyduck", "Starmie"]},
    "Surge": {"name": "Lt. Surge", "gym_name": "Vermilion City Gym", "badge": "Thunder Badge", "icon": "⚡", "type": "Electric", "team": ["Voltorb", "Pikachu", "Raichu"]},
    "Erika": {"name": "Erika", "gym_name": "Celadon City Gym", "badge": "Rainbow Badge", "icon": "🌈", "type": "Grass", "team": ["Victreebel", "Tangela", "Vileplume"]},
    "Koga": {"name": "Koga", "gym_name": "Fuchsia City Gym", "badge": "Soul Badge", "icon": "☠️", "type": "Poison", "team": ["Koffing", "Muk", "Weezing"]},
    "Sabrina": {"name": "Sabrina", "gym_name": "Saffron City Gym", "badge": "Marsh Badge", "icon": "🔮", "type": "Psychic", "team": ["Kadabra", "Mr. Mime", "Alakazam"]},
    "Blaine": {"name": "Blaine", "gym_name": "Cinnabar Island Gym", "badge": "Volcano Badge", "icon": "🔥", "type": "Fire", "team": ["Growlithe", "Ponyta", "Arcanine"]},
    "Giovanni": {"name": "Giovanni", "gym_name": "Viridian City Gym", "badge": "Earth Badge", "icon": "🌍", "type": "Ground", "team": ["Dugtrio", "Nidoqueen", "Rhydon"]}
}

ASH_ROSTER = ["Pikachu", "Charizard", "Bulbasaur", "Squirtle", "Snorlax", "Pidgeot", "Muk", "Tauros", "Kingler"]

AUTHENTIC_STATS = {
    "Pikachu": {"hp": 280, "atk": 220, "def": 180, "spd": 320, "type": "Electric"},
    "Charizard": {"hp": 340, "atk": 280, "def": 240, "spd": 300, "type": "Fire/Flying"},
    "Bulbasaur": {"hp": 300, "atk": 200, "def": 200, "spd": 210, "type": "Grass/Poison"},
    "Squirtle": {"hp": 290, "atk": 210, "def": 230, "spd": 220, "type": "Water"},
    "Snorlax": {"hp": 400, "atk": 290, "def": 250, "spd": 150, "type": "Normal"},
    "Pidgeot": {"hp": 310, "atk": 260, "def": 220, "spd": 310, "type": "Normal/Flying"},
    "Muk": {"hp": 350, "atk": 270, "def": 240, "spd": 180, "type": "Poison"},
    "Tauros": {"hp": 320, "atk": 280, "def": 250, "spd": 290, "type": "Normal"},
    "Kingler": {"hp": 300, "atk": 300, "def": 280, "spd": 240, "type": "Water"},
    
    "Geodude": {"hp": 260, "atk": 240, "def": 280, "spd": 150, "type": "Rock/Ground"},
    "Graveler": {"hp": 300, "atk": 270, "def": 300, "spd": 170, "type": "Rock/Ground"},
    "Onix": {"hp": 280, "atk": 210, "def": 320, "spd": 240, "type": "Rock/Ground"},
    "Staryu": {"hp": 260, "atk": 200, "def": 200, "spd": 280, "type": "Water"},
    "Psyduck": {"hp": 280, "atk": 220, "def": 200, "spd": 210, "type": "Water"},
    "Starmie": {"hp": 320, "atk": 280, "def": 250, "spd": 310, "type": "Water/Psychic"},
    "Voltorb": {"hp": 260, "atk": 200, "def": 200, "spd": 300, "type": "Electric"},
    "Raichu": {"hp": 310, "atk": 280, "def": 220, "spd": 310, "type": "Electric"},
    "Victreebel": {"hp": 330, "atk": 290, "def": 220, "spd": 240, "type": "Grass/Poison"},
    "Tangela": {"hp": 310, "atk": 240, "def": 280, "spd": 220, "type": "Grass"},
    "Vileplume": {"hp": 330, "atk": 270, "def": 250, "spd": 200, "type": "Grass/Poison"},
    "Koffing": {"hp": 280, "atk": 220, "def": 260, "spd": 180, "type": "Poison"},
    "Weezing": {"hp": 320, "atk": 280, "def": 300, "spd": 220, "type": "Poison"},
    "Kadabra": {"hp": 260, "atk": 280, "def": 180, "spd": 300, "type": "Psychic"},
    "Mr. Mime": {"hp": 280, "atk": 250, "def": 280, "spd": 260, "type": "Psychic/Fairy"},
    "Alakazam": {"hp": 300, "atk": 320, "def": 200, "spd": 330, "type": "Psychic"},
    "Growlithe": {"hp": 280, "atk": 240, "def": 200, "spd": 220, "type": "Fire"},
    "Ponyta": {"hp": 280, "atk": 250, "def": 210, "spd": 280, "type": "Fire"},
    "Arcanine": {"hp": 350, "atk": 310, "def": 250, "spd": 290, "type": "Fire"},
    "Dugtrio": {"hp": 280, "atk": 280, "def": 200, "spd": 330, "type": "Ground"},
    "Nidoqueen": {"hp": 350, "atk": 270, "def": 260, "spd": 240, "type": "Poison/Ground"},
    "Rhydon": {"hp": 360, "atk": 310, "def": 300, "spd": 180, "type": "Rock/Ground"}
}

AUTHENTIC_MOVES = {
    "Pikachu": [{"name": "Thunderbolt", "type": "Electric", "power": 90, "acc": 100}, {"name": "Iron Tail", "type": "Steel", "power": 100, "acc": 75}, {"name": "Quick Attack", "type": "Normal", "power": 40, "acc": 100}, {"name": "Volt Tackle", "type": "Electric", "power": 120, "acc": 100}],
    "Charizard": [{"name": "Flamethrower", "type": "Fire", "power": 90, "acc": 100}, {"name": "Seismic Toss", "type": "Fighting", "power": 80, "acc": 100}, {"name": "Slash", "type": "Normal", "power": 70, "acc": 100}, {"name": "Dragon Rage", "type": "Dragon", "power": 80, "acc": 100}],
    "Bulbasaur": [{"name": "Vine Whip", "type": "Grass", "power": 45, "acc": 100}, {"name": "Razor Leaf", "type": "Grass", "power": 55, "acc": 95}, {"name": "Tackle", "type": "Normal", "power": 40, "acc": 100}, {"name": "Solar Beam", "type": "Grass", "power": 120, "acc": 100}],
    "Squirtle": [{"name": "Water Gun", "type": "Water", "power": 40, "acc": 100}, {"name": "Hydro Pump", "type": "Water", "power": 110, "acc": 80}, {"name": "Skull Bash", "type": "Normal", "power": 130, "acc": 100}, {"name": "Bite", "type": "Normal", "power": 60, "acc": 100}],
    "Snorlax": [{"name": "Body Slam", "type": "Normal", "power": 85, "acc": 100}, {"name": "Hyper Beam", "type": "Normal", "power": 150, "acc": 90}, {"name": "Mega Punch", "type": "Normal", "power": 120, "acc": 85}, {"name": "Ice Punch", "type": "Ice", "power": 75, "acc": 100}],
    "Pidgeot": [{"name": "Gust", "type": "Flying", "power": 40, "acc": 100}, {"name": "Quick Attack", "type": "Normal", "power": 40, "acc": 100}, {"name": "Double-Edge", "type": "Normal", "power": 120, "acc": 100}, {"name": "Hurricane", "type": "Flying", "power": 110, "acc": 70}],
    "Muk": [{"name": "Sludge Bomb", "type": "Poison", "power": 90, "acc": 100}, {"name": "Body Slam", "type": "Normal", "power": 85, "acc": 100}, {"name": "Poison Jab", "type": "Poison", "power": 80, "acc": 100}, {"name": "Gunk Shot", "type": "Poison", "power": 120, "acc": 80}],
    "Tauros": [{"name": "Horn Attack", "type": "Normal", "power": 65, "acc": 100}, {"name": "Take Down", "type": "Normal", "power": 90, "acc": 85}, {"name": "Earthquake", "type": "Ground", "power": 100, "acc": 100}, {"name": "Zen Headbutt", "type": "Psychic", "power": 80, "acc": 90}],
    "Kingler": [{"name": "Crabhammer", "type": "Water", "power": 100, "acc": 90}, {"name": "Bubble Beam", "type": "Water", "power": 65, "acc": 100}, {"name": "Stomp", "type": "Normal", "power": 65, "acc": 100}, {"name": "Vice Grip", "type": "Normal", "power": 55, "acc": 100}],
    
    "Geodude": [{"name": "Rock Throw", "type": "Rock", "power": 50, "acc": 90}, {"name": "Tackle", "type": "Normal", "power": 40, "acc": 100}, {"name": "Magnitude", "type": "Ground", "power": 70, "acc": 100}, {"name": "Rollout", "type": "Rock", "power": 60, "acc": 90}],
    "Graveler": [{"name": "Rock Slide", "type": "Rock", "power": 75, "acc": 90}, {"name": "Earthquake", "type": "Ground", "power": 100, "acc": 100}, {"name": "Take Down", "type": "Normal", "power": 90, "acc": 85}, {"name": "Rock Tomb", "type": "Rock", "power": 60, "acc": 95}],
    "Onix": [{"name": "Bind", "type": "Normal", "power": 15, "acc": 85}, {"name": "Rock Throw", "type": "Rock", "power": 50, "acc": 90}, {"name": "Slam", "type": "Normal", "power": 80, "acc": 75}, {"name": "Iron Tail", "type": "Steel", "power": 100, "acc": 75}],
    "Staryu": [{"name": "Water Gun", "type": "Water", "power": 40, "acc": 100}, {"name": "Rapid Spin", "type": "Normal", "power": 50, "acc": 100}, {"name": "Swift", "type": "Normal", "power": 60, "acc": 100}, {"name": "Bubble Beam", "type": "Water", "power": 65, "acc": 100}],
    "Psyduck": [{"name": "Water Gun", "type": "Water", "power": 40, "acc": 100}, {"name": "Confusion", "type": "Psychic", "power": 50, "acc": 100}, {"name": "Zen Headbutt", "type": "Psychic", "power": 80, "acc": 90}, {"name": "Surf", "type": "Water", "power": 90, "acc": 100}],
    "Starmie": [{"name": "Bubble Beam", "type": "Water", "power": 65, "acc": 100}, {"name": "Swift", "type": "Normal", "power": 60, "acc": 100}, {"name": "Psychic", "type": "Psychic", "power": 90, "acc": 100}, {"name": "Hydro Pump", "type": "Water", "power": 110, "acc": 80}],
    "Voltorb": [{"name": "Tackle", "type": "Normal", "power": 40, "acc": 100}, {"name": "Spark", "type": "Electric", "power": 65, "acc": 100}, {"name": "Thunderbolt", "type": "Electric", "power": 90, "acc": 100}, {"name": "Rollout", "type": "Rock", "power": 60, "acc": 90}],
    "Raichu": [{"name": "Thunderbolt", "type": "Electric", "power": 90, "acc": 100}, {"name": "Mega Kick", "type": "Normal", "power": 120, "acc": 75}, {"name": "Quick Attack", "type": "Normal", "power": 40, "acc": 100}, {"name": "Thunder", "type": "Electric", "power": 110, "acc": 70}],
    "Victreebel": [{"name": "Razor Leaf", "type": "Grass", "power": 55, "acc": 95}, {"name": "Acid", "type": "Poison", "power": 40, "acc": 100}, {"name": "Sludge Bomb", "type": "Poison", "power": 90, "acc": 100}, {"name": "Solar Beam", "type": "Grass", "power": 120, "acc": 100}],
    "Tangela": [{"name": "Vine Whip", "type": "Grass", "power": 45, "acc": 100}, {"name": "Bind", "type": "Normal", "power": 15, "acc": 85}, {"name": "Mega Drain", "type": "Grass", "power": 40, "acc": 100}, {"name": "Power Whip", "type": "Grass", "power": 120, "acc": 85}],
    "Vileplume": [{"name": "Mega Drain", "type": "Grass", "power": 40, "acc": 100}, {"name": "Petal Dance", "type": "Grass", "power": 120, "acc": 100}, {"name": "Sludge Bomb", "type": "Poison", "power": 90, "acc": 100}, {"name": "Solar Beam", "type": "Grass", "power": 120, "acc": 100}],
    "Koffing": [{"name": "Sludge", "type": "Poison", "power": 65, "acc": 100}, {"name": "Tackle", "type": "Normal", "power": 40, "acc": 100}, {"name": "Smog", "type": "Poison", "power": 30, "acc": 70}, {"name": "Sludge Bomb", "type": "Poison", "power": 90, "acc": 100}],
    "Weezing": [{"name": "Sludge Bomb", "type": "Poison", "power": 90, "acc": 100}, {"name": "Sludge", "type": "Poison", "power": 65, "acc": 100}, {"name": "Tackle", "type": "Normal", "power": 40, "acc": 100}, {"name": "Dark Pulse", "type": "Dark", "power": 80, "acc": 100}],
    "Kadabra": [{"name": "Confusion", "type": "Psychic", "power": 50, "acc": 100}, {"name": "Psybeam", "type": "Psychic", "power": 65, "acc": 100}, {"name": "Psychic", "type": "Psychic", "power": 90, "acc": 100}, {"name": "Shadow Ball", "type": "Ghost", "power": 80, "acc": 100}],
    "Mr. Mime": [{"name": "Confusion", "type": "Psychic", "power": 50, "acc": 100}, {"name": "Psybeam", "type": "Psychic", "power": 65, "acc": 100}, {"name": "Magical Leaf", "type": "Grass", "power": 60, "acc": 100}, {"name": "Psychic", "type": "Psychic", "power": 90, "acc": 100}],
    "Alakazam": [{"name": "Psychic", "type": "Psychic", "power": 90, "acc": 100}, {"name": "Psybeam", "type": "Psychic", "power": 65, "acc": 100}, {"name": "Focus Blast", "type": "Fighting", "power": 120, "acc": 70}, {"name": "Shadow Ball", "type": "Ghost", "power": 80, "acc": 100}],
    "Growlithe": [{"name": "Bite", "type": "Normal", "power": 60, "acc": 100}, {"name": "Ember", "type": "Fire", "power": 40, "acc": 100}, {"name": "Take Down", "type": "Normal", "power": 90, "acc": 85}, {"name": "Flamethrower", "type": "Fire", "power": 90, "acc": 100}],
    "Ponyta": [{"name": "Stomp", "type": "Normal", "power": 65, "acc": 100}, {"name": "Ember", "type": "Fire", "power": 40, "acc": 100}, {"name": "Take Down", "type": "Normal", "power": 90, "acc": 85}, {"name": "Fire Spin", "type": "Fire", "power": 35, "acc": 85}],
    "Arcanine": [{"name": "Flamethrower", "type": "Fire", "power": 90, "acc": 100}, {"name": "Bite", "type": "Normal", "power": 60, "acc": 100}, {"name": "Take Down", "type": "Normal", "power": 90, "acc": 85}, {"name": "Fire Blast", "type": "Fire", "power": 110, "acc": 85}],
    "Dugtrio": [{"name": "Dig", "type": "Ground", "power": 80, "acc": 100}, {"name": "Slash", "type": "Normal", "power": 70, "acc": 100}, {"name": "Earthquake", "type": "Ground", "power": 100, "acc": 100}, {"name": "Magnitude", "type": "Ground", "power": 70, "acc": 100}],
    "Nidoqueen": [{"name": "Body Slam", "type": "Normal", "power": 85, "acc": 100}, {"name": "Double Kick", "type": "Normal", "power": 60, "acc": 100}, {"name": "Earthquake", "type": "Ground", "power": 100, "acc": 100}, {"name": "Sludge Bomb", "type": "Poison", "power": 90, "acc": 100}],
    "Rhydon": [{"name": "Horn Drill", "type": "Normal", "power": 80, "acc": 100}, {"name": "Take Down", "type": "Normal", "power": 90, "acc": 85}, {"name": "Earthquake", "type": "Ground", "power": 100, "acc": 100}, {"name": "Rock Slide", "type": "Rock", "power": 75, "acc": 90}],
}
