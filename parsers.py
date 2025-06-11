# parsers.py
import re

# Import specific tag from config for passive_line parsing (Kanji tag)
import config


def parse_passive_line(line):
    """
    Parses a line from passive_cards.txt to extract the front, back, and a tag.
    Handles three formats:
    1) いすわるto stay -> Front: 'いすわる', Back: 'to stay' (returns tag_suffix=None)
    2) せつseason節 -> Front: 'せつ', Back: 'season' (returns tag_suffix=None)
    3) (摯)　(シ)　真摯 -> Front: '(摯)', Back: '(シ)　真摯' (returns tag_suffix=config.PASSIVE_KANJI_TAG)
    Returns: (front, back, card_type_tag_suffix)
    """
    line = line.strip()
    if not line:
        return None, None, None

    # Regex for Kanji format: (Kanji/Word) Reading/Example
    # e.g., (摯) (シ) 真摯  OR (岩) いわ OR (色素) しきそ
    # Front: Content inside first parentheses (including parentheses)
    # Back: Everything after the first closing parenthesis
    # This must be first as it's very distinct and specific.
    match_kanji_format = re.match(r'^(\(.+?\))\s*(.+)$', line)
    if match_kanji_format:
        front = match_kanji_format.group(1).strip()
        back = match_kanji_format.group(2).strip()
        return front, back, config.PASSIVE_KANJI_TAG

    # Regex for original vocabulary format 1: (JapaneseKana)(English)
    # e.g., いすわるto stay
    # This must be checked before format 2 as it's more specific (ends exactly after English).
    match_vocab_no_trailing = re.match(r'^([\u3040-\u30FF]+)([a-zA-Z\s]+)$', line)
    if match_vocab_no_trailing:
        front = match_vocab_no_trailing.group(1).strip()
        back = match_vocab_no_trailing.group(2).strip()
        return front, back, None

    # Regex for original vocabulary format 2: (JapaneseKana)(English)(Ignored Kanji/Chars)
    # e.g., せつseason節
    match_vocab_with_trailing = re.match(r'^([\u3040-\u30FF]+)([a-zA-Z\s]+).+$', line)
    if match_vocab_with_trailing:
        front = match_vocab_with_trailing.group(1).strip()
        back = match_vocab_with_trailing.group(2).strip()
        return front, back, None

    # If no pattern matches
    return None, None, None


def parse_active_line(line):
    """
    Parses a line from active_cards.txt to extract the front and back.
    Handles two formats:
    1) (English phrase)JapaneseWord -> Front: '(English phrase)', Back: 'JapaneseWord'
    2) JapaneseWord(Kanji) -> Front: '(Kanji)', Back: 'JapaneseWord'
    Returns: (front, back, None) (no specific tags for active cards via the parser)
    """
    line = line.strip()
    if not line:
        return None, None, None

    # Japanese character set for the "JapaneseWord" part (Hiragana, Katakana, Common Kanji)
    # Using a broad range to cover common Japanese characters.
    JP_CHARS_PATTERN = r'[\u3040-\u30FF\u4E00-\u9FAF\uFF00-\uFFEF]+'

    # Pattern 1: (Phrase in brackets)JapaneseWord (e.g., (physical book)紙の本, (to spasm) ひきつる)
    # Front: the bracketed phrase, Back: the Japanese word/kana
    match_phrase_then_jp = re.match(r'^(\(.+?\))\s*(' + JP_CHARS_PATTERN + r')$', line)
    if match_phrase_then_jp:
        front = match_phrase_then_jp.group(1).strip()  # Capture (physical book)
        back = match_phrase_then_jp.group(2).strip()  # Capture 紙の本
        return front, back, None

    # Pattern 2: JapaneseWord(Kanji in brackets) (e.g., はっかく(発見), しがい(死体))
    # Front: the bracketed Kanji, Back: the Japanese word/kana
    match_jp_then_kanji = re.match(r'^(' + JP_CHARS_PATTERN + r')\s*(\(.+?\))$', line)
    if match_jp_then_kanji:
        front = match_jp_then_kanji.group(2).strip()  # Capture (発見)
        back = match_jp_then_kanji.group(1).strip()  # Capture はっかく
        return front, back, None

    # If no pattern matches
    return None, None, None
