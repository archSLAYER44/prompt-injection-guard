# backup_round4: the round-four detector, frozen

Copied from the working tree at commit 55d9726 on 2026-10-04 (everything except .git, .venv, backup_round3,
data/cache, data/raw, src/models/candidates and caches). The round-four model is git tag `model-frozen`
(commit f10a911); since that tag `src/` changed only in `src/predict.py`, which gained the read-only
`explain()` function (115 lines added, none removed), so `predict()` here is the round-four `predict()`
exactly. `src/models/injection_model.pkl` sha1: 7165962019c3d48372e51ca1a09c294f1e146e26.

The round-five gate (`src/gate.py`) runs this copy's own `src.predict` in a subprocess to get the
champion's verdicts. `report/champion_dev_scores.csv` here is the ROUND-THREE verdict cache that round
four was gated against; it was moved out of `report/` so that round five computes round four's verdicts
fresh. `report/metrics.json`, `report/train_log.txt` and `report/writeup.md` are the round-four
records; `data/new_train.csv` and `data/new_test.csv` are the round-four versions of the six-source files.
