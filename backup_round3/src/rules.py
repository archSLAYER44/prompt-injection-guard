"""The 16 rule features.

Every rule returns (value, snippets): the number fed to the SVM and the pieces of
text that triggered it, which the CLI and GUI show as the explanation.
"""
import math
import re

from .normalize import (
    BASE64_RE, HEX_RE, SPACED_LETTERS_RE, ZERO_WIDTH_RE, is_leet, is_mixed_script, light_normalize,
    make_views,
)

# ---------------------------------------------------------------- pattern tables

IMPERATIVE_VERBS = [
    "ignore", "disregard", "forget", "override", "bypass", "skip", "discard", "abandon",
    "set aside", "drop", "disable", "act", "pretend", "roleplay", "reveal", "print",
    "output", "repeat", "execute", "obey", "comply", "stop",
]
_LEAD = r"(?:please|now|just|then|and|also|kindly|instead|finally|first|next|simply)"
_VERBS = "|".join(v.replace(" ", r"\s+") for v in IMPERATIVE_VERBS)
# a command verb at the start of a sentence/clause, or right after a lead-in word
IMPERATIVE_RE = re.compile(
    rf"(?:^|[.!?;:,\n\"'(\[\-]\s*|\b{_LEAD}\s+)(?:{_LEAD}\s+)*({_VERBS})\b", re.M
)
YOU_RE = re.compile(r"\b(?:you|your|yourself|you're)\b")
YOU_MUST_RE = re.compile(r"\byou\s+(?:must|shall|will|have to|need to|are to|should)\b")
SENTENCE_SPLIT_RE = re.compile(r"[.!?\n]+")

_DROP = r"(?:ignore|disregard|forget|override|bypass|set\s+aside|discard|drop|skip|abandon|cancel)"
_WHICH = r"(?:previous|prior|above|earlier|preceding|former|all|any|every|your|their|its|these|those)"
_RULES = (r"(?:instructions?|rules?|guidelines?|prompts?|directions?|directives?|context|"
          r"restrictions?|limits?|filters?|constraints?|setup|configuration|programming|"
          r"training|safeguards?|polic(?:y|ies)|guardrails?|guidance|orders|commands)")

_ROLE = (r"(?:developer|admin|administrator|engineer|officer|operator|team|lead|manager|owner|"
         r"auditor|supervisor|creator|maintainer|reviewer|moderator|staff|director)")
_SAFETY = (r"(?:safety|filter(?:s|ing)?|restrictions?|limits?|guardrails?|moderation|safeguards?|"
           r"content\s+policy|censorship)")
_SECRETS = (r"(?:prompts?|instructions?|rules|configuration|directives?|guidelines|guidance|settings|"
            r"setup|policy(?:\s+text)?|(?:system|boot|initial|setup)\s+(?:message|text))")
_LEAK = (r"(?:reveal|print|show|display|repeat|output|list|share|leak|expose|return|disclose|dump|"
         r"recite|echo|paste|quote|provide|copy|write\s+out|tell\s+me|give\s+me|send)")

