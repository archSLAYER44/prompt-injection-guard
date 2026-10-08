"""Round-six gate: compare every candidate of the run trees with the round-four champion. Report only.

    .venv/bin/python scripts/gate_round6.py --round 7              # the round's trees -> report/round7_gate.{txt,json}
    .venv/bin/python scripts/gate_round6.py --trees r1_rules       # a subset
    .venv/bin/python scripts/gate_round6.py --self-check           # backup_round4's own pickle as the candidate: must equal the champion
    .venv/bin/python scripts/gate_round6.py --promote r1_rules/emb+rules20   # attended: copy the decided candidate into the live tree

Rules fixed before the run (report/round_six_results.md): `src.gate.passes()` with TOLERANCE = 0 on POOLED,
RECENT and probe_dev (probe misses strictly lower); the six round-four source development splits are printed
but never binding; tie-break among passers: fewest total mistakes on the six gate sets, then fewer probe
misses, then run order r1, r2, r3, then emb+rules20 before emb+rules16. Each candidate is scored by a
subprocess inside its own tree, so the rules.py it was trained with computes its features. The default mode
copies nothing; only --promote writes into the live tree, and only the decided candidate.
"""
import argparse
import hashlib
import json
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import numpy as np
import pandas as pd

from src.gate import (BACKUP, CHAMPION_PICKLE, GROUPS, PREFERENCE, PROBE, TOLERANCE, champion_verdicts,
                      mistakes, passes, side_by_side)
from src.dataset import load_dev_sets
from src.train import output_paths

ROUNDS = {
    6: {"runs": "round6", "trees": ["r1_rules", "r2_data", "r3_rules_data"], "gate": "round_six_gate", "records": "round_six"},
    7: {"runs": "round7", "trees": ["r1_rules", "r7_rules_drafted"], "gate": "round7_gate", "records": "round7"},
}
RUNS = ROOT / "rounds" / "round6"                      # reset by configure()
TREE_ORDER = ROUNDS[6]["trees"]                        # also the run order of the tie-break
REPORT_ONLY = ["wild_dev", "llmail_dev", "gsum_dev", "yanis_dev", "aya_dev", "dolly_dev"]
BAR = {"official_dev": (0, 1), "handwritten_dev": (5, 3), "handwritten_dev3": (2, 3),
       "handwritten_dev4": (3, 7), "agent_drafted_dev5": (4, 13), "probe_dev": (12, 24)}
GATE_JSON = ROOT / "report" / "round_six_gate.json"   # reset by configure()
RECORD_DIR = ROOT / "report" / "round_six"
LIVE_PICKLE = ROOT / "src" / "models" / "injection_model.pkl"

CANDIDATE_SCRIPT = """
import json, sys
import joblib
from src.predict import score_texts
model = joblib.load(sys.argv[1])
texts = json.load(open(sys.argv[2], encoding="utf-8"))
decisions, _ = score_texts(model, texts, cache_name="all")
json.dump({"threshold": float(model["threshold"]), "feature_set": model["feature_set"],
           "params": model["params"], "training_units": int(model["training_units"]),
           "rule_names": list(model["rule_names"]), "scores": [float(d) for d in decisions]},
          open(sys.argv[3], "w"))
"""


def configure(round_number):
    """Point the module at one round's trees and record files."""
    global RUNS, TREE_ORDER, GATE_JSON, RECORD_DIR
    spec = ROUNDS[round_number]
    RUNS = ROOT / "rounds" / spec["runs"]
    TREE_ORDER = spec["trees"]
    GATE_JSON = ROOT / "report" / f"{spec['gate']}.json"
    RECORD_DIR = ROOT / "report" / spec["records"]


def rule_text():
    tol = " + TOLERANCE" if TOLERANCE else ""
    clauses = [f"{label}: false alarms <= champion's{tol}, missed " + ("strictly lower" if strict else f"<= champion's{tol}")
               for label, _, strict in GROUPS]
    return f"pass = every group passes (TOLERANCE = {TOLERANCE}): " + "; ".join(clauses) + ". The six source splits are report only."


def sha1(path, n=12):
    return hashlib.sha1(Path(path).read_bytes()).hexdigest()[:n]


