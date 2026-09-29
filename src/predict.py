"""The one prediction function. The CLI and the GUI both call predict()."""
import math
from functools import lru_cache
from pathlib import Path

import joblib
import numpy as np

from .pipeline import extract
from .rules import DESCRIPTIVE_RULES, analyze, fired
from .windows import split_units

MODEL_PATH = Path(__file__).resolve().parent / "models" / "injection_model.pkl"
MAX_WINDOWS = 64
MAX_SENTENCES = 128


@lru_cache(maxsize=1)
def load_model():
    if not MODEL_PATH.exists():
        raise FileNotFoundError(f"{MODEL_PATH} not found. Train it first: python -m src.train")
    return joblib.load(MODEL_PATH)


def _sigmoid(x):
    return 1.0 / (1.0 + math.exp(-max(-50.0, min(50.0, x))))


def predict(text):
    """Classify one text.

    Returns a dict with:
      verdict        "injection" or "benign"
      confidence     0.5 to 1.0, how far the text sits from the decision threshold
      probability    calibrated probability that the text is an injection
      features       all 16 rule values for the most suspicious part of the text
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
    features = extract(model["feature_set"], windows, model["view"])
    decisions = model["pipeline"].decision_function(features)
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
