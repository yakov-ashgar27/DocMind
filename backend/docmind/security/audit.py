"""Audit log for sensitive actions + a small in-memory rate limiter."""
from __future__ import annotations

import json
import threading
import time
from collections import defaultdict, deque

from flask import request

from ..db import new_id, now_iso


def audit(ctx, user_id: str | None, event: str, target: str | None = None, **meta) -> None:
    try:
        ip = request.remote_addr
        ua = (request.headers.get("User-Agent") or "")[:200]
    except RuntimeError:  # outside request context (background jobs)
        ip, ua = None, None
    ctx.db.insert("audit_log", {
        "id": new_id(), "user_id": user_id, "action": event, "target": target,
        "ip": ip, "user_agent": ua, "meta_json": json.dumps(meta, ensure_ascii=False), "created_at": now_iso(),
    })


class RateLimiter:
    """Sliding window per key. Single-process; replace with Redis when scaling horizontally."""

    def __init__(self):
        self._hits: dict[str, deque] = defaultdict(deque)
        self._lock = threading.Lock()

    def allow(self, key: str, limit: int, window_s: int) -> bool:
        now = time.monotonic()
        with self._lock:
            q = self._hits[key]
            while q and now - q[0] > window_s:
                q.popleft()
            if len(q) >= limit:
                return False
            q.append(now)
            return True