def score_in_tree(tree, pickle, dev_sets):
    """Decision values of one candidate on every text, computed by the tree's own code."""
    texts = [t for frame in dev_sets.values() for t in frame["text"]]
    with tempfile.TemporaryDirectory() as folder:
        in_path, out_path = Path(folder) / "texts.json", Path(folder) / "scores.json"
        in_path.write_text(json.dumps(texts), encoding="utf-8")
        subprocess.run([sys.executable, "-c", CANDIDATE_SCRIPT, str(pickle), str(in_path), str(out_path)],
                       cwd=tree, check=True)
        result = json.loads(out_path.read_text())
    scores, offset = {}, 0
    for name, frame in dev_sets.items():
        scores[name] = np.array(result["scores"][offset:offset + len(frame)])
        offset += len(frame)
    assert offset == len(result["scores"])
    result["scores"] = scores
    return result


def counts(verdicts, dev_sets):
    return {name: dict(zip(("false_alarms", "missed"), mistakes(verdicts, dev_sets, [name]))) for name in dev_sets}


def group_counts(verdicts, dev_sets):
    out = {}
    for label, names, _ in GROUPS:
        fa, missed = mistakes(verdicts, dev_sets, names)
        out[label] = {"false_alarms": fa, "missed": missed, "total": fa + missed}
    return out


def compact_table(dev_sets, verdicts):
    entries = [(name, [name]) for name in dev_sets] + [(label, names) for label, names, _ in GROUPS if len(names) > 1]
    rows = []
    for label, names in entries:
        row = {"set": label + (" (report only)" if label in REPORT_ONLY else ""),
               "rows": sum(len(dev_sets[n]) for n in names if n in dev_sets)}
        for model, model_verdicts in verdicts.items():
            fa, missed = mistakes(model_verdicts, dev_sets, names)
            row[model] = f"{fa} / {missed}"
        rows.append(row)
    return pd.DataFrame(rows)


def check_bar(champion, dev_sets):
    off = {name: (mistakes(champion, dev_sets, [name]), bar) for name, bar in BAR.items()
           if name in dev_sets and mistakes(champion, dev_sets, [name]) != bar}
    if off:
        sys.exit(f"the champion's recomputed counts differ from the frozen bar: {off}. "
                 f"The gate stops; fix the cause (report/champion_dev_scores.csv, backup_round4/) and rerun.")
    print("champion counts equal the frozen bar on every gate set")


