from flask import jsonify, request

from ..security import auth as authsvc
from ..security.audit import audit
from . import api, body, ctx, rate_limit


def _session_response(user, status=200):
    c = ctx()
    resp = jsonify(access_token=authsvc.issue_access_token(c, user), expires_in=c.config.access_token_ttl,
                   user=_me(user))
    resp.status_code = status
    resp.set_cookie(authsvc.REFRESH_COOKIE, authsvc.issue_refresh_token(c, user), max_age=c.config.refresh_token_ttl,
                    httponly=True, secure=c.config.secure_cookies, samesite="Strict", path="/api/auth")
    return resp


def _me(user):
    import json
    return {"id": user["id"], "email": user["email"], "display_name": user["display_name"], "locale": user["locale"],
            "settings": json.loads(user["settings_json"] or "{}"), "created_at": user["created_at"],
            "mfa_enabled": bool(user.get("totp_enabled")), "vault_pin_set": bool(user.get("vault_pin_hash"))}


@api.post("/auth/register")
def register():
    if (r := rate_limit("register", 10, 3600)):
        return r
    b = body()
    user = authsvc.register_user(ctx(), b.get("email"), b.get("password"), b.get("display_name"), b.get("locale", "he"))
    audit(ctx(), user["id"], "auth.register")
    return _session_response(user, 201)


@api.post("/auth/login")
def login():
    if (r := rate_limit("login", 10, 300)):
        return r
    b = body()
    try:
        user = authsvc.authenticate(ctx(), b.get("email"), b.get("password"))
    except authsvc.AuthError:
        audit(ctx(), None, "auth.login_failed", (b.get("email") or "")[:120])
        raise
    if user["totp_enabled"]:
        audit(ctx(), user["id"], "auth.password_ok_mfa_pending")
        return jsonify(mfa_required=True, mfa_token=authsvc.issue_mfa_token(ctx(), user))
    audit(ctx(), user["id"], "auth.login")
    return _session_response(user)


@api.post("/auth/mfa")
def login_mfa():
    if (r := rate_limit("mfa", 10, 300)):
        return r
    b = body()
    try:
        user = authsvc.verify_second_factor(ctx(), b.get("mfa_token"), b.get("code"))
    except authsvc.AuthError as e:
        audit(ctx(), None, "auth.mfa_failed", None, error=e.code)
        raise
    audit(ctx(), user["id"], "auth.login", None, mfa=True)
    return _session_response(user)


@api.post("/auth/refresh")
def refresh():
    if (r := rate_limit("refresh", 60, 300)):
        return r
    raw = request.cookies.get(authsvc.REFRESH_COOKIE)
    if not raw:
        return jsonify(error="no_session"), 401
    user, new_raw = authsvc.rotate_refresh_token(ctx(), raw)
    c = ctx()
    resp = jsonify(access_token=authsvc.issue_access_token(c, user), expires_in=c.config.access_token_ttl, user=_me(user))
    resp.set_cookie(authsvc.REFRESH_COOKIE, new_raw, max_age=c.config.refresh_token_ttl, httponly=True,
                    secure=c.config.secure_cookies, samesite="Strict", path="/api/auth")
    return resp


@api.post("/auth/logout")
def logout():
    authsvc.revoke_refresh_token(ctx(), request.cookies.get(authsvc.REFRESH_COOKIE))
    resp = jsonify(ok=True)
    resp.delete_cookie(authsvc.REFRESH_COOKIE, path="/api/auth")
    return resp
