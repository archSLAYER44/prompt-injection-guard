"""Feature sets and the SVM pipeline shared by training and prediction."""
import numpy as np
from sklearn.base import BaseEstimator, TransformerMixin
from sklearn.compose import ColumnTransformer
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import FunctionTransformer, StandardScaler
from sklearn.svm import SVC

from .features import EMBEDDING_DIM, embed, legacy_matrix, rule_columns, rule_matrix
from .normalize import normalize
from .rules import RULE_NAMES

FEATURE_SETS = ["legacy6", "rules16", "emb", "emb+rules16", "emb+rules20"]
COUNT_CAP = 3                   # a count of 3 or more reads as "fully present"
LENGTH_SCALE = 10.0             # log_text_length is at most about 9 (8,000 characters)


def feature_rules(feature_set):
    """Rule names a feature set uses, in RULE_NAMES order."""
    if feature_set in ("rules16", "emb+rules16"):
        return RULE_NAMES[:16]
    if feature_set == "emb+rules20":
        return list(RULE_NAMES)
    if feature_set in ("legacy6", "emb"):
        return []
    raise ValueError(f"unknown feature set: {feature_set}")


def rule_kind(name):
    """count: log-scaled and capped; length: divided by 10; ratio: already in 0..1."""
    if name == "log_text_length":
        return "length"
    if name.endswith(("_count", "_score")):
        return "count"
    return "ratio"


class BlockWeight(BaseEstimator, TransformerMixin):
    """Scale a block of columns so a few rules do not drown out the 384 embedding columns."""

    def __init__(self, weight=1.0):
        self.weight = weight

    def fit(self, X, y=None):
        self.n_features_in_ = X.shape[1]
        return self

    def transform(self, X):
        return X * self.weight


def log_counts(X):
    """Round-three scaling (kept for the rules16 ablation): log1p on counts, then standardized."""
    X = np.array(X, dtype=np.float64)
    counts = [i for i, name in enumerate(RULE_NAMES[:16]) if rule_kind(name) == "count"]
    X[:, counts] = np.log1p(X[:, counts])
    return X


def bounded_scale(X, kinds):
    """Every rule column lands in 0..1, so one hit of a rare rule cannot decide the verdict."""
    X = np.array(X, dtype=np.float64)
    cap = np.log1p(COUNT_CAP)
    for column, kind in enumerate(kinds):
        if kind == "count":
            X[:, column] = np.minimum(np.log1p(np.maximum(X[:, column], 0)), cap) / cap
        elif kind == "length":
            X[:, column] = X[:, column] / LENGTH_SCALE
        else:
            X[:, column] = np.clip(X[:, column], 0.0, 1.0)
    return X


def _bounded_block(rule_names):
    kinds = [rule_kind(name) for name in rule_names]
    return Pipeline([("bound", FunctionTransformer(bounded_scale, kw_args={"kinds": kinds})),
                     ("weight", BlockWeight())])


def build_model(feature_set, **svc_params):
    # no SVC(probability=...): the calibrator is a separate Platt fit on held-out texts
    svc = SVC(class_weight="balanced", random_state=42, cache_size=500, **svc_params)
    if feature_set == "legacy6":
        return Pipeline([("scale", StandardScaler()), ("svc", svc)])
    if feature_set == "rules16":
        return Pipeline([("log", FunctionTransformer(log_counts)), ("scale", StandardScaler()),
                         ("svc", svc)])
    if feature_set == "emb":
        return Pipeline([("svc", svc)])
    if feature_set in ("emb+rules16", "emb+rules20"):
        rule_names = feature_rules(feature_set)
        columns = ColumnTransformer([
            ("emb", "passthrough", slice(0, EMBEDDING_DIM)),
            ("rules", _bounded_block(rule_names), slice(EMBEDDING_DIM, EMBEDDING_DIM + len(rule_names))),
        ])
        return Pipeline([("features", columns), ("svc", svc)])
    raise ValueError(f"unknown feature set: {feature_set}")


def embed_view(texts, view, cache_name=None):
    """view='raw' embeds the text as written, view='norm' embeds the de-obfuscated text."""
    if view == "norm":
        texts = [normalize(t) for t in texts]
    return embed(texts, cache_name=f"embeddings_{view}" if cache_name else None)


def extract(feature_set, texts, view="norm", cache_name=None, rule_names=None):
    """Feature matrix for texts. rule_names (default: the feature set's) picks the rule columns."""
    texts = list(texts)
    if feature_set == "legacy6":
        return legacy_matrix(texts)
    if feature_set == "emb":
        return embed_view(texts, view, cache_name)
    if feature_set in ("rules16", "emb+rules16", "emb+rules20"):
        rules = rule_matrix(texts)[:, rule_columns(rule_names or feature_rules(feature_set))]
        if feature_set == "rules16":
            return rules
        return np.hstack([embed_view(texts, view, cache_name), rules])
    raise ValueError(f"unknown feature set: {feature_set}")


def assemble(feature_set, embeddings, rules, legacy):
    """Pick the columns of a feature set from blocks that were computed once.

    `rules` holds every rule in RULE_NAMES order; the feature set chooses its columns.
    """
    if feature_set == "legacy6":
        return legacy
    if feature_set == "emb":
        return embeddings
    if feature_set in ("rules16", "emb+rules16", "emb+rules20"):
        chosen = rules[:, rule_columns(feature_rules(feature_set))]
        return chosen if feature_set == "rules16" else np.hstack([embeddings, chosen])
    raise ValueError(f"unknown feature set: {feature_set}")
