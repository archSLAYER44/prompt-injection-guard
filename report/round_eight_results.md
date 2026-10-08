# Round eight: rule patterns for the set-6 forms, gated against round seven

## Fixed before the run (2026-10-08, 01:10 to 02:10, before any training run)

These rules were written down before the round-eight training run and are not changed after it, whatever it
shows. Round seven's record is `report/round_seven_results.md`.

- **What the user asked** (2026-10-08, after a status check): "seems good but I wanted to improve it a bit". The
  evidence-ordered list in CLAUDE.md and the set-6 mistakes (`report/set6_scored.csv`, development data since they
  were read) point at the same thing: 17 of the 19 set-6 misses are orders no rule reaches, in forms the rules
  were never written for. Round eight changes rule patterns only: no data change, no grid change, no threshold
  rule change.
- **Champion: round seven**, the live model, frozen as `backup_round7/` (copy of the working tree made 01:22
  before any edit: code, six-source data files, reports, pickle sha1 73b0883558c6). `src/gate.py` now points
  `BACKUP` at it. Reason: the user's rule is "nothing worse than the live model"; round seven is better than round
  four on sets 4 and 5, so gating against round four would allow a regression on them.
- **Set 6 joins the RECENT group** (`agent_drafted_dev6`, loaded by `src/dataset.py` from
  `data/agent_drafted_test6.csv`), as sets 4 and 5 did when their mistakes had been read. The rule changes were
  written from set 6's mistakes, so its counts measure the targeted fix, not generalisation; the honest test is a
  new set 7, which does not exist yet.
- **Bar** (false alarms / missed), from `report/round7_gate.json` (r1_rules/emb+rules20) and `report/set6_scored.csv`:
  official_dev 0 / 1, handwritten_dev 5 / 3, handwritten_dev3 2 / 3 (POOLED 7 / 7); set 4 2 / 5, set 5 4 / 10, set 6
  5 / 19 (RECENT 11 / 34); probe_dev 12 / 24. `scripts/gate_round6.py` holds it as `BAR_BY_ROUND[8]` and stops if the
  recomputed champion counts differ.
- **Gate rule: unchanged since round seven.** `TOLERANCE = 0`, every group non-strict: on POOLED, RECENT and
  probe_dev the candidate's false alarms must be at or below the champion's AND its missed attacks at or below the
  champion's. The six source development splits are report only. Precision floor `MIN_PRECISION = 0.96`, unchanged
  since round four. Grid pinned to C = 0.3, rule weight 1.0 as in rounds six and seven.
- **One candidate tree, `rounds/round8/r8_rules`:** the live (round-seven) tree + `report/round_eight_rules.diff`
  (+ `report/round_eight_check_rules.diff`), live six-source data. It saves `emb+rules20` and `emb+rules16`;
  tie-break as in round seven (fewest total mistakes over the seven gate sets, fewer probe misses, `emb+rules20`
  first). A fail by one text is a fail.
