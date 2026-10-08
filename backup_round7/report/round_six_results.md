# Round six: three single-change runs, one gate, set 6 scored once

## Fixed before the run (2026-10-04 evening, before any run tree was copied)

These rules were written down before any round-six code ran and are not changed after the run, whatever it
shows. Round five's record of a run that changed three things at once is `report/round_five_results.md`.

- **What the user asked for:** the promoted model must not be worse than round four anywhere that is
  measured; parts that do not improve must stay equal; improvements are optional.
- **Precision floor:** `MIN_PRECISION = 0.96` (`src/train.py`), unchanged since round four.
- **Champion:** the round-four model, run by its own code in `backup_round4/` (a subprocess). Its 1,062 verdicts
  on the six gate sets are cached in `report/champion_dev_scores.csv` under the tag `backup_round4`.
- **Gate groups and rule:** `TOLERANCE = 0` in `src/gate.py` (rounds four and five used 1). Three groups, every
  one must pass: POOLED = official_dev + handwritten_dev + handwritten_dev3; RECENT = set 4 + set 5; probe_dev.
  On each group the candidate's false alarms must be at or below the champion's AND its missed attacks at or
  below the champion's; on probe_dev the missed attacks must be strictly lower.
- **Champion bar** (false alarms / missed attacks): official_dev 0 / 1, handwritten_dev 5 / 3,
  handwritten_dev3 2 / 3, POOLED 7 / 7; set 4 3 / 7, set 5 4 / 13, RECENT 7 / 20; probe_dev 12 / 24. A candidate
  therefore needs POOLED false alarms <= 7 and misses <= 7; RECENT false alarms <= 7 and misses <= 20; probe false
  alarms <= 12 and misses <= 23. The gate driver recomputes the champion's counts from the cache and stops if any
  count differs from this bar.
- **Report only, never binding:** the six round-four source development splits (wild_dev, llmail_dev, gsum_dev,
  yanis_dev, aya_dev, dolly_dev; 901 rows) are scored for the champion and every candidate and printed in the
  same table. Decided now: one text's noise on 901 in-family rows should not veto a gain; the write-up will show
  them. The oasst1, injecagent and bipia splits of `data/new_test.csv` are TEST sets and are not opened before
  the test-scoring step.
