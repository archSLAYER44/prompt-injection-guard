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
- **Set 6 was scored once on 2026-10-05** (round seven's promoted model): recall 36.7%, false alarms 16.7%, both
  standards missed. It is `data/agent_drafted_test6.csv` and development data now (`report/set6_scored.csv`; in the
  gate's RECENT group since round eight). **There is no unread sentence set.** The next honest sentence-set number
  needs a set 7 (same recipe: agents, chunks of six, no repo access, user review, sealed until a promotion).
- **Gate since round seven:** `TOLERANCE = 0` and the probe clause non-strict (`src/gate.py` GROUPS): a candidate passes
  when no count on POOLED, RECENT or probe_dev is worse than the champion's. **Since round eight (2026-10-08) the champion
  is round seven** (`backup_round7/`, `BACKUP` in `src/gate.py`; `BAR_BY_ROUND` in `scripts/gate_round6.py`) and RECENT
  is sets 4, 5 and 6. Round six (`report/round_six_results.md`)
  used the strict probe clause and rejected the same rule-fixes candidate by 24 = 24; the clause was changed after
  round six and before round seven's run, and the write-up must say so.
- **Round eight (2026-10-08, 01:10 to 03:30) promoted the rule-patterns model.** Live model = round four's six-source
  data, round seven's rules plus `report/round_eight_rules.diff` (the assistant addressed in passing, send / destructive
  orders in the set-6 wording, output manipulation, pt/es/it/fr/de notes, Hindi), grid pinned C = 0.3 / weight 1.0,
  threshold 0.546, pickle sha1 9a6ca3abfe9f. Gate against round seven: nothing worse; set 6 misses 19 -> 4, probe 24 -> 19,
  false alarms identical. Test sets scored once: official 98.6% / 99.8% (identical), external 79.9% / 97.3% (85% recall
  standard still missed), oasst1 6 false alarms, BIPIA 12.3% (two attacks lost). Record `report/round_eight_results.md`.
  Round seven is frozen in `backup_round7/`. **Committed as fe2d1d2 on 2026-10-08** (rounds five to eight, the
  front end, under the user's git identity, at the user's request; commits still happen only when the user asks).
- **Round seven (2026-10-05) promoted the rule-fixes model.** Live model = round four's six-source data and 20 rules with
  the two rule fixes (`DELETE FROM` / truncate / purge, mass messaging), threshold 0.547, pickle sha1 73b0883558c6.
  Record `report/round_seven_results.md`. **Follow-up done 2026-10-06 (01:20 to 01:35):** out-of-fold score distribution
  rebuilt for round seven (`report/score_distribution.json` + `_oof.csv`, 526 s, log `report/round7/export_score_distribution.log`),
  charts (`rule_firing_rates.png` is the only one that changed), notebook rebuilt and executed (no errors), `report/writeup.md`
  updated to round seven, dashboard AppTest passed (`report/round7/dashboard_apptest.txt`). Committed in fe2d1d2.
- This laptop has no Ollama (checked 2026-10-03). The working chat model for the dashboard is the in-process
  option of `llm_client.py` (about 12 s to load, 1 to 6 s per reply on the CPU). The model is FROZEN while the
  dashboard is built: no retraining, no new rules, no change to the scoring code.

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
| `backup_round4/` | Frozen, runnable copy of round four (code, model, reports, the six-source data files); the gate's champion in rounds five to seven |
| `backup_round7/` | Frozen, runnable copy of round seven (code, data, reports, pickle 73b0883558c6); the gate's champion since round eight |
| `report/round_eight_results.md`, `report/round_eight_rules.diff`, `report/round_eight_check_rules.diff`, `report/round8/` | Round eight: the rules fixed before the run, the patterns per set-6 form, self-check rates before and after, the gate, the promotion, the test scores; the two diffs the run tree was built from; logs, metrics, self-checks |
| `scripts/score_set.py`, `scripts/merge_set.py` | Score a held-out set once through `predict()` (refuses to re-score); merge agent-drafted chunks and check them |
| `report/round_five_results.md`, `report/round_five_rules.diff` | The round-five record (frozen rules, data, gate FAIL, diagnosis) and the two rule fixes kept for round six |
| `dashboard.py` | Streamlit app with left navigation (`st.navigation`, restyled 2026-10-08 after the Stitch design): pages Chat (composer with six presets, compact score-distribution panel, conversation as bubbles), Guard inspector (verdict banner, tiles with the real detector latency, nine-stage status list, full stage details per scanned text, model request and response), Monitoring (source "This session" or "All sessions (live)": the shared log re-read every 3 s by a `st.fragment`; hero panel on out-of-fold training scores, tiles, score per request, rules fired, allowed vs blocked, recent requests with surface, session and detector latency, a filter), Results (standards, held-out test table, the round-eight gate table, official test by category, all read from `report/metrics.json` and `report/round8_gate.json`), History, About (architecture flow, known limits, model metadata; real values). Top bar with status chips and a profile line on every page. Stub model built in; real models through `llm_client.py` |
| `.streamlit/config.toml` | Dashboard theme (Grafana-like dark palette, Streamlit's bundled font, no external fonts); the source watcher is off because it trips over transformers' lazy modules |
| `scripts/export_score_distribution.py` | Out-of-fold scores of the training data (grouped folds, 5 fold fits, about 7 minutes) to `report/score_distribution.json` + `report/score_distribution_oof.csv`; `--from-csv` reuses a saved OOF file, `--official-test` is the labelled fallback |
| `guard_core.py` | One chat request through the guard (2026-10-08): `handle_request(message, document, settings)` scans, decides, calls the model, returns a plain dict; `history_row()` flattens it. No Streamlit in it; shared by `dashboard.py` and `chat_app.py` |
| `guard_log.py` | The shared decision log, `logs/guard_log.jsonl` (git-ignored; `GUARD_LOG_PATH` overrides): `append`, `read`, `clear`, `summary`. Both pages write it; the dashboard's live monitor reads it |
| `chat_app.py` | The production chat page (2026-10-08): an end user talks to the assistant with the guard in front, no inspector; a Guard panel, test payloads and a simulated retrieved document on the right; every request appended to the shared log. `streamlit run chat_app.py --server.port 8502` |
| `guard_ui.py` | HTML pieces both pages share (palette, chips, badges with icons, tiles, the chat transcript as bubbles with the blocked card); no Streamlit calls |
| `design/stitch/` | The user's Google Stitch export (five screens as HTML + `DESIGN.md`; `renders/` are Brave renders of them). Only its visual system was applied; every number in those screens is invented and none was copied |
| `llm_client.py` | Dashboard chat client (2026-10-03): `chat(provider, base_url, model, api_key, messages)` over ten providers: in-process transformers model (Qwen2.5-0.5B-Instruct, no server, no key), Ollama, OpenAI-compatible servers, OpenAI, Anthropic (official SDK), Gemini, Groq, OpenRouter, Mistral, DeepSeek. Keys only in request headers, never stored |
| `scripts/round6_setup.py` | `--round N`: builds `rounds/roundN/<tree>` as copies of the working tree per the round's tree specs (grid pinned to C=0.3 / weight 1.0, data variant or `"live"`, a rules diff pair or `None` for an unpatched dev copy, extra training files), symlinked cache, and checks them; `--smoke TREE` |
| `scripts/round6_overnight.sh` | `ROUND=N`: runs the round's trees in sequence under `systemd-inhibit` (refuses without AC power), then the gate. Launch line in its header |
| `scripts/gate_round6.py` | `--round N`: report-only gate across the trees: each candidate scored by a subprocess in its own tree; `passes()` from `src/gate.py`; six source dev splits report-only; tie-break; writes `report/roundN_gate.{txt,json}`. `--self-check`; `--promote TREE/CANDIDATE` is the only writing mode (pickle, rules, check sentences, `new_train.csv`, drafted files, metrics, log) |
| `scripts/score_tests.py` | `--round N --tree T [--ablation]`: scores the held-out test sets once for the promoted pickle exactly as `--final` would; refuses a second run |
| `scripts/merge_drafted.py`, `scripts/check_set6_overlap.py` | Round seven: merge and check agent-drafted training chunks (columns, labels, lengths, languages, override words, duplicates, near copies of any `data/*.csv`); check a held-out set for copies of training or drafted rows before scoring it |
| `rounds/round6/`, `rounds/round7/`, `rounds/round8/` | Git-ignored run trees, logs and candidates; `report/round_six_results.md`, `report/round_seven_results.md` and `report/round_eight_results.md` are the records; `report/round7/briefs.md` the drafting briefs; `rounds/round8/_dev` the unpatched copy the round-eight diff was developed in |

## Commands

```bash
.venv/bin/python cli.py check-text "some text"
.venv/bin/python gui.py
.venv/bin/python -m src.dataset          # balance and duplicate report
.venv/bin/python -m src.train            # development numbers only
.venv/bin/python -m src.train --final    # also scores the held-out test sets (~65 min warm)
.venv/bin/streamlit run dashboard.py     # the guard demo: test page, live monitor, results (needs streamlit)
.venv/bin/streamlit run chat_app.py --server.port 8502   # the production chat page; its calls appear on the dashboard's live monitor
.venv/bin/python llm_client.py --provider "Local (in-process)" "hi"   # chat client test
```

## Status: round eight promoted and committed on 2026-10-08 (fe2d1d2); the front end has a production chat page and a live monitor

**Round eight (2026-10-08 01:10 to 03:30).** One tree, `rounds/round8/r8_rules`: the live round-seven tree plus
`report/round_eight_rules.diff` (13 hunks; developed in `rounds/round8/_dev`, checked with the rule self-check: every
example passes, firing rates on harmless corpora unchanged except +1 and +4 in-the-wild prompts of 1,500), six-source
data, grid pinned. Gate against round seven (frozen as `backup_round7/`, set 6 in RECENT, rule and floor unchanged, all
written down before the run): r8_rules/emb+rules20 PASS, POOLED 7/7 (=), RECENT 11/18 (11/34), probe 12/19 (12/24),
one yanis_dev miss more (report only); emb+rules16 fails. Promoted 02:58; tests scored once 03:10 to 03:17 (table in
`report/round_eight_results.md`); ablation, charts, score distribution, write-up and notebook rebuilt afterwards. Two
set-6 attacks round seven caught by a hair (0.55, 0.57) are missed by a hair (0.53, 0.52); the five set-6 false alarms
are the same texts. **Round-nine questions:** a set 7 (nothing unread exists); the persona false alarms (3 of 6 on set 6,
untouched since set 5); BIPIA's two lost attacks; whether the threshold should be read off a false-alarm budget.
Launch note: the overnight driver's "already running" check (`pgrep -f src.train|gate_round6|score_tests`) matches the
launching shell's own command line if that line mentions those names, so launch it from a command that does not.

**Front end (2026-10-08 evening, after the promotion).** `guard_core.py` (one request through the guard, no Streamlit),
`guard_log.py` (shared log `logs/guard_log.jsonl`, git-ignored), `chat_app.py` (production chat page, port 8502),
`dashboard.py` extended (round-eight wording, six presets, Results tab from the report files, Monitoring source
"All sessions (live)" re-reading the log every 3 s). Both pages pass Streamlit AppTest runs; screenshots
`report/dashboard_{chat,monitoring,results,live}.png` taken headless with Brave + Playwright (`playwright` in the venv
only; its bundled chromium build does not match, so launch with `executable_path=/usr/bin/brave`). **Restyled the same
evening after the user's Google Stitch export** (`design/stitch/`): `dashboard.py` became a left-navigation app
(`st.navigation`: Chat, Guard inspector, Monitoring, Results, History, About) with a top bar, status chips, telemetry tiles,
badges with icons, chat bubbles with the blocked card, a nine-stage status list, and the detector's real latency per
request (`scan_ms` in `guard_core.py`); `chat_app.py` got the same header plus a Guard panel, test payloads and a sample
ticket; shared HTML pieces in `guard_ui.py`. Only the design's visual system was used: its sample numbers are invented
and none was copied. Both pages pass AppTest; screenshots retaken (`report/dashboard_{chat,live,inspector,monitoring,
results,about}.png`). To screenshot: scratch scripts start both servers by PID (never kill them with a pattern that the
launching shell's own command line also matches). **Open for the submission (in two days from 2026-10-08):** a set 7 if
an honest sentence-set number is wanted; otherwise the write-up already states the gap.

**Round seven (2026-10-05 01:30 to 03:35).** Round four's six-source data + the two rule fixes (+ a second candidate
with 312 agent-drafted training rows, which lost the tie-break by one false alarm and did not help set 6 either). Gate
"not worse than round four on any group", TOLERANCE 0, probe clause non-strict: r1_rules/emb+rules20 PASS with POOLED
7/7 (= round four), RECENT 6/15 (round four 7/20), probe 12/24 (=); one llmail_dev miss more (report only). Promoted;
test sets scored once: official 98.6% recall / 99.8% precision, external 79.6% / 96.9% (85% recall standard still
missed), oasst1 7 false alarms in 289, injecagent 33.3% recall, bipia 13.6% recall; set 6 36.7% recall / 16.7% false
alarms (both missed). Records: `report/round_seven_results.md`, `report/round7_gate.{txt,json}`, `report/round7/`,
`report/round7_tests.txt`. Data: `data/new_train.csv` is six-source again, the nine-source file is
`data/new_train_round5.csv` (loaded by nothing), `data/new_test.csv` keeps nine sources (three are test sets),
`data/agent_drafted_test6.csv` = set 6. The drafted rows (`rounds/round7/drafted_train7.csv`, git-ignored) are not
training data; `src/dataset.py` would read them from `data/drafted_train7.csv`. `backup_round4/` stays the gate's
champion until the user decides to snapshot round seven as `backup_round7/`. Round-eight questions: a set 7; whether
the drafted rows help with a different threshold rule (their twins raised the floor 0.547 -> 0.574); the persona false
alarms (3 of 6 on set 6) and the tool-output insertions (2 of 6) that no rule reaches.

### Round four (the previous promoted model, 2026-10-01)

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

**Round five (2026-10-04): attempted, rejected by the gate; round four stays.** Three sources added to
`data/new_train.csv` / `new_test.csv` (oasst1, InjecAgent, BIPIA; six round-four sources byte-identical), two rule
fixes, gate against round four in `backup_round4/` with sets 4 and 5 as a second binding group. The 20-rule
candidate (C=1, rule weight 2.0, threshold 0.852 from the 96% floor) matched round four on POOLED (6/8 vs 7/7),
beat it on RECENT (7/14 vs 7/20: set 5 misses 13 -> 8) and lost on probe_dev (13/27 vs 12/24) at every
threshold, so no candidate passed; the test sets were not scored and set 6 stays unscored. The live model, code
and `report/metrics.json` are round four's again (`src/rules.py` restored; the rule fixes live in
`report/round_five_rules.diff`). **`data/new_train.csv` now holds nine sources; the round-four model was trained
on the six-source files in `backup_round4/data/`, so a `--final` run today trains on round-five data.** Record:
`report/round_five_results.md`, log `report/train_log_round5_fail.txt`, metrics `report/metrics_round5_fail.json`,
candidates in `src/models/candidates/` (git-ignored). Run time 2 h 9 min.

**Round six (2026-10-04 23:05 to 2026-10-05 00:58, 1 h 53 min): three single-change runs, no candidate passed,
round four stays.** Record `report/round_six_results.md`; gate `report/round_six_gate.{txt,json}`; per-run logs and
metrics in `report/round_six/`. Three trees in `rounds/round6/` (git-ignored), one change each, grid pinned to
round four's C = 0.3 / weight 1.0, gated once against round four with `TOLERANCE = 0` (user's rule: nothing worse,
gains optional), six source dev splits report-only. r1_rules (rule fixes, six-source data): POOLED 7/7 = champion,
RECENT 6/15 vs 7/20, probe 12/24 = champion, one llmail_dev miss more; failed only because probe misses were not
strictly lower. r2_data / r3_rules_data (nine-source data): threshold 0.72 at the 96% floor, official_dev misses
1 -> 48, fail at every threshold. So the rule fixes are safe, the benign oasst1 data raises the floor, and round
five's grid move was compensating for that. Nothing in the live tree changed (pickle sha1 7165962019c3 = backup).
Round-seven questions, decided before any run: whether the probe clause becomes "not worse" like the other groups
(then r1_rules reruns in 25 min and is gated again, and the write-up says the rule changed after round six), and a
threshold rule that benign prompts cannot raise. Set 6 stays unscored.

