"""Write the charts that report/writeup.md embeds, from report/metrics.json and the training pool.

    .venv/bin/python scripts/make_charts.py

Charts: training_sources.png, rule_firing_rates.png, recall_by_attack_type.png, ablation_recall.png.
A chart whose data is missing from metrics.json (for example the test categories when no candidate
was promoted) is skipped with a message.
"""
import json
import sys
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from src.dataset import load_pool
from src.features import firing_rates
from src.rules import DESCRIPTIVE_RULES

OUT = ROOT / "report"
BENIGN, INJECTION = "#2a78d6", "#eb6834"
SURFACE, INK, MUTED, GRID = "#fcfcfb", "#0b0b0b", "#52514e", "#e1e0d9"
FEATURE_LABELS = {"legacy6": "original 6 rules", "rules16": "16 rules", "emb": "embedding",
                  "emb+rules16": "embedding + 16 rules", "emb+rules20": "embedding + 20 rules"}


def style(ax, title, xlabel=""):
    ax.set_title(title, loc="left", fontsize=12, color=INK, pad=12)
    ax.set_xlabel(xlabel, color=MUTED, fontsize=9)
    ax.set_facecolor(SURFACE)
    ax.figure.set_facecolor(SURFACE)
    ax.grid(axis="x", color=GRID, linewidth=1)
    ax.set_axisbelow(True)
    ax.tick_params(colors=MUTED, labelsize=9, length=0)
    for side in ("top", "right", "left"):
        ax.spines[side].set_visible(False)
    ax.spines["bottom"].set_color("#c3c2b7")


def label_bars(ax, bars, fmt):
    for bar in bars:
        ax.text(bar.get_width(), bar.get_y() + bar.get_height() / 2, " " + fmt(bar.get_width()),
                va="center", ha="left", fontsize=8, color=MUTED)


def save(fig, name):
    fig.tight_layout()
    fig.savefig(OUT / name, dpi=150)
    plt.close(fig)
    print(f"wrote report/{name}")


def grouped_barh(ax, names, top_values, bottom_values, top_label, bottom_label, fmt):
    y = range(len(names))
    top = ax.barh([i + 0.19 for i in y], top_values, height=0.34, color=BENIGN, label=top_label)
    bottom = ax.barh([i - 0.19 for i in y], bottom_values, height=0.34, color=INJECTION, label=bottom_label)
    label_bars(ax, top, fmt)
    label_bars(ax, bottom, fmt)
    ax.set_yticks(list(y))
    ax.set_yticklabels(names)
    ax.legend(frameon=False, fontsize=9, loc="lower right")


def training_sources(pool):
    counts = pool.groupby(["source", "label"]).size().unstack(fill_value=0).sort_values(1, ascending=True)
    fig, ax = plt.subplots(figsize=(8, 0.45 * len(counts) + 1.5))
    grouped_barh(ax, list(counts.index), counts[0], counts[1], "benign", "injection", lambda v: f"{int(v):,}")
    style(ax, "Training rows by source", "rows")
    save(fig, "training_sources.png")


def rule_firing(pool):
    rates = firing_rates(pool)
    rates = rates[~rates["descriptive"]].sort_values("fires_injection")
    fig, ax = plt.subplots(figsize=(8, 0.4 * len(rates) + 1.5))
    grouped_barh(ax, list(rates.index), rates["fires_benign"] * 100, rates["fires_injection"] * 100,
                 "benign texts", "injection texts", lambda v: f"{v:.1f}%")
    ax.set_xlim(0, 110)
    style(ax, "Share of training texts on which each rule fires", "texts (%)")
    save(fig, "rule_firing_rates.png")


def recall_by_attack_type(metrics):
    rows = pd.DataFrame(metrics.get("official_by_category", []))
    if not len(rows):
        print("skipped recall_by_attack_type.png: no official test categories in metrics.json")
        return
    attacks = rows[rows["label"] == 1].sort_values("correct_share")
    names = [f"{r.category}{'' if r.seen_in_train else ' (unseen type)'}" for r in attacks.itertuples()]
    fig, ax = plt.subplots(figsize=(8, 2.8))
    bars = ax.barh(names, attacks["correct_share"] * 100, height=0.45, color=INJECTION)
    label_bars(ax, bars, lambda v: f"{v:.0f}%")
    ax.set_xlim(0, 110)
    style(ax, "Official test: share of attacks caught, by attack type", "recall (%)")
    save(fig, "recall_by_attack_type.png")


def ablation(metrics):
    rows = metrics.get("ablation")
    if not rows:
        print("skipped ablation_recall.png: no ablation in metrics.json")
        return
    table = pd.DataFrame(rows).set_index("features")
    names = [FEATURE_LABELS.get(f, f) for f in table.index]
    fig, ax = plt.subplots(figsize=(8, 3.6))
    grouped_barh(ax, names, table["official_dev_recall"] * 100, table["probe_dev_recall"] * 100,
                 "official development half", "probe set", lambda v: f"{v:.0f}")
    ax.set_xlim(0, 110)
    style(ax, "Attacks caught, by feature set (development sets)", "recall (%)")
    save(fig, "ablation_recall.png")


def main():
    metrics = json.loads((OUT / "metrics.json").read_text())
    recall_by_attack_type(metrics)
    ablation(metrics)
    pool = load_pool()
    training_sources(pool)
    rule_firing(pool)


if __name__ == "__main__":
    main()
