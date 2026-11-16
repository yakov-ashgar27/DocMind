from flask import g, jsonify

from ..security.auth import require_auth
from ..services import memory as memsvc
from . import api, body, ctx


def _lang():
    return g.user["locale"]


@api.get("/memory")
@require_auth
def memory_overview():
    c = ctx()
    facts = [f for f in memsvc.list_facts(c, g.user["id"])]
    return jsonify(checklists=memsvc.list_checklists(c, g.user["id"]), facts=facts,
                   proposals=memsvc.pending_proposals(c, g.user["id"]))


@api.post("/memory/checklists")
@require_auth
def create_checklist():
    b = body()
    return jsonify(checklist=memsvc.create_checklist_explicit(ctx(), g.user, b.get("name"), b.get("purpose_key"),
                                                              b.get("items") or [], _lang())), 201


@api.patch("/memory/checklists/<cid>")
@require_auth
def edit_checklist(cid):
    row = memsvc.get_checklist(ctx(), g.user["id"], cid)
    if not row:
        return jsonify(error="not_found"), 404
    return jsonify(checklist=memsvc.edit_checklist(ctx(), g.user, row, body(), _lang()))


@api.delete("/memory/checklists/<cid>")
@require_auth
def delete_checklist(cid):
    row = memsvc.get_checklist(ctx(), g.user["id"], cid)
    if not row:
        return jsonify(error="not_found"), 404
    memsvc.delete_checklist(ctx(), g.user, row)
    return jsonify(ok=True)


@api.post("/memory/proposals/<pid>")
@require_auth
def resolve_proposal(pid):
    return jsonify(memsvc.resolve_proposal(ctx(), g.user, pid, bool(body().get("accept"))))


@api.delete("/memory/facts/<fid>")
@require_auth
def delete_fact(fid):
    memsvc.delete_fact(ctx(), g.user, fid)
    return jsonify(ok=True)


@api.delete("/memory")
@require_auth
def wipe_memory():
    if body().get("confirm") is not True:
        return jsonify(error="confirmation_required"), 400
    memsvc.wipe(ctx(), g.user)
    return jsonify(ok=True)
