"""Download the round-four public sources and write data/new_train.csv and data/new_test.csv.

    TrustAIRLab/in-the-wild-jailbreak-prompts   MIT           400 jailbreaks + 600 regular prompts
    microsoft/llmail-inject-challenge           MIT           400 api_triggered attack mails + all benign mails
    Lakera/gandalf_summarization                MIT           all rows, official split kept
    yanismiraoui/prompt_injections              Apache 2.0    all rows in languages that aya also covers
    CohereLabs/aya_dataset                      Apache 2.0    benign prompts, per language as many as yanis attacks
    databricks/databricks-dolly-15k             CC BY-SA 3.0  1,000 benign instructions, half with context

Sampling is seeded. Rows are dropped when empty, longer than 6,000 characters, or when their
normalized key already occurs in the existing training files, in the held-out files, or in
rows already taken. Regular in-the-wild prompts that carry override or jailbreak cues, or that
are near-copies of a jailbreak prompt, are dropped as well (not relabelled).

Splits: gandalf_summarization keeps its official split. wild, llmail, aya and dolly rows are
grouped by TF-IDF near-copy (connected components at cosine >= 0.7) and a whole group goes to
one side (80/20), decided by a sha1 hash. yanis rows are grouped by the multilingual sentence embedding at cosine
>= 0.7; the giant component is training and the small components are test. Measurements are
written to data/SOURCES.md.

Run from the project root:
    python scripts/download_new_sources.py
"""
import hashlib
import json
import re
import sys
from pathlib import Path
from urllib.request import urlretrieve

import numpy as np
import pandas as pd
from scipy.sparse.csgraph import connected_components
from sklearn.feature_extraction.text import TfidfVectorizer

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from src.dataset import dedup_key   # noqa: E402

DATA = ROOT / "data"
RAW = DATA / "raw" / "new"
HF = "https://huggingface.co/datasets/{repo}/resolve/main/{path}"

SEED = 20260930
MAX_CHARS = 6000
TRAIN_SHARE = 0.8
GROUP_SIM = 0.7          # TF-IDF char n-gram cosine that joins two near-copies (wild, llmail)
YANIS_GROUP_SIM = 0.7    # embedding cosine that joins two yanis rows (translations, paraphrases)
WILD_ATTACKS, WILD_REGULAR, LLMAIL_ATTACKS = 400, 600, 400
COLUMNS = ["text", "label", "category", "technique", "language", "source"]
NOTES = {}               # measurements the builders record for SOURCES.md

FILES = {
    "wild_jailbreak.parquet": ("TrustAIRLab/in-the-wild-jailbreak-prompts",
                               "jailbreak_2023_12_25/train-00000-of-00001.parquet"),
    "wild_regular.parquet": ("TrustAIRLab/in-the-wild-jailbreak-prompts",
                             "regular_2023_12_25/train-00000-of-00001.parquet"),
    "llmail_p1.json": ("microsoft/llmail-inject-challenge",
                       "data/labelled_unique_submissions_phase1.json"),
    "llmail_fp.json": ("microsoft/llmail-inject-challenge", "data/emails_for_fp_tests.json"),
    "gsum_train.parquet": ("Lakera/gandalf_summarization",
                           "data/train-00000-of-00001-44378fdb62cbf9b7.parquet"),
    "gsum_validation.parquet": ("Lakera/gandalf_summarization",
                                "data/validation-00000-of-00001-c7b174a69fca3472.parquet"),
    "gsum_test.parquet": ("Lakera/gandalf_summarization",
                          "data/test-00000-of-00001-1696577a5023b698.parquet"),
    "yanis.csv": ("yanismiraoui/prompt_injections", "prompt_injections.csv"),
    "aya_train.parquet": ("CohereLabs/aya_dataset", "data/train-00000-of-00001.parquet"),
    "dolly.jsonl": ("databricks/databricks-dolly-15k", "databricks-dolly-15k.jsonl"),
}

EXISTING_TRAIN = ["injection_train.csv", "extra_train.csv", "contrast_train.csv"]
HELD_OUT = ["injection_test.csv", "extra_test.csv", "handwritten_test.csv",
            "handwritten_dev.csv", "handwritten_dev2.csv", "handwritten_dev3.csv",
            "handwritten_test4.csv", "probe_dev.csv"]

# yanis languages first; aya offers no Romanian, so yanis' few Romanian rows are dropped
YANIS_LANGUAGES = ["en", "fr", "de", "es", "it", "pt"]
AYA_CODES = {"eng": "en", "fra": "fr", "deu": "de", "spa": "es", "ita": "it", "por": "pt",
             "nld": "nl", "rus": "ru", "tur": "tr", "hin": "hi", "jpn": "ja", "zho": "zh",
             "arb": "ar"}
LANGUAGE_NAMES = {"english": "en", "french": "fr", "german": "de", "spanish": "es",
                  "italian": "it", "portuguese": "pt", "dutch": "nl", "russian": "ru",
                  "turkish": "tr", "hindi": "hi", "japanese": "ja", "chinese": "zh",
                  "arabic": "ar"}
SCRIPTS = [("ar", re.compile(r"[؀-ۿ]")), ("hi", re.compile(r"[ऀ-ॿ]")),
           ("ru", re.compile(r"[Ѐ-ӿ]")), ("ja", re.compile(r"[぀-ヿ]")),
           ("zh", re.compile(r"[一-鿿]"))]

