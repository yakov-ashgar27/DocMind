"""Cross-source discovery. Searches EVERY searchable connector in the mandated order before any
requirement can be declared "not found", de-duplicates, and attaches acquisition guidance only
after the full search."""
from __future__ import annotations

import logging

from ..connectors.base import registry
from ..connectors.google import ConnectorError
from ..knowledge.catalog import acquisition_for, doc_type_label
from ..services import classifier
from ..services import memory as memsvc

log = logging.getLogger(__name__)

STATUS_ORDER = ["found_local", "found_whatsapp", "found_gmail", "found_gdrive", "found_external_not_downloaded"]


def search_plan(ctx, user) -> dict:
    searched, unavailable, failed = [], [], []
    conns = []
    for c in registry(ctx):
        a = c.availability(ctx, user)
        entry = {"key": c.key, "label": c.label, "state": a.state, "order": c.order}
        if a.searchable:
            searched.append(entry)
            conns.append(c)
        else:
            unavailable.append(entry)
    return {"connectors": conns, "searched": searched, "unavailable": unavailable, "failed": failed}


def find_requirement(ctx, user, dek, plan, doc_type: str | None, label: str, lang: str) -> dict:
    hits = []
    for c in plan["connectors"]:
        try:
            hits.extend(c.find(ctx, user, dek, doc_type, label))
        except ConnectorError as e:
            log.warning("connector %s failed: %s", c.key, e.code)
            if not any(f["key"] == c.key for f in plan["failed"]):
                plan["failed"].append({"key": c.key, "label": c.label, "error": e.code})
    hits = _dedupe(hits)
    hits.sort(key=lambda h: (h.match == "content_match", STATUS_ORDER.index(h.status)
                              if h.status in STATUS_ORDER else 99, -h.score))
    req = {"doc_type": doc_type, "label": label or doc_type_label(doc_type, lang)}
    if not hits:
        complete = not plan["failed"]
        return {"requirement": req, "status": "not_found" if complete else "search_incomplete",
                "best": None, "alternatives": [],
                "acquisition": acquisition_for(doc_type, lang) if (doc_type and complete) else None,
                "previously_found_in": memsvc.location_for(ctx, user["id"], doc_type) if doc_type else None}
    best = hits[0]
    fresh = classifier.freshness(best.document) if best.document else {"state": "unknown"}
    return {"requirement": req, "status": best.status, "best": best.to_dict(),
            "alternatives": [h.to_dict() for h in hits[1:4]], "freshness": fresh,
            "uncertain": best.match == "content_match",
            "acquisition": None,
            "previously_found_in": memsvc.location_for(ctx, user["id"], doc_type) if doc_type else None}


def _dedupe(hits):
    seen_docs, seen_ext, local_names = set(), set(), set()
    out = []
    for h in hits:
        if h.document:
            if h.document["id"] in seen_docs:
                continue
            seen_docs.add(h.document["id"])
            local_names.add((h.document["original_filename"].lower(), h.document["size_bytes"]))
            out.append(h)
    for h in hits:
        if h.external:
            key = (h.external.get("kind"), h.external.get("ref"))
            name_size = ((h.external.get("filename") or "").lower(), int(h.external.get("size") or -1))
            if key in seen_ext or name_size in local_names:
                continue
            seen_ext.add(key)
            out.append(h)
    return out
