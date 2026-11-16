"""Personal memory. Checklists are only created or changed through explicit user confirmation
(proposals) or explicit edits in the Memory screen — never silently by the assistant."""
from __future__ import annotations

import json
import re

from ..db import new_id, now_iso
from ..knowledge.catalog import DOC_TYPES, doc_type_label
from ..security.audit import audit


class MemoryError_(Exception):
    def __init__(self, code: str, status: int = 400):
        super().__init__(code)
        self.code = code
        self.status = status


def _clean_items(items: list[dict], lang: str = "en") -> list[dict]:
    out, seen = [], set()
    for it in items or []:
        dt = it.get("doc_type") or None
        if dt and dt not in DOC_TYPES:
            dt = None
        label = (it.get("label") or (doc_type_label(dt, lang) if dt else "")).strip()[:120]
        if not label:
            continue
        key = dt or label.lower()
        if key in seen:
            continue
        seen.add(key)
        out.append({"doc_type": dt, "label": label, "note": (it.get("note") or "").strip()[:300] or None})
    return out


def checklist_public(row: dict) -> dict:
    return {**{k: row[k] for k in ("id", "name", "purpose_key", "version", "use_count", "created_at", "updated_at",
                                    "last_used_at")}, "items": json.loads(row["items_json"])}


def list_checklists(ctx, user_id):
    return [checklist_public(r) for r in ctx.db.all(
        "SELECT * FROM checklists WHERE user_id = ? ORDER BY COALESCE(last_used_at, updated_at) DESC", (user_id,))]


def get_checklist(ctx, user_id, cid):
    return ctx.db.one("SELECT * FROM checklists WHERE id = ? AND user_id = ?", (cid, user_id))


def _create_checklist(ctx, user_id, name, purpose_key, items):
    cid = new_id()
    ts = now_iso()
    ctx.db.insert("checklists", {"id": cid, "user_id": user_id, "name": name[:120], "purpose_key": purpose_key,
                                 "items_json": json.dumps(items, ensure_ascii=False), "version": 1, "use_count": 1,
                                 "created_at": ts, "updated_at": ts, "last_used_at": ts})
    return cid


def create_checklist_explicit(ctx, user, name, purpose_key, items, lang):
    items = _clean_items(items, lang)
    if not name or not items:
        raise MemoryError_("invalid_checklist")
    cid = _create_checklist(ctx, user["id"], name.strip(), purpose_key or "custom:" + slug(name), items)
    audit(ctx, user["id"], "memory.checklist_create", cid)
    return checklist_public(get_checklist(ctx, user["id"], cid))


def edit_checklist(ctx, user, row, patch, lang):
    values = {}
    if "name" in patch and str(patch["name"]).strip():
        values["name"] = str(patch["name"]).strip()[:120]
    if "items" in patch:
        items = _clean_items(patch["items"], lang)
        if not items:
            raise MemoryError_("checklist_needs_items")
        values["items_json"] = json.dumps(items, ensure_ascii=False)
        values["version"] = row["version"] + 1
    if values:
        values["updated_at"] = now_iso()
        ctx.db.update("checklists", row["id"], values)
        audit(ctx, user["id"], "memory.checklist_edit", row["id"], fields=sorted(values))
    return checklist_public(get_checklist(ctx, user["id"], row["id"]))


def delete_checklist(ctx, user, row):
    ctx.db.execute("DELETE FROM checklists WHERE id = ?", (row["id"],))
    audit(ctx, user["id"], "memory.checklist_delete", row["id"])


def touch_checklist(ctx, cid):
    ctx.db.execute("UPDATE checklists SET use_count = use_count + 1, last_used_at = ? WHERE id = ?", (now_iso(), cid))


# ---- proposals ---------------------------------------------------------------------------
def propose(ctx, user_id, kind, payload) -> dict:
    # Supersede earlier pending proposals for the same purpose so the user sees one decision.
    for p in ctx.db.all("SELECT * FROM memory_proposals WHERE user_id = ? AND status = 'pending'", (user_id,)):
        if json.loads(p["payload_json"]).get("purpose_key") == payload.get("purpose_key"):
            ctx.db.execute("UPDATE memory_proposals SET status = 'superseded', resolved_at = ? WHERE id = ?",
                           (now_iso(), p["id"]))
    pid = new_id()
    ctx.db.insert("memory_proposals", {"id": pid, "user_id": user_id, "kind": kind,
                                       "payload_json": json.dumps(payload, ensure_ascii=False),
                                       "status": "pending", "created_at": now_iso()})
    return {"id": pid, "kind": kind, **payload}


