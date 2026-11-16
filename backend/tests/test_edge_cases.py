"""Robustness: bad input, hostile input, odd user behaviour. Nothing here may crash or leak."""
import io
import time

import jwt

from tests.conftest import Session


def up(s, data, name):
    return s.post("/api/documents", data={"files": [(io.BytesIO(data), name)]}, content_type="multipart/form-data")


def test_empty_and_plain_text_uploads(session):
    assert up(session, b"", "empty.pdf").status_code == 400
    r = up(session, "אישור לימודים\nהנו סטודנט מן המניין בשנת הלימודים".encode(), "note.txt")
    assert r.status_code == 201
    d = session.get(f"/api/documents/{r.json['documents'][0]['id']}").json["document"]
    assert d["status"] == "ready" and d["doc_type"] == "enrollment_proof"


def test_corrupt_pdf_fails_gracefully_and_can_be_reprocessed(session):
    r = up(session, b"%PDF-1.4 this is not really a pdf", "broken.pdf")
    assert r.status_code == 201
    d = session.get(f"/api/documents/{r.json['documents'][0]['id']}").json["document"]
    assert d["status"] in ("ready", "failed")  # never stuck in processing, never a 500
    assert session.post(f"/api/documents/{d['id']}/reprocess").status_code == 200
    assert session.get("/api/dashboard").status_code == 200


def test_oversized_upload_rejected(session, ctx):
    ctx.config.max_upload_bytes = 1000
    r = up(session, b"%PDF-1.4" + b"0" * 2000, "big.pdf")
    assert r.status_code == 400 and r.json["errors"][0]["error"] == "file_too_large"


def test_hostile_filenames_are_sanitised(session):
    r = up(session, b"just text", "../../etc/<script>passwd.txt")
    name = r.json["documents"][0]["original_filename"]
    assert "/" not in name and "<" not in name and name.endswith(".txt")


def test_static_path_traversal_blocked(client):
    for p in ("/../backend/run.py", "/%2e%2e/backend/run.py", "/..%2fbackend/docmind/config.py"):
        r = client.get(p)
        assert b"load_config" not in r.data and b"create_app" not in r.data


def test_unknown_api_route_is_json_404(client):
    r = client.get("/api/nope")
    assert r.status_code == 404 and r.json["error"] == "not_found"


def test_expired_and_forged_tokens(client, ctx):
    s = Session(client, email="tok@example.com")
    payload = {"sub": s.user["id"], "tv": 0, "typ": "access", "iat": 0, "exp": int(time.time()) - 5}
    expired = jwt.encode(payload, ctx.config.jwt_secret, algorithm="HS256")
    assert client.get("/api/me", headers={"Authorization": f"Bearer {expired}"}).status_code == 401
    forged = jwt.encode({**payload, "exp": int(time.time()) + 600}, "wrong-secret-wrong-secret-wrong-secret!", algorithm="HS256")
    assert client.get("/api/me", headers={"Authorization": f"Bearer {forged}"}).status_code == 401
    none_alg = jwt.encode({**payload, "exp": int(time.time()) + 600}, None, algorithm="none")
    assert client.get("/api/me", headers={"Authorization": f"Bearer {none_alg}"}).status_code == 401
    # A download link token must not work as an access token.
    doc = s.upload("download (3).pdf")[0]
    link = s.post(f"/api/documents/{doc['id']}/link", json={}).json["url"].rsplit("/", 1)[1]
    assert client.get("/api/me", headers={"Authorization": f"Bearer {link}"}).status_code == 401


def test_assistant_odd_messages(library):
    assert library.post("/api/assistant/message", json={"text": "   "}).status_code == 400
    assert library.post("/api/assistant/message", json={}).status_code == 400
    for text in ("🙂🙂", "x" * 5000, "?", "<img src=x onerror=alert(1)>", "תעודת זהות תעודת זהות תעודת זהות"):
        r = library.post("/api/assistant/message", json={"text": text})
        assert r.status_code == 200 and r.json["text"]
    r = library.post("/api/assistant/message", json={"text": "hello", "conversation_id": "does-not-exist"})
    assert r.status_code == 200 and r.json["conversation_id"] != "does-not-exist"


def test_cannot_touch_other_users_conversation(client):
    a = Session(client, email="ca@example.com")
    a.say("find my passport", new=True)
    b = Session(client, email="cb@example.com")
    assert b.get(f"/api/conversations/{a.conv}").status_code == 404
    r = b.post("/api/assistant/message", json={"text": "hi", "conversation_id": a.conv})
    assert r.json["conversation_id"] != a.conv
    assert a.get(f"/api/conversations/{a.conv}").json["messages"][0]["text"] == "find my passport"


