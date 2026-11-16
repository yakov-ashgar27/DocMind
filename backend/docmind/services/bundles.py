"""Document bundles: purpose-specific collections, downloaded as individual original files.
A combined PDF is optional and only produced on explicit request."""
from __future__ import annotations

import io
import re

from ..db import new_id, now_iso
from ..knowledge.catalog import DOC_TYPES
from ..security.audit import audit
from . import documents as docsvc
from . import memory as memsvc
from .extract import SUPPORTED_MIME


class BundleError(Exception):
    def __init__(self, code, status=400):
        super().__init__(code)
        self.code = code
        self.status = status


def _ext(doc) -> str:
    orig = doc["original_filename"]
    if "." in orig and len(orig.rsplit(".", 1)[1]) <= 5:
        return "." + orig.rsplit(".", 1)[1].lower()
    return SUPPORTED_MIME.get(doc["mime_type"], "")


def sanitize_filename(name: str) -> str:
    name = re.sub(r"[\x00-\x1f<>:\"/\\|?*]", "_", name)
    name = re.sub(r"\s+", " ", name).strip(" .")
    return name[:150] or "document"


def item_filename(item, doc) -> str:
    if item.get("custom_filename"):
        base = item["custom_filename"]
        if base.lower().endswith(_ext(doc)):
            base = base[: -len(_ext(doc))]
    else:
        base = f"{item['position'] + 1:02d}_{item['label']}"
    return sanitize_filename(base) + _ext(doc)


def create(ctx, user, name, items, checklist_id=None) -> dict:
    name = (name or "").strip()[:120]
    if not name:
        raise BundleError("name_required")
    if checklist_id and not memsvc.get_checklist(ctx, user["id"], checklist_id):
        checklist_id = None
    bid = new_id()
    ts = now_iso()
    ctx.db.insert("bundles", {"id": bid, "user_id": user["id"], "name": name, "checklist_id": checklist_id,
                              "created_at": ts, "updated_at": ts})
    for pos, it in enumerate(items or []):
        _insert_item(ctx, user, bid, pos, it)
        if it.get("document_id"):
            doc = docsvc.get_owned(ctx, user["id"], it["document_id"])
            if doc:
                memsvc.remember_location(ctx, user, doc["doc_type"], doc["source_kind"])
    audit(ctx, user["id"], "bundle.create", bid, items=len(items or []))
    return get(ctx, user, bid)


def _insert_item(ctx, user, bid, pos, it):
    doc_id = it.get("document_id")
    if doc_id and not docsvc.get_owned(ctx, user["id"], doc_id):
        raise BundleError("document_not_found", 404)
    dt = it.get("doc_type") if it.get("doc_type") in DOC_TYPES else None
    label = (it.get("label") or "").strip()[:120] or (DOC_TYPES[dt]["en"] if dt else "Document")
    ctx.db.insert("bundle_items", {"id": new_id(), "bundle_id": bid, "position": pos, "label": label, "doc_type": dt,
                                   "document_id": doc_id, "custom_filename": None, "selected": 1})


def list_bundles(ctx, user):
    rows = ctx.db.all("SELECT b.*, (SELECT COUNT(*) FROM bundle_items i WHERE i.bundle_id = b.id) AS n, "
                      "(SELECT COUNT(*) FROM bundle_items i WHERE i.bundle_id = b.id AND i.document_id IS NOT NULL) AS n_ready "
                      "FROM bundles b WHERE b.user_id = ? ORDER BY b.updated_at DESC", (user["id"],))
    return [{"id": r["id"], "name": r["name"], "items": r["n"], "ready": r["n_ready"], "created_at": r["created_at"],
             "updated_at": r["updated_at"]} for r in rows]


def get_row(ctx, user, bid):
    row = ctx.db.one("SELECT * FROM bundles WHERE id = ? AND user_id = ?", (bid, user["id"]))
    if not row:
        raise BundleError("not_found", 404)
    return row


def get(ctx, user, bid) -> dict:
    row = get_row(ctx, user, bid)
    items = []
    for it in ctx.db.all("SELECT * FROM bundle_items WHERE bundle_id = ? ORDER BY position", (bid,)):
        doc = docsvc.get_owned(ctx, user["id"], it["document_id"]) if it["document_id"] else None
        items.append({"id": it["id"], "position": it["position"], "label": it["label"], "doc_type": it["doc_type"],
                      "selected": bool(it["selected"]), "custom_filename": it["custom_filename"],
                      "document": docsvc.public(doc) if doc else None,
                      "download_filename": item_filename(it, doc) if doc else None})
    return {"id": row["id"], "name": row["name"], "checklist_id": row["checklist_id"], "created_at": row["created_at"],
            "updated_at": row["updated_at"], "items": items}


