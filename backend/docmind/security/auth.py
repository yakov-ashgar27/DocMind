"""Authentication: short-lived JWT access tokens + rotating refresh tokens (httpOnly cookie)."""
from __future__ import annotations

import re
import secrets
import time
from datetime import datetime, timedelta, timezone
from functools import wraps

import jwt
from flask import current_app, g, jsonify, request

from ..db import new_id, now_iso
from . import crypto

EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
REFRESH_COOKIE = "dm_refresh"


class AuthError(Exception):
    def __init__(self, message: str, status: int = 401):
        super().__init__(message)
        self.status = status


def validate_password(pw: str) -> None:
    if len(pw) < 10:
        raise AuthError("password_too_short", 400)
    if pw.lower() == pw or not re.search(r"\d", pw):
        raise AuthError("password_too_weak", 400)


def register_user(ctx, email: str, password: str, display_name: str, locale: str = "he") -> dict:
    email = (email or "").strip().lower()
    if not EMAIL_RE.match(email):
        raise AuthError("invalid_email", 400)
    validate_password(password or "")
    if ctx.db.one("SELECT id FROM users WHERE email = ?", (email,)):
        raise AuthError("email_taken", 409)
    uid = new_id()
    dek = crypto.new_key()
    ctx.db.insert("users", {
        "id": uid, "email": email, "password_hash": crypto.hash_password(password),
        "display_name": (display_name or email.split("@")[0])[:80],
        "locale": locale if locale in ("he", "en") else "he",
        "wrapped_dek": crypto.wrap_key(ctx.config.master_key, dek, f"user:{uid}"),
        "settings_json": "{}", "created_at": now_iso(),
    })
    return ctx.db.one("SELECT * FROM users WHERE id = ?", (uid,))


def authenticate(ctx, email: str, password: str) -> dict:
    user = ctx.db.one("SELECT * FROM users WHERE email = ?", ((email or "").strip().lower(),))
    if not user:
        crypto.hash_password("timing-equaliser")  # don't leak which emails exist via timing
        raise AuthError("invalid_credentials")
    if not crypto.verify_password(password or "", user["password_hash"]):
        raise AuthError("invalid_credentials")
    return user


def issue_access_token(ctx, user: dict) -> str:
    now = int(time.time())
    payload = {"sub": user["id"], "tv": user["token_version"], "iat": now,
               "exp": now + ctx.config.access_token_ttl, "typ": "access"}
    return jwt.encode(payload, ctx.config.jwt_secret, algorithm="HS256")


def issue_refresh_token(ctx, user: dict) -> str:
    raw = secrets.token_urlsafe(48)
    exp = datetime.now(timezone.utc) + timedelta(seconds=ctx.config.refresh_token_ttl)
    ctx.db.insert("refresh_tokens", {
        "id": new_id(), "user_id": user["id"], "token_hash": crypto.sha256_hex(raw.encode()),
        "user_agent": (request.headers.get("User-Agent") or "")[:200],
        "created_at": now_iso(), "expires_at": exp.replace(microsecond=0).isoformat(), "revoked_at": None,
    })
    return raw


def rotate_refresh_token(ctx, raw: str) -> tuple[dict, str]:
    row = ctx.db.one("SELECT * FROM refresh_tokens WHERE token_hash = ?", (crypto.sha256_hex(raw.encode()),))
    if not row:
        raise AuthError("invalid_refresh")
    if row["revoked_at"]:
        # Reuse of a rotated token = likely theft: revoke every session of this user.
        revoke_all_sessions(ctx, row["user_id"])
        raise AuthError("refresh_reused")
    if row["expires_at"] < now_iso():
        raise AuthError("refresh_expired")
    ctx.db.execute("UPDATE refresh_tokens SET revoked_at = ? WHERE id = ?", (now_iso(), row["id"]))
    user = ctx.db.one("SELECT * FROM users WHERE id = ?", (row["user_id"],))
    if not user:
        raise AuthError("invalid_refresh")
    return user, issue_refresh_token(ctx, user)


def revoke_refresh_token(ctx, raw: str | None) -> None:
    if raw:
        ctx.db.execute("UPDATE refresh_tokens SET revoked_at = ? WHERE token_hash = ? AND revoked_at IS NULL",
                       (now_iso(), crypto.sha256_hex(raw.encode())))


def revoke_all_sessions(ctx, user_id: str) -> None:
    ctx.db.execute("UPDATE refresh_tokens SET revoked_at = ? WHERE user_id = ? AND revoked_at IS NULL",
                   (now_iso(), user_id))
    ctx.db.execute("UPDATE users SET token_version = token_version + 1 WHERE id = ?", (user_id,))


def user_dek(ctx, user: dict) -> bytes:
    return crypto.unwrap_key(ctx.config.master_key, user["wrapped_dek"], f"user:{user['id']}")


def require_auth(fn):
    @wraps(fn)
    def wrapper(*args, **kwargs):
        ctx = current_app.extensions["docmind"]
        header = request.headers.get("Authorization", "")
        if not header.startswith("Bearer "):
            return jsonify(error="unauthorized"), 401
        try:
            payload = jwt.decode(header[7:], ctx.config.jwt_secret, algorithms=["HS256"],
                                 options={"require": ["exp", "sub"]})
        except jwt.PyJWTError:
            return jsonify(error="unauthorized"), 401
        if payload.get("typ") != "access":
            return jsonify(error="unauthorized"), 401
        user = ctx.db.one("SELECT * FROM users WHERE id = ?", (payload["sub"],))
        if not user or user["token_version"] != payload.get("tv"):
            return jsonify(error="unauthorized"), 401
        g.user = user
        g.dek = user_dek(ctx, user)
        return fn(*args, **kwargs)
    return wrapper