# the same addresses go into varied attack mails and into signed benign mails
ADDRESSES = ["finance@northwind-trading.com", "j.marlow@outlook.com", "helpdesk@acme-corp.co.uk",
             "ops-team@brightline.io", "anna.keller@gmx.de", "invoices@meridian-supply.net",
             "hr@lumen-health.org", "t.okafor@gmail.com", "support@quillstack.app",
             "legal@harbor-and-vale.com", "mike.r@fastmail.fm", "alerts@sentinel-ops.dev"]
PAYLOADS = ["approved", "done", "received", "acknowledged", "ok", "ready", "yes",
            "processed", "completed", "noted"]
NAMES = ["Anna Keller", "James Marlow", "Tunde Okafor", "Mike Reyes", "Priya Nair",
         "Lena Fischer", "Carlos Mendes", "Sofia Rossi", "Daniel Park", "Ruth Adeyemi"]
# lines that carry an address into a benign mail: before its sign-off, after the signed name,
# or as a signature block when the mail has no sign-off
INLINE_LINES = [" Please reply to {address}.", " You can reach me at {address}.",
                " Questions go to {address}.", " Copy {address} on your reply."]
AFTER_NAME = [" ({address})", "\n{address}", " | {address}", " <{address}>"]
BLOCKS = ["\n\nBest regards,\n{name}\n{address}", "\n\n-- \n{name}\n{address}",
          "\n\nThanks,\n{name} ({address})", "\n\n{name}\n{address}"]
SIGNOFF_RE = re.compile(r"(?:regards|best|thanks|cheers|sincerely)[,!]?\s+[A-Z][a-z]+\.?\s*$",
                        re.IGNORECASE)

EMAIL_RE = re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+")


# --------------------------------------------------------------------------- downloads

def fetch(url, dest):
    if dest.exists():
        return dest
    print(f"  downloading {dest.name}")
    dest.parent.mkdir(parents=True, exist_ok=True)
    urlretrieve(url, dest)
    return dest


def raw(name):
    repo, path = FILES[name]
    return fetch(HF.format(repo=repo, path=path), RAW / name)


# --------------------------------------------------------------------------- helpers

def frame(texts, label, category, technique="", language="en"):
    return pd.DataFrame({
        "text": list(texts), "label": label, "category": category,
        "technique": technique, "language": language,
    })


def sha1(text):
    return hashlib.sha1(text.encode("utf-8")).hexdigest()


def known_keys():
    keys = set()
    for name in EXISTING_TRAIN + HELD_OUT:
        path = DATA / name
        if path.exists():
            texts = pd.read_csv(path, keep_default_na=False, usecols=["text"])["text"]
            keys |= set(texts.astype(str).map(dedup_key))
    return keys


def clean(df, source, taken):
    """Drop empty, over-long and duplicate rows; print what each filter removed."""
    n = len(df)
    df = df[df["text"].str.strip() != ""]
    print(f"  {source}: {n - len(df)} empty")
    n = len(df)
    df = df[df["text"].str.len() <= MAX_CHARS]
    print(f"  {source}: {n - len(df)} longer than {MAX_CHARS} characters")
    keys = df["text"].map(dedup_key)
    n = len(df)
    df = df[~keys.duplicated()]
    print(f"  {source}: {n - len(df)} duplicated inside the source")
    keys = keys[df.index]
    n = len(df)
    df = df[~keys.isin(taken)]
    print(f"  {source}: {n - len(df)} already in training, held-out or taken rows")
    return df.reset_index(drop=True)


def take(df, taken):
    taken |= set(df["text"].map(dedup_key))
    return df


def sample(df, n, rng):
    if len(df) <= n:
        return df
    return df.iloc[np.sort(rng.choice(len(df), n, replace=False))].reset_index(drop=True)


def split_by_group(df, groups):
    """Whole groups go to one side, decided by the group's smallest sha1."""
    hashes = df["text"].map(sha1)
    anchor = pd.Series(hashes.values, index=groups).groupby(level=0).min()
    side = anchor.map(lambda h: int(h[:8], 16) % 100 < TRAIN_SHARE * 100)
    return df.assign(split=np.where(side.loc[groups].values, "train", "test"))


def tfidf():
    return TfidfVectorizer(analyzer="char_wb", ngram_range=(3, 5), sublinear_tf=True)


def near_copy_groups(texts, source):
    """Connected components over TF-IDF character n-gram cosine >= GROUP_SIM."""
    matrix = tfidf().fit_transform(texts)
    n_groups, groups = connected_components((matrix @ matrix.T) >= GROUP_SIM, directed=False)
    print(f"  {source}: {n_groups} near-copy groups for {len(texts)} rows")
    NOTES[f"groups {source}"] = int(n_groups)
    return groups


def drop_near_copies(df, reference, source):
    """Drop rows within GROUP_SIM of any reference text."""
    vectorizer = tfidf().fit(pd.concat([df["text"], reference], ignore_index=True))
    similarity = vectorizer.transform(df["text"]) @ vectorizer.transform(reference).T
    close = similarity.max(axis=1).toarray().ravel() >= GROUP_SIM
    print(f"  {source}: {close.sum()} sampled prompts are near-copies of a jailbreak prompt")
    NOTES["wild_copies"] = int(close.sum())
    return df[~close].reset_index(drop=True)


# --------------------------------------------------------------------------- wild

