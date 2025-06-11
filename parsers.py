# parsers.py
import re
import config

def parse_passive_line(line):
    """
    Parses a line from passive_cards.txt.
    Handles two primary formats:
    1) (摯)... -> Kanji card with special tag.
    2) ばらまきspending (money) recklessly -> Vocab card.
    Returns: (front, back, card_type_tag_suffix)
    """
    line = line.strip()
    if not line:
        return None, None, None

    # 1. Check for the specific Kanji format first: (Kanji) reading...
    match_kanji_format = re.match(r'^(\(.+?\))\s*(.+)$', line)
    if match_kanji_format:
        front = match_kanji_format.group(1).strip()
        back = match_kanji_format.group(2).strip()
        return front, back, config.PASSIVE_KANJI_TAG

    # 2. UPDATED: A more robust regex for general vocabulary.
    # It takes the initial Japanese kana as the front and EVERYTHING else as the back.
    # This correctly handles backs with nested parentheses.
    match_vocab = re.match(r'^([\u3040-\u30FF]+)(.+)$', line)
    if match_vocab:
        front = match_vocab.group(1).strip()
        back = match_vocab.group(2).strip()
        return front, back, None

    # If no pattern matches
    return None, None, None

def parse_active_line(line):
    # This function remains unchanged as its logic was already robust.
    line = line.strip()
    if not line:
        return None, None, None
    JP_CHARS_PATTERN = r'[\u3040-\u30FF\u4E00-\u9FAF\uFF00-\uFFEF]+'
    match_phrase_then_jp = re.match(r'^(\(.+?\))\s*(' + JP_CHARS_PATTERN + r')$', line)
    if match_phrase_then_jp:
        return match_phrase_then_jp.group(1).strip(), match_phrase_then_jp.group(2).strip(), None
    match_jp_then_kanji = re.match(r'^(' + JP_CHARS_PATTERN + r')\s*(\(.+?\))$', line)
    if match_jp_then_kanji:
        return match_jp_then_kanji.group(2).strip(), match_jp_then_kanji.group(1).strip(), None
    return None, None, None