def gate(trees, candidate_override=None, write=True):
    dev_sets = load_dev_sets()
    gate_names = [name for _, names, _ in GROUPS for name in names]
    missing = [name for name in gate_names if name not in dev_sets]
    if missing:
        sys.exit(f"gate sets missing from load_dev_sets(): {missing}")
    dev_sets = {name: dev_sets[name] for name in gate_names + REPORT_ONLY if name in dev_sets}
    print(f"sets: {', '.join(f'{n} ({len(f)})' for n, f in dev_sets.items())}")

    verdicts = {"champion": champion_verdicts(dev_sets, output_paths(False)["champion"])}
    check_bar(verdicts["champion"], dev_sets)

    candidates = []
    for tree in trees:
        pickles = ([("champion-pickle", Path(candidate_override))] if candidate_override else
                   [(name, tree / "src" / "models" / "candidates" / f"{name}.pkl") for name in PREFERENCE])
        for name, pickle in pickles:
            if not pickle.exists():
                print(f"warning: {pickle} is missing (did the run finish?); skipped")
                continue
            cid = f"{tree.name}/{name}"
            started = time.time()
            result = score_in_tree(tree, pickle, dev_sets)
            verdicts[cid] = {n: (s >= result["threshold"]).astype(int) for n, s in result["scores"].items()}
            print(f"scored {cid}: threshold {result['threshold']:.3f}, {time.time() - started:.0f} s")
            candidates.append({
                "id": cid, "tree": str(tree), "pickle": str(pickle), "pickle_sha1": sha1(pickle),
                "rules_sha1": sha1(tree / "src" / "rules.py"),
                "new_train_md5": hashlib.md5((tree / "data" / "new_train.csv").read_bytes()).hexdigest(),
                "threshold": result["threshold"], "params": result["params"],
                "training_units": result["training_units"], "feature_set": result["feature_set"],
                "counts": counts(verdicts[cid], dev_sets), "groups": group_counts(verdicts[cid], dev_sets),
                "total_mistakes": sum(sum(mistakes(verdicts[cid], dev_sets, [n])) for n in gate_names),
                "probe_missed": mistakes(verdicts[cid], dev_sets, [PROBE])[1],
                "passes": passes(verdicts["champion"], verdicts[cid], dev_sets),
                "scores": {n: [round(float(x), 4) for x in s] for n, s in result["scores"].items()},
            })

    print(f"\n=== Round-six gate: round-four champion ({BACKUP.name}) against {len(candidates)} candidate(s), "
          f"development data only ===")
    pd.set_option("display.width", 1000)
    pd.set_option("display.max_columns", 40)
    print(side_by_side(dev_sets, verdicts).to_string(index=False))
    print("\ncompact (false alarms / missed attacks):")
    print(compact_table(dev_sets, verdicts).to_string(index=False))
    print("\n" + rule_text())
    for c in candidates:
        print(f"  {c['id']}: {'PASS' if c['passes'] else 'fail'}  "
              f"(total {c['total_mistakes']}, probe missed {c['probe_missed']}, threshold {c['threshold']:.3f})")

    tree_rank = {name: i for i, name in enumerate(TREE_ORDER)}
    pref_rank = {name: i for i, name in enumerate(PREFERENCE)}
    passers = [c for c in candidates if c["passes"]]
    decision = None
    if passers:
        key = lambda c: (c["total_mistakes"], c["probe_missed"],
                         tree_rank.get(c["id"].split("/")[0], 99), pref_rank.get(c["id"].split("/")[1], 99))
        decision = min(passers, key=key)["id"]
        print(f"\ntie-break (fewest total mistakes, fewer probe misses, run order, preference) over "
              f"{[c['id'] for c in passers]}")
        print(f"DECISION: promote {decision}")
    else:
        print("\nDECISION: none passed; round four stays")

    if write:
        record = {
            "written": time.strftime("%Y-%m-%d %H:%M:%S %z"), "tolerance": TOLERANCE,
            "groups": [{"label": label, "sets": names, "strict": strict} for label, names, strict in GROUPS],
            "report_only": [n for n in REPORT_ONLY if n in dev_sets],
            "sets": {name: len(frame) for name, frame in dev_sets.items()},
            "champion": {"name": BACKUP.name, "pickle_sha1": sha1(CHAMPION_PICKLE),
                         "counts": counts(verdicts["champion"], dev_sets),
                         "groups": group_counts(verdicts["champion"], dev_sets)},
            "candidates": candidates, "passers": [c["id"] for c in passers],
            "rule": rule_text(),
            "tie_break": ["fewest total mistakes over the six gate sets", "fewer probe_dev misses",
                          "run order " + ", ".join(TREE_ORDER), "emb+rules20 before emb+rules16"],
            "decision": decision,
        }
        GATE_JSON.write_text(json.dumps(record, indent=2), encoding="utf-8")
        print(f"wrote {GATE_JSON}")
    return decision, verdicts, dev_sets


def self_check():
    """The backup's own pickle scored as a candidate inside backup_round4 must reproduce the champion exactly."""
    decision, verdicts, dev_sets = gate([BACKUP], candidate_override=CHAMPION_PICKLE, write=False)
    cid = f"{BACKUP.name}/champion-pickle"
    same = all(np.array_equal(verdicts["champion"][n], verdicts[cid][n]) for n in dev_sets)
    # a candidate identical to the champion fails a strict group (misses not lower) and passes a non-strict one
    expected = None if any(strict for _, _, strict in GROUPS) else cid
    ok = same and decision == expected
    print(f"\nSELF-CHECK {'OK' if ok else 'FAILED'}: candidate verdicts {'equal' if same else 'differ from'} "
          f"the champion's on every set; decision {decision!r} (expected {expected!r} under the current GROUPS)")
    sys.exit(0 if ok else 1)


