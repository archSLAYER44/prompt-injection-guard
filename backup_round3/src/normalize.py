"""Text views used by the rule features.

raw    the input, untouched (stylometric rules)
light  NFKC + lowercase + whitespace cleanup (delimiter rules, baseline for hidden hits)
norm   light + de-obfuscation: zero-width strip, homoglyphs, leetspeak, spaced-out letters;
       base64 and hex runs replaced by their decoded text; reassembled split payloads,
       rot13 and reversed readings appended when the text asks for them
"""
import base64
import binascii
import codecs
import re
import unicodedata
from dataclasses import dataclass

ZERO_WIDTH_RE = re.compile("[​-‏⁠﻿­]")

LEET_MAP = str.maketrans({
    "1": "i", "0": "o", "3": "e", "4": "a", "5": "s", "7": "t", "@": "a", "$": "s",
})
LEET_CHARS = set("013457@$")

# Cyrillic / Greek letters that look like Latin ones
HOMOGLYPHS = str.maketrans({
    "а": "a", "е": "e", "о": "o", "р": "p", "с": "c", "х": "x", "у": "y", "і": "i",
    "ѕ": "s", "ј": "j", "һ": "h", "ԁ": "d", "ո": "n", "к": "k", "м": "m", "т": "t",
    "в": "b", "н": "h",
    "α": "a", "ο": "o", "ε": "e", "ι": "i", "κ": "k", "ν": "v", "ρ": "p", "τ": "t",
    "υ": "u", "χ": "x",
})

LATIN_RE = re.compile(r"[a-z]")
FOREIGN_LOOKALIKE_RE = re.compile(r"[Ͱ-ϿЀ-ԯ]")

# single characters separated by one space or separator: "i g n o r e", "i.g.n.o.r.e"
SPACED_LETTERS_RE = re.compile(r"(?<![^\W_])(?:[^\W_][ ._\-*]){3,}[^\W_](?![^\W_])")


@dataclass
class Views:
    raw: str
    light: str
    norm: str


def is_mixed_script(token):
    return bool(LATIN_RE.search(token) and FOREIGN_LOOKALIKE_RE.search(token))


LEET_INSIDE_RE = re.compile(r"[a-z][013457@$]+[a-z]", re.I)
LEET_LEADING_RE = re.compile(r"^[013457@$][a-z]{4,}", re.I)
EMAIL_OR_URL_RE = re.compile(r"\w@\w+\.\w|://|^www\.", re.I)
BASE64_RE = re.compile(r"(?<![A-Za-z0-9+/])(?=[A-Za-z0-9+/]*[0-9+/A-Z])[A-Za-z0-9+/]{20,}={0,2}")


def is_leet(token):
    """A word with leet characters standing in for letters, e.g. 'pr3vious', '1gnore'.

    Ordinary tokens such as '3pm', '15th', 'mp3' or an email address do not count.
    """
    core = token.strip(".,;:!?\"'()[]{}")
    if len(core) > 20 or EMAIL_OR_URL_RE.search(core):
        return False
    return bool(LEET_INSIDE_RE.search(core) or LEET_LEADING_RE.search(core))


HEX_RE = re.compile(r"\b(?:[0-9a-fA-F]{2}[ :]?){8,}\b|(?:\\x[0-9a-fA-F]{2}){4,}")
ROT13_HINT_RE = re.compile(r"\brot-?13\b|\bcaesar\b", re.I)
REVERSE_HINT_RE = re.compile(r"\b(?:revers\w*|backwards?)\b", re.I)


def _readable(data):
    """Decoded bytes as text, or None when they are not plain readable text."""
    try:
        plain = data.decode("utf-8")
    except UnicodeDecodeError:
        return None
    if plain and sum(c.isalpha() or c.isspace() for c in plain) / len(plain) > 0.8:
        return plain
    return None


def _decode_base64(match):
    run = match.group(0)
    try:
        data = base64.b64decode(run + "=" * (-len(run) % 4), validate=True)
    except (binascii.Error, ValueError):
        return run
    return _readable(data) or run


def _decode_hex(match):
    digits = re.sub(r"\\x|[ :]", "", match.group(0))
    try:
        data = bytes.fromhex(digits)
    except ValueError:
        return match.group(0)
    return _readable(data) or match.group(0)