def update(ctx, user, bid, patch):
    get_row(ctx, user, bid)
    if "name" in patch and str(patch["name"]).strip():
        ctx.db.update("bundles", bid, {"name": str(patch["name"]).strip()[:120], "updated_at": now_iso()})
    return get(ctx, user, bid)


def add_item(ctx, user, bid, item):
    get_row(ctx, user, bid)
    pos = ctx.db.one("SELECT COALESCE(MAX(position), -1) + 1 AS p FROM bundle_items WHERE bundle_id = ?", (bid,))["p"]
    _insert_item(ctx, user, bid, pos, item)
    ctx.db.update("bundles", bid, {"updated_at": now_iso()})
    return get(ctx, user, bid)


def update_item(ctx, user, bid, item_id, patch):
    get_row(ctx, user, bid)
    it = ctx.db.one("SELECT * FROM bundle_items WHERE id = ? AND bundle_id = ?", (item_id, bid))
    if not it:
        raise BundleError("item_not_found", 404)
    values = {}
    if "custom_filename" in patch:
        v = (patch["custom_filename"] or "").strip()
        values["custom_filename"] = sanitize_filename(v) if v else None
    if "label" in patch and str(patch["label"]).strip():
        values["label"] = str(patch["label"]).strip()[:120]
    if "selected" in patch:
        values["selected"] = int(bool(patch["selected"]))
    if "document_id" in patch:
        did = patch["document_id"]
        if did and not docsvc.get_owned(ctx, user["id"], did):
            raise BundleError("document_not_found", 404)
        values["document_id"] = did or None
    if values:
        ctx.db.update("bundle_items", item_id, values)
        ctx.db.update("bundles", bid, {"updated_at": now_iso()})
    return get(ctx, user, bid)


def remove_item(ctx, user, bid, item_id):
    get_row(ctx, user, bid)
    ctx.db.execute("DELETE FROM bundle_items WHERE id = ? AND bundle_id = ?", (item_id, bid))
    for pos, r in enumerate(ctx.db.all("SELECT id FROM bundle_items WHERE bundle_id = ? ORDER BY position", (bid,))):
        ctx.db.execute("UPDATE bundle_items SET position = ? WHERE id = ?", (pos, r["id"]))
    return get(ctx, user, bid)


def delete(ctx, user, bid):
    get_row(ctx, user, bid)
    ctx.db.execute("DELETE FROM bundles WHERE id = ?", (bid,))  # documents themselves are untouched
    audit(ctx, user["id"], "bundle.delete", bid)


def item_file(ctx, user, bid, item_id) -> tuple[bytes, str, str]:
    get_row(ctx, user, bid)
    it = ctx.db.one("SELECT * FROM bundle_items WHERE id = ? AND bundle_id = ?", (item_id, bid))
    if not it or not it["document_id"]:
        raise BundleError("item_has_no_document", 404)
    doc = docsvc.get_owned(ctx, user["id"], it["document_id"])
    if not doc or not doc["is_local"]:
        raise BundleError("document_not_local", 409)
    audit(ctx, user["id"], "bundle.download_item", item_id, bundle=bid)
    return docsvc.read_bytes(ctx, doc), item_filename(it, doc), doc["mime_type"]


def combined_pdf(ctx, user, bid) -> tuple[bytes, str]:
    """Optional: merge selected items into one PDF (images become pages). Only on explicit request."""
    from PIL import Image, ImageOps
    from pypdf import PdfReader, PdfWriter
    b = get_row(ctx, user, bid)
    writer = PdfWriter()
    added = 0
    for it in ctx.db.all("SELECT * FROM bundle_items WHERE bundle_id = ? AND selected = 1 AND document_id IS NOT NULL "
                         "ORDER BY position", (bid,)):
        doc = docsvc.get_owned(ctx, user["id"], it["document_id"])
        if not doc or not doc["is_local"]:
            continue
        data = docsvc.read_bytes(ctx, doc)
        if doc["mime_type"] == "application/pdf":
            for page in PdfReader(io.BytesIO(data)).pages:
                writer.add_page(page)
            added += 1
        elif doc["mime_type"].startswith("image/") and doc["mime_type"] != "image/heic":
            img = ImageOps.exif_transpose(Image.open(io.BytesIO(data))).convert("RGB")
            buf = io.BytesIO()
            img.save(buf, "PDF", resolution=150)
            for page in PdfReader(io.BytesIO(buf.getvalue())).pages:
                writer.add_page(page)
            added += 1
    if not added:
        raise BundleError("nothing_to_combine", 409)
    out = io.BytesIO()
    writer.write(out)
    audit(ctx, user["id"], "bundle.download_combined", bid, files=added)
    return out.getvalue(), sanitize_filename(b["name"]) + ".pdf"
