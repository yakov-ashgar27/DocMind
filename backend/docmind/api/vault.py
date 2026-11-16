from flask import g, jsonify

from ..security import vault
from ..security.auth import require_auth
from . import api, body, ctx, rate_limit


def _status(user, unlocked=None):
    return {"has_pin": vault.has_pin(user), "locked_categories": vault.locked_categories(user),
            "default_locked": vault.DEFAULT_LOCKED,
            "unlocked": not g.hidden_cats if unlocked is None else unlocked, "ttl": vault.VAULT_TTL}


def _fresh_user():
    return ctx().db.one("SELECT * FROM users WHERE id = ?", (g.user["id"],))


@api.get("/vault")
@require_auth
def vault_status():
    return jsonify(_status(g.user))


@api.post("/vault/pin")
@require_auth
def vault_set_pin():
    if (r := rate_limit(f"vaultpin:{g.user['id']}", 10, 600)):
        return r
    b = body()
    if vault.has_pin(g.user) and g.hidden_cats:
        return jsonify(error="vault_locked"), 423  # changing the PIN needs the current PIN too
    vault.set_pin(ctx(), g.user, b.get("password"), str(b.get("pin") or ""))
    return jsonify(_status(_fresh_user(), unlocked=False))


@api.delete("/vault/pin")
@require_auth
def vault_remove_pin():
    if g.hidden_cats:
        return jsonify(error="vault_locked"), 423
    vault.remove_pin(ctx(), g.user, body().get("password"))
    return jsonify(_status(_fresh_user(), unlocked=True))


@api.put("/vault/categories")
@require_auth
def vault_categories():
    if g.hidden_cats:
        return jsonify(error="vault_locked"), 423  # can't unprotect without the PIN
    keys = vault.set_locked_categories(ctx(), g.user, body().get("categories") or [])
    return jsonify({**_status(_fresh_user()), "locked_categories": keys})


@api.post("/vault/unlock")
@require_auth
def vault_unlock():
    if (r := rate_limit(f"vault:{g.user['id']}", 20, 600)):
        return r
    token = vault.unlock(ctx(), g.user, str(body().get("pin") or ""))
    return jsonify(vault_token=token, expires_in=vault.VAULT_TTL)
