"""Train the SVM, check it on development folds, and save the final model.

    python -m src.train            development numbers only (no test set is touched)
    python -m src.train --final    also run the ablation and score the held-out test sets

Three kinds of data, kept apart:
    train   fitted on
    dev     never fitted on, used to find mistakes and make decisions
    test    never fitted on and never used for a decision; scored only with --final
"""
import argparse
import itertools
import json
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
from .dataset import load_dev_sets, load_pool, load_tests, load_train, payload_group
from .features import EMBEDDING_MODEL, legacy_matrix, rule_matrix
from .pipeline import FEATURE_SETS, assemble, build_model, embed_view
from .rules import DESCRIPTIVE_RULES, RULE_NAMES
from .windows import split_units

ROOT = Path(__file__).resolve().parent.parent
MODEL_PATH = ROOT / "src" / "models" / "injection_model.pkl"
METRICS_PATH = ROOT / "report" / "metrics.json"

SEED = 42
VIEW = "norm"
FINAL_FEATURE_SET = "emb+rules16"
WINDOW_LIMIT = 12           # windows scored per text during evaluation
SENTENCE_LIMIT = 16         # single sentences scored per text during evaluation
TRAIN_LIMIT = 3             # windows, and sentences, that one training text contributes
EMBEDDED_ATTACKS = {"indirect_injection", "appended_override"}   # last sentence is the payload
SUSPICIOUS_ACCURACY = 0.97
MIN_PRECISION = 0.98        # the threshold is the most sensitive one that keeps this precision

STANDARDS = {
    "official": {"recall": 0.90, "precision": 0.95},
    "external": {"recall": 0.85, "precision": 0.90},
    "handwritten": {"recall": 0.85, "max_false_alarm_rate": 2 / 28},
}

SVC_GRID = (
    [{"svc__kernel": "linear", "svc__C": c} for c in (0.3, 1)]
    + [{"svc__kernel": "rbf", "svc__C": c, "svc__gamma": "scale"} for c in (1, 3)]
)
RULE_WEIGHTS = (0.3, 1.0)
ABLATION_GRID = [{"svc__kernel": "linear", "svc__C": 1},
                 {"svc__kernel": "rbf", "svc__C": 1, "svc__gamma": "scale"}]
CONTENT_RULES = [i for i, n in enumerate(RULE_NAMES) if n in {
    "override_phrase_count", "role_reassignment_score", "delimiter_mimicry_count",
    "authority_claim_count", "indirect_address_count", "exfiltration_count",
    "output_manipulation_count", "hypothetical_framing_count"}]


def param_grid(feature_set):
    if feature_set != "emb+rules16":
        return SVC_GRID
    return [dict(g, features__rules__weight__weight=w) for g in SVC_GRID for w in RULE_WEIGHTS]


# ------------------------------------------------------------------ corpus


class Corpus:
    """Every text, the units it is split into, and the feature blocks of every unit."""

    def __init__(self, texts):
        self.texts = texts.reset_index(drop=True)
        rows = []
        for text_id, text in enumerate(self.texts["text"]):
            for kind, unit in split_units(text, WINDOW_LIMIT, SENTENCE_LIMIT):
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

    def unit_rows(self, text_mask, training):
        mask = text_mask.to_numpy()[self.units["text_id"]]
        if not training:
            return np.flatnonzero(mask)
        mask &= self.units["for_training"].to_numpy() & ~self.ambiguous
        rows = np.flatnonzero(mask)
        # the datasets repeat the same sentences many times; one copy of each is enough
        return rows[~self.units["unit"].iloc[rows].duplicated().to_numpy()]

    def text_scores(self, unit_rows, unit_scores):
        """Score of a text = score of its most suspicious unit."""
        ids = self.units["text_id"].to_numpy()[unit_rows]
        best = pd.Series(unit_scores).groupby(ids).max()
        return best.index.to_numpy(), best.to_numpy()


def build_corpus(with_tests):
    pool = load_pool().assign(kind="original", role="train", set="train")
    pool["group"] = pool["text"].map(payload_group)
    pool["parent"] = pool.index

    copies_a = augment(pool, templates="a", seed=SEED).assign(kind="aug_a")
    copies_b = augment(pool, templates="b", seed=SEED + 1).assign(kind="aug_b")
    parts = [pool, copies_a, copies_b]
    held_out = [("dev", load_dev_sets())] + ([("test", load_tests())] if with_tests else [])
    for role, sets in held_out:
        for name, frame in sets.items():
            parts.append(frame.assign(kind="held_out", role=role, set=name, group="", parent=-1))
    return Corpus(pd.concat(parts, ignore_index=True))


# ------------------------------------------------------------- evaluation


def scores(y_true, y_pred):
    precision, recall, f1, _ = precision_recall_fscore_support(
        y_true, y_pred, labels=[1], average=None, zero_division=0)
    tn, fp, fn, tp = confusion_matrix(y_true, y_pred, labels=[0, 1]).ravel()
    return {
        "n": int(len(y_true)), "accuracy": float(accuracy_score(y_true, y_pred)),
        "precision": float(precision[0]), "recall": float(recall[0]), "f1": float(f1[0]),
        "tn": int(tn), "fp": int(fp), "fn": int(fn), "tp": int(tp),
    }


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


