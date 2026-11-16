from flask import g, jsonify

from ..assistant.engine import Conversation, Engine, load_messages
from ..security.auth import require_auth
from . import api, body, ctx, rate_limit


@api.post("/assistant/message")
@require_auth
def assistant_message():
    if (r := rate_limit(f"assistant:{g.user['id']}", 60, 60)):
        return r
    b = body()
    text = (b.get("text") or "").strip()
    if not text:
        return jsonify(error="empty_message"), 400
    conv = Conversation(ctx(), g.user, b.get("conversation_id"))
    return jsonify(Engine(ctx(), g.user, g.dek).respond(conv, text))


@api.get("/conversations")
@require_auth
def conversations():
    rows = ctx().db.all("SELECT id, title, created_at, updated_at FROM conversations WHERE user_id = ? "
                        "ORDER BY updated_at DESC LIMIT 50", (g.user["id"],))
    return jsonify(conversations=rows)


@api.get("/conversations/<cid>")
@require_auth
def conversation(cid):
    row = ctx().db.one("SELECT id, title, created_at FROM conversations WHERE id = ? AND user_id = ?", (cid, g.user["id"]))
    if not row:
        return jsonify(error="not_found"), 404
    return jsonify(conversation=row, messages=load_messages(ctx(), g.dek, cid))


@api.delete("/conversations/<cid>")
@require_auth
def delete_conversation(cid):
    ctx().db.execute("DELETE FROM conversations WHERE id = ? AND user_id = ?", (cid, g.user["id"]))
    return jsonify(ok=True)
