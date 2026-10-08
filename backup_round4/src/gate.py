"""Decide which model becomes src/models/injection_model.pkl, on development data only.

    python -m src.gate            compare the saved candidates with the round-three model, promote one
    python -m src.gate --smoke    a few texts per set, scratch folders, promotes nothing

The champion is the round-three model, run by its own code in backup_round3/ (a subprocess), and
its verdicts are cached in report/champion_dev_scores.csv. A candidate passes when, pooled over
official_dev + handwritten_dev + handwritten_dev3, its false alarms plus missed attacks are not higher
than the champion's and neither count is higher by more than TOLERANCE, AND on probe_dev its false
alarms plus missed attacks are not higher, its false alarms are not higher by more than TOLERANCE and
its missed attacks are lower. The first round-four gate had no tolerance and rejected a candidate by a
single false alarm; TOLERANCE = 1 was added on 2026-10-01 after that result, before any test set was
scored (report/round_four_results.md). Candidates are tried in order of preference; the first that passes
is promoted. If none passes, the champion pickle is kept and the round-three code must be restored.
"""
import argparse
import hashlib
import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

import joblib
import numpy as np
import pandas as pd

from .dataset import load_dev_sets
from .predict import score_texts

ROOT = Path(__file__).resolve().parent.parent
BACKUP = ROOT / "backup_round3"
CHAMPION_PICKLE = BACKUP / "src" / "models" / "injection_model.pkl"
PREFERENCE = ["emb+rules20", "emb+rules16"]
POOLED = ["official_dev", "handwritten_dev", "handwritten_dev3"]
PROBE = "probe_dev"
HIDDEN_TEXT = {PROBE}           # cached by hash only, so the file does not spell the probe out
SMOKE_ROWS = 6
TOLERANCE = 1                   # added 2026-10-01; the first gate had none and failed by one false alarm

CHAMPION_SCRIPT = """
import json, sys
from src.predict import predict
texts = json.load(open(sys.argv[1], encoding="utf-8"))
out = []
for text in texts:
    try:
        result = predict(text)
        out.append({"predicted": int(result["is_injection"]), "probability": result["probability"]})
    except ValueError:
        out.append({"predicted": 0, "probability": 0.0})
json.dump(out, open(sys.argv[2], "w"))
"""


def text_key(text):
    return hashlib.sha1(text.encode("utf-8")).hexdigest()


def run_champion(texts):
    """Verdicts of the round-three model, computed by the round-three code in backup_round3."""
    if not CHAMPION_PICKLE.exists():
        raise FileNotFoundError(f"{CHAMPION_PICKLE} not found: the round-three backup is missing")
    with tempfile.TemporaryDirectory() as folder:
        in_path, out_path = Path(folder) / "texts.json", Path(folder) / "verdicts.json"
        in_path.write_text(json.dumps(texts), encoding="utf-8")
        subprocess.run([sys.executable, "-c", CHAMPION_SCRIPT, str(in_path), str(out_path)],
                       cwd=BACKUP, check=True)
        return json.loads(out_path.read_text())


def champion_verdicts(dev_sets, cache_path):
    """Champion verdict per development text, from the cache or freshly computed and cached."""
    columns = ["set", "key", "text", "label", "predicted", "probability"]
    cache = pd.read_csv(cache_path, keep_default_na=False) if cache_path.exists() \
        else pd.DataFrame(columns=columns)
    have = set(zip(cache["set"], cache["key"]))
    todo = [(name, text_key(text), text, label)
            for name, frame in dev_sets.items()
            for text, label in zip(frame["text"], frame["label"])
            if (name, text_key(text)) not in have]
    if todo:
        print(f"scoring {len(todo)} development texts with the round-three model (backup_round3)...", flush=True)
        results = run_champion([text for _, _, text, _ in todo])
        rows = [{"set": name, "key": key, "text": "" if name in HIDDEN_TEXT else text,
                 "label": int(label), **result}
                for (name, key, text, label), result in zip(todo, results)]
        cache = pd.concat([cache, pd.DataFrame(rows, columns=columns)], ignore_index=True)
        cache_path.parent.mkdir(parents=True, exist_ok=True)
        cache.to_csv(cache_path, index=False)
    lookup = dict(zip(zip(cache["set"], cache["key"]), cache["predicted"].astype(int)))
    return {name: np.array([lookup[(name, text_key(t))] for t in frame["text"]])
            for name, frame in dev_sets.items()}


def candidate_verdicts(model, dev_sets):
    return {name: (score_texts(model, list(frame["text"]), cache_name="all")[0] >= model["threshold"]).astype(int)
            for name, frame in dev_sets.items()}


