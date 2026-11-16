"""Local bilingual (Hebrew/English) intent parser. Deterministic, runs on-server, no data leaves."""
from __future__ import annotations

import re
from dataclasses import dataclass, field

from ..knowledge.catalog import PROCESSES, REQUEST_ALIASES

HEB = r"֐-׿"
_PREFIX = "(?:[והבלמשכ]{1,2})?"  # Hebrew attached prepositions/conjunctions: ו, ה, ב, ל, מ, ש, כ


@dataclass
class Intent:
    lang: str
    doc_types: list[str] = field(default_factory=list)
    process_key: str | None = None
    custom_purpose: str | None = None
    is_task: bool = False
    wants_again: bool = False
    yes: bool = False
    no: bool = False
    nothing_more: bool = False
    adding: bool = False
    greeting: bool = False
    find_only: bool = False
    help: bool = False
    free_text: str = ""


def detect_lang(text: str, fallback: str = "he") -> str:
    heb = len(re.findall(f"[{HEB}]", text))
    lat = len(re.findall(r"[A-Za-z]", text))
    if heb == lat == 0:
        return fallback
    return "he" if heb >= lat else "en"


def _norm(text: str) -> str:
    t = text.lower().replace("״", "\"").replace("׳", "'").replace("–", "-")
    return re.sub(r"\s+", " ", t)


def _alias_regex(alias: str) -> re.Pattern:
    a = re.escape(_norm(alias))
    if re.search(f"[{HEB}]", alias):
        return re.compile(f"(?<![{HEB}\\w]){_PREFIX}{a}(?![{HEB}])")
    return re.compile(f"(?<![\\w]){a}(?![\\w])")


_ALIAS_TABLE = sorted(((a, dt, _alias_regex(a)) for dt, aliases in REQUEST_ALIASES.items() for a in aliases),
                      key=lambda x: -len(x[0]))
_PROC_TABLE = sorted(((t, pk, _alias_regex(t)) for pk, p in PROCESSES.items() for t in p["triggers"]),
                     key=lambda x: -len(x[0]))

_TASK_PATTERNS = [
    re.compile(r"\b(?:documents?|docs|paperwork|everything|what(?:'s| is) needed)\b.*?\bfor\b\s+(?:my |a |an |the |another |this )?(.+)", re.I),
    re.compile(r"\bprepare\b\s+(?:everything|all|documents?)?.*?\bfor\b\s+(?:my |a |an |the |another |this )?(.+)", re.I),
    re.compile(r"\b(?:submit|apply for|applying for|application for)\b\s+(?:my |a |an |the |another )?(.+)", re.I),
    re.compile(f"מסמכים\\s+(?:עבור|בשביל|ל|ל־|ל-)\\s*([{HEB}\\w\\s\"'-]+)"),
    re.compile(f"(?:להגיש|להגשת|הגשת|הגשה של|הגשה ל)\\s*([{HEB}\\w\\s\"'-]+)"),
    re.compile(f"(?:תכין|תכיני|הכן|להכין)\\s+(?:לי\\s+)?(?:את\\s+)?(?:כל\\s+)?(?:מה ש|המסמכים\\s+)?(?:צריך\\s+)?(?:עבור|בשביל|ל)\\s*([{HEB}\\w\\s\"'-]+)"),
]
_AGAIN = re.compile(r"\b(another|again|new|next|once more)\b|נוספת|נוסף|שוב|עוד פעם|חדשה|הבאה", re.I)
_YES = re.compile(r"^\s*(yes|yep|yeah|sure|ok|okay|please do|do it|confirm|correct|כן|בטח|אישור|מאשר|מאשרת|נכון|סבבה|יאללה|תשמור|שמור)\b", re.I)
_NO = re.compile(r"^\s*(no|nope|not now|don't|do not|לא|לא תודה|אל תשמור|לא עכשיו)\b", re.I)
_NOTHING_MORE = re.compile(r"\b(that'?s all|nothing else|no more|that is all|nothing)\b|זה הכל|זהו|אין עוד|לא צריך עוד|שום דבר", re.I)
_ADDING = re.compile(r"\b(also|add|plus|another document|in addition)\b|גם|בנוסף|תוסיף|תוסיפי|להוסיף|ועוד", re.I)
_FIND = re.compile(r"^\s*(?:please\s+)?(find|search|where(?:'s| is)|show me|locate)\b|^\s*(תמצא|תמצאי|מצא|חפש|תחפש|תחפשי|איפה|תראה לי|תראי לי)", re.I)
_GREETING = re.compile(r"^\s*(hi|hello|hey|good (?:morning|evening)|שלום|היי|הי|בוקר טוב|ערב טוב)\W*$", re.I)
_HELP = re.compile(r"\b(help|what can you do|how does this work)\b|עזרה|מה אתה יודע|מה את יודעת|איך זה עובד", re.I)


def parse(text: str, fallback_lang: str = "he") -> Intent:
    lang = detect_lang(text, fallback_lang)
    norm = _norm(text)
    it = Intent(lang=lang, free_text=text.strip())
    masked = norm
    for alias, pk, rx in _PROC_TABLE:
        m = rx.search(masked)
        if m:
            it.process_key = pk
            masked = masked[:m.start()] + " " * (m.end() - m.start()) + masked[m.end():]
            break
    found: list[tuple[int, str]] = []
    for alias, dt, rx in _ALIAS_TABLE:
        for m in rx.finditer(masked):
            found.append((m.start(), dt))
            masked = masked[:m.start()] + " " * (m.end() - m.start()) + masked[m.end():]
    seen = set()
    for _, dt in sorted(found):
        if dt not in seen:
            seen.add(dt)
            it.doc_types.append(dt)
    if not it.process_key:
        for rx in _TASK_PATTERNS:
            m = rx.search(text)
            if m:
                purpose = re.sub(r"[.?!,]+$", "", m.group(1).strip())
                purpose = re.split(r"\s+(?:and|ו)?(?:please|בבקשה)\b", purpose)[0].strip()
                if 2 <= len(purpose) <= 80 and not _is_only_doc_names(purpose):
                    it.custom_purpose = purpose
                    break
    it.is_task = bool(it.process_key or it.custom_purpose)
    it.wants_again = bool(_AGAIN.search(text))
    it.yes = bool(_YES.search(text))
    it.no = bool(_NO.search(text)) and not it.yes
    it.nothing_more = bool(_NOTHING_MORE.search(text))
    it.adding = bool(_ADDING.search(text))
    it.greeting = bool(_GREETING.match(text))
    it.find_only = bool(_FIND.search(text)) and not it.adding
    it.help = bool(_HELP.search(text))
    return it


def _is_only_doc_names(s: str) -> bool:
    n = _norm(s)
    for alias, _, rx in _ALIAS_TABLE:
        n = rx.sub(" ", n)
    return not re.sub(r"[\s,.&]|\band\b|\bmy\b|ו", "", n)
