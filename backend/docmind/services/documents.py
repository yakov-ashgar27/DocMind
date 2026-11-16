"""Document ingestion pipeline + library operations."""
from __future__ import annotations

import json
import logging
import re
import zipfile
import io
from pathlib import PurePosixPath

from ..db import new_id, now_iso
from ..knowledge.catalog import DOC_TYPES
from ..security import crypto
from ..security.audit import audit
from . import classifier, extract

log = logging.getLogger(__name__)

PUBLIC_FIELDS = ("id", "source_kind", "source_url", "is_local", "original_filename", "display_name", "mime_type",
                 "size_bytes", "category_key", "doc_type", "doc_type_confidence", "doc_type_source", "issuer",
                 "doc_date", "expiry_date", "status", "error", "duplicate_of", "duplicate_kind", "archived",
                 "ocr_used", "language", "text_chars", "created_at", "updated_at")


class IngestError(Exception):
    def __init__(self, code: str, status: int = 400):
        super().__init__(code)
        self.code = code
        self.status = status


def public(doc: dict, with_freshness: bool = True) -> dict:
    out = {k: doc.get(k) for k in PUBLIC_FIELDS}
    out["tags"] = json.loads(doc.get("tags_json") or "[]")
    out["is_local"] = bool(out["is_local"])
    out["archived"] = bool(out["archived"])
    out["ocr_used"] = bool(out["ocr_used"])
    if with_freshness:
        out["freshness"] = classifier.freshness(doc)
    return out


def _safe_name(name: str) -> str:
    name = PurePosixPath((name or "document").replace("\\", "/")).name
    name = re.sub(r"[\x00-\x1f<>:\"|?*]", "_", name).strip(" .") or "document"
    return name[:180]


def ingest(ctx, user: dict, dek: bytes, data: bytes, filename: str, source_kind: str = "upload",
           source_ref: str | None = None) -> dict:
    if not data:
        raise IngestError("empty_file")
    if len(data) > ctx.config.max_upload_bytes:
        raise IngestError("file_too_large", 413)
    filename = _safe_name(filename)
    mime = extract.sniff_mime(data, filename)
    if not mime:
        raise IngestError("unsupported_file_type", 415)
    sha = crypto.sha256_hex(data)
    exact = ctx.db.one("SELECT id FROM documents WHERE user_id = ? AND sha256 = ? AND duplicate_of IS NULL "
                       "ORDER BY created_at LIMIT 1", (user["id"], sha))
    storage_key, wrapped = ctx.blobs.put(data)
    doc_id = new_id()
    ts = now_iso()
    ctx.db.insert("documents", {
        "id": doc_id, "user_id": user["id"], "source_kind": source_kind, "source_ref": source_ref,
        "is_local": 1, "original_filename": filename, "display_name": filename.rsplit(".", 1)[0],
        "mime_type": mime, "size_bytes": len(data), "sha256": sha, "storage_key": storage_key,
        "wrapped_file_key": wrapped, "status": "processing",
        "duplicate_of": exact["id"] if exact else None, "duplicate_kind": "exact" if exact else None,
        "created_at": ts, "updated_at": ts,
    })
    audit(ctx, user["id"], "document.upload", doc_id, source=source_kind, size=len(data))
    if ctx.config.process_sync:
        process(ctx, user["id"], doc_id)
    else:
        ctx.executor.submit(_process_safe, ctx, user["id"], doc_id)
    return ctx.db.one("SELECT * FROM documents WHERE id = ?", (doc_id,))


def _process_safe(ctx, user_id, doc_id):
    try:
        process(ctx, user_id, doc_id)
    except Exception:  # pragma: no cover - logged, surfaced as status=failed
        log.exception("processing failed for %s", doc_id)


