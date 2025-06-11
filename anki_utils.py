# anki_utils.py
import json
import urllib.error
import urllib.request

# Import common configuration
import config


def anki_request(action, **params):
    """Helper function to send requests to AnkiConnect."""
    payload = {"action": action, "params": params, "version": 6}
    try:
        response = urllib.request.urlopen(
            urllib.request.Request(config.ANKI_CONNECT_URL, json.dumps(payload).encode('utf-8'))
        )
        return json.load(response)
    except urllib.error.URLError as e:
        print(f"Error connecting to AnkiConnect: {e}")
        print("Please ensure Anki is running and AnkiConnect is installed.")
        return None


def ensure_deck_exists(deck_name):
    """Checks if a deck exists and creates it if it doesn't."""
    deck_names_response = anki_request('deckNames')
    if deck_names_response is None:
        return False  # Cannot connect or get deck names

    if deck_name not in deck_names_response.get('result', []):
        print(f"Deck '{deck_name}' not found. Creating it...")
        create_response = anki_request('createDeck', deck=deck_name)
        if create_response is None or create_response.get('error'):
            print(f"Could not create deck '{deck_name}'. Please create it manually in Anki.")
            return False
    return True


def add_card(target_deck_name, model_name, front, back, tags_list):
    """
    Adds a single card to the specified Anki deck.
    Returns: "added", "skipped", or "failed"
    """
    note = {
        "deckName": target_deck_name,
        "modelName": model_name,
        "fields": {
            "Front": front,
            "Back": back
        },
        "options": {
            "allowDuplicate": False,
            "duplicateScope": "deck",
            "duplicateScopeOptions": {
                "deckName": target_deck_name,
                "checkChildren": False,
                "checkAllModels": False
            }
        },
        "tags": tags_list
    }

    # Check for duplicates by Front field within the target deck
    query = f'"deck:{target_deck_name}" "Front:{front}"'
    find_response = anki_request('findNotes', query=query)

    if find_response is None:
        return "failed"

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
        if "cannot create note because it is a duplicate" in str(error).lower():
            print(f"  > Skipping (reported as duplicate by Anki in '{target_deck_name}'): {front}")
            return "skipped"
        print(f"  x Failed to add '{front}' to '{target_deck_name}': {error}")
        return "failed"
