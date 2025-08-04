import unittest
from unittest.mock import patch, call

import anki_utils


class TestGetInfoForExistingNotes(unittest.TestCase):
    """Tests for the get_info_for_existing_notes function."""

    @patch('anki_utils.anki_request')
    def test_query_is_global_and_correctly_formatted(self, mock_anki_request):
        """
        Verify that the query sent to AnkiConnect is not deck-specific and
        is formatted correctly for multiple notes.
        """
        # Mock the response from anki_request to prevent actual network calls
        # The first call is findNotes, second is notesInfo.
        # Let's return empty results to keep the test simple.
        mock_anki_request.side_effect = [
            {"result": [], "error": None},  # Mock response for findNotes
            {"result": [], "error": None}   # Mock response for notesInfo
        ]

        deck_name = "any-deck"  # This should be ignored by the function now
        front_texts = ["front1", "front2 with \"quotes\""]

        anki_utils.get_info_for_existing_notes(deck_name, front_texts)

        # We expect anki_request to have been called. Let's check the 'query' parameter
        # of the 'findNotes' action.
        # The first call to anki_request should be for 'findNotes'.
        self.assertGreaterEqual(mock_anki_request.call_count, 1, "anki_request was not called")

        # Get the arguments of the first call
        first_call_args = mock_anki_request.call_args_list[0]

        # The call is made with positional args for action and keyword args for params
        action_arg = first_call_args[0][0]
        params_arg = first_call_args[1]

        self.assertEqual(action_arg, "findNotes", "The action should be findNotes")

        # The query should not contain the deck name
        actual_query = params_arg.get("query")
        self.assertNotIn(deck_name, actual_query, "Query should not be deck-specific")

        # Check if the query is formatted as expected
        expected_query = '("Front:front1" or "Front:front2 with \\\"quotes\\\"")'
        self.assertEqual(actual_query, expected_query, "Query format is incorrect")


if __name__ == '__main__':
    unittest.main(verbosity=2)
