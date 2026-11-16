import json
import re

from flask import g, jsonify

from ..db import new_id, now_iso
from ..knowledge.catalog import DOC_TYPES, PROCESSES
from ..security import auth as authsvc
from ..security import crypto
from ..security.audit import audit
from ..security.auth import require_auth
from ..services import classifier
from ..services import documents as docsvc
from ..services import memory as memsvc
from ..services import reminders as remsvc
from . import api, body, ctx

SETTINGS_KEYS = {"ai_provider_consent": bool, "shared_learning_opt_in": bool, "remember_locations": bool, "reminder_days": int}


@api.get("/meta")
def meta():
    c = ctx()
    return jsonify(
        doc_types={k: {"en": v["en"], "he": v["he"], "category": v["cat"]} for k, v in DOC_TYPES.items()},
        processes={k: {"en": v["en"], "he": v["he"]} for k, v in PROCESSES.items()},
        llm={"provider": c.llm.name, "available": c.llm.available},
        shared_learning_available=c.config.shared_learning_enabled,
        google_configured=bool(c.config.google_client_id and c.config.google_client_secret),
    )


@api.get("/me")
@require_auth
def me():
    from .auth import _me
    return jsonify(user=_me(g.user))


@api.patch("/me")
@require_auth
def patch_me():
    b = body()
    settings = json.loads(g.user["settings_json"] or "{}")
    values = {}
    for k, typ in SETTINGS_KEYS.items():
        if k in b:
            try:
                settings[k] = typ(b[k])
            except (TypeError, ValueError):
                return jsonify(error=f"invalid_{k}"), 400
    if "reminder_days" in settings and settings["reminder_days"] not in remsvc.ALLOWED_LEAD_DAYS:
        return jsonify(error="invalid_reminder_days"), 400
    values["settings_json"] = json.dumps(settings)
    if b.get("locale") in ("he", "en"):
        values["locale"] = b["locale"]
    if b.get("display_name"):
        values["display_name"] = str(b["display_name"]).strip()[:80]
    ctx().db.update("users", g.user["id"], values)
    audit(ctx(), g.user["id"], "account.settings", None, keys=sorted(b))
    from .auth import _me
    return jsonify(user=_me(ctx().db.one("SELECT * FROM users WHERE id = ?", (g.user["id"],))))


@api.post("/me/logout-all")
@require_auth
def logout_all():
    authsvc.revoke_all_sessions(ctx(), g.user["id"])
    audit(ctx(), g.user["id"], "auth.revoke_all")
    return jsonify(ok=True)


@api.post("/me/password")
@require_auth
def change_password():
    b = body()
    if not crypto.verify_password(b.get("current_password") or "", g.user["password_hash"]):
        return jsonify(error="invalid_credentials"), 403
    authsvc.validate_password(b.get("new_password") or "")
    ctx().db.update("users", g.user["id"], {"password_hash": crypto.hash_password(b["new_password"])})
    authsvc.revoke_all_sessions(ctx(), g.user["id"])
    audit(ctx(), g.user["id"], "auth.password_change")
    return jsonify(ok=True)


@api.get("/me/audit")
@require_auth
def audit_log():
    rows = ctx().db.all("SELECT action, target, ip, created_at, meta_json FROM audit_log WHERE user_id = ? "
                        "ORDER BY created_at DESC LIMIT 200", (g.user["id"],))
    return jsonify(events=[{**r, "meta": json.loads(r.pop("meta_json"))} for r in rows])


@api.get("/me/export")
@require_auth
def export_data():
    c = ctx()
    docs = [docsvc.public(d) for d in c.db.all("SELECT * FROM documents WHERE user_id = ?", (g.user["id"],))]
    audit(c, g.user["id"], "account.export")
    return jsonify(exported_at=now_iso(), documents=docs, checklists=memsvc.list_checklists(c, g.user["id"]),
                   memory=memsvc.list_facts(c, g.user["id"]),
                   bundles=c.db.all("SELECT id, name, created_at FROM bundles WHERE user_id = ?", (g.user["id"],)))


@api.delete("/me")
@require_auth
def delete_account():
    c = ctx()
    if not crypto.verify_password(body().get("password") or "", g.user["password_hash"]):
        return jsonify(error="invalid_credentials"), 403
    for d in c.db.all("SELECT storage_key, thumb_key FROM documents WHERE user_id = ?", (g.user["id"],)):
        for k in (d["storage_key"], d["thumb_key"]):
            if k:
                c.blobs.delete(k)
    c.db.execute("DELETE FROM users WHERE id = ?", (g.user["id"],))  # cascades; wrapped DEK is gone => text unrecoverable
    c.search.invalidate(g.user["id"])
    audit(c, None, "account.delete", g.user["id"])
    return jsonify(ok=True)


