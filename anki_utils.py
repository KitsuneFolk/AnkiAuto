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
    Adds a single card.
    Returns: ('status', note_id_or_none)
    e.g., ("added", 12345), ("skipped", 54321), ("failed", None)
    """
    # ... (This function is updated to return the noteId on skip) ...
    query = f'"deck:{target_deck_name}" "Front:{front}"'
    find_response = anki_request('findNotes', query=query)

    if find_response is None:
        return "failed", None

    # If a duplicate is found by the Front field
    if find_response.get('result'):
        note_id = find_response.get('result')[0]
        print(f"  > Skipping (already exists): {front} (Note ID: {note_id})")
        return "skipped", note_id

    note = {
        "deckName": target_deck_name,
        "modelName": model_name,
        "fields": {"Front": front, "Back": back},
        "options": {"allowDuplicate": False, "duplicateScope": "deck"},
        "tags": tags_list
    }

    add_response = anki_request('addNote', note=note)
    if add_response and add_response.get('result'):
        note_id = add_response.get('result')
        print(f"  + Added: {front} -> {back} (Note ID: {note_id})")
        return "added", note_id
    else:
        error = add_response.get('error', "Unknown error")
        print(f"  x Failed to add '{front}': {error}")
        return "failed", None

# --- NEW FUNCTIONS FOR GUI INTERACTION ---

def get_note_info(note_id):
    """Retrieves all info for a given note ID."""
    return anki_request("notesInfo", notes=[note_id])


def update_note_fields(note_id, fields_to_update):
    """Updates one or more fields of an existing note."""
    note = {"id": note_id, "fields": fields_to_update}
    return anki_request("updateNoteFields", note=note)


def reset_cards(note_ids):
    """Resets (forgets) one or more cards, making them new again."""
    return anki_request("relearnNotes", notes=note_ids)


def open_editor_for_note(note_id):
    """Opens the Anki Edit window for a specific note."""
    return anki_request("guiEditNote", note=note_id)