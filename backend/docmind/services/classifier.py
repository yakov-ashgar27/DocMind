"""Document understanding: type classification, issuer, dates, expiry, outdated detection.

Two layers:
1. Knowledge-based scorer (weighted bilingual keywords on content + filename hints + structural
   signals such as a valid Israeli ID check digit, IBAN, passport MRZ).
2. Personal layer: documents the user has manually (re)labelled act as nearest-neighbour examples,
   so the classifier adapts to each user's own documents over time.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date, datetime

from ..knowledge.catalog import DOC_TYPES, KNOWN_ISSUERS


@dataclass
class Classification:
    doc_type: str
    confidence: float
    category: str
    issuer: str | None = None
    doc_date: str | None = None
    expiry_date: str | None = None
    signals: list[str] = field(default_factory=list)


def _norm(s: str) -> str:
    s = s.lower()
    s = s.replace("״", "\"").replace("׳", "'").replace("”", "\"").replace("“", "\"")
    return re.sub(r"\s+", " ", s)


def valid_israeli_id(num: str) -> bool:
    if not num.isdigit() or len(num) > 9 or set(num) == {"0"}:
        return False
    num = num.zfill(9)
    total = 0
    for i, ch in enumerate(num):
        d = int(ch) * (1 + i % 2)
        total += d - 9 if d > 9 else d
    return total % 10 == 0


def _structural_signals(text: str) -> dict[str, float]:
    out: dict[str, float] = {}
    if re.search(r"P<ISR|P<[A-Z]{3}[A-Z<]{5,}", text):
        out["passport"] = 8
    if re.search(r"\bIL\d{2}\s?(?:\d{4}\s?){4}\d{3}\b", text):
        out["bank_confirmation"] = 1.5
    for m in re.finditer(r"(?<!\d)(\d{9})(?!\d)", text):
        if valid_israeli_id(m.group(1)):
            out["id_card"] = out.get("id_card", 0) + 1.0
            out["id_appendix"] = out.get("id_appendix", 0) + 0.5
            break
    return out


def score_types(text: str, filename: str) -> dict[str, float]:
    t = _norm(text)
    fn = _norm(filename)
    scores: dict[str, float] = {}
    for key, spec in DOC_TYPES.items():
        s = 0.0
        for kw, w in spec["kw"].items():
            kwn = _norm(kw)
            if re.fullmatch(r"[a-z0-9' \-/<.]+", kwn):
                hits = len(re.findall(r"(?<![a-z])" + re.escape(kwn) + r"(?![a-z])", t))
            else:
                hits = t.count(kwn)
            if hits:
                s += w * (1 + 0.25 * min(hits - 1, 4))  # diminishing returns for repetition
        for hint in spec["fn"]:
            if hint in fn:
                s += 3
                break
        if s:
            scores[key] = s
    for k, v in _structural_signals(text).items():
        scores[k] = scores.get(k, 0) + v
    # Disambiguation: "appendix" docs also mention ID words; ID card docs rarely say "ספח".
    if scores.get("id_appendix", 0) >= 5 and "id_card" in scores:
        scores["id_card"] *= 0.6
    # A reserve *order* talks about reporting for duty; a confirmation talks about days served.
    if "reserve_order" in scores and "reserve_service_confirmation" in scores:
        if any(k in t for k in ("ימי מילואים", "3010", "days of reserve")):
            scores["reserve_order"] *= 0.5
        elif any(k in t for k in ("להתייצב", "report for duty", "צו 8")):
            scores["reserve_service_confirmation"] *= 0.5
    return scores


def classify(text: str, filename: str, personal_hint: tuple[str, float] | None = None) -> Classification:
    scores = score_types(text, filename)
    best, conf = "unknown", 0.0
    if scores:
        ranked = sorted(scores.items(), key=lambda kv: kv[1], reverse=True)
        best, top = ranked[0]
        second = ranked[1][1] if len(ranked) > 1 else 0
        # Confidence grows with absolute evidence and with the margin over the runner-up.
        conf = min(0.99, (1 - 2.718 ** (-top / 6)) * (0.6 + 0.4 * (top - second) / top))
        if top < 3:
            best, conf = "unknown", conf * 0.5
    if personal_hint and personal_hint[1] > max(conf, 0.55):
        best, conf = personal_hint
    category = DOC_TYPES.get(best, {}).get("cat", "other")
    dates = extract_dates(text)
    return Classification(
        doc_type=best, confidence=round(conf, 3), category=category,
        issuer=detect_issuer(text), doc_date=dates.get("doc_date"), expiry_date=dates.get("expiry_date"),
        signals=[f"{k}:{v:.1f}" for k, v in sorted(scores.items(), key=lambda kv: -kv[1])[:4]],
    )


def detect_issuer(text: str) -> str | None:
    t = _norm(text)
    best = None
    best_pos = 10 ** 9
    for pat, name in KNOWN_ISSUERS:
        p = _norm(pat)
        if re.fullmatch(r"[a-z0-9 \-']+", p):
            m = re.search(r"(?<![a-z])" + re.escape(p) + r"(?![a-z])", t)
            pos = m.start() if m else -1
        else:
            pos = t.find(p)
        if 0 <= pos < best_pos:  # letterhead usually comes first
            best, best_pos = name, pos
    return best


_DATE_PATTERNS = [
    (re.compile(r"(?<!\d)(\d{1,2})[./-](\d{1,2})[./-](\d{4})(?!\d)"), "dmy"),
    (re.compile(r"(?<!\d)(\d{4})-(\d{2})-(\d{2})(?!\d)"), "ymd"),
    (re.compile(r"(?<!\d)(\d{1,2})[./](\d{1,2})[./](\d{2})(?![\d./])"), "dmy2"),
]
_EXPIRY_WORDS = ["בתוקף עד", "תוקף עד", "תאריך פקיעה", "פג תוקף", "valid until", "valid thru", "expiry",
                 "expires", "date of expiry", "expiration"]


def _parse(m, kind) -> date | None:
    try:
        if kind == "ymd":
            y, mo, d = int(m.group(1)), int(m.group(2)), int(m.group(3))
        else:
            d, mo, y = int(m.group(1)), int(m.group(2)), int(m.group(3))
            if kind == "dmy2":
                y += 2000 if y < 70 else 1900
        if not (1950 <= y <= 2100):
            return None
        return date(y, mo, d)
    except ValueError:
        return None


def extract_dates(text: str) -> dict:
    found: list[tuple[int, date]] = []
    for rx, kind in _DATE_PATTERNS:
        for m in rx.finditer(text):
            dt = _parse(m, kind)
            if dt:
                found.append((m.start(), dt))
    if not found:
        return {}
    low = text.lower()
    expiry = None
    for word in _EXPIRY_WORDS:
        i = low.find(word)
        if i >= 0:
            after = [dt for pos, dt in found if 0 <= pos - i <= 60]
            if after:
                expiry = after[0]
                break
    today = date.today()
    # Document date = latest date not in the future and not the expiry (birth dates are early, so
    # "latest past date" is a good proxy for issue date).
    past = [dt for _, dt in found if dt <= today and dt != expiry]
    out = {}
    if past:
        out["doc_date"] = max(past).isoformat()
    if expiry:
        out["expiry_date"] = expiry.isoformat()
    return out


def freshness(doc: dict, today: date | None = None) -> dict:
    """Heuristic outdated check. Returned as a *flag with a reason*, never as a hard fact."""
    today = today or date.today()
    if doc.get("expiry_date"):
        exp = date.fromisoformat(doc["expiry_date"])
        if exp < today:
            return {"state": "expired", "reason_key": "expired_on", "date": doc["expiry_date"]}
        if (exp - today).days <= 60:
            return {"state": "expiring", "reason_key": "expires_soon", "date": doc["expiry_date"]}
    spec = DOC_TYPES.get(doc.get("doc_type") or "")
    max_age = spec.get("max_age") if spec else None
    ref = doc.get("doc_date") or (doc.get("created_at") or "")[:10]
    if max_age and ref:
        try:
            age = (today - date.fromisoformat(ref[:10])).days
        except ValueError:
            return {"state": "ok"}
        if age > max_age:
            return {"state": "maybe_outdated", "reason_key": "older_than", "days": age, "max_age": max_age}
    return {"state": "ok"}


def now_date() -> str:
    return datetime.now().date().isoformat()