- **After a pass, attended:** `gate_round6.py --round 8 --promote r8_rules/<candidate>` copies the pickle, the
  tree's `rules.py` and `check_rules.py` into the live tree; `scripts/score_tests.py --round 8 --tree r8_rules
  --ablation` scores the held-out test sets once (official final half, deepset, gandalf, jackhhao, oasst1,
  injecagent, bipia); the write-up, charts and notebook are rebuilt. Set 6 is development data and is not a test.
  If nothing passes, round seven stays and nothing is scored.
- **Expectation, stated now:** set 6 misses fall (17 of 19 now have a rule firing; whether the SVM flips them is
  the question), set 6 false alarms unchanged (no benign set-6 row's rule values moved), the other sets within a
  text or two of round seven. The risk is false alarms on documents and emails that mention assistants or send
  orders in the new forms; the self-check rates below bound it on the harmless corpora.

## The rule changes (`report/round_eight_rules.diff`, 13 hunks; developed in `rounds/round8/_dev`, 01:35 to 01:55)

Each pattern was written for a set-6 form; the sentences in `report/round_eight_check_rules.diff` are fresh
paraphrases, not set-6 rows.

| Rule | Change | Set-6 forms it reaches |
|---|---|---|
| `indirect_address_count` | the assistant addressed in passing: "if / when / for (an, the, whichever) [automated, shopping, reviewing, ...] assistant is / picks / preparing / ends up ...", "Reviewing assistant:", "Shopping assistant guidance:", "@opsbot"; "note for the assistant" in pt / es / it / fr / de (`ASSISTANT_LEAD`, `FOREIGN_NOTE`) | kettle review, help-desk ticket, article, reconciliation table, email thread, product page, @opsbot, Portuguese and Italian notes |
| `AI_ADDRESSED_RE` (inside `dangerous_action_count` / `tool_action_count`) | the same two patterns, so such clauses count as orders and as attack evidence; a colon lead that addresses the AI makes the next clause an order | kettle, ticket, product page |
| `tool_action_count` (`SEND_TO_RE`) | send verbs export / push / sync / mirror / dump / move / paste / attach; destination "my / their / a (personal, private, home, other, ...) address / mailbox / channel / bucket / drive"; a paste into a `#channel`; a reply-all with an attachment | ticket, sync test, .env token, forwarding to a personal address, board pack |
| `PRIVATE_DATA_RE` (evidence) | "everything in the clients folder"; private / confidential folders, archives, emails; env-style secret names (`deploy_token`, `api_key`, ...); tax returns, id scans, passport, payslips, saved / payment cards, sign-in history; "marked confidential" | sync test, .env token, forwarding, board pack, product page |
| `SECRECY_RE` (evidence) | "don't bother with a confirmation", "no confirmation needed", "skip the confirmation" | sync test |
| `dangerous_action_count` | a comma list of tables after truncate; revoke / invalidate / delete every access key, credential, token, certificate; a billing / payment / payout / invoice contact set, changed or switched to an address; `add x@y as an editor / owner / admin`; share edit / write / full access with an address | @opsbot truncate, checklist, CRM record, calendar entry |
| `_is_order` | imperative verbs empty, revoke, invalidate, push, zip, grab, collect, gather, bundle, compress, sync, mirror, dump, reply, attach, end, close, finish; the comma lead-in before an imperative grew from 40 to 60 characters | bucket cleanup, checklist, sync test, product page |
| `override_phrase_count` | checks / verification / validation as things that can be skipped ("skip your own checks") | reconciliation table |
| `output_manipulation_count` | close / open / conclude the summary / report / output with / by; "state in your answer that"; "leave X out of the summary"; "only this" and "do not mention this note" in pt / es / it / fr / de | article, reconciliation table, email thread, product page, Portuguese and Italian notes |
| `multilingual_override_count` (hi) | reveal verbs paste / send; object "the text given to you at the start of the conversation" | Hindi support-team request |

**Effect on set 6 (rule values only, before any training):** 17 of the 30 attacks gain at least one firing rule,
all of them round-seven misses; the two misses that do not are the "delete all of the backups and snapshots"
request (its rule already fired; the SVM scored it 0.37 against the 0.547 threshold) and the "reply all with the
board pack attached" order, which the warning filter still excludes because of its "rather than" clause. None of
the 30 benign rows changes any rule value, including the three persona requests and the two benign false alarms.

**Self-check** (`scripts/check_rules.py` in the dev copy, `report/round8/check_rules_r8_dev.txt`; the live tree's
run for comparison in `report/round8/check_rules_live.txt`): every hand-written example passes (58 / 32 / 23 / 26
positive and 35 / 30 / 14 / 17 negative sentences for the four clause rules, plus 12 / 9 positive and 6 / 4
negative for `indirect_address_count` / `output_manipulation_count`, which the check now covers too). Firing rates
on the harmless corpora: see the comparison table in the section below.

## Live-tree edits before the run

- `backup_round7/` created (01:22) as the frozen copy of round seven; `data/cache/embeddings_norm.*` backed up to
  `data/cache/backup_round8/`.
