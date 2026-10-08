"""Score distribution of the training data, for the dashboard's "where does this score sit" panel.

Default: out-of-fold scores on the grouped folds, the approach of scripts/oof_floor_check.py: every
training text is scored by a fold model that did not see it, with the promoted setting (emb+rules20,
linear SVC, C=0.3, rule weight 1.0). This is NOT the frozen model's in-sample score, which would look
unrealistically clean. The frozen model file is never written.

    .venv/bin/python scripts/export_score_distribution.py                         # fresh out-of-fold run (slow)
    .venv/bin/python scripts/export_score_distribution.py --from-csv report/round_four_scores/oof_grouped_folds_emb+rules20.csv
    .venv/bin/python scripts/export_score_distribution.py --official-test         # fallback: held-out official test set, final model

Writes report/score_distribution.json (or --out): the score scale (min, max, threshold, on the real
decision-value scale that predict() thresholds and explain() returns), 40 density bins per class,
201 quantiles per class for percentile lookup, counts per class and source, the date generated.
"""
import argparse
import json
import sys
import time
import warnings
from datetime import date
from pathlib import Path

import numpy as np
import pandas as pd

warnings.filterwarnings("ignore")
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

BINS = 40
QUANTILES = np.linspace(0, 100, 201)
PARAMS = {"svc__kernel": "linear", "svc__C": 0.3, "features__rules__weight__weight": 1.0}


def model_threshold():
    from src.predict import load_model
    return float(load_model()["threshold"])


def compute_out_of_fold():
    from src.train import build_corpus, make_folds, originals, out_of_fold
    corpus = build_corpus(with_tests=True)
    folds = make_folds(corpus)
    print(f"grouped folds: {len(folds[1])}; fitting one model per fold ...", flush=True)
    (_, by_group), = out_of_fold(corpus, "emb+rules20", [PARAMS], ([], folds[1]), n_jobs=-1).values()
    oof = originals(by_group)
    return oof, ("out-of-fold scores of the training data: grouped folds, emb+rules20, linear SVC C=0.3, "
                 "rule weight 1.0; one score per original text, from a fold model that did not see it")


def from_csv(path):
    frame = pd.read_csv(path, keep_default_na=False)
    if "kind" in frame.columns:
        frame = frame[frame["kind"] == "original"]
    return frame, (f"out-of-fold scores of the training data read from {Path(path).as_posix()} "
                   "(grouped folds, emb+rules20, linear SVC C=0.3, rule weight 1.0; one score per original text)")


def official_test():
    from src.predict import load_model, score_texts
    frame = pd.read_csv(ROOT / "data" / "injection_test.csv", keep_default_na=False)
    scores, _ = score_texts(load_model(), frame["text"].tolist(), cache_name="embeddings")
    frame = frame.assign(score=scores)
    if "source" not in frame.columns:
        frame["source"] = "official_test"
    return frame, "FALLBACK: the held-out official test set scored by the final frozen model (not out-of-fold training scores)"


def build(frame, source, threshold):
    frame = frame[["label", "score"] + (["source"] if "source" in frame.columns else [])].copy()
    frame["label"] = frame["label"].astype(int)
    frame["score"] = frame["score"].astype(float)
    benign = np.sort(frame.loc[frame["label"] == 0, "score"].to_numpy())
    attack = np.sort(frame.loc[frame["label"] == 1, "score"].to_numpy())
    low, high = float(min(benign.min(), attack.min())), float(max(benign.max(), attack.max()))
    edges = np.linspace(low, high, BINS + 1)
    dens_b, _ = np.histogram(benign, bins=edges, density=True)
    dens_a, _ = np.histogram(attack, bins=edges, density=True)
    r = lambda values: [round(float(v), 4) for v in values]
    out = {
        "generated": date.today().isoformat(),
        "source": source,
        "scale": {"name": "SVM decision value: the 'score' explain() returns and the value predict() compares with the threshold",
                  "min": round(low, 4), "max": round(high, 4), "threshold": round(threshold, 4)},
        "counts": {"benign": int(len(benign)), "injection": int(len(attack))},
        "at_threshold": {"benign_above_pct": round(100 * float((benign >= threshold).mean()), 2),
                         "injection_below_pct": round(100 * float((attack < threshold).mean()), 2)},
        "bins": {"edges": r(edges), "benign": r(dens_b), "injection": r(dens_a)},
        "quantiles": {"percent": r(QUANTILES), "benign": r(np.percentile(benign, QUANTILES)),
                      "injection": r(np.percentile(attack, QUANTILES))},
    }
    if "source" in frame.columns:
        out["by_source"] = {k: {"benign": int(v.get(0, 0)), "injection": int(v.get(1, 0))}
                            for k, v in frame.groupby("source")["label"].value_counts().unstack(fill_value=0).iterrows()}
    return out


def main():
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--from-csv", help="reuse an existing out-of-fold score file instead of recomputing")
    parser.add_argument("--official-test", action="store_true", help="fallback: score the held-out official test set with the final model")
    parser.add_argument("--out", default=str(ROOT / "report" / "score_distribution.json"))
    parser.add_argument("--save-csv", help="also save the per-text scores here (fresh runs)")
    args = parser.parse_args()

    started = time.time()
    if args.from_csv:
        frame, source = from_csv(args.from_csv)
    elif args.official_test:
        frame, source = official_test()
    else:
        frame, source = compute_out_of_fold()
        if args.save_csv:
            frame.to_csv(args.save_csv, index=False)
    data = build(frame, source, model_threshold())
    Path(args.out).write_text(json.dumps(data, indent=1))
    c, s, t = data["counts"], data["scale"], data["at_threshold"]
    print(f"wrote {args.out} in {time.time() - started:.0f}s")
    print(f"  source: {source}")
    print(f"  benign {c['benign']}, injection {c['injection']}; score scale {s['min']} to {s['max']}, threshold {s['threshold']}")
    print(f"  at the threshold: {t['benign_above_pct']}% of benign scores are above it (false alarms), "
          f"{t['injection_below_pct']}% of injection scores are below it (misses)")


if __name__ == "__main__":
    main()
