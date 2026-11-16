from flask import g, jsonify, redirect, request

from ..connectors import google
from ..connectors.base import registry
from ..security.auth import require_auth
from ..services import documents as docsvc
from . import api, body, ctx


@api.get("/connectors")
@require_auth
def list_connectors():
    return jsonify(connectors=[c.describe(ctx(), g.user) for c in registry(ctx())])


@api.post("/connectors/<kind>/connect")
@require_auth
def connect(kind):
    return jsonify(auth_url=google.start_oauth(ctx(), g.user, kind))


@api.get("/oauth/google/callback")
def oauth_callback():
    # Browser redirect from Google: the one-time `state` (bound to the user server-side) authenticates it.
    if request.args.get("error"):
        return redirect("/#/accounts?error=" + request.args["error"][:40])
    try:
        uid, kind = google.finish_oauth(ctx(), request.args.get("code", ""), request.args.get("state", ""))
    except google.ConnectorError as e:
        return redirect("/#/accounts?error=" + e.code)
    _sync_in_background(uid, kind)
    return redirect(f"/#/accounts?connected={kind}")


def _sync_in_background(user_id, kind):
    c = ctx()

    def job():
        from ..security.auth import user_dek
        user = c.db.one("SELECT * FROM users WHERE id = ?", (user_id,))
        if user:
            try:
                google.sync_index(c, user, user_dek(c, user), kind)
            except google.ConnectorError:
                pass
    c.executor.submit(job)


@api.post("/connectors/<kind>/sync")
@require_auth
def sync(kind):
    return jsonify(google.sync_index(ctx(), g.user, g.dek, kind))


@api.delete("/connectors/<kind>")
@require_auth
def disconnect(kind):
    google.disconnect(ctx(), g.user, g.dek, kind)
    return jsonify(ok=True)


@api.post("/connectors/<kind>/import")
@require_auth
def import_external(kind):
    doc = google.import_external(ctx(), g.user, g.dek, kind, body().get("ref") or "")
    return jsonify(document=docsvc.public(doc)), 201
