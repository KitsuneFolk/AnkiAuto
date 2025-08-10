import re

import config


# Defining Japanese character class as a constant for reuse.
JP_CHAR_CLASS = r'[\u3040-\u30FF\u4e00-\u9fff\u3002\u3001\u300C\u300D\u3005]'


def _parse_kanji_line(line):
    """Handles parsing of lines in the format: (Kanji) reading..."""
    match = re.match(r'^(\(.+?\))\s*(.+)$', line)
    if match:
        return match.group(1).strip(), match.group(2).strip(), config.PASSIVE_KANJI_TAG
    return None, None, None


def _parse_vocab_line(line):
    """
    Handles parsing of lines in the format: Japanese_word English_definition
    - The back part must start with a non-Japanese, non-space character.
    - Special comma handling: if a comma is followed by Japanese text, the entire text after the comma is included.
    """
    # Regex to capture Japanese front and the rest of the line.
    vocab_pattern = re.compile(
        r'^(' + JP_CHAR_CLASS + r'+)'  # Group 1: Japanese front
        r'(\s*[^ \s' + JP_CHAR_CLASS.replace('[', '').replace(']', '') + r'].*)$'  # Group 2: Potential back
    )
    match = vocab_pattern.match(line)
    if not match:
        return None, None, None

    front_text = match.group(1).strip()
    potential_back = match.group(2).strip()
    final_back = ""

    # Check for the comma rule.
    comma_match = re.search(r'[,、]', potential_back)
    if comma_match:
        comma_idx = comma_match.start()
        text_after_comma = potential_back[comma_idx + 1:]
        if re.search(JP_CHAR_CLASS, text_after_comma):
            final_back = potential_back
        else:
            # Fall through to accumulate non-Japanese characters if comma rule doesn't apply.
            pass

    if not final_back:
        accumulated_chars = []
        for char in potential_back:
            if not re.match(JP_CHAR_CLASS, char):
                accumulated_chars.append(char)
            else:
                break  # Stop at the first Japanese character.
        final_back = "".join(accumulated_chars).strip()

    return (front_text, final_back, None) if final_back else (None, None, None)


def parse_passive_line(line):
    """
    Parses a line for passive cards, dispatching to specific parsers.
    Handles two formats:
    1) (摯)... -> Kanji card with special tag.
    2) ばらまき spending (money) recklessly -> Vocab card.
    Returns: (front, back, card_type_tag_suffix)
    """
    line = line.strip()
    if not line:
        return None, None, None

    # Try parsing as a Kanji card first.
    front, back, tag = _parse_kanji_line(line)
    if front:
        return front, back, tag

    # If not a Kanji card, try parsing as a vocabulary card.
    return _parse_vocab_line(line)


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