RULE_PATTERNS = {
    "override_phrase_count": [
        rf"\b(?:turn\s+off|switch\s+off|disable|deactivate|remove|lift|suspend)\b[^.!?\n]{{0,30}}?\b{_SAFETY}\b",
        rf"\b{_DROP}\s+(?:the\s+|your\s+)?(?:assistant\s+role|task|system\s+message|what\s+you\s+were\s+told)\b",
        rf"\b{_DROP}\b[^.!?\n]{{0,40}}?\b{_WHICH}\b[^.!?\n]{{0,30}}?\b{_RULES}\b",
        rf"\b{_DROP}\s+(?:everything|anything|all)\s+(?:above|before|prior|so far|you\s+(?:were|have been)\s+told)",
        rf"\b{_WHICH}\s+{_RULES}\s+(?:are|is)\s+(?:void|cancelled|canceled|revoked|no longer|obsolete|suspended)",
        r"\b(?:your|these|following|follow\s+(?:the|my))\s+new\s+(?:instructions?|rules|directives?|orders|task)\b",
        r"\bnew\s+(?:instructions?|rules|directives?|orders|task)\s*:",
        r"\byou\s+must\s+now\b",
        r"\binstead,?\s+(?:do|you\s+(?:will|must|should))\b",
        r"\bfrom\s+(?:this\s+point|now)\s+on,?\s+you\b",
    ],
    "role_reassignment_score": [
        r"\byou\s+are\s+now\b",
        r"\bact\s+as\b",
        r"\bpretend\s+(?:to\s+be|you\s+are|that\s+you)\b",
        r"\bfrom\s+now\s+on,?\s+you\b",
        r"\brole-?play\s+as\b",
        r"\bsimulate\s+(?:an?|being)\b",
        r"\byou(?:'re|\s+are)\s+no\s+longer\b",
        r"\byour\s+new\s+(?:role|persona|identity|name)\b",
        r"\b(?:switch|change|enter|go)\s+(?:to|into)\s+\w+(?:\s+\w+)?\s+mode\b",
        r"\b(?:developer|dev|god|unrestricted|jailbreak)\s+mode\b",
        r"\bjailbr(?:eak|oken)\b",
        r"\bdo\s+anything\s+now\b",
    ],
    "delimiter_mimicry_count": [
        r"<\|[a-z_]+\|>",
        r"\[/?inst\]",
        r"<</?\w+>>",
        r"</s>",
        r"^\s*(?:system|assistant|developer)\s*:",
        r"#{2,}\s*(?:instructions?|system|override|new\s+task|admin)",
        r"\[(?:system|admin|developer|override|instructions?)[^\]\n]{0,30}\]",
        r"</?(?:system|admin|instructions?|prompt|developer|override|directive)>",
        r"```\s*(?:system|prompt|instructions?)",
        r"\b(?:begin|end)\s+(?:of\s+)?(?:system|instructions?|prompt)\b",
        r"-{3,}\s*(?:instructions?|system)",
        r"(?:/\*|<!--|//)[^\n]{0,40}\b(?:model|assistant|ai|llm)\b",
    ],
    "authority_claim_count": [
        rf"\bas\s+(?:your|the)\s+(?:[\w-]+\s+){{0,3}}?{_ROLE}\b",
        rf"\b(?:i\s+am|i'm|this\s+is|speaking\s+as|on\s+behalf\s+of)\s+(?:the\s+|your\s+|a\s+|an\s+)?"
        rf"(?:[\w-]+\s+){{0,3}}?{_ROLE}\b",
        rf"\b{_ROLE}\b(?:\s+[\w-]+){{0,4}}\s+here\b",
        r"\bfrom\s+(?:openai|anthropic|google|microsoft|meta|the\s+\w+\s+team)\b",
        r"\bi\s+authori[sz]e\s+you\b",
        r"\bauthori[sz]ed\s+(?:override|access|user|personnel|request)\b",
        r"\b(?:admin|administrator|maintenance|debug|root|sudo)\s+(?:mode|access|override|privileges?)\b",
        r"\bpriority\s*:?\s*(?:critical|high|urgent)\b",
        r"\bofficial\s+(?:instruction|request|notice|order)\b",
        r"\b(?:security|compliance|safety)\s+(?:audit|check|review|clearance)\b",
    ],
    "indirect_address_count": [
        r"\b(?:ai|assistants?|models?|llms?|chatbots?|agents?|language\s+models?)\s+(?:reading|processing|summari[sz]ing|parsing|that\s+reads?)\b",
        r"\b(?:note|instructions?|message)\s+(?:to|for)\s+(?:the\s+|any\s+)?(?:ai|assistant|model|llm|chatbot|language\s+model)s?\b",
        r"\bwhen\s+(?:the|an?)\s+(?:ai|assistant|model|llm|chatbot)(?:\s+\w+)?\s+(?:reads?|sees?|process(?:es)?)\b",
        r"\bif\s+you\s+are\s+an?\s+(?:ai|llm|language\s+model|assistant|chatbot)\b",
        r"\bwhen\s+(?:you\s+)?(?:summari[sz]|process|read|translat|analy[sz])\w*\s+this\b",
        r"\bhidden\s+instructions?\b",
        r"\b(?:attention|dear|hey|hello|hi),?\s+(?:ai|assistant|model|chatbot|llm)\b",
    ],
    "exfiltration_count": [
        rf"\b{_LEAK}\b[^.!?\n]{{0,30}}?\b(?:your|hidden|internal|initial|system|secret|original|"
        rf"confidential|operating)\b[^.!?\n]{{0,30}}?\b{_SECRETS}",
        rf"\b{_LEAK}\b[^.!?\n]{{0,40}}?\b(?:{_SECRETS}|text|wording)\b[^.!?\n]{{0,30}}?"
        rf"\b(?:you\s+were\s+given|loaded\s+before|written\s+above|above\s+this|before\s+this\s+(?:conversation|chat))",
        r"\b(?:instructions?|rules|text|lines?|prompt|message)\s+(?:that\s+)?(?:sit\s+)?above\s+this\b",
        r"\b(?:lines?|text|words|message)\s+that\s+(?:configure|define|govern|control)s?\s+(?:you|your)\b",
        r"\b(?:rules|instructions?|guidelines)\s+you\s+(?:follow|were\s+given|operate\s+under)\b",
        rf"\b{_LEAK}\b[^.!?\n]{{0,30}}?\b(?:system|boot|initial|setup|hidden|secret)\s+"
        rf"(?:prompt|message|text|instructions?)\b",
        rf"\b{_LEAK}\b[^.!?\n]{{0,30}}?\b(?:prompt|instructions?|rules)\s+above\b",
        rf"\b{_LEAK}\b[^.!?\n]{{0,40}}?\b(?:passwords?|credentials|(?:api|secret|access|private)\s+"
        rf"(?:key|token)s?)\b",
        r"\b(?:send|forward|email|post|upload)\b[^.!?\n]{0,60}?\bto\s+(?:https?://|\S+@\S+)",
        r"!?\[[^\]\n]*\]\(https?://[^)\s]*\?[^)\s]*\)",
    ],
    "output_manipulation_count": [
        r"\b(?:respond|reply|answer)\s+(?:only\s+)?with\b",
        r"\b(?:respond|reply|answer)\s+only\b",
        r"\b(?:do\s+not|don't|never)\s+(?:mention|tell|reveal|disclose|warn|refuse|say|inform)\b",
        r"\bsay\s+(?:that\s+)?you\s+are\b",
        r"\b(?:begin|start|end|finish)\s+(?:your|every|each)\s+(?:response|reply|answer|message)s?\s+with\b",
        r"\bwithout\s+(?:any\s+)?(?:warnings?|disclaimers?|caveats?)\b",
        r"\bno\s+(?:warnings|disclaimers|caveats)\b",
        r"\bconfirm\s+with\s+the\s+word\b",
        r"\bthe\s+word\s+[\"']?[a-z]+[\"']?\s*(?:\.|$)",
    ],
    "hypothetical_framing_count": [
        r"\bhypothetical(?:ly)?\b",
        r"\bfor\s+(?:a|my)\s+(?:story|novel|screenplay|game)\b",
        r"\bimagine\s+(?:you|that\s+you)\b",
        r"\b(?:in\s+a\s+)?fictional\s+(?:world|mode|scenario|universe|setting)\b",
        r"\bfor\s+(?:educational|research|testing)\s+purposes\b",
        r"\b(?:no|without|zero)\s+(?:(?:any|the|your|usual|normal|content)\s+){0,2}"
        r"(?:restrictions|limits|filters|rules|boundaries|censorship|policy|caveats)\b",
        r"\bstay\s+in\s+character\b",
        r"\b(?:unrestricted|unfiltered|uncensored)\b",
        r"\bsafety\s+(?:layer|filter|mode|check)s?\s+(?:off|disabled)\b",
    ],
    "urgency_pressure_count": [
        r"\bimmediately\b", r"\burgent(?:ly)?\b", r"\byou\s+must\b", r"\bfailure\s+to\s+comply\b",
        r"\bor\s+else\b", r"\bthis\s+is\s+(?:critical|an\s+emergency|mandatory)\b", r"\bmandatory\b",
        r"\bright\s+now\b", r"\bat\s+once\b", r"\bno\s+exceptions\b",
    ],
    "payload_split_count": [
        r"\b(?:combine|concatenate|join|merge|assemble|stitch|put\s+together|glue)\b",
        r"\bpart\s*(?:1|one|a)\b[\s\S]{0,200}?\bpart\s*(?:2|two|b)\b",
        r"\b\w+\s*=\s*[\"'][^\"'\n]{1,80}[\"']",
        r"\blet\s+\w+\s+(?:be|=)\s",
        r"\bfirst\s+(?:letter|character|word)s?\s+of\s+each\b",
        r"\bthen\s+(?:follow|execute|run|obey|do)\s+(?:the\s+)?(?:result|output|combined|it)\b",
    ],
}
RULE_PATTERNS = {
    name: [re.compile(p, re.M) for p in patterns] for name, patterns in RULE_PATTERNS.items()
}

