# --- AnkiConnect General Configuration ---
ANKI_CONNECT_URL = "http://localhost:8765"
MODEL_NAME = "Basic"

# --- Deck Configurations ---
PASSIVE_DECK_NAME = "Japanese::Passive"
ACTIVE_DECK_NAME = "Japanese::Active"
PASSIVE_KANJI_TAG = "Kanji"

# --- Overall Processing Configuration ---
# This list defines deck properties, which parser to use, and tag generation rules.
PROCESSING_CONFIGS = [
    {
        "deck_name": PASSIVE_DECK_NAME,
        "parser_func_name": "parse_passive_line",
        "tag_generation_func": lambda tag_suffix: [PASSIVE_KANJI_TAG] if tag_suffix == PASSIVE_KANJI_TAG else []
    },
    {
        "deck_name": ACTIVE_DECK_NAME,
        "parser_func_name": "parse_active_line",
        "tag_generation_func": lambda tag_suffix: []
    }
]