- **Three runs, one change each, in copies of the working tree under `rounds/round6/` (git-ignored):**

  | Run | Rules | Training data | Grid | Isolates |
  |---|---|---|---|---|
  | r1_rules | round four + the two fixes (`report/round_five_rules.diff`) | six-source `new_train.csv` / `new_test.csv` from `backup_round4/data/` | pinned | the rule fixes |
  | r2_data | round four | nine-source (live `data/`) | pinned | the new data |
  | r3_rules_data | round four + the two fixes | nine-source | pinned | both: round five minus the grid move |

  The grid is pinned in every run to round four's choice, linear SVC with C = 0.3 and rule weight 1.0
  (`SVC_GRID`, `RULE_WEIGHTS` in each tree's `src/train.py`). Each run picks its own threshold from its
  out-of-fold 96% floor; thresholds are not edited afterwards. Runs are `python -m src.train` without `--final`:
  they save two candidates (`emb+rules20`, `emb+rules16`) and `metrics.json`, promote nothing and score no test
  set. Nothing else differs between the trees; each tree's `ORIGIN.txt` lists the changed files with their md5.
- **One gate pass, report only** (`scripts/gate_round6.py`): every candidate (up to six) is scored by a
  subprocess inside its own tree, so the `rules.py` it was trained with computes its features;
  `src.gate.passes()` decides. **Tie-break among passers, in this order:** fewest total mistakes over the six
  gate sets; fewer probe misses; run order r1, r2, r3; `emb+rules20` before `emb+rules16`. At most one candidate
  is promoted. A fail by one text is a fail. If none passes, round four stays, no test set is scored, set 6 stays
  unscored, and the floor, tolerance, groups and tie-break are not revisited.
- **After a pass, attended:** `gate_round6.py --promote` copies the pickle (and the tree's `rules.py` and
  self-check sentences when they differ) into the live tree; `scripts/score_tests.py` scores the held-out test
  sets once (official final half, deepset, gandalf, jackhhao, oasst1, injecagent, bipia) exactly as `--final`
  would, then runs the development-only ablation for the record; `scripts/score_set.py ... --name set6` scores
  set 6 once. Set 6 is then development data and round seven needs a set 7.
- **Expectation, stated now:** the gate guarantees "not worse" on development data, not "better everywhere".
  Improvement is plausible on the set-5 attack types the rule fixes target (destructive commands, mass-messaging
  orders, instructions hidden in tool output and documents); no change is expected on non-English attacks
  without override words, intent-only deepset attacks or persona false alarms. A fair outcome is that no run
  passes and round four stays, with the cause written down.
- **Safety of the runs:** the shared embedding cache is backed up to `data/cache/backup_round6/` before the
  first run; runs are sequential under one `systemd-inhibit`, on mains power only; the live tree is not modified
  by any run.

## Before the run (2026-10-04, 22:20 to 23:05)

- Live tree edits: `src/gate.py` TOLERANCE 1 -> 0 with a dated comment; `.gitignore` += `rounds/`;
  `scripts/build_notebook.py` tolerates a `metrics.json` without an ablation block; `data/cache/embeddings_norm.*`
  backed up to `data/cache/backup_round6/` (157 MB, byte-identical). `src/rules.py`, the data files and the live
  pickle (sha1 7165962019c3, equal to `backup_round4`'s) untouched.
- New scripts: `scripts/round6_setup.py` (tree copies and checks), `scripts/round6_overnight.sh` (driver),
  `scripts/gate_round6.py` (report-only gate; `--self-check`; `--promote`), `scripts/score_tests.py` (test sets
  once, as `--final` would).
- Trees built 22:40 under `rounds/round6/` by `shutil.copytree` of the working tree (no `rsync` on this machine),
  `data/cache` and `data/raw` as relative symlinks, `report/` empty, no pickle. Patches applied cleanly:
  `round_five_rules.diff`; `round_five_check_rules.diff` minus its first hunk (the live file already has it).
  Checks (`rounds/round6/setup_log.txt`, `setup_check_log.txt`, `setup_check2_log.txt`, all passed): pinned grid
  confirmed in-tree; `rules.py` / `check_rules.py` match the spec; data files equal their source; the file-level
  diff against the live tree is exactly the intended set; `load_pool()` gives 13,157 rows in r1_rules (round
  four's original count) and 15,451 in r2_data and r3_rules_data (round five's); `scripts/check_rules.py` full
  mode passes in r1 and r3 (0 example failures, the new rules under the 0.5% limit), `--examples` in r2; no
  `rounds/` entry in `git status`.
- Smoke run in r1_rules (`rounds/round6/r1_rules/report/smoke_log.txt`): 5% of the data, chosen parameters C = 0.3
  / weight 1.0, thresholds 0.575 and 0.649, two candidates saved.
- Gate self-check (`gate_round6.py --self-check`): the round-four pickle, scored inside `backup_round4` as a
  candidate, equals the champion's verdicts on all twelve sets; the champion's counts equal the bar; decision None
  (equal probe misses fail the strict rule), as expected. The six report-only splits were scored by the round-four
  code once and cached (`report/champion_dev_scores.csv`: 1,963 rows). Round four on them (false alarms / missed):
  wild_dev 34 / 21, llmail_dev 0 / 4, gsum_dev 0 / 6, yanis_dev 0 / 83, aya_dev 1 / 0, dolly_dev 0 / 0. The cache
  the self-check created in `backup_round4/data/` was removed afterwards.
- The working tree was uncommitted at launch (the round-five state plus the edits above; the user commits).

## The run

Started 2026-10-04 23:05:08 +05:30 on mains power (battery 100%): `scripts/round6_overnight.sh` under
`systemd-inhibit`, order r1_rules, r2_data, r3_rules_data, then `scripts/gate_round6.py` writing
`report/round_six_gate.txt` and `report/round_six_gate.json`. Driver log `report/round_six_overnight.log`; per-run
logs `rounds/round6/<tree>/report/train_log.txt`; `DONE_<rc>` markers per tree. Expected 2.5 to 3 hours.

## The run (2026-10-04 23:05 to 2026-10-05 00:58, 1 h 53 min, mains power, no interruption)

| Run | Texts -> units | Training units | Threshold emb+rules20 / emb+rules16 | Wall time |
|---|---|---|---|---|
| r1_rules | 23,503 -> 107,283 (1,945 pieces dropped as held out, as round four) | 36,314 | 0.547 / 0.689 | 25 min |
| r2_data | 26,692 -> 128,835 (2,171 dropped, as round five) | 41,999 | 0.720 / 0.904 | 40 min |
| r3_rules_data | 26,692 -> 128,835 (2,171 dropped) | 42,001 | 0.718 / 0.898 | 41 min |

Every run used the pinned C = 0.3, rule weight 1.0. The text counts exclude the test sets, which a non-final
run does not load as texts (their pieces are still blocked from training). The gate ran 00:51 to 00:58, one
subprocess per candidate inside its tree (60 to 68 s each); the champion's counts equalled the frozen bar on
every gate set.

### Gate table (false alarms / missed attacks; `report/round_six_gate.txt`; decision values per text in `report/round_six_gate.json`)

| Set | Rows | Round four | r1 rules20 | r1 rules16 | r2 rules20 | r2 rules16 | r3 rules20 | r3 rules16 |
|---|---|---|---|---|---|---|---|---|
| official_dev | 493 | 0 / 1 | 0 / 1 | 0 / 1 | 0 / 48 | 0 / 30 | 0 / 48 | 0 / 30 |
| handwritten_dev | 112 | 5 / 3 | 5 / 3 | 5 / 4 | 5 / 3 | 5 / 4 | 5 / 2 | 5 / 4 |
| handwritten_dev3 | 56 | 2 / 3 | 2 / 3 | 1 / 3 | 1 / 4 | 1 / 3 | 1 / 4 | 1 / 3 |
| set 4 (handwritten_dev4) | 125 | 3 / 7 | 2 / 5 | 3 / 8 | 4 / 8 | 3 / 10 | 4 / 6 | 3 / 10 |
| set 5 (agent_drafted_dev5) | 60 | 4 / 13 | 4 / 10 | 4 / 14 | 4 / 12 | 4 / 13 | 4 / 9 | 4 / 13 |
| probe_dev | 216 | 12 / 24 | 12 / 24 | 17 / 30 | 12 / 25 | 14 / 30 | 12 / 25 | 14 / 30 |
| **POOLED** | 661 | 7 / 7 | 7 / 7 | 6 / 8 | 6 / 55 | 6 / 37 | 6 / 54 | 6 / 37 |
| **RECENT** | 185 | 7 / 20 | 6 / 15 | 7 / 22 | 8 / 20 | 7 / 23 | 8 / 15 | 7 / 23 |
| wild_dev (report only) | 208 | 34 / 21 | 34 / 21 | 32 / 21 | 32 / 19 | 34 / 20 | 32 / 19 | 34 / 20 |
| llmail_dev (report only) | 97 | 0 / 4 | 0 / 5 | 0 / 6 | 0 / 4 | 0 / 5 | 0 / 4 | 0 / 5 |
| gsum_dev (report only) | 13 | 0 / 6 | 0 / 6 | 0 / 7 | 0 / 7 | 0 / 8 | 0 / 7 | 0 / 8 |
| yanis_dev (report only) | 154 | 0 / 83 | 0 / 83 | 0 / 88 | 0 / 96 | 0 / 98 | 0 / 96 | 0 / 98 |
| aya_dev (report only) | 198 | 1 / 0 | 1 / 0 | 1 / 0 | 1 / 0 | 1 / 0 | 1 / 0 | 1 / 0 |
| dolly_dev (report only) | 231 | 0 / 0 | 0 / 0 | 0 / 0 | 0 / 0 | 0 / 0 | 0 / 0 | 0 / 0 |
| gate | | | fail | fail | fail | fail | fail | fail |

**Result: no candidate passed. Round four stays.** No test set was scored; set 6 stays unscored; the live model,
`src/rules.py`, `report/metrics.json` and `report/train_log.txt` were never touched (live pickle sha1 7165962019c3
equals `backup_round4`'s; `cmp` of `rules.py` against the backup is clean).

### Why each candidate failed (development data only; the decision above stands)

- **r1_rules/emb+rules20, the rule fixes alone,** failed on one clause: probe_dev misses must be strictly lower
  than 24, and they are exactly 24. On every binding count it is equal or better: POOLED 7 / 7 (equal), RECENT
  6 / 15 against 7 / 20, probe 12 / 24 (equal). Six verdicts differ from round four's. Five are better: on set 4
  the `DELETE FROM` order (score 1.68) and the mass-messaging order (1.59) are caught and a false alarm on a
  high-level security question is gone (0.543, just under the threshold); on set 5 all three destructive commands
  are caught (2.48, 1.16, 3.97). One is worse, on a report-only set: one llmail attack is now missed at 0.533
  against the 0.547 threshold. The probe set's verdicts are identical text for text: its 24 missed attacks score
  at most 0.395, so no threshold between 0.40 and 0.65 changes that count (at 0.40 the candidate has 15 false
  alarms and still 24 misses). The rule fixes do not reach the probe set at all.
- **r2_data and r3_rules_data, the nine-source data,** fail POOLED by a wide margin: official_dev misses 1 -> 48
  (20 rules) and 1 -> 30 (16 rules). Their 96% floor thresholds are 0.72 and 0.90 instead of 0.55: the 1,213
  benign oasst1 prompts score high enough that keeping 96% precision on the out-of-fold originals pushes the
  threshold up, exactly as the benign in-the-wild prompts did in the first round-four run (threshold 1.304,
  `report/round_four_results.md`). At round four's threshold 0.548 the same candidates would show official_dev
  0 / 16, POOLED 6 / 21, RECENT 8 / 18 (r3: 8 / 14), probe 14 / 22; at 0.50 official_dev 0 / 1 and POOLED 6 / 6,
  but RECENT 8 false alarms and probe 16 false alarms, both above the champion's 7 and 12. There is no threshold
  at which they pass. Round five's grid choice (C = 1, weight 2.0, threshold 0.852, official_dev 0 / 1) was
  therefore compensating for the data's effect on the floor, not causing the probe loss on its own.
- The 16-rule candidates are worse than their 20-rule twins on the probe set (30 misses) and everywhere else that
  matters, and are not discussed further.

### What round six answers

Of round five's three simultaneous changes: the **rule fixes** cost nothing on the gate sets and gain five catches
on sets 4 and 5 (one llmail development text lost); the **nine-source data under the pinned grid** raises the
floor threshold and costs the official development half dozens of attacks; the **grid move** was the response to
that, with its own probe cost (13 / 27 in round five). None of the six candidates improves the probe set: its 24
misses stand in every one (best 24, worst 30).

### State after the fail

- Live model, `src/rules.py`, `report/metrics.json`, `report/train_log.txt`: round four's, untouched by the run.
  `src/gate.py` keeps `TOLERANCE = 0`. The round-five rule fixes stay in `report/round_five_rules.diff`.
- Records: `report/round_six_gate.txt` and `.json` (every candidate's decision values on the twelve sets),
  `report/round_six/<tree>_{metrics.json,train_log.txt,ORIGIN.txt}` and `gate.txt`, `report/round_six_overnight.log`,
  this file. The trees with their candidates stay in `rounds/round6/` (git-ignored, about 70 MB each) until the
  user deletes them; `rounds/round6/r1_rules` reproduces the r1 candidate exactly if run again.
- Set 6 stays unscored and valid. The oasst1, injecagent and bipia splits of `data/new_test.csv` stay unscored.
- `report/champion_dev_scores.csv` now also holds round four's verdicts on the six source development splits
  (1,963 rows); `report/round_six_gate.json` holds the candidates'.

### What round seven could ask, to be decided before its run

1. **The probe clause against the user's criterion.** The user's rule for this round was "nothing worse than
   round four; improvements optional". The frozen gate kept the older clause "probe misses strictly lower",
   which demands an improvement on the probe set. r1_rules/emb+rules20 meets the user's criterion on every
   binding set and fails only that clause. If the user decides, before any run and in writing, that round
   seven's gate is "no count worse on any group" with the probe set treated like the others, the r1_rules
   configuration can be run again (deterministic: same data, code and seeds give the same candidate, 25 minutes)
   and gated under that rule. The write-up must then say the rule was changed after seeing round six, as it says
   of round four's floor change, and must state the one llmail_dev miss.
2. **The floor with benign-heavy data.** Any round that adds benign prompts needs a threshold rule that does not
   let them raise the floor: a false-alarm budget per development set (the round-five record's open question), a
   floor computed on the official originals only, or dropping oasst1 from the pool. One change per run, as here.
3. **Set 6** stays the held-out set for whichever candidate is promoted.
