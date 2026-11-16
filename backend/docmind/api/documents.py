import io
import json

import jwt
from flask import g, jsonify, request, send_file

from ..security import crypto
from ..security.audit import audit
from ..security.auth import require_auth
from ..security.vault import ensure_visible
from ..services import bundles as bundlesvc
from ..services import documents as docsvc
from . import api, body, ctx, rate_limit, sign_link, verify_link


def _owned_or_404(doc_id):
    doc = docsvc.get_owned(ctx(), g.user["id"], doc_id)
    if not doc:
        raise docsvc.IngestError("not_found", 404)
    ensure_visible(doc)
    return doc


@api.get("/documents")
@require_auth
def list_documents():
    c = ctx()
    a = request.args
    sql = "SELECT * FROM documents WHERE user_id = ?"
    params: list = [g.user["id"]]
    if a.get("include_archived") != "1":
        sql += " AND archived = 0"
    for field, col in (("category", "category_key"), ("doc_type", "doc_type"), ("source", "source_kind"),
                       ("status", "status")):
        if a.get(field):
            sql += f" AND {col} = ?"
            params.append(a[field])
    if a.get("issuer"):
        sql += " AND issuer LIKE ?"
        params.append(f"%{a['issuer']}%")
    if a.get("from"):
        sql += " AND COALESCE(doc_date, substr(created_at,1,10)) >= ?"
        params.append(a["from"])
    if a.get("to"):
        sql += " AND COALESCE(doc_date, substr(created_at,1,10)) <= ?"
        params.append(a["to"])
    if a.get("tag"):
        sql += " AND tags_json LIKE ?"
        params.append(f"%{json.dumps(a['tag'], ensure_ascii=False)}%")
    if a.get("duplicates") == "1":
        sql += " AND duplicate_of IS NOT NULL"
    rows = c.db.all(sql + " ORDER BY created_at DESC", tuple(params))
    q = (a.get("q") or "").strip()
    if q:
        allowed = {r["id"] for r in rows}
        ranked = c.search.search(g.user["id"], g.dek, q, limit=50, min_score=0.1)
        return jsonify(documents=[{**docsvc.public(d), "score": round(s, 3)} for d, s in ranked if d["id"] in allowed])
    return jsonify(documents=[docsvc.public(r) for r in rows])


@api.post("/documents")
@require_auth
def upload_documents():
    if (r := rate_limit(f"upload:{g.user['id']}", 120, 600)):
        return r
    files = request.files.getlist("files")
    if not files:
        return jsonify(error="no_files"), 400
    source = request.form.get("source", "upload")
    if source not in ("upload", "whatsapp_import"):
        source = "upload"
    created, errors = [], []
    for f in files[:50]:
        try:
            doc = docsvc.ingest(ctx(), g.user, g.dek, f.read(ctx().config.max_upload_bytes + 1), f.filename or "document",
                                source_kind=source)
            created.append(docsvc.public(doc))
        except docsvc.IngestError as e:
            errors.append({"filename": f.filename, "error": e.code})
    return jsonify(documents=created, errors=errors), 201 if created else 400


@api.post("/import/whatsapp")
@require_auth
def import_whatsapp():
    f = request.files.get("file")
    if not f:
        return jsonify(error="no_file"), 400
    return jsonify(docsvc.import_whatsapp_export(ctx(), g.user, g.dek, f.read())), 201


@api.get("/documents/<doc_id>")
@require_auth
def get_document(doc_id):
    doc = _owned_or_404(doc_id)
    text = crypto.decrypt_text(g.dek, doc["text_enc"], f"doctext:{doc_id}")
    dup = docsvc.get_owned(ctx(), g.user["id"], doc["duplicate_of"]) if doc["duplicate_of"] else None
    if dup and dup["category_key"] in g.hidden_cats:
        dup = None
    bundles = ctx().db.all("SELECT b.id, b.name FROM bundle_items i JOIN bundles b ON b.id = i.bundle_id "
                           "WHERE i.document_id = ? AND b.user_id = ?", (doc_id, g.user["id"]))
    return jsonify(document=docsvc.public(doc), text_excerpt=text[:4000], text_length=len(text),
                   duplicate_of=docsvc.public(dup) if dup else None, bundles=bundles)


