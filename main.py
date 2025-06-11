#!/usr/bin/env python3
import json
import re
import urllib.request

# --- Configuration ---
ANKI_CONNECT_URL = "http://localhost:8765"
DECK_NAME = "Japanese::Passive"  # Deck for all cards
MODEL_NAME = "Basic"  # Model for all cards
INPUT_FILE = "passive_cards.txt"
KANJI_CARD_TAG = "Kanji"  # Specific tag for the new Kanji format


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


def parse_line(line):
    """
    Parses a line to extract the front, back, and a type identifier for tagging.
    Returns: (front, back, card_type_tag_suffix)
    card_type_tag_suffix can be KANJI_CARD_TAG or None.
    """
    line = line.strip()
    if not line:
        return None, None, None

    # Regex for new Kanji format: (Kanji/Word) Reading/Example
    # e.g., (摯) (シ) 真摯  OR (岩) いわ OR (色素) しきそ
    # MODIFICATION HERE: The first capturing group now includes the literal parentheses
    match_new_kanji_format = re.match(r'^(\(.+?\))\s*(.+)$', line)
    if match_new_kanji_format:
        front = match_new_kanji_format.group(1).strip()  # Will now capture "(摯)"
        back = match_new_kanji_format.group(2).strip()
        return front, back, KANJI_CARD_TAG

    # Regex for original format 1: (JapaneseKana)(English)
    # e.g., いすわるto stay
    match_vocab_no_trailing = re.match(r'^([\u3040-\u30FF]+)([a-zA-Z\s]+)$', line)
    if match_vocab_no_trailing:
        front = match_vocab_no_trailing.group(1).strip()
        back = match_vocab_no_trailing.group(2).strip()
        return front, back, None

    # Regex for original format 2: (JapaneseKana)(English)(Ignored Kanji/Chars)
    # e.g., せつseason節
    match_vocab_with_trailing = re.match(r'^([\u3040-\u30FF]+)([a-zA-Z\s]+).+$', line)
    if match_vocab_with_trailing:
        front = match_vocab_with_trailing.group(1).strip()
        back = match_vocab_with_trailing.group(2).strip()
        return front, back, None

    # If no pattern matches
    return None, None, None


def add_card(front, back, tags_list):
    """
    Adds a single card to the specified Anki deck.
    Returns: "added", "skipped", or "failed"
    """
    note = {
        "deckName": DECK_NAME,
        "modelName": MODEL_NAME,
        "fields": {
            "Front": front,
            "Back": back
        },
        "options": {
            "allowDuplicate": False,
            "duplicateScope": "deck",
            "duplicateScopeOptions": {
                "deckName": DECK_NAME,
                "checkChildren": False,
                "checkAllModels": False
            }
        },
        "tags": tags_list
    }

    # Check for duplicates by Front field within the target deck
    query = f'"deck:{DECK_NAME}" "Front:{front}"'
    find_response = anki_request('findNotes', query=query)

    if find_response is None:
        return "failed"

    if find_response.get('result'):
        print(f"  > Skipping (already exists based on Front field): {front}")
        return "skipped"

    add_response = anki_request('addNote', note=note)
    if add_response and add_response.get('error') is None and add_response.get('result') is not None:
        tags_display = f" (Tags: {', '.join(tags_list)})" if tags_list else ""
        print(f"  + Added: {front} -> {back}{tags_display}")
        return "added"
    else:
        error = add_response.get('error') if add_response else "Unknown error"
        if "cannot create note because it is a duplicate" in str(error).lower():
            print(f"  > Skipping (reported as duplicate by Anki): {front}")
            return "skipped"
        print(f"  x Failed to add '{front}': {error}")
        return "failed"


def main():
    """Main function to read the file and add cards to Anki."""
    print("--- Starting Anki Card Importer ---")

    anki_version_response = anki_request('version')
    if anki_version_response is None:
        return
    print(f"Connected to AnkiConnect version {anki_version_response.get('result')}")

    deck_names_response = anki_request('deckNames')
    if deck_names_response is None: return

    if DECK_NAME not in deck_names_response.get('result', []):
        print(f"Deck '{DECK_NAME}' not found. Creating it...")
        create_deck_response = anki_request('createDeck', deck=DECK_NAME)
        if create_deck_response is None or create_deck_response.get('error'):
            print(f"Could not create deck '{DECK_NAME}'. Please create it manually in Anki.")
            return

    try:
        with open(INPUT_FILE, 'r', encoding='utf-8') as f:
            lines = f.readlines()
    except FileNotFoundError:
        print(f"Error: Input file '{INPUT_FILE}' not found.")
        print("Please create it and add your cards.")
        return

    newly_added_count = 0
    skipped_due_to_duplicate_count = 0
    failed_to_add_count = 0
    unparsable_lines_count = 0

    print(f"\nProcessing {len(lines)} lines from '{INPUT_FILE}'...")
    for i, line_content in enumerate(lines):
        line_content = line_content.strip()
        if not line_content:
            continue

        front, back, card_specific_tag = parse_line(line_content)

        if front and back:
            current_tags = []
            if card_specific_tag:
                current_tags.append(card_specific_tag)

            status = add_card(front, back, current_tags)

            if status == "added":
                newly_added_count += 1
            elif status == "skipped":
                skipped_due_to_duplicate_count += 1
            elif status == "failed":
                failed_to_add_count += 1
        else:
            print(f"  ! Warning: Could not parse line {i + 1}: '{line_content}'")
            unparsable_lines_count += 1

    print("\n--- Import Complete ---")
    print(f"Newly added cards: {newly_added_count}")
    print(f"Skipped (already exist or reported as duplicate): {skipped_due_to_duplicate_count}")
    print(f"Failed to add (due to error): {failed_to_add_count}")
    print(f"Unparsable lines: {unparsable_lines_count}")


if __name__ == "__main__":
    main()