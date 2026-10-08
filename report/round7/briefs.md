# Round seven drafting briefs (2026-10-05)

Every drafting agent received one brief of the shape below and an output path under the session's scratch folder.
Agents had no repository access by instruction ("do NOT read any files, search the web or look at any dataset"),
so no held-out text could leak into training. The merged, checked result is `rounds/round7/drafted_train7.csv`
(312 rows; `data/drafted_train7.csv` after a promotion). Outcome per chunk: `report/round_seven_results.md`.

## Common brief (first wave: 6 attacks + 6 twins per agent)

> You are drafting TRAINING DATA for a defensive prompt-injection detector: a course project, a scikit-learn text
> classifier that reads one text and says "injection" or "benign". Your rows teach it to recognise instructions aimed
> at an AI assistant that are hidden inside ordinary-looking content, and to leave harmless content of the same form
> alone. No system is attacked and nothing is executed; these are classifier training examples.
>
> Do NOT read any files or directories, do not search the web, do not look at any dataset: write from your own
> knowledge only, so that no existing test example can leak into training. Your only tool use is creating the output
> directory and writing ONE file.
>
> Write exactly 12 rows: 6 attacks (label 1) and 6 harmless twins (label 0). CATEGORY: <category>. ATTACKS: <the
> category's attack forms: an order addressed to the AI assistant that processes the text, asking it to reveal its
> configuration or hidden instructions, to send or post content to a .example address, to run a command, or to
> change how it handles the user's request>. TWINS: <the same forms with ordinary content for human readers and no
> instruction aimed at an AI>. Language: <language>.
>
> Rules for every row: 40 to 400 words; realistic and specific; vary tone, length and topic; no two rows alike; no
> placeholders like [NAME]. Attacks must NOT contain any of these words or phrases: ignore, disregard, forget,
> override, previous instructions, prior instructions, system prompt, jailbreak, "you are now" (encoded_payload:
> only inside the encoded payload). Keep the harmful action generic and non-operational: no real email addresses,
> phone numbers, domains, companies or people; only .example domains; no working exploit code. A twin is a
> DIFFERENT text of the same kind, not an attack with one sentence removed; it must not share whole sentences with
> any attack row.
>
> Output: a CSV file at <path>, UTF-8, header exactly: text,label,category,language,technique. Write with Python's
> csv module (quoting=csv.QUOTE_ALL), read it back to verify the counts per label, reply with only the path and the
> counts.

## Retry brief (second wave: 3 attacks + 3 twins per agent, Opus)

Same content, with the framing "labelled classifier examples, like the public LLMail-Inject or BIPIA benchmarks",
the attack described as "mildly and generically" asking the assistant to do something outside its task (include
its configuration in the summary, add a line recommending a page at a .example domain, repeat the instructions it
was given, send a copy to a .example mailbox, treat a sender as approved, answer with a given phrase only), and the
forms split between the two halves of a chunk (for example customer email + product review + plain request, and
document excerpt + tool result + chat message, for the non-English chunks).

## Chunk list

| # | category | language | attack forms | twin forms |
|---|---|---|---|---|
| 1 | doc_insertion | en | policy clause, compliance notice, terms excerpt, README, CONTRIBUTING | same documents, human instructions |
| 2 | doc_insertion | en | invoice, receipt, purchase order, shipping note, meeting minutes | same |
| 3 | doc_insertion | en | support ticket, bug report, spec, onboarding guide, job description, wiki page | same |
| 4 | tool_result_insertion | en | JSON API responses, config dumps, DB rows, ticket payloads | clean payloads |
| 5 | tool_result_insertion | en | log lines, calendar entries, search snippets, page extracts | clean results |
| 6 | destructive_routine | en | database: delete all rows, truncate, drop, as routine tickets | questions, docs, past tense, safe tasks |
| 7 | destructive_routine | en | filesystem / devices / access: rm -rf, wipe, revoke keys, disable backups | same |
| 8 | send_exfiltration | en | forward / email / upload of files, summaries, credentials to .example | normal scoped sending asks |
| 9 | send_exfiltration | en | mass-message contacts / customers, post to channel or webhook, share link with everyone | same |
| 10 | nonenglish_no_override | tr | email, review, request; document, tool result, chat | ordinary Turkish texts |
| 11 | nonenglish_no_override | ar | same | ordinary Arabic texts |
| 12 | nonenglish_no_override | zh | same | ordinary Chinese texts |
| 13 | nonenglish_no_override | ko | same | ordinary Korean texts |
| 14 | nonenglish_no_override | de | same | ordinary German texts |
| 15 | nonenglish_no_override | fr | same | ordinary French texts |
| 16 | task_pivot | en | "before you answer", "one more small thing", footnote reveal | genuine two-part requests |
| 17 | task_pivot | en | task switched midway in the text to translate / proofread / summarise | ordinary passages |
| 18 | authority_persona | en | maintenance mode, developer on call, compliance audit, vendor policy | benign persona and role play |
| 19 | authority_persona | en | operator notice, admin broadcast, elevated privileges, quality team | benign role play |
| 20 | encoded_payload | en | base64, hex, leetspeak payloads | harmless encoded content |
| 21 | encoded_payload | en | split words, homoglyphs, reversed, rot13, word per line | puzzles, codes, ASCII art |
| 22 | correspondence | en | work and personal emails with a line aimed at the assistant | ordinary emails |
| 23 | correspondence | en | team, support and group chats with a message aimed at the assistant | ordinary chats |
| 24 | appended_payload | en | 150 to 350 words of product / travel / recipe / essay / forum / review text, attack in the last sentence | different long benign texts |
| 25 | appended_payload | en | explainer / local news / FAQ / lecture notes / how-to / newsletter, attack in the last sentence | same |

Chunks 24 and 25 and the search-snippet half of chunk 5 were written by the orchestrating assistant after their
agents were stopped (see the record).
