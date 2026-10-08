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
# (the run must hold a letter: "8.8.8.8" and "1.2.3.4" are not spaced-out letters)
SPACED_LETTERS_RE = re.compile(
    r"(?<![^\W_])(?=(?:[^\W_][ ._\-*])*[^\W\d_](?:[ ._\-*][^\W_])*(?![^\W_]))"
    r"(?:[^\W_][ ._\-*]){3,}[^\W_](?![^\W_])"
)


@dataclass
class Views:
    raw: str
    light: str
    norm: str


def is_mixed_script(token):
    return bool(LATIN_RE.search(token) and FOREIGN_LOOKALIKE_RE.search(token))


LEET_INSIDE_RE = re.compile(r"[a-z][013457@$]+[a-z]", re.I)
# a leading digit standing for a letter: '1gnore', '0utput'; '$' and '@' never start a leet word
LEET_LEADING_RE = re.compile(r"^[013457][a-z]{4,}", re.I)
EMAIL_OR_URL_RE = re.compile(r"\w@\w+\.\w|://|^www\.", re.I)
BASE64_RE = re.compile(r"(?<![A-Za-z0-9+/])(?=[A-Za-z0-9+/]*[0-9+/A-Z])[A-Za-z0-9+/]{20,}={0,2}")

# digits leetspeak does not use: a token holding one is a version, hash or identifier
NON_LEET_DIGIT_RE = re.compile(r"[2689]")
# punctuation inside a token: path, identifier, version number, IP address, assignment
IDENTIFIER_RE = re.compile(r"[\w$@][_/\\.:=\-+#][\w$@]")
HEX_TOKEN_RE = re.compile(r"^(?=.*\d)(?=.*[a-f])[0-9a-f]{7,}$|^0x[0-9a-f]+$", re.I)
# a number with a unit or ordinal suffix: 3pm, 5th, 24h, 30s, 5min, 4k, 1080p
DIGIT_SUFFIX_RE = re.compile(
    r"^\d+(?:st|nd|rd|th|am|pm|h|hr|hrs|s|sec|secs|m|min|mins|ms|k|kb|mb|gb|tb|g|kg|mg|x|d|w|y|yr|yrs|px|"
    r"pt|cm|mm|km|ml|l|oz|lb|lbs|fps|hz|khz|mhz|ghz|bit|bits|ish|c|f|v|p|mah|mp|dpi|ppi|rpm|mph|kph|kmh)$",
    re.I,
)
# short all-caps product codes and acronyms with one digit or symbol: MH4U, A3XX, T1D, A$AP
# ("L34K" and "RUL3$" hold two, so shouted leetspeak still counts)
PRODUCT_CODE_RE = re.compile(r"^(?=[A-Z]*[0-9$@][A-Z]*$)(?=(?:[^A-Z]*[A-Z]){1,3}[^A-Z]*$)[A-Z0-9$@]{2,6}$")
# numeronyms, tool and product names that read like leetspeak
TECH_TOKENS = frozenset("""
a11y l10n i18n g11n c14n m17n n11n k8s k3s y2k w3c m4a i3 a16z
md5sum sha1sum sha224sum sha256sum sha384sum sha512sum b2sum log4j log4net log4js log4shell
1password 4chan 3blue1brown c3po r2d2 s3fs s3cmd h264 h265 x264 x265 mp3tag i3wm i3status
win32api p3p e2e b2b b2c p2p m2m o365 b3lyp 3ds 7zip 5g 4g 3g 1st 3rd py3k d3js web3js 0day
""".split())


def _core(token):
    return token.strip(".,;:!?\"'()[]{}")


def is_technical(core):
    """An identifier, path, version, hash, numeronym or tool name: never leetspeak."""
    return bool(
        len(core) > 20 or EMAIL_OR_URL_RE.search(core) or NON_LEET_DIGIT_RE.search(core)
        or IDENTIFIER_RE.search(core) or HEX_TOKEN_RE.match(core) or PRODUCT_CODE_RE.match(core)
        or core.lower() in TECH_TOKENS
    )