# ---- categories ------------------------------------------------------------------------------
@api.get("/categories")
@require_auth
def categories():
    c = ctx()
    rows = c.db.all("SELECT * FROM categories WHERE user_id IS NULL OR user_id = ? ORDER BY is_custom, rowid", (g.user["id"],))
    counts = {r["category_key"]: r["n"] for r in c.db.all(
        "SELECT category_key, COUNT(*) n FROM documents WHERE user_id = ? AND archived = 0 GROUP BY category_key",
        (g.user["id"],))}
    return jsonify(categories=[{"id": r["id"], "key": r["key"], "name": {"en": r["name_en"], "he": r["name_he"]},
                                "icon": r["icon"], "is_custom": bool(r["is_custom"]), "count": counts.get(r["key"], 0)}
                               for r in rows])


@api.post("/categories")
@require_auth
def create_category():
    name = (body().get("name") or "").strip()[:60]
    if not name:
        return jsonify(error="name_required"), 400
    key = "c_" + re.sub(r"[^\w֐-׿]+", "_", name.lower()).strip("_")[:40]
    c = ctx()
    if c.db.one("SELECT 1 FROM categories WHERE key = ? AND (user_id IS NULL OR user_id = ?)", (key, g.user["id"])):
        return jsonify(error="category_exists"), 409
    c.db.insert("categories", {"id": new_id(), "user_id": g.user["id"], "key": key, "name_en": name, "name_he": name,
                               "icon": "tag", "is_custom": 1, "created_at": now_iso()})
    return jsonify(key=key), 201


@api.delete("/categories/<key>")
@require_auth
def delete_category(key):
    c = ctx()
    row = c.db.one("SELECT * FROM categories WHERE key = ? AND user_id = ?", (key, g.user["id"]))
    if not row:
        return jsonify(error="not_found"), 404
    c.db.execute("UPDATE documents SET category_key = 'other' WHERE user_id = ? AND category_key = ?", (g.user["id"], key))
    c.db.execute("DELETE FROM categories WHERE id = ?", (row["id"],))
    c.search.invalidate(g.user["id"])
    return jsonify(ok=True)


# ---- dashboard -------------------------------------------------------------------------------
@api.get("/dashboard")
@require_auth
def dashboard():
    c = ctx()
    uid = g.user["id"]
    docs = c.db.all("SELECT * FROM documents WHERE user_id = ? AND archived = 0", (uid,))
    attention = []
    for d in docs:
        f = classifier.freshness(d)
        if f["state"] in ("expired", "expiring", "maybe_outdated"):
            attention.append({"kind": f["state"], "document": docsvc.public(d)})
        elif d["duplicate_of"]:
            attention.append({"kind": "duplicate", "document": docsvc.public(d)})
        elif d["status"] == "ready" and d["doc_type"] == "unknown":
            attention.append({"kind": "unclassified", "document": docsvc.public(d)})
        elif d["status"] == "failed":
            attention.append({"kind": "failed", "document": docsvc.public(d)})
    order = {"expired": 0, "failed": 1, "duplicate": 2, "expiring": 3, "maybe_outdated": 4, "unclassified": 5}
    attention.sort(key=lambda a: order[a["kind"]])
    from ..services.bundles import list_bundles
    return jsonify(
        totals={"documents": len(docs), "processing": sum(d["status"] == "processing" for d in docs),
                "checklists": c.db.one("SELECT COUNT(*) n FROM checklists WHERE user_id = ?", (uid,))["n"],
                "bundles": c.db.one("SELECT COUNT(*) n FROM bundles WHERE user_id = ?", (uid,))["n"]},
        attention=attention[:8], recent_documents=[docsvc.public(d) for d in sorted(docs, key=lambda d: d["created_at"], reverse=True)[:6]],
        bundles=list_bundles(c, g.user)[:4], checklists=memsvc.list_checklists(c, uid)[:4],
        reminders=remsvc.upcoming(c, g.user)[:5],
        proposals=memsvc.pending_proposals(c, uid))


# ---- reminders ---------------------------------------------------------------------------------
@api.get("/reminders")
@require_auth
def reminders():
    return jsonify(reminders=remsvc.upcoming(ctx(), g.user), lead_days=remsvc.lead_days(g.user))


@api.post("/reminders/calendar-link")
@require_auth
def reminders_calendar_link():
    from . import sign_link
    ids = [str(i) for i in (body().get("document_ids") or [])][:200]
    return jsonify(url=sign_link(g.user["id"], "ics", {"ids": ids}))
