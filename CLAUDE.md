# Prompt injection detector

Course project. A static text classifier: one text in, verdict `injection` or `benign` out, with a
confidence and the rules that fired. No LLM API calls, nothing executed, offline after downloads.

## Rules for working here

- **The user commits to git themselves.** Never run `git add`, `git commit` or `git push`. Say when the
  work is at a good point to commit.
- **The classifier stays scikit-learn `SVC`.** It is on the course syllabus. No Random Forest, no neural
  classifier, no fine-tuned transformer.
- **The interface does not change.** `predict(text)` keeps its signature and returned keys. No second
  input, no third verdict. `cli.py` and `gui.py` call the same `predict()`.
- **Test sets are never trained on or tuned on.** Development sets guide changes; test sets are scored
  once per round. When the mistakes on a hand-written test set have been read, it becomes development
  data and a new one is written.
- **Report results as they are.** Standards that are missed are reported as missed.
- A full training run takes about 65 minutes with a warm embedding cache (up to 2 hours cold) and uses
  all 8 CPU cores. Ask before starting one if the user may be away or asleep. The laptop must be on AC
  power (a run drained the battery on 2026-10-01); see the machine notes below.
- Always use `.venv/bin/python`. The GUI needs Tk (`sudo pacman -S tk`).

## Layout

| Path | Purpose |
|---|---|
| `src/normalize.py` | Normalization and de-obfuscation (leetspeak, base64, hex, rot13, split payloads) |
| `src/rules.py` | The rule features (16 in round three, 20 in the round-four code) |
| `src/windows.py` | Splits a text into windows, sentences and decoded readings |
| `src/features.py` | Sentence embedding (`paraphrase-multilingual-MiniLM-L12-v2`) with an on-disk cache |
| `src/augment.py` | Obfuscated training copies |
| `src/dataset.py` | Loading, duplicate checks, train / development / test separation |
| `src/pipeline.py` | The SVM pipeline |
| `src/train.py` | Parameter search, evaluation, saves `src/models/injection_model.pkl` |
| `src/predict.py` | `predict(text)` |
| `src/gate.py` | Compares saved candidates with the round-three model on development data, promotes or keeps |
| `scripts/` | Dataset download (`download_dataset.py`, `download_new_sources.py`), contrast set generator, rule checks, notebook builder |
| `report/writeup.md` | Full write-up with results and limitations |
| `backup_round3/` | Frozen, runnable copy of round three (code, model, reports) |

## Commands

```bash
.venv/bin/python cli.py check-text "some text"
.venv/bin/python gui.py
.venv/bin/python -m src.dataset          # balance and duplicate report
.venv/bin/python -m src.train            # development numbers only
.venv/bin/python -m src.train --final    # also scores the held-out test sets (~65 min warm)
```

## Status: round four is complete, not yet committed (2026-10-01 18:38)

Model in `src/models/injection_model.pkl`: embedding + 20 rules, linear SVC, C = 0.3, rule weight 1.0,
bounded rule scaling, threshold 0.548 (96% precision floor), 36,312 training pieces. Promoted by the
gate over round three on development data; the held-out test sets were scored once, by the same run.
Write-up: `report/writeup.md`. Record of the round, including the rejected first run:
`report/round_four_results.md`. Round three stays runnable in `backup_round3/`.

| Standard | Target | Result | Met |
|---|---|---|---|
| Official test recall | >= 90% | 98.6% | yes |
| Official test precision | >= 95% | 99.8% | yes |
| External tests recall | >= 85% | 79.6% | no |
| External tests precision | >= 90% | 96.9% | yes |
| Hand-written recall (set 4) | >= 85% | 89.2% | yes |
| Hand-written false alarms (set 4) | <= 7.1% | 5.0% (3 in 60) | yes |

New sources, scored once: wild 64.9% precision / 75.0% recall (27% false alarms on real benign
prompts), llmail 100% / 93.8%, gsum 53.8% recall, yanis 46.1% recall, aya 1 false alarm in 198,
dolly 0 in 231. Hand-written set 4 and the new-source test splits have now been read: **they are
development data from here on; round five needs new held-out sets.**

### How round four got here (2026-10-01)

1. Build workflow (new data, four rules, decoder/window/leakage/scaling fixes, probe and test sets).
2. First `--final` run with the round-three 98% floor and a no-tolerance gate: rejected. The new
   benign in-the-wild prompts pushed the threshold to 1.304 and recall on the official development
   half to 81%. Log kept as `report/train_log_round4_p98.txt`, metrics as `report/metrics_round4_p98.json`.
3. Out-of-fold scores recomputed (`scripts/oof_floor_check.py`, `report/round_four_scores/`): at a 96%
   floor the candidate beats round three on three of four gate counts and loses by one false alarm.
4. User's decision: `MIN_PRECISION = 0.96` in `src/train.py`, `TOLERANCE = 1` in `src/gate.py`
   (total mistakes not higher, neither count higher by more than one; probe misses strictly lower).
   Both changes made after seeing step 2, before any test set was scored; the write-up says so.
5. Retrain 17:10 to 18:38: gate PASS (pooled 7 / 7 against 6 / 10; probe 12 / 24 against 13 / 33),
   20-rule model promoted, test sets scored, write-up, charts (`scripts/make_charts.py`) and notebook
   rebuilt.

### Housekeeping

- `src/models/candidates/` (47 MB) and `data/raw/new/` (613 MB, git-ignored) can be deleted.
- `data/cache/embeddings_norm.npy` is tracked in git and is now 130 MB.
- A full run is about 65 minutes with a warm embedding cache, plus about 25 minutes per 40,000 new
  pieces. It needs AC power: start it with `setsid nohup ... & disown` and hold
  `systemd-inhibit --what=sleep:idle:handle-lid-switch --mode=block` while the PID lives.

## Known limits

- Who an instruction is aimed at is not in the text. "Send the report to x@y" reads the same in a
  normal email and in an attack. This is the cause of most false alarms on documents.
- About a third of deepset attacks have no cue in the text. deepset recall is 31.7%, yanis 46.1%; the
  85% external recall standard has been missed in rounds two, three and four.
- Real benign prompts that ask for personas or role play are flagged often: 27% false alarms on the
  in-the-wild regular prompts. Raising the precision floor fixes that only by missing the main
  dataset's attacks (see the first round-four run).
- A fixed offline detector can be probed until something passes. It is a first filter, to be combined
  with limits on what the assistant may do.
- Attacks spread over several messages are not detected.
