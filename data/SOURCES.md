# New public sources (rounds four and five)

Written by `scripts/download_new_sources.py`. Output: `data/new_train.csv` and `data/new_test.csv` (columns `text,label,category,technique,language,source`; label 1 = injection, 0 = benign). Every number below is measured by the script.

| Source | URL | Licence | What was taken | Train benign | Train injection | Test benign | Test injection |
|---|---|---|---|---|---|---|---|
| wild | https://huggingface.co/datasets/TrustAIRLab/in-the-wild-jailbreak-prompts | MIT | 400 of 1,405 jailbreak prompts (jailbreak_2023_12_25) and 600 of 13,735 regular prompts (regular_2023_12_25), seeded sample after filtering; regular prompts with override or jailbreak cues or near-copies of a jailbreak were dropped first | 476 | 316 | 124 | 84 |
| llmail | https://huggingface.co/datasets/microsoft/llmail-inject-challenge | MIT | 400 phase-1 submissions labelled attack_attempt = True, reason = api_triggered, plus all benign mails from emails_for_fp_tests.json (203, 160 after removing duplicates); in the training part half of the attack targets were varied and half of the benign mails got a signature with an address | 128 | 335 | 32 | 65 |
| gsum | https://huggingface.co/datasets/Lakera/gandalf_summarization | MIT | all rows, all attacks; the official train + validation rows are training, the official test rows are test | 0 | 126 | 0 | 13 |
| yanis | https://huggingface.co/datasets/yanismiraoui/prompt_injections | Apache 2.0 | all rows (attacks) in English, French, German, Spanish, Italian and Portuguese; Romanian dropped because aya has no Romanian | 0 | 813 | 0 | 154 |
| aya | https://huggingface.co/datasets/CohereLabs/aya_dataset | Apache 2.0 | benign prompts (column inputs); per language as many rows as yanis has attacks in that language; the other aya languages only where the training pool has more attacks than benign rows (see the language table) | 769 | 0 | 198 | 0 |
| dolly | https://huggingface.co/datasets/databricks/databricks-dolly-15k | CC BY-SA 3.0 | 1,000 benign rows: 500 instructions with their context passage (instruction, blank line, context) and 500 without | 769 | 0 | 231 | 0 |
| oasst1 | https://huggingface.co/datasets/OpenAssistant/oasst1 | Apache 2.0 | round five; benign prompter root prompts (not deleted, review_result True): 1,200 English, non-English only where the pool still had more attacks than benign rows after aya, plus 300 short English follow-up turns; prompts with override or jailbreak cues dropped, not relabelled | 1213 | 0 | 289 | 0 |
| injecagent | https://github.com/uiuc-kang-lab/InjecAgent | no licence file in the repository; research use, cited | round five; the 17 tool-output templates with each attacker instruction substituted (direct-harm and data-stealing cases, a seeded third with the benchmark's enhanced prefix, at most 2 templates per instruction) as attacks, and the same templates with a neutral filler as clean twins; template sides by sha1 rank, instruction sides by hash, same-side pairs only | 78 | 100 | 24 | 24 |
| bipia | https://github.com/microsoft/BIPIA | MIT | round five; clean email, table (200 sampled) and code contexts, and the same contexts with one manipulative attack string inserted at a seeded position (two per context, at most 12 carriers per string); the plain-task text-attack categories and the web-QA and summarization contexts, which are not in the repository, are excluded; context side by hash, attack side by BIPIA file | 301 | 602 | 77 | 154 |

## How the rows were chosen