def leave_one_source_out(corpus):
    """Folds that hold out one whole data source; its copies use unseen wording (set b)."""
    texts = corpus.texts
    for source in sorted(texts.loc[texts["role"] == "train", "source"].unique()):
        train = (texts["role"] == "train") & (texts["source"] != source) \
            & texts["kind"].isin(["original", "aug_a"])
        held = (texts["role"] == "train") & (texts["source"] == source) \
            & texts["kind"].isin(["original", "aug_b"])
        yield source, train, held


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


def select_params(corpus, feature_set, grid, source_folds=True):
    """Grid search on development folds only.

    Each setting is scored by average precision (how well it ranks injections above
    benign texts) on two kinds of held-out text: a whole source it never trained on,
    and unseen payloads from sources it did train on. The two are averaged.

    Returns the best setting, its score, and its held-out scores for both kinds of fold.
    """
    by_source = list(leave_one_source_out(corpus)) if source_folds else []
    folds = by_source + list(grouped_folds(corpus))
    results = Parallel(n_jobs=-1)(
        delayed(fit_and_score)(corpus, feature_set, params, train, held)
        for params, (_, train, held) in itertools.product(grid, folds))

    def frame(chunk, names):
        parts = [
            corpus.texts.loc[ids, ["label", "source", "kind", "category"]].assign(
                fold=name, score=values)
            for (ids, values), name in zip(chunk, names)]
        return pd.concat(parts) if parts else None

    best = None
    for i, params in enumerate(grid):
        chunk = results[i * len(folds):(i + 1) * len(folds)]
        names = [name for name, _, _ in folds]
        source = frame(chunk[:len(by_source)], names[:len(by_source)])
        group = frame(chunk[len(by_source):], names[len(by_source):])
        ranking = [average_precision_score(f["label"], f["score"])
                   for f in (source, group) if f is not None]
        if best is None or np.mean(ranking) > best[1]:
            best = (params, float(np.mean(ranking)), source, group)
    return best


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
    print(f"\n{title}")
    rows = []
    oof = oof.assign(kind=oof["kind"].str.replace(r"aug_.", "obfuscated copy", regex=True))
    for (fold, kind), part in oof.groupby(["fold", "kind"]):
        s = scores(part["label"], (part["score"] >= threshold).astype(int))
        rows.append({"held out": fold, "texts": kind, "rows": s["n"], "precision": s["precision"],
                     "recall": s["recall"], "f1": s["f1"], "false alarms": s["fp"], "missed": s["fn"]})
    total = scores(oof["label"], (oof["score"] >= threshold).astype(int))
    rows.append({"held out": "ALL", "texts": "", "rows": total["n"], "precision": total["precision"],
                 "recall": total["recall"], "f1": total["f1"], "false alarms": total["fp"],
                 "missed": total["fn"]})
    print(pd.DataFrame(rows).round(3).to_string(index=False))
    return total


def print_scores(name, s):
    print(f"\n{name} ({s['n']} rows)")
    print(f"  accuracy {s['accuracy']:.3f} | injection precision {s['precision']:.3f} "
          f"recall {s['recall']:.3f} F1 {s['f1']:.3f}")
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
    external = frame[frame["set"].isin(["deepset", "gandalf", "jackhhao"])]
    if len(external):
        report["external"] = scores(external["label"], external["predicted"])

    official = frame[frame["set"].str.startswith("official")]
    seen = set(load_train()["category"])
    table = official.assign(correct=official["predicted"] == official["label"]).groupby(
        ["label", "category"])["correct"].agg(["size", "mean"]).reset_index()
    table.columns = ["label", "category", "rows", "correct_share"]
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
    official, written = report["official" + suffix], report["handwritten" + suffix]
    checks = [
        ("official recall", official["recall"], STANDARDS["official"]["recall"], True),
        ("official precision", official["precision"], STANDARDS["official"]["precision"], True),
        ("hand-written recall", written["recall"], STANDARDS["handwritten"]["recall"], True),
        ("hand-written false alarm rate", written["fp"] / (written["fp"] + written["tn"]),
         STANDARDS["handwritten"]["max_false_alarm_rate"], False),
    ]
    if "external" in report:
        checks += [
            ("external recall", report["external"]["recall"], STANDARDS["external"]["recall"], True),
            ("external precision", report["external"]["precision"],
             STANDARDS["external"]["precision"], True),
        ]
    rows, passed = [], True
    for name, value, target, higher_is_better in checks:
        ok = value >= target if higher_is_better else value <= target
        passed &= ok
        rows.append({"standard": name, "target": target, "result": round(float(value), 3),
                     "met": "yes" if ok else "NO"})
    print(f"\n=== Standards ({'development sets' if suffix else 'held-out test sets'}) ===")
    print(pd.DataFrame(rows).to_string(index=False))
    print("ALL STANDARDS MET" if passed else "STANDARDS NOT MET")
    return passed, rows


