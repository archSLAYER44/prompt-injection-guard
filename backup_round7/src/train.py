"""Train the SVM, check it on development folds, and save the candidate models.

    python -m src.train            development numbers; candidates saved to src/models/candidates/
    python -m src.train --final    also run the gate, then score the held-out test sets with the
                                   model the gate promoted (nothing else ever sees the test sets)
    python -m src.train --smoke    5% of the data, one setting, few folds; writes to a scratch
                                   folder only, so it can be run at any time as a quick check

Three kinds of data, kept apart:
    train   fitted on
    dev     never fitted on, used to find mistakes and make decisions
    test    never fitted on and never used for a decision; scored only with --final

Held-out texts (dev and test) are split into as many pieces as predict() scores (MAX_WINDOWS,
MAX_SENTENCES), so thresholds, the development report, the gate and the test numbers describe
the model as deployed. Training texts, and therefore the out-of-fold scores of the training
folds, use the smaller TRAIN_WINDOW_LIMIT / TRAIN_SENTENCE_LIMIT.
"""
import argparse
import itertools
import json
import math
import tempfile
import warnings
from pathlib import Path

import joblib
import numpy as np
import pandas as pd
from joblib import Parallel, delayed
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import (
    accuracy_score, average_precision_score, confusion_matrix, precision_recall_curve,
    precision_recall_fscore_support,
)
from sklearn.model_selection import StratifiedGroupKFold

from .augment import augment
from .dataset import dedup_key, family_of, load_dev_sets, load_pool, load_tests, load_train, payload_group
from .features import EMBEDDING_MODEL, legacy_matrix, rule_matrix
from .pipeline import FEATURE_SETS, assemble, build_model, embed_view, feature_rules
from .rules import RULE_NAMES
from .windows import (
    MAX_SENTENCES, MAX_WINDOWS, TRAIN_SENTENCE_LIMIT, TRAIN_WINDOW_LIMIT, WINDOW_CHARS, WINDOW_TOKENS,
    split_sentences, split_units,
)

ROOT = Path(__file__).resolve().parent.parent

SEED = 42
VIEW = "norm"
CANDIDATES = ["emb+rules20", "emb+rules16"]    # tuned by the grid; fitted at the same setting
TRAIN_LIMIT = 3             # windows, and sentences, that one training text contributes
SPLIT_LIMITS = {"train": (TRAIN_WINDOW_LIMIT, TRAIN_SENTENCE_LIMIT)}   # held-out texts: as predict()
EMBEDDED_ATTACKS = {"indirect_injection", "appended_override"}   # last sentence is the payload
LEAK_EXEMPT = {"mirzaakhi"}  # its official split shares carrier sentences by design
MIN_LEAK_CHARS = 20         # held-out sentences at least this long are blocked inside windows too
SUSPICIOUS_ACCURACY = 0.97
MIN_PRECISION = 0.96        # the threshold is the most sensitive one that keeps this precision
                            # (0.98 in round three; lowered on 2026-10-01 after the first
                            # round-four run, see report/round_four_results.md)
SMOKE_FRACTION = 0.05
SMOKE_HELD_OUT = 20         # rows per held-out set in a smoke run

STANDARDS = {
    "official": {"recall": 0.90, "precision": 0.95},
    "external": {"recall": 0.85, "precision": 0.90},
    "handwritten": {"recall": 0.85, "max_false_alarm_rate": 2 / 28},
}
EXTERNAL_SETS = ["deepset", "gandalf", "jackhhao"]
NEW_SETS = ["oasst1", "injecagent", "bipia"]           # round five; the six round-four sources are development data now

SVC_GRID = [{"svc__kernel": "linear", "svc__C": c} for c in (0.3, 1)]
RULE_WEIGHTS = (0.5, 1.0, 2.0)
ABLATION_GRID = [{"svc__kernel": "linear", "svc__C": 1}]
CONTENT_RULES = [i for i, n in enumerate(RULE_NAMES) if n in {
    "override_phrase_count", "role_reassignment_score", "delimiter_mimicry_count",
    "authority_claim_count", "indirect_address_count", "exfiltration_count",
    "output_manipulation_count", "hypothetical_framing_count", "dangerous_action_count",
    "tool_action_count", "multilingual_override_count", "task_pivot_count"}]


def param_grid(feature_set, grid=SVC_GRID):
    if not feature_set.startswith("emb+"):
        return grid
    return [dict(g, features__rules__weight__weight=w) for g in grid for w in RULE_WEIGHTS]