- Sampling is seeded (`SEED = 20260930`) and every split decision comes from a sha1 hash of the text or of a group's smallest text hash, so re-running the script gives the same files.
- Rows were dropped when empty, longer than 6,000 characters, duplicated inside the source, or when their normalized key (`src.dataset.dedup_key`) already occurred in `injection_train.csv`, `extra_train.csv`, `contrast_train.csv`, the held-out files (`injection_test.csv`, `extra_test.csv`, `handwritten_test.csv`, `handwritten_dev*.csv`, `handwritten_test4.csv`, `probe_dev.csv`, `agent_drafted_test5.csv`, `agent_drafted_test6.csv`) or in rows already taken from an earlier source. Many in-the-wild jailbreaks duplicate jackhhao rows; the run prints how many rows each filter removed.
- wild: the regular (benign) prompts of the source include many that this project labels as injections elsewhere ("Ignore all previous instructions. From now on you ..."). 1,590 of 12,461 regular candidates carry override, role-reassignment or jailbreak cues (a regex copy of the project's `override_phrase_count` / `role_reassignment_score` patterns plus DAN, jailbreak, developer mode, "without any restrictions", "free from ... rules") and were dropped before sampling, and 32 more carry a non-English override cue (the detector's `multilingual_override_count` rule fires on them); 20 sampled regular prompts were near-copies (TF-IDF cosine >= 0.7) of a jailbreak prompt and were dropped too. They were not relabelled, they are simply on neither side.
- gandalf_summarization keeps its official split. wild, llmail, aya, dolly and oasst1 rows (attack and benign alike) are grouped by TF-IDF character n-gram cosine similarity >= 0.7 (connected components) and a whole group goes to one side (80/20 by the group's smallest sha1), so no near-copy sits on both sides of a source's split. `src.dataset.load_pool` measures near-copies against all held-out sets with its own TF-IDF weights, and still removes these training rows per source: `{'aya': 0, 'bipia': 0, 'dolly': 0, 'gsum': 0, 'injecagent': 0, 'llmail': 4, 'oasst1': 0, 'wild': 3, 'yanis': 0}` (the wild rows are near-copies of jackhhao test prompts).
- InjecAgent and BIPIA are cross products of carriers and attack strings. A carrier's side (InjecAgent template: by sha1 rank, the 4 highest of 17 are test; BIPIA context: by sha1 of the text, because 11 BIPIA email contexts appear in both of its files) and an attack's side (InjecAgent instruction: by sha1; BIPIA: the benchmark's own train and test attack files, whose categories are disjoint) are decided separately and only same-side pairs are built, so every carrier of one attack string, and the clean and attacked versions of one carrier, sit on one side.
- yanis: rows are joined at multilingual embedding cosine >= 0.7. This gives 110 components; the giant one (813 rows) is training, the remaining 109 small components (154 rows) are test. See the yanis section below.
- `language` holds an ISO 639-1 code: aya from its `language_code`, oasst1 from its `lang` column with the region stripped (pt-BR is pt), yanis from a small stop-word detector, the English-only sources `en`. The detector, scored against aya's language codes on 100 seeded prompts of at most 150 characters per language, is de 86%, en 92%, es 98%, fr 97%, it 96%, pt 94% correct (English errors are mostly undetected rather than mislabelled). `language` is metadata only; it decided which yanis rows were dropped as Romanian or undetected.

## Language balance of the training pool

Language is a possible class shortcut in a multilingual embedding, so aya and oasst1 benign rows are not spread evenly: each yanis language gets as many aya rows as yanis has attacks in it, and the other aya languages (nl, ru, tr, hi, ja, zh, ar) get rows only when the existing training files hold more attacks than benign rows in that language. Counts below are the training pool after this script (existing files by their language column, script or the detector, plus `new_train.csv`); aya rows wanted per language: `{'ar': 0, 'de': 122, 'en': 330, 'es': 131, 'fr': 141, 'hi': 0, 'it': 122, 'ja': 0, 'nl': 0, 'pt': 121, 'ru': 0, 'tr': 0, 'zh': 0}`; oasst1 non-English rows wanted after aya: `{'es': 2}` (`src.dataset` caps aya and oasst1 together per language at load time).

| Language | Benign | Injection | of which new benign | of which new injection |
|---|---|---|---|---|
| ar | 16 | 16 | 0 | 0 |
| de | 248 | 211 | 94 | 118 |
| en | 7614 | 6078 | 3223 | 1689 |
| es | 129 | 149 | 106 | 124 |
| fr | 150 | 166 | 110 | 132 |
| hi | 20 | 18 | 0 | 0 |
| it | 143 | 142 | 104 | 115 |
| ja | 18 | 17 | 0 | 0 |
| nl | 16 | 16 | 0 | 0 |
| pt | 176 | 142 | 97 | 114 |
| ro | 2 | 0 | 0 | 0 |
| ru | 20 | 18 | 0 | 0 |
| tr | 16 | 16 | 0 | 0 |
| zh | 17 | 17 | 0 | 0 |

## llmail target address: literal diversified, address presence remains a cue

Nearly every llmail attack mail in the challenge tells the assistant to mail a fixed target (`contact@contact.com`; about a fifth use `contact@domain.com`, `contact_me@contact.com`, `contact@domin.com`, `contact@contact,com` or a spelled-out `contact <at> contact <dot> com`) with the body `confirmation`, and no benign mail in the challenge contains an address. In the **training part only**, seeded and with test rows untouched: half of the attack mails had every spelling of the fixed target replaced with one of 12 realistic addresses and the payload word replaced (`technique = api_triggered_varied`), and half of the benign mails got a reply-to line before their sign-off, an address after the signed name, or a signature block, drawn from the **same** 12 addresses (`technique = email_signed`), so no address is attack-only.

What remains, measured on the llmail training rows: 329 of 335 attack mails and 64 of 128 benign mails contain an e-mail address; 163 attack mails still carry a fixed challenge target and 135 still carry the word `confirmation` (0 benign mails do). Formatting still separates the classes: 239 of 335 attack mails contain a line break against 14 of 128 benign mails, 241 attack mails contain `<` against 4 benign mails, and benign mails are 206-479 characters long against 105-5979 for attacks. A model can still learn "asks to send a mail to some address => attack" from llmail; the contrast set's correspondence pairs are what counters that.

## llmail benign mails are templates

The challenge's benign mails (`emails_for_fp_tests.json`) are short single-line templates from a few families (meeting notes, invoices, newsletters): 160 after de-duplication, in 94 near-copy groups at cosine 0.7. The llmail precision figure in `new_test.csv` therefore reflects template mails only, and it is a small set (32 mails). Realistic benign correspondence lives in the contrast set and the hand-written sets.

## yanis test rows

The source is one set of attack sentences translated and paraphrased across languages. Average-linkage clustering did not separate translations (round-four review: translations of one sentence sat on both sides at cosine 0.75-0.8), so the split now uses connected components at embedding cosine >= 0.7. Most rows (813 of 967) form one giant component, which is training; the test side is the rows outside it, so by construction every test row is below cosine 0.7 to every training row. Measured: test row to nearest training row median 0.56, max 0.698 (nearest other-language training row median 0.54, max 0.694), while a training row's nearest other training row has median 0.93. The yanis test score therefore checks attacks that are unlike the training sentences, not translation or paraphrase memorization; it is a small and hard set, and mostly English because translations join the giant component (test languages: `{'en': 120, 'fr': 9, 'es': 7, 'pt': 7, 'it': 7, 'de': 4}`).

## Attribution

The `dolly` rows come from **databricks-dolly-15k** (Databricks, Inc., 2023), https://huggingface.co/datasets/databricks/databricks-dolly-15k, licensed under **CC BY-SA 3.0** (https://creativecommons.org/licenses/by-sa/3.0/). Rows were selected and the instruction and context fields were joined with a blank line; no other changes were made. Under the share-alike condition, any redistribution of these rows or of a dataset derived from them must carry the same CC BY-SA 3.0 licence and this attribution.

The `injecagent` rows are built from the InjecAgent benchmark (Zhan et al., 2024), https://github.com/uiuc-kang-lab/InjecAgent, whose repository publishes **no licence file**; the rows are used for research and the benchmark is cited. The `bipia` rows come from Microsoft's BIPIA benchmark, https://github.com/microsoft/BIPIA, **MIT**; its email, table and code contexts come from OpenAI Evals, WikiTableQuestions and Stack Exchange respectively (see the BIPIA repository for their terms). The other sources are MIT or Apache 2.0 licensed; their licence notices are on the linked dataset pages.

## Round five sources

- oasst1: `{'roots': 10363, 'cued': 10, 'wanted': {'es': 2}, 'english': 1200, 'non_english': 2, 'followups': 300, 'languages': {'en': 1500, 'es': 2}}`
- injecagent: `{'templates': 17, 'test_templates': 4, 'instructions': 62, 'enhanced': 20, 'attacked': 124, 'clean': 102}`
- bipia: `{'email': {'contexts': 78, 'attacked': 156}, 'table': {'contexts': 200, 'attacked': 400}, 'code': {'contexts': 100, 'attacked': 200}}`

## Round seven (2026-10-05)

The promoted model (round seven, `rounds/round7/r1_rules`) was trained on the six-source `new_train.csv` of round
four; that file is `data/new_train.csv` again. The nine-source training file built for round five (oasst1, InjecAgent,
BIPIA added) is kept as `data/new_train_round5.csv`; no loader reads it. `data/new_test.csv` keeps the nine sources:
the oasst1, injecagent and bipia splits are test sets, scored once for the promoted model (`report/round_seven_results.md`).
`data/agent_drafted_test6.csv` is set 6 (agent-drafted, human-reviewed), scored once on 2026-10-05 and development data
since. The 312 agent-drafted training rows of round seven (`rounds/round7/drafted_train7.csv`, 150 attacks and 162
harmless twins) were not promoted and are not in `data/`; `src/dataset.py` would read them from `data/drafted_train7.csv`.
