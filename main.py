#!/usr/bin/env python3
import json
import re
import urllib.request

# --- Configuration ---
ANKI_CONNECT_URL = "http://localhost:8765"
MODEL_NAME = "Basic"  # Model for all cards (e.g., "Basic", "Basic (and reversed card)")

# Passive Deck Configuration
PASSIVE_DECK_NAME = "Japanese::Passive"
PASSIVE_INPUT_FILE = "passive_cards.txt"
KANJI_CARD_TAG = "Kanji"  # Specific tag for Kanji cards in Passive deck (e.g., (摯) ...)

# Active Deck Configuration
ACTIVE_DECK_NAME = "Japanese::Active"
ACTIVE_INPUT_FILE = "active_cards.txt"


# Active cards do not have specific tags per requirements.
# ---------------------

def anki_request(action, **params):
    """Helper function to send requests to AnkiConnect."""
    payload = {"action": action, "params": params, "version": 6}
    try:
        response = urllib.request.urlopen(
            urllib.request.Request(ANKI_CONNECT_URL, json.dumps(payload).encode('utf-8'))
        )
        return json.load(response)
    except urllib.error.URLError as e:
        print(f"Error connecting to AnkiConnect: {e}")
        print("Please ensure Anki is running and AnkiConnect is installed.")
        return None


def parse_passive_line(line):
    """
    Parses a line from passive_cards.txt to extract the front, back, and a tag.
    Handles three formats:
    1) いすわるto stay -> Front: 'いすわる', Back: 'to stay' (no tag)
    2) せつseason節 -> Front: 'せつ', Back: 'season' (no tag)
    3) (摯)　(シ)　真摯 -> Front: '(摯)', Back: '(シ)　真摯' (KANJI_CARD_TAG)
    Returns: (front, back, card_type_tag_suffix) where suffix is KANJI_CARD_TAG or None.
    """
    line = line.strip()
    if not line:
        return None, None, None

    # Regex for Kanji format: (Kanji/Word) Reading/Example
    # e.g., (摯) (シ) 真摯  OR (岩) いわ OR (色素) しきそ
    # Front: Content inside first parentheses (including parentheses)
    # Back: Everything after the first closing parenthesis
    # This must be first as it's very distinct.
    match_kanji_format = re.match(r'^(\(.+?\))\s*(.+)$', line)
    if match_kanji_format:
        front = match_kanji_format.group(1).strip()
        back = match_kanji_format.group(2).strip()
        return front, back, KANJI_CARD_TAG  # This type gets the Kanji tag

    # Regex for original vocabulary format 1: (JapaneseKana)(English)
    # e.g., いすわるto stay
    match_vocab_no_trailing = re.match(r'^([\u3040-\u30FF]+)([a-zA-Z\s]+)$', line)
    if match_vocab_no_trailing:
        front = match_vocab_no_trailing.group(1).strip()
        back = match_vocab_no_trailing.group(2).strip()
        return front, back, None  # This type gets no specific tag

    # Regex for original vocabulary format 2: (JapaneseKana)(English)(Ignored Kanji/Chars)
    # e.g., せつseason節
    # This must be checked after the more specific pattern with no trailing characters.
    match_vocab_with_trailing = re.match(r'^([\u3040-\u30FF]+)([a-zA-Z\s]+).+$', line)
    if match_vocab_with_trailing:
        front = match_vocab_with_trailing.group(1).strip()
        back = match_vocab_with_trailing.group(2).strip()
        return front, back, None  # This type gets no specific tag

    # If no pattern matches
    return None, None, None


def parse_active_line(line):
    """
    Parses a line from active_cards.txt to extract the front and back.
    Handles two formats:
    1) (English phrase)JapaneseWord -> Front: '(English phrase)', Back: 'JapaneseWord'
    2) JapaneseWord(Kanji) -> Front: '(Kanji)', Back: 'JapaneseWord'
    Returns: (front, back, None) (no specific tags for active cards)
    """
    line = line.strip()
    if not line:
        return None, None, None

    # Japanese character set for the "JapaneseWord" part (Hiragana, Katakana, Common Kanji)
    # This covers `紙の本`, `はっかく`, `ひきつる`, `愛しい`, `混`
    JP_CHARS = r'[\u3040-\u30FF\u4E00-\u9FAF]+'

    # Pattern 1: (Phrase in brackets)JapaneseWord (e.g., (physical book)紙の本, (to spasm) ひきつる)
    # Front: the bracketed phrase, Back: the Japanese word/kana
    match_phrase_then_jp = re.match(r'^(\(.+?\))\s*(' + JP_CHARS + r')$', line)
    if match_phrase_then_jp:
        front = match_phrase_then_jp.group(1).strip()  # Capture (physical book)
        back = match_phrase_then_jp.group(2).strip()  # Capture 紙の本
        return front, back, None

    # Pattern 2: JapaneseWord(Kanji in brackets) (e.g., はっかく(発見), しがい(死体))
    # Front: the bracketed Kanji, Back: the Japanese word/kana
    match_jp_then_kanji = re.match(r'^(' + JP_CHARS + r')\s*(\(.+?\))$', line)
    if match_jp_then_kanji:
        front = match_jp_then_kanji.group(2).strip()  # Capture (発見)
        back = match_jp_then_kanji.group(1).strip()  # Capture はっかく
        return front, back, None

    # If no pattern matches
    return None, None, None


