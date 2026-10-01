"""Out-of-fold scores of the chosen setting on the grouped folds; threshold per precision floor (development data only)."""
import sys, warnings
from pathlib import Path
import numpy as np, pandas as pd
warnings.filterwarnings("ignore")
sys.path.insert(0, ".")
from sklearn.metrics import precision_recall_curve
from src.train import build_corpus, make_folds, out_of_fold, originals

S = Path(sys.argv[1])
PARAMS = {"svc__kernel": "linear", "svc__C": 0.3, "features__rules__weight__weight": 1.0}
POOLED = ["official_dev", "handwritten_dev", "handwritten_dev3"]

corpus = build_corpus(with_tests=True)
folds = make_folds(corpus)
print(f"family folds {len(folds[0])}, grouped folds {len(folds[1])}", flush=True)
(_, by_group), = out_of_fold(corpus, "emb+rules20", [PARAMS], ([], folds[1]), n_jobs=-1).values()
oof = originals(by_group)
oof.to_csv(S / "oof_group_rules20.csv", index=False)
print(f"out-of-fold original texts: {len(oof)} ({int(oof['label'].sum())} attacks)", flush=True)

champ = pd.read_csv("report/champion_dev_scores.csv", keep_default_na=False)
lookup = dict(zip(zip(champ["set"], champ["key"]), champ["predicted"].astype(int)))
dev = pd.read_csv(S / "dev_scores_emb+rules20.csv", keep_default_na=False)
dev["champion"] = [lookup[(s, k)] for s, k in zip(dev["set"], dev["key"])]

def counts(frame, pred):
    return int(((pred == 1) & (frame["label"] == 0)).sum()), int(((pred == 0) & (frame["label"] == 1)).sum())

pooled = dev[dev["set"].isin(POOLED)]; probe = dev[dev["set"] == "probe_dev"]
print("champion: pooled FA/miss", counts(pooled, pooled["champion"]), "probe FA/miss", counts(probe, probe["champion"]))

precision, recall, thresholds = precision_recall_curve(oof["label"], oof["score"])
print(f"\n{'floor':>6} {'threshold':>9} {'oof prec':>8} {'oof recall':>10} {'pooled FA/miss':>14} {'probe FA/miss':>13}  gate")
for floor in [0.98, 0.97, 0.96, 0.95, 0.94, 0.93, 0.92, 0.91, 0.90, 0.88, 0.85]:
    ok = precision[:-1] >= floor
    if not ok.any():
        print(f"{floor:6.2f}  none"); continue
    t = float(thresholds[ok][np.argmax(recall[:-1][ok])])
    pred = (oof["score"] >= t).astype(int)
    p = ((pred == 1) & (oof["label"] == 1)).sum() / max(1, (pred == 1).sum()); r = ((pred == 1) & (oof["label"] == 1)).sum() / oof["label"].sum()
    pf, pm = counts(pooled, (pooled["score"] >= t).astype(int)); qf, qm = counts(probe, (probe["score"] >= t).astype(int))
    kf, km = counts(pooled, pooled["champion"]); jf, jm = counts(probe, probe["champion"])
    gate = "PASS" if (pf <= kf and pm <= km and qf <= jf and qm < jm) else "fail"
    print(f"{floor:6.2f} {t:9.3f} {p:8.3f} {r:10.3f} {pf:6d}/{pm:<7d} {qf:6d}/{qm:<6d}  {gate}")

print("\nout-of-fold false alarms by source at a few thresholds (benign originals only):")
ben = oof[oof["label"] == 0]
for t in [0.544, 0.7, 0.85, 1.0, 1.304]:
    fa = ben[ben["score"] >= t].groupby("source").size().to_dict()
    print(f"  t={t:5.3f}: total {sum(fa.values())} {fa}")
print("benign originals per source:", ben.groupby("source").size().to_dict())