def promote(target, force):
    if not GATE_JSON.exists():
        sys.exit(f"{GATE_JSON} not found: run the gate first")
    record = json.loads(GATE_JSON.read_text(encoding="utf-8"))
    if record["decision"] != target:
        message = f"the gate's decision is {record['decision']!r}, not {target!r}"
        if not force:
            sys.exit(message + "; refusing (use --force only with a written reason)")
        print(f"WARNING: {message}; --force given")
    tree_name, name = target.split("/")
    tree = RUNS / tree_name
    candidate = next(c for c in record["candidates"] if c["id"] == target)
    pickle = Path(candidate["pickle"])
    if sha1(pickle) != candidate["pickle_sha1"]:
        sys.exit(f"{pickle} changed since the gate ran")
    if sha1(LIVE_PICKLE) != sha1(CHAMPION_PICKLE):
        sys.exit("the live pickle is not round four's (differs from backup_round4's); refusing to overwrite")
    for required in ("metrics.json", "train_log.txt"):
        if not (BACKUP / "report" / required).exists():
            sys.exit(f"backup_round4/report/{required} missing: round four would not be recoverable")

    shutil.copy2(pickle, LIVE_PICKLE)
    print(f"copied {pickle} -> {LIVE_PICKLE}")
    live_rules, tree_rules = ROOT / "src" / "rules.py", tree / "src" / "rules.py"
    if live_rules.read_bytes() != tree_rules.read_bytes():
        if tree_name == "r2_data":
            sys.exit("r2_data's rules.py differs from the live one, which the design forbids; stopping")
        shutil.copy2(tree_rules, live_rules)
        shutil.copy2(tree / "scripts" / "check_rules.py", ROOT / "scripts" / "check_rules.py")
        print("copied the tree's src/rules.py and scripts/check_rules.py into the live tree")
    else:
        print("rules.py unchanged (round four's)")
    tree_train, live_train = tree / "data" / "new_train.csv", ROOT / "data" / "new_train.csv"
    if tree_train.read_bytes() != live_train.read_bytes():
        kept = ROOT / "data" / "new_train_round5.csv"
        if not kept.exists():
            shutil.copy2(live_train, kept)
            print(f"kept the live (nine-source) new_train.csv as {kept.name}")
        shutil.copy2(tree_train, live_train)
        print("copied the tree's data/new_train.csv (the promoted model's training data) over the live one; "
              "new_test.csv stays (its extra sources are test sets)")
    for extra in sorted((tree / "data").glob("drafted_*.csv")):
        shutil.copy2(extra, ROOT / "data" / extra.name)
        print(f"copied the tree's {extra.name} into data/")
    for item in ("metrics.json", "train_log.txt"):
        shutil.copy2(tree / "report" / item, ROOT / "report" / item)
        print(f"copied {tree.name}/report/{item} -> report/{item} (round four's stay in backup_round4/report/)")
    RECORD_DIR.mkdir(exist_ok=True)
    for other in TREE_ORDER:
        for item, suffix in (("metrics.json", "_metrics.json"), ("train_log.txt", "_train_log.txt")):
            source = RUNS / other / "report" / item
            if source.exists():
                shutil.copy2(source, RECORD_DIR / f"{other}{suffix}")
    print(f"copied every tree's metrics and log to {RECORD_DIR}/")
    print(f"\nnext: .venv/bin/python scripts/check_rules.py && "
          f".venv/bin/python scripts/score_tests.py --tree {tree_name} --ablation")


def main():
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--round", type=int, default=7, choices=sorted(ROUNDS))
    parser.add_argument("--trees", help="comma-separated tree names under rounds/round<N>/ (default: the round's trees)")
    parser.add_argument("--self-check", action="store_true")
    parser.add_argument("--promote", metavar="TREE/CANDIDATE")
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args()
    configure(args.round)
    if args.trees is None:
        args.trees = ",".join(TREE_ORDER)
    if args.self_check:
        self_check()
    elif args.promote:
        promote(args.promote, args.force)
    else:
        trees = [RUNS / name for name in args.trees.split(",")]
        for tree in trees:
            if not (tree / "src").is_dir():
                sys.exit(f"{tree} is not a run tree")
        gate(trees)


if __name__ == "__main__":
    main()