def add_card(target_deck_name, front, back, tags_list):
    """
    Adds a single card to the specified Anki deck.
    Returns: "added", "skipped", or "failed"
    """
    note = {
        "deckName": target_deck_name,
        "modelName": MODEL_NAME,
        "fields": {
            "Front": front,
            "Back": back
        },
        "options": {
            "allowDuplicate": False,  # AnkiConnect will prevent exact duplicates in the deck
            "duplicateScope": "deck",  # Check for duplicates within this deck
            "duplicateScopeOptions": {
                "deckName": target_deck_name,
                "checkChildren": False,  # Do not check subdecks for duplicates
                "checkAllModels": False  # Only check duplicates for the current model
            }
        },
        "tags": tags_list
    }

    # Check for duplicates by Front field within the target deck
    # AnkiConnect's addNote with allowDuplicate=false also performs this check,
    # but an explicit findNotes gives us a better message for skipped cards.
    query = f'"deck:{target_deck_name}" "Front:{front}"'
    find_response = anki_request('findNotes', query=query)

    if find_response is None:
        return "failed"  # AnkiConnect connection error

    if find_response.get('result'):
        print(f"  > Skipping (already exists in '{target_deck_name}' based on Front field): {front}")
        return "skipped"

    add_response = anki_request('addNote', note=note)
    if add_response and add_response.get('error') is None and add_response.get('result') is not None:
        tags_display = f" (Tags: {', '.join(tags_list)})" if tags_list else ""
        print(f"  + Added to '{target_deck_name}': {front} -> {back}{tags_display}")
        return "added"
    else:
        error = add_response.get('error') if add_response else "Unknown error"
        # AnkiConnect might return an error if allowDuplicate is false and a card with the same first field exists
        # even if other fields are different.
        if "cannot create note because it is a duplicate" in str(error).lower():
            print(f"  > Skipping (reported as duplicate by Anki in '{target_deck_name}'): {front}")
            return "skipped"
        print(f"  x Failed to add '{front}' to '{target_deck_name}': {error}")
        return "failed"


def main():
    """Main function to read files and add cards to Anki."""
    print("--- Starting Anki Card Importer ---")

    anki_version_response = anki_request('version')
    if anki_version_response is None:
        return  # Exit if we can't connect to Anki
    print(f"Connected to AnkiConnect version {anki_version_response.get('result')}")

    # Ensure target decks exist in Anki
    deck_names_response = anki_request('deckNames')
    if deck_names_response is None: return

    # Define the files to process and their corresponding decks/parsers/tagging rules
    processing_configs = [
        {
            "file": PASSIVE_INPUT_FILE,
            "deck": PASSIVE_DECK_NAME,
            "parser": parse_passive_line,
            "tags_func": lambda tag_suffix: [tag_suffix] if tag_suffix else []  # Tags for Kanji cards only
        },
        {
            "file": ACTIVE_INPUT_FILE,
            "deck": ACTIVE_DECK_NAME,
            "parser": parse_active_line,
            "tags_func": lambda tag_suffix: []  # No tags for Active cards
        }
    ]

    # Check and create decks if they don't exist
    for config in processing_configs:
        deck_name = config["deck"]
        if deck_name not in deck_names_response.get('result', []):
            print(f"Deck '{deck_name}' not found. Creating it...")
            create_response = anki_request('createDeck', deck=deck_name)
            if create_response is None or create_response.get('error'):
                print(f"Could not create deck '{deck_name}'. Please create it manually in Anki.")
                return  # Exit if any deck creation fails

    total_newly_added = 0
    total_skipped = 0
    total_failed = 0
    total_unparsable = 0

    # Process each configured file
    for config in processing_configs:
        file_path = config["file"]
        deck_name = config["deck"]
        parse_func = config["parser"]
        tags_func = config["tags_func"]

        print(f"\n--- Processing '{file_path}' for deck '{deck_name}' ---")
        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                lines = f.readlines()
        except FileNotFoundError:
            print(f"Error: Input file '{file_path}' not found. Skipping this file.")
            continue  # Skip this file and proceed to the next one

        for i, line_content in enumerate(lines):
            line_content = line_content.strip()
            if not line_content:
                continue

            front, back, card_specific_tag = parse_func(line_content)

            if front and back:
                current_tags = tags_func(card_specific_tag)  # Get tags based on the function provided by config

                status = add_card(deck_name, front, back, current_tags)

                if status == "added":
                    total_newly_added += 1
                elif status == "skipped":
                    total_skipped += 1
                elif status == "failed":
                    total_failed += 1
            else:
                print(f"  ! Warning: Could not parse line {i + 1} in '{file_path}': '{line_content}'")
                total_unparsable += 1

    print("\n--- Import Complete ---")
    print(f"Total newly added cards: {total_newly_added}")
    print(f"Total skipped (already exist or reported as duplicate): {total_skipped}")
    print(f"Total failed to add (due to error): {total_failed}")
    print(f"Total unparsable lines: {total_unparsable}")


if __name__ == "__main__":
    main()