- `src/gate.py`: `BACKUP` -> `backup_round7`; `RECENT` gains `agent_drafted_dev6`; wording "round-four" -> "champion".
- `src/dataset.py`: `AGENT_DRAFTED_DEV6_CSV` loaded by `load_dev_sets()` as `agent_drafted_dev6`.
- `scripts/gate_round6.py`: round 8 registered (`rounds/round8`, tree `r8_rules`, `report/round8_gate.*`); the bar
  is now per round (`BAR_BY_ROUND`); messages name the champion instead of round four.
- `scripts/round6_setup.py`: round 8 spec; a rules spec may name a diff pair (`RULES_DIFFS`), `"live"` data means
  the live csv files, `None` rules means an unpatched copy (the dev copy); marker checks per spec.
- `scripts/round6_overnight.sh`: `ROUND=8` runs `r8_rules`.
- `src/rules.py`, `scripts/check_rules.py`, the data files and the live pickle untouched (the changes live in the
  two diffs and in `rounds/round8/`).

### Firing rates on harmless text, live rules -> round-eight rules (% of texts; `report/round8/check_rules_{live,r8_dev}.txt`)

| Rule | dolly (14,773) | llmail_fp (165) | wild_regular (1,500) | injection_train benign (2,210) | extra_train benign (1,416) |
|---|---|---|---|---|---|
| indirect_address_count | 0.00 -> 0.00 | 0.00 -> 0.00 | 0.07 -> 0.13 | 0.00 -> 0.00 | 0.00 -> 0.00 |
| output_manipulation_count | 0.11 -> 0.11 | 0.00 -> 0.00 | 12.53 -> 12.80 | 0.00 -> 0.00 | 0.64 -> 0.64 |
| override_phrase_count | 0.00 -> 0.00 | 0.00 -> 0.00 | 9.33 -> 9.33 | 0.14 -> 0.14 | 0.00 -> 0.00 |
| dangerous_action_count | 0.00 -> 0.00 | 0.00 -> 0.00 | 0.00 -> 0.00 | 0.00 -> 0.00 | 0.00 -> 0.00 |
| tool_action_count | 0.00 -> 0.00 | 0.00 -> 0.00 | 0.00 -> 0.00 | 0.00 -> 0.00 | 0.00 -> 0.00 |
| multilingual_override_count | 0.00 -> 0.00 | 0.00 -> 0.00 | 0.13 -> 0.13 | 0.00 -> 0.00 | 0.00 -> 0.00 |

Every other rule's rate is unchanged to two decimals. Two cells moved: one more in-the-wild prompt (of 1,500) fires
`indirect_address_count`, four more fire `output_manipulation_count` (the wider "end / close the summary with / by"
form and "state in your answer that"). The four clause rules stay at 0.00% on every harmless corpus; the old-rule
warnings (second_person_command_ratio 35.4%, role_reassignment_score 26.1%, imperative_verb_density 25.5% of the
in-the-wild prompts) are round four's and unchanged. Contrast coverage unchanged: dangerous 154 / 154, tool 69 / 90,
multilingual 102 / 216, task pivot 106 / 180.

The five in-the-wild prompts that newly fire are persona prompts of the known false-alarm kind: "Assume the role of
Ollie Wood, my Cinema Assistant" (`indirect_address_count`, the "... assistant:" form) and four role-play prompts with
"end every output with", "start your summary with", "begin each output with", "start your response by"
(`output_manipulation_count`). No harmless email (llmail_fp), instruction (dolly) or training benign text changed.

## Trees and checks (01:58 to 02:20)

