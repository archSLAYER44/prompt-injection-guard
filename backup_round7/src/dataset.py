"""Load the project CSVs and check them before training.

Run the report from the project root:
    python -m src.dataset
"""
import re
import unicodedata
from collections import Counter
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
NEW_TRAIN_CSV = DATA / "new_train.csv"                # written by scripts/download_new_sources.py
NEW_TEST_CSV = DATA / "new_test.csv"
DRAFTED_TRAIN_CSV = DATA / "drafted_train7.csv"    # round seven: agent-drafted attacks with harmless twins (training only)
HANDWRITTEN_DEV_CSVS = [DATA / "handwritten_dev.csv", DATA / "handwritten_dev2.csv"]
HANDWRITTEN_DEV3_CSV = DATA / "handwritten_dev3.csv"  # the round-three final set, now development data
PROBE_DEV_CSV = DATA / "probe_dev.csv"                # written independently of the rules
HANDWRITTEN_CSV = None                                # round five: set 6 is scored after promotion by scripts/score_set.py
HANDWRITTEN_DEV4_CSV = DATA / "handwritten_test4.csv"      # the round-four final set, development data since 2026-10-01
AGENT_DRAFTED_DEV5_CSV = DATA / "agent_drafted_test5.csv"  # scored once on 2026-10-03, development data since
ROUND4_NEW_SOURCES = {"wild", "llmail", "gsum", "yanis", "aya", "dolly"}   # their test splits are development data since round five
OFFICIAL_DEV_SHARE = 0.4
COLUMNS = ["text", "label", "category", "technique", "language", "source"]

# sources that share a style are held out together, so a fold cannot lean on a sibling source
FAMILIES = {"jackhhao": "jailbreak", "wild": "jailbreak", "gandalf": "gandalf", "gsum": "gandalf",
            "yanis": "multilingual", "aya": "multilingual",
            "injecagent": "indirect", "bipia": "indirect"}   # oasst1 is its own family

# the sources name languages two ways; everything is mapped to one code so tables and caps line up
LANGUAGE_CODES = {
    "english": "en", "german": "de", "french": "fr", "spanish": "es", "italian": "it",
    "portuguese": "pt", "dutch": "nl", "russian": "ru", "chinese": "zh", "japanese": "ja",
    "arabic": "ar", "hindi": "hi", "turkish": "tr", "korean": "ko", "polish": "pl",
    "swedish": "sv", "indonesian": "id", "vietnamese": "vi", "thai": "th", "greek": "el",
    "hebrew": "he", "persian": "fa", "bengali": "bn", "ukrainian": "uk", "czech": "cs",
    "romanian": "ro", "hungarian": "hu", "finnish": "fi", "danish": "da", "norwegian": "no",
    "urdu": "ur", "tamil": "ta", "telugu": "te", "malay": "ms", "swahili": "sw",
}
# a benign-only source teaches "this language -> benign"; per language it is capped at the
# number of injection rows in that language, so no language is known from one side only
CAPPED_BENIGN_SOURCES = {"aya", "oasst1"}
MIN_CAPPED_ROWS = 5

NEAR_DUP_THRESHOLD = 0.90   # cosine similarity on char n-gram TF-IDF
SKEW_THRESHOLD = 0.60       # majority class share that counts as skewed
MIN_SKEW_ROWS = 20          # a language or script with fewer rows is not flagged


def load(path):
    """One CSV with the standard columns; missing optional columns are filled with ''."""
    df = pd.read_csv(path, keep_default_na=False)
    missing = {"text", "label"} - set(df.columns)
    if missing:
        raise ValueError(f"{path.name} is missing columns: {missing}")
    df["text"] = df["text"].astype(str)
    df["label"] = df["label"].astype(int)
    for column in COLUMNS:
        if column not in df.columns:
            df[column] = ""
    df["language"] = df["language"].map(language_code)
    return df


def language_code(value):
    """ISO code for a language name ('Chinese' -> 'zh'); codes and unknown names pass through."""
    value = str(value).strip().lower()
    return LANGUAGE_CODES.get(value, value)


def load_optional(path):
    """The CSV when it exists, otherwise None with a printed warning."""
    if not path.exists():
        print(f"  warning: {path.relative_to(ROOT)} not found, skipped")
        return None
    return load(path)


def family_of(source):
    """Held-out-source folds hold out a whole family of similar sources."""
    return FAMILIES.get(source, source)


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
    written = [frame for frame in map(load_optional, HANDWRITTEN_DEV_CSVS) if frame is not None]
    if written:
        sets["handwritten_dev"] = pd.concat(written, ignore_index=True).assign(source="handwritten")
    dev3 = load_optional(HANDWRITTEN_DEV3_CSV)
    if dev3 is not None:
        sets["handwritten_dev3"] = dev3.assign(source="handwritten")
    probe = load_optional(PROBE_DEV_CSV)
    if probe is not None:
        sets["probe_dev"] = probe.assign(source="probe")
    dev4 = load_optional(HANDWRITTEN_DEV4_CSV)
    if dev4 is not None:
        sets["handwritten_dev4"] = dev4.assign(source="handwritten")
    dev5 = load_optional(AGENT_DRAFTED_DEV5_CSV)
    if dev5 is not None:
        sets["agent_drafted_dev5"] = dev5.assign(source="agent_drafted")
    new = load_optional(NEW_TEST_CSV)
    if new is not None:                       # the round-four source splits: reported, never gating
        for source, part in new.groupby("source"):
            if source in ROUND4_NEW_SOURCES:
                sets[f"{source}_dev"] = part.reset_index(drop=True)
    return sets


