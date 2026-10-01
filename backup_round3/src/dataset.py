"""Load the project CSVs and check them before training.

Run the report from the project root:
    python -m src.dataset
"""
import re
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.feature_extraction.text import TfidfVectorizer

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"

TRAIN_CSV = DATA / "injection_train.csv"
TEST_CSV = DATA / "injection_test.csv"
EXTRA_TRAIN_CSV = DATA / "extra_train.csv"
EXTRA_TEST_CSV = DATA / "extra_test.csv"
CONTRAST_CSV = DATA / "contrast_train.csv"            # written by scripts/make_contrast_set.py
HANDWRITTEN_DEV_CSVS = [DATA / "handwritten_dev.csv", DATA / "handwritten_dev2.csv"]
HANDWRITTEN_CSV = DATA / "handwritten_test.csv"
OFFICIAL_DEV_SHARE = 0.4

NEAR_DUP_THRESHOLD = 0.90   # cosine similarity on char n-gram TF-IDF
SKEW_THRESHOLD = 0.60       # majority class share that counts as skewed


def load(path):
    df = pd.read_csv(path, keep_default_na=False)
    missing = {"text", "label"} - set(df.columns)
    if missing:
        raise ValueError(f"{path.name} is missing columns: {missing}")
    df["text"] = df["text"].astype(str)
    df["label"] = df["label"].astype(int)
    return df


def load_train():
    """Official train split of the main dataset."""
    return load(TRAIN_CSV)


def load_test():
    """Official test split of the main dataset, with a `half` column.

    The training split does not contain the attack wording used in the test split, so
    part of the test split is set aside for development. The split is by payload: every
    copy of an instruction lands in the same half, so the final half holds wording that
    development never saw.
    """
    test = load(TEST_CSV)
    groups = test["text"].map(payload_group)
    rng = np.random.default_rng(7)
    test["half"] = "final"
    for _, part in test.groupby("category"):
        names = sorted(groups[part.index].unique())
        rng.shuffle(names)
        dev = set(names[:max(1, round(OFFICIAL_DEV_SHARE * len(names)))])
        test.loc[part.index[groups[part.index].isin(dev)], "half"] = "dev"
    return test


def load_dev_sets():
    """Sets used while improving the model. Never trained on, but not a fair final test."""
    test = load_test()
    sets = {"official_dev": test[test["half"] == "dev"].reset_index(drop=True)}
    written = [load(path) for path in HANDWRITTEN_DEV_CSVS if path.exists()]
    if written:
        sets["handwritten_dev"] = pd.concat(written, ignore_index=True).assign(source="handwritten")
    return sets


def load_tests():
    """Held-out test sets, by name. Never trained on and never used to make a decision."""
    test = load_test()
    tests = {"official": test[test["half"] == "final"].reset_index(drop=True)}
    extra = load(EXTRA_TEST_CSV)
    for source, frame in extra.groupby("source"):
        tests[source] = frame.reset_index(drop=True)
    if HANDWRITTEN_CSV.exists():
        tests["handwritten"] = load(HANDWRITTEN_CSV).assign(source="handwritten")
    return tests


def held_out_sets():
    return {**load_dev_sets(), **load_tests()}


def load_pool():
    """All training rows from every source, minus duplicates and anything held out."""
    parts = [load_train(), load(EXTRA_TRAIN_CSV)]
    if CONTRAST_CSV.exists():
        parts.append(load(CONTRAST_CSV))
    pool = pd.concat(parts, ignore_index=True)
    pool = pool[pool["text"].str.strip() != ""]
    keys = pool["text"].map(dedup_key)

    held_out = pd.concat(held_out_sets().values(), ignore_index=True)
    pool = pool[~keys.isin(set(held_out["text"].map(dedup_key))) & ~keys.duplicated()]
    pool = pool.reset_index(drop=True)

    # some sources publish near-copies of one prompt on both sides of their split
    tfidf = TfidfVectorizer(analyzer="char_wb", ngram_range=(3, 5), sublinear_tf=True)
    held_m = tfidf.fit_transform(held_out["text"])
    leaked = _similarity_max(tfidf.transform(pool["text"]), held_m, same=False) >= NEAR_DUP_THRESHOLD
    return pool[~leaked].reset_index(drop=True)