# mirrors override_phrase_count and role_reassignment_score in src/rules.py, plus jailbreak cues;
# regular prompts that carry these are kept out of both sides, not relabelled
_DROP = r"(?:ignore|disregard|forget|override|bypass|set\s+aside|discard|drop|skip|abandon|cancel)"
_WHICH = r"(?:previous|prior|above|earlier|preceding|former|all|any|every|your|their|its|these|those)"
_RULES = (r"(?:instructions?|rules?|guidelines?|prompts?|directions?|directives?|context|"
          r"restrictions?|limits?|filters?|constraints?|setup|configuration|programming|"
          r"training|safeguards?|polic(?:y|ies)|guardrails?|guidance|orders|commands)")
_SAFETY = (r"(?:safety|filter(?:s|ing)?|restrictions?|limits?|guardrails?|moderation|safeguards?|"
           r"content\s+policy|censorship)")
WILD_CUE_PATTERNS = [
    rf"\b{_DROP}\b[^.!?\n]{{0,40}}?\b{_WHICH}\b[^.!?\n]{{0,30}}?\b{_RULES}\b",
    rf"\b{_DROP}\s+(?:everything|anything|all)\s+(?:above|before|prior|so\s+far)\b",
    rf"\b(?:turn\s+off|switch\s+off|disable|deactivate|remove|lift|suspend)\b[^.!?\n]{{0,30}}?\b{_SAFETY}\b",
    r"\byou\s+are\s+now\b",
    r"\bfrom\s+(?:this\s+point|now)\s+on,?\s+you\b",
    r"\bfree\s+(?:from|of)\b[^.!?\n]{0,40}\b(?:rules|restrictions|limits|guidelines|policies|constraints)\b",
    r"\bwithout\s+any\s+(?:restrictions?|limits?|limitations?|rules|filters?|censorship)\b",
    r"\b(?:no|not\s+bound\s+by|not\s+subject\s+to)\s+(?:any\s+)?(?:restrictions?|rules|limitations?|guidelines|content\s+polic(?:y|ies))\b",
    r"\bDAN\b|\bdo\s+anything\s+now\b|\bjailbreak\b|\bdeveloper\s+mode\b",
]
WILD_CUE_RE = re.compile("|".join(f"(?:{p})" for p in WILD_CUE_PATTERNS), re.IGNORECASE)


def build_wild(rng, taken):
    jailbreaks = pd.read_parquet(raw("wild_jailbreak.parquet"))["prompt"].astype(str)
    regular = pd.read_parquet(raw("wild_regular.parquet"))["prompt"].astype(str)
    attacks = clean(frame(jailbreaks, 1, "wild_jailbreak", "jailbreak"), "wild attacks", taken)
    regular = clean(frame(regular, 0, "wild_regular", "prompt"), "wild benign", taken)
    n = len(regular)
    regular = regular[~regular["text"].str.contains(WILD_CUE_RE)].reset_index(drop=True)
    NOTES["wild_cued"], NOTES["wild_regular"] = n - len(regular), n
    print(f"  wild benign: {n - len(regular)} of {n} regular prompts carry override or jailbreak "
          "cues and are dropped")
    # the cue regex is English; non-English override prompts are caught by the detector's own rule
    from src.rules import multilingual_override_count
    from src.normalize import make_views
    foreign = regular["text"].map(lambda t: multilingual_override_count(make_views(t))[0] > 0)
    NOTES["wild_cued_foreign"] = int(foreign.sum())
    regular = regular[~foreign].reset_index(drop=True)
    print(f"  wild benign: {NOTES['wild_cued_foreign']} more carry a non-English override cue and are dropped")
    attacks = take(sample(attacks, WILD_ATTACKS, rng), taken)
    regular = sample(regular, int(WILD_REGULAR * 1.1), rng)
    regular = take(drop_near_copies(regular, jailbreaks, "wild benign").head(WILD_REGULAR), taken)
    df = pd.concat([attacks, regular], ignore_index=True)
    return split_by_group(df, near_copy_groups(df["text"], "wild"))


# --------------------------------------------------------------------------- llmail

_AT = r"(?:@|\[@\]|<at>|\(at\)|\[at\]|\sat\s|/@/|&#64;)"
_DOT = r"(?:[.,]|\[\.\]|<dot>|\(dot\)|\[dot\]|\sdot\s|/\./)"
ADDRESS_RE = re.compile(
    rf"contact(?:_me|\d+)?\s*{_AT}\s*(?:contact|domain|domin)\s*{_DOT}\s*com", re.IGNORECASE)
PAYLOAD_RE = re.compile(r"\bconfirmation\b", re.IGNORECASE)


def build_llmail(rng, taken):
    submissions = json.loads(raw("llmail_p1.json").read_text())
    attacks = [t for t, v in submissions.items()
               if v.get("attack_attempt") == "True" and v.get("reason") == "api_triggered"]
    benign = json.loads(raw("llmail_fp.json").read_text())
    attacks = frame(attacks, 1, "llmail_attack", "api_triggered")
    benign = frame(benign, 0, "llmail_benign", "email")
    attacks = take(sample(clean(attacks, "llmail attacks", taken), LLMAIL_ATTACKS, rng), taken)
    benign = take(clean(benign, "llmail benign", taken), taken)
    attacks = split_by_group(attacks, near_copy_groups(attacks["text"], "llmail attacks"))
    benign = split_by_group(benign, near_copy_groups(benign["text"], "llmail benign"))
    attacks = vary_llmail_targets(attacks, rng)
    benign = sign_llmail_benign(benign, rng)
    llmail_notes(attacks, benign)
    return pd.concat([attacks, benign], ignore_index=True)


def _keep_case(replacement, match):
    return replacement.upper() if match.group(0).isupper() else replacement