OBFUSCATION_HINT_RE = re.compile(
    r"\b(?:base64|rot-?13|decode|decipher|decrypt|unscramble|backwards|reversed?|leet(?:speak)?|"
    r"hex(?:adecimal)?)\b"
)

# keyword rules whose extra hits after de-obfuscation count as deliberate hiding
HIDDEN_HIT_RULES = [
    "override_phrase_count", "role_reassignment_score", "authority_claim_count",
    "exfiltration_count", "output_manipulation_count",
]

# ------------------------------------------------------------------- helpers


def _snip(text, limit=60):
    text = " ".join(text.split())
    return text if len(text) <= limit else text[:limit - 3] + "..."


def _count(name, text):
    snippets = [_snip(m.group(0)) for p in RULE_PATTERNS[name] for m in p.finditer(text)]
    return len(snippets), snippets


def _pattern_rule(name, view="norm"):
    def rule(views):
        return _count(name, getattr(views, view))
    return rule


# --------------------------------------------------------------------- rules


def imperative_verb_density(views):
    words = re.findall(r"\w+", views.norm)
    verbs = [m.group(1) for m in IMPERATIVE_RE.finditer(views.norm)]
    return (len(verbs) / len(words) if words else 0.0), verbs


def log_text_length(views):
    return math.log1p(len(views.raw)), []


