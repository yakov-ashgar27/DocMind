from flask import g, jsonify

from ..security.auth import require_auth
from ..services import bundles as bundlesvc
from . import api, body, ctx, sign_link


@api.get("/bundles")
@require_auth
def list_bundles():
    return jsonify(bundles=bundlesvc.list_bundles(ctx(), g.user))


@api.post("/bundles")
@require_auth
def create_bundle():
    b = body()
    return jsonify(bundle=bundlesvc.create(ctx(), g.user, b.get("name"), b.get("items") or [], b.get("checklist_id"))), 201


@api.get("/bundles/<bid>")
@require_auth
def get_bundle(bid):
    return jsonify(bundle=bundlesvc.get(ctx(), g.user, bid))


@api.patch("/bundles/<bid>")
@require_auth
def patch_bundle(bid):
    return jsonify(bundle=bundlesvc.update(ctx(), g.user, bid, body()))


@api.delete("/bundles/<bid>")
@require_auth
def delete_bundle(bid):
    bundlesvc.delete(ctx(), g.user, bid)
    return jsonify(ok=True)


@api.post("/bundles/<bid>/items")
@require_auth
def add_item(bid):
    return jsonify(bundle=bundlesvc.add_item(ctx(), g.user, bid, body())), 201


@api.patch("/bundles/<bid>/items/<iid>")
@require_auth
def patch_item(bid, iid):
    return jsonify(bundle=bundlesvc.update_item(ctx(), g.user, bid, iid, body()))


@api.delete("/bundles/<bid>/items/<iid>")
@require_auth
def delete_item(bid, iid):
    return jsonify(bundle=bundlesvc.remove_item(ctx(), g.user, bid, iid))


@api.post("/bundles/<bid>/links")
@require_auth
def bundle_links(bid):
    """Signed links for each selected file — the client downloads them one by one as separate files."""
    bundle = bundlesvc.get(ctx(), g.user, bid)
    only = set(body().get("item_ids") or [])
    for it in bundle["items"]:
        if ((only and it["id"] in only) or (not only and it["selected"])) and it["document"] \
                and it["document"]["category_key"] in g.hidden_cats:
            return jsonify(error="vault_locked"), 423
    links = []
    for it in bundle["items"]:
        if (only and it["id"] not in only) or (not only and not it["selected"]):
            continue
        if it["document"] and it["document"]["is_local"]:
            links.append({"item_id": it["id"], "filename": it["download_filename"],
                          "url": sign_link(g.user["id"], "bundle_item", {"b": bid, "i": it["id"]})})
    return jsonify(links=links)


@api.post("/bundles/<bid>/combined-link")
@require_auth
def combined_link(bid):
    bundle = bundlesvc.get(ctx(), g.user, bid)
    if any(it["selected"] and it["document"] and it["document"]["category_key"] in g.hidden_cats for it in bundle["items"]):
        return jsonify(error="vault_locked"), 423
    return jsonify(url=sign_link(g.user["id"], "bundle_pdf", {"b": bid}))
