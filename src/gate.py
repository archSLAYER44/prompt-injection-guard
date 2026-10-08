"""Decide which model becomes src/models/injection_model.pkl, on development data only.

    python -m src.gate            compare the saved candidates with the round-four model, promote one
    python -m src.gate --smoke    a few texts per set, scratch folders, promotes nothing

The champion is the live model's frozen copy (backup_round7/ since round eight; backup_round4/ in rounds four to
seven), run by its own code (a subprocess); its verdicts
are cached in report/champion_dev_scores.csv under the backup's name, so a cache from another round is
never reused. A candidate passes when EVERY group passes: POOLED (official_dev + handwritten_dev +
handwritten_dev3) and RECENT (hand-written set 4 + agent-drafted set 5, development data since their
mistakes were read): false alarms plus missed attacks not higher than the champion's and neither count
higher by more than TOLERANCE; probe_dev: the same (its "missed attacks strictly lower" clause of rounds four to
six was dropped for round seven, 2026-10-05, before the run). TOLERANCE = 1 was
added on 2026-10-01 (report/round_four_results.md) and used in rounds four and five; round six set it to 0
before its run (report/round_six_results.md: nothing may be worse than round four). The RECENT group was
added for round five, in writing, before any round-five code (report/round_five_results.md). Candidates are
tried in order of preference; the first that passes is promoted. If none passes, the champion pickle is kept
and the round-four code must be restored from the backup. Round six does not call run_gate(): its three
runs are gated by scripts/gate_round6.py, which reuses champion_verdicts(), passes() and side_by_side().
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
BACKUP = ROOT / "backup_round7"   # round eight (2026-10-08): the champion is the live round-seven model; rounds
                                  # four to seven gated against backup_round4
CHAMPION_PICKLE = BACKUP / "src" / "models" / "injection_model.pkl"
PREFERENCE = ["emb+rules20", "emb+rules16"]
POOLED = ["official_dev", "handwritten_dev", "handwritten_dev3"]
RECENT = ["handwritten_dev4", "agent_drafted_dev5", "agent_drafted_dev6"]   # sets 4, 5 and 6: development data since
                                                                            # their mistakes were read (set 6 added for round eight, 2026-10-08)
PROBE = "probe_dev"
# (label, sets, missed attacks must be strictly lower); every group must pass
# PROBE was strict (missed attacks strictly lower) in rounds four to six; round seven set it to False on
# 2026-10-05, before its run: the user's rule is "nothing worse than the champion, gains optional"
# (report/round_seven_results.md). Round six's rule-fixes candidate had failed only that clause (24 = 24).
GROUPS = [("POOLED", POOLED, False), ("RECENT", RECENT, False), ("PROBE", [PROBE], False)]
HIDDEN_TEXT = {PROBE}           # cached by hash only, so the file does not spell the probe out
SMOKE_ROWS = 6
TOLERANCE = 0                   # round six, decided 2026-10-04 before the run: no count may be worse than the
                                # champion's. Rounds four and five used 1 (added 2026-10-01; the first gate had
                                # none and failed by one false alarm).

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
    """Verdicts of the champion, computed by its own code in the backup folder."""
    if not CHAMPION_PICKLE.exists():
        raise FileNotFoundError(f"{CHAMPION_PICKLE} not found: the champion backup is missing")
    with tempfile.TemporaryDirectory() as folder:
        in_path, out_path = Path(folder) / "texts.json", Path(folder) / "verdicts.json"
        in_path.write_text(json.dumps(texts), encoding="utf-8")
        subprocess.run([sys.executable, "-c", CHAMPION_SCRIPT, str(in_path), str(out_path)],
                       cwd=BACKUP, check=True)
        return json.loads(out_path.read_text())


def champion_verdicts(dev_sets, cache_path):
    """Champion verdict per development text, from the cache or freshly computed and cached."""
    columns = ["set", "key", "text", "label", "predicted", "probability", "champion"]
    cache = pd.read_csv(cache_path, keep_default_na=False) if cache_path.exists() \
        else pd.DataFrame(columns=columns)
    if "champion" not in cache.columns:              # a cache from before round five: never reuse it
        cache = pd.DataFrame(columns=columns)
    cache = cache[cache["champion"] == BACKUP.name].reset_index(drop=True)
    have = set(zip(cache["set"], cache["key"]))
    todo = [(name, text_key(text), text, label)
            for name, frame in dev_sets.items()
            for text, label in zip(frame["text"], frame["label"])
            if (name, text_key(text)) not in have]
    if todo:
        print(f"scoring {len(todo)} development texts with the champion ({BACKUP.name})...", flush=True)
        results = run_champion([text for _, _, text, _ in todo])
        rows = [{"set": name, "key": key, "text": "" if name in HIDDEN_TEXT else text,
                 "label": int(label), **result, "champion": BACKUP.name}
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
    """Every group: total mistakes not higher than the champion's and neither count higher by more than
    TOLERANCE; where `strict`, the missed attacks must also be lower. A missing set fails the gate."""
    for _, names, strict in GROUPS:
        if any(name not in dev_sets for name in names):
            return False
        c_fa, c_missed = mistakes(candidate, dev_sets, names)
        k_fa, k_missed = mistakes(champion, dev_sets, names)
        missed_ok = c_missed < k_missed if strict else c_missed <= k_missed + TOLERANCE
        if not (c_fa + c_missed <= k_fa + k_missed and c_fa <= k_fa + TOLERANCE and missed_ok):
            return False
    return True


def side_by_side(dev_sets, verdicts):
    """One table: false alarms and missed attacks per set and per model."""
    rows = []
    groups = [(name, [name]) for name in dev_sets] + [(f"{label} " + "+".join(names), names)
                                                       for label, names, _ in GROUPS if len(names) > 1]
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
    gate_names = [name for _, names, _ in GROUPS for name in names]
    for name in gate_names:
        if name not in dev_sets:
            print(f"warning: {name} is missing, so no candidate can pass the gate")
    dev_sets = {name: dev_sets[name] for name in gate_names if name in dev_sets}   # the champion is scored on these only

    candidates = {name: paths["candidates"] / f"{name}.pkl" for name in PREFERENCE}
    candidates = {name: path for name, path in candidates.items() if path.exists()}
    if not candidates:
        print(f"no candidates found in {paths['candidates']}")
    verdicts = {"champion": champion_verdicts(dev_sets, paths["champion"])}
    for name, path in candidates.items():
        verdicts[name] = candidate_verdicts(joblib.load(path), dev_sets)

    print(f"\n=== Gate: champion ({BACKUP.name}) against the candidates (development data only) ===")
    pd.set_option("display.width", 250)
    print(side_by_side(dev_sets, verdicts).to_string(index=False))
    print(f"pass = POOLED and RECENT: total mistakes not higher than the champion's, neither count higher by "
          f"more than {TOLERANCE}; probe_dev: the same, and missed attacks lower; every group must pass")

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
        print(f"no candidate passed: the round-four model stays at {paths['model']}. "
              f"Restore the champion's code from {BACKUP}/src so that the code matches the model.")
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