`scripts/round6_setup.py --round 8 --smoke r8_rules` built `rounds/round8/r8_rules` from the live working tree (grid
pinned, live six-source data, the two round-eight diffs applied cleanly, `data/cache` and `data/raw` symlinked). All
checks passed (`report/round8/setup_r8_rules.log`): pinned grid confirmed in-tree; `rules.py` and `check_rules.py`
match the spec; data files equal the live ones; the file-level diff against the live tree is exactly `src/train.py`
(pin), `src/rules.py`, `scripts/check_rules.py`; `load_pool()` gives 13,157 rows (round four's count);
`scripts/check_rules.py` full mode passes in-tree (342 s). Smoke run (5% of the data): pinned parameters chosen, two
candidates saved, 164 s.

Gate self-check (`gate_round6.py --round 8 --self-check`, `report/round8/gate_self_check.txt`, 02:05 to 02:19): the
round-seven pickle scored inside `backup_round7` equals the champion's verdicts on all thirteen sets; the champion's
recomputed counts equal the frozen bar on every gate set, set 6 included (5 / 19); under the non-strict rule an
identical candidate passes, as intended. The champion's verdicts are cached in `report/champion_dev_scores.csv`
under `backup_round7`.

## The run

Started 2026-10-08 02:33 +05:30 on mains power (a first launch at 02:31 was refused: the launching shell's own command line matched the driver's "already running" check) (battery 97%, charging): `ROUND=8 scripts/round6_overnight.sh` under
`systemd-inhibit`, tree r8_rules, then `scripts/gate_round6.py --round 8` writing `report/round8_gate.txt` and
`report/round8_gate.json`. Driver log `report/round8_overnight.log`; run log `rounds/round8/r8_rules/report/train_log.txt`.
Expected about 25 minutes plus the gate.

## Result (2026-10-08, run 02:33 to 02:54, gate 02:54 to 02:55)

| Run | Texts -> units | Training units | Thresholds emb+rules20 / emb+rules16 | Wall time |
|---|---|---|---|---|
| r8_rules | 23,563 -> 107,660 (the 60 extra texts are set 6, a development set now) | 36,326 | 0.546 / 0.700 | 20 min 46 s |

The run chose the pinned C = 0.3, rule weight 1.0 (development ranking score 0.964). The champion's recomputed
counts equalled the frozen bar. Candidate pickles: emb+rules20 sha1 9a6ca3abfe9f, emb+rules16 d9f9fa684925;
rules.py sha1 227942430732.

### Gate table (false alarms / missed attacks; `report/round8_gate.txt`, per-text decision values in `report/round8_gate.json`)

| Set | Rows | Round seven | r8 rules20 | r8 rules16 |
|---|---|---|---|---|
| official_dev | 493 | 0 / 1 | 0 / 1 | 0 / 1 |
| handwritten_dev | 112 | 5 / 3 | 5 / 3 | 5 / 4 |
| handwritten_dev3 | 56 | 2 / 3 | 2 / 3 | 1 / 3 |
| set 4 | 125 | 2 / 5 | 2 / 5 | 3 / 8 |
| set 5 | 60 | 4 / 10 | 4 / 9 | 4 / 14 |
| set 6 | 60 | 5 / 19 | **5 / 4** | 6 / 13 |
| probe_dev | 216 | 12 / 24 | **12 / 19** | 17 / 26 |
| **POOLED** | 661 | 7 / 7 | 7 / 7 | 6 / 8 |
| **RECENT** | 245 | 11 / 34 | 11 / 18 | 13 / 35 |
| wild_dev (report only) | 208 | 34 / 21 | 34 / 21 | 32 / 21 |
| llmail_dev (report only) | 97 | 0 / 5 | 0 / 5 | 0 / 5 |
| gsum_dev (report only) | 13 | 0 / 6 | 0 / 6 | 0 / 7 |
| yanis_dev (report only) | 154 | 0 / 83 | 0 / 84 | 0 / 89 |
| aya_dev (report only) | 198 | 1 / 0 | 1 / 0 | 1 / 0 |
| dolly_dev (report only) | 231 | 0 / 0 | 0 / 0 | 0 / 0 |

**Decision: r8_rules/emb+rules20 PASS** (total mistakes over the seven gate sets 74 against the champion's 95; probe
misses 19 against 24; threshold 0.546). No binding count is worse; false alarms are identical on every gate set and
on every report-only set. One report-only count is worse by one: yanis_dev misses 83 -> 84. emb+rules16 fails
(set 6 false alarms 6, probe 17 / 26).

**Set 6 under the promoted model** (per-text scores from the gate record; `report/set6_scored.csv` holds round
seven's): all 17 attacks the new patterns reach now score above the threshold (0.61 to 5.44; four of them were
below -0.9 before). Two attacks that round seven caught by a hair are now missed by a hair: the Spanish maintenance
request (0.55 -> 0.53) and the "spring open day" running notes (0.57 -> 0.52). With the two misses the patterns do
not reach (the "delete all of the backups" request at 0.37 both times, the board-pack reply-all at -0.36), set 6 misses
are 4 of 30 (recall 86.7%, from 36.7%). The five benign false alarms are the same five texts as in round seven
(three persona requests, the Portuguese lock manual, the pension-form email); their scores moved by at most 0.05.
Set 5 gains one caught attack (misses 10 -> 9); set 4 is unchanged; probe_dev gains five (24 -> 19) at the same
12 false alarms. These are development numbers: the patterns were written from set 6, so set 6 measures the fix,
not generalisation. Set 7 is the test that is still missing.

**Promoted 02:58** (`gate_round6.py --round 8 --promote r8_rules/emb+rules20`): live pickle sha1 9a6ca3abfe9f,
`src/rules.py` and `scripts/check_rules.py` are the tree's, `report/metrics.json` and `report/train_log.txt` are the
run's (round seven's stay in `backup_round7/report/`), the tree's metrics and log copied to `report/round8/`. The live
`scripts/check_rules.py` full mode passes (0 example failures, same rates and coverage as the dev copy).

