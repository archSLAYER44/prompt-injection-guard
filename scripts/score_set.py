"""Score one held-out CSV (text,label,category) ONCE on the saved model, through predict().

    .venv/bin/python scripts/score_set.py /path/to/set6.csv --name set6 [--out-dir report] [--force]

Writes <out-dir>/<name>_scored.csv (label, category, verdict, score, confidence, fired rules, text) and
<name>_summary.json, and prints tn/fp/fn/tp, precision, recall, F1 and the false-alarm rate against the
hand-written standards, the per-category table and every mistake. It refuses to overwrite an existing
<name>_scored.csv without --force, so a set is scored once. It records the model's sha1, the git commit
and the input's md5, so the record says which model saw which file.
"""
import argparse
import csv
import hashlib
import json
import subprocess
import sys
import time
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def main():
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("csv", type=Path)
    parser.add_argument("--name", required=True, help="prefix of the output files, e.g. set6")
    parser.add_argument("--out-dir", type=Path, default=ROOT / "report")
    parser.add_argument("--force", action="store_true", help="overwrite an existing scored file")
    args = parser.parse_args()
    out_csv = args.out_dir / f"{args.name}_scored.csv"
    if out_csv.exists() and not args.force:
        sys.exit(f"{out_csv} exists: this set was scored already. A held-out set is scored once; use --force only to redo a broken run.")

    from sklearn.metrics import confusion_matrix, precision_recall_fscore_support
    from src.predict import MODEL_PATH, load_model, predict, score_texts
    from src.train import STANDARDS

    rows = list(csv.DictReader(args.csv.open(encoding="utf-8", newline="")))
    texts = [r["text"] for r in rows]
    y = [int(r["label"]) for r in rows]
    assert set(y) <= {0, 1}, "labels must be 0/1"
    model = load_model()
    threshold = float(model["threshold"])
    commit = subprocess.run(["git", "rev-parse", "--short", "HEAD"], capture_output=True, text=True, cwd=ROOT).stdout.strip()
    model_sha1 = hashlib.sha1(MODEL_PATH.read_bytes()).hexdigest()[:12]
    input_md5 = hashlib.md5(args.csv.read_bytes()).hexdigest()
    print(f"model {MODEL_PATH.name} sha1 {model_sha1}, threshold {threshold:.4f}, commit {commit or '?'}, input md5 {input_md5}")

    started = time.time()
    decisions, _ = score_texts(model, texts)
    preds, scored = [], []
    for r, d in zip(rows, decisions):
        res = predict(r["text"])
        assert res["is_injection"] == (d >= threshold), f"batch and single scoring disagree on: {r['text'][:60]}"
        preds.append(int(res["is_injection"]))
        scored.append({"label": int(r["label"]), "category": r.get("category", ""), "verdict": res["verdict"],
                       "score": round(float(d), 4), "confidence": round(res["confidence"], 4),
                       "segment_kind": res["segment_kind"],
                       "fired": ";".join(f"{k}={v['value']:.3g}" for k, v in res["fired"].items()), "text": r["text"]})
    tn, fp, fn, tp = (int(v) for v in confusion_matrix(y, preds, labels=[0, 1]).ravel())
    p, rc, f1, _ = precision_recall_fscore_support(y, preds, average="binary", zero_division=0)
    benign = tn + fp
    fa_rate = fp / benign if benign else None
    standard = STANDARDS["handwritten"]
    print(f"rows {len(rows)} ({sum(y)} attacks, {benign} benign), scored in {time.time() - started:.0f}s")
    print(f"tn {tn}  fp {fp}  fn {fn}  tp {tp}")
    print(f"precision {p:.4f}  recall {rc:.4f}  f1 {f1:.4f}")
    print(f"recall standard >= {standard['recall']:.0%}: {'met' if rc >= standard['recall'] else 'MISSED'} ({rc:.1%})")
    if fa_rate is not None:
        print(f"false-alarm rate {fp}/{benign} = {fa_rate:.1%}, standard <= {standard['max_false_alarm_rate']:.1%}: "
              f"{'met' if fa_rate <= standard['max_false_alarm_rate'] else 'MISSED'}")

    print("\nper category (label, n, correct, wrong):")
    by_cat = defaultdict(lambda: [0, 0, 0])
    for s, pr in zip(scored, preds):
        c = by_cat[(s["category"], s["label"])]
        c[0] += 1
        c[1 if pr == s["label"] else 2] += 1
    for (cat, lab), (n, ok, bad) in sorted(by_cat.items(), key=lambda kv: (-kv[0][1], kv[0][0])):
        print(f"  {cat:<36} label {lab}  n {n:>2}  correct {ok:>2}  wrong {bad}")
    print("\nmistakes:")
    for s, pr in zip(scored, preds):
        if pr != s["label"]:
            kind = "FALSE ALARM" if s["label"] == 0 else "MISSED"
            print(f"  [{kind}] {s['category']} score {s['score']:+.3f} fired: {s['fired'] or '-'}")
            print(f"      {' '.join(s['text'].split())[:220]}")

    args.out_dir.mkdir(parents=True, exist_ok=True)
    with out_csv.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=list(scored[0].keys()))
        writer.writeheader()
        writer.writerows(scored)
    summary = {"name": args.name, "input": str(args.csv), "input_md5": input_md5, "model_sha1": model_sha1, "commit": commit,
               "threshold": threshold, "rows": len(rows), "tn": tn, "fp": fp, "fn": fn, "tp": tp,
               "precision": float(p), "recall": float(rc), "f1": float(f1), "false_alarm_rate": fa_rate,
               "scored_at": time.strftime("%Y-%m-%d %H:%M:%S")}
    (args.out_dir / f"{args.name}_summary.json").write_text(json.dumps(summary, indent=2))
    print(f"\nwrote {out_csv} and {args.name}_summary.json")


if __name__ == "__main__":
    main()