def output_paths(smoke):
    """Where this run writes. A smoke run writes to a scratch folder and never over real files."""
    base = Path(tempfile.gettempdir()) / "detector_smoke" if smoke else ROOT
    return {
        "model": base / "src" / "models" / "injection_model.pkl",
        "candidates": base / "src" / "models" / "candidates",
        "metrics": base / "report" / "metrics.json",
        "champion": base / "report" / "champion_dev_scores.csv",
    }


# ------------------------------------------------------------------ corpus


class Corpus:
    """Every text, the units it is split into, and the feature blocks of every unit."""

    def __init__(self, texts, blocked=(set(), set())):
        self.texts = texts.reset_index(drop=True)
        rows = []
        for text_id, (text, role) in enumerate(zip(self.texts["text"], self.texts["role"])):
            window_limit, sentence_limit = SPLIT_LIMITS.get(role, (MAX_WINDOWS, MAX_SENTENCES))
            for kind, unit in split_units(text, window_limit, sentence_limit):
                rows.append((text_id, kind, unit))
        self.units = pd.DataFrame(rows, columns=["text_id", "kind", "unit"])

        unique = self.units["unit"].drop_duplicates().tolist()
        print(f"{len(self.texts)} texts -> {len(self.units)} units ({len(unique)} distinct)", flush=True)
        position = {u: i for i, u in enumerate(unique)}
        order = self.units["unit"].map(position).to_numpy()
        self.embeddings = embed_view(unique, VIEW, "all")[order]
        self.rules = rule_matrix(unique)[order]
        self.legacy = legacy_matrix(unique)[order]

        self.units["label"] = self.texts["label"].to_numpy()[self.units["text_id"]]
        self.units["for_training"] = self._training_choice()
        # a piece of text that appears under both labels cannot teach the model anything
        labels_seen = self.units[self.units["for_training"]].groupby("unit")["label"].nunique()
        self.ambiguous = self.units["unit"].isin(labels_seen.index[labels_seen > 1]).to_numpy()
        self.leaked = self._leaked(*blocked)
        self._leak_report()

    def _leaked(self, pieces, sentences):
        """Training units equal (after normalization) to a held-out piece, or containing a
        held-out sentence: a window that carries one would teach it with the training label."""
        text_ids = self.units["text_id"].to_numpy()
        scanned = (self.texts["role"].to_numpy() == "train") \
            & ~self.texts["source"].isin(LEAK_EXEMPT).to_numpy()
        keys = self.units["unit"].map(dedup_key).to_numpy()
        leaked = pd.Series(keys).isin(pieces).to_numpy() & scanned[text_ids]

        text_keys = [dedup_key(t) if s else "" for t, s in zip(self.texts["text"], scanned)]
        rows_of = self.units.groupby("text_id").indices
        for text_id, hits in enumerate(contained_sentences(text_keys, sentences)):
            if hits:
                for row in rows_of.get(text_id, ()):
                    leaked[row] |= any(sentence in keys[row] for sentence in hits)
        return leaked

    def _leak_report(self):
        """How many pieces that would otherwise be trained on (after dedup) the leak filter drops."""
        rows = self.unit_rows(self.texts["role"] == "train", training=True, drop_leaked=False)
        dropped = rows[self.leaked[rows]]
        sources = self.texts["source"].to_numpy()[self.units["text_id"].to_numpy()[dropped]]
        counts = pd.Series(sources).value_counts()
        print(f"training pieces dropped for matching a held-out piece: {len(dropped)}"
              + (f" ({', '.join(f'{s}: {n}' for s, n in counts.items())})" if len(counts) else ""))

    def _training_choice(self):
        """Units a text contributes to training.

        A benign text is benign throughout, so any of its units will do. An injection text
        is only known to be an injection as a whole. It gives its opening window, the units
        where the content rules find something, its hidden readings, and its last sentence
        when the dataset says the attack was appended to a document.
        """
        rng = np.random.default_rng(SEED)
        hits = (self.rules[:, CONTENT_RULES] > 0).sum(axis=1)
        kinds = self.units["kind"].to_numpy()
        categories = self.texts["category"].to_numpy()
        chosen = np.zeros(len(self.units), dtype=bool)

        for text_id, index in self.units.groupby("text_id").groups.items():
            index = np.asarray(index)
            attack = self.units["label"].iat[index[0]] == 1
            chosen[index[0]] = True
            chosen[index[kinds[index] == "reading"]] = True

            for kind, spare in (("window", 1), ("sentence", 0)):
                rest = index[kinds[index] == kind][spare:]
                if not len(rest):
                    continue
                if attack:
                    if kind == "sentence" and categories[text_id] in EMBEDDED_ATTACKS:
                        chosen[rest[-1]] = True
                    rest = rest[hits[rest] > 0]
                    rest = rest[np.argsort(-hits[rest], kind="stable")]
                else:
                    rest = rng.permutation(rest)
                chosen[rest[:TRAIN_LIMIT - spare]] = True
        return chosen

    def matrix(self, feature_set):
        return assemble(feature_set, self.embeddings, self.rules, self.legacy)

    def unit_rows(self, text_mask, training, drop_leaked=True):
        mask = text_mask.to_numpy()[self.units["text_id"]]
        if not training:
            return np.flatnonzero(mask)
        mask &= self.units["for_training"].to_numpy() & ~self.ambiguous
        if drop_leaked:
            mask &= ~self.leaked
        rows = np.flatnonzero(mask)
        # the datasets repeat the same sentences many times; one copy of each is enough
        return rows[~self.units["unit"].iloc[rows].duplicated().to_numpy()]

    def text_scores(self, unit_rows, unit_scores):
        """Score of a text = score of its most suspicious unit."""
        ids = self.units["text_id"].to_numpy()[unit_rows]
        best = pd.Series(unit_scores).groupby(ids).max()
        return best.index.to_numpy(), best.to_numpy()


