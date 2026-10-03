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
| `src/predict.py` | `predict(text)`; `explain(text)` (added 2026-10-03): the same computation reported in full, for the dashboard. Read-only, 125 added lines, predict() unchanged (proved on 20 texts) |
| `src/gate.py` | Compares saved candidates with the round-three model on development data, promotes or keeps |
| `scripts/` | Dataset download (`download_dataset.py`, `download_new_sources.py`), contrast set generator, rule checks, notebook builder |
| `report/writeup.md` | Full write-up with results and limitations |
| `report/round_four_results.md` | Round-four record: the rejected first run, diagnosis, decision, final numbers |
| `report.txt` | Progress report of 2026-10-01: bug status, before/after table on every test set, git state |
| `scripts/make_charts.py` | Regenerates the four charts the write-up embeds, from `report/metrics.json` |
| `scripts/oof_floor_check.py` | Threshold per precision floor, from out-of-fold scores on the grouped folds |
| `backup_round3/` | Frozen, runnable copy of round three (code, model, reports) |

## Commands

```bash
.venv/bin/python cli.py check-text "some text"
.venv/bin/python gui.py
.venv/bin/python -m src.dataset          # balance and duplicate report
.venv/bin/python -m src.train            # development numbers only
.venv/bin/python -m src.train --final    # also scores the held-out test sets (~65 min warm)
```

## Status: round four is complete and committed (48b97d7, 2026-10-01 19:09)

Model in `src/models/injection_model.pkl`: embedding + 20 rules, linear SVC, C = 0.3, rule weight 1.0,
bounded rule scaling, threshold 0.548 (96% precision floor), 36,312 training pieces. Promoted by the
gate over round three on development data; the held-out test sets were scored once, by the same run.
Write-up: `report/writeup.md`. Record of the round, including the rejected first run:
`report/round_four_results.md`. Round three stays runnable in `backup_round3/`. `report.txt` holds a before/after re-score of every
test set done on 2026-10-01; it matches the training log (one jackhhao text differs for round three).

| Standard | Target | Result | Met |
|---|---|---|---|
| Official test recall | >= 90% | 98.6% | yes |
| Official test precision | >= 95% | 99.8% | yes |
| External tests recall | >= 85% | 79.6% | no |
| External tests precision | >= 90% | 96.9% | yes |
| Hand-written recall (set 4) | >= 85% | 89.2% | yes |
| Hand-written false alarms (set 4) | <= 7.1% | 5.0% (3 in 60) | yes |
| Set 5 recall (agent-drafted, scored after the round) | >= 85% | 56.7% (17 of 30) | no |
| Set 5 false alarms (scored after the round) | <= 7.1% | 13.3% (4 in 30) | no |

New sources, scored once: wild 64.9% precision / 75.0% recall (27% false alarms on real benign
prompts), llmail 100% / 93.8%, gsum 53.8% recall, yanis 46.1% recall, aya 1 false alarm in 198,
dolly 0 in 231. Hand-written set 4 and the new-source test splits have now been read: **they are
development data from here on; round five needs new held-out sets.**

**Set 5 (2026-10-03, model frozen; git tag `model-frozen` = f10a911).** 60 rows, half attacks, drafted by
ten agents in chunks of six with no access to the repo, reviewed by the user (no edits), labelled
"agent-drafted, human-reviewed", scored once through `predict()`: tn 26, fp 4, fn 13, tp 17; precision
81.0%, recall 56.7%, F1 66.7%, false alarms 13.3%. Both sentence-set standards missed. Files:
`data/agent_drafted_test5.csv`, `report/set5_scored.csv`; write-up updated. Its mistakes have been read:
**set 5 is development data; a round-five run needs a new held-out set.** It is not yet in the HELD_OUT
list of `scripts/check_rules.py` or the dedup lists of `scripts/download_new_sources.py`.

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

- `src/models/candidates/` was deleted on 2026-10-03. It is git-ignored and was never committed.
- Keep `data/raw/new/` (613 MB, git-ignored) while a fresh held-out sample may still be drawn from it.
- `data/cache/` (`embeddings_norm.npy` is 124 MB) is git-ignored and not tracked. A fresh clone rebuilds it
  on the first run, which is the cold-cache time above.
- A full run is about 65 minutes with a warm embedding cache, plus about 25 minutes per 40,000 new
  pieces. It needs AC power: start it with `setsid nohup ... & disown` and hold
  `systemd-inhibit --what=sleep:idle:handle-lid-switch --mode=block` while the PID lives.

## Next steps (written 2026-10-01 evening, for whoever picks this up)

**Committed** as 48b97d7 on 2026-10-01. `report.txt` and these status notes came after and are committed
separately. The nine `src/__pycache__/*.pyc` files that slipped into history were untracked on 2026-10-03.

**How to test.** Every held-out set has been read, so only new text is an honest test.

1. Set 5 is written and scored (2026-10-03) and is development data now. Write set 6 before touching
   any code, with the same recipe: about 60 rows, half benign, drafted in chunks of six by agents that
   cannot read the repo, reviewed by hand, kept out of the repo until scored once.
2. Probe with the CLI (`cli.py check-text`, `--file` for documents) using real emails and documents,
   and paraphrase a known attack until one passes: that shows how much wording it takes.
3. For data-set numbers, draw a second sample from `data/raw/new/`, deduplicated against every
   training, development and test file (`src.dataset.dedup_key` plus the near-duplicate filter in
   `load_pool`).

**Improvements, in order of evidence.**

1. Two new rules miss their own targets (set 4, confirmed again on set 5): `dangerous_action_count` has
   `drop table` but not `delete from`; `tool_action_count` needs attack evidence in nearby clauses, so "message every one
   of my contacts" is benign. Pattern changes in `src/rules.py`, checked with `scripts/check_rules.py`.
2. False alarms on real benign prompts (27% on wild regular): `second_person_command_ratio` fires on
   35% of them (self-check warning). Tightening it, or adding benign persona and role-play data,
   trades against main-dataset recall; the first round-four run shows how.
3. Decoded readings are not cut to 126 tokens: window the readings in `split_units`
   (`src/windows.py`) the way windows are.
4. Non-English recall 46%: `multilingual_override_count` covers 47% of its own contrast cues; add
   patterns per language first, then data.
5. External recall 79.6% against 85%: intent-only deepset attacks. Accept and document, or redefine
   the standard.

**Process rule for round five.** Fix the gate rule and the precision floor before the run and do not
change them after. New held-out sets are required: set 4 and the new-source test splits are
development data now.

**Stopping point.** Items 1 and 3 are an afternoon; 2 and 4 are a full round. If a deadline is near:
commit, score set 5 once into the write-up, and leave the rest as future work.

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
- Decoded readings longer than 126 tokens are read only to their first 126; the windows, decoded
  piece by piece, still cover the content.
- Two of the four new rules missed their own targets on set 4 (a `DELETE FROM` order, a "message all
  my contacts" order).
- The rule self-check (`scripts/check_rules.py`) warns that several old rules fire on 9 to 35% of
  in-the-wild benign prompts, `second_person_command_ratio` most of all.
- Set 5 (agent-drafted, scored once after the round): recall 56.7%, false alarms 13.3%. Attacks with no
  override word in Turkish, Arabic and Chinese, hidden instructions in a policy clause, a README and an
  invoice, and a `DELETE FROM` order were all missed; three of six benign persona requests were flagged.
