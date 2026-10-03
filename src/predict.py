"""The one prediction function. The CLI and the GUI both call predict()."""
import math
import re
from functools import lru_cache
from pathlib import Path

import joblib
import numpy as np

from .pipeline import extract
from .rules import DESCRIPTIVE_RULES, analyze, fired
from .windows import MAX_SENTENCES, MAX_WINDOWS, split_units

# used by explain() only
from .features import EMBEDDING_DIM, EMBEDDING_MODEL, token_count
from .normalize import (
    BASE64_RE, HEX_RE, HOMOGLYPHS, LEET_MAP, REVERSE_HINT_RE, ROT13_HINT_RE, SPACED_LETTERS_RE,
    ZERO_WIDTH_RE, _decode_base64, _decode_hex, alternate_readings, is_leet, is_mixed_script,
    light_normalize, normalize, reassemble_split_parts,
)
from .rules import RULE_NAMES
from .windows import WINDOW_TOKENS

MODEL_PATH = Path(__file__).resolve().parent / "models" / "injection_model.pkl"


@lru_cache(maxsize=1)
def load_model():
    if not MODEL_PATH.exists():
        raise FileNotFoundError(f"{MODEL_PATH} not found. Train it first: python -m src.train")
    return joblib.load(MODEL_PATH)


def _sigmoid(x):
    return 1.0 / (1.0 + math.exp(-max(-50.0, min(50.0, x))))


def features(model, texts, cache_name=None):
    """Feature matrix the way the model was trained: its feature set and its rule columns."""
    return extract(model["feature_set"], texts, model["view"], cache_name,
                   rule_names=model.get("rule_names"))


def score_texts(model, texts, cache_name=None):
    """Decision value of every text (score of its most suspicious piece), for many texts at once.

    Returns (decisions, best_units) where best_units[i] is the (kind, text) pair that scored highest.
    """
    pieces, owner = [], []
    for index, text in enumerate(texts):
        units = split_units(text.strip(), MAX_WINDOWS, MAX_SENTENCES)
        pieces.extend(units)
        owner.extend([index] * len(units))
    decisions = model["pipeline"].decision_function(features(model, [u for _, u in pieces], cache_name))
    owner = np.asarray(owner)
    best = np.full(len(texts), -np.inf)
    top = [None] * len(texts)
    for row, (index, value) in enumerate(zip(owner, decisions)):
        if value > best[index]:
            best[index], top[index] = value, pieces[row]
    return best, top


def predict(text):
    """Classify one text.

    Returns a dict with:
      verdict        "injection" or "benign"
      confidence     0.5 to 1.0, how far the text sits from the decision threshold
      probability    calibrated probability that the text is an injection
      features       every rule value for the most suspicious part of the text
      fired          the rules that triggered, each with its value and matched snippets
      semantic_only  True when the verdict is injection but no rule fired
      segment        the most suspicious part, when the text was split into several parts
      segment_kind   "window", "sentence", or "reading" (text that was hidden, now decoded)
    """
    text = text.strip()
    if not text:
        raise ValueError("the text is empty")

    model = load_model()
    units = split_units(text, MAX_WINDOWS, MAX_SENTENCES)
    windows = [unit for _, unit in units]
    decisions = model["pipeline"].decision_function(features(model, windows))
    top = int(np.argmax(decisions))
    decision = float(decisions[top])

    slope, intercept = model["calibrator"]
    is_injection = decision >= model["threshold"]
    margin = _sigmoid(slope * (decision - model["threshold"]))

    analysis = analyze(windows[top])
    triggered = {
        name: {"value": float(value), "matches": list(dict.fromkeys(snippets))}
        for name, (value, snippets) in fired(analysis).items()
    }
    return {
        "verdict": "injection" if is_injection else "benign",
        "is_injection": bool(is_injection),
        "confidence": margin if is_injection else 1.0 - margin,
        "probability": _sigmoid(slope * decision + intercept),
        "features": {name: float(value) for name, (value, _) in analysis.items()},
        "fired": triggered,
        "semantic_only": bool(is_injection and not triggered),
        "segment": windows[top] if len(windows) > 1 else None,
        "segment_kind": units[top][0],
        "windows": len(windows),
        "descriptive": sorted(DESCRIPTIVE_RULES),
    }


