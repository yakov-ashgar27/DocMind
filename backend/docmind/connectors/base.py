"""Source connectors, searched in the product's mandated order.

Every connector reports *honest* availability. A source that is not connected, not configured, or
needs the native app is listed as such and is never presented as searched.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from ..knowledge.catalog import DOC_TYPES, REQUEST_ALIASES
from ..services import documents as docsvc


@dataclass
class Hit:
    source: str            # connector key
    status: str            # found_local | found_whatsapp | found_gmail | found_gdrive | found_external_not_downloaded
    score: float
    match: str             # exact_type | content_match
    document: dict | None = None      # library document (public view)
    external: dict | None = None      # external reference (not downloaded yet)

    def to_dict(self):
        return {"source": self.source, "status": self.status, "score": round(self.score, 3), "match": self.match,
                "document": self.document, "external": self.external}


@dataclass
class Availability:
    state: str          # connected | not_connected | not_configured | requires_native_app | always
    searchable: bool
    detail: dict = field(default_factory=dict)


class Connector:
    key = ""
    order = 0
    label = {"en": "", "he": ""}
    stage = 1

    def availability(self, ctx, user) -> Availability:
        raise NotImplementedError

    def find(self, ctx, user, dek, doc_type: str | None, query: str) -> list[Hit]:
        return []

    def describe(self, ctx, user) -> dict:
        a = self.availability(ctx, user)
        return {"key": self.key, "order": self.order, "label": self.label, "stage": self.stage,
                "state": a.state, "searchable": a.searchable, **a.detail}


class LibraryConnector(Connector):
    """Documents stored (encrypted) in DocMind, filtered by how they arrived."""
    source_kinds: tuple[str, ...] = ()
    found_status = "found_local"

    def find(self, ctx, user, dek, doc_type, query):
        kinds = ",".join("?" for _ in self.source_kinds)
        hits: list[Hit] = []
        if doc_type and doc_type != "unknown":
            rows = ctx.db.all(
                f"SELECT * FROM documents WHERE user_id = ? AND doc_type = ? AND archived = 0 AND status = 'ready' "
                f"AND duplicate_of IS NULL AND source_kind IN ({kinds}) "
                f"ORDER BY COALESCE(doc_date, substr(created_at,1,10)) DESC, doc_type_confidence DESC",
                (user["id"], doc_type, *self.source_kinds))
            hits += [Hit(self.key, self.found_status, r["doc_type_confidence"], "exact_type", docsvc.public(r))
                     for r in rows]
        if not hits:
            # Fall back to content search (unclear filenames, unclassified docs, OCR'd text).
            q = query
            if doc_type in DOC_TYPES:
                q = " ".join([DOC_TYPES[doc_type]["en"], DOC_TYPES[doc_type]["he"], *REQUEST_ALIASES.get(doc_type, [])])
            for d, s in ctx.search.search(user["id"], dek, q, limit=5, min_score=0.22):
                if d["source_kind"] in self.source_kinds and d["duplicate_of"] is None:
                    if doc_type and d["doc_type"] not in ("unknown", doc_type):
                        continue  # confidently a different type
                    hits.append(Hit(self.key, self.found_status, s, "content_match", docsvc.public(d)))
        return hits


class DeviceUploadsConnector(LibraryConnector):
    key = "device_files"
    order = 1
    label = {"en": "Files on this device (uploaded)", "he": "קבצים מהמכשיר (שהועלו)"}
    source_kinds = ("upload",)
    found_status = "found_local"

    def availability(self, ctx, user):
        n = ctx.db.one("SELECT COUNT(*) n FROM documents WHERE user_id = ? AND source_kind = 'upload'", (user["id"],))["n"]
        return Availability("always", True, {"documents": n})


class NativeOnlyConnector(Connector):
    """Gallery / Downloads scanning needs Android storage permissions in the native app."""
    stage = 3

    def availability(self, ctx, user):
        return Availability("requires_native_app", False)


class GalleryConnector(NativeOnlyConnector):
    key = "gallery"
    order = 2
    label = {"en": "Photo gallery", "he": "גלריית תמונות"}


class DownloadsConnector(NativeOnlyConnector):
    key = "downloads"
    order = 3
    label = {"en": "Downloads & folders", "he": "הורדות ותיקיות"}


class WhatsAppImportConnector(LibraryConnector):
    key = "whatsapp"
    order = 4
    label = {"en": "WhatsApp (imported chats)", "he": "וואטסאפ (צ'אטים שיובאו)"}
    source_kinds = ("whatsapp_import",)
    found_status = "found_whatsapp"

    def availability(self, ctx, user):
        n = ctx.db.one("SELECT COUNT(*) n FROM documents WHERE user_id = ? AND source_kind = 'whatsapp_import'",
                       (user["id"],))["n"]
        return Availability("connected" if n else "not_connected", n > 0, {"documents": n, "mode": "export_import"})


def registry(ctx) -> list[Connector]:
    from .google import DriveConnector, GmailConnector
    return sorted([DeviceUploadsConnector(), GalleryConnector(), DownloadsConnector(), WhatsAppImportConnector(),
                   GmailConnector(), DriveConnector()], key=lambda c: c.order)