def load_tests():
    """Held-out test sets, by name. Never trained on and never used to make a decision."""
    test = load_test()
    tests = {"official": test[test["half"] == "final"].reset_index(drop=True)}
    for path in (EXTRA_TEST_CSV, NEW_TEST_CSV):
        frame = load_optional(path)
        if frame is not None:
            for source, part in frame.groupby("source"):
                if path == NEW_TEST_CSV and source in ROUND4_NEW_SOURCES:
                    continue                  # development data since round five, see load_dev_sets()
                tests[source] = part.reset_index(drop=True)
    written = load_optional(HANDWRITTEN_CSV) if HANDWRITTEN_CSV is not None else None
    if written is not None:
        tests["handwritten"] = written.assign(source="handwritten")
    return tests


def held_out_sets():
    return {**load_dev_sets(), **load_tests()}


def load_pool():
    """All training rows from every source, minus duplicates and anything held out."""
    parts = [load_train(), load(EXTRA_TRAIN_CSV)]
    for path in (CONTRAST_CSV, NEW_TRAIN_CSV, DRAFTED_TRAIN_CSV):
        frame = load_optional(path)
        if frame is not None:
            parts.append(frame)
    pool = pd.concat(parts, ignore_index=True)
    pool = pool[pool["text"].str.strip() != ""]
    pool["family"] = pool["source"].map(family_of)
    keys = pool["text"].map(dedup_key)

    held_out = pd.concat(held_out_sets().values(), ignore_index=True)
    pool = pool[~keys.isin(set(held_out["text"].map(dedup_key))) & ~keys.duplicated()]
    pool = pool.reset_index(drop=True)

    # some sources publish near-copies of one prompt on both sides of their split
    tfidf = TfidfVectorizer(analyzer="char_wb", ngram_range=(3, 5), sublinear_tf=True)
    held_m = tfidf.fit_transform(held_out["text"])
    leaked = _similarity_max(tfidf.transform(pool["text"]), held_m, same=False) >= NEAR_DUP_THRESHOLD
    pool = cap_benign_by_language(pool[~leaked]).reset_index(drop=True)
    print("training pool, class balance by language:")
    print(balance_by(pool, "language").to_string())
    return pool


def cap_benign_by_language(pool, sources=CAPPED_BENIGN_SOURCES, seed=7):
    """Benign rows of a benign-only source, capped per language at that language's injection count.

    Without the cap a language that only ever appears as benign text is a shortcut the SVM
    can learn, and every attack in that language is then missed. A handful of rows is kept
    even when a language has no injections at all.
    """
    injections = pool[pool["label"] == 1].groupby("language").size()
    rng = np.random.default_rng(seed)
    drop = []
    benign = pool[pool["source"].isin(sources) & (pool["label"] == 0)]
    for language, index in benign.groupby("language").groups.items():
        cap = max(int(injections.get(language, 0)), MIN_CAPPED_ROWS)
        if len(index) > cap:
            drop.extend(rng.choice(np.asarray(index), size=len(index) - cap, replace=False))
    if drop:
        print(f"  {len(drop)} benign rows of {sorted(sources)} dropped so that no language "
              f"has more benign rows from them than injection rows")
    return pool.drop(index=drop)


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
    # Latin keys are exactly as in round three, so the official dev/final halves do not move;
    # a tail without Latin letters keeps its own words instead of landing in one empty group
    return re.sub(r"[^a-z ]", "", tail).strip() or dedup_key(tail)


def class_balance(df):
    counts = df["label"].value_counts().sort_index()
    share = counts / counts.sum()
    return pd.DataFrame({"count": counts, "share": share.round(3)}).rename(
        index={0: "benign (0)", 1: "injection (1)"}
    )


def script_of(text, sample=300):
    """Majority script of the letters in the text's first characters: latin, cyrillic, cjk, ..."""
    counts = Counter(unicodedata.name(ch, "OTHER").split()[0] for ch in text[:sample] if ch.isalpha())
    return counts.most_common(1)[0][0].lower() if counts else "none"


def balance_by(df, column):
    """Benign and injection rows per value of the column; FLAG where one class dominates."""
    values = df[column].replace("", "(none)") if column in df.columns else df["text"].map(script_of)
    table = df.assign(**{column: values}).groupby([column, "label"]).size().unstack(fill_value=0)
    table = table.reindex(columns=[0, 1], fill_value=0)
    table.columns = ["benign", "injection"]
    table["rows"] = table["benign"] + table["injection"]
    table["injection_share"] = (table["injection"] / table["rows"]).round(3)
    majority = table[["benign", "injection"]].max(axis=1) / table["rows"]
    table["skewed"] = np.where((majority > SKEW_THRESHOLD) & (table["rows"] >= MIN_SKEW_ROWS), "FLAG", "")
    return table.sort_values("rows", ascending=False)


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


def report(name, df, by_language=True):
    print(f"\n=== {name}: {len(df)} rows ===")
    balance = class_balance(df)
    print(balance.to_string())
    if balance["share"].max() > SKEW_THRESHOLD:
        print(f"  FLAG: skewed, majority class is {balance['share'].max():.0%}")
    if by_language:
        for column in ("language", "script"):
            table = balance_by(df, column)
            if len(table) > 1 or column == "script":
                print(f"class balance by {column}:")
                print(table.to_string())

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
    report("TRAINING POOL (all sources, official train splits)", pool, by_language=False)
    print("class balance by script:")
    print(balance_by(pool, "script").to_string())

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