def special_char_ratio(views):
    raw = views.raw
    return (sum(not c.isalnum() for c in raw) / len(raw) if raw else 0.0), []


def second_person_command_ratio(views):
    sentences = [s.strip() for s in SENTENCE_SPLIT_RE.split(views.norm) if s.strip()]
    hits = [
        _snip(s) for s in sentences
        if YOU_RE.search(s) and (IMPERATIVE_RE.search(s) or YOU_MUST_RE.search(s))
    ]
    return (len(hits) / len(sentences) if sentences else 0.0), hits


def obfuscation_score(views):
    raw = views.raw
    snippets = []

    zero_width = len(ZERO_WIDTH_RE.findall(raw))
    if zero_width:
        snippets.append(f"{zero_width} zero-width chars")

    tokens = raw.split()
    leet = [t for t in tokens if is_leet(t)]
    mixed = [t for t in tokens if is_mixed_script(t.lower())]
    encoded = [m.group(0) for m in BASE64_RE.finditer(raw)] + [m.group(0) for m in HEX_RE.finditer(raw)]
    spaced = [m.group(0) for m in SPACED_LETTERS_RE.finditer(light_normalize(raw))]
    hints = [m.group(0) for m in OBFUSCATION_HINT_RE.finditer(views.light)]
    snippets += [_snip(s) for s in leet + mixed + encoded + spaced + hints]

    hidden = 0
    for name in HIDDEN_HIT_RULES:
        hidden += max(0, _count(name, views.norm)[0] - _count(name, views.light)[0])
    if hidden:
        snippets.append(f"{hidden} rule hits only after de-obfuscation")

    score = zero_width + len(leet) + len(mixed) + len(encoded) + len(spaced) + len(hints) + hidden
    return score, snippets