def held_out_piece_keys(frames):
    """Normalized keys of every piece of every held-out text, and of its longer sentences.

    Returns (pieces, sentences): a training unit equal to a piece, or containing one of the
    sentences, never reaches the model. A text takes the score of its most suspicious unit,
    so a held-out sentence learnt inside a training window would inflate the held-out score.
    """
    pieces, sentences = set(), set()
    for frame in frames:
        for text in frame["text"]:
            pieces.update(dedup_key(unit) for _, unit in split_units(text))
            sentences.update(k for k in map(dedup_key, split_sentences(text)) if len(k) >= MIN_LEAK_CHARS)
    pieces.discard("")
    return pieces, sentences


def contained_sentences(keys, sentences):
    """For each key, the sentences it contains as a substring.

    A word-trigram index of the sentences keeps this linear in the text length: a sentence is
    only compared at positions where its first three words appear.
    """
    index, short = {}, []
    for sentence in sentences:
        words = sentence.split(" ")
        if len(words) >= 3:
            index.setdefault(tuple(words[:3]), []).append(sentence)
        else:
            short.append(sentence)
    found = []
    for key in keys:
        hits = [s for s in short if s in key] if key else []
        words = key.split(" ")
        offset = 0
        for i in range(len(words) - 2):
            for sentence in index.get((words[i], words[i + 1], words[i + 2]), ()):
                if key.startswith(sentence, offset):
                    hits.append(sentence)
            offset += len(words[i]) + 1
        found.append(hits)
    return found


def build_corpus(with_tests, smoke=False):
    pool = load_pool().assign(kind="original", role="train", set="train")
    if smoke:
        pool = pool.sample(frac=SMOKE_FRACTION, random_state=SEED).reset_index(drop=True)
    pool["group"] = pool["text"].map(payload_group)
    pool["parent"] = pool.index

    copies_a = augment(pool, templates="a", seed=SEED).assign(kind="aug_a")
    copies_b = augment(pool, templates="b", seed=SEED + 1).assign(kind="aug_b")
    parts = [pool, copies_a, copies_b]

    dev, tests = load_dev_sets(), load_tests()
    if smoke:
        dev = {k: f.sample(min(len(f), SMOKE_HELD_OUT), random_state=SEED) for k, f in dev.items()}
        tests = {k: f.sample(min(len(f), SMOKE_HELD_OUT), random_state=SEED) for k, f in tests.items()}
    held_out = [("dev", dev)] + ([("test", tests)] if with_tests else [])
    for role, sets in held_out:
        for name, frame in sets.items():
            parts.append(frame.assign(kind="held_out", role=role, set=name, group="", parent=-1))
    texts = pd.concat(parts, ignore_index=True)
    texts["family"] = texts["source"].map(family_of)
    # pieces and sentences of ALL held-out texts are blocked from training, scored or not
    return Corpus(texts, held_out_piece_keys(list(dev.values()) + list(tests.values())))


