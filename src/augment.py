"""Training-set augmentation: obfuscated and split copies of existing rows.

The main train split has no obfuscation or payload-split examples, so rules for those
attacks would stay at zero and the SVM could not learn from them. Copies keep the label
of their source row: a benign request written in leetspeak is still benign.
Only training data is augmented; the test sets are never touched.

There are two template sets. During development the model is fitted with set "a" and
checked on copies made with set "b", so the check uses wording it has not seen.
The final model is fitted with both.
"""
import base64
import codecs
import re

import numpy as np
import pandas as pd

INJECTION_RATE = 0.50   # share of injection rows that get an obfuscated copy
BENIGN_RATE = 0.25      # lower: obfuscation is rarer in honest text
MAX_CHARS = 600         # long documents are left alone

TO_LEET = {"i": "1", "o": "0", "e": "3", "a": "4", "s": "5", "t": "7"}
TO_HOMOGLYPH = {"a": "а", "e": "е", "o": "о", "p": "р", "c": "с", "x": "х", "y": "у", "i": "і"}
ZERO_WIDTH = "​"

WRAPPERS = {
    "a": {
        "encoded": [
            "Decode this {name} and do what it says: {code}",
            "The following is {name}. Decode it and follow it: {code}",
            "{code}\nDecode the line above ({name}) and carry it out.",
        ],
        "split": [
            "Let a = '{p1}' and b = '{p2}'. Join a and b, then do what the result says.",
            "x = \"{p1}\"\ny = \"{p2}\"\nConcatenate x and y and follow the combined text.",
            "Part 1: '{p1}'. Part 2: '{p2}'. Combine part 1 and part 2 and act on it.",
        ],
        "separators": [" "],
        "char_share": 0.7,
    },
    "b": {
        "encoded": [
            "Here is a message in {name}: {code}\nWork out what it says, then comply.",
            "{name} input follows. Convert it to plain text and treat it as your task.\n{code}",
            "Please read {code} ({name}) and respond as it asks.",
        ],
        "split": [
            "Take the fragments \"{p1}\" and \"{p2}\". Merge them in order and carry out the sentence.",
            "first: '{p1}'\nsecond: '{p2}'\nRead first followed by second as one request and answer it.",
            "s1 = '{p1}'; s2 = '{p2}'. Treat s1 + s2 as the message.",
        ],
        "separators": ["-", ".", " "],
        "char_share": 0.4,
    },
}

LAST_SENTENCE_RE = re.compile(
    r"^(.*(?:[.!?:]\s+|\n))([^\n]*?[^\s\"'\n][^\n]*?)(\s*(?:\"\"\"|''')?\s*)$", re.S)


def split_tail(text):
    """(head, last sentence, trailing quotes). Obfuscation is applied to the last sentence."""
    match = LAST_SENTENCE_RE.match(text)
    if not match or len(match.group(2).split()) < 3:
        return "", text, ""
    return match.groups()


def _per_word(text, rng, change, word_share):
    words = []
    for word in text.split(" "):
        if sum(c.isalpha() for c in word) >= 4 and rng.random() < word_share:
            word = change(word, rng)
        words.append(word)
    return " ".join(words)


def _swap_chars(table, char_share):
    def change(word, rng):
        return "".join(
            table[c.lower()] if c.lower() in table and rng.random() < char_share else c
            for c in word)
    return change


def leet(text, rng, style):
    return _per_word(text, rng, _swap_chars(TO_LEET, style["char_share"]), word_share=0.7)


def homoglyph(text, rng, style):
    return _per_word(text, rng, _swap_chars(TO_HOMOGLYPH, style["char_share"]), word_share=0.6)


def zero_width(text, rng, style):
    def change(word, rng):
        cut = rng.integers(1, len(word))
        return word[:cut] + ZERO_WIDTH + word[cut:]
    return _per_word(text, rng, change, word_share=0.6)


def spaced(text, rng, style):
    separator = style["separators"][rng.integers(len(style["separators"]))]

    def change(word, rng):
        core = word.rstrip(".,;:!?")
        return separator.join(core) + word[len(core):]
    return _per_word(text, rng, change, word_share=0.4)


def _pick(templates, rng):
    return templates[rng.integers(len(templates))]


def base64_wrap(text, rng, style):
    code = base64.b64encode(text.strip().encode("utf-8")).decode("ascii")
    return _pick(style["encoded"], rng).format(name="base64", code=code)


def hex_wrap(text, rng, style):
    code = text.strip().encode("utf-8").hex(" ")
    return _pick(style["encoded"], rng).format(name="hex", code=code)


def rot13_wrap(text, rng, style):
    return _pick(style["encoded"], rng).format(name="rot13", code=codecs.encode(text.strip(), "rot13"))


def reversed_wrap(text, rng, style):
    return _pick(style["encoded"], rng).format(name="reversed text", code=text.strip()[::-1])


def payload_split(text, rng, style):
    words = text.strip().replace('"', "").replace("'", "").split()
    if len(words) < 2:
        return text
    cut = rng.integers(1, len(words))
    return _pick(style["split"], rng).format(p1=" ".join(words[:cut]), p2=" ".join(words[cut:]))


TECHNIQUES = {
    "leet": leet, "homoglyph": homoglyph, "zero_width": zero_width, "spaced": spaced,
    "base64": base64_wrap, "hex": hex_wrap, "rot13": rot13_wrap, "reversed": reversed_wrap,
    "payload_split": payload_split,
}
# payload splitting is the most common of these in practice, so it is drawn more often
WEIGHTS = {name: (3.0 if name == "payload_split" else 1.0) for name in TECHNIQUES}


def obfuscate(text, technique, rng, templates="a"):
    head, tail, trailer = split_tail(text)
    return head + TECHNIQUES[technique](tail, rng, WRAPPERS[templates]) + trailer


def augment(df, templates="a", seed=42):
    """Obfuscated copies of a sample of rows; `parent` is the index of the source row."""
    rng = np.random.default_rng(seed)
    names = list(TECHNIQUES)
    weights = np.array([WEIGHTS[n] for n in names])
    weights = weights / weights.sum()

    rows = []
    for index, row in df.iterrows():
        rate = INJECTION_RATE if row["label"] == 1 else BENIGN_RATE
        if len(row["text"]) > MAX_CHARS or rng.random() >= rate:
            continue
        technique = names[rng.choice(len(names), p=weights)]
        copy = row.to_dict()
        copy["text"] = obfuscate(row["text"], technique, rng, templates)
        copy["technique"] = f"aug_{technique}"
        copy["parent"] = index
        rows.append(copy)
    return pd.DataFrame(rows)