def decode_runs(text):
    """Replace base64 and hex runs that hide readable text with that text."""
    return HEX_RE.sub(_decode_hex, BASE64_RE.sub(_decode_base64, text))


COMMON_WORDS = frozenset("""
a about above after all an and any are as at be before below but by can do for from have how i
if in into is it me my no not now of on only or our out say so that the their them then this to
up us was we what when who will with without you your
ignore forget reveal show print tell follow rules instructions prompt system secret password
""".split())


def looks_english(text):
    words = re.findall(r"[a-z']+", text.lower())
    return len(words) >= 2 and sum(w in COMMON_WORDS for w in words) / len(words) >= 0.2


def alternate_readings(text):
    """Readings the text itself asks for (rot13 or reversed), kept when they read as English."""
    decoders = []
    if ROT13_HINT_RE.search(text):
        decoders.append(lambda part: codecs.decode(part, "rot13"))
    if REVERSE_HINT_RE.search(text):
        decoders.append(lambda part: part[::-1])

    readings = []
    for decode in decoders:
        for part in re.split(r"[:\n()]", text):
            part = ROT13_HINT_RE.sub("", part).strip()
            if len(part.split()) < 2 or looks_english(part):
                continue
            reading = decode(part).strip()
            if looks_english(reading):
                readings.append(reading)
    return readings


def decoded_runs(text):
    """The readable text hidden in base64 and hex runs."""
    found = []
    for pattern, decode in ((BASE64_RE, _decode_base64), (HEX_RE, _decode_hex)):
        for match in pattern.finditer(text):
            plain = decode(match)
            if plain != match.group(0):
                found.append(plain)
    return found


# quoted fragments handed out piece by piece: a = "ign", let b be 'ore rules'
SPLIT_PART_RE = re.compile(r"\b\w+\s*(?:=|:|\bbe\b|\bis\b)\s*[\"']([^\"'\n]{1,80})[\"']", re.I)


def reassemble_split_parts(text):
    """The payload of a split attack put back together, joined with and without spaces."""
    parts = SPLIT_PART_RE.findall(text)
    if len(parts) < 2:
        return []
    return [" ".join(parts), "".join(parts)]


def _clean_whitespace(text):
    text = re.sub(r"[^\S\n]+", " ", text)
    text = re.sub(r" ?\n ?", "\n", text)
    return re.sub(r"\n{2,}", "\n", text).strip()


def light_normalize(text):
    return _clean_whitespace(unicodedata.normalize("NFKC", text).lower())


def _could_be_leet(token):
    core = token.strip(".,;:!?\"'()[]{}")
    if len(core) > 20 or EMAIL_OR_URL_RE.search(core):
        return False
    return any(c.isalpha() for c in core) and any(c in LEET_CHARS for c in core)


def _deobfuscate_token(token, leet_text):
    if is_mixed_script(token):
        token = token.translate(HOMOGLYPHS)
    if is_leet(token) or (leet_text and _could_be_leet(token)):
        token = token.translate(LEET_MAP)
    return token


def normalize(text):
    text = ZERO_WIDTH_RE.sub("", text)
    text = decode_runs(text)
    hidden = reassemble_split_parts(text) + alternate_readings(text)
    if hidden:
        text = text + "\n" + "\n".join(hidden)
    text = light_normalize(text)
    text = SPACED_LETTERS_RE.sub(lambda m: re.sub(r"[ ._\-*]", "", m.group(0)), text)
    # split on whitespace but keep it, so newlines survive
    parts = re.split(r"(\s+)", text)
    # once a text clearly uses leetspeak, short words such as "7h3" are decoded too
    leet_text = sum(is_leet(p) for p in parts) >= 2
    return "".join(p if p.isspace() else _deobfuscate_token(p, leet_text) for p in parts)


def hidden_readings(text):
    """Everything a text hides: decoded runs, reassembled payloads, rot13/reversed readings."""
    text = ZERO_WIDTH_RE.sub("", text)
    return decoded_runs(text) + reassemble_split_parts(text)[:1] + alternate_readings(text)


def make_views(text):
    return Views(raw=text, light=light_normalize(text), norm=normalize(text))
