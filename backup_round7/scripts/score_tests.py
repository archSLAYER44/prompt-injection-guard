"""Score the held-out test sets ONCE for the promoted model, exactly as `python -m src.train --final` would have.

    .venv/bin/python scripts/score_tests.py --round 7 --tree r7_rules_drafted [--ablation] [--force] \\
        | tee -a report/train_log.txt report/round_six_tests.txt

Reproduces the block after the gate in src/train.py main(): build_corpus(with_tests=True), held_out_report() on
the test role with the live pickle's pipeline and threshold, the same printed tables, check_standards(), and
the same keys merged into report/metrics.json ("tests", "standards", "official_by_category", "promoted").
--ablation then runs the development-only ablation (every feature set tuned on the grouped folds) and stores it
under "ablation", which the notebook and the charts expect. It refuses to run when metrics.json already has
"tests" or the marker report/ROUND6_TESTS_SCORED.json exists, so the test sets are scored once per round.
The live src/rules.py computes the corpus features, so with --tree it must equal the tree's rules.py, and the
live pickle must equal the tree's candidate.
"""
import argparse
import hashlib
import json
import sys
import time
import warnings
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

METRICS = ROOT / "report" / "metrics.json"
RUNS = ROOT / "rounds"          # / round<N>, from --round


def sha1(path, n=12):
    return hashlib.sha1(Path(path).read_bytes()).hexdigest()[:n]


def main():
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--round", type=int, default=7)
    parser.add_argument("--tree", help="run tree the promoted candidate came from (name under rounds/round<N>/)")
    parser.add_argument("--ablation", action="store_true", help="also run the development-only ablation")
    parser.add_argument("--force", action="store_true", help="score again even though a record exists")
    args = parser.parse_args()

    MARKER = ROOT / "report" / f"ROUND{args.round}_TESTS_SCORED.json"
    metrics = json.loads(METRICS.read_text(encoding="utf-8"))
    if ("tests" in metrics or MARKER.exists()) and not args.force:
        sys.exit(f"{METRICS} already holds test scores or {MARKER.name} exists: the test sets are scored once "
                 f"per round. Copy the promoted run's metrics.json into report/ first (gate_round6.py --promote).")

    import pandas as pd
    from src.pipeline import FEATURE_SETS
    from src.predict import MODEL_PATH, load_model
    from src.train import (EXTERNAL_SETS, NEW_SETS, ablation_row, ablation_table, build_corpus, check_standards,
                           held_out_report, make_folds, print_mistakes, print_scores)

    model = load_model()
    feature_set, pipeline, threshold = model["feature_set"], model["pipeline"], float(model["threshold"])
    entry = metrics.get("candidates", {}).get(feature_set)
    if entry is None:
        sys.exit(f"metrics.json has no candidate {feature_set!r}: it is not the promoted run's file")
    if abs(float(entry["threshold"]) - threshold) > 1e-9 or metrics.get("params") != model["params"]:
        sys.exit(f"metrics.json (threshold {entry['threshold']}, params {metrics.get('params')}) does not match the "
                 f"live pickle (threshold {threshold}, params {model['params']})")
    tree = None
    if args.tree:
        tree = RUNS / f"round{args.round}" / args.tree
        candidate = tree / "src" / "models" / "candidates" / f"{feature_set}.pkl"
        if sha1(MODEL_PATH) != sha1(candidate):
            sys.exit(f"the live pickle is not {candidate}")
        if sha1(ROOT / "src" / "rules.py") != sha1(tree / "src" / "rules.py"):
            sys.exit(f"the live src/rules.py differs from {tree}/src/rules.py: the corpus features would not be the "
                     f"model's. Promote first (gate_round6.py --promote).")

    warnings.filterwarnings("ignore")
    pd.set_option("display.width", 250)
    pd.set_option("display.max_columns", 30)
    started = time.time()
    print(f"\n=== scripts/score_tests.py {time.strftime('%Y-%m-%d %H:%M:%S')}: {feature_set}, threshold {threshold:.3f}, "
          f"pickle sha1 {sha1(MODEL_PATH)}, rules sha1 {sha1(ROOT / 'src' / 'rules.py')}"
          f"{f', tree {tree.name}' if tree else ''} ===")
    corpus = build_corpus(with_tests=True)
    print(f"corpus built in {time.time() - started:.0f} s (the training pool is the live data; only test units are scored)")

    report, table, frame = held_out_report(corpus, feature_set, pipeline, threshold, "test")
    print(f"\n=== Final model ({feature_set}) on the held-out test sets ===")
    for name in ["official"] + EXTERNAL_SETS + ["external"] + NEW_SETS + ["external_new", "handwritten"]:
        if name in report:
            print_scores(name.upper(), report[name])
    print("\nofficial test (final half) by category (correct_share = recall for attacks):")
    print(table.round(3).to_string(index=False))
    print_mistakes(frame, "handwritten")
    _, rows = check_standards(report)
    metrics.update({"tests": report, "standards": rows, "official_by_category": table.to_dict("records")})
    metrics["promoted"] = feature_set
    metrics[f"round{args.round}"] = {"tree": tree.name if tree else None, "pickle_sha1": sha1(MODEL_PATH),
                         "rules_sha1": sha1(ROOT / "src" / "rules.py"),
                         "tests_scored_at": time.strftime("%Y-%m-%d %H:%M:%S %z"),
                         "test_sets": sorted(k for k in report if isinstance(report[k], dict))}

    if args.ablation:
        started = time.time()
        folds = make_folds(corpus)
        ablation = [ablation_row(corpus, fs, folds, -1) for fs in FEATURE_SETS]
        print(f"\n=== Ablation on the development sets ({time.time() - started:.0f} s; live training pool) ===")
        print(ablation_table(ablation))
        metrics["ablation"] = ablation

    METRICS.write_text(json.dumps(metrics, indent=2, default=str), encoding="utf-8")
    MARKER.write_text(json.dumps(metrics[f"round{args.round}"], indent=2), encoding="utf-8")
    print(f"saved metrics to {METRICS}; marker {MARKER.name} written")


if __name__ == "__main__":
    main()
