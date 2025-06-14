import re
import config


def parse_passive_line(line):
    """
    Parses a line.
    Handles two primary formats:
    1) (摯)... -> Kanji card with special tag.
    2) ばらまきspending (money) recklessly -> Vocab card.
    Returns: (front, back, card_type_tag_suffix)
    """
    line = line.strip()
    if not line:
        return None, None, None

    # Check for the specific Kanji format first: (Kanji) reading...
    match_kanji_format = re.match(r'^(\(.+?\))\s*(.+)$', line)
    if match_kanji_format:
        front = match_kanji_format.group(1).strip()
        back = match_kanji_format.group(2).strip()
        return front, back, config.PASSIVE_KANJI_TAG

    # It takes the initial Japanese (kana and/or kanji) as the front and EVERYTHING else as the back.
    match_vocab = re.match(r'^([\u3040-\u30FF\u4e00-\u9fff]+)(.+)$', line)
    if match_vocab:
        front = match_vocab.group(1).strip()
        back = match_vocab.group(2).strip()
        return front, back, None

    # If no pattern matches
    return None, None, None


def parse_active_line(line):
    """
    Parses a line for active recall cards.
    Handles two primary formats:
    1) (English phrase) Japanese phrase
    2) Japanese phrase (English phrase)
    Returns: (front, back, card_type_tag_suffix)
    """
    line = line.strip()
    if not line:
        return None, None, None

    # Pattern 1: (English) Japanese
    match_phrase_then_jp = re.match(r'^(\(.+\))\s*(.+)$', line)
    if match_phrase_then_jp:
        front = match_phrase_then_jp.group(1).strip()
        back = match_phrase_then_jp.group(2).strip()
        return front, back, None

    # Pattern 2: Japanese (English)
    match_jp_then_phrase = re.match(r'^(.+?)\s*(\(.+\))$', line)
    if match_jp_then_phrase:
        # The order is swapped to keep (English) as the front
        front = match_jp_then_phrase.group(2).strip()
        back = match_jp_then_phrase.group(1).strip()
        return front, back, None

    return None, None, None