def is_leet(token):
    """A word with leet characters standing in for letters, e.g. 'pr3vious', '1gnore'.

    Ordinary tokens such as '3pm', '15th', 'mp3', '$HOME', '@name', 'md5sum', 'log4j', 'a11y',
    version numbers, hashes, paths and email addresses do not count. '$' and '@' only stand
    for letters inside a word, never at its start.
    """
    core = _core(token)
    if is_technical(core):
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


def _printable(data):
    """Decoded bytes as text when they are printable ASCII (code, a URL, JSON), else None.

    Random bytes, as a hash or an identifier gives, are almost never 90% printable.
    """
    try:
        plain = data.decode("utf-8")
    except UnicodeDecodeError:
        return None
    if len(plain) >= 8 and sum(32 <= ord(c) < 127 or c in "\n\t\r" for c in plain) / len(plain) >= 0.9:
        return plain
    return None


def _decode_bytes(run, kind):
    try:
        if kind == "base64":
            return base64.b64decode(run + "=" * (-len(run) % 4), validate=True)
        return bytes.fromhex(re.sub(r"\\x|[ :]", "", run))
    except (binascii.Error, ValueError):
        return None


def _decode_base64(match, accept=_readable):
    data = _decode_bytes(match.group(0), "base64")
    return (accept(data) if data is not None else None) or match.group(0)


def _decode_hex(match, accept=_readable):
    data = _decode_bytes(match.group(0), "hex")
    return (accept(data) if data is not None else None) or match.group(0)


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


def decoded_runs(text, accept=_readable):
    """The text hidden in base64 and hex runs: readable prose, or with `accept=printable_text`
    also code, URLs and JSON (for counting; only prose replaces the run in the norm view)."""
    found = []
    for pattern, decode in ((BASE64_RE, _decode_base64), (HEX_RE, _decode_hex)):
        for match in pattern.finditer(text):
            plain = decode(match, accept)
            if plain != match.group(0):
                found.append(plain)
    return found


printable_text = _printable


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
    """In a text that clearly uses leetspeak: any word mixing letters and leet characters."""
    core = _core(token)
    return not is_technical(core) and any(c.isalpha() for c in core) and any(c in LEET_CHARS for c in core)


def _wordlike(token):
    """Three or more characters with at least two letters: '0bey' and 'pr3sent', not 's3' or 'm3'."""
    core = _core(token)
    return len(core) >= 3 and sum(c.isalpha() for c in core) >= 2


def _unit_like(token):
    """A number with a unit or ordinal: '3pm', '5th', '24h'. Only a clearly leet text decodes these."""
    return bool(DIGIT_SUFFIX_RE.match(_core(token)))


def _deobfuscate_token(token, leet_text, decode_units):
    if is_mixed_script(token):
        token = token.translate(HOMOGLYPHS)
    if is_leet(token) or (leet_text and _could_be_leet(token) and (decode_units or not _unit_like(token))):
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
    # once a text clearly uses leetspeak, short words such as "7h3" and "0bey" are decoded too:
    # two leet words, or one leet word and another word-like candidate ("1gnore ... and 0bey");
    # a lone typo next to "3pm" or "s3" is not enough
    strong = sum(is_leet(p) for p in parts)
    candidates = [p for p in parts if _could_be_leet(p) and not _unit_like(p)]
    leet_text = strong >= 2 or (strong == 1 and sum(_wordlike(p) for p in candidates) >= 2)
    return "".join(p if p.isspace() else _deobfuscate_token(p, leet_text, strong >= 2) for p in parts)


def hidden_readings(text):
    """Everything a text hides: decoded runs, reassembled payloads, rot13/reversed readings."""
    text = ZERO_WIDTH_RE.sub("", text)
    return decoded_runs(text) + reassemble_split_parts(text)[:1] + alternate_readings(text)


def make_views(text):
    return Views(raw=text, light=light_normalize(text), norm=normalize(text))
