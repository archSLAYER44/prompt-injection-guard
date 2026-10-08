"""Merge the round-seven drafted training chunks into one training CSV and check them.

    .venv/bin/python scripts/merge_drafted.py <chunk dir> <out csv> [--source drafted7]

Reads <chunk dir>/chunk*.csv (columns text,label,category,language,technique). Checks: the columns; labels 0/1;
no empty text; 20 to 450 words (characters / 2 for zh, ja, ko); language codes the loaders know (src.dataset
LANGUAGE_CODES values or ''); no override words in label-1 rows outside encoded_payload (same regex as
scripts/merge_set.py); duplicates inside the set (src.dataset.dedup_key); exact and near copies (char n-gram
tf-idf cosine >= src.dataset.NEAR_DUP_THRESHOLD) of any row of any data/*.csv. Rows that are exact or near
copies of a held-out file (anything other than the four training files) are DROPPED and listed; near copies
of a training file are reported and kept (the pool's own dedup decides). Writes
text,label,category,technique,language,source (extra_train.csv's column order, QUOTE_ALL) and prints the
per-chunk, per-category and per-label tallies. It reads only the chunk files and data/*.csv.
"""
import argparse
import csv
import re
import sys
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.feature_extraction.text import TfidfVectorizer

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from src.dataset import LANGUAGE_CODES, NEAR_DUP_THRESHOLD, dedup_key  # noqa: E402

COLUMNS = ["text", "label", "category", "language", "technique"]
OUT_COLUMNS = ["text", "label", "category", "technique", "language", "source"]
TRAINING_FILES = {"injection_train.csv", "extra_train.csv", "contrast_train.csv", "new_train.csv"}
# the words the drafting briefs banned in attack rows (merge_set.py's list also bans "previous", "prior" and
# "instructions" on their own, which the briefs allowed in phrases like "the instructions it was given")
OVERRIDE_WORDS = re.compile(r"\b(ignore|disregard|forget|override|previous instructions|prior instructions|"
                            r"system prompt|jailbreak|you are now)\b", re.I)
OVERRIDE_EXEMPT = {"encoded_payload"}
MIN_WORDS, MAX_WORDS = 20, 450
CJK = {"zh", "ja", "ko"}


def word_count(text, language):
    return len(text) // 2 if language in CJK else len(text.split())


def main():
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("chunk_dir", type=Path)
    parser.add_argument("out", type=Path)
    parser.add_argument("--source", default="drafted7")
    args = parser.parse_args()

    known_codes = set(LANGUAGE_CODES.values()) | {""}
    frames, problems = [], []
    for path in sorted(args.chunk_dir.glob("chunk*.csv")):
        frame = pd.read_csv(path, dtype=str, keep_default_na=False, encoding="utf-8")
        if list(frame.columns) != COLUMNS:
            problems.append(f"{path.name}: columns {list(frame.columns)}")
            continue
        frame["chunk"] = path.stem
        frames.append(frame)
    if problems:
        sys.exit("bad chunk files:\n  " + "\n  ".join(problems))
    rows = pd.concat(frames, ignore_index=True)
    print(f"{len(frames)} chunk files, {len(rows)} rows")

    for i, r in rows.iterrows():
        if r["label"] not in {"0", "1"}:
            problems.append(f"{r['chunk']}: label {r['label']!r}")
        if not r["text"].strip():
            problems.append(f"{r['chunk']}: empty text")
        n = word_count(r["text"], r["language"])
        if not MIN_WORDS <= n <= MAX_WORDS:
            problems.append(f"{r['chunk']}: {n} words: {r['text'][:60]!r}")
        if r["language"] not in known_codes:
            problems.append(f"{r['chunk']}: unknown language {r['language']!r}")
        if r["label"] == "1" and r["category"] not in OVERRIDE_EXEMPT and OVERRIDE_WORDS.search(r["text"]):
            problems.append(f"{r['chunk']}: override word in attack: {OVERRIDE_WORDS.search(r['text']).group(0)!r} in {r['text'][:60]!r}")
    if problems:
        print("PROBLEMS:\n  " + "\n  ".join(problems))
        sys.exit(1)

    rows["key"] = rows["text"].map(dedup_key)
    dup = rows[rows["key"].duplicated(keep=False)]
    if len(dup):
        print(f"duplicates inside the set: {len(dup)} rows")
        for _, r in dup.iterrows():
            print(f"  {r['chunk']} label {r['label']}: {r['text'][:70]!r}")
        sys.exit(1)

    # exact and near copies of any data/*.csv row
    corpus = []
    for path in sorted((ROOT / "data").glob("*.csv")):
        try:
            other = pd.read_csv(path, dtype=str, keep_default_na=False, encoding="utf-8", usecols=["text"])
        except ValueError:
            continue
        corpus.append(pd.DataFrame({"text": other["text"].astype(str), "file": path.name}))
    corpus = pd.concat(corpus, ignore_index=True)
    corpus["key"] = corpus["text"].map(dedup_key)
    exact = rows["key"].isin(set(corpus["key"]))
    vec = TfidfVectorizer(analyzer="char_wb", ngram_range=(3, 5), min_df=1)
    matrix = vec.fit_transform(pd.concat([corpus["text"], rows["text"]], ignore_index=True))
    sims = (matrix[len(corpus):] @ matrix[:len(corpus)].T).toarray()
    best = sims.argmax(axis=1)
    rows["near_file"] = corpus["file"].to_numpy()[best]
    rows["near_sim"] = sims[np.arange(len(rows)), best]
    rows["near"] = (rows["near_sim"] >= NEAR_DUP_THRESHOLD) | exact
    held_out_hit = rows["near"] & ~rows["near_file"].isin(TRAINING_FILES)
    train_hit = rows["near"] & rows["near_file"].isin(TRAINING_FILES)
    print(f"near or exact copies: {int(rows['near'].sum())} ({int(held_out_hit.sum())} of a held-out file, dropped; "
          f"{int(train_hit.sum())} of a training file, kept)")
    for _, r in rows[rows["near"]].iterrows():
        print(f"  {'DROP' if r['near_file'] not in TRAINING_FILES else 'keep'} {r['chunk']} label {r['label']} "
              f"~ {r['near_file']} ({r['near_sim']:.2f}): {r['text'][:70]!r}")
    print(f"highest similarity to any existing row: {rows['near_sim'].max():.3f} ({rows.loc[rows['near_sim'].idxmax(), 'near_file']})")
    kept = rows[~held_out_hit].copy()

    kept["source"] = args.source
    kept["label"] = kept["label"].astype(int)
    print("\nper chunk (label 0 / label 1):")
    tally = kept.groupby(["chunk", "label"]).size().unstack(fill_value=0)
    print(tally.to_string())
    print("\nper category:")
    print(kept.groupby(["category", "label"]).size().unstack(fill_value=0).to_string())
    print("\nper language:")
    print(kept.groupby(["language", "label"]).size().unstack(fill_value=0).to_string())
    print(f"\ntotal kept: {len(kept)} ({int((kept['label'] == 1).sum())} attacks, {int((kept['label'] == 0).sum())} benign)")

    args.out.parent.mkdir(parents=True, exist_ok=True)
    kept[OUT_COLUMNS].to_csv(args.out, index=False, quoting=csv.QUOTE_ALL, encoding="utf-8")
    print(f"wrote {args.out}")


if __name__ == "__main__":
    main()