def process(ctx, user_id: str, doc_id: str) -> None:
    """Extraction -> OCR -> classification -> near-duplicate check -> thumbnail. Runs locally."""
    doc = ctx.db.one("SELECT * FROM documents WHERE id = ?", (doc_id,))
    user = ctx.db.one("SELECT * FROM users WHERE id = ?", (user_id,))
    if not doc or not user:
        return
    from ..security.auth import user_dek
    dek = user_dek(ctx, user)
    try:
        data = ctx.blobs.get(doc["storage_key"], doc["wrapped_file_key"])
        ex = extract.extract_text(data, doc["mime_type"], ctx.config.ocr_languages, ctx.config.ocr_max_pdf_pages)
        hint = ctx.search.nearest_labelled(user_id, dek, ex.text, doc["original_filename"])
        c = classifier.classify(ex.text, doc["original_filename"], hint)
        values = {
            "text_enc": crypto.encrypt_text(dek, ex.text, f"doctext:{doc_id}"), "text_chars": len(ex.text),
            "ocr_used": int(ex.ocr_used), "language": ex.language,
            "doc_type": c.doc_type, "doc_type_confidence": c.confidence, "category_key": c.category,
            "issuer": c.issuer, "doc_date": c.doc_date, "expiry_date": c.expiry_date,
            "status": "ready", "error": None, "updated_at": now_iso(),
        }
        if c.doc_type != "unknown" and doc["display_name"] == doc["original_filename"].rsplit(".", 1)[0]:
            values["display_name"] = _smart_name(c, doc, user.get("locale") or "he")
        thumb = extract.make_thumbnail(data, doc["mime_type"])
        if thumb:
            if doc.get("thumb_key"):
                ctx.blobs.delete(doc["thumb_key"])
            values["thumb_key"], values["wrapped_thumb_key"] = ctx.blobs.put(thumb)
        ctx.db.update("documents", doc_id, values)
        if not doc["duplicate_of"]:
            _near_duplicate(ctx, user_id, dek, doc_id, c.doc_type, ex.text)
    except Exception as e:
        ctx.db.update("documents", doc_id, {"status": "failed", "error": str(e)[:300], "updated_at": now_iso()})
        log.warning("processing failed for %s: %s", doc_id, e)
    finally:
        ctx.search.invalidate(user_id)


def _smart_name(c, doc, lang: str = "he") -> str:
    """Readable name for documents with meaningless filenames (IMG_2026..., document_7)."""
    fname = doc["original_filename"].rsplit(".", 1)[0]
    meaningless = re.fullmatch(r"(img|image|scan|doc|document|file|photo|pxl|dsc|whatsapp image|screenshot|download|p|wa)?[\s_\-]*[\d_\-\s:.()atw]*",
                               fname.lower()) is not None
    if not meaningless:
        return fname
    # Short, localised: "<type> · <issuer>" — the date is shown separately in the UI.
    parts = [DOC_TYPES[c.doc_type]["he" if lang == "he" else "en"]]
    if c.issuer and len(c.issuer) <= 20:
        parts.append(c.issuer)
    return " · ".join(parts)


def _near_duplicate(ctx, user_id, dek, doc_id, doc_type, text):
    if doc_type == "unknown" or len(text) < 40:
        return
    others = ctx.db.all("SELECT id, text_enc FROM documents WHERE user_id = ? AND doc_type = ? AND id != ? "
                        "AND status = 'ready' AND duplicate_of IS NULL AND archived = 0", (user_id, doc_type, doc_id))
    a = set(re.findall(r"\w{3,}", text.lower()))
    for o in others:
        b = set(re.findall(r"\w{3,}", crypto.decrypt_text(dek, o["text_enc"], f"doctext:{o['id']}").lower()))
        if a and b and len(a & b) / len(a | b) >= 0.85:
            ctx.db.update("documents", doc_id, {"duplicate_of": o["id"], "duplicate_kind": "near"})
            return


def reprocess(ctx, user, doc_id):
    ctx.db.update("documents", doc_id, {"status": "processing", "updated_at": now_iso()})
    if ctx.config.process_sync:
        process(ctx, user["id"], doc_id)
    else:
        ctx.executor.submit(_process_safe, ctx, user["id"], doc_id)


def get_owned(ctx, user_id: str, doc_id: str) -> dict | None:
    return ctx.db.one("SELECT * FROM documents WHERE id = ? AND user_id = ?", (doc_id, user_id))


def update_metadata(ctx, user: dict, doc: dict, patch: dict) -> dict:
    values: dict = {}
    if "display_name" in patch:
        name = str(patch["display_name"]).strip()[:180]
        if name:
            values["display_name"] = name
    if "doc_type" in patch:
        dt = patch["doc_type"]
        if dt not in DOC_TYPES and dt != "unknown":
            raise IngestError("invalid_doc_type")
        values.update(doc_type=dt, doc_type_source="user", doc_type_confidence=1.0)
        if "category_key" not in patch:
            values["category_key"] = DOC_TYPES.get(dt, {}).get("cat", "other")
    if "category_key" in patch:
        key = patch["category_key"]
        ok = ctx.db.one("SELECT 1 FROM categories WHERE key = ? AND (user_id IS NULL OR user_id = ?)", (key, user["id"]))
        if not ok:
            raise IngestError("invalid_category")
        values["category_key"] = key
    if "tags" in patch:
        tags = [str(t).strip()[:40] for t in patch["tags"] if str(t).strip()][:20]
        values["tags_json"] = json.dumps(tags, ensure_ascii=False)
    for f in ("doc_date", "expiry_date", "issuer"):
        if f in patch:
            v = patch[f] or None
            if v and f != "issuer" and not re.fullmatch(r"\d{4}-\d{2}-\d{2}", v):
                raise IngestError(f"invalid_{f}")
            values[f] = v[:120] if v else None
    if "archived" in patch:
        values["archived"] = int(bool(patch["archived"]))
    if values:
        values["updated_at"] = now_iso()
        ctx.db.update("documents", doc["id"], values)
        ctx.search.invalidate(user["id"])
        audit(ctx, user["id"], "document.update", doc["id"], fields=sorted(values))
    return get_owned(ctx, user["id"], doc["id"])


