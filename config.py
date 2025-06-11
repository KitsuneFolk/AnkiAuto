# config.py

# --- AnkiConnect General Configuration ---
ANKI_CONNECT_URL = "http://localhost:8765"
MODEL_NAME = "Basic"  # Anki Note Type/Model Name (e.g., "Basic", "Japanese (recognition)")

# --- Card Type Specific Configurations ---

# Configuration for "Japanese::Passive" deck cards
PASSIVE_DECK_NAME = "Japanese::Passive"
PASSIVE_INPUT_FILE = "passive_cards.txt"
PASSIVE_KANJI_TAG = "Kanji"  # Tag applied to (Kanji) cards in Passive deck

# Configuration for "Japanese::Active" deck cards
ACTIVE_DECK_NAME = "Japanese::Active"
ACTIVE_INPUT_FILE = "active_cards.txt"

# --- Overall Processing Configuration ---
# This list defines which files to process, which deck they go to,
# which parser to use, and how to generate tags.
PROCESSING_CONFIGS = [
    {
        "file_path": PASSIVE_INPUT_FILE,
        "deck_name": PASSIVE_DECK_NAME,
        "parser_func_name": "parse_passive_line",  # Function name in parsers.py
        "tag_generation_func": lambda tag_suffix: [PASSIVE_KANJI_TAG] if tag_suffix == PASSIVE_KANJI_TAG else []
    },
    {
        "file_path": ACTIVE_INPUT_FILE,
        "deck_name": ACTIVE_DECK_NAME,
        "parser_func_name": "parse_active_line",  # Function name in parsers.py
        "tag_generation_func": lambda tag_suffix: []  # Active cards have no tags
    }
]
