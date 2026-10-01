"""Split long texts into overlapping windows.

The embedding model reads at most 128 tokens, so anything later in a long document
would be invisible to it. Each window is scored on its own and the text takes the
score of its most suspicious window.

Windows are sized by characters first and then checked against the token limit of the
embedding model: code, leetspeak and encoded text carry far more tokens per character
than prose, and without the check the end of such windows was never read. The check
is done on the NORMALIZED text, because that is what gets embedded.
"""
import re

WINDOW_CHARS = 450
WINDOW_TOKENS = 126             # the model reads 128 tokens, two of them are [CLS] and [SEP]
MAX_WINDOWS = 64                # pieces scored per text by predict()
MAX_SENTENCES = 128
TRAIN_WINDOW_LIMIT = 12         # pieces scored per text during training and evaluation
TRAIN_SENTENCE_LIMIT = 16
BOUNDARY_RE = re.compile(r"(?<=[.!?])\s+|\n+")


def _fits(text):
    """True when the normalized text stays within the embedding model's reading limit."""
    from .features import token_count
    from .normalize import normalize

    count = token_count(normalize(text))
    return count is None or count <= WINDOW_TOKENS


def _longest_fit(text, begin, end):
    """End of the longest prefix of text[begin:end] that fits, cut at a space when possible."""
    low, high = begin + 1, end
    while low < high:
        middle = (low + high + 1) // 2
        if _fits(text[begin:middle]):
            low = middle
        else:
            high = middle - 1
    space = text.rfind(" ", begin + (low - begin) // 2, low)
    return space + 1 if space > begin else low


def _token_split(text, begin, end):
    """Pieces of one span, each of which fits the token limit."""
    pieces = []
    while end - begin > 1 and not _fits(text[begin:end]):
        cut = _longest_fit(text, begin, end)
        pieces.append((begin, cut))
        begin = cut
    pieces.append((begin, end))
    return pieces


def _units(text, size):
    """Sentence-like spans of the text, none longer than the window size or the token limit."""
    spans, start = [], 0
    for match in BOUNDARY_RE.finditer(text):
        spans.append((start, match.end()))
        start = match.end()
    spans.append((start, len(text)))

    units = []
    for begin, end in spans:
        while end - begin > size:
            units.append((begin, begin + size))
            begin += size
        if end > begin:
            units.append((begin, end))
    return [piece for begin, end in units for piece in _token_split(text, begin, end)]


def split_windows(text, size=WINDOW_CHARS, limit=None):
    """Windows of whole sentences, each overlapping the previous one by a sentence."""
    text = text.strip()
    if len(text) <= size and _fits(text):
        return [text]

    units = _units(text, size)
    windows, first = [], 0
    while first < len(units):
        last = first
        while last + 1 < len(units) and units[last + 1][1] - units[first][0] <= size:
            last += 1
        while last > first and not _fits(text[units[first][0]:units[last][1]]):
            last -= 1
        windows.append(text[units[first][0]:units[last][1]].strip())
        if last + 1 >= len(units):
            break
        first = last if last > first else last + 1

    return _thin([w for w in windows if w], limit)


def split_sentences(text, min_words=3):
    """Single sentences, for spotting one instruction hidden inside a longer text."""
    sentences = []
    for begin, end in _units(text.strip(), WINDOW_CHARS):
        sentence = text.strip()[begin:end].strip().strip("\"'").strip()
        if len(sentence.split()) >= min_words:
            sentences.append(sentence)
    return sentences


def _thin(items, limit):
    """At most `limit` items, evenly spaced, always keeping the first and the last."""
    if not limit or len(items) <= limit:
        return items
    step = (len(items) - 1) / (limit - 1)
    return [items[round(i * step)] for i in range(limit)]


def split_units(text, window_limit=None, sentence_limit=None):
    """Everything that gets scored for one text, as (kind, text) pairs.

    window    overlapping stretches of the text, as many as the embedding can read at once
    sentence  each sentence alone, so an instruction is not diluted by the text around it
    reading   text that was hidden: decoded base64/hex/rot13, reassembled split payloads
    """
    from .normalize import hidden_readings

    windows = split_windows(text, limit=window_limit)
    units = [("window", w) for w in windows]
    seen = set(windows)
    for kind, items in (("sentence", _thin(split_sentences(text), sentence_limit)),
                        ("reading", hidden_readings(text))):
        for item in items:
            if item not in seen:
                seen.add(item)
                units.append((kind, item))
    return units
