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
        _, kind = google.finish_oauth(ctx(), request.args.get("code", ""), request.args.get("state", ""))
    except google.ConnectorError as e:
        return redirect("/#/accounts?error=" + e.code)
    return redirect(f"/#/accounts?connected={kind}")


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