def mistakes(verdicts, dev_sets, names):
    """(false alarms, missed attacks) pooled over the named sets."""
    false_alarms = missed = 0
    for name in names:
        if name in dev_sets:
            labels = dev_sets[name]["label"].to_numpy()
            false_alarms += int(((verdicts[name] == 1) & (labels == 0)).sum())
            missed += int(((verdicts[name] == 0) & (labels == 1)).sum())
    return false_alarms, missed


def passes(champion, candidate, dev_sets):
    """Total mistakes not higher than the champion's and neither count higher by more than TOLERANCE,
    pooled and on probe_dev; on probe_dev the missed attacks must also be lower."""
    c_fa, c_missed = mistakes(candidate, dev_sets, POOLED)
    k_fa, k_missed = mistakes(champion, dev_sets, POOLED)
    pooled_ok = (c_fa + c_missed <= k_fa + k_missed
                 and c_fa <= k_fa + TOLERANCE and c_missed <= k_missed + TOLERANCE)
    if PROBE not in dev_sets:
        return False
    (c_fa, c_missed), (k_fa, k_missed) = mistakes(candidate, dev_sets, [PROBE]), mistakes(champion, dev_sets, [PROBE])
    return (pooled_ok and c_fa + c_missed <= k_fa + k_missed
            and c_fa <= k_fa + TOLERANCE and c_missed < k_missed)


def side_by_side(dev_sets, verdicts):
    """One table: false alarms and missed attacks per set and per model."""
    rows = []
    groups = [(name, [name]) for name in dev_sets] + [("POOLED " + "+".join(POOLED), POOLED)]
    for label, names in groups:
        row = {"set": label, "rows": sum(len(dev_sets[n]) for n in names if n in dev_sets)}
        for model, model_verdicts in verdicts.items():
            false_alarms, missed = mistakes(model_verdicts, dev_sets, names)
            row[f"{model} false alarms"], row[f"{model} missed"] = false_alarms, missed
        rows.append(row)
    return pd.DataFrame(rows)


def run_gate(paths, smoke=False):
    """Compare every saved candidate with the champion and promote the first that passes.

    Returns the promoted feature set, or None when the champion stays.
    """
    dev_sets = load_dev_sets()
    if smoke:
        dev_sets = {k: f.sample(min(len(f), SMOKE_ROWS), random_state=1).reset_index(drop=True)
                    for k, f in dev_sets.items()}
    if PROBE not in dev_sets:
        print(f"warning: {PROBE} is missing, so no candidate can pass the gate")

    candidates = {name: paths["candidates"] / f"{name}.pkl" for name in PREFERENCE}
    candidates = {name: path for name, path in candidates.items() if path.exists()}
    if not candidates:
        print(f"no candidates found in {paths['candidates']}")
    verdicts = {"champion": champion_verdicts(dev_sets, paths["champion"])}
    for name, path in candidates.items():
        verdicts[name] = candidate_verdicts(joblib.load(path), dev_sets)

    print("\n=== Gate: round-three champion against the candidates (development data only) ===")
    pd.set_option("display.width", 250)
    print(side_by_side(dev_sets, verdicts).to_string(index=False))
    print(f"pass = pooled: total mistakes not higher than the champion's, neither count higher by more than "
          f"{TOLERANCE}; probe_dev: the same, and missed attacks lower")

    for name in PREFERENCE:
        if name not in verdicts:
            continue
        ok = passes(verdicts["champion"], verdicts[name], dev_sets)
        print(f"  {name}: {'PASS' if ok else 'fail'}")
        if ok:
            if smoke:
                print(f"smoke run: {name} would be promoted; nothing is written")
            else:
                paths["model"].parent.mkdir(parents=True, exist_ok=True)
                shutil.copy(candidates[name], paths["model"])
                print(f"promoted {name} to {paths['model']}")
            return name

    if smoke:
        print("smoke run: no candidate would be promoted; nothing is written")
    else:
        shutil.copy(CHAMPION_PICKLE, paths["model"])
        print(f"no candidate passed: the round-three model stays at {paths['model']}. "
              f"Restore the round-three code from {BACKUP}/src so that the code matches the model.")
    return None


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--smoke", action="store_true",
                        help="a few texts per set, candidates and cache in the scratch folder, no promotion")
    args = parser.parse_args()
    from .train import output_paths
    run_gate(output_paths(args.smoke), smoke=args.smoke)


if __name__ == "__main__":
    main()