# ------------------------------------------------------------- evaluation


def wilson(hits, n, z=1.96):
    """95% Wilson score interval for a proportion hits / n."""
    if n == 0:
        return (0.0, 1.0)
    p = hits / n
    denominator = 1 + z * z / n
    centre = (p + z * z / (2 * n)) / denominator
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / denominator
    return (max(0.0, centre - half), min(1.0, centre + half))


def scores(y_true, y_pred):
    precision, recall, f1, _ = precision_recall_fscore_support(
        y_true, y_pred, labels=[1], average=None, zero_division=0)
    tn, fp, fn, tp = confusion_matrix(y_true, y_pred, labels=[0, 1]).ravel()
    return {
        "n": int(len(y_true)), "accuracy": float(accuracy_score(y_true, y_pred)),
        "precision": float(precision[0]), "recall": float(recall[0]), "f1": float(f1[0]),
        "recall_ci": wilson(int(tp), int(tp + fn)),
        "false_alarm_rate": float(fp / (fp + tn)) if fp + tn else 0.0,
        "false_alarm_ci": wilson(int(fp), int(fp + tn)),
        "tn": int(tn), "fp": int(fp), "fn": int(fn), "tp": int(tp),
    }


def _interval(value, ci, n=1):
    """'value [low, high]', or '-' when the rate has no denominator."""
    if n == 0:
        return "-"
    return f"{value:.3f} [{ci[0]:.2f}, {ci[1]:.2f}]"


def score_row(part, threshold, **labels):
    """One printable row of a score table, with Wilson intervals."""
    s = scores(part["label"], (part["score"] >= threshold).astype(int))
    return {**labels, "rows": s["n"], "precision": round(s["precision"], 3),
            "recall [95%]": _interval(s["recall"], s["recall_ci"], s["tp"] + s["fn"]), "missed": s["fn"],
            "false alarms": s["fp"],
            "fa rate [95%]": _interval(s["false_alarm_rate"], s["false_alarm_ci"], s["fp"] + s["tn"])}


def fit(corpus, feature_set, params, train_texts):
    rows = corpus.unit_rows(train_texts, training=True)
    model = build_model(feature_set).set_params(**params)
    model.fit(corpus.matrix(feature_set)[rows], corpus.units["label"].to_numpy()[rows])
    return model, len(rows)


def score(corpus, feature_set, model, eval_texts):
    """Text-level scores: each text takes the score of its most suspicious unit."""
    rows = corpus.unit_rows(eval_texts, training=False)
    return corpus.text_scores(rows, model.decision_function(corpus.matrix(feature_set)[rows]))


def fit_and_score(corpus, feature_set, params, train_texts, eval_texts):
    model, _ = fit(corpus, feature_set, params, train_texts)
    return score(corpus, feature_set, model, eval_texts)


def leave_one_family_out(corpus, limit=None):
    """Folds that hold out one whole family of sources; its copies use unseen wording (set b)."""
    texts = corpus.texts
    families = sorted(texts.loc[texts["role"] == "train", "family"].unique())
    for family in families[:limit]:
        train = (texts["role"] == "train") & (texts["family"] != family) \
            & texts["kind"].isin(["original", "aug_a"])
        held = (texts["role"] == "train") & (texts["family"] == family) \
            & texts["kind"].isin(["original", "aug_b"])
        yield family, train, held


def grouped_folds(corpus, n_splits=5):
    """Folds over all sources; every copy of a payload stays on one side."""
    texts = corpus.texts
    original = texts[(texts["role"] == "train") & (texts["kind"] == "original")]
    folds = StratifiedGroupKFold(n_splits=n_splits, shuffle=True, random_state=SEED)
    for number, (_, held_idx) in enumerate(
            folds.split(original["text"], original["label"], original["group"])):
        held_parents = set(original.index[held_idx])
        in_held = texts["parent"].isin(held_parents) & (texts["role"] == "train")
        yield number, (texts["role"] == "train") & ~in_held, in_held


def make_folds(corpus, smoke=False):
    """(family folds, grouped folds). A smoke run uses one family fold and two grouped folds."""
    if smoke:
        return list(leave_one_family_out(corpus, limit=1)), list(grouped_folds(corpus, n_splits=2))
    return list(leave_one_family_out(corpus)), list(grouped_folds(corpus))