def test_proposal_cannot_be_resolved_twice_or_by_others(client, library):
    library.say("I need documents for my reserve benefits", new=True)
    r = library.say("identity card and bank confirmation")
    pid = [b for b in r["blocks"] if b["type"] == "proposal"][0]["proposal"]["id"]
    other = Session(client, email="other@example.com")
    assert other.post(f"/api/memory/proposals/{pid}", json={"accept": True}).status_code == 404
    assert library.post(f"/api/memory/proposals/{pid}", json={"accept": True}).status_code == 200
    assert library.post(f"/api/memory/proposals/{pid}", json={"accept": True}).status_code == 409
    # Saying "yes" in chat afterwards must not crash.
    assert library.say("yes")["text"]


def test_deleting_document_leaves_bundle_slot_missing(library):
    r = library.say("Find my identity card and bank confirmation", new=True)
    payload = [a for a in r["actions"] if a["type"] == "create_bundle"][0]["payload"]
    b = library.post("/api/bundles", json=payload).json["bundle"]
    doc_id = b["items"][0]["document"]["id"]
    library.delete(f"/api/documents/{doc_id}", json={"confirm": True})
    b2 = library.get(f"/api/bundles/{b['id']}").json["bundle"]
    assert b2["items"][0]["document"] is None and len(b2["items"]) == 2
    links = library.post(f"/api/bundles/{b['id']}/links", json={}).json["links"]
    assert len(links) == 1


def test_bundle_cannot_reference_foreign_documents(client, library):
    mine = library.get("/api/documents").json["documents"][0]["id"]
    other = Session(client, email="thief@example.com")
    r = other.post("/api/bundles", json={"name": "x", "items": [{"label": "a", "document_id": mine}]})
    assert r.status_code == 404


def test_unicode_download_filename(library, client):
    r = library.say("find my bank confirmation", new=True)
    doc = [b for b in r["blocks"] if b["type"] == "requirements"][0]["results"][0]["best"]["document"]
    b = library.post("/api/bundles", json={"name": "בדיקה", "items": [{"label": "אישור בנק", "document_id": doc["id"]}]}).json["bundle"]
    link = library.post(f"/api/bundles/{b['id']}/links", json={}).json["links"][0]
    resp = client.get(link["url"])
    assert "filename*=UTF-8''" in resp.headers["Content-Disposition"]


def test_custom_categories(library):
    r = library.post("/api/categories", json={"name": "רכב"})
    assert r.status_code == 201
    key = r.json["key"]
    assert library.post("/api/categories", json={"name": "רכב"}).status_code == 409
    doc = library.get("/api/documents").json["documents"][0]
    assert library.patch(f"/api/documents/{doc['id']}", json={"category_key": key}).status_code == 200
    assert library.patch(f"/api/documents/{doc['id']}", json={"category_key": "nope"}).status_code == 400
    assert library.delete("/api/categories/identity").status_code == 404  # built-ins are protected
    assert library.delete(f"/api/categories/{key}").status_code == 200
    assert library.get(f"/api/documents/{doc['id']}").json["document"]["category_key"] == "other"


def test_invalid_metadata_rejected(library):
    doc = library.get("/api/documents").json["documents"][0]
    assert library.patch(f"/api/documents/{doc['id']}", json={"doc_type": "rocket"}).status_code == 400
    assert library.patch(f"/api/documents/{doc['id']}", json={"expiry_date": "31/12/2030"}).status_code == 400
    assert library.patch(f"/api/documents/{doc['id']}", json={"display_name": "   "}).status_code == 200


def test_export_contains_no_document_text(library):
    data = library.get("/api/me/export").json
    assert len(data["documents"]) == 8
    assert "is a registered student" not in str(data)


def test_password_change_revokes_sessions(session, client):
    r = session.post("/api/me/password", json={"current_password": "wrong", "new_password": "An0therGoodPw"})
    assert r.status_code == 403
    r = session.post("/api/me/password", json={"current_password": "Sup3rSecretPw", "new_password": "An0therGoodPw"})
    assert r.status_code == 200
    assert session.get("/api/me").status_code == 401
    assert client.post("/api/auth/login", json={"email": "user@example.com", "password": "An0therGoodPw"}).status_code == 200


def test_login_rate_limit(client):
    codes = [client.post("/api/auth/login", json={"email": "x@y.co", "password": "bad"}).status_code for _ in range(12)]
    assert 429 in codes
