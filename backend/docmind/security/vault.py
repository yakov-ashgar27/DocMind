"""Vault: a separate PIN that protects chosen categories (identity, finance, medical by default).

While the vault is locked, documents in protected categories are hidden in every API response
(names, dates, issuers, previews, text, thumbnails, downloads, search hits). Unlocking returns a
short-lived vault token (5 minutes) that the client keeps in memory only.
Brute force: 5 wrong PINs lock the vault for 15 minutes. Setting or changing the PIN requires the
account password.
"""
from __future__ import annotations

import json
import re
import time
from datetime import datetime, timedelta, timezone

import jwt

from ..db import now_iso
from . import crypto
from .audit import audit

DEFAULT_LOCKED = ["identity", "finance", "medical"]
VAULT_TTL = 5 * 60
MAX_FAILS = 5
LOCKOUT = timedelta(minutes=15)
PIN_RE = re.compile(r"^\d{4,12}$")
HEADER = "X-Vault-Token"


class VaultError(Exception):
    def __init__(self, code: str, status: int = 400):
        super().__init__(code)
        self.code = code
        self.status = status


def settings(user) -> dict:
    return json.loads(user.get("settings_json") or "{}")


def has_pin(user) -> bool:
    return bool(user.get("vault_pin_hash"))


def locked_categories(user) -> list[str]:
    if not has_pin(user):
        return []
    return list(settings(user).get("locked_categories", DEFAULT_LOCKED))


def set_pin(ctx, user, password: str, pin: str) -> None:
    if not crypto.verify_password(password or "", user["password_hash"]):
        raise VaultError("invalid_credentials", 403)
    if not PIN_RE.match(pin or ""):
        raise VaultError("invalid_pin_format")
    if len(set(pin)) == 1 or pin in "0123456789012" or pin in "9876543210":
        raise VaultError("pin_too_simple")
    s = settings(user)
    s.setdefault("locked_categories", DEFAULT_LOCKED)
    ctx.db.execute("UPDATE users SET vault_pin_hash = ?, vault_failed = 0, vault_locked_until = NULL, settings_json = ? "
                   "WHERE id = ?", (crypto.hash_password(pin), json.dumps(s), user["id"]))
    audit(ctx, user["id"], "vault.pin_set")


def remove_pin(ctx, user, password: str) -> None:
    if not crypto.verify_password(password or "", user["password_hash"]):
        raise VaultError("invalid_credentials", 403)
    ctx.db.execute("UPDATE users SET vault_pin_hash = NULL, vault_failed = 0, vault_locked_until = NULL WHERE id = ?",
                   (user["id"],))
    audit(ctx, user["id"], "vault.pin_removed")


def set_locked_categories(ctx, user, keys: list[str]) -> list[str]:
    valid = {r["key"] for r in ctx.db.all("SELECT key FROM categories WHERE user_id IS NULL OR user_id = ?", (user["id"],))}
    keys = sorted({k for k in keys if k in valid})
    s = settings(user)
    s["locked_categories"] = keys
    ctx.db.execute("UPDATE users SET settings_json = ? WHERE id = ?", (json.dumps(s), user["id"]))
    audit(ctx, user["id"], "vault.categories", None, categories=keys)
    return keys


def unlock(ctx, user, pin: str) -> str:
    if not has_pin(user):
        raise VaultError("no_pin", 409)
    if user.get("vault_locked_until") and user["vault_locked_until"] > now_iso():
        raise VaultError("vault_temporarily_locked", 429)
    if not crypto.verify_password(pin or "", user["vault_pin_hash"]):
        fails = (user.get("vault_failed") or 0) + 1
        until = None
        if fails >= MAX_FAILS:
            until = (datetime.now(timezone.utc) + LOCKOUT).replace(microsecond=0).isoformat()
            fails = 0
        ctx.db.execute("UPDATE users SET vault_failed = ?, vault_locked_until = ? WHERE id = ?", (fails, until, user["id"]))
        audit(ctx, user["id"], "vault.unlock_failed", None, locked_out=bool(until))
        raise VaultError("vault_temporarily_locked" if until else "invalid_pin", 429 if until else 403)
    ctx.db.execute("UPDATE users SET vault_failed = 0, vault_locked_until = NULL WHERE id = ?", (user["id"],))
    audit(ctx, user["id"], "vault.unlock")
    now = int(time.time())
    return jwt.encode({"sub": user["id"], "tv": user["token_version"], "typ": "vault", "iat": now, "exp": now + VAULT_TTL},
                      ctx.config.jwt_secret, algorithm="HS256")


def is_unlocked(ctx, user, token: str | None) -> bool:
    if not token:
        return False
    try:
        p = jwt.decode(token, ctx.config.jwt_secret, algorithms=["HS256"], options={"require": ["exp", "sub"]})
    except jwt.PyJWTError:
        return False
    return p.get("typ") == "vault" and p.get("sub") == user["id"] and p.get("tv") == user["token_version"]


def hidden_categories(ctx, user, token: str | None) -> set[str]:
    """Categories whose documents must be hidden for this request."""
    cats = locked_categories(user)
    if not cats or is_unlocked(ctx, user, token):
        return set()
    return set(cats)


_KEEP = ("id", "category_key", "doc_type", "status", "source_kind", "is_local", "mime_type", "archived")


def redact(obj, hidden: set[str]):
    """Walk any JSON structure and replace protected documents with a locked placeholder."""
    if isinstance(obj, list):
        return [redact(x, hidden) for x in obj]
    if isinstance(obj, dict):
        if "original_filename" in obj and "category_key" in obj and obj.get("category_key") in hidden:
            return {**{k: obj.get(k) for k in _KEEP}, "locked": True, "display_name": None,
                    "original_filename": None, "tags": [], "freshness": {"state": "unknown"}}
        return {k: redact(v, hidden) for k, v in obj.items()}
    return obj


def current_hidden() -> set[str]:
    """Hidden categories for the current request (empty outside a request)."""
    try:
        from flask import g
        return set(getattr(g, "hidden_cats", set()))
    except RuntimeError:
        return set()


def ensure_visible(doc: dict | None) -> None:
    if doc and doc.get("category_key") in current_hidden():
        raise VaultError("vault_locked", 423)
