"""The 20 rule features.

Every rule returns (value, snippets): the number fed to the SVM and the pieces of
text that triggered it, which the CLI and GUI show as the explanation.
"""
import math
import re

from .normalize import (
    SPACED_LETTERS_RE, ZERO_WIDTH_RE, decoded_runs, is_leet, is_mixed_script, light_normalize, make_views,
    printable_text,
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
    # base64/hex runs that hide text or code: a hash, a URL path or a long word does not count
    encoded = decoded_runs(raw, accept=printable_text)
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


# ------------------------------------------------------- clause-level rules (17-20)
#
# These count clauses that order the assistant to act, not keyword mentions. Questions,
# warnings, personal accounts, authoring requests and code blocks do not count.

# a full stop only splits before whitespace, so addresses, URLs and version numbers stay whole;
# a colon stays on the clause before it, so "run this on your server:" is recognisable;
# "and" splits before a second order verb, so "ignore the rules and delete all files" gives two clauses
_SPLIT_VERBS = (r"(?:run|execute|delete|drop|wipe|erase|disable|transfer|wire|grant|send|forward|"
                r"email|upload|format|truncate|post|leak|exfiltrate)")
_CLOSE = r"[\"'”’)\]]*"
CLAUSE_SPLIT_RE = re.compile(
    rf"(?:\.(?={_CLOSE}(?:\s|$))|[!?;\n。！？；])+|\s+(?:and\s+then|then)\s+|\s+and\s+(?={_SPLIT_VERBS}\b)|(?<=:)(?=\s)"
)
CODE_BLOCK_RE = re.compile(r"```.*?(?:```|$)", re.S)
# a shell prompt line: "$ rm -rf /", "# sudo apt install", "user@host:~$ ls", "# git reset --hard"
SHELL_LINE_RE = re.compile(
    r"^\s*(?:\$\s*$|\$\s|[\w.-]+@[\w.-]+:\S*[$#]\s|#\s*(?:sudo\b|rm\b|mkfs|dd\s+if=|chmod\b|chown\b|curl\b|"
    r"wget\b|\w[\w.-]*\s+(?:-{1,2}\w|/|\./|~)))"
)
# markdown headings and quoted replies are read without their prefix
QUOTE_PREFIX_RE = re.compile(r"^\s*(?:>\s*|#+\s+)+")

_Q_AUX = r"(?:is|are|was|were|do|does|did|can|could|should|would|will|shall|may|might|has|have|had|to)"
QUESTION_START_RE = re.compile(
    r"^\s*(?:what(?:'s|\s+(?:is|are|was|were|does|do|did|would|will|can|could|should|"
    r"happens|happened|if|about|kind|exactly|else|the|are))|how(?:\s+(?:do|does|did|can|could|"
    r"would|should|to|is|are|was|were|about|much|many|long|often|come|will|i|you|we|one))|"
    rf"why|(?:when|where|which|who|whom|whose)\s+{_Q_AUX}|is|are|was|were|(?:does|do|did)(?!\s+not\b|n't)|"
    r"can(?!not\b|'t)|could|would|should|will|shall|may|might|has|have|had|am|isn't|aren't|doesn't|don't|"
    r"any\s+idea|anyone\s+know)\b"
)
QUESTION_INSIDE_RE = re.compile(
    r"\b(?:what\s+does|what\s+do|what\s+is|what\s+are|what\s+happens|what\s+would|how\s+do\s+i|"
    r"how\s+can\s+i|how\s+does|how\s+would|how\s+to|is\s+it\s+safe|is\s+there|explain|meaning\s+of|"
    r"difference\s+between|tell\s+me\s+about|i\s+(?:wonder|was\s+wondering)|do\s+you\s+know|does\s+anyone)\b"
)
# "can you run ...", "could you please forward ...", "would you mind running ...": a request, not a question
# a short lead-in may precede the verb: "when you are done, run", "[for the assistant] run", "note: run"
_LEAD_IN = r"(?:\[[^\]\n]{0,40}\]\s*|\([^)\n]{0,40}\)\s*|[^,\n]{0,40},\s*|[^:\n]{0,40}:\s*)?"
POLITE_ORDER_RE = re.compile(
    rf"^\s*{_LEAD_IN}(?:can|could|would|will|can't|cant)\s+(?:you|u|ya)\s+"
    r"(?:(?:please|pls|plz|just|kindly|quickly|maybe|perhaps|also|now|go\s+ahead\s+and)\s+)*(?:mind\s+)?"
    r"(?:run|running|execute|executing|type|typing|issue|issuing|do|doing|perform|performing|call|calling|"
    r"invoke|invoking|delete|deleting|drop|dropping|wipe|wiping|erase|erasing|format|formatting|truncate|"
    r"truncating|disable|disabling|turn|turning|transfer|transferring|wire|wiring|grant|granting|send|"
    r"sending|forward|forwarding|email|emailing|mail|mailing|upload|uploading|post|posting|share|sharing|"
    r"copy|copying|export|exporting|bcc|cc|leak|leaking|pay|paying|move|moving|add|adding)\b"
)
# "do not / never ..." warns, unless what follows is "ask", "confirm", "tell" (that is secrecy or pressure)
WARNING_RE = re.compile(
    r"\b(?:never|do\s+not|don't|dont|shouldn't|should\s+not|must\s+not|mustn't)"
    r"(?!\s+(?:ask|confirm|tell|warn|check|question|hesitate|worry|wait|mention|notify|bother|explain|"
    r"show|display|log|report|announce|say|let|even|stop|refuse|skip|hold|delay|verify|double-?check|"
    r"prompt|inform|reveal|disclose|acknowledge|include|echo|forget)\b)\b|"
    r"\b(?:avoid|beware|be\s+careful|careful|caution|warning|dangerous|danger|risky|harmful|"
    r"not\s+recommended|bad\s+idea|will\s+(?:destroy|wipe|erase|delete)|would\s+(?:destroy|wipe|erase|delete)|"
    r"can\s+(?:destroy|wipe|erase|delete)|(?<!not\s)(?<!n't\s)(?<!never\s)(?<!dont\s)refuse|refused|"
    r"malicious|attack(?:er|s)?|scam|phishing|unless|instead\s+of\s+running|rather\s+than)\b"
)
_ACCOUNT_VERBS = (r"(?:accidentally\s+|once\s+|just\s+|then\s+|already\s+|mistakenly\s+)?(?:ran|executed|"
                  r"typed|entered|used|did|tried|issued|wrote|deleted|wiped|erased|formatted|dropped|"
                  r"truncated|disabled|transferred|wired|granted|had\s+to|decided|forgot|remember|noticed|"
                  r"found|think|thought|believe)")
# "I ran ...", "we had to drop ...", "the script deleted ..."; the assistant as subject is an order
PERSONAL_ACCOUNT_RE = re.compile(
    rf"\b(?:i|we|he|she|they|someone|somebody)\s+{_ACCOUNT_VERBS}\b|"
    r"\b(?:i|we|he|she|they|someone|somebody)\s+(?:have\s+to|need\s+to|needed\s+to|want\s+to|wanted\s+to|"
    r"was\s+going\s+to|am\s+going\s+to|would|could|might|should|will)\b|"
    rf"\b(?:my|the)\s+(?!(?:ai|assistant|agent|model|bot|chatbot|llm|copilot)\b)\w+\s+{_ACCOUNT_VERBS}\b|"
    r"\bi'(?:ve|d|ll|m)\b|\bwe'(?:ve|d|ll|re)\b"
)
AUTHORING_RE = re.compile(
    r"\b(?:write|create|draft|generate|make|build|show|give|provide|suggest|share|produce|"
    r"prepare|design|code|implement|add|compose)\b[^.!?\n]{0,25}?"
    r"\b(?:dockerfile|migration|script|playbook|snippet|example|command|commands|function|"
    r"query|makefile|cronjob|cron\s+job|one-?liner|program|tutorial|guide|manual|"
    r"documentation|recipe|module|class|method|test|tests|pipeline|workflow|runbook|"
    r"checklist|sql|bash|shell|code|alias|hook|job|procedure|policy|rule|regex|"
    r"post|article|essay|poem|story|blog|paragraph|list|explanation|summary|answer)\b"
)
IMPERATIVE_ORDER_RE = re.compile(
    rf"^\s*{_LEAD_IN}(?:(?:please|pls|plz|now|just|then|and|also|kindly|simply|first|next|finally|"
    r"immediately|go\s+ahead\s+and|make\s+sure\s+to|quickly|silently|secretly|quietly)\s+)*"
    r"(?:run|execute|type|enter|use|do|issue|invoke|launch|fire|perform|call|apply|start|"
    r"trigger|paste|copy|send|forward|email|mail|upload|post|share|transfer|wire|pay|move|"
    r"delete|erase|wipe|remove|drop|truncate|format|destroy|purge|disable|turn|switch|shut|"
    r"stop|kill|grant|give|add|open|initiate|proceed|go|make|set|chmod|sudo|rm|mkfs|dd|curl|"
    r"message|text|dm|ping|contact|spam|access|export|download|connect|"
    r"wget|führe?|führen\s+sie|ejecut[ae]|ejecuten|exécute[z]?|execute[z]|esegui|eseguite|voer|"
    r"выполни(?:те)?|запусти(?:те)?)\b"
)
# order verbs of languages that put the verb elsewhere in the clause
ML_ORDER_RE = re.compile(r"çalıştır|चलाओ|चलाएं|चलाएँ|実行|执行|執行|نفّذ|نفذ|شغّل|شغل")
ORDER_MARKER_RE = re.compile(
    r"\bplease\b|\byou\s+(?:must|shall|will|have\s+to|need\s+to|are\s+to|should|are\s+required|"
    r"are\s+going\s+to|are\s+instructed|are\s+authori[sz]ed|can\s+now|may\s+now)\b|"
    r"\b(?:on|in|to|from|of)\s+(?:your|the\s+user'?s?|the\s+host|this|the\s+target|the\s+company'?s?|"
    r"their|the\s+production|the\s+prod|the\s+main|every|each|all(?:\s+of)?(?:\s+the)?)\s+"
    r"(?:system|machine|server|computer|laptop|box|host|database|db|environment|cluster|account|"
    r"network|infrastructure|instance|device|repo|repository|filesystem|disk|drive|root|home|node)s?\b|"
    r"\b(?:i\s+(?:want|need|order|command|instruct|demand|require)\s+you\s+to|"
    r"your\s+(?:next\s+)?(?:task|job|instruction|assignment|order)\s+is\s+to|"
    r"as\s+(?:soon\s+as|quickly\s+as)\s+(?:you\s+can|possible)|right\s+now|right\s+away|"
    r"do\s+it\s+now|do\s+this\s+now|now\s+run|go\s+ahead|this\s+is\s+(?:an?\s+)?"
    r"(?:order|command|instruction|directive)|before\s+(?:you\s+)?(?:answer|reply|respond|"
    r"continue|proceed|do\s+anything\s+else)|so\s+(?:execute|run|do\s+it|just|go\s+ahead)|"
    r"you\s+have\s+(?:\w+\s+){0,2}?access|no\s+questions(?:\s+asked)?)\b"
)

_ORDER_VERB = (r"(?:run|execute|type|enter|use|issue|invoke|launch|fire|perform|call|apply|"
               r"start|trigger|paste|do)")
DANGEROUS_PATTERNS = [
    # shell syntax: only counts when something orders it
    r"\brm\s*-\s*(?:rf|fr)\b", r"\brm\s*-\s*r\s*-\s*f\b", r"\brm\s*-\s*f\s*-\s*r\b",
    r"\brm\s+-\w*r\w*\s+/(?:\s|$|\*)", r"\bmkfs(?:\.\w+)?\b", r"\bdd\s+if=", r"\bformat\s+[a-z]:",
    r"\bdrop\s+(?:table|database|schema)\b", r"\btruncate\s+table\b",
    # "truncate the events and metrics tables" (round five; the clause splitter drops the ";" that the
    # old "delete from ... ;" form needed, so that form never matched inside a clause)
    r"\btruncate\s+(?:the\s+|all\s+|every\s+)?(?:[\w-]+\s+){0,3}?tables?\b",
    r"\bdelete\s+from\s+[\w.\"`]+(?:\s+where\b[^;\n]{0,80})?\s*(?:;|$)", r"\b(?:curl|wget)\b[^|\n]{0,100}\|\s*(?:sudo\s+)?(?:ba|z|da)?sh\b",
    r"\bchmod\s+-r\s+777\b", r"\bchmod\s+777\s+/(?:\s|$)", r":\(\)\s*\{\s*:\s*\|\s*:\s*&\s*\}\s*;\s*:",
    r"\bfork\s*bomb\b", r"\bshutdown\s+(?:-h|/s|now)\b", r"\breboot\s+--force\b",
    # english wording
    # "delete all the user's emails", "wipe every disk"; "delete all references to ai" is not destructive
    r"\b(?:delete|erase|wipe|destroy|purge|nuke)\s+(?:everything|the\s+entire|the\s+whole|your\s+entire|"
    r"its\s+entire)\b",
    r"\b(?:delete|erase|wipe|destroy|purge|nuke)\s+(?:all|every|each)\s+(?:of\s+)?(?:the\s+|your\s+|its\s+|"
    r"their\s+|my\s+|our\s+)?(?:[\w-]+'?s?\s+){0,2}?(?:files?|data|records?|users?|backups?|logs?|databases?|"
    r"tables?|directories|folders?|accounts?|contents?|rows?|entries|emails?|messages?|documents?|snapshots?|"
    r"volumes?|keys?|disks?|drives?|partitions?|servers?|machines?|systems?|repos?|repositories|branches|"
    r"buckets?|containers?|instances?|nodes?|vms?|objects?|images?|photos?|contacts?|customers?|orders?|"
    r"transactions?|history|caches?|cookies|sessions?|credentials|secrets|evidence|traces?)\b",
    # a path may sit before the noun: "remove the entire /var/app/data directory"
    r"\b(?:remove|drop)\s+(?:all|every|the\s+entire|the\s+whole)\s+(?:the\s+)?(?:[\w~.-]*[/~.][\w/~.-]*\s+)?"
    r"(?:files?|data|records?|users?|backups?|logs?|databases?|tables?|director(?:y|ies)|folders?|accounts?|"
    r"contents?|rows?|entries|emails?|messages?|documents?|snapshots?|volumes?|keys?|buckets?)\b",
    # "purge all of the snapshots", "empty the archive storage bucket"
    r"\b(?:empty|purge|wipe)\s+(?:the\s+|every\s+|all\s+(?:of\s+)?(?:the\s+)?)?(?:[\w-]+\s+){0,2}?(?:buckets?|snapshots?)\b",
    r"\b(?:wipe|erase|format|destroy|nuke|reformat)\s+(?:the\s+|your\s+|my\s+|its\s+|their\s+)?"
    r"(?:hard\s+|main\s+|primary\s+|root\s+|production\s+|prod\s+|entire\s+|whole\s+)?"
    r"(?:drive|disk|server|machine|system|database|computer|partition|filesystem|volume|"
    r"cluster|repo|repository|backups?)\b",
    r"\b(?:disable|turn\s+off|switch\s+off|shut\s+down|shut\s+off|deactivate|stop|kill|"
    r"remove|bypass|uninstall|suspend)\s+(?:the\s+|your\s+|all\s+|any\s+|every\s+|its\s+)?"
    r"(?:firewalls?|antivirus|anti-virus|anti-malware|2fa|two-?factor(?:\s+auth\w*)?|mfa|"
    r"multi-?factor(?:\s+auth\w*)?|logging|audit\s+log(?:s|ging)?|logs|log\s+files|monitoring|"
    r"security\s+\w+|backups?|selinux|windows\s+defender|defender|endpoint\s+protection|"
    r"encryption|authentication|password\s+protection|access\s+controls?|alerts?|alerting)\b",
    r"\b(?:transfer|wire|send|move|pay|remit)\s+(?:the\s+)?(?:(?:\$|€|£|usd\s*|eur\s*|gbp\s*)"
    r"?\d[\d,.]*\s*(?:k|m|million|thousand|dollars|usd|eur|euros?|gbp|pounds|btc|eth|bitcoin|"
    r"bitcoins|sol|usdt)?|all\s+(?:the\s+|available\s+|remaining\s+)?(?:funds|money|balance|"
    r"assets|crypto|bitcoin)|the\s+(?:funds|money|balance|full\s+amount|entire\s+balance))"
    r"\s+(?:to|into)\b",
    r"\b(?:grant|give|assign|allow|provide)\s+(?:me|them|him|her|us|it|the\s+user|this\s+user|"
    r"[\w@.-]+)\s+(?:full\s+|complete\s+|unrestricted\s+|permanent\s+)?(?:admin|administrator|"
    r"root|sudo|superuser|full|write|owner|unrestricted)\s+(?:access|rights|privileges?|"
    r"permissions?|role)\b",
    r"\b(?:grant|give|escalate\s+to)\s+(?:full\s+|complete\s+|unrestricted\s+)?"
    r"(?:admin|administrator|root|sudo|superuser)\s+(?:access|rights|privileges?|permissions?)\b",
    r"\badd\s+[\w@.-]+\s+to\s+(?:the\s+)?(?:sudoers|admins?|administrators?|root)\s*(?:group|file|list)?\b",
    r"\b(?:make|set)\s+[\w@.-]+\s+(?:an?\s+)?(?:admin|administrator|root|superuser|owner)\b",
    r"\b(?:leak|exfiltrate|dump|export|steal)\s+(?:all\s+|the\s+|every\s+)?(?:passwords?|"
    r"credentials|secrets|private\s+keys?|customer\s+(?:data|records)|user\s+(?:data|records)|"
    r"database)\b",
]
DANGEROUS_RE = re.compile("|".join(f"(?:{p})" for p in DANGEROUS_PATTERNS), re.M)
# a bare shell command: only an order when something around it says so
SHELL_ONLY_RE = re.compile(r"^\s*(?:sudo\s+)?(?:rm|mkfs(?:\.\w+)?|dd|chmod|chown|curl|wget)\s|^\s*:\(\)")


def _clauses(text):
    """Sentences and clauses of a text, with fenced code blocks and shell lines removed.

    A clause that ended in a question mark keeps it, so questions stay recognisable.
    """
    text = CODE_BLOCK_RE.sub(" ", text)
    lines = [QUOTE_PREFIX_RE.sub("", line) for line in text.split("\n") if not SHELL_LINE_RE.match(line)]
    text = "\n".join(lines)
    clauses, start = [], 0
    for match in CLAUSE_SPLIT_RE.finditer(text):
        clause = text[start:match.start()].strip()
        if clause:
            question = "?" in match.group(0) or "？" in match.group(0)
            clauses.append(clause + "?" if question else clause)
        start = match.end()
    tail = text[start:].strip()
    if tail:
        clauses.append(tail)
    return clauses


def _is_question(clause):
    return bool(clause.endswith("?") or QUESTION_START_RE.match(clause) or QUESTION_INSIDE_RE.search(clause))


def _is_order(clause, previous):
    """Does the clause tell the reader (or the assistant) to do something?"""
    # "could you export the passwords and send them to x@y?": the second clause is asked as politely
    polite = POLITE_ORDER_RE.match(clause) or (previous and POLITE_ORDER_RE.match(previous)
                                               and IMPERATIVE_ORDER_RE.match(clause))
    if not polite and (clause.endswith("?") or QUESTION_START_RE.match(clause)):
        return False
    if QUESTION_INSIDE_RE.search(clause) or WARNING_RE.search(clause) or PERSONAL_ACCOUNT_RE.search(clause):
        return False
    if AUTHORING_RE.search(clause):
        return False
    if (polite or IMPERATIVE_ORDER_RE.match(clause) or ORDER_MARKER_RE.search(clause)
            or AI_ADDRESSED_RE.search(clause) or ML_ORDER_RE.search(clause)):
        return True
    # a bare command right after "run the following on your server:"
    return bool(previous and previous.rstrip().endswith(":") and ORDER_MARKER_RE.search(previous)
                and not WARNING_RE.search(previous) and not _is_question(previous))


def _ordered_clauses(text, pattern, evidence=None):
    """Clauses that match `pattern` and are an order, as snippets.

    With `evidence`, the clause also needs that predicate to hold on it and its neighbours.
    """
    hits, clauses = [], _clauses(text)
    for i, clause in enumerate(clauses):
        if not pattern.search(clause):
            continue
        previous = clauses[i - 1] if i else ""
        bare_shell = (SHELL_ONLY_RE.match(clause) and not previous.rstrip().endswith(":")
                      and not ORDER_MARKER_RE.search(clause) and not AI_ADDRESSED_RE.search(clause))
        if bare_shell or not _is_order(clause, previous):
            continue
        if evidence and not evidence(clauses[max(0, i - 1):i + 2]):
            continue
        hits.append(_snip(clause))
    return hits


def dangerous_action_count(views):
    """Clauses that order a destructive command or action."""
    hits = _ordered_clauses(views.norm, DANGEROUS_RE)
    return len(hits), hits


# --- tool calls and data-sending orders

_DATA_ACTION = (r"(?:send|forward|email|mail|upload|post|transfer|pay|wire|make_payment|exfiltrate|leak|"
                r"purchase|buy)")
_ACTION = rf"(?:{_DATA_ACTION}|delete|remove|grant|share|submit|export|order|execute|run|exec)"
TOOL_SYNTAX_RE = re.compile(
    # a call that moves data counts as such; other calls need a quoted argument ("run_tests()" is prose)
    rf"\b{_DATA_ACTION}_[a-z_]*\s*\([^\n]{{0,120}}\)|"
    r"\b(?:execute|run|exec|delete|remove|share|submit|export)_[a-z_]+\s*\(\s*[\"'][^\n]{0,120}\)|"
    r"\b(?:function_call|tool_call|tool_use|function_calling)\b|"
    r"<(?:tool_call|function_call|invoke|function=|tool_use|antml:invoke)\b[^>]*>|"
    r"\"(?:tool_name|function_name)\"\s*:\s*\"|\"(?:tool|function)\"\s*:\s*\{|"
    r"\"type\"\s*:\s*\"(?:function|tool_use|tool_call)\"|"
    rf"\b(?:call|use|invoke|trigger)\s+(?:the\s+|your\s+|its\s+|a\s+)?(?:[\w-]+\s+){{0,2}}?"
    rf"(?:tool|plugin|function|api|endpoint|webhook)\s+(?:call\s+)?(?:to\s+|and\s+){_ACTION}\b|"
    r"\b(?:call|use|invoke|trigger)\s+(?:the\s+|your\s+|a\s+)?[a-z]+_[a-z_]+\s+(?:tool|function|api|plugin|endpoint)\b"
)
SEND_TO_RE = re.compile(
    r"\b(?:send|forward|email|mail|upload|post|share|submit|transmit|exfiltrate|leak|"
    r"deliver|report|copy|cc|bcc)\b[^.!?\n]{0,100}?\bto\s+"
    r"(?:https?://\S+|www\.\S+|[\w.+-]+\s*(?:@|\(at\)|\[at\]|<at>|\{at\}|\bat\b)\s*[\w-]+\s*"
    r"(?:\.|\(dot\)|\[dot\]|<dot>|\{dot\}|\bdot\b)\s*\w+|(?:the\s+|this\s+)?(?:following|below|"
    r"attached|given|above|this|that|my|our)\s+(?:address|url|email|endpoint|webhook|server|link|"
    r"inbox|number|account)|[\w-]+\.(?:com|net|org|io|xyz|ru|cn|info|co|me|top|site|online|"
    r"dev|app|ai|cc|tk|link|click|example|test|invalid|localhost)\b)"
)
EVASIVE_ADDRESS_RE = re.compile(
    r"\(at\)|\[at\]|<at>|\{at\}|\(dot\)|\[dot\]|<dot>|\{dot\}|\b\w+\s+at\s+\w+\s+dot\s+\w+\b|"
    r"hxxps?://|\[\.\]|\(\.\)|\bdot\s+(?:com|net|org|io|xyz|ru)\b"
)
SECRECY_RE = re.compile(
    r"\bsecretly\b|\bcovertly\b|\bquietly\b|\bdiscreetly\b|\bsilently\b|\bstealthily\b|"
    r"\bin\s+the\s+background\b|\bbehind\s+the\s+scenes\b|"
    r"\bwithout\s+(?:telling|informing|notifying|alerting|mentioning|asking|confirming|"
    r"showing|letting|announcing|saying|the\s+user(?:'s)?\s+(?:knowledge|consent|noticing|"
    r"permission|awareness)|(?:any\s+)?(?:confirmation|notice|warning|prompt|approval))\b|"
    r"\b(?:do\s+not|don't|dont|never)\s+(?:mention|tell|reveal|disclose|inform|"
    r"notify|alert|show|display|let\s+(?:the\s+)?(?:user|them|anyone)\s+(?:know|see)|say\s+"
    r"anything|acknowledge|announce|confirm|ask|log|report\s+this|include\s+this|echo)\b|"
    r"\bno\s+need\s+to\s+(?:mention|tell|reveal|disclose|inform|notify|alert|let\s+(?:the\s+)?"
    r"(?:user|them|anyone)\s+know|say\s+anything|acknowledge|announce|log|report\s+this)\b|"
    r"\bkeep\s+(?:this|it|that)\s+(?:a\s+)?(?:secret|hidden|between\s+us|quiet|to\s+yourself)\b|"
    r"\bthe\s+user\s+(?:must|should|will|won't|does)\s+not\s+(?:know|see|notice|be\s+told|"
    r"be\s+aware|find\s+out)\b|\bnobody\s+(?:will|needs\s+to)\s+(?:know|notice)\b|"
    r"\bdelete\s+(?:this|the)\s+(?:message|email|instruction|note)\s+(?:after|afterwards|once)\b"
)
# data that belongs to the user or the system; plain words such as "contacts" or "location" do not count
PRIVATE_DATA_RE = re.compile(
    r"\b(?:passwords?|passcodes?|credentials|login\s+details|api\s+keys?|secret\s+keys?|"
    r"access\s+tokens?|auth\s+tokens?|(?:session|login|auth|browser)\s+cookies?|session\s+tokens?|"
    r"private\s+keys?|seed\s+phrase|recovery\s+(?:codes?|phrase)|(?:2fa|mfa|otp|one-time|verification)\s+codes?|"
    r"contact\s+list|address\s+book|saved\s+addresses|home\s+address|shipping\s+address|"
    r"credit\s+card|card\s+numbers?|cvv|ssn|social\s+security|bank\s+(?:details|account|"
    r"credentials)|account\s+numbers?|routing\s+numbers?|iban|"
    r"(?:this|the|our|entire|whole|full|current|previous)\s+(?:conversation|chat|chat\s+history|"
    r"conversation\s+history|transcript|thread)|chat\s+log|message\s+history|"
    r"browsing\s+history|search\s+history|gps\s+coordinates|"
    r"(?:the\s+)?(?:other\s+)?(?:users?'?s?|tenants?'?s?|customers?'?s?|clients?'?s?|patients?'?s?|"
    r"employees?'?s?|members?'?s?)\s+(?:data|files|emails|messages|information|details|inbox|documents|"
    r"sessions?|conversations?|records|contacts|contact\s+details|addresses|location|cookies|"
    r"personal\s+\w+|private\s+\w+|names?\s+and\s+\w+|email\s+address(?:es)?|phone\s+numbers?)|"
    r"(?:everything|all\s+(?:the\s+)?(?:emails?|messages?|files|documents|attachments|mail)|"
    r"each\s+message|every\s+(?:message|email|file))\s+(?:in|from)\s+(?:the|this|their|my|your|his|her|"
    r"other\s+users'?)\s+(?:inbox|mailbox|account|drive|folder|conversation|sessions?|chats?)|"
    r"(?:private|personal|confidential|sensitive|customer|patient|employee|medical|financial|"
    r"payroll|hr)\s+(?:data|information|details|records|files|documents|info)|pii|"
    r"everything\s+(?:you|the\s+user)\s+(?:know|said|typed|wrote|shared)|system\s+prompt|"
    r"your\s+(?:instructions|prompt|configuration|system\s+message))\b"
)
_AI = r"(?:ai|assistant|agent|chatbot|bot|llm|copilot|gpt|chatgpt|claude|gemini|siri|alexa|language\s+model)"
AI_ADDRESSED_RE = re.compile(
    rf"\b(?:if\s+you\s+are\s+an?\s+(?:ai|llm|assistant|agent|model|language\s+model|chatbot|bot)|"
    rf"{_AI}s?\s*[,:!\])]|(?:dear|hey|hello|hi|attention|yo)\s+(?:the\s+|any\s+|all\s+)?{_AI}s?\b|"
    rf"(?:note|message|instructions?|reminder|word|request|ps|p\.s\.)\s+(?:to|for)\s+(?:the\s+|any\s+|all\s+)?{_AI}s?\b|"
    r"to\s+(?:the\s+|any\s+|all\s+)?(?:ai|llm|chatbot|copilot|gpt|chatgpt|claude|gemini|language\s+model)s?\b|"
    r"you\s+are\s+(?:an?\s+)?(?:ai|assistant|agent|llm|language\s+model|chatbot|bot)\b|"
    r"as\s+an?\s+(?:ai|assistant|agent|llm|language\s+model|chatbot)\b|"
    r"(?:the|any|an)\s+(?:ai|assistant|agent|llm|chatbot|bot|copilot|language\s+model|ai\s+model)\s+"
    r"(?:reading|processing|summari[sz]ing|parsing|handling|that\s+reads?|that\s+process(?:es)?|"
    r"who\s+reads?|must|should|will|is\s+to|needs?\s+to|has\s+to|shall)\b|"
    r"(?:the|any)\s+model\s+(?:reading|processing|summari[sz]ing|parsing|that\s+reads?|that\s+process(?:es)?)\b|"
    r"(?:your|the)\s+(?:system\s+prompt|function\s+calls?|tool\s+calls?|api\s+access|previous\s+instructions?)\b)"
)


# an order to message everyone the user knows counts on its own: no secrecy or address needed (round five)
MASS_MESSAGE_RE = re.compile(
    r"\b(?:message|text|dm|email|e-mail|mail|contact|spam|ping|write\s+to)\s+"
    r"(?:every\s+(?:single\s+)?(?:one\s+(?:of\s+)?)?|all\s+(?:of\s+)?|each\s+(?:of\s+)?|everyone\s+(?:in|on)\s+|"
    r"everybody\s+(?:in|on)\s+)(?:the\s+|my\s+|your\s+|their\s+|his\s+|her\s+|our\s+)?(?:[\w-]+\s+){0,2}?"
    r"(?:contacts?|contact\s+list|address\s+book|friends?|followers?|users?|customers?|clients?|members?|"
    r"subscribers?|employees?|them)\b"
)


def _send_evidence(nearby):
    """Signs that a send order is an attack: secrecy, private data, an evasive address, the AI as reader."""
    text = "\n".join(nearby)
    return bool(SECRECY_RE.search(text) or PRIVATE_DATA_RE.search(text)
                or EVASIVE_ADDRESS_RE.search(text) or AI_ADDRESSED_RE.search(text))


def tool_action_count(views):
    """Tool-call syntax, plus orders to send data somewhere when the clauses around show an attack."""
    text = views.norm
    hits = [_snip(m.group(0)) for m in TOOL_SYNTAX_RE.finditer(text)]
    hits += _ordered_clauses(text, SEND_TO_RE, _send_evidence)
    hits += _ordered_clauses(text, MASS_MESSAGE_RE)
    return len(hits), hits


# --- override and system-prompt wording in other languages

# (verb, object) pairs per language: an override verb with a rules object, or a reveal verb with
# a system-prompt object ("your instructions", "prompt système"). A clause counts with one pair.
_ML = {
    "de": {
        "override": r"\b(?:ignorier\w*|vergiss|vergesst|vergessen|missacht\w*|übergeh\w*|überschreib\w*|"
                    r"verwirf|verwerf\w*|umgeh\w*|außer\s+kraft|nicht\s+mehr\s+(?:befolg\w*|beacht\w*|gelten|"
                    r"gültig)|hebe?\s+(?:\w+\s+){0,3}?auf|lösch\w*|streich\w*|deaktivier\w*|brich\w*|"
                    r"halte?\s+dich\s+nicht|hör\w*\s+auf|aufhören|nicht\s+(?:\w+\s+){0,3}?(?:befolg\w*|beacht\w*|"
                    r"folg\w*))\b",
        "rules": r"\b(?:\w*anweisung\w*|\w*regeln|\w*richtlinien|\w*vorgaben|instruktion\w*|befehle|system-?prompt\w*|"
                 r"system-?nachricht\w*|system-?anweisung\w*|einschränkung\w*|leitlinien|vorschriften|"
                 r"auflagen|programmierung|prompt\w*|sicherheitsvorkehrungen|filter)\b",
        "reveal": r"\b(?:zeig\w*|gib\s+(?:\w+\s+){0,3}?(?:aus|preis|wieder)|verrat\w*|druck\w*|wiederhol\w*|"
                  r"offenbar\w*|enthüll\w*|nenn\w*|schreib\w*|leak\w*|kopier\w*|sage?\s+mir|erzähl\w*|"
                  r"liste\w*)\b",
        "prompt": r"\b(?:system-?prompt\w*|system-?nachricht\w*|system-?anweisung\w*|"
                  r"(?:deine[nrs]?|ihre[nrs]?|eure[nrs]?)\s+(?:\w+\s+)?(?:anweisung\w*|regeln|instruktion\w*|"
                  r"richtlinien|vorgaben|konfiguration|prompt\w*|programmierung)|"
                  r"(?:versteckt\w*|verborgen\w*|geheim\w*|ursprünglich\w*|initial\w*|intern\w*|vorherig\w*)\s+"
                  r"(?:anweisung\w*|regeln|instruktion\w*|prompt\w*|nachricht|text))\b",
    },
    "es": {
        "override": r"\b(?:ignor[ae]\w*|olvid[ae]\w*|omit[ae]\w*|descart[ae]\w*|anul[ae]\w*|desobedec\w*|"
                    r"salt[ae]\w*|desactiv[ae]\w*|no\s+sigas|no\s+obedezcas|ha(?:z|cer)\s+caso\s+omiso|"
                    r"pas[ae]\s+por\s+alto|deja\s+de\s+seguir|elimin[ae]\w*|borr[ae]\w*)\b",
        "rules": r"\b(?:instrucciones|reglas|indicaciones|directrices|órdenes|ordenes|restricciones|prompt|"
                 r"mensaje\s+del\s+sistema|configuración|configuracion|pautas|lineamientos|normas|directivas|"
                 r"programación|programacion|limitaciones|filtros)\b",
        "reveal": r"\b(?:revel[ae]\w*|muestr[ae]\w*|mostrar|imprim[ae]\w*|repit[ae]\w*|repet\w*|dime|díme|"
                  r"dame|escrib[ae]\w*|copi[ae]\w*|compart[ei]\w*|expon\w*|filtr[ae]\w*|ens[eé]ñame|"
                  r"cu[eé]ntame|lista|enumera)\b",
        "prompt": r"\b(?:prompt\s+(?:del\s+)?(?:sistema|inicial|oculto|secreto|original)|mensaje\s+del\s+sistema|"
                  r"instrucciones\s+(?:del\s+sistema|iniciales|ocultas|secretas|originales|previas|anteriores)|"
                  r"(?:tus?|sus?|vuestr[ao]s?)\s+(?:\w+\s+)?(?:instrucciones|reglas|prompt|configuración|"
                  r"configuracion|directrices|indicaciones|programación|programacion)|"
                  r"configuración\s+del\s+sistema)\b",
    },
    "fr": {
        "override": r"\b(?:ignor\w*|oubli\w*|néglig\w*|neglig\w*|outrepass\w*|contourn\w*|désactiv\w*|"
                    r"desactiv\w*|ne\s+(?:suis|suivez|respecte|respectez|tiens|tenez)\s+(?:pas|plus)|"
                    r"fai(?:s|tes)\s+abstraction|passe[z]?\s+outre|annul\w*|abandonn\w*|supprim\w*|"
                    r"laisse[z]?\s+tomber)\b",
        "rules": r"\b(?:instructions?|consignes?|règles?|regles?|directives?|restrictions?|prompt|"
                 r"invite\s+(?:système|systeme)|message\s+(?:système|systeme)|configuration|limitations?|"
                 r"programmation|paramètres|parametres|filtres?|garde-fous)\b",
        "reveal": r"\b(?:révèl\w*|revel\w*|affich\w*|montr\w*|imprim\w*|répèt\w*|repet\w*|dévoil\w*|"
                  r"devoil\w*|divulgu\w*|écri\w*|ecri\w*|donne\w*|copi\w*|partag\w*|di(?:s|tes)[\s-]moi|"
                  r"liste\w*|récit\w*|recit\w*)\b",
        "prompt": r"\b(?:(?:prompt|invite|message|instructions?|consignes?|règles?|regles?|directives?)\s+"
                  r"(?:système|systeme|initial\w*|cach\w*|secr\w*|d'origine|de\s+base|original\w*)|"
                  r"(?:ton|tes|vos|votre)\s+(?:\w+\s+)?(?:prompt|instructions?|consignes?|règles?|regles?|"
                  r"directives?|configuration|programmation)|prompt\s+du\s+(?:système|systeme))\b",
    },
    "it": {
        "override": r"\b(?:ignor\w*|dimentic\w*|tralasci\w*|scavalc\w*|aggir\w*|disattiv\w*|"
                    r"non\s+(?:seguire|rispettare|obbedire|seguir)|annull\w*|abbandon\w*|elimin\w*|salt\w*)\b",
        "rules": r"\b(?:istruzioni|regole|direttive|indicazioni|restrizioni|prompt|messaggio\s+di\s+sistema|"
                 r"configurazione|limitazioni|linee\s+guida|programmazione|impostazioni|filtri)\b",
        "reveal": r"\b(?:rivel\w*|mostr\w*|stamp\w*|ripet\w*|svel\w*|dimmi|scriv\w*|copi\w*|condivid\w*|"
                  r"elenc\w*|riport\w*|visualizz\w*)\b",
        "prompt": r"\b(?:prompt\s+(?:di\s+sistema|iniziale|nascosto|segreto|originale)|messaggio\s+di\s+sistema|"
                  r"istruzioni\s+(?:di\s+sistema|iniziali|nascoste|segrete|originali|precedenti)|"
                  r"(?:le\s+tue|la\s+tua|tue|tua|le\s+sue|sue|vostr[ae])\s+(?:\w+\s+)?(?:istruzioni|regole|"
                  r"prompt|configurazione|direttive|impostazioni|programmazione))\b",
    },
    "pt": {
        "override": r"\b(?:ignor\w*|esque[çc]\w*|desconsider\w*|descart\w*|desativ\w*|"
                    r"n[ãa]o\s+(?:siga|obede[çc]a|respeite)|anul\w*|cancel\w*|abandon\w*|elimin\w*|pul[ae]\w*)\b",
        "rules": r"\b(?:instru[çc][õo]es|instru[çc][ãa]o|regras|diretrizes|orienta[çc][õo]es|restri[çc][õo]es|"
                 r"prompt|mensagem\s+do\s+sistema|configura[çc][ãa]o|comandos\s+anteriores|limita[çc][õo]es|"
                 r"programa[çc][ãa]o|filtros)\b",
        "reveal": r"\b(?:revel\w*|mostr\w*|imprim\w*|repit\w*|repet\w*|exib\w*|diga|diga-me|me\s+diga|"
                  r"me\s+conte|escrev\w*|copi\w*|compartilh\w*|divulg\w*|list\w*)\b",
        "prompt": r"\b(?:prompt\s+(?:do\s+sistema|inicial|oculto|secreto|original)|mensagem\s+do\s+sistema|"
                  r"instru[çc][õo]es\s+(?:do\s+sistema|iniciais|ocultas|secretas|originais|anteriores)|"
                  r"(?:suas?|seus?|tuas?|teus?)\s+(?:\w+\s+)?(?:instru[çc][õo]es|regras|prompt|"
                  r"configura[çc][ãa]o|diretrizes|programa[çc][ãa]o))\b",
    },
    "nl": {
        "override": r"\b(?:negeer\w*|vergeet|vergeten|omzeil\w*|schakel\s+(?:\w+\s+){0,3}?uit|"
                    r"volg\s+(?:\w+\s+){0,3}?niet|overschrijf|annuleer|verwerp|laat\s+(?:\w+\s+){0,2}?vallen|"
                    r"sla\s+(?:\w+\s+){0,3}?over)\b",
        "rules": r"\b(?:instructies|regels|richtlijnen|aanwijzingen|beperkingen|systeem-?prompt|"
                 r"systeem-?bericht|systeem-?instructies|opdrachten|prompt|configuratie|voorschriften|"
                 r"programmering|instellingen|filters)\b",
        "reveal": r"\b(?:onthul\w*|toon|laat\s+(?:\w+\s+){0,3}?zien|print\w*|herhaal|herhalen|schrijf\w*|"
                  r"kopieer\w*|deel|geef\s+(?:\w+\s+){0,3}?(?:weer|prijs|door)|vertel\w*|noem|"
                  r"som\s+(?:\w+\s+){0,3}?op)\b",
        "prompt": r"\b(?:systeem-?prompt|systeem-?bericht|systeem-?instructies|"
                  r"(?:je|jouw|uw|jullie)\s+(?:\w+\s+)?(?:instructies|regels|prompt|configuratie|richtlijnen|"
                  r"aanwijzingen|programmering|instellingen)|(?:verborgen|geheime|oorspronkelijke|"
                  r"initi[eë]le|interne)\s+(?:instructies|regels|prompt))\b",
    },
    "ru": {
        "override": r"(?:игнорир\w*|проигнорир\w*|забудь\w*|забыть|отмен\w*|отбрось\w*|отброс\w*|"
                    r"не\s+(?:следуй|соблюдай|выполняй|подчиняйся|учитывай)|обойди|отключи\w*|наруш\w*|"
                    r"пропусти\w*|сними\w*|игнор\w*)",
        "rules": r"(?:инструкци\w*|правил\w*|указани\w*|ограничени\w*|промпт\w*|директив\w*|установк\w*|"
                 r"запрет\w*|фильтр\w*|настройк\w*|системн\w*\s+(?:сообщени\w*|подсказк\w*))",
        "reveal": r"(?:покажи\w*|раскрой\w*|выведи\w*|повтори\w*|напечатай\w*|расскажи\w*|скажи\w*|"
                  r"перечисли\w*|напиши\w*|скопируй\w*|выдай|назови|процитируй|воспроизведи|отправь)",
        "prompt": r"(?:системн\w*\s+(?:промпт\w*|сообщени\w*|подсказк\w*|инструкци\w*|настройк\w*)|"
                  r"(?:тво[иьеёй]\w*|ваш\w*|сво[иьеёй]\w*)\s+(?:\w+\s+)?(?:инструкци\w*|правил\w*|промпт\w*|"
                  r"настройк\w*|конфигураци\w*|указани\w*)|(?:скрыт\w*|секретн\w*|исходн\w*|первоначальн\w*|"
                  r"начальн\w*|внутренн\w*)\s+(?:инструкци\w*|правил\w*|промпт\w*|сообщени\w*))",
    },
    "tr": {
        "override": r"\b(?:yok\s+say\w*|yoksay\w*|unut\w*|g[öo]rmezden\s+gel\w*|atla\w*|uyma\w*|"
                    r"iptal\s+et\w*|devre\s+dışı\s+bırak\w*|çiğne\w*|dikkate\s+alma\w*|boş\s*ver\w*|"
                    r"kald[ıi]r\w*)",
        "rules": r"\b(?:talimat\w*|kural\w*|y[öo]nerge\w*|k[ıi]s[ıi]tlama\w*|sistem\s+(?:istemi\w*|mesaj[ıi]\w*|"
                 r"promptu\w*|komutu\w*|ayarlar[ıi]\w*)|prompt\w*|komut\w*|s[ıi]n[ıi]rlama\w*|direktif\w*|"
                 r"ayar\w*|filtre\w*)",
        "reveal": r"\b(?:g[öo]ster\w*|a[çc][ıi]kla\w*|yazd[ıi]r\w*|tekrarla\w*|s[öo]yle\w*|payla[şs]\w*|"
                  r"listele\w*|if[şs]a\s+et\w*|yaz\b|ver\b|anlat\w*|oku\w*)",
        "prompt": r"\b(?:sistem\s+(?:istemi\w*|mesaj[ıi]\w*|promptu\w*|komutu\w*|ayarlar[ıi]\w*|talimat\w*)|"
                  r"(?:gizli|sakl[ıi]|ilk|orijinal|[öo]nceki|dahili)\s+(?:talimat\w*|kural\w*|prompt\w*|"
                  r"istem\w*|komut\w*)|(?:senin|sizin|kendi)\s+(?:\w+\s+)?(?:talimat\w*|kural\w*|prompt\w*|"
                  r"y[öo]nerge\w*|ayar\w*)|talimatlar[ıi]n[ıi]|kurallar[ıi]n[ıi]|promptunu|istemini)",
    },
    "hi": {
        "override": r"(?:अनदेखा|नज़रअंदाज़|नजरअंदाज|नजरंदाज|भूल\s*जा\w*|भूल|छोड़\s*द\w*|छोड़|अवहेलना|उल्लंघन|"
                    r"मत\s+मान\w*|न\s+मान\w*|रद्द|हटा\w*|बंद\s+कर\w*|तोड़\w*|मत\s+फॉलो)",
        "rules": r"(?:निर्देश\w*|नियम\w*|सिस्टम\s*प्रॉम्प्ट|सिस्टम\s*संदेश|प्रॉम्प्ट|अनुदेश\w*|आदेश\w*|दिशानिर्देश\w*|"
                 r"प्रतिबंध\w*|सीमा\w*|सेटिंग\w*|प्रोग्रामिंग|हिदायत\w*|फ़िल्टर|फिल्टर)",
        "reveal": r"(?:दिखा\w*|बता\w*|प्रकट|प्रिंट|दोहरा\w*|लिख\w*|उजागर|खोल\w*|साझा\s+कर\w*|सुना\w*|छाप\w*|कॉपी)",
        "prompt": r"(?:सिस्टम\s*प्रॉम्प्ट|सिस्टम\s*संदेश|सिस्टम\s*निर्देश|(?:अपने|अपनी|अपना|तुम्हारे|तुम्हारी|आपके|आपकी)\s+"
                  r"(?:\S+\s+)?(?:निर्देश\w*|नियम\w*|प्रॉम्प्ट|सेटिंग\w*|अनुदेश\w*|प्रोग्रामिंग|कॉन्फ़िगरेशन)|"
                  r"(?:छिपे|छुपे|गुप्त|मूल|प्रारंभिक|आंतरिक)\s+(?:निर्देश\w*|नियम\w*|प्रॉम्प्ट))",
    },
    "ja": {
        "override": r"(?:無視|忘れ|従わな|従うな|無効|破棄|解除|取り消|上書き|回避|バイパス|オフに|停止|守らな|捨て)",
        "rules": r"(?:指示|命令|ルール|規則|システムプロンプト|システム\s*プロンプト|プロンプト|制限|ガイドライン|制約|"
                 r"設定|方針|システムメッセージ|初期設定|フィルタ)",
        "reveal": r"(?:表示|教えて|出力|開示|公開|見せて|繰り返|復唱|印刷|書き出|暴露|漏らし|漏洩|読み上げ|再現)",
        "prompt": r"(?:システムプロンプト|システム\s*プロンプト|システムメッセージ|初期(?:設定|指示|プロンプト)|"
                  r"(?:あなたの|君の|お前の|自分の)(?:指示|命令|ルール|規則|プロンプト|設定|制限|ガイドライン)|"
                  r"(?:隠された|秘密の|内部の|元の|最初の)(?:指示|命令|ルール|プロンプト|設定))",
    },
    "zh": {
        "override": r"(?:忽略|忽视|无视|無視|(?<!不要)(?<!不能)(?<!别)(?<!千万别)(?:忘记|忘掉|忘記)|不要遵守|不用遵守|不再遵守|不要遵循|不需遵守|不必遵守|"
                    r"绕过|繞過|覆盖|覆蓋|取消|放弃|放棄|撤销|撤銷|推翻|关闭|關閉|禁用|解除|停用|跳过|跳過|"
                    r"打破|突破|抛弃|拋棄|摆脱|擺脫)",
        "rules": r"(?:指令|指示|规则|規則|提示词|提示詞|系统提示|系統提示|系统消息|系統消息|系统信息|系統信息|"
                 r"限制|约束|約束|设定|設定|准则|準則|规定|規定|守则|守則|安全措施|过滤|過濾|指导方针|指導方針)",
        "reveal": r"(?:显示|顯示|输出|輸出|告诉我|告訴我|泄露|洩露|泄漏|打印|列印|重复|重複|复述|複述|透露|"
                  r"公开|公開|展示|列出|写出|寫出|复制|複製|说出|說出|背诵|背誦|念出)",
        "prompt": r"(?:系统提示词|系統提示詞|系统提示|系統提示|系统消息|系統消息|系统信息|系統信息|系统指令|系統指令|"
                  r"系统设定|系統設定|初始(?:指令|提示|设定|設定|提示词|提示詞)|"
                  r"(?:你的|您的|你们的|自己的)\S{0,4}?(?:指令|指示|规则|規則|提示词|提示詞|设定|設定|配置|限制|准则|準則)|"
                  r"(?:隐藏的|隱藏的|秘密的|内部的|內部的|原始的|原来的|原來的)(?:指令|指示|规则|規則|提示词|提示詞|设定|設定|提示))",
    },
    "ar": {
        "override": r"(?:تجاهل\w*|انسَ|انس\w*|تناسَ|تناس\w*|تخطَّ|تخط\w*|تجاوز\w*|أهمل\w*|اهمل\w*|"
                    r"لا\s+تتبع\w*|لا\s+تلتزم\w*|لا\s+تطع\w*|ألغ\w*|الغ\w*|عطّل\w*|عطل\w*|أوقف\w*|اوقف\w*|"
                    r"اكسر\w*|أزل\s|ازل\s|تخلَّ|تخل\s+عن)",
        "rules": r"(?:التعليمات|تعليمات\w*|القواعد|قواعد\w*|الأوامر|الاوامر|أوامر\w*|اوامر\w*|التوجيهات|"
                 r"توجيهات\w*|القيود|قيود\w*|موجه\s+النظام|موجّه\s+النظام|رسالة\s+النظام|البرومبت|برومبت\w*|"
                 r"الإرشادات|الارشادات|إرشادات\w*|ارشادات\w*|الإعدادات|الاعدادات|البرمجة|برمجت\w*|الضوابط|"
                 r"الفلاتر|المرشحات)",
        "reveal": r"(?:أظهر\w*|اظهر\w*|اطبع\w*|أطبع\w*|اكشف\w*|أكشف\w*|أعطني|اعطني|كرر\w*|أخبرني|اخبرني|"
                  r"قل\s+لي|اعرض\w*|أعرض\w*|اكتب\w*|أكتب\w*|انسخ\w*|شارك\w*|سرّب\w*|سرب\w*|أرني|ارني|"
                  r"اذكر\w*|أذكر\w*)",
        "prompt": r"(?:موجه\s+النظام|موجّه\s+النظام|رسالة\s+النظام|تعليمات\s+النظام|إعدادات\s+النظام|"
                  r"اعدادات\s+النظام|البرومبت|برومبت\w*|تعليماتك|قواعدك|أوامرك|اوامرك|توجيهاتك|إعداداتك|"
                  r"اعداداتك|برمجتك|قيودك|(?:التعليمات|القواعد|الأوامر|الاوامر)\s+(?:الخفية|السرية|الأصلية|"
                  r"الاصلية|الأولية|الاولية|الداخلية|السابقة))",
    },
}
# function words that show the clause is really in that language: "ignore" + "instructions" is also
# french or portuguese on paper, so a latin-script pair needs one of these or a non-ascii letter
_ML_MARKERS = {
    "de": r"\b(?:alle[nrsm]?|deine[nrsm]?|ihre[nrsm]?|eure[nrsm]?|dein|ihr|euer|die|der|das|den|dem|des|und|"
          r"nicht|mir|mich|dir|dich|jetzt|bitte|vorherige[nrs]?|bisherige[nrs]?|sämtliche[nrs]?|sofort|"
          r"eine[nrsm]?|ein|zu|auf|mit|du|es|ist|sind|dass|nur|auch|oder|aus|bei|nach|über|für|wie|wenn|"
          r"dann|noch|schon|hier|diese[nrsm]?|dieses|jede[nrsm]?|keine[nrsm]?|ich|wir|uns|euch|sie|alles|"
          r"nichts|mal|doch|ab\s+(?:jetzt|sofort)|von\s+(?:nun|jetzt)\s+an)\b",
    "es": r"\b(?:todas?|todos?|las|los|el|tus?|sus?|vuestr[ao]s?|anteriores?|previ[ao]s?|ahora|por\s+favor|"
          r"del|que|no|mi|mis|est[eao]s?|es[eao]s?|con|para|desde|un|una|unos|unas|ya|también|tambien|sin|"
          r"sobre|al|son|lo|les|dime|dame|hazlo|inmediatamente|solo|sólo|muy|más|mas|pero|porque|cuando|"
          r"donde|como|cómo|qué|quién|nada|todo|siempre|nunca|hoy|a\s+partir\s+de\s+ahora)\b",
    "fr": r"\b(?:toutes?|tous|les|des|tes|ton|ta|vos|votre|ses|sa|précédentes?|precedentes?|antérieures?|"
          r"anterieures?|et|maintenant|s'il\s+(?:te|vous)\s+pla[iî]t|stp|svp|du|au|aux|ce|cette|ces|dans|"
          r"pour|avec|sur|ne|pas|moi|une|que|qui|est|sont|ça|cela|aussi|à|il|elle|vous|tu|je|nous|ils|"
          r"elles|d'|l'|qu'|c'est|n'|j'|t'|immédiatement|tout\s+de\s+suite|désormais)\b",
    "it": r"\b(?:tutte?|tutti|gli|il|lo|tue|tuo|tua|tuoi|vostr[ei]|sue|suo|sua|suoi|precedenti|precedente|ora|"
          r"adesso|per\s+favore|del|della|dei|delle|degli|dello|di|che|mi|mio|mia|miei|mie|quest[oaie]|"
          r"quell[oaie]|con|una|uno|anche|senza|sul|sulla|sui|sulle|nel|nella|nei|nelle|dal|dalla|è|sono|ti|"
          r"ci|subito|ogni|qualsiasi|niente|nulla|tutto|sempre|mai|d'ora\s+in\s+poi|ed|ma|perché|perche|"
          r"quando|dove|come|cosa|chi|dimmi|dammi)\b",
    "pt": r"\b(?:todas?|todos?|tuas?|teus?|suas?|seus?|anteriores?|prévias?|previas?|agora|por\s+favor|dos|"
          r"das|não|nao|meu|minha|meus|minhas|est[ea]s?|ess[ea]s?|isso|isto|para|uma|também|tambem|sem|"
          r"sobre|ao|aos|é|são|sao|lhe|você|voce|vocês|voces|tu|já|ja|depois|antes|apenas|só|nunca|sempre|"
          r"tudo|nada|imediatamente|a\s+partir\s+de\s+agora|qual|quais|quando|onde|como|porque|mas|que)\b",
    "nl": r"\b(?:alle|je|jouw|uw|jullie|jij|het|een|niet|nu|alsjeblieft|alstublieft|aub|vorige|eerdere|eerste|"
          r"oorspronkelijke|op|dat|dit|deze|voor|naar|ook|maar|om|te|hier|daar|mij|ik|wij|zij|ze|zijn|wordt|"
          r"worden|geen|meer|nog|als|wat|alles|niets|altijd|nooit|meteen|onmiddellijk|vanaf\s+nu|hem|haar|"
          r"hun|ons|onze|mijn|dus|toch|gewoon)\b",
    "tr": r"\b(?:tüm|tum|bütün|butun|önceki|onceki|ve|şimdi|simdi|lütfen|lutfen|bana|beni|senin|sizin|kendi|"
          r"bu|şu|bir|için|icin|ile|ama|fakat|veya|çok|cok|daha|hiç|hic|sonra|önce|artık|artik|hemen|bundan|"
          r"böyle|boyle|şunu|bunu|onu|sana|size|bize|değil|degil|yok|nasıl|nasil|neden|niçin|hangi|hepsini|"
          r"hepsi|tamamen|derhal|asla|yine|sadece|yalnızca|yalnizca)\b",
}
MULTILINGUAL_OVERRIDE = [
    (lang, re.compile(p[verb]), re.compile(p[obj]), re.compile(_ML_MARKERS[lang]) if lang in _ML_MARKERS else None)
    for lang, p in _ML.items() for verb, obj in (("override", "rules"), ("reveal", "prompt"))
]
NON_ASCII_LETTER_RE = re.compile(r"[^\x00-\x7f\W\d_]")
# the english rules already cover english clauses; keep them out of this one
ENGLISH_CLAUSE_RE = re.compile(
    r"\b(?:the|and|you|your|this|that|with|from|have|are|for|not|all|any|previous|above|"
    r"please|instructions?|rules)\b"
)


def multilingual_override_count(views):
    """Clauses in another language that tell the assistant to drop or reveal its instructions."""
    hits = []
    for clause in _clauses(views.norm):
        if (len(ENGLISH_CLAUSE_RE.findall(clause)) >= 3 or _count("override_phrase_count", clause)[0]
                or _count("exfiltration_count", clause)[0]):
            continue
        foreign = NON_ASCII_LETTER_RE.search(clause)
        for lang, verb, obj, marker in MULTILINGUAL_OVERRIDE:
            if not (verb.search(clause) and obj.search(clause)):
                continue
            if marker and not (foreign or marker.search(clause)):
                continue
            hits.append(f"[{lang}] {_snip(clause)}")
            break
    return len(hits), hits


# --- an injected change of task

_TASK = r"(?:task|job|assignment|request|question|work|mission)"
_TASK_VERB = (r"(?:summari[sz]ing|translating|answering|replying|responding|analy[sz]ing|reviewing|"
              r"classifying|proofreading|editing|rewriting|paraphrasing|completing|following|continuing|"
              r"processing|describing|extracting|explaining|evaluating|grading|labeling|labelling|"
              r"categori[sz]ing|transcribing|correcting|checking|rating|scoring|converting|formatting|"
              r"doing\s+(?:what|that|this))")
_ORDER_AFTER = (r"(?:please\s+|just\s+|simply\s+|now\s+|you\s+(?:must|should|will|need\s+to|have\s+to)\s+|"
                r"i\s+want\s+you\s+to\s+)?(?:write|say|reply|respond|answer|output|print|tell|give|return|"
                r"translate|generate|produce|do|explain|list|repeat|create|ignore|follow|provide|send|"
                r"describe|compose|start|begin|act|pretend|reveal|show|insert|include|add)\b")
_PIVOT_DROP = (r"\b(?:ignore|forget|disregard|drop|abandon|skip|cancel|stop|discard|dismiss|set\s+aside|"
               r"throw\s+out)")
_PIVOT_DET = r"(?:that|this|the|your|whatever|any|all)"
_PIVOT_QUALIFIER = r"(?:previous|original|earlier|current|first|initial|above|prior|assigned|last|old|actual|real)"
# an order that replaces the task: assistant work, not "and refund the customer"
_REPLACEMENT = (r"(?:please\s+|just\s+|simply\s+|now\s+|you\s+(?:must|should|will|need\s+to|have\s+to)\s+|"
                r"i\s+want\s+you\s+to\s+)?(?:write|say|reply|respond|answer|output|print|tell\s+me|return|"
                r"translate|generate|produce|explain|list|repeat|create|ignore|describe|compose|pretend|"
                r"reveal|show\s+me|act|insert|include|start|begin|obey)\b")
TASK_PIVOT_PATTERNS = [
    r"\bnew\s+(?:task|assignment|job|mission)\s*(?::|,?\s+(?:which|that)\s+(?:replaces|supersedes|overrides|"
    r"cancels|takes\s+the\s+place)\b)",
    r"\b(?:actually|ok|okay|wait|hold\s+on|never\s*mind|nevermind|hmm|no|oh|update|correction|edit),?\s+"
    r"(?:scratch|forget|ignore|drop|cancel|disregard|skip|discard)\s+(?:that|this|it|all\s+that|"
    r"the\s+above|everything\s+above|what\s+i\s+(?:said|asked|wrote)|the\s+(?:previous|last|original|"
    r"earlier|first)\s+" + _TASK + r")\b",
    r"\bscratch\s+(?:that|this|the\s+(?:previous|last|original|earlier)\s+" + _TASK + r")\b",
    r"\binstead\s+of\s+" + _TASK_VERB + r"\b[^.!?\n]{0,80}?[,:]?\s+" + _ORDER_AFTER,
    r"\b(?:rather\s+than|in\s+place\s+of)\s+" + _TASK_VERB + r"\b[^.!?\n]{0,60}?[,:]?\s+" + _ORDER_AFTER,
    _PIVOT_DROP + r"\s+(?:about\s+)?" + _PIVOT_DET + r"\s+(?:\w+\s+){0,2}?(?:task|assignment|mission)s?\b"
    r"(?:\s+(?:you\s+(?:were|have\s+been|had\s+been|got|received)\s+(?:given|assigned|asked|"
    r"told|set)|above|before|earlier|entirely|completely|for\s+now))?",
    # "the request" alone is a ticket; it is a pivot with a qualifier or a replacement order
    _PIVOT_DROP + r"\s+(?:about\s+)?" + _PIVOT_DET + r"\s+(?:(?:\w+\s+)?" + _PIVOT_QUALIFIER
    + r"\s+(?:job|request|question|work)s?\b|(?:\w+\s+){0,2}?(?:job|request|question|work)s?\s+"
    r"(?:you\s+(?:were|have\s+been|had\s+been|got|received)\s+(?:given|assigned|asked|told|set)|"
    r"above|before|earlier)\b|(?:\w+\s+){0,2}?(?:job|request|question|work)s?\s*[,;:-]?\s*(?:and\s+)?"
    r"(?:now\s+)?" + _REPLACEMENT + r")",
    r"\bforget\s+(?:about\s+)?(?:what|whatever|everything)\s+you\s+were\s+(?:asked|told|assigned|"
    r"doing|supposed|going)\b",
    r"\b(?:stop|cease|quit|halt)\s+(?:what\s+you(?:'re|\s+are)\s+doing|what\s+you\s+(?:were|have\s+been|"
    r"had\s+been)\s+(?:asked|told|assigned|supposed)\s+to\s+do|" + _TASK_VERB + r"|the\s+"
    r"(?:current|previous|original|assigned)\s+" + _TASK + r")\b[^.!?\n]{0,40}?(?:\band\b|\.|,|;|:|$)",
    r"\b(?:your|the)\s+(?:real|actual|true|new|updated|revised|correct|changed)\s+"
    + _TASK + r"\s+(?:is|will\s+be|has\s+(?:now\s+)?(?:become|changed))\b",
    r"\b(?:the|your)\s+" + _TASK + r"\s+(?:has|have)\s+(?:now\s+)?(?:changed|been\s+(?:changed|updated|"
    r"replaced|cancelled|canceled|revoked|withdrawn|superseded))\b",
    r"\b(?:change|switch)\s+of\s+(?:plans?|task|tasks|assignment)\s*:",
    r"\b(?:do\s+not|don't|dont|do\s+no\s+longer|no\s+longer)\s+(?:summari[sz]e|translate|answer|reply|"
    r"respond|analy[sz]e|review|classify|proofread|edit|rewrite|complete|follow|continue|process|"
    r"describe|extract|evaluate|grade|label|rate|score|convert|format|transcribe|correct|check)\b"
    r"[^.!?\n]{0,50}?\b(?:instead|rather)\b",
    r"\b(?:don't|do\s+not|never\s+mind)\s+(?:bother\s+)?(?:with\s+)?(?:the\s+)?(?:summary|"
    r"translation|answer|review|analysis|original\s+" + _TASK + r"|previous\s+" + _TASK + r")\b"
    r"[^.!?\n]{0,40}?\b(?:instead|rather|just|only)\b",
    r"\b(?:this|that|the)\s+(?:above\s+|previous\s+|earlier\s+|original\s+)?" + _TASK
    + r"\s+(?:is|was)\s+(?:a\s+)?(?:test|decoy|distraction|fake|not\s+real|cancelled|canceled|void|"
    r"no\s+longer\s+(?:needed|valid|relevant|required))\b",
    r"\bnever\s+mind\s+(?:the|that|this|what)\b[^.!?\n]{0,40}?,?\s+" + _ORDER_AFTER,
    r"\b(?:forget|ignore|skip|drop)\s+(?:that|this|it|the\s+above)\s*[,;:-]+\s*" + _ORDER_AFTER,
    # german
    r"\bneue\s+(?:aufgabe|anweisung|aufgabenstellung|instruktion)\s*:",
    r"\b(?:vergiss|vergesst|vergessen\s+sie|ignorier\w*|verwirf|brich\w*|lass|lassen\s+sie|streich\w*)"
    r"\s+(?:die|deine|ihre|eure|diese|jede|alle)\s+(?:vorherige\w*|bisherige\w*|eigentliche\w*|"
    r"ursprüngliche\w*|erste\w*|obige\w*|alte\w*|frühere\w*|gestellte\w*|zugewiesene\w*|aktuelle\w*)?"
    r"\s*(?:aufgabe\w*|auftrag|auftrag\w*|anfrage|arbeit|aufgabenstellung)\b",
    r"\b(?:an)?statt\s+(?:zu\s+)?(?:zusammenzufassen|zu\s+übersetzen|zu\s+beantworten|zu\s+antworten|"
    r"zu\s+analysieren|zu\s+korrigieren|zu\s+bewerten|zu\s+übersetzten|zu\s+prüfen|zu\s+überprüfen|"
    r"der\s+zusammenfassung|der\s+übersetzung|einer\s+zusammenfassung|einer\s+übersetzung|"
    r"einer\s+antwort|der\s+antwort)\b",
    r"\b(?:deine|ihre|eure|die)\s+(?:eigentliche|neue|wahre|wirkliche|einzige|richtige|aktuelle|geänderte)"
    r"\s+(?:aufgabe|anweisung|aufgabenstellung|mission|arbeit)\s+(?:ist|lautet|besteht|wird)\b",
    r"\b(?:die|deine|ihre)\s+(?:aufgabe|anweisung|aufgabenstellung)\s+(?:hat\s+sich\s+geändert|wurde\s+"
    r"(?:geändert|ersetzt|aufgehoben|zurückgezogen|storniert))\b",
    r"\b(?:vergiss|ignorier\w*|lass)\s+(?:das|es|dies|alles)\s*[,;:-]?\s*(?:und\s+)?(?:schreib\w*|"
    r"sag\w*|antworte|gib|erstell\w*|übersetz\w*|erzähl\w*|nenn\w*|beschreib\w*|mach\w*|stattdessen)\b",
    r"\bplanänderung\s*[:,!.]|\bkurswechsel\s*[:,!.]",
    # spanish
    r"\bnueva\s+(?:tarea|instrucción|instruccion|misión|mision|asignación|asignacion|orden)\s*:",
    r"\b(?:olvida|olvide|olvídate\s+de|olvidate\s+de|ignora|ignore|descarta|cancela|abandona|deja|"
    r"omite|salta)\s+(?:la|tu|su|esa|esta|cualquier|toda|todas?\s+las?)\s+(?:tarea\w*|trabajo|"
    r"petición|peticion|solicitud|encargo|instrucción\s+anterior|instruccion\s+anterior|"
    r"pregunta\s+anterior|asignación|asignacion)\b",
    r"\ben\s+(?:lugar|vez)\s+de\s+(?:resumir|traducir|responder|contestar|analizar|revisar|corregir|"
    r"evaluar|clasificar|completar|seguir|continuar|procesar|describir|explicar|hacer\s+(?:eso|esto|"
    r"lo\s+que)|la\s+traducción|la\s+traduccion|el\s+resumen|la\s+respuesta)\b",
    r"\b(?:tu|su|la)\s+(?:verdadera|nueva|única|unica|real|auténtica|autentica|actual|principal)\s+"
    r"(?:tarea|misión|mision|instrucción|instruccion|trabajo|objetivo)\s+(?:es|será|sera|consiste)\b",
    r"\b(?:la|tu)\s+(?:tarea|misión|mision|instrucción|instruccion)\s+(?:ha\s+cambiado|fue\s+cambiada|"
    r"queda\s+(?:cancelada|anulada)|ha\s+sido\s+(?:cambiada|cancelada|reemplazada|anulada))\b",
    r"\b(?:olvida|olvídalo|olvidalo|ignora|deja)\s+(?:eso|esto|lo\s+anterior|todo)\s*[,;:-]?\s*(?:y\s+)?"
    r"(?:en\s+su\s+lugar|mejor|ahora|escribe|responde|di|dime|traduce|cuéntame|cuentame|dame|haz|"
    r"describe|explica|genera|crea)\b",
    r"\bcambio\s+de\s+planes\s*[:,!.]",
]
TASK_PIVOT_RE = re.compile("|".join(f"(?:{p})" for p in TASK_PIVOT_PATTERNS), re.M)
# "instead of summarizing each chapter, I decided to..." is an account, not a pivot
PIVOT_ACCOUNT_RE = re.compile(
    r"\b(?:i|we|he|she|they)\s+(?:decided|chose|opted|ended\s+up|prefer|preferred|started|began|"
    r"tried|used|usually|often|always|tend|went|did|do|would|could|should|will|can|have|had|"
    r"was|were|am|are)\b|\bi'(?:ve|d|ll|m)\b|\bwe'(?:ve|d|ll|re)\b"
)


PIVOT_CONTINUATION_RE = re.compile(r"^\s*(?:instead|rather|but\s+instead|in\s+its\s+place)\b")
QUOTED_RE = re.compile(r"[\"'“‘][^\"'”’\n]{1,80}[\"'”’]")


def task_pivot_count(views):
    """Clauses that cancel or replace the task the assistant was given."""
    hits, clauses = [], _clauses(views.norm)
    for i, clause in enumerate(clauses):
        # "do not summarize this; instead, ..." spans two clauses
        if i + 1 < len(clauses) and PIVOT_CONTINUATION_RE.match(clauses[i + 1]):
            clause = f"{clause} {clauses[i + 1]}"
        if not TASK_PIVOT_RE.search(clause):
            continue
        unquoted = QUOTED_RE.sub(" ", clause)
        if _is_question(clause) or PIVOT_ACCOUNT_RE.search(unquoted):
            continue
        hits.append(_snip(clause))
    return len(hits), hits


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
    "dangerous_action_count": dangerous_action_count,
    "tool_action_count": tool_action_count,
    "multilingual_override_count": multilingual_override_count,
    "task_pivot_count": task_pivot_count,
}
RULE_NAMES = list(RULES)

# always non-zero, so they describe the text rather than "fire"
DESCRIPTIVE_RULES = {"log_text_length", "special_char_ratio", "uppercase_ratio"}


def analyze(text):
    """All rules for one text: {name: (value, snippets)}."""
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
