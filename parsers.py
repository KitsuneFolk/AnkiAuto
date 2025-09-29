import re

import config


def parse_passive_line(line):
    """
    Parses a line.
    Handles three primary formats:
    1) (摯)... -> Kanji card with special tag.
    2) front　back -> separated by full-width space.
    3) ばらまきspending (money) recklessly -> Vocab card.
    Returns: (front, back, card_type_tag_suffix)
    """
    line = line.replace('\u200b', '').strip()
    if not line:
        return None, None, None

    # Check for the specific Kanji format first: (Kanji) reading...
    match_kanji_format = re.match(r'^(\(.+?\))\s*(.+)$', line)
    if match_kanji_format:
        front = match_kanji_format.group(1).strip()
        back = match_kanji_format.group(2).strip()
        return front, back, config.PASSIVE_KANJI_TAG

    # New format: front　back (full-width space)
    if '　' in line:
        parts = line.split('　', 1)
        if len(parts) == 2:
            front = parts[0].strip()
            back = parts[1].strip()
            if front and back:
                return front, back, None

    # Vocabulary card parsing:
    # 1. Front part must be Japanese characters (including specified punctuation).
    # 2. Back part must start with a non-Japanese, non-space character.
    # 3. Special handling for commas in the back part: if a comma is followed by Japanese text,
    #    the entire text after the comma is included in the back.
    # 4. Otherwise, the back part consists of non-Japanese characters, stopping at the first Japanese character.

    jp_char_class = r'[\u3040-\u30FF\u4e00-\u9fff\u3002\u3001\u300C\u300D\u3005]'
    # Regex to capture Japanese front and the rest of the line if it starts with a non-Japanese, non-space char
    vocab_pattern_initial_split = re.compile(
        r'^(' + jp_char_class + r'+)'  # Group 1: Japanese front part
        r'(\s*[^ \s' + jp_char_class.replace('[', '').replace(']', '') + r'].*)$'  # Group 2: Potential back part
    )
    match_vocab = vocab_pattern_initial_split.match(line)

    if match_vocab:
        front_text = match_vocab.group(1).strip()
        potential_back_text = match_vocab.group(2).strip()
        final_back_text = ""

        # Check for comma rule: "text_before_comma , japanese_text_after_comma"
        # Find the first comma (English or Japanese)
        comma_idx = -1
        first_comma_char = None
        for i, char_code in enumerate(potential_back_text):
            if char_code == ',' or char_code == '、':
                comma_idx = i
                first_comma_char = char_code
                break

        if comma_idx != -1:
            text_after_comma = potential_back_text[comma_idx + 1:]
            # If text after comma contains any Japanese character, take the whole potential_back_text
            if re.search(jp_char_class, text_after_comma):
                final_back_text = potential_back_text
            else:
                # Comma not followed by Japanese text, treat as normal character.
                # Fall through to character-by-character accumulation for the part before the comma,
                # then append comma and the rest (which is non-Japanese).
                # This means the comma itself is treated as a non-Japanese char if not followed by Japanese.
                # For simplicity now, if comma rule for Japanese extension doesn't apply,
                # we process the potential_back_text by accumulating non-Japanese chars.
                pass # Let the next block handle it by iterating

        if not final_back_text: # If comma rule didn't set final_back_text
            accumulated_chars = []
            # Iterate through the potential_back_text (already stripped of leading whitespace by group 2 capture)
            # or potential_back_text.lstrip() if group 2 could have leading space.
            # Group 2's regex `\s*[^ \s...]` ensures first non-space is non-Japanese.
            for char_code in potential_back_text: # Iterate over the original potential_back_text
                if not re.match(jp_char_class, char_code):
                    accumulated_chars.append(char_code)
                else:
                    # Stop at the first Japanese character if comma rule didn't apply
                    break
            final_back_text = "".join(accumulated_chars).strip()

        if final_back_text: # Ensure the back is not empty after processing
            return front_text, final_back_text, None
        else:
            # This case might happen if potential_back_text was, e.g., only Japanese chars after a comma
            # that itself wasn't caught by the "comma followed by Japanese" rule, or if potential_back_text
            # started with non-Japanese but then only had Japanese chars which were all stripped.
            # Given the initial regex, group 2 must start with non-Jap, so final_back_text should not be empty
            # unless potential_back_text itself was just spaces (but regex for group 2 prevents that).
            # This path implies an issue or an edge case not fully covered.
            # For safety, if final_back is empty, consider it unparseable.
            return None, None, None

    # If no pattern matches (neither Kanji nor new Vocab logic)
    return None, None, None


def parse_active_line(line):
    """
    Parses a line for active recall cards.
    Handles two primary formats:
    1) (English phrase) Japanese phrase
    2) Japanese phrase (English phrase)
    Returns: (front, back, card_type_tag_suffix)
    """
    line = line.replace('\u200b', '').strip()
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
