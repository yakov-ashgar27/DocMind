import pytest
from cryptography.exceptions import InvalidTag

from docmind.security import crypto
from tests.conftest import Session


def test_encrypt_roundtrip_and_tamper():
    k = crypto.new_key()
    blob = crypto.encrypt(k, b"secret", aad=b"ctx")
    assert crypto.decrypt(k, blob, aad=b"ctx") == b"secret"
    with pytest.raises(InvalidTag):
        crypto.decrypt(k, blob, aad=b"other-context")
    with pytest.raises(InvalidTag):
        crypto.decrypt(crypto.new_key(), blob, aad=b"ctx")


def test_password_hashing():
    h = crypto.hash_password("Correct Horse 9")
    assert h.startswith("scrypt$") and "Correct" not in h
    assert crypto.verify_password("Correct Horse 9", h)
    assert not crypto.verify_password("wrong", h)


def test_weak_password_rejected(client):
    r = client.post("/api/auth/register", json={"email": "x@y.co", "password": "short"})
    assert r.status_code == 400 and r.json["error"] == "password_too_short"


def test_login_refresh_rotation_and_reuse_detection(client):
    Session(client, email="r@example.com")
    r = client.post("/api/auth/login", json={"email": "r@example.com", "password": "Sup3rSecretPw"})
    assert r.status_code == 200
    old_cookie = client.get_cookie("dm_refresh", path="/api/auth").value
    r2 = client.post("/api/auth/refresh")
    assert r2.status_code == 200 and r2.json["access_token"]
    # Replaying the rotated token revokes everything.
    client.set_cookie("dm_refresh", old_cookie, path="/api/auth")
    assert client.post("/api/auth/refresh").status_code == 401
    assert client.get("/api/me", headers={"Authorization": "Bearer " + r2.json["access_token"]}).status_code == 401


def test_wrong_password(client):
    Session(client, email="w@example.com")
    r = client.post("/api/auth/login", json={"email": "w@example.com", "password": "nope"})
    assert r.status_code == 401


def test_requires_auth(client):
    assert client.get("/api/documents").status_code == 401
    assert client.get("/api/documents", headers={"Authorization": "Bearer garbage"}).status_code == 401


def test_users_are_isolated(client):
    a = Session(client, email="a@example.com")
    doc = a.upload("download (3).pdf")[0]
    b = Session(client, email="b@example.com")
    assert b.get(f"/api/documents/{doc['id']}").status_code == 404
    assert b.post(f"/api/documents/{doc['id']}/link", json={}).status_code == 404
    assert b.get("/api/documents").json["documents"] == []
    reply = b.say("find my proof of enrollment")
    assert reply["blocks"][0]["results"][0]["status"] == "not_found"


def test_data_encrypted_at_rest(session, ctx):
    session.upload("download (3).pdf")
    for blob in ctx.config.blob_dir.rglob("*"):
        if blob.is_file():
            raw = blob.read_bytes()
            assert b"%PDF" not in raw and b"Registrar" not in raw
    row = ctx.db.one("SELECT text_enc FROM documents")
    assert b"Registrar" not in row["text_enc"] and b"ENROLLMENT" not in row["text_enc"]
    raw_db = ctx.config.db_path.read_bytes()
    assert b"is a registered student" not in raw_db


def test_logout_all_revokes_access(session, client):
    assert session.post("/api/me/logout-all").status_code == 200
    assert session.get("/api/me").status_code == 401


def test_security_headers(client):
    r = client.get("/api/meta")
    assert "default-src 'self'" in r.headers["Content-Security-Policy"]
    assert r.headers["X-Frame-Options"] == "DENY"


def test_signed_link_single_use(session, client):
    doc = session.upload("download (3).pdf")[0]
    url = session.post(f"/api/documents/{doc['id']}/link", json={}).json["url"]
    r = client.get(url)
    assert r.status_code == 200 and r.data.startswith(b"%PDF")
    assert client.get(url).status_code == 410


def test_rejects_unknown_file_types(session):
    import io
    r = session.post("/api/documents", data={"files": [(io.BytesIO(b"MZ\x90\x00 evil"), "invoice.pdf")]},
                     content_type="multipart/form-data")
    assert r.status_code == 400 and r.json["errors"][0]["error"] == "unsupported_file_type"


def test_audit_log_records_sensitive_actions(session):
    doc = session.upload("download (3).pdf")[0]
    session.post(f"/api/documents/{doc['id']}/link", json={})
    actions = {e["action"] for e in session.get("/api/me/audit").json["events"]}
    assert {"auth.register", "document.upload"} <= actions


def test_account_deletion_shreds_blobs(session, ctx):
    session.upload("download (3).pdf", "Scan_20261109.pdf")
    assert any(p.is_file() for p in ctx.config.blob_dir.rglob("*"))
    assert session.delete("/api/me", json={"password": "wrong"}).status_code == 403
    assert session.delete("/api/me", json={"password": "Sup3rSecretPw"}).status_code == 200
    assert not any(p.is_file() for p in ctx.config.blob_dir.rglob("*"))
    assert ctx.db.one("SELECT COUNT(*) n FROM documents")["n"] == 0