@api.patch("/documents/<doc_id>")
@require_auth
def patch_document(doc_id):
    doc = _owned_or_404(doc_id)
    return jsonify(document=docsvc.public(docsvc.update_metadata(ctx(), g.user, doc, body())))


@api.delete("/documents/<doc_id>")
@require_auth
def delete_document(doc_id):
    doc = _owned_or_404(doc_id)
    if body().get("confirm") is not True:
        return jsonify(error="confirmation_required"), 400
    docsvc.delete_document(ctx(), g.user, doc)
    return jsonify(ok=True)


@api.post("/documents/<doc_id>/reprocess")
@require_auth
def reprocess(doc_id):
    doc = _owned_or_404(doc_id)
    docsvc.reprocess(ctx(), g.user, doc_id)
    return jsonify(document=docsvc.public(docsvc.get_owned(ctx(), g.user["id"], doc["id"])))


@api.post("/documents/<doc_id>/duplicate")
@require_auth
def resolve_duplicate(doc_id):
    doc = _owned_or_404(doc_id)
    docsvc.resolve_duplicate(ctx(), g.user, doc, body().get("action"))
    return jsonify(document=docsvc.public(docsvc.get_owned(ctx(), g.user["id"], doc_id)))


@api.get("/documents/<doc_id>/thumbnail")
@require_auth
def thumbnail(doc_id):
    data = docsvc.read_thumbnail(ctx(), _owned_or_404(doc_id))
    if not data:
        return jsonify(error="no_thumbnail"), 404
    resp = send_file(io.BytesIO(data), mimetype="image/jpeg")
    resp.headers["Cache-Control"] = "private, max-age=3600"
    return resp


@api.post("/documents/<doc_id>/link")
@require_auth
def document_link(doc_id):
    doc = _owned_or_404(doc_id)
    if not doc["is_local"]:
        return jsonify(error="document_not_local"), 409
    disposition = "inline" if body().get("disposition") == "inline" else "attachment"
    return jsonify(url=sign_link(g.user["id"], "doc", {"d": doc_id, "disp": disposition}))


@api.get("/dl/<token>")
def signed_download(token):
    if (r := rate_limit("dl", 300, 300)):
        return r
    try:
        p = verify_link(token)
    except jwt.PyJWTError:
        return jsonify(error="link_expired"), 410
    c = ctx()
    user = c.db.one("SELECT * FROM users WHERE id = ?", (p["sub"],))
    if not user:
        return jsonify(error="not_found"), 404
    if p["k"] == "doc":
        doc = docsvc.get_owned(c, user["id"], p["r"]["d"])
        if not doc:
            return jsonify(error="not_found"), 404
        data, name, mime = docsvc.read_bytes(c, doc), doc["original_filename"], doc["mime_type"]
        inline = p["r"]["disp"] == "inline"
        audit(c, user["id"], "document.preview" if inline else "document.download", doc["id"])
    elif p["k"] == "bundle_item":
        data, name, mime = bundlesvc.item_file(c, user, p["r"]["b"], p["r"]["i"])
        inline = False
    elif p["k"] == "bundle_pdf":
        data, name = bundlesvc.combined_pdf(c, user, p["r"]["b"])
        mime, inline = "application/pdf", False
    elif p["k"] == "ics":
        from ..services.reminders import calendar_ics
        data, name, mime, inline = calendar_ics(c, user, p["r"].get("ids") or None, set(p["r"].get("x") or [])), "docmind-reminders.ics", "text/calendar", False
        audit(c, user["id"], "reminders.export")
    else:
        return jsonify(error="bad_link"), 400
    resp = send_file(io.BytesIO(data), mimetype=mime, as_attachment=not inline, download_name=name)
    resp.headers["Cache-Control"] = "no-store"
    if inline:
        # Allow only our own page to frame the preview. PDFs need the browser's built-in viewer,
        # which a `default-src 'none'` policy would block, so they get frame-ancestors only.
        resp.headers["Content-Security-Policy"] = ("frame-ancestors 'self'" if mime == "application/pdf"
                                                   else "default-src 'none'; img-src 'self'; style-src 'unsafe-inline'; frame-ancestors 'self'")
        resp.headers["X-Frame-Options"] = "SAMEORIGIN"
    return resp