def out_of_fold(corpus, feature_set, grid, folds, n_jobs=-1):
    """Held-out text scores of every grid setting on every fold: {setting index: (by_family, by_group)}."""
    by_family, by_group = folds
    all_folds = by_family + by_group
    results = Parallel(n_jobs=n_jobs)(
        delayed(fit_and_score)(corpus, feature_set, params, train, held)
        for params, (_, train, held) in itertools.product(grid, all_folds))

    def frame(chunk, names):
        parts = [
            corpus.texts.loc[ids, ["label", "source", "family", "language", "kind", "category"]]
            .assign(fold=name, score=values)
            for (ids, values), name in zip(chunk, names)]
        return pd.concat(parts) if parts else None

    names = [name for name, _, _ in all_folds]
    out = {}
    for i in range(len(grid)):
        chunk = results[i * len(all_folds):(i + 1) * len(all_folds)]
        out[i] = (frame(chunk[:len(by_family)], names[:len(by_family)]),
                  frame(chunk[len(by_family):], names[len(by_family):]))
    return out


def select_params(corpus, feature_set, grid, folds, n_jobs=-1):
    """Grid search on development folds only.

    Each setting is scored by average precision (how well it ranks injections above
    benign texts) on two kinds of held-out text: a whole family of sources it never
    trained on, and unseen payloads from sources it did train on. The two are averaged.

    Returns the best setting, its score, and its held-out scores for both kinds of fold.
    """
    best = None
    for i, (by_family, by_group) in out_of_fold(corpus, feature_set, grid, folds, n_jobs).items():
        ranking = [average_precision_score(f["label"], f["score"])
                   for f in (by_family, by_group) if f is not None]
        if best is None or np.mean(ranking) > best[1]:
            best = (grid[i], float(np.mean(ranking)), by_family, by_group)
    return best


def originals(oof):
    return oof[oof["kind"] == "original"]


def choose_threshold(oof):
    """Lowest decision value that still keeps MIN_PRECISION on held-out development texts."""
    precision, recall, thresholds = precision_recall_curve(oof["label"], oof["score"])
    ok = precision[:-1] >= MIN_PRECISION
    if not ok.any():
        return 0.0
    return float(thresholds[ok][np.argmax(recall[:-1][ok])])


def fit_calibrator(oof):
    """Turn a decision value into a probability (Platt scaling on held-out texts)."""
    calibrator = LogisticRegression(C=1e6)
    calibrator.fit(oof[["score"]].to_numpy(), oof["label"])
    return float(calibrator.coef_[0, 0]), float(calibrator.intercept_[0])


def development_report(oof, threshold, title):
    """Score tables by fold, source, family and language. Returns the pooled scores and the tables."""
    print(f"\n{title}")
    if oof is None or not len(oof):
        print("  (no fold of this kind)")
        return None, {}
    oof = oof.assign(kind=oof["kind"].str.replace(r"aug_.", "obfuscated copy", regex=True))
    tables = {}
    rows = [score_row(part, threshold, **{"held out": fold, "texts": kind})
            for (fold, kind), part in oof.groupby(["fold", "kind"])]
    rows.append(score_row(oof, threshold, **{"held out": "ALL", "texts": ""}))
    tables["by_fold"] = rows
    print(pd.DataFrame(rows).to_string(index=False))

    for column in ("source", "family", "language"):
        part = oof[oof[column] != ""]
        if part[column].nunique() < 2:
            continue
        rows = [score_row(chunk, threshold, **{column: value}) for value, chunk in part.groupby(column)]
        tables[f"by_{column}"] = rows
        print(f"\n  by {column}:")
        print(pd.DataFrame(rows).to_string(index=False))

    # a fold that holds out several languages, per language: a language shortcut shows up here
    # as attacks missed in the languages the training side only ever saw as benign text
    languages = oof[oof["language"] != ""].groupby("fold")["language"].nunique()
    part = oof[oof["fold"].isin(languages.index[languages > 1]) & (oof["language"] != "")]
    if len(part):
        rows = [score_row(chunk, threshold, **{"held out": fold, "language": language})
                for (fold, language), chunk in part.groupby(["fold", "language"])]
        tables["by_fold_language"] = rows
        print("\n  by fold and language (folds that hold out more than one language):")
        print(pd.DataFrame(rows).to_string(index=False))
    return scores(oof["label"], (oof["score"] >= threshold).astype(int)), tables


