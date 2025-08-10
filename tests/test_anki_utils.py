import unittest
from unittest.mock import patch, call
import sys
import os
import ntpath

import anki_utils


class TestAnkiUtils(unittest.TestCase):
    """Tests for the anki_utils functions."""

    @patch('anki_utils.anki_request')
    def test_get_info_for_existing_notes(self, mock_anki_request):
        """
        Verify that get_info_for_existing_notes functions correctly.
        """
        mock_anki_request.side_effect = [
            {"result": [101, 102], "error": None},
            {"result": [
                {"noteId": 101, "fields": {"Front": {"value": "front1"}}, "cards": [201]},
                {"noteId": 102, "fields": {"Front": {"value": "front2"}}, "cards": [202]}
            ], "error": None},
            {"result": [
                {"cardId": 201, "deckName": "Deck A"},
                {"cardId": 202, "deckName": "Deck B"}
            ], "error": None}
        ]

        front_texts = ["front1", "front2"]
        result_map = anki_utils.get_info_for_existing_notes(front_texts)

        self.assertIn("deckName", result_map["front1"])
        self.assertEqual(result_map["front1"]["deckName"], "Deck A")
        self.assertIn("deckName", result_map["front2"])
        self.assertEqual(result_map["front2"]["deckName"], "Deck B")

        self.assertEqual(mock_anki_request.call_count, 3)
        self.assertEqual(mock_anki_request.call_args_list[0][0][0], "findNotes")
        self.assertEqual(mock_anki_request.call_args_list[1][0][0], "notesInfo")
        self.assertEqual(mock_anki_request.call_args_list[2][0][0], "cardsInfo")

    @patch('anki_utils.anki_request')
    def test_ensure_deck_exists_creates_deck(self, mock_anki_request):
        """Test that ensure_deck_exists creates a deck if it does not exist."""
        mock_anki_request.side_effect = [
            {"result": ["Default"], "error": None},  # deckNames
            {"result": 12345, "error": None}  # createDeck
        ]
        self.assertTrue(anki_utils.ensure_deck_exists("New-Deck"))
        mock_anki_request.assert_has_calls([
            call('deckNames'),
            call('createDeck', deck='New-Deck')
        ])

    @patch('anki_utils.anki_request')
    def test_add_notes_bulk(self, mock_anki_request):
        """Test that add_notes_bulk calls addNotes with the correct parameters."""
        notes = [{"front": "f1", "back": "b1"}]
        anki_utils.add_notes_bulk(notes)
        mock_anki_request.assert_called_once_with("addNotes", notes=notes)

    @patch('anki_utils.anki_request')
    def test_add_note_single(self, mock_anki_request):
        """Test that add_note_single calls addNote with allowDuplicate."""
        note = {"front": "f1", "back": "b1"}
        anki_utils.add_note_single(note)
        expected_note = note.copy()
        expected_note.setdefault('options', {})['allowDuplicate'] = True
        mock_anki_request.assert_called_once_with("addNote", note=expected_note)

    @patch('anki_utils.anki_request')
    def test_reset_cards(self, mock_anki_request):
        """Test that reset_cards calls unsuspend and forgetCards."""
        note_ids = [1, 2, 3]
        card_ids = [101, 102, 103]
        mock_anki_request.side_effect = [
            {"result": card_ids, "error": None},  # findCards
            {"result": None, "error": None},  # unsuspend
            {"result": None, "error": None}  # forgetCards
        ]
        anki_utils.reset_cards(note_ids)
        mock_anki_request.assert_has_calls([
            call('findCards', query='nid:1 or nid:2 or nid:3'),
            call('unsuspend', cards=card_ids),
            call('forgetCards', cards=card_ids)
        ])

    @patch('sys.platform', 'win32')
    @patch.dict('os.environ', {'ProgramFiles': 'C:\\Program Files'}, clear=True)
    @patch('os.path.exists', return_value=True)
    @patch('os.path.join', new=ntpath.join)
    def test_get_anki_executable_path_windows(self, mock_exists):
        """Test get_anki_executable_path on Windows."""
        self.assertEqual(anki_utils.get_anki_executable_path(), 'C:\\Program Files\\Anki\\anki.exe')

    @patch('sys.platform', 'darwin')
    @patch('os.path.exists', return_value=True)
    def test_get_anki_executable_path_macos(self, mock_exists):
        """Test get_anki_executable_path on macOS."""
        self.assertEqual(anki_utils.get_anki_executable_path(), '/Applications/Anki.app/Contents/MacOS/Anki')

    @patch('sys.platform', 'linux')
    @patch('os.path.exists', side_effect=lambda p: p == '/usr/bin/anki')
    def test_get_anki_executable_path_linux(self, mock_exists):
        """Test get_anki_executable_path on Linux."""
        self.assertEqual(anki_utils.get_anki_executable_path(), '/usr/bin/anki')


if __name__ == '__main__':
    unittest.main(verbosity=2)