def resolve_duplicate(ctx, user, doc, action: str):
    """keep_both | archive_this | not_duplicate. Originals are never deleted automatically."""
    if action == "not_duplicate" or action == "keep_both":
        ctx.db.update("documents", doc["id"], {"duplicate_of": None, "duplicate_kind": None, "updated_at": now_iso()})
    elif action == "archive_this":
        ctx.db.update("documents", doc["id"], {"archived": 1, "updated_at": now_iso()})
    else:
        raise IngestError("invalid_action")
    ctx.search.invalidate(user["id"])
    audit(ctx, user["id"], "document.duplicate_resolve", doc["id"], action=action)


def delete_document(ctx, user, doc):
    """User-initiated permanent delete: crypto-shred the blob, then remove the row."""
    if doc["storage_key"]:
        ctx.blobs.delete(doc["storage_key"])
    if doc.get("thumb_key"):
        ctx.blobs.delete(doc["thumb_key"])
    ctx.db.execute("UPDATE documents SET duplicate_of = NULL, duplicate_kind = NULL WHERE duplicate_of = ?", (doc["id"],))
    ctx.db.execute("DELETE FROM documents WHERE id = ?", (doc["id"],))
    ctx.search.invalidate(user["id"])
    audit(ctx, user["id"], "document.delete", doc["id"])


def read_bytes(ctx, doc) -> bytes:
    return ctx.blobs.get(doc["storage_key"], doc["wrapped_file_key"])


def read_thumbnail(ctx, doc) -> bytes | None:
    if not doc.get("thumb_key"):
        return None
    return ctx.blobs.get(doc["thumb_key"], doc["wrapped_thumb_key"])


# ---- WhatsApp: official "Export chat" (with media) import ---------------------------------
WA_MEDIA = re.compile(r"\.(pdf|jpe?g|png|webp)$", re.I)
MAX_ZIP_MEMBERS = 300
MAX_ZIP_TOTAL = 200 * 1024 * 1024


def import_whatsapp_export(ctx, user, dek, zip_bytes: bytes) -> dict:
    """WhatsApp has no official API for reading a personal account's chats. The supported path is
    the user-initiated "Export chat → Attach media" feature, which produces a .zip we import here."""
    try:
        zf = zipfile.ZipFile(io.BytesIO(zip_bytes))
    except zipfile.BadZipFile:
        raise IngestError("invalid_zip") from None
    members = [m for m in zf.infolist() if not m.is_dir() and WA_MEDIA.search(m.filename)]
    if len(members) > MAX_ZIP_MEMBERS or sum(m.file_size for m in members) > MAX_ZIP_TOTAL:
        raise IngestError("zip_too_large", 413)
    chat_name = None
    for m in zf.infolist():
        if m.filename.lower().endswith(".txt") and m.file_size < 20 * 1024 * 1024:
            chat_name = PurePosixPath(m.filename).stem.replace("WhatsApp Chat with ", "").replace("WhatsApp Chat - ", "")
            break
    imported, skipped = [], []
    for m in members:
        if m.file_size > ctx.config.max_upload_bytes:
            skipped.append({"name": m.filename, "reason": "file_too_large"})
            continue
        data = zf.read(m)
        try:
            doc = ingest(ctx, user, dek, data, PurePosixPath(m.filename).name, "whatsapp_import",
                         source_ref=f"chat:{chat_name}" if chat_name else None)
            imported.append(doc["id"])
        except IngestError as e:
            skipped.append({"name": m.filename, "reason": e.code})
    audit(ctx, user["id"], "whatsapp.import", None, imported=len(imported), skipped=len(skipped))
    return {"imported": imported, "skipped": skipped, "chat": chat_name}
