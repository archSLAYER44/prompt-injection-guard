"""Check a held-out set for exact and near copies of training rows before it is scored.

    .venv/bin/python scripts/check_set6_overlap.py /path/to/set6.csv [--against data/drafted_train7.csv ...] [--out report/set6_overlap.json]

Compares every row of the held-out CSV (text,label,category) with (a) each --against file and (b) the whole training
pool the live loaders give (`src.dataset.load_pool()`), by exact dedup key (`src.dataset.dedup_key`) and by char
n-gram tf-idf cosine similarity at `src.dataset.NEAR_DUP_THRESHOLD`. Prints every hit with its nearest training row and
writes a JSON summary (hits per file, the flagged held-out row indexes) so a score can be reported with and without
the flagged rows. It changes nothing. Run it only once a candidate is promoted: until then the held-out set is sealed.
"""
import argparse
import json
import sys
import time
from pathlib import Path

import pandas as pd
from sklearn.feature_extraction.text import TfidfVectorizer

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from src.dataset import NEAR_DUP_THRESHOLD, dedup_key, load_pool  # noqa: E402


def compare(held, texts, label):
    """Exact and near copies of `held` rows among `texts`; returns a frame of hits."""
    keys = set(texts.map(dedup_key))
    vec = TfidfVectorizer(analyzer="char_wb", ngram_range=(3, 5), min_df=1)
    matrix = vec.fit_transform(pd.concat([texts, held["text"]], ignore_index=True))
    sims = (matrix[len(texts):] @ matrix[:len(texts)].T).toarray()
    best = sims.argmax(axis=1)
    hits = []
    for i, row in held.reset_index(drop=True).iterrows():
        exact = dedup_key(row["text"]) in keys
        sim = float(sims[i, best[i]])
        if exact or sim >= NEAR_DUP_THRESHOLD:
            hits.append({"held_out_index": int(i), "label": int(row["label"]), "category": row.get("category", ""),
                         "exact": bool(exact), "similarity": round(sim, 3), "against": label,
                         "nearest": " ".join(str(texts.iloc[best[i]]).split())[:120],
                         "held_out": " ".join(row["text"].split())[:120]})
    return hits, float(sims.max()) if sims.size else 0.0


def main():
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("held_out", type=Path)
    parser.add_argument("--against", type=Path, nargs="*", default=[])
    parser.add_argument("--out", type=Path, default=ROOT / "report" / "set6_overlap.json")
    args = parser.parse_args()

    held = pd.read_csv(args.held_out, dtype=str, keep_default_na=False, encoding="utf-8")
    held["label"] = held["label"].astype(int)
    print(f"{args.held_out}: {len(held)} rows ({int((held['label'] == 1).sum())} attacks)")
    summary = {"held_out": str(args.held_out), "rows": len(held), "threshold": NEAR_DUP_THRESHOLD,
               "checked_at": time.strftime("%Y-%m-%d %H:%M:%S %z"), "comparisons": [], "hits": []}
    sources = []
    for path in args.against:
        frame = pd.read_csv(path, dtype=str, keep_default_na=False, encoding="utf-8")
        sources.append((str(path.relative_to(ROOT)) if path.is_absolute() and ROOT in path.parents else str(path),
                        frame["text"].astype(str)))
    pool = load_pool()
    sources.append(("training pool (load_pool)", pool["text"].astype(str)))
    for label, texts in sources:
        hits, top = compare(held, texts, label)
        summary["comparisons"].append({"against": label, "rows": int(len(texts)), "hits": len(hits), "highest_similarity": round(top, 3)})
        summary["hits"].extend(hits)
        print(f"against {label} ({len(texts)} rows): {len(hits)} exact or near copies, highest similarity {top:.3f}")
        for h in hits:
            kind = "EXACT" if h["exact"] else f"{h['similarity']:.2f}"
            print(f"  row {h['held_out_index']} (label {h['label']}, {h['category']}) {kind}: "
                  f"{h['held_out']!r} ~ {h['nearest']!r}")
    summary["flagged_rows"] = sorted({h["held_out_index"] for h in summary["hits"]})
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(summary, indent=2), encoding="utf-8")
    print(f"flagged held-out rows: {summary['flagged_rows'] or 'none'}; wrote {args.out}")


if __name__ == "__main__":
    main()