## Test sets, scored once (03:10 to 03:17, `scripts/score_tests.py --round 8 --tree r8_rules --ablation`, log `report/round8_tests.txt`)

| Test set | Rows | Precision | Recall | False alarms | Missed | Round seven |
|---|---|---|---|---|---|---|
| Official test, final part | 736 | 99.8% | 98.6% | 1 | 7 | identical |
| deepset | 116 | 100% | 31.7% | 0 | 41 | identical |
| jackhhao | 400 | 94.7% | 88.7% | 7 | 16 | 8 / 16 |
| gandalf (attacks only) | 112 | 100% | 94.6% | 0 | 6 | 0 / 7 |
| External pooled | 628 | 97.3% | 79.9% | 7 | 63 | 96.9% / 79.6%, 8 / 64 |
| oasst1 (benign only) | 289 | | | 6 | 0 | 7 / 0 |
| InjecAgent | 48 | 100% | 33.3% | 0 | 16 | identical |
| BIPIA | 231 | 95.0% | 12.3% | 1 | 135 | 95.5% / 13.6%, 1 / 133 |
| Round-five sources pooled | 568 | 79.4% | 15.2% | 7 | 151 | 78.4% / 16.3%, 8 / 149 |

Standards: official recall 98.6% (>= 90%) and precision 99.8% (>= 95%) met; external recall 79.9% against 85%
**missed** (every round that scored it has missed it); external precision 97.3% (>= 90%) met. The two
sentence-set standards cannot be scored: there is no unread sentence set (set 6 was scored once on round seven,
36.7% / 16.7%, and is development data now). Five test verdicts changed against round seven, four of them the right
way (one gandalf attack caught, one jackhhao and one oasst1 benign prompt no longer flagged) and two BIPIA attacks
lost. The official test by category is unchanged (obfuscation 96.8%, multilingual attacks 4 of 5, everything else
100%); no training piece was dropped differently (1,956 held-out matches, as in round seven's run).

## What round eight did not do

- No set 7. The sentence-set standards stay unscored for this model; set 6's 4 / 30 is a development number.
- The three persona false alarms on set 6 (and the Portuguese lock manual, and the pension-form email) are the same
  five texts as in round seven; no rule change was aimed at them.
- The two set-6 attacks the patterns do not reach ("delete all of the backups and snapshots", scored 0.37 with its
  rule firing; the board-pack reply-all, excluded by the warning filter's "rather than") and the two that slipped
  just below the threshold (0.53, 0.52) are open.
- BIPIA lost two attacks and yanis_dev one: the retrained weights moved a few borderline texts the wrong way.