def explain(text, max_chars=300):
    """Every intermediate value behind predict(text), for the dashboard. Read-only.

    It walks the path predict() walks (split_units, features, decision_function, the calibrator,
    the threshold) and reports what it saw. It changes nothing: no model state, no cache, and
    predict() does not call it. The verdict that counts is predict()'s; this one is the same
    computation shown in full.

    Returns a dict with:
      text            the stripped input
      normalization   before (the input), light (NFKC, lowercase, whitespace), after (the norm
                      view the embedding reads), changed, and decoded: what de-obfuscation found,
                      by kind (zero-width characters, base64, hex, split payload, rot13 or
                      reversed, spaced-out letters, look-alike letters, leetspeak), each with
                      found and became
      pieces          every piece scored, in order: index, kind (window, sentence or reading),
                      text and normalized (both cut to max_chars), chars, tokens (None without a
                      tokenizer), score, is_max
      max_piece       index of the highest-scoring piece, the one predict() explains
      rules           the 20 rule values of that piece, in the model's rule order
      fired           the rules that triggered on it, each with its value and matched snippets
      descriptive     rule names that are text statistics rather than triggers
      embedding       model name, vector size, the view embedded, the token limit per piece
      score, threshold, verdict, confidence, probability   as predict() computes them
    """
    text = text.strip()
    if not text:
        raise ValueError("the text is empty")
    model = load_model()

    def cut(value):
        return value if len(value) <= max_chars else value[:max_chars] + "\u2026"

    # 1. normalization: what the norm view decoded, found with the helpers normalize() uses
    clean = ZERO_WIDTH_RE.sub("", text)
    decoded = []
    if clean != text:
        decoded.append({"kind": "zero-width characters",
                        "found": f"{len(text) - len(clean)} character(s)", "became": "removed"})
    for kind, pattern, decode in (("base64", BASE64_RE, _decode_base64), ("hex", HEX_RE, _decode_hex)):
        for match in pattern.finditer(clean):
            plain = decode(match)
            if plain != match.group(0):
                decoded.append({"kind": kind, "found": match.group(0), "became": plain})
    for reading in reassemble_split_parts(clean)[:1]:
        decoded.append({"kind": "split payload", "found": "quoted fragments", "became": reading})
    readings = alternate_readings(clean)
    if readings:
        hints = [name for name, pattern in (("rot13", ROT13_HINT_RE), ("reversed", REVERSE_HINT_RE))
                 if pattern.search(clean)]
        for reading in readings:
            decoded.append({"kind": " or ".join(hints), "found": "text the message asks to decode",
                            "became": reading})
    light = light_normalize(clean)
    for match in SPACED_LETTERS_RE.finditer(light):
        decoded.append({"kind": "spaced-out letters", "found": match.group(0),
                        "became": re.sub(r"[ ._\-*]", "", match.group(0))})
    tokens = light.split()
    lookalike = [token for token in tokens if is_mixed_script(token)]
    if lookalike:
        decoded.append({"kind": "look-alike letters", "found": " ".join(lookalike[:5]),
                        "became": " ".join(token.translate(HOMOGLYPHS) for token in lookalike[:5])})
    leet = [token for token in tokens if is_leet(token)]
    if leet:
        decoded.append({"kind": "leetspeak", "found": " ".join(leet[:5]),
                        "became": " ".join(token.translate(LEET_MAP) for token in leet[:5])})
    norm = normalize(text)

    # 2. every piece, scored the way predict() scores them
    units = split_units(text, MAX_WINDOWS, MAX_SENTENCES)
    piece_texts = [unit for _, unit in units]
    decisions = model["pipeline"].decision_function(features(model, piece_texts))
    top = int(np.argmax(decisions))
    pieces = []
    for index, ((kind, unit), value) in enumerate(zip(units, decisions)):
        piece_norm = normalize(unit)
        pieces.append({"index": index, "kind": kind, "text": cut(unit), "normalized": cut(piece_norm),
                       "chars": len(unit), "tokens": token_count(piece_norm), "score": float(value),
                       "is_max": index == top})

    # 3. the rules of the top piece, as predict() reports them
    analysis = analyze(piece_texts[top])
    rule_names = list(model.get("rule_names") or RULE_NAMES)
    rules = {name: float(analysis[name][0]) for name in rule_names}
    triggered = {
        name: {"value": float(value), "matches": list(dict.fromkeys(snippets))}
        for name, (value, snippets) in fired(analysis).items()
    }

    # 4. the decision, with predict()'s formulas
    decision = float(decisions[top])
    slope, intercept = model["calibrator"]
    threshold = float(model["threshold"])
    is_injection = decision >= threshold
    margin = _sigmoid(slope * (decision - threshold))
    return {
        "text": text,
        "normalization": {"before": text, "light": light, "after": norm, "changed": norm != light,
                          "decoded": decoded},
        "pieces": pieces,
        "max_piece": top,
        "rules": rules,
        "fired": triggered,
        "descriptive": sorted(DESCRIPTIVE_RULES),
        "embedding": {"model": EMBEDDING_MODEL, "dimension": EMBEDDING_DIM, "view": model["view"],
                      "token_limit": WINDOW_TOKENS},
        "score": decision,
        "threshold": threshold,
        "verdict": "injection" if is_injection else "benign",
        "confidence": margin if is_injection else 1.0 - margin,
        "probability": _sigmoid(slope * decision + intercept),
    }
