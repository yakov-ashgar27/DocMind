"""Anonymised aggregate learning — architecture in place, DISABLED by default.

What may be contributed: only (canonical process key, canonical document type) pairs from a
checklist the user explicitly approved. Never: free-text names, document contents, email data,
filenames, dates, or user ids. Contributors are recorded as a keyed HMAC so a user counts once per
pair; patterns are only surfaced once K distinct contributors agree (k-anonymity).

Both the global flag (DOCMIND_SHARED_LEARNING) and the per-user opt-in must be on.
"""
from __future__ import annotations

import json

from ..knowledge.catalog import DOC_TYPES, PROCESSES
from ..security.crypto import hmac_hex

K_ANONYMITY = 20


def _opted_in(ctx, user) -> bool:
    if not ctx.config.shared_learning_enabled:
        return False
    return bool(json.loads(user.get("settings_json") or "{}").get("shared_learning_opt_in"))


def contribute(ctx, user, process_key: str, doc_types: list[str | None]) -> int:
    if process_key not in PROCESSES or not _opted_in(ctx, user):
        return 0
    contributor = hmac_hex(ctx.config.jwt_secret, f"shared:{user['id']}")
    added = 0
    for dt in {d for d in doc_types if d in DOC_TYPES}:
        cur = ctx.db.execute("INSERT OR IGNORE INTO shared_contributions VALUES (?, ?, ?)", (contributor, process_key, dt))
        if cur.rowcount:
            ctx.db.execute("INSERT INTO shared_patterns VALUES (?, ?, 1) ON CONFLICT(process_key, doc_type) "
                           "DO UPDATE SET contributors = contributors + 1", (process_key, dt))
            added += 1
    return added


def suggestions(ctx, process_key: str) -> list[str]:
    if not ctx.config.shared_learning_enabled or process_key not in PROCESSES:
        return []
    return [r["doc_type"] for r in ctx.db.all(
        "SELECT doc_type FROM shared_patterns WHERE process_key = ? AND contributors >= ? ORDER BY contributors DESC",
        (process_key, K_ANONYMITY))]
