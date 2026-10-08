"""Merge agent-drafted chunks into one held-out CSV and check them.

    .venv/bin/python scripts/merge_set.py <chunk dir> <out csv>

Checks: header text,label,category; labels 0/1; duplicates inside the set; exact and near copies (char
n-gram tf-idf cosine >= NEAR_DUP_THRESHOLD) of any row in data/*.csv; and it reports override words per
row for the reviewer. Writes the merged file in the quoting style of the earlier sets. It reads nothing
else, so it is safe to run on a set that has not been scored yet.
"""
import csv
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import pandas as pd
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity
from src.dataset import NEAR_DUP_THRESHOLD, dedup_key

OVERRIDE_WORDS = re.compile(r"\b(ignore|disregard|forget|override|previous|prior|instructions|system prompt|jailbreak)\b", re.I)


def main():
    chunk_dir, out = Path(sys.argv[1]), Path(sys.argv[2])
    frames = []
    for f in sorted(chunk_dir.glob("chunk*.csv")):
        df = pd.read_csv(f, dtype=str, keep_default_na=False, encoding="utf-8")
        assert list(df.columns) == ["text", "label", "category"], (f.name, list(df.columns))
        frames.append(df)
        print(f"{f.name:<48} {len(df)} rows")
    merged = pd.concat(frames, ignore_index=True)
    merged["text"] = merged["text"].str.strip()
    assert merged["label"].isin(["0", "1"]).all(), "labels must be 0/1"
    assert (merged["text"].str.len() > 0).all(), "empty text"
    print(f"\ntotal {len(merged)} rows: {int((merged.label == '1').sum())} injection, {int((merged.label == '0').sum())} benign")
    print(merged.groupby(["label", "category"]).size().to_string())

    keys = merged["text"].map(dedup_key)
    internal = keys.duplicated(keep=False)
    print(f"\nduplicates inside the set: {int(internal.sum())}")
    repo = []
    for f in sorted((ROOT / "data").glob("*.csv")):
        df = pd.read_csv(f, dtype=str, keep_default_na=False, encoding="utf-8")
        if "text" in df.columns:
            repo.append(pd.DataFrame({"text": df["text"].astype(str), "file": f.name}))
    repo = pd.concat(repo, ignore_index=True)
    repo = repo[repo.text.str.len() > 0].reset_index(drop=True)
    exact = keys.isin(set(repo["text"].map(dedup_key)))
    print(f"exact copies of a row in data/*.csv ({len(repo)} rows checked): {int(exact.sum())}")
    tfidf = TfidfVectorizer(analyzer="char_wb", ngram_range=(3, 5), sublinear_tf=True)
    repo_m = tfidf.fit_transform(repo["text"])
    sims = cosine_similarity(tfidf.transform(merged["text"]), repo_m)
    best, best_sim = sims.argmax(axis=1), sims.max(axis=1)
    near = best_sim >= NEAR_DUP_THRESHOLD
    print(f"near copies (cosine >= {NEAR_DUP_THRESHOLD}): {int(near.sum())}")
    for i in merged.index[near]:
        print(f"  sim {best_sim[i]:.2f}  {merged.text[i][:80]}  ~  {repo.file[best[i]]}: {repo.text[best[i]][:80]}")
    print("highest similarity to any repo row:", round(float(best_sim.max()), 2))

    print("\noverride words per attack row (for the reviewer; the chunk briefs limited them):")
    for i in merged.index[merged.label == "1"]:
        hits = sorted({h.lower() for h in OVERRIDE_WORDS.findall(merged.text[i])})
        print(f"  {merged.category[i]:<36} {('HIT ' + ','.join(hits)) if hits else 'clean':<34} {merged.text[i][:60]}")
    merged[["text", "label", "category"]].to_csv(out, index=False, quoting=csv.QUOTE_ALL, encoding="utf-8")
    print(f"\nwrote {out} ({len(merged)} rows)")


if __name__ == "__main__":
    main()