def vary_llmail_targets(attacks, rng):
    """In half of the TRAIN attack mails, swap the challenge's fixed target address and the
    payload word "confirmation" for varied realistic ones."""
    train = np.flatnonzero((attacks["split"] == "train").to_numpy())
    chosen = rng.choice(train, len(train) // 2, replace=False)
    texts = attacks["text"].to_numpy(dtype=object)
    changed = 0
    for i in chosen:
        address, payload = rng.choice(ADDRESSES), rng.choice(PAYLOADS)
        new = ADDRESS_RE.sub(lambda m: _keep_case(address, m), texts[i])
        new = PAYLOAD_RE.sub(lambda m: _keep_case(payload, m), new)
        if new != texts[i]:
            texts[i] = new
            attacks.loc[i, "technique"] = "api_triggered_varied"
            changed += 1
    attacks["text"] = texts
    print(f"  llmail attacks: {changed} of {len(chosen)} chosen train mails had their "
          f"address or payload replaced")
    return attacks


def with_address(text, rng):
    """Put one of the shared addresses into a mail where a person would write one."""
    address, name = rng.choice(ADDRESSES), rng.choice(NAMES)
    signoff = SIGNOFF_RE.search(text)
    if signoff and rng.random() < 0.5:
        line = str(rng.choice(INLINE_LINES)).format(address=address)
        return text[:signoff.start()].rstrip() + line + " " + text[signoff.start():].rstrip()
    if signoff:
        return text.rstrip() + str(rng.choice(AFTER_NAME)).format(address=address)
    return text.rstrip() + str(rng.choice(BLOCKS)).format(name=name, address=address)


def sign_llmail_benign(benign, rng):
    """Give half of the TRAIN benign mails a reply line or signature with one of the same
    addresses, so that an address is not an attack-only cue inside llmail."""
    train = np.flatnonzero((benign["split"] == "train").to_numpy())
    chosen = rng.choice(train, len(train) // 2, replace=False)
    texts = benign["text"].to_numpy(dtype=object)
    for i in chosen:
        texts[i] = with_address(texts[i], rng)
        benign.loc[i, "technique"] = "email_signed"
    benign["text"] = texts
    print(f"  llmail benign: {len(chosen)} of {len(train)} train mails got a signature or "
          "reply line with an address")
    return benign


def llmail_notes(attacks, benign):
    """Record how far the address, payload and formatting cues still separate the classes."""
    a = attacks.loc[attacks["split"] == "train", "text"]
    b = benign.loc[benign["split"] == "train", "text"]
    NOTES["llmail"] = {
        "attacks": len(a), "benign": len(b),
        "attacks_any_address": int(a.str.contains(EMAIL_RE).sum()),
        "benign_any_address": int(b.str.contains(EMAIL_RE).sum()),
        "attacks_fixed_address": int(a.str.contains(ADDRESS_RE).sum()),
        "attacks_confirmation": int(a.str.contains(PAYLOAD_RE).sum()),
        "attacks_newline": int(a.str.contains("\n").sum()),
        "benign_newline": int(b.str.contains("\n").sum()),
        "attacks_angle": int(a.str.contains("<", regex=False).sum()),
        "benign_angle": int(b.str.contains("<", regex=False).sum()),
        "benign_chars": (int(b.str.len().min()), int(b.str.len().max())),
        "attacks_chars": (int(a.str.len().min()), int(a.str.len().max())),
    }
    print("  llmail train cues:", NOTES["llmail"])


# --------------------------------------------------------------------------- gsum

def build_gsum(taken):
    parts = []
    for name, split in [("gsum_train.parquet", "train"), ("gsum_validation.parquet", "train"),
                        ("gsum_test.parquet", "test")]:
        texts = pd.read_parquet(raw(name))["text"].astype(str)
        parts.append(frame(texts, 1, "gsum", "summarization").assign(split=split))
    df = pd.concat(parts, ignore_index=True)
    return take(clean(df, "gsum", taken), taken)


# --------------------------------------------------------------------------- languages

# stop words and spelling cues per language; scores are counted, the best language wins
LANGUAGE_CUES = {
    "en": ("the you your and to of is are what was be this that with all for an in it as not do "
           "me my tell show reveal ignore mode enable activate unrestricted".split(), ""),
    "fr": ("le la les des tu ta tes vous votre et de est sont quel quelle que pour une un dans ne "
           "pas à ce ton mes moi qui du au l d j qu mode active révèle ignore".split(), "œêâ"),
    "de": ("der die das du dein deine deiner und zu ist sind was ein eine nicht mit für auf den "
           "dem ich alle mir mich deinen um dich aktiviere modus".split(), "ßüöä"),
    "es": ("el la los las tu tus y de es son qué que para una un en no con lo del al mis mi "
           "cuál cuáles dime revela ignora sigue sobre sin como ahora solo sus activa "
           "activar desarrollador".split(), "ñ¿¡"),
    "it": ("il la le gli i tu tuo tua tue tuoi e di è sono che per una un non con del della "
           "delle dei degli alla nel nella sul sulla ai al quale mi mie miei ti rivela ignora "
           "qual come solo ora questo questa modalità abilita attiva".split(), ""),
    "pt": ("o a os as seu sua seus suas e de é são qual que para uma um não com do da no na "
           "você te teu tua teus tuas me ao meu minha meus minhas sem como agora apenas ativar "
           "habilitar desenvolvedor modo".split(), "ãõç"),
    "ro": ("și sau este sunt care pentru un o cu nu la de ce tu tale tău în din pe ale îți "
           "ți mi".split(), "șțăî"),
}
SUFFIX_CUES = {"it": ["zione", "zioni", "mente", "ità"], "es": ["ción", "ciones"],
               "pt": ["ção", "ções"], "fr": ["tion", "ement"], "de": ["ung", "keit"]}


def detect_language(text):
    """Small stop-word and spelling detector for the yanis languages."""
    words = re.findall(r"\w+", text.lower())
    scores = {}
    for code, (stops, chars) in LANGUAGE_CUES.items():
        score = sum(w in stops for w in words) + 2 * sum(c in chars for c in text.lower())
        score += sum(w.endswith(s) for w in words for s in SUFFIX_CUES.get(code, []))
        scores[code] = score
    best = max(scores, key=scores.get)
    return best if scores[best] > 0 else ""


def language_of(text, given=""):
    """ISO code from a language column value, else from the script, else from the detector."""
    given = str(given).strip().lower()
    code = LANGUAGE_NAMES.get(given, given)
    if code in AYA_CODES.values():
        return code
    for lang, pattern in SCRIPTS:
        if len(pattern.findall(text)) >= 5:
            return lang
    return detect_language(text) or "en"


def pool_language_balance():
    """Rows per (language, label) in the existing training files."""
    counts = {}
    for name in EXISTING_TRAIN:
        df = pd.read_csv(DATA / name, keep_default_na=False)
        given = df["language"] if "language" in df.columns else [""] * len(df)
        for text, lang, label in zip(df["text"].astype(str), given, df["label"].astype(int)):
            key = (language_of(text, lang), label)
            counts[key] = counts.get(key, 0) + 1
    return counts


def validate_detector(aya):
    """Score detect_language against aya's language codes on a seeded sample of short prompts."""
    rng = np.random.default_rng(SEED)
    short = aya[(aya["text"].str.len() <= 150) & aya["language"].isin(YANIS_LANGUAGES)]
    accuracy = {}
    for lang, part in short.groupby("language"):
        part = sample(part.reset_index(drop=True), 100, rng)
        accuracy[lang] = round(float((part["text"].map(detect_language) == lang).mean()), 2)
    NOTES["detector"] = accuracy
    print("  yanis detector accuracy on 100 short aya prompts per language:", accuracy)


# --------------------------------------------------------------------------- yanis

def build_yanis(rng, taken):
    from src.features import embed

    texts = pd.read_csv(raw("yanis.csv"))["prompt_injections"].astype(str)
    df = frame(texts, 1, "yanis", "multilingual", language="")
    df = clean(df, "yanis", taken)
    df["language"] = df["text"].map(detect_language)
    print("  yanis: detected languages", df["language"].value_counts().to_dict())
    n = len(df)
    df = take(df[df["language"].isin(YANIS_LANGUAGES)].reset_index(drop=True), taken)
    print(f"  yanis: {n - len(df)} rows in languages without aya benign rows")

    vectors = embed(df["text"], cache_name="new_sources_yanis")
    n_groups, groups = connected_components(vectors @ vectors.T >= YANIS_GROUP_SIM, directed=False)
    sizes = np.bincount(groups)
    giant = sizes.argmax()
    df["split"] = np.where(groups == giant, "train", "test")
    NOTES["yanis"] = {"components": int(n_groups), "giant": int(sizes[giant]),
                      "test_rows": int(len(df) - sizes[giant]), "test_components": int(n_groups - 1),
                      "test_languages": df.loc[df["split"] == "test", "language"].value_counts().to_dict()}
    print(f"  yanis: {n_groups} components at embedding cosine >= {YANIS_GROUP_SIM}; the largest "
          f"({sizes[giant]} rows) is training, the other {len(df) - sizes[giant]} rows are test")
    yanis_separation(df, vectors)
    print("  yanis: detector check on 12 random train rows")
    for row in df[df["split"] == "train"].sample(12, random_state=SEED).itertuples():
        print(f"    {row.language}  {row.text[:80]!r}")
    return df


def yanis_separation(df, vectors):
    """Measure how close test rows are to training rows (all and other-language)."""
    train = (df["split"] == "train").to_numpy()
    language = df["language"].to_numpy()
    similarity = vectors[~train] @ vectors[train].T
    other = language[~train][:, None] != language[train][None, :]
    within = vectors[train] @ vectors[train].T
    np.fill_diagonal(within, -1)
    nearest = similarity.max(axis=1)
    nearest_other = np.where(other, similarity, -1).max(axis=1)
    NOTES["yanis"].update({
        "test_nearest_median": round(float(np.median(nearest)), 2),
        "test_nearest_max": round(float(nearest.max()), 3),
        "test_other_median": round(float(np.median(nearest_other)), 2),
        "test_other_max": round(float(nearest_other.max()), 3),
        "train_nearest_median": round(float(np.median(within.max(axis=1))), 2),
    })
    print("  yanis: test row -> nearest train row cosine median "
          f"{NOTES['yanis']['test_nearest_median']}, max {NOTES['yanis']['test_nearest_max']}; "
          f"other-language train row median {NOTES['yanis']['test_other_median']}, max "
          f"{NOTES['yanis']['test_other_max']}; train row -> nearest other train row median "
          f"{NOTES['yanis']['train_nearest_median']}")


# --------------------------------------------------------------------------- aya, dolly

def aya_targets(yanis, balance):
    """Benign rows per language: as many as yanis has attacks in that language; for the other
    aya languages only what the existing training files lack to reach one benign per attack."""
    wanted = yanis["language"].value_counts().to_dict()
    for code in AYA_CODES.values():
        if code not in wanted:
            wanted[code] = max(balance.get((code, 1), 0) - balance.get((code, 0), 0), 0)
    return {code: int(n) for code, n in sorted(wanted.items())}


def build_aya(rng, taken, yanis, balance):
    aya = pd.read_parquet(raw("aya_train.parquet"), columns=["inputs", "language_code"])
    aya = aya[aya["language_code"].isin(AYA_CODES)]
    df = frame(aya["inputs"].astype(str), 0, "aya", "prompt", language="")
    df["language"] = aya["language_code"].map(AYA_CODES).to_numpy()
    df = clean(df, "aya", taken)
    validate_detector(df)
    wanted = aya_targets(yanis, balance)
    NOTES["aya_wanted"] = wanted
    print("  aya: benign rows wanted per language", wanted)
    parts = [sample(part.reset_index(drop=True), wanted[lang], rng)
             for lang, part in df.groupby("language") if wanted.get(lang, 0) > 0]
    df = take(pd.concat(parts, ignore_index=True), taken)
    print("  aya: rows per language", df["language"].value_counts().sort_index().to_dict())
    return split_by_group(df, near_copy_groups(df["text"], "aya"))


def build_dolly(rng, taken):
    rows = [json.loads(line) for line in raw("dolly.jsonl").read_text().splitlines() if line]
    df = pd.DataFrame(rows)
    has_context = df["context"].str.strip() != ""
    text = np.where(has_context, df["instruction"] + "\n\n" + df["context"], df["instruction"])
    df = frame(text, 0, "dolly", df["category"].to_numpy())
    df["with_context"] = has_context.to_numpy()
    df = clean(df, "dolly", taken)
    parts = [sample(part.reset_index(drop=True), 500, rng)
             for _, part in df.groupby("with_context")]
    df = take(pd.concat(parts, ignore_index=True).drop(columns="with_context"), taken)
    return split_by_group(df, near_copy_groups(df["text"], "dolly"))


# --------------------------------------------------------------------------- output

def build(balance):
    rng = np.random.default_rng(SEED)
    taken = known_keys()
    print(f"keys already in training and held-out files: {len(taken)}")
    parts = {}
    for name, builder in [("wild", build_wild), ("llmail", build_llmail),
                          ("gsum", lambda r, t: build_gsum(t)), ("yanis", build_yanis),
                          ("aya", lambda r, t: build_aya(r, t, parts["yanis"], balance)),
                          ("dolly", build_dolly)]:
        print(f"{name}:")
        parts[name] = builder(rng, taken).assign(source=name)
    df = pd.concat(parts.values(), ignore_index=True)
    df["label"] = df["label"].astype(int)
    return df[COLUMNS + ["split"]]


def language_balance(df, balance):
    """Benign and injection rows per language in the training pool (existing files + new_train)."""
    existing = pd.Series(balance).unstack(fill_value=0)
    new = df[df["split"] == "train"].groupby(["language", "label"]).size().unstack(fill_value=0)
    table = existing.add(new, fill_value=0).astype(int)
    table = table.rename(columns={0: "benign", 1: "injection"}).sort_index()
    table["new benign"] = new.get(0, 0)
    table["new injection"] = new.get(1, 0)
    table = table.fillna(0).astype(int)
    NOTES["balance"] = table
    return table


def summarize(df, balance):
    print("\nrows per source, split and label:")
    counts = df.groupby(["source", "split", "label"]).size().unstack("label", fill_value=0)
    counts = counts.rename(columns={0: "benign", 1: "injection"})
    print(counts.to_string())
    print("\ntotal:", df.groupby(["split", "label"]).size().to_dict())
    print("\ntext length quartiles per source (characters):")
    lengths = df.assign(chars=df["text"].str.len()).groupby("source")["chars"]
    print(lengths.quantile([0.25, 0.5, 0.75]).unstack().rename(
        columns={0.25: "q1", 0.5: "median", 0.75: "q3"}).astype(int).to_string())
    print("\nrows per language:", df["language"].value_counts().to_dict())
    print("\ntraining pool per language (existing files + new_train):")
    print(language_balance(df, balance).to_string())
    return counts


SOURCE_INFO = [
    ("wild", "TrustAIRLab/in-the-wild-jailbreak-prompts", "MIT",
     "400 of 1,405 jailbreak prompts (jailbreak_2023_12_25) and 600 of 13,735 regular "
     "prompts (regular_2023_12_25), seeded sample after filtering; regular prompts with "
     "override or jailbreak cues or near-copies of a jailbreak were dropped first"),
    ("llmail", "microsoft/llmail-inject-challenge", "MIT",
     "400 phase-1 submissions labelled attack_attempt = True, reason = api_triggered, "
     "plus all benign mails from emails_for_fp_tests.json (203, 160 after removing duplicates); "
     "in the training part half of the attack targets were varied and half of the benign mails "
     "got a signature with an address"),
    ("gsum", "Lakera/gandalf_summarization", "MIT",
     "all rows, all attacks; the official train + validation rows are training, "
     "the official test rows are test"),
    ("yanis", "yanismiraoui/prompt_injections", "Apache 2.0",
     "all rows (attacks) in English, French, German, Spanish, Italian and Portuguese; "
     "Romanian dropped because aya has no Romanian"),
    ("aya", "CohereLabs/aya_dataset", "Apache 2.0",
     "benign prompts (column inputs); per language as many rows as yanis has attacks in that "
     "language; the other aya languages only where the training pool has more attacks than "
     "benign rows (see the language table)"),
    ("dolly", "databricks/databricks-dolly-15k", "CC BY-SA 3.0",
     "1,000 benign rows: 500 instructions with their context passage "
     "(instruction, blank line, context) and 500 without"),
]


def write_sources_md(counts):
    llmail, yanis, detector = NOTES["llmail"], NOTES["yanis"], NOTES["detector"]
    lines = [
        "# New public sources (round four)",
        "",
        "Written by `scripts/download_new_sources.py`. Output: `data/new_train.csv` and "
        "`data/new_test.csv` (columns `text,label,category,technique,language,source`; "
        "label 1 = injection, 0 = benign). Every number below is measured by the script.",
        "",
        "| Source | URL | Licence | What was taken | Train benign | Train injection | "
        "Test benign | Test injection |",
        "|---|---|---|---|---|---|---|---|",
    ]
    for name, repo, licence, taken in SOURCE_INFO:
        cells = [int(counts.loc[(name, split), label]) if (name, split) in counts.index else 0
                 for split in ["train", "test"] for label in ["benign", "injection"]]
        lines.append(f"| {name} | https://huggingface.co/datasets/{repo} | {licence} | {taken} | "
                     + " | ".join(str(c) for c in cells) + " |")
    lines += [
        "",
        "## How the rows were chosen",
        "",
        f"- Sampling is seeded (`SEED = {SEED}`) and every split decision comes from a sha1 hash "
        "of the text or of a group's smallest text hash, so re-running the script gives the "
        "same files.",
        f"- Rows were dropped when empty, longer than {MAX_CHARS:,} characters, duplicated inside "
        "the source, or when their normalized key (`src.dataset.dedup_key`) already occurred in "
        "`injection_train.csv`, `extra_train.csv`, `contrast_train.csv`, the held-out files "
        "(`injection_test.csv`, `extra_test.csv`, `handwritten_test.csv`, `handwritten_dev*.csv`, "
        "`handwritten_test4.csv`, `probe_dev.csv`) or in rows already taken from an earlier "
        "source. Many in-the-wild jailbreaks duplicate jackhhao rows; the run prints how many "
        "rows each filter removed.",
        f"- wild: the regular (benign) prompts of the source include many that this project "
        "labels as injections elsewhere (\"Ignore all previous instructions. From now on you "
        f"...\"). {NOTES['wild_cued']:,} of {NOTES['wild_regular']:,} regular candidates carry "
        "override, role-reassignment or jailbreak cues (a regex copy of the project's "
        "`override_phrase_count` / `role_reassignment_score` patterns plus DAN, jailbreak, "
        "developer mode, \"without any restrictions\", \"free from ... rules\") and were dropped "
        f"before sampling, and {NOTES['wild_cued_foreign']} more carry a non-English override "
        "cue (the detector's `multilingual_override_count` rule fires on them); "
        f"{NOTES['wild_copies']} sampled regular prompts were near-copies "
        f"(TF-IDF cosine >= {GROUP_SIM}) of a jailbreak prompt and were dropped too. They were "
        "not relabelled, they are simply on neither side.",
        "- gandalf_summarization keeps its official split. wild, llmail, aya and dolly rows "
        "(attack and benign alike) are grouped by TF-IDF character n-gram cosine similarity "
        f">= {GROUP_SIM} (connected components) and a whole group goes to one side (80/20 by "
        "the group's smallest sha1), so no near-copy sits on both sides of a source's split. "
        "`src.dataset.load_pool` measures near-copies against all held-out sets with its own "
        "TF-IDF weights, and still removes these training rows per source: "
        f"`{NOTES['leaks']}` (the wild rows are near-copies of jackhhao test prompts).",
        f"- yanis: rows are joined at multilingual embedding cosine >= {YANIS_GROUP_SIM}. This "
        f"gives {yanis['components']} components; the giant one ({yanis['giant']} rows) is "
        f"training, the remaining {yanis['test_components']} small components "
        f"({yanis['test_rows']} rows) are test. See the yanis section below.",
        "- `language` holds an ISO 639-1 code: aya from its `language_code`, yanis from a small "
        "stop-word detector, the English-only sources `en`. The detector, scored against aya's "
        "language codes on 100 seeded prompts of at most 150 characters per language, is "
        + ", ".join(f"{lang} {acc:.0%}" for lang, acc in detector.items())
        + " correct (English errors are mostly undetected rather than mislabelled). `language` "
        "is metadata only; it decided which yanis rows were dropped as Romanian or undetected.",
        "",
        "## Language balance of the training pool",
        "",
        "Language is a possible class shortcut in a multilingual embedding, so aya benign rows "
        "are not spread evenly: each yanis language gets as many aya rows as yanis has attacks "
        "in it, and the other aya languages (nl, ru, tr, hi, ja, zh, ar) get rows only when "
        "the existing training files hold more attacks than benign rows in that language. "
        "Counts below are the training pool after this script (existing files by their "
        "language column, script or the detector, plus `new_train.csv`); "
        f"aya rows wanted per language: `{NOTES['aya_wanted']}`.",
        "",
        "| Language | Benign | Injection | of which new benign | of which new injection |",
        "|---|---|---|---|---|",
    ]
    for lang, row in NOTES["balance"].iterrows():
        lines.append(f"| {lang or '(none)'} | {row['benign']} | {row['injection']} | "
                     f"{row['new benign']} | {row['new injection']} |")
    lines += [
        "",
        "## llmail target address: literal diversified, address presence remains a cue",
        "",
        "Nearly every llmail attack mail in the challenge tells the assistant to mail a fixed "
        "target (`contact@contact.com`; about a fifth use `contact@domain.com`, "
        "`contact_me@contact.com`, `contact@domin.com`, `contact@contact,com` or a spelled-out "
        "`contact <at> contact <dot> com`) with the body `confirmation`, and no benign mail in "
        "the challenge contains an address. In the **training part only**, seeded and with test "
        "rows untouched: half of the attack mails had every spelling of the fixed target "
        "replaced with one of 12 realistic addresses and the payload word replaced "
        "(`technique = api_triggered_varied`), and half of the benign mails got a reply-to "
        "line before their sign-off, an address after the signed name, or a signature block, "
        "drawn from the **same** 12 addresses (`technique = email_signed`), so no address is "
        "attack-only.",
        "",
        "What remains, measured on the llmail training rows: "
        f"{llmail['attacks_any_address']} of {llmail['attacks']} attack mails and "
        f"{llmail['benign_any_address']} of {llmail['benign']} benign mails contain an e-mail "
        f"address; {llmail['attacks_fixed_address']} attack mails still carry a fixed challenge "
        f"target and {llmail['attacks_confirmation']} still carry the word `confirmation` "
        "(0 benign mails do). Formatting still separates the classes: "
        f"{llmail['attacks_newline']} of {llmail['attacks']} attack mails contain a line break "
        f"against {llmail['benign_newline']} of {llmail['benign']} benign mails, "
        f"{llmail['attacks_angle']} attack mails contain `<` against {llmail['benign_angle']} "
        f"benign mails, and benign mails are {llmail['benign_chars'][0]}-"
        f"{llmail['benign_chars'][1]} characters long against {llmail['attacks_chars'][0]}-"
        f"{llmail['attacks_chars'][1]} for attacks. A model can still learn "
        "\"asks to send a mail to some address => attack\" from llmail; the contrast set's "
        "correspondence pairs are what counters that.",
        "",
        "## llmail benign mails are templates",
        "",
        "The challenge's benign mails (`emails_for_fp_tests.json`) are short single-line "
        "templates from a few families (meeting notes, invoices, newsletters): 160 after "
        f"de-duplication, in {NOTES['groups llmail benign']} near-copy groups at cosine "
        f"{GROUP_SIM}. The llmail precision figure "
        "in `new_test.csv` therefore reflects template mails only, and it is a small set "
        f"({int(counts.loc[('llmail', 'test'), 'benign'])} mails). Realistic benign "
        "correspondence lives in the contrast set and the hand-written sets.",
        "",
        "## yanis test rows",
        "",
        "The source is one set of attack sentences translated and paraphrased across "
        "languages. Average-linkage clustering did not separate translations (round-four "
        "review: translations of one sentence sat on both sides at cosine 0.75-0.8), so the "
        f"split now uses connected components at embedding cosine >= {YANIS_GROUP_SIM}. Most rows "
        f"({yanis['giant']} of {yanis['giant'] + yanis['test_rows']}) form one giant component, "
        "which is training; the test side is the rows outside it, so by construction every "
        f"test row is below cosine {YANIS_GROUP_SIM} to every training row. Measured: test row "
        f"to nearest training row median {yanis['test_nearest_median']}, max "
        f"{yanis['test_nearest_max']} (nearest other-language training row median "
        f"{yanis['test_other_median']}, max {yanis['test_other_max']}), while a training row's "
        f"nearest other training row has median {yanis['train_nearest_median']}. The yanis test "
        "score therefore checks attacks that are unlike the training sentences, not "
        "translation or paraphrase memorization; it is a small and hard set, and mostly "
        f"English because translations join the giant component (test languages: "
        f"`{yanis['test_languages']}`).",
        "",
        "## Attribution",
        "",
        "The `dolly` rows come from **databricks-dolly-15k** (Databricks, Inc., 2023), "
        "https://huggingface.co/datasets/databricks/databricks-dolly-15k, licensed under "
        "**CC BY-SA 3.0** (https://creativecommons.org/licenses/by-sa/3.0/). Rows were selected "
        "and the instruction and context fields were joined with a blank line; no other changes "
        "were made. Under the share-alike condition, any redistribution of these rows or of a "
        "dataset derived from them must carry the same CC BY-SA 3.0 licence and this attribution.",
        "",
        "The other sources are MIT or Apache 2.0 licensed; their licence notices are on the "
        "linked dataset pages.",
        "",
    ]
    (DATA / "SOURCES.md").write_text("\n".join(lines))
    print("wrote data/SOURCES.md")


def leak_check(df):
    """Count the new_train rows that the project's own leak check (src.dataset.load_pool,
    near-copy of any held-out row) would still remove; only counts, never rows."""
    from src.dataset import load_pool

    written = df[df["split"] == "train"].groupby("source").size()
    kept = load_pool().groupby("source").size().reindex(written.index, fill_value=0)
    NOTES["leaks"] = (written - kept).astype(int).to_dict()
    print("\nnew_train rows that src.dataset.load_pool still removes as near-copies of a "
          "held-out row:", NOTES["leaks"])


def main():
    balance = pool_language_balance()
    df = build(balance)
    for split, name in [("train", "new_train.csv"), ("test", "new_test.csv")]:
        part = df.loc[df["split"] == split, COLUMNS].reset_index(drop=True)
        part.to_csv(DATA / name, index=False)
        print(f"wrote {name}: {len(part)} rows")
    counts = summarize(df, balance)
    leak_check(df)
    write_sources_md(counts)


if __name__ == "__main__":
    main()
