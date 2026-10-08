"""Experiment: which sentence-embedding model separates injections from benign text best?

Uses training data and development sets only. Each text is represented by its first
window, and an embedding-only linear SVM is scored by average precision.

    python scripts/compare_embeddings.py
"""
import sys
import warnings
from pathlib import Path

import numpy as np
import pandas as pd
from sentence_transformers import SentenceTransformer
from sklearn.metrics import average_precision_score
from sklearn.model_selection import StratifiedGroupKFold
from sklearn.svm import SVC

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from src.dataset import load_dev_sets, load_pool, payload_group   # noqa: E402
from src.normalize import normalize                               # noqa: E402
from src.windows import split_windows                             # noqa: E402

CACHE = Path(__file__).resolve().parent.parent / "data" / "cache"
MODELS = {
    "MiniLM-L12 (current)": ("sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2", ""),
    "e5-small": ("intfloat/multilingual-e5-small", "query: "),
    "mpnet-base": ("sentence-transformers/paraphrase-multilingual-mpnet-base-v2", ""),
}


def embed(name, texts, tag):
    path = CACHE / f"compare_{tag}_{name.split()[0]}.npy"
    if path.exists():
        return np.load(path)
    repo, prefix = MODELS[name]
    model = SentenceTransformer(repo, device="cpu")
    vectors = model.encode([prefix + t for t in texts], batch_size=32, normalize_embeddings=True,
                           show_progress_bar=False, convert_to_numpy=True)
    CACHE.mkdir(parents=True, exist_ok=True)
    np.save(path, vectors)
    return vectors


def held_out_scores(X, y, folds):
    scores = np.zeros(len(y))
    for train, held in folds:
        model = SVC(kernel="linear", C=1, class_weight="balanced").fit(X[train], y[train])
        scores[held] = model.decision_function(X[held])
    return scores


def main():
    warnings.filterwarnings("ignore")
    pool = load_pool()
    dev = pd.concat([f.assign(set=n) for n, f in load_dev_sets().items()], ignore_index=True)
    first = lambda text: normalize(split_windows(text)[0])
    pool_texts, dev_texts = pool["text"].map(first).tolist(), dev["text"].map(first).tolist()
    y, groups = pool["label"].to_numpy(), pool["text"].map(payload_group)

    by_group = list(StratifiedGroupKFold(5, shuffle=True, random_state=42).split(pool_texts, y, groups))
    sources = pool["source"].to_numpy()
    by_source = [(np.flatnonzero(sources != s), np.flatnonzero(sources == s))
                 for s in sorted(set(sources))]

    rows = []
    for name in MODELS:
        print("embedding with", name, flush=True)
        X, X_dev = embed(name, pool_texts, "pool"), embed(name, dev_texts, "dev")
        row = {
            "model": name, "dims": X.shape[1],
            "unseen payloads": average_precision_score(y, held_out_scores(X, y, by_group)),
            "unseen source": average_precision_score(y, held_out_scores(X, y, by_source)),
        }
        full = SVC(kernel="linear", C=1, class_weight="balanced").fit(X, y)
        dev_scores = full.decision_function(X_dev)
        for set_name, part in dev.groupby("set"):
            row[set_name] = average_precision_score(part["label"], dev_scores[part.index])
        for source in ("deepset", "jackhhao"):
            mask = sources == source
            row[f"{source} (unseen payloads)"] = average_precision_score(
                y[mask], held_out_scores(X, y, by_group)[mask])
        rows.append(row)
        print(pd.DataFrame(rows).round(3).to_string(index=False), flush=True)


if __name__ == "__main__":
    main()
