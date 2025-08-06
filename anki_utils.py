import json
import logging
import urllib.error
import urllib.request

import config

# Get a logger for this module
logger = logging.getLogger(__name__)


def anki_request(action, **params):
    """Helper function to send requests to AnkiConnect."""
    payload = {"action": action, "params": params, "version": 6}
    try:
        response = urllib.request.urlopen(
            urllib.request.Request(config.ANKI_CONNECT_URL, json.dumps(payload).encode('utf-8'))
        )
        return json.load(response)
    except urllib.error.URLError as e:
        logger.error(f"Error connecting to AnkiConnect: {e}")
        logger.error("Please ensure Anki is running and AnkiConnect is installed.")
        return None


def ensure_deck_exists(deck_name):
    """Checks if a deck exists and creates it if it doesn't."""
    deck_names_response = anki_request('deckNames')
    if deck_names_response is None:
        return False  # Cannot connect or get deck names

    if deck_name not in deck_names_response.get('result', []):
        logger.info(f"Deck '{deck_name}' not found. Creating it...")
        create_response = anki_request('createDeck', deck=deck_name)
        if create_response is None or create_response.get('error'):
            logger.error(f"Could not create deck '{deck_name}'. Please create it manually in Anki.")
            return False
    return True


def get_info_for_existing_notes(deck_name, front_texts):
    """
    Finds all existing notes in a deck that match a list of front fields.
    Returns a dictionary mapping front_text -> note_info for fast lookups.
    """
    if not front_texts:
        return {}

    # Escape quotes in front text for the query
    escaped_fronts = [f.replace('"', '\\"') for f in front_texts]
    query = f'("Front:{escaped_fronts[0]}"'
    for f in escaped_fronts[1:]:
        query += f' or "Front:{f}"'
    query += ')'

    find_response = anki_request("findNotes", query=query)
    if not find_response or not find_response.get("result"):
        return {}

    existing_note_ids = find_response["result"]
    info_response = anki_request("notesInfo", notes=existing_note_ids)

    if not info_response or not info_response.get("result"):
        return {}

    notes_info = info_response['result']

    # Get the deck name for each note by checking its first card
    all_card_ids = [info['cards'][0] for info in notes_info if info.get('cards')]
    if all_card_ids:
        cards_info_response = anki_request("cardsInfo", cards=all_card_ids)
        if cards_info_response and cards_info_response.get("result"):
            card_id_to_deck = {info['cardId']: info['deckName'] for info in cards_info_response['result']}
            for info in notes_info:
                if info.get('cards'):
                    first_card_id = info['cards'][0]
                    if first_card_id in card_id_to_deck:
                        info['deckName'] = card_id_to_deck[first_card_id]

    # Create a lookup map: {front_text: note_info}
    return {
        info['fields']['Front']['value']: info
        for info in notes_info
    }


def add_notes_bulk(notes_to_add):
    """
    Adds a list of notes in a single batch request.
    Returns the result from the 'addNotes' action.
    """
    if not notes_to_add:
        return None
    return anki_request("addNotes", notes=notes_to_add)


def add_note_single(note_to_add):
    """
    Adds a single note, allowing duplicates.
    A wrapper for the 'addNote' action with allowDuplicate=True.
    """
    if not note_to_add:
        return None

    # Ensure the note payload includes the allowDuplicate option
    note_payload = note_to_add.copy()
    note_payload.setdefault('options', {})['allowDuplicate'] = True

    return anki_request("addNote", note=note_payload)


def get_note_info(note_id):
    """Retrieves all info for a given note ID."""
    return anki_request("notesInfo", notes=[note_id])


def update_note_fields(note_id, fields_to_update):
    """Updates one or more fields of an existing note."""
    note = {"id": note_id, "fields": fields_to_update}
    return anki_request("updateNoteFields", note=note)


def reset_cards(note_ids):
    """
    Resets (forgets) one or more notes, making their cards new again.
    This also ensures the cards are unsuspended so they can be studied.
    """
    if not note_ids:
        return None

    query = " or ".join(f"nid:{nid}" for nid in note_ids)
    response = anki_request("findCards", query=query)

    if not response or not response.get('result'):
        logger.warning(f"No cards found for note IDs {note_ids} during reset.")
        return None

    card_ids = response['result']

    anki_request("unsuspend", cards=card_ids)

    return anki_request("forgetCards", cards=card_ids)


import os
import subprocess
import sys
import time


def get_anki_executable_path():
    """Tries to find the Anki executable path for the current OS."""
    if sys.platform == "win32":
        # Common paths for Windows
        possible_paths = [
            os.path.join(os.environ["ProgramFiles"], "Anki", "anki.exe"),
            os.path.join(os.environ["ProgramFiles(x86)"], "Anki", "anki.exe"),
        ]
    elif sys.platform == "darwin":
        # Common path for macOS
        possible_paths = ["/Applications/Anki.app/Contents/MacOS/Anki"]
    else:
        # Common path for Linux
        possible_paths = ["/usr/bin/anki", "/usr/local/bin/anki"]

    for path in possible_paths:
        if os.path.exists(path):
            return path
    return None


def launch_anki():
    """Launches the Anki application if it's not already running."""
    anki_path = get_anki_executable_path()
    if anki_path:
        try:
            subprocess.Popen([anki_path])
            logger.info(f"Launched Anki from: {anki_path}")
            # Wait for Anki to start up
            time.sleep(10)  # 10 seconds might be enough
            return True
        except Exception as e:
            logger.error(f"Failed to launch Anki: {e}")
            return False
    else:
        logger.warning("Could not find Anki executable. Please start it manually.")
        return False


def open_editor_for_note(note_id):
    """Opens the Anki Edit window for a specific note."""
    return anki_request("guiEditNote", note=note_id)