def print_scores(name, s):
    print(f"\n{name} ({s['n']} rows)")
    print(f"  accuracy {s['accuracy']:.3f} | injection precision {s['precision']:.3f} "
          f"recall {_interval(s['recall'], s['recall_ci'], s['tp'] + s['fn'])} F1 {s['f1']:.3f} | "
          f"false alarm rate {_interval(s['false_alarm_rate'], s['false_alarm_ci'], s['fp'] + s['tn'])}")
    print("  confusion matrix      predicted benign  predicted injection")
    print(f"    actual benign       {s['tn']:>16}  {s['fp']:>19}")
    print(f"    actual injection    {s['fn']:>16}  {s['tp']:>19}")
    if s["accuracy"] > SUSPICIOUS_ACCURACY:
        print(f"  FLAG: accuracy above {SUSPICIOUS_ACCURACY:.0%}, check for leakage or templated data")


def held_out_report(corpus, feature_set, model, threshold, role):
    """Score the held-out sets of one role (dev or test) with a model fitted on all training texts."""
    texts = corpus.texts
    ids, values = score(corpus, feature_set, model, texts["role"] == role)
    frame = texts.loc[ids].assign(score=values, predicted=(values >= threshold).astype(int))

    report = {name: scores(part["label"], part["predicted"]) for name, part in frame.groupby("set")}
    for name, members in (("external", EXTERNAL_SETS), ("external_new", NEW_SETS)):
        part = frame[frame["set"].isin(members)]
        if len(part):
            report[name] = scores(part["label"], part["predicted"])

    official = frame[frame["set"].str.startswith("official")]
    seen = set(load_train()["category"])
    table = official.assign(correct=official["predicted"] == official["label"]).groupby(
        ["label", "category"])["correct"].agg(["size", "mean", "sum"]).reset_index()
    table.columns = ["label", "category", "rows", "correct_share", "correct"]
    table["correct [95%]"] = [_interval(share, wilson(int(hits), int(n)), n)
                              for share, hits, n in zip(table["correct_share"], table["correct"], table["rows"])]
    table = table.drop(columns="correct")
    table["seen_in_train"] = table["category"].isin(seen)
    attacks = official[official["label"] == 1]
    report["official_recall_seen"] = float(attacks[attacks["category"].isin(seen)]["predicted"].mean())
    report["official_recall_unseen"] = float(attacks[~attacks["category"].isin(seen)]["predicted"].mean())
    return report, table, frame


def print_mistakes(frame, set_name):
    wrong = frame[(frame["set"] == set_name) & (frame["predicted"] != frame["label"])]
    print(f"\n{set_name}: {len(wrong)} mistakes")
    for row in wrong.itertuples():
        kind = "missed attack" if row.label == 1 else "false alarm"
        print(f"  [{kind} / {row.category}] {' '.join(row.text.split())[:120]!r}")


def check_standards(report, suffix=""):
    checks = []
    if "official" + suffix in report:
        official = report["official" + suffix]
        checks += [("official recall", official["recall"], STANDARDS["official"]["recall"], True),
                   ("official precision", official["precision"], STANDARDS["official"]["precision"], True)]
    if "handwritten" + suffix in report:
        written = report["handwritten" + suffix]
        checks += [("hand-written recall", written["recall"], STANDARDS["handwritten"]["recall"], True),
                   ("hand-written false alarm rate", written["false_alarm_rate"],
                    STANDARDS["handwritten"]["max_false_alarm_rate"], False)]
    if "external" in report:
        checks += [("external recall", report["external"]["recall"], STANDARDS["external"]["recall"], True),
                   ("external precision", report["external"]["precision"],
                    STANDARDS["external"]["precision"], True)]
    rows, passed = [], True
    for name, value, target, higher_is_better in checks:
        ok = value >= target if higher_is_better else value <= target
        passed &= ok
        rows.append({"standard": name, "target": round(target, 3), "result": round(float(value), 3),
                     "met": "yes" if ok else "NO"})
    print(f"\n=== Standards ({'development sets' if suffix else 'held-out test sets'}) ===")
    print(pd.DataFrame(rows).to_string(index=False) if rows else "  (no set to check)")
    print("ALL STANDARDS MET" if passed else "STANDARDS NOT MET")
    return passed, rows


# -------------------------------------------------------------- candidates


