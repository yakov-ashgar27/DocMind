"""Expiry reminders. Free and private: shown in-app and exportable as a standard iCalendar (.ics) file
that any calendar (Google Calendar, Apple Calendar, Outlook) imports. No email/SMS service needed."""
from __future__ import annotations

import json
from datetime import date, datetime, timedelta, timezone

from ..knowledge.catalog import DOC_TYPES
from . import documents as docsvc

DEFAULT_LEAD_DAYS = 60
ALLOWED_LEAD_DAYS = (14, 30, 60, 90)


def lead_days(user) -> int:
    v = json.loads(user.get("settings_json") or "{}").get("reminder_days", DEFAULT_LEAD_DAYS)
    return v if v in ALLOWED_LEAD_DAYS else DEFAULT_LEAD_DAYS


def upcoming(ctx, user, today: date | None = None) -> list[dict]:
    today = today or date.today()
    horizon = today + timedelta(days=lead_days(user))
    rows = ctx.db.all("SELECT * FROM documents WHERE user_id = ? AND archived = 0 AND expiry_date IS NOT NULL "
                      "AND duplicate_of IS NULL AND expiry_date <= ? ORDER BY expiry_date", (user["id"], horizon.isoformat()))
    out = []
    for d in rows:
        exp = date.fromisoformat(d["expiry_date"])
        days = (exp - today).days
        out.append({"document": docsvc.public(d), "expiry_date": d["expiry_date"], "days_left": days,
                    "state": "expired" if days < 0 else "expiring"})
    return out


def _esc(s: str) -> str:
    return s.replace("\\", "\\\\").replace(";", "\\;").replace(",", "\\,").replace("\n", "\\n")


def _fold(line: str) -> str:
    # RFC 5545: lines longer than 75 octets are folded.
    b = line.encode("utf-8")
    if len(b) <= 75:
        return line
    parts, cur = [], b""
    for ch in line:
        e = ch.encode("utf-8")
        if len(cur) + len(e) > (75 if not parts else 74):
            parts.append(cur.decode("utf-8"))
            cur = b""
        cur += e
    parts.append(cur.decode("utf-8"))
    return "\r\n ".join(parts)


def calendar_ics(ctx, user, doc_ids: list[str] | None = None) -> bytes:
    lang = user.get("locale") or "he"
    lead = lead_days(user)
    sql = "SELECT * FROM documents WHERE user_id = ? AND archived = 0 AND expiry_date IS NOT NULL AND duplicate_of IS NULL"
    rows = ctx.db.all(sql, (user["id"],))
    if doc_ids:
        rows = [r for r in rows if r["id"] in set(doc_ids)]
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    lines = ["BEGIN:VCALENDAR", "VERSION:2.0", "PRODID:-//DocMind//Document reminders//HE", "CALSCALE:GREGORIAN",
             "METHOD:PUBLISH", "X-WR-CALNAME:DocMind"]
    for d in rows:
        exp = date.fromisoformat(d["expiry_date"])
        label = DOC_TYPES.get(d["doc_type"], {}).get(lang) or d["display_name"]
        if lang == "he":
            summary = f"לחדש: {label} (פג תוקף {exp.strftime('%d.%m.%Y')})"
            desc = f"המסמך “{d['display_name']}” פג תוקף ב-{exp.strftime('%d.%m.%Y')}. תזכורת מ-DocMind."
        else:
            summary = f"Renew: {label} (expires {exp.strftime('%d %b %Y')})"
            desc = f"“{d['display_name']}” expires on {exp.isoformat()}. Reminder from DocMind."
        start = max(exp - timedelta(days=lead), date.today())
        lines += ["BEGIN:VEVENT", f"UID:docmind-{d['id']}@docmind.local", f"DTSTAMP:{stamp}",
                  f"DTSTART;VALUE=DATE:{start.strftime('%Y%m%d')}",
                  f"DTEND;VALUE=DATE:{(start + timedelta(days=1)).strftime('%Y%m%d')}",
                  f"SUMMARY:{_esc(summary)}", f"DESCRIPTION:{_esc(desc)}", "TRANSP:TRANSPARENT",
                  "BEGIN:VALARM", "ACTION:DISPLAY", f"DESCRIPTION:{_esc(summary)}", "TRIGGER:PT9H", "END:VALARM",
                  "END:VEVENT"]
    lines.append("END:VCALENDAR")
    return ("\r\n".join(_fold(ln) for ln in lines) + "\r\n").encode("utf-8")