def uppercase_ratio(views):
    letters = [c for c in views.raw if c.isalpha()]
    return (sum(c.isupper() for c in letters) / len(letters) if letters else 0.0), []


def role_reassignment_score(views):
    count, snippets = _count("role_reassignment_score", views.norm)
    if re.search(r"\bDAN\b", views.raw):
        count, snippets = count + 1, snippets + ["DAN"]
    return count, snippets


RULES = {
    "imperative_verb_density": imperative_verb_density,
    "override_phrase_count": _pattern_rule("override_phrase_count"),
    "role_reassignment_score": role_reassignment_score,
    "delimiter_mimicry_count": _pattern_rule("delimiter_mimicry_count", view="light"),
    "log_text_length": log_text_length,
    "special_char_ratio": special_char_ratio,
    "authority_claim_count": _pattern_rule("authority_claim_count"),
    "indirect_address_count": _pattern_rule("indirect_address_count"),
    "exfiltration_count": _pattern_rule("exfiltration_count"),
    "output_manipulation_count": _pattern_rule("output_manipulation_count"),
    "hypothetical_framing_count": _pattern_rule("hypothetical_framing_count"),
    "urgency_pressure_count": _pattern_rule("urgency_pressure_count"),
    "second_person_command_ratio": second_person_command_ratio,
    "obfuscation_score": obfuscation_score,
    "payload_split_count": _pattern_rule("payload_split_count"),
    "uppercase_ratio": uppercase_ratio,
}
RULE_NAMES = list(RULES)

# always non-zero, so they describe the text rather than "fire"
DESCRIPTIVE_RULES = {"log_text_length", "special_char_ratio", "uppercase_ratio"}


def analyze(text):
    """All 16 rules for one text: {name: (value, snippets)}."""
    views = make_views(text)
    return {name: rule(views) for name, rule in RULES.items()}


def rule_vector(text):
    return [float(value) for value, _ in analyze(text).values()]


def fired(analysis):
    """Rules that triggered, for the CLI/GUI explanation."""
    return {
        name: (value, snippets) for name, (value, snippets) in analysis.items()
        if name not in DESCRIPTIVE_RULES and value > 0
    }


# ------------------------------------------- original 6 features (ablation only)

LEGACY_NAMES = [
    "imperative_verb_density", "override_phrase_count", "role_reassignment_flag",
    "delimiter_mimicry_count", "text_length", "special_char_ratio",
]
_LEGACY_VERBS = {"ignore", "disregard", "act", "pretend", "override", "forget"}
_LEGACY_OVERRIDES = ["ignore previous", "disregard the above", "new instructions",
                     "forget everything", "you must now"]
_LEGACY_ROLES = ["you are now", "act as", "pretend to be", "from now on you"]
_LEGACY_DELIMITERS = [r"###", r"\[system\]", r"<<.*?>>", r"---instruction---"]


def legacy_vector(text):
    """The 6 features exactly as the first project spec defined them."""
    lower = text.lower()
    words = re.findall(r"\w+", lower)
    return [
        sum(w in _LEGACY_VERBS for w in words) / len(words) if words else 0.0,
        float(sum(lower.count(p) for p in _LEGACY_OVERRIDES)),
        float(any(p in lower for p in _LEGACY_ROLES)),
        float(sum(len(re.findall(p, lower)) for p in _LEGACY_DELIMITERS)),
        float(len(text)),
        sum(not c.isalnum() for c in text) / len(text) if text else 0.0,
    ]