def save_candidate(path, feature_set, model, units, params, threshold, calibrator):
    path.parent.mkdir(parents=True, exist_ok=True)
    joblib.dump({
        "pipeline": model, "feature_set": feature_set, "view": VIEW,
        "threshold": threshold, "calibrator": calibrator, "rule_names": feature_rules(feature_set),
        "embedding_model": EMBEDDING_MODEL, "params": params, "training_units": units,
        "window_chars": WINDOW_CHARS, "window_tokens": WINDOW_TOKENS,
    }, path)
    print(f"saved candidate {feature_set} to {path} ({units} training units)")


def build_candidate(corpus, feature_set, params, by_family, by_group, paths):
    """Threshold and calibrator from its own grouped folds (originals only), fit on everything, save."""
    threshold = choose_threshold(originals(by_group))
    calibrator = fit_calibrator(originals(by_group))
    print(f"\n### candidate {feature_set}: {params}")
    print(f"decision threshold {threshold:.3f} (keeps precision >= {MIN_PRECISION:.0%} "
          f"on held-out original texts)")
    development = {
        "held_out_family": development_report(
            by_family, threshold, f"=== {feature_set}: one whole family held out ==="),
        "held_out_payloads": development_report(
            by_group.assign(fold=by_group["source"]), threshold,
            f"=== {feature_set}: payload groups held out, all sources in training ==="),
    }
    model, units = fit(corpus, feature_set, params, corpus.texts["role"] == "train")
    save_candidate(paths["candidates"] / f"{feature_set}.pkl", feature_set, model, units,
                   params, threshold, calibrator)
    return {"model": model, "threshold": threshold, "calibrator": calibrator, "params": params,
            "development": {k: {"scores": s, "tables": t} for k, (s, t) in development.items()}}


def dev_set_report(corpus, feature_set, candidate):
    """Scores on the development sets, with mistakes listed for the hand-written ones."""
    dev, table, frame = held_out_report(corpus, feature_set, candidate["model"], candidate["threshold"], "dev")
    print(f"\n=== {feature_set} on the development sets (held out, but used to guide improvements) ===")
    for name in sorted(k for k, v in dev.items() if isinstance(v, dict) and "n" in v):
        print_scores(name.upper(), dev[name])
    if len(table):
        print("\nofficial_dev by category (correct_share = recall for attacks):")
        print(table.round(3).to_string(index=False))
    shown = frame.assign(text=frame["text"].str[-150:]).drop_duplicates("text")
    for name in ("official_dev", "handwritten_dev", "handwritten_dev3", "handwritten_dev4", "agent_drafted_dev5"):
        if name in dev:
            print_mistakes(shown, name)
    if "probe_dev" in dev and "slice" in frame.columns:
        probe = frame[frame["set"] == "probe_dev"]
        print("\nprobe_dev by slice (mistakes / rows):")
        by_slice = probe.assign(wrong=probe["predicted"] != probe["label"]).groupby("slice")["wrong"]
        print(by_slice.agg(["sum", "size"]).rename(columns={"sum": "mistakes", "size": "rows"}).to_string())
    _, rows = check_standards(dev, suffix="_dev")
    return {"scores": dev, "standards": rows, "official_by_category": table.to_dict("records")}


def ablation_row(corpus, feature_set, folds, n_jobs):
    """One feature set, tuned on the grouped folds only and scored on the development sets."""
    params, _, _, by_group = select_params(
        corpus, feature_set, param_grid(feature_set, ABLATION_GRID), ([], folds[1]), n_jobs)
    model, _ = fit(corpus, feature_set, params, corpus.texts["role"] == "train")
    report, _, _ = held_out_report(corpus, feature_set, model, choose_threshold(originals(by_group)), "dev")
    row = {"features": feature_set, "kernel": params["svc__kernel"]}
    for name in ("official_dev", "handwritten_dev", "handwritten_dev3", "probe_dev"):
        if name in report:
            s = report[name]
            row.update({f"{name}_recall": s["recall"], f"{name}_recall_ci": s["recall_ci"],
                        f"{name}_false_alarms": s["fp"], f"{name}_false_alarm_rate": s["false_alarm_rate"],
                        f"{name}_false_alarm_ci": s["false_alarm_ci"],
                        f"{name}_attacks": s["tp"] + s["fn"], f"{name}_benign": s["fp"] + s["tn"]})
    return row


