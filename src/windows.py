"""Split long texts into overlapping windows.

The embedding model reads at most 128 tokens, so anything later in a long document
would be invisible to it. Each window is scored on its own and the text takes the
score of its most suspicious window.
"""
import re

WINDOW_CHARS = 450
BOUNDARY_RE = re.compile(r"(?<=[.!?])\s+|\n+")


def _units(text, size):
    """Sentence-like spans of the text, none longer than the window size."""
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
    return units


def split_windows(text, size=WINDOW_CHARS, limit=None):
    """Windows of whole sentences, each overlapping the previous one by a sentence."""
    text = text.strip()
    if len(text) <= size:
        return [text]

    units = _units(text, size)
    windows, first = [], 0
    while first < len(units):
        last = first
        while last + 1 < len(units) and units[last + 1][1] - units[first][0] <= size:
            last += 1
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