def pending_proposals(ctx, user_id):
    return [{"id": p["id"], "kind": p["kind"], "created_at": p["created_at"], **json.loads(p["payload_json"])}
            for p in ctx.db.all("SELECT * FROM memory_proposals WHERE user_id = ? AND status = 'pending' "
                                "ORDER BY created_at DESC", (user_id,))]


def resolve_proposal(ctx, user, pid, accept: bool) -> dict:
    p = ctx.db.one("SELECT * FROM memory_proposals WHERE id = ? AND user_id = ?", (pid, user["id"]))
    if not p:
        raise MemoryError_("not_found", 404)
    if p["status"] != "pending":
        raise MemoryError_("already_resolved", 409)
    payload = json.loads(p["payload_json"])
    result = {"status": "accepted" if accept else "rejected", "kind": p["kind"]}
    if accept:
        if p["kind"] == "create_checklist":
            cid = _create_checklist(ctx, user["id"], payload["name"], payload["purpose_key"], payload["items"])
            result["checklist_id"] = cid
        elif p["kind"] == "update_checklist":
            row = get_checklist(ctx, user["id"], payload["checklist_id"])
            if not row:
                raise MemoryError_("checklist_gone", 409)
            ctx.db.update("checklists", row["id"], {"items_json": json.dumps(payload["items"], ensure_ascii=False),
                                                    "version": row["version"] + 1, "updated_at": now_iso()})
            result["checklist_id"] = row["id"]
        from . import shared_learning
        shared_learning.contribute(ctx, user, payload.get("purpose_key", ""), [i.get("doc_type") for i in payload["items"]])
    ctx.db.execute("UPDATE memory_proposals SET status = ?, resolved_at = ? WHERE id = ?",
                   (result["status"], now_iso(), pid))
    audit(ctx, user["id"], f"memory.proposal_{result['status']}", pid, kind=p["kind"])
    return result


# ---- matching -----------------------------------------------------------------------------
def slug(text: str) -> str:
    t = re.sub(r"[^\w֐-׿]+", "-", text.lower()).strip("-")
    return t[:60] or "task"


def _grams(s: str) -> set[str]:
    s = re.sub(r"\s+", " ", s.lower())
    return {s[i:i + 3] for i in range(max(0, len(s) - 2))}


def match_checklist(ctx, user_id, purpose_key: str | None, text: str) -> dict | None:
    rows = ctx.db.all("SELECT * FROM checklists WHERE user_id = ?", (user_id,))
    if purpose_key:
        for r in rows:
            if r["purpose_key"] == purpose_key:
                return r
    best, best_s = None, 0.0
    g = _grams(text)
    for r in rows:
        rg = _grams(r["name"])
        if not rg:
            continue
        s = len(g & rg) / len(rg)  # how much of the saved name appears in the request
        if s > best_s:
            best, best_s = r, s
    return best if best_s >= 0.7 else None


# ---- other memory facts --------------------------------------------------------------------
def remember_location(ctx, user, doc_type, source_key):
    settings = json.loads(user.get("settings_json") or "{}")
    if not settings.get("remember_locations", True) or not doc_type:
        return
    ts = now_iso()
    ctx.db.execute(
        "INSERT INTO memory_facts (id, user_id, kind, key, value_json, created_at, updated_at) VALUES (?,?,?,?,?,?,?) "
        "ON CONFLICT(user_id, kind, key) DO UPDATE SET value_json = excluded.value_json, updated_at = excluded.updated_at",
        (new_id(), user["id"], "doc_location", doc_type, json.dumps({"source": source_key}), ts, ts))


def location_for(ctx, user_id, doc_type):
    r = ctx.db.one("SELECT value_json, updated_at FROM memory_facts WHERE user_id = ? AND kind = 'doc_location' AND key = ?",
                   (user_id, doc_type))
    return {**json.loads(r["value_json"]), "at": r["updated_at"]} if r else None


def list_facts(ctx, user_id):
    return [{"id": r["id"], "kind": r["kind"], "key": r["key"], "value": json.loads(r["value_json"]),
             "updated_at": r["updated_at"]}
            for r in ctx.db.all("SELECT * FROM memory_facts WHERE user_id = ? ORDER BY updated_at DESC", (user_id,))]


def delete_fact(ctx, user, fid):
    ctx.db.execute("DELETE FROM memory_facts WHERE id = ? AND user_id = ?", (fid, user["id"]))
    audit(ctx, user["id"], "memory.fact_delete", fid)


def wipe(ctx, user):
    ctx.db.execute("DELETE FROM checklists WHERE user_id = ?", (user["id"],))
    ctx.db.execute("DELETE FROM memory_facts WHERE user_id = ?", (user["id"],))
    ctx.db.execute("DELETE FROM memory_proposals WHERE user_id = ?", (user["id"],))
    audit(ctx, user["id"], "memory.wipe")