def ablation_table(rows):
    """The ablation rows as a printable table, recall and false-alarm rate with Wilson intervals."""
    printed = []
    for row in rows:
        line = {"features": row["features"], "kernel": row["kernel"]}
        for name in ("official_dev", "handwritten_dev", "handwritten_dev3", "probe_dev"):
            if f"{name}_recall" in row:
                line[f"{name} recall [95%]"] = _interval(
                    row[f"{name}_recall"], row[f"{name}_recall_ci"], row[f"{name}_attacks"])
                line[f"{name} fa rate [95%]"] = _interval(
                    row[f"{name}_false_alarm_rate"], row[f"{name}_false_alarm_ci"], row[f"{name}_benign"])
        printed.append(line)
    return pd.DataFrame(printed).to_string(index=False)


# ------------------------------------------------------------------- main


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--final", action="store_true",
                        help="run the gate, then score the held-out test sets with the promoted model")
    parser.add_argument("--smoke", action="store_true",
                        help="quick check on 5%% of the data; writes to a scratch folder only")
    args = parser.parse_args()

    warnings.filterwarnings("ignore")
    pd.set_option("display.width", 250)
    pd.set_option("display.max_columns", 30)
    paths = output_paths(args.smoke)
    n_jobs = 2 if args.smoke else -1
    if args.smoke:
        import torch
        torch.set_num_threads(2)
        print(f"SMOKE RUN: {SMOKE_FRACTION:.0%} of the data, one grid setting, 3 folds; output in {paths['model'].parents[2]}")
        if args.final:
            print("--final is ignored in a smoke run: test sets are only scored by a real run")
            args.final = False

    corpus = build_corpus(with_tests=args.final, smoke=args.smoke)
    train = corpus.texts[corpus.texts["role"] == "train"]
    print(train.groupby(["kind", "label"]).size().unstack(fill_value=0).to_string())
    print(train[train["kind"] == "original"].groupby(["family", "source"]).size().to_string())
    folds = make_folds(corpus, args.smoke)

    tuned = CANDIDATES[0]
    grid = param_grid(tuned)[:1] if args.smoke else param_grid(tuned)
    params, ranking, by_family, by_group = select_params(corpus, tuned, grid, folds, n_jobs)
    print(f"\nchosen parameters for {tuned} (development ranking score {ranking:.3f}): {params}")

    candidates, metrics = {}, {"params": params, "candidates": {}}
    candidates[tuned] = build_candidate(corpus, tuned, params, by_family, by_group, paths)
    for feature_set in CANDIDATES[1:]:
        (by_family, by_group), = out_of_fold(corpus, feature_set, [params], folds, n_jobs).values()
        candidates[feature_set] = build_candidate(corpus, feature_set, params, by_family, by_group, paths)
    for feature_set, candidate in candidates.items():
        candidate["development_sets"] = dev_set_report(corpus, feature_set, candidate)
        metrics["candidates"][feature_set] = {k: candidate[k] for k in
                                              ("threshold", "calibrator", "params", "development", "development_sets")}

    if args.final:
        ablation = [ablation_row(corpus, feature_set, folds, n_jobs) for feature_set in FEATURE_SETS]
        print("\n=== Ablation on the development sets ===")
        print(ablation_table(ablation))
        metrics["ablation"] = ablation

        from .gate import run_gate
        promoted = run_gate(paths)
        metrics["promoted"] = promoted
        if promoted is None:
            print("\nno candidate passed the gate: the test sets were not scored. The round-four "
                  "test numbers stand (backup_round4/report/metrics.json).")
        else:
            candidate = candidates[promoted]
            report, table, frame = held_out_report(
                corpus, promoted, candidate["model"], candidate["threshold"], "test")
            print(f"\n=== Final model ({promoted}) on the held-out test sets ===")
            for name in ["official"] + EXTERNAL_SETS + ["external"] + NEW_SETS + ["external_new", "handwritten"]:
                if name in report:
                    print_scores(name.upper(), report[name])
            print("\nofficial test (final half) by category (correct_share = recall for attacks):")
            print(table.round(3).to_string(index=False))
            print_mistakes(frame, "handwritten")
            _, rows = check_standards(report)
            metrics.update({"tests": report, "standards": rows,
                            "official_by_category": table.to_dict("records")})

    paths["metrics"].parent.mkdir(parents=True, exist_ok=True)
    paths["metrics"].write_text(json.dumps(metrics, indent=2, default=str))
    print(f"saved metrics to {paths['metrics']}")


if __name__ == "__main__":
    main()
