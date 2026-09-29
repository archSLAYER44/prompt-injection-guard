"""Feature matrix = [384-dim sentence embedding | 16 rule features].

Show example vectors and the rule firing-rate table:
    python -m src.features
"""
import hashlib
import json
from pathlib import Path

import numpy as np
import pandas as pd

from .rules import DESCRIPTIVE_RULES, LEGACY_NAMES, RULE_NAMES, legacy_vector, rule_vector

ROOT = Path(__file__).resolve().parent.parent
CACHE = ROOT / "data" / "cache"

EMBEDDING_MODEL = "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"
EMBEDDING_DIM = 384
N_RULES = len(RULE_NAMES)
SAVE_EVERY = 1000

_model = None


def get_embedder():
    global _model
    if _model is None:
        from sentence_transformers import SentenceTransformer
        _model = SentenceTransformer(EMBEDDING_MODEL, device="cpu")
    return _model


def _encode(texts):
    return get_embedder().encode(
        texts, batch_size=64, normalize_embeddings=True,
        show_progress_bar=False, convert_to_numpy=True,
    ).astype(np.float32)


_stores = {}


def _store(name):
    """Per-text embedding cache on disk: each distinct text is embedded once."""
    if name not in _stores:
        keys_path, vectors_path = CACHE / f"{name}.keys.json", CACHE / f"{name}.npy"
        if keys_path.exists() and vectors_path.exists():
            keys, vectors = json.loads(keys_path.read_text()), np.load(vectors_path)
        else:
            keys, vectors = [], np.zeros((0, EMBEDDING_DIM), dtype=np.float32)
        _stores[name] = {"index": {k: i for i, k in enumerate(keys)}, "vectors": vectors}
    return _stores[name]


def embed(texts, cache_name=None):
    """Normalized sentence embeddings. With cache_name, texts seen before are read from disk."""
    texts = list(texts)
    if not cache_name:
        return _encode(texts)

    store = _store(cache_name)
    keys = [hashlib.sha1(t.encode("utf-8")).hexdigest() for t in texts]
    missing = {k: t for k, t in zip(keys, texts) if k not in store["index"]}
    if missing:
        print(f"  embedding {len(missing)} new texts ({cache_name})", flush=True)
    items = list(missing.items())
    for start in range(0, len(items), SAVE_EVERY):   # save as we go, so a stopped run resumes
        chunk = items[start:start + SAVE_EVERY]
        vectors = _encode([text for _, text in chunk])
        for offset, (key, _) in enumerate(chunk):
            store["index"][key] = len(store["vectors"]) + offset
        store["vectors"] = np.vstack([store["vectors"], vectors])
        CACHE.mkdir(parents=True, exist_ok=True)
        np.save(CACHE / f"{cache_name}.npy", store["vectors"])
        (CACHE / f"{cache_name}.keys.json").write_text(json.dumps(list(store["index"])))
        if len(items) > SAVE_EVERY:
            print(f"    {min(start + SAVE_EVERY, len(items))}/{len(items)}", flush=True)
    return store["vectors"][[store["index"][k] for k in keys]]


def rule_matrix(texts):
    return np.array([rule_vector(t) for t in texts], dtype=np.float32)


def legacy_matrix(texts):
    return np.array([legacy_vector(t) for t in texts], dtype=np.float32)


def build_matrix(texts, cache_name=None):
    """Columns 0..383 are the embedding, columns 384..399 the rules in RULE_NAMES order."""
    texts = list(texts)
    return np.hstack([embed(texts, cache_name), rule_matrix(texts)])


def firing_rates(df):
    """Per rule: how often it is non-zero and its mean value, for each class."""
    rules = pd.DataFrame(rule_matrix(df["text"]), columns=RULE_NAMES)
    labels = df["label"].to_numpy()
    rows = []
    for name in RULE_NAMES:
        inj, ben = rules.loc[labels == 1, name], rules.loc[labels == 0, name]
        rows.append({
            "rule": name,
            "fires_injection": (inj > 0).mean(),
            "fires_benign": (ben > 0).mean(),
            "mean_injection": inj.mean(),
            "mean_benign": ben.mean(),
            "descriptive": name in DESCRIPTIVE_RULES,
        })
    return pd.DataFrame(rows).set_index("rule")


def main():
    from .dataset import load_train
    from .rules import analyze, fired

    pd.set_option("display.width", 250)
    pd.set_option("display.max_columns", 30)
    pd.set_option("display.max_colwidth", 70)

    train = load_train()
    sample = pd.concat([
        train[train["label"] == 1].groupby("category").sample(1, random_state=7).head(5),
        train[train["label"] == 0].groupby("category").sample(1, random_state=7).head(5),
    ])

    print("=== 5 injection + 5 benign examples ===")
    for i, row in enumerate(sample.itertuples(), 1):
        kind = "INJECTION" if row.label else "benign"
        print(f"\n[{i}] {kind} / {row.category}")
        print("    text:", repr(row.text if len(row.text) <= 200 else row.text[:197] + "..."))
        analysis = analyze(row.text)
        print("    vector:", {k: round(float(v), 3) for k, (v, _) in analysis.items()})
        for name, (value, snippets) in fired(analysis).items():
            print(f"    fired {name} = {value:.3g}  {snippets[:3]}")

    matrix = build_matrix(sample["text"])
    print(f"\nembedding shape: {matrix[:, :EMBEDDING_DIM].shape}, "
          f"rules shape: {matrix[:, EMBEDDING_DIM:].shape}, full matrix: {matrix.shape}")
    print("embedding L2 norms:", np.linalg.norm(matrix[:, :EMBEDDING_DIM], axis=1).round(3))
    print("legacy (original 6) vector of example 1:",
          dict(zip(LEGACY_NAMES, np.round(legacy_matrix(sample["text"].head(1))[0], 3))))

    print("\n=== Rule firing rates on TRAIN ===")
    rates = firing_rates(train)
    print(rates.round(3).to_string())

    noisy = rates[(~rates["descriptive"]) & (rates["fires_benign"] > 0.10)
                  & (rates["fires_benign"] >= 0.5 * rates["fires_injection"])]
    print("\nrules that fire on benign text too often (candidates to drop):",
          list(noisy.index) or "none")
    silent = rates[(~rates["descriptive"]) & (rates["fires_injection"] < 0.01)]
    print("rules that almost never fire on train injections:", list(silent.index) or "none")


if __name__ == "__main__":
    main()
