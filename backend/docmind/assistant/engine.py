"""Dialogue engine: understands the request, runs discovery, manages task state and memory proposals."""
from __future__ import annotations

import json
from datetime import date

from ..db import new_id, now_iso
from ..knowledge.catalog import DOC_TYPES, PROCESSES, doc_type_label
from ..security import crypto
from ..services import memory as memsvc
from ..services import shared_learning
from . import discovery, intent as intent_mod
from .texts import join_list, t


class Conversation:
    def __init__(self, ctx, user, conv_id: str | None):
        self.ctx, self.user = ctx, user
        row = ctx.db.one("SELECT * FROM conversations WHERE id = ? AND user_id = ?", (conv_id, user["id"])) if conv_id else None
        if not row:
            row = {"id": new_id(), "user_id": user["id"], "title": None, "state_json": "{}",
                   "created_at": now_iso(), "updated_at": now_iso()}
            ctx.db.insert("conversations", row)
        self.row = row
        self.state = json.loads(row["state_json"])

    @property
    def id(self):
        return self.row["id"]

    def save(self, title: str | None = None):
        values = {"state_json": json.dumps(self.state, ensure_ascii=False), "updated_at": now_iso()}
        if title and not self.row["title"]:
            values["title"] = title[:80]
            self.row["title"] = values["title"]
        self.ctx.db.update("conversations", self.id, values)

    def add_message(self, dek, role, text, payload=None) -> str:
        mid = new_id()
        self.ctx.db.insert("messages", {
            "id": mid, "conversation_id": self.id, "role": role,
            "content_enc": crypto.encrypt_text(dek, text, f"msg:{mid}"),
            "payload_enc": crypto.encrypt_text(dek, json.dumps(payload, ensure_ascii=False), f"msgp:{mid}") if payload else None,
            "created_at": now_iso()})
        return mid


def load_messages(ctx, dek, conv_id) -> list[dict]:
    out = []
    for m in ctx.db.all("SELECT * FROM messages WHERE conversation_id = ? ORDER BY created_at, rowid", (conv_id,)):
        payload = json.loads(crypto.decrypt_text(dek, m["payload_enc"], f"msgp:{m['id']}")) if m["payload_enc"] else None
        out.append({"id": m["id"], "role": m["role"], "text": crypto.decrypt_text(dek, m["content_enc"], f"msg:{m['id']}"),
                    "payload": payload, "created_at": m["created_at"]})
    return out


