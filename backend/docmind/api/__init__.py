"""HTTP API (JSON). See docs/API.md."""
from __future__ import annotations

import time

import jwt
from flask import Blueprint, current_app, jsonify, request

from ..connectors.google import ConnectorError
from ..security.auth import AuthError
from ..security.vault import VaultError
from ..services.bundles import BundleError
from ..services.documents import IngestError
from ..services.memory import MemoryError_

api = Blueprint("api", __name__, url_prefix="/api")


def ctx():
    return current_app.extensions["docmind"]


def body() -> dict:
    data = request.get_json(silent=True)
    return data if isinstance(data, dict) else {}


def rate_limit(bucket: str, limit: int, window: int):
    if not ctx().limiter.allow(f"{bucket}:{request.remote_addr}", limit, window):
        return jsonify(error="rate_limited"), 429
    return None


# Short-lived signed links let the browser download/preview natively (good on mobile, enables
# downloading several separate files) without putting the long-lived token in a URL.
_used_links: dict[str, float] = {}


def sign_link(user_id: str, kind: str, ref: dict, ttl: int = 120) -> str:
    now = int(time.time())
    token = jwt.encode({"sub": user_id, "typ": "dl", "k": kind, "r": ref, "iat": now, "exp": now + ttl,
                        "jti": f"{now}-{id(ref)}-{time.perf_counter_ns()}"}, ctx().config.jwt_secret, algorithm="HS256")
    return f"/api/dl/{token}"


def verify_link(token: str) -> dict:
    payload = jwt.decode(token, ctx().config.jwt_secret, algorithms=["HS256"])
    if payload.get("typ") != "dl":
        raise jwt.InvalidTokenError("wrong type")
    now = time.time()
    for k, exp in list(_used_links.items()):
        if exp < now:
            _used_links.pop(k, None)
    if payload["jti"] in _used_links:
        raise jwt.InvalidTokenError("used")
    _used_links[payload["jti"]] = payload["exp"]
    return payload


def register(app):
    from . import account, assistant, auth, bundles, connectors, documents, memory, vault  # noqa: F401
    app.register_blueprint(api)

    for exc in (IngestError, BundleError, MemoryError_, AuthError, ConnectorError, VaultError):
        app.register_error_handler(exc, lambda e: (jsonify(error=getattr(e, "code", str(e))), e.status))
