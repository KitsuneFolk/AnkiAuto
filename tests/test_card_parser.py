import unittest
from unittest.mock import patch

from parsers import parse_passive_line, parse_active_line


# To test the `parse_passive_line` function, we need to mock the `config` module
# it depends on. This fake class will stand in for the real config.
class MockConfig:
    PASSIVE_KANJI_TAG = 'test-passive-kanji'


# We use the @patch decorator to replace the actual `config` module in `parsers`
# with our MockConfig for the duration of these tests.
@patch('parsers.config', new=MockConfig)
class TestParsePassiveLine(unittest.TestCase):
    """Tests for the parse_passive_line function."""

    def test_kanji_card_standard(self):
        """Tests a standard kanji card format: (Kanji) reading..."""
        line = "(摯) し sincerity, admonish"
        front, back, tag = parse_passive_line(line)
        self.assertEqual(front, "(摯)")
        self.assertEqual(back, "し sincerity, admonish")
        self.assertEqual(tag, MockConfig.PASSIVE_KANJI_TAG)

    def test_kanji_card_with_extra_whitespace(self):
        """Tests that leading/trailing whitespace is correctly stripped."""
        line = "  (摯)   し sincerity, admonish  "
        front, back, tag = parse_passive_line(line)
        self.assertEqual(front, "(摯)")
        self.assertEqual(back, "し sincerity, admonish")
        self.assertEqual(tag, MockConfig.PASSIVE_KANJI_TAG)

    def test_vocab_card_standard(self):
        """Tests a standard vocab card format: Japanese... English..."""
        line = "ばらまきspending (money) recklessly"
        front, back, tag = parse_passive_line(line)
        self.assertEqual(front, "ばらまき")
        self.assertEqual(back, "spending (money) recklessly")
        self.assertIsNone(tag)

    def test_vocab_card_with_katakana(self):
        """Tests that the vocab parser handles katakana correctly."""
        line = "コンピューター a computer"
        front, back, tag = parse_passive_line(line)
        self.assertEqual(front, "コンピューター")
        self.assertEqual(back, "a computer")
        self.assertIsNone(tag)

    def test_vocab_card_with_kanji(self):
        """Tests that the vocab parser handles words with kanji."""
        line = "童謡children's song"
        front, back, tag = parse_passive_line(line)
        self.assertEqual(front, "童謡")
        self.assertEqual(back, "children's song")
        self.assertIsNone(tag)

    def test_vocab_card_with_extra_whitespace(self):
        """Tests a vocab card with extra whitespace."""
        line = "  ばらまき   spending (money) recklessly  "
        front, back, tag = parse_passive_line(line)
        self.assertEqual(front, "ばらまき")
        self.assertEqual(back, "spending (money) recklessly")
        self.assertIsNone(tag)

    def test_empty_line(self):
        """Tests that an empty line returns None for all fields."""
        line = ""
        front, back, tag = parse_passive_line(line)
        self.assertIsNone(front)
        self.assertIsNone(back)
        self.assertIsNone(tag)

    def test_whitespace_only_line(self):
        """Tests that a line with only whitespace returns None for all fields."""
        line = "   \t   "
        front, back, tag = parse_passive_line(line)
        self.assertIsNone(front)
        self.assertIsNone(back)
        self.assertIsNone(tag)

    def test_no_match_english_first(self):
        """Tests a line that doesn't match any passive format."""
        line = "This is a line that should not match"
        front, back, tag = parse_passive_line(line)
        self.assertIsNone(front)
        self.assertIsNone(back)
        self.assertIsNone(tag)

    def test_no_match_kanji_format_without_back(self):
        """Tests a line that looks like kanji format but has no back part."""
        # The regex `(.+)` requires at least one character for the back.
        line = "(摯)"
        front, back, tag = parse_passive_line(line)
        self.assertIsNone(front)
        self.assertIsNone(back)
        self.assertIsNone(tag)


class TestParseActiveLine(unittest.TestCase):
    """Tests for the parse_active_line function."""

    def test_english_then_japanese_standard(self):
        """Tests the (English) Japanese format."""
        line = "(to spend money recklessly) ばらまき"
        front, back, tag = parse_active_line(line)
        self.assertEqual(front, "(to spend money recklessly)")
        self.assertEqual(back, "ばらまき")
        self.assertIsNone(tag)

    def test_english_then_japanese_with_whitespace(self):
        """Tests the (English) Japanese format with extra whitespace."""
        line = "  (to spend money recklessly)   ばらまき  "
        front, back, tag = parse_active_line(line)
        self.assertEqual(front, "(to spend money recklessly)")
        self.assertEqual(back, "ばらまき")
        self.assertIsNone(tag)

    def test_japanese_then_english_standard(self):
        """Tests the Japanese (English) format, ensuring front/back are swapped."""
        line = "ばらまき (to spend money recklessly)"
        front, back, tag = parse_active_line(line)
        # Note the swapped order: English part should be the front
        self.assertEqual(front, "(to spend money recklessly)")
        self.assertEqual(back, "ばらまき")
        self.assertIsNone(tag)

    def test_japanese_then_english_with_whitespace(self):
        """Tests the Japanese (English) format with extra whitespace."""
        line = "  ばらまき   (to spend money recklessly)  "
        front, back, tag = parse_active_line(line)
        self.assertEqual(front, "(to spend money recklessly)")
        self.assertEqual(back, "ばらまき")
        self.assertIsNone(tag)

    def test_japanese_with_punctuation(self):
        """Tests that Japanese phrases with punctuation are handled correctly."""
        line = "これは何ですか、ええと (What is this?)"
        front, back, tag = parse_active_line(line)
        self.assertEqual(front, "(What is this?)")
        self.assertEqual(back, "これは何ですか、ええと")
        self.assertIsNone(tag)

    def test_empty_line(self):
        """Tests that an empty line returns None."""
        line = ""
        front, back, tag = parse_active_line(line)
        self.assertIsNone(front)
        self.assertIsNone(back)
        self.assertIsNone(tag)

    def test_whitespace_only_line(self):
        """Tests that a line with only whitespace returns None."""
        line = "    "
        front, back, tag = parse_active_line(line)
        self.assertIsNone(front)
        self.assertIsNone(back)
        self.assertIsNone(tag)

    def test_no_match_no_parentheses(self):
        """Tests a line with no parentheses, which should not match."""
        line = "a simple phrase"
        front, back, tag = parse_active_line(line)
        self.assertIsNone(front)
        self.assertIsNone(back)
        self.assertIsNone(tag)

    def test_no_match_parentheses_in_middle(self):
        """Tests a line where parentheses are not at the start or end."""
        line = "some text (in the middle) more text"
        front, back, tag = parse_active_line(line)
        self.assertIsNone(front)
        self.assertIsNone(back)
        self.assertIsNone(tag)

    def test_no_match_only_parentheses(self):
        """Tests a line with only a parenthetical, which shouldn't match either pattern."""
        # Pattern 1 requires text *after* the parentheses.
        # Pattern 2 requires text *before* the parentheses.
        line = "(just this)"
        front, back, tag = parse_active_line(line)
        self.assertIsNone(front)
        self.assertIsNone(back)
        self.assertIsNone(tag)

    def test_english_with_nested_parentheses_then_japanese(self):
        """Tests that a parenthetical front with nested parentheses is parsed correctly."""
        line = "(spending (money) recklessly) ばらまき"
        front, back, tag = parse_active_line(line)
        self.assertEqual(front, "(spending (money) recklessly)")
        self.assertEqual(back, "ばらまき")
        self.assertIsNone(tag)


if __name__ == '__main__':
    unittest.main(verbosity=2)