# ------------------------------------------------------------------- main


def save_model(model, units, params, threshold, calibrator):
    MODEL_PATH.parent.mkdir(parents=True, exist_ok=True)
    joblib.dump({
        "pipeline": model, "feature_set": FINAL_FEATURE_SET, "view": VIEW,
        "threshold": threshold, "calibrator": calibrator, "rule_names": RULE_NAMES,
        "embedding_model": EMBEDDING_MODEL, "params": params, "training_units": units,
    }, MODEL_PATH)
    print(f"\nsaved model to {MODEL_PATH.relative_to(ROOT)} ({units} training units)")


def ablation_row(corpus, feature_set):
    grid = ABLATION_GRID if feature_set != "emb+rules16" else [
        dict(g, features__rules__weight__weight=1.0) for g in ABLATION_GRID]
    params, _, _, by_group = select_params(corpus, feature_set, grid, source_folds=False)
    model, _ = fit(corpus, feature_set, params, corpus.texts["role"] == "train")
    report, _, _ = held_out_report(corpus, feature_set, model, choose_threshold(by_group), "test")
    return {
        "features": feature_set, "kernel": params["svc__kernel"],
        "official_precision": report["official"]["precision"],
        "official_recall": report["official"]["recall"],
        "official_f1": report["official"]["f1"],
        "recall_unseen_types": report["official_recall_unseen"],
        "external_precision": report["external"]["precision"],
        "external_recall": report["external"]["recall"],
        "external_f1": report["external"]["f1"],
        "handwritten_recall": report["handwritten"]["recall"],
        "handwritten_false_alarms": report["handwritten"]["fp"],
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--final", action="store_true",
                        help="run the ablation and score the held-out test sets")
    args = parser.parse_args()

    warnings.filterwarnings("ignore")
    pd.set_option("display.width", 250)
    pd.set_option("display.max_columns", 30)

    corpus = build_corpus(with_tests=args.final)
    train = corpus.texts[corpus.texts["role"] == "train"]
    print(train.groupby(["kind", "label"]).size().unstack(fill_value=0).to_string())

    params, ranking, by_source, by_group = select_params(
        corpus, FINAL_FEATURE_SET, param_grid(FINAL_FEATURE_SET))
    print(f"\nchosen parameters (development ranking score {ranking:.3f}): {params}")
    threshold = choose_threshold(by_group)
    calibrator = fit_calibrator(by_group)
    print(f"decision threshold {threshold:.3f} (keeps precision >= {MIN_PRECISION:.0%} in development)")

    metrics = {"params": params, "threshold": threshold, "development": {
        "held_out_source": development_report(
            by_source, threshold, "=== Development: one whole source held out ==="),
        "held_out_payloads": development_report(
            by_group.assign(fold=by_group["source"]), threshold,
            "=== Development: payload groups held out, all sources in training ==="),
    }}

    model, units = fit(corpus, FINAL_FEATURE_SET, params, corpus.texts["role"] == "train")
    save_model(model, units, params, threshold, calibrator)

    dev, dev_table, dev_frame = held_out_report(corpus, FINAL_FEATURE_SET, model, threshold, "dev")
    print("\n=== Development sets (held out, but used to guide improvements) ===")
    for name in ("official_dev", "handwritten_dev"):
        print_scores(name.upper(), dev[name])
    print("\nofficial_dev by category (correct_share = recall for attacks):")
    print(dev_table.round(3).to_string(index=False))
    for name in ("official_dev", "handwritten_dev"):
        print_mistakes(dev_frame.assign(text=dev_frame["text"].str[-150:]).drop_duplicates("text"), name)
    _, dev_rows = check_standards(dev, suffix="_dev")
    metrics["development_sets"] = {"scores": dev, "standards": dev_rows,
                                   "official_by_category": dev_table.to_dict("records")}

    if args.final:
        ablation = [ablation_row(corpus, feature_set) for feature_set in FEATURE_SETS]
        print("\n=== Ablation on the held-out test sets ===")
        print(pd.DataFrame(ablation).round(3).to_string(index=False))

        report, table, frame = held_out_report(corpus, FINAL_FEATURE_SET, model, threshold, "test")
        print(f"\n=== Final model: {FINAL_FEATURE_SET} ===")
        for name in ("official", "deepset", "jackhhao", "gandalf", "external", "handwritten"):
            print_scores(name.upper(), report[name])
        print("\nofficial test (final half) by category (correct_share = recall for attacks):")
        print(table.round(3).to_string(index=False))
        print_mistakes(frame, "handwritten")

        _, rows = check_standards(report)
        metrics.update({"ablation": ablation, "tests": report, "standards": rows,
                        "official_by_category": table.to_dict("records")})

    METRICS_PATH.parent.mkdir(parents=True, exist_ok=True)
    METRICS_PATH.write_text(json.dumps(metrics, indent=2, default=str))
    print(f"saved metrics to {METRICS_PATH.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