class Engine:
    def __init__(self, ctx, user, dek):
        self.ctx, self.user, self.dek = ctx, user, dek
        self.settings = json.loads(user.get("settings_json") or "{}")

    # ---- entry point ------------------------------------------------------------------
    def respond(self, conv: Conversation, text: str) -> dict:
        text = (text or "").strip()[:2000]
        it = intent_mod.parse(text, self.user["locale"])
        self._maybe_llm(it)
        lang = it.lang
        conv.add_message(self.dek, "user", text)
        reply = self._route(conv, it, lang)
        reply["lang"] = lang
        reply["conversation_id"] = conv.id
        reply["message_id"] = conv.add_message(self.dek, "assistant", reply["text"],
                                               {k: v for k, v in reply.items() if k not in ("text", "conversation_id")})
        conv.save(title=text)
        return reply

    def _maybe_llm(self, it):
        llm = self.ctx.llm
        if not (llm.available and self.settings.get("ai_provider_consent")):
            return
        if it.doc_types or it.is_task or it.yes or it.no or it.greeting or it.help:
            return
        parsed = llm.parse_intent(it.free_text)  # request text only — never document contents
        if parsed:
            it.doc_types = parsed["doc_types"]
            it.process_key = parsed["process_key"]
            it.custom_purpose = parsed["custom_purpose"]
            it.is_task = bool(it.process_key or it.custom_purpose)

    def _route(self, conv, it, lang) -> dict:
        st = conv.state
        # 1) answer to a pending memory proposal
        if st.get("pending_proposal") and (it.yes or it.no) and not it.doc_types and not it.is_task:
            return self._resolve_proposal(conv, it.yes, lang)
        # 2) answering "which documents were required?"
        if st.get("awaiting_checklist") and not it.is_task:
            task = st["awaiting_checklist"]
            if it.doc_types:
                items = [{"doc_type": d, "label": doc_type_label(d, lang)} for d in it.doc_types]
                return self._run_task(conv, task, items, lang, checklist=None)
            if it.yes and task.get("suggested"):
                items = [{"doc_type": d, "label": doc_type_label(d, lang)} for d in task["suggested"]]
                return self._run_task(conv, task, items, lang, checklist=None)
            return self._ask_checklist(conv, task, lang, again=True)
        # 3) follow-ups inside an active task
        task = st.get("active_task")
        if task and it.doc_types and not it.is_task and not it.find_only:
            return self._add_to_task(conv, task, it.doc_types, lang)
        if task and (it.nothing_more or it.no) and not it.is_task:
            return self._task_complete(conv, task, lang)
        # 4) a new task
        if it.is_task:
            return self._start_task(conv, it, lang)
        # 5) plain find
        if it.doc_types:
            return self._find(conv, it.doc_types, lang)
        if it.greeting:
            return {"text": t("greeting", lang, name=self.user["display_name"]), "blocks": [],
                    "quick_replies": self._starter_replies(lang)}
        if it.help:
            return {"text": t("help", lang), "blocks": [], "quick_replies": self._starter_replies(lang)}
        # 6) free-text content search
        return self._free_search(it.free_text, lang)

    # ---- tasks ------------------------------------------------------------------------
    def _start_task(self, conv, it, lang):
        if it.process_key:
            pk = it.process_key
            label = PROCESSES[pk][lang]
        else:
            pk = "custom:" + memsvc.slug(it.custom_purpose)
            label = it.custom_purpose
        task = {"purpose_key": pk, "label": label}
        conv.state = {}
        checklist = memsvc.match_checklist(self.ctx, self.user["id"], pk if it.process_key else None, it.free_text)
        if checklist:
            memsvc.touch_checklist(self.ctx, checklist["id"])
            items = json.loads(checklist["items_json"])
            extra = [d for d in it.doc_types if d not in {i["doc_type"] for i in items}]
            task.update(purpose_key=checklist["purpose_key"], label=checklist["name"])
            reply = self._run_task(conv, task, items, lang, checklist=checklist)
            if extra:
                follow = self._add_to_task(conv, conv.state["active_task"], extra, lang)
                reply["blocks"] += follow["blocks"]
                reply["text"] += "\n\n" + follow["text"]
            return reply
        if it.doc_types:
            items = [{"doc_type": d, "label": doc_type_label(d, lang)} for d in it.doc_types]
            return self._run_task(conv, task, items, lang, checklist=None)
        return self._ask_checklist(conv, task, lang)

    def _suggested_for(self, purpose_key, exclude=()) -> list[str]:
        base = list(PROCESSES.get(purpose_key, {}).get("suggested", []))
        for d in shared_learning.suggestions(self.ctx, purpose_key):
            if d not in base:
                base.append(d)
        return [d for d in base if d not in exclude]

    def _suggestion_block(self, doc_types, lang):
        have = {r["doc_type"] for r in self.ctx.db.all(
            "SELECT DISTINCT doc_type FROM documents WHERE user_id = ? AND archived = 0", (self.user["id"],))}
        return {"type": "suggestions", "note": t("suggestions_note", lang),
                "items": [{"doc_type": d, "label": doc_type_label(d, lang), "in_library": d in have} for d in doc_types]}

    def _ask_checklist(self, conv, task, lang, again=False):
        suggested = self._suggested_for(task["purpose_key"])
        task["suggested"] = suggested
        conv.state = {"awaiting_checklist": task}
        blocks = [self._suggestion_block(suggested, lang)] if suggested else []
        quick = [{"label": t("use_suggestions", lang), "send": "כן" if lang == "he" else "yes"}] if suggested else []
        quick += [{"label": doc_type_label(d, lang), "send": doc_type_label(d, lang)} for d in suggested[:5]]
        key = "ask_checklist_again" if again else "ask_checklist"
        return {"text": t(key, lang, task=task["label"]), "blocks": blocks, "quick_replies": quick}

    def _search(self, items, lang):
        plan = discovery.search_plan(self.ctx, self.user)
        results = [discovery.find_requirement(self.ctx, self.user, self.dek, plan, i.get("doc_type"), i["label"], lang)
                   for i in items]
        return plan, results

    def _summary(self, plan, results, lang) -> list[str]:
        found = sum(1 for r in results if r["status"].startswith("found"))
        lines = [t("searched_summary", lang, found=found, total=len(results),
                   sources=join_list([s["label"][lang] for s in plan["searched"]], lang))]
        missing = [s for s in plan["unavailable"] if s["state"] in ("not_connected",)]
        if missing and found < len(results):
            lines.append(t("not_searched", lang, sources=join_list([s["label"][lang] for s in missing], lang)))
        if plan["failed"]:
            lines.append(t("search_failed", lang, sources=join_list([s["label"][lang] for s in plan["failed"]], lang)))
        outdated = sum(1 for r in results if r.get("freshness", {}).get("state") in ("expired", "maybe_outdated"))
        if outdated:
            lines.append(t("outdated_note", lang, n=outdated))
        return lines

    def _results_block(self, plan, results, title=None):
        return {"type": "requirements", "title": title, "results": results,
                "sources_searched": plan["searched"], "sources_unavailable": plan["unavailable"],
                "sources_failed": plan["failed"]}

    def _bundle_action(self, task_label, results, lang):
        items = [{"label": r["requirement"]["label"], "doc_type": r["requirement"]["doc_type"],
                  "document_id": r["best"]["document"]["id"] if r["best"] and r["best"].get("document") else None}
                 for r in results]
        return {"type": "create_bundle", "label": t("create_bundle", lang),
                "payload": {"name": f"{task_label} – {date.today().strftime('%d.%m.%Y')}", "items": items}}

    def _run_task(self, conv, task, items, lang, checklist):
        plan, results = self._search(items, lang)
        task = {**task, "items": items, "checklist_id": checklist["id"] if checklist else None}
        conv.state = {"active_task": task}
        lines = []
        if checklist:
            lines.append(t("remembered", lang, name=checklist["name"], n=len(items)))
        lines += self._summary(plan, results, lang)
        blocks = [self._results_block(plan, results, task["label"])]
        suggested = self._suggested_for(task["purpose_key"], exclude={i.get("doc_type") for i in items})
        if suggested:
            blocks.append(self._suggestion_block(suggested, lang))
        actions = [self._bundle_action(task["label"], results, lang)]
        if not checklist:
            prop = memsvc.propose(self.ctx, self.user["id"], "create_checklist",
                                  {"name": task["label"], "purpose_key": task["purpose_key"], "items": items})
            conv.state["pending_proposal"] = prop["id"]
            blocks.append({"type": "proposal", "proposal": prop, "question": t("propose_save", lang, task=task["label"]),
                           "accept_label": t("remember_yes", lang), "reject_label": t("remember_no", lang)})
            lines.append(t("additional", lang))
        else:
            lines.append(t("anything_changed", lang))
        quick = [{"label": t("nothing_more", lang), "send": "זה הכל" if lang == "he" else "that's all"}]
        quick += [{"label": "+ " + doc_type_label(d, lang),
                   "send": ("צריך גם " if lang == "he" else "also ") + doc_type_label(d, lang)} for d in suggested[:3]]
        return {"text": "\n".join(lines), "blocks": blocks, "actions": actions, "quick_replies": quick}

    def _add_to_task(self, conv, task, doc_types, lang):
        existing = {i.get("doc_type") for i in task["items"]}
        new = [{"doc_type": d, "label": doc_type_label(d, lang)} for d in doc_types if d not in existing]
        if not new:
            return {"text": t("additional", lang), "blocks": [], "quick_replies": []}
        plan, results = self._search(new, lang)
        task["items"] = task["items"] + new
        conv.state["active_task"] = task
        lines = [t("added_items", lang, items=join_list([n["label"] for n in new], lang))] + self._summary(plan, results, lang)
        blocks = [self._results_block(plan, results)]
        if task.get("checklist_id"):
            row = memsvc.get_checklist(self.ctx, self.user["id"], task["checklist_id"])
            if row:
                prop = memsvc.propose(self.ctx, self.user["id"], "update_checklist",
                                      {"checklist_id": row["id"], "name": row["name"], "purpose_key": row["purpose_key"],
                                       "items": task["items"], "added": new})
                conv.state["pending_proposal"] = prop["id"]
                blocks.append({"type": "proposal", "proposal": prop,
                               "question": t("propose_update", lang, name=row["name"],
                                             added=join_list([n["label"] for n in new], lang)),
                               "accept_label": t("update_yes", lang), "reject_label": t("update_no", lang)})
        else:
            prop = memsvc.propose(self.ctx, self.user["id"], "create_checklist",
                                  {"name": task["label"], "purpose_key": task["purpose_key"], "items": task["items"]})
            conv.state["pending_proposal"] = prop["id"]
            blocks.append({"type": "proposal", "proposal": prop, "question": t("propose_save", lang, task=task["label"]),
                           "accept_label": t("remember_yes", lang), "reject_label": t("remember_no", lang)})
        lines.append(t("additional", lang))
        # Re-run the full list so the bundle action covers every item.
        _, all_results = self._search(task["items"], lang)
        return {"text": "\n".join(lines), "blocks": blocks, "actions": [self._bundle_action(task["label"], all_results, lang)],
                "quick_replies": [{"label": t("nothing_more", lang), "send": "זה הכל" if lang == "he" else "that's all"}]}

    def _task_complete(self, conv, task, lang):
        _, results = self._search(task["items"], lang)
        return {"text": t("complete", lang), "blocks": [], "actions": [self._bundle_action(task["label"], results, lang)],
                "quick_replies": []}

    def _resolve_proposal(self, conv, accept, lang):
        pid = conv.state.pop("pending_proposal")
        try:
            res = memsvc.resolve_proposal(self.ctx, self.user, pid, accept)
        except memsvc.MemoryError_:
            return {"text": t("additional", lang), "blocks": []}
        task = conv.state.get("active_task") or {}
        if accept and res.get("checklist_id"):
            task["checklist_id"] = res["checklist_id"]
            conv.state["active_task"] = task
        key = ("saved" if res["kind"] == "create_checklist" else "updated") if accept else "not_saved"
        text = t(key, lang, task=task.get("label", "")) + "\n" + t("additional", lang)
        return {"text": text, "blocks": [],
                "quick_replies": [{"label": t("nothing_more", lang), "send": "זה הכל" if lang == "he" else "that's all"}]}

    # ---- find / search -----------------------------------------------------------------
    def _find(self, conv, doc_types, lang):
        items = [{"doc_type": d, "label": doc_type_label(d, lang)} for d in doc_types]
        plan, results = self._search(items, lang)
        lines = [t("find_summary", lang, sources=join_list([s["label"][lang] for s in plan["searched"]], lang))]
        lines += self._summary(plan, results, lang)[1:]
        lines.append(t("anything_else", lang))
        actions = [self._bundle_action(join_list([i["label"] for i in items], lang)[:60], results, lang)] if len(items) > 1 else []
        return {"text": "\n".join(lines), "blocks": [self._results_block(plan, results)], "actions": actions,
                "quick_replies": []}

    def _free_search(self, text, lang):
        n = self.ctx.db.one("SELECT COUNT(*) n FROM documents WHERE user_id = ? AND archived = 0", (self.user["id"],))["n"]
        if not n:
            return {"text": t("empty_library", lang), "blocks": [], "actions": [{"type": "open_upload", "label": "+"}]}
        from ..services import documents as docsvc
        hits = self.ctx.search.search(self.user["id"], self.dek, text, limit=6, min_score=0.12)
        if not hits:
            return {"text": t("free_none", lang), "blocks": [], "quick_replies": self._starter_replies(lang)}
        return {"text": t("free_results", lang),
                "blocks": [{"type": "documents", "documents": [{**docsvc.public(d), "score": round(s, 3)} for d, s in hits]}]}

    def _starter_replies(self, lang):
        if lang == "he":
            return [{"label": "מסמכים למלגת מילואים", "send": "אני צריך מסמכים למלגת מילואים"},
                    {"label": "אישור ניהול חשבון", "send": "תמצא לי את אישור ניהול החשבון"},
                    {"label": "תעודת זהות וספח", "send": "תמצא את תעודת הזהות והספח"}]
        return [{"label": "Reserve scholarship documents", "send": "I need documents for a military reserve scholarship"},
                {"label": "Bank confirmation", "send": "Find my latest bank confirmation"},
                {"label": "ID card + appendix", "send": "Find my identity card and appendix"}]


__all__ = ["Engine", "Conversation", "load_messages", "DOC_TYPES"]