**Dashboard (2026-10-03, model frozen).** `explain(text)` added to `src/predict.py` (predict() unchanged,
proved on 20 texts), `llm_client.py` (ten providers), `dashboard.py` (Streamlit, dark SOC-style theme, chat
transcript + guard inspector, four presets, deep links `?preset=<name>&send=1`). Tested with Streamlit's
AppTest harness (stub and the real in-process model) and screenshotted headless through Brave + Playwright
(`playwright` is in the venv for that only; it is not in requirements.txt). Guard on: the direct injection
is blocked; guard off: Qwen2.5-0.5B-Instruct prints the secret in 0.6 s. Restyled 2026-10-04 to a Grafana-like
monitoring layout with Plotly (`plotly` in requirements.txt); fonts removed; `report/score_distribution.json`
built from a fresh out-of-fold run (identical to the round-four OOF scores). `src/` untouched throughout.

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

1. Set 6 exists, reviewed by the user, UNSCORED (`/home/guts/Documents/set6_review/set6_draft.csv`). It is the
   held-out set for the next promotion; if the project ends first, score it once on round four with
   `scripts/score_set.py` and put the number in the write-up.
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

**Process rule for round six.** Fix the gate rule and the precision floor before the run and do not
change them after (round five did this and the gate rejected the candidate; the rules stayed). Round-six
questions, in order: whether the probe-set loss comes from the new data, the rule fixes or the grid's
choice of C=1 / rule weight 2.0 (one run per change, each gated); whether oasst1's 1,500 benign prompts
should shrink; and whether the floor should be stated as a false-alarm budget per development set
instead of OOF precision, decided before the run.

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
- Set 5 (agent-drafted, scored once after round four): recall 56.7%, false alarms 13.3%. Attacks with no
  override word in Turkish, Arabic and Chinese, hidden instructions in a policy clause, a README and an
  invoice, and a `DELETE FROM` order were all missed; three of six benign persona requests were flagged.
- Set 6 (agent-drafted, scored once on round seven, 2026-10-05): recall 36.7%, false alarms 16.7%. Orders inside JSON
  tool results, calendar entries, articles, tables and email threads scored well below zero with no rule firing;
  destructive routines phrased as housekeeping and send orders dressed as sync tests or forwarding requests were missed;
  three of six persona requests are flagged. 312 drafted training rows aimed at these categories did not move them.
  Round eight's rule patterns do (set 6 as development data: 4 misses, same 5 false alarms), but that is the fix measured
  on its own target: nothing unread has been scored on the round-eight model, and the persona false alarms are untouched.
