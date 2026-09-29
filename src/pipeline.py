"""Feature sets and the SVM pipeline shared by training and prediction."""
import numpy as np
from sklearn.base import BaseEstimator, TransformerMixin
from sklearn.compose import ColumnTransformer
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import FunctionTransformer, StandardScaler
from sklearn.svm import SVC

from .features import EMBEDDING_DIM, N_RULES, embed, legacy_matrix, rule_matrix
from .normalize import normalize
from .rules import RULE_NAMES

FEATURE_SETS = ["legacy6", "rules16", "emb", "emb+rules16"]
COUNT_COLUMNS = [i for i, name in enumerate(RULE_NAMES) if name.endswith(("_count", "_score"))]


class BlockWeight(BaseEstimator, TransformerMixin):
    """Scale a block of columns so 16 rules do not drown out the 384 embedding columns."""

    def __init__(self, weight=1.0):
        self.weight = weight

    def fit(self, X, y=None):
        self.n_features_in_ = X.shape[1]
        return self

    def transform(self, X):
        return X * self.weight


def log_counts(X):
    X = np.array(X, dtype=np.float64)
    X[:, COUNT_COLUMNS] = np.log1p(X[:, COUNT_COLUMNS])
    return X


def _rules_block():
    return [("log", FunctionTransformer(log_counts)), ("scale", StandardScaler())]


def build_model(feature_set, probability=False, **svc_params):
    svc = SVC(class_weight="balanced", probability=probability, random_state=42,
              cache_size=500, **svc_params)
    if feature_set == "legacy6":
        return Pipeline([("scale", StandardScaler()), ("svc", svc)])
    if feature_set == "rules16":
        return Pipeline(_rules_block() + [("svc", svc)])
    if feature_set == "emb":
        return Pipeline([("svc", svc)])
    if feature_set == "emb+rules16":
        rules = Pipeline(_rules_block() + [("weight", BlockWeight())])
        columns = ColumnTransformer([
            ("emb", "passthrough", slice(0, EMBEDDING_DIM)),
            ("rules", rules, slice(EMBEDDING_DIM, EMBEDDING_DIM + N_RULES)),
        ])
        return Pipeline([("features", columns), ("svc", svc)])
    raise ValueError(f"unknown feature set: {feature_set}")


def embed_view(texts, view, cache_name=None):
    """view='raw' embeds the text as written, view='norm' embeds the de-obfuscated text."""
    if view == "norm":
        texts = [normalize(t) for t in texts]
    return embed(texts, cache_name=f"embeddings_{view}" if cache_name else None)


def extract(feature_set, texts, view="norm", cache_name=None):
    texts = list(texts)
    if feature_set == "legacy6":
        return legacy_matrix(texts)
    if feature_set == "rules16":
        return rule_matrix(texts)
    if feature_set == "emb":
        return embed_view(texts, view, cache_name)
    if feature_set == "emb+rules16":
        return np.hstack([embed_view(texts, view, cache_name), rule_matrix(texts)])
    raise ValueError(f"unknown feature set: {feature_set}")


def assemble(feature_set, embeddings, rules, legacy):
    """Pick the columns of a feature set from blocks that were computed once."""
    if feature_set == "legacy6":
        return legacy
    if feature_set == "rules16":
        return rules
    if feature_set == "emb":
        return embeddings
    if feature_set == "emb+rules16":
        return np.hstack([embeddings, rules])
    raise ValueError(f"unknown feature set: {feature_set}")