def dedup_key(text):
    """Lowercase, drop punctuation, collapse whitespace."""
    text = re.sub(r"[^\w\s]", " ", text.lower())
    return re.sub(r"\s+", " ", text).strip()


LEAD_IN_RE = re.compile(r"^[\w .']{1,25}?[,:]\s+")


def payload_group(text):
    """Grouping key for validation splits: the last sentence without its lead-in.

    The main dataset reuses one instruction across many carrier documents. Splitting by
    this key keeps every copy of an instruction on the same side of the split.
    """
    from .augment import split_tail

    _, tail, _ = split_tail(text)
    tail = LEAD_IN_RE.sub("", tail.strip().lower())
    return re.sub(r"[^a-z ]", "", tail).strip()


def class_balance(df):
    counts = df["label"].value_counts().sort_index()
    share = counts / counts.sum()
    return pd.DataFrame({"count": counts, "share": share.round(3)}).rename(
        index={0: "benign (0)", 1: "injection (1)"}
    )


def _similarity_max(left, right, same):
    best = np.zeros(left.shape[0])
    for start in range(0, left.shape[0], 500):
        sims = (left[start:start + 500] @ right.T).toarray()
        if same:
            rows = np.arange(sims.shape[0])
            sims[rows, start + rows] = 0.0   # ignore self-similarity
        best[start:start + 500] = sims.max(axis=1)
    return best


def near_duplicate_stats(texts, threshold=NEAR_DUP_THRESHOLD):
    """Mark rows that have at least one other row above the similarity threshold."""
    tfidf = TfidfVectorizer(analyzer="char_wb", ngram_range=(3, 5), sublinear_tf=True)
    matrix = tfidf.fit_transform(texts)
    return _similarity_max(matrix, matrix, same=True) >= threshold


def cross_split_overlap(train, test, threshold=NEAR_DUP_THRESHOLD):
    """Test rows that are exact or near copies of a train row (leakage)."""
    exact = test["text"].map(dedup_key).isin(set(train["text"].map(dedup_key)))
    tfidf = TfidfVectorizer(analyzer="char_wb", ngram_range=(3, 5), sublinear_tf=True)
    train_m = tfidf.fit_transform(train["text"])
    near = _similarity_max(tfidf.transform(test["text"]), train_m, same=False) >= threshold
    return exact.to_numpy(), near


def report(name, df):
    print(f"\n=== {name}: {len(df)} rows ===")
    balance = class_balance(df)
    print(balance.to_string())
    if balance["share"].max() > SKEW_THRESHOLD:
        print(f"  FLAG: skewed, majority class is {balance['share'].max():.0%}")

    keys = df["text"].map(dedup_key)
    twins = near_duplicate_stats(df["text"])
    print(f"exact duplicate rows:            {int(df['text'].duplicated().sum())}")
    print(f"duplicates after normalization:  {int(keys.duplicated().sum())}")
    print(f"rows with a near-duplicate (cosine >= {NEAR_DUP_THRESHOLD}): "
          f"{int(twins.sum())} ({twins.mean():.0%})")
    if twins.mean() > 0.30:
        print("  FLAG: heavily near-duplicated")

    conflicts = df.assign(key=keys).groupby("key")["label"].nunique()
    print(f"same text with both labels:      {int((conflicts > 1).sum())}")

    by = ["source", "label"] if df["source"].nunique() > 1 else ["label", "category"]
    table = df.assign(twin=twins).groupby(by).agg(
        rows=("twin", "size"), near_dup=("twin", "mean"),
        median_chars=("text", lambda s: s.str.len().median()))
    print(table.round(2).to_string())


def main():
    pool = load_pool()
    report("TRAINING POOL (all sources, official train splits)", pool)

    for name, test in held_out_sets().items():
        report(f"HELD OUT: {name}", test)
        exact, near = cross_split_overlap(pool, test)
        print(f"test rows identical to a training row:      {int(exact.sum())}")
        print(f"test rows near-identical to a training row: {int(near.sum())} ({near.mean():.0%})")

    train, test = load_train(), load_test()
    print("\nofficial test split, rows per half:")
    print(test.groupby(["half", "label"]).size().unstack(fill_value=0).to_string())
    seen = set(train["category"])
    print(f"\nmain dataset, categories only in test:  {sorted(set(test['category']) - seen)}")
    print(f"main dataset, categories only in train: {sorted(seen - set(test['category']))}")


if __name__ == "__main__":
    main()
