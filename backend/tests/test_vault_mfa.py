"""Vault (PIN-protected categories), two-factor sign-in and account lockout."""
import json

from docmind.security import totp
from tests.conftest import Session

PW = "Sup3rSecretPw"


def with_vault(s, pin="482915"):
    r = s.post("/api/vault/pin", json={"password": PW, "pin": pin})
    assert r.status_code == 200, r.json
    return r.json


def unlocked_headers(s, pin="482915"):
    tok = s.post("/api/vault/unlock", json={"pin": pin}).json["vault_token"]
    return {**s.h, "X-Vault-Token": tok}


def test_pin_rules(library):
    assert library.post("/api/vault/pin", json={"password": "wrong", "pin": "482915"}).status_code == 403
    for bad in ("12", "abcd12", "1111", "123456"):
        assert library.post("/api/vault/pin", json={"password": PW, "pin": bad}).status_code == 400
    st = with_vault(library)
    assert st["has_pin"] and set(st["locked_categories"]) == {"identity", "finance", "medical"}


def test_locked_documents_never_leak(library, client, ctx):
    with_vault(library)
    docs = library.get("/api/documents").json["documents"]
    ids = [d for d in docs if d["category_key"] == "identity"]
    assert ids and all(d["locked"] and d["display_name"] is None and d["original_filename"] is None for d in ids)
    military = [d for d in docs if d["category_key"] == "military"]
    assert military and all(not d.get("locked") and d["display_name"] for d in military)
    doc_id = ids[0]["id"]
    # every byte/detail path is closed
    assert library.get(f"/api/documents/{doc_id}").status_code == 423
    assert library.get(f"/api/documents/{doc_id}/thumbnail").status_code == 423
    assert library.post(f"/api/documents/{doc_id}/link", json={}).status_code == 423
    assert library.patch(f"/api/documents/{doc_id}", json={"display_name": "x"}).status_code == 423
    assert library.delete(f"/api/documents/{doc_id}", json={"confirm": True}).status_code == 423
    # content search must not reveal protected text
    hits = library.get("/api/documents", query_string={"q": "IBAN ניהול חשבון"}).json["documents"]
    assert all(h["category_key"] not in ("identity", "finance") for h in hits)
    # nothing protected anywhere in dashboard / export / assistant
    raw = json.dumps(library.get("/api/dashboard").json, ensure_ascii=False)
    raw += json.dumps(library.get("/api/me/export").json, ensure_ascii=False)
    r = library.say("find my identity card and bank confirmation", new=True)
    raw += json.dumps(r, ensure_ascii=False)
    hist = library.get(f"/api/conversations/{r['conversation_id']}").json
    raw += json.dumps(hist, ensure_ascii=False)
    for secret in ("תעודת זהות – ", "IMG_20261115", "Scan_20261109", "2032-05-01", "2026-11-09"):
        assert secret not in raw, secret
    res = {x["requirement"]["doc_type"]: x for x in r["blocks"][0]["results"]}
    assert res["id_card"]["status"] == "found_local" and res["id_card"]["best"]["document"]["locked"]


def test_unlock_reveals_and_expires(library, ctx):
    with_vault(library)
    h = unlocked_headers(library)
    docs = library.client.get("/api/documents", headers=h).json["documents"]
    assert not any(d.get("locked") for d in docs)
    idc = [d for d in docs if d["doc_type"] == "id_card"][0]
    assert library.client.get(f"/api/documents/{idc['id']}", headers=h).status_code == 200
    # logout-all invalidates vault tokens too (token_version)
    library.post("/api/me/logout-all")
    assert library.client.get(f"/api/documents/{idc['id']}", headers=h).status_code == 401


def test_vault_bruteforce_lockout(library):
    with_vault(library)
    codes = [library.post("/api/vault/unlock", json={"pin": "000001"}).status_code for _ in range(5)]
    assert codes[:4] == [403] * 4 and codes[4] == 429
    # even the right PIN is refused during lockout
    assert library.post("/api/vault/unlock", json={"pin": "482915"}).status_code == 429


def test_cannot_unprotect_or_change_pin_while_locked(library):
    with_vault(library)
    assert library.client.put("/api/vault/categories", headers=library.h, json={"categories": []}).status_code == 423
    assert library.post("/api/vault/pin", json={"password": PW, "pin": "135792"}).status_code == 423
    h = unlocked_headers(library)
    r = library.client.put("/api/vault/categories", headers=h, json={"categories": ["identity", "military", "bogus"]})
    assert r.json["locked_categories"] == ["identity", "military"]
    docs = library.get("/api/documents").json["documents"]
    assert all(d.get("locked") for d in docs if d["category_key"] == "military")
    assert not any(d.get("locked") for d in docs if d["category_key"] == "finance")


def test_bundle_download_needs_unlock(library):
    r = library.say("Find my identity card and proof of enrollment", new=True)
    b = library.post("/api/bundles", json=[a for a in r["actions"] if a["type"] == "create_bundle"][0]["payload"]).json["bundle"]
    with_vault(library)
    assert library.post(f"/api/bundles/{b['id']}/links", json={}).status_code == 423
    assert library.post(f"/api/bundles/{b['id']}/combined-link").status_code == 423
    bundle = library.get(f"/api/bundles/{b['id']}").json["bundle"]
    assert bundle["items"][0]["document"]["locked"] and bundle["items"][0]["download_filename"]  # label-based name only
    assert "תעודת" not in (bundle["items"][0]["document"]["display_name"] or "")
    h = unlocked_headers(library)
    assert len(library.client.post(f"/api/bundles/{b['id']}/links", headers=h, json={}).json["links"]) == 2


def test_two_factor_login(client, ctx):
    s = Session(client, email="mfa@example.com")
    assert s.post("/api/me/2fa/setup", json={"password": "nope"}).status_code == 403
    setup = s.post("/api/me/2fa/setup", json={"password": PW}).json
    assert setup["otpauth_uri"].startswith("otpauth://totp/DocMind:")
    assert s.post("/api/me/2fa/enable", json={"code": "000000"}).status_code == 400
    codes = s.post("/api/me/2fa/enable", json={"code": totp.now_code(setup["secret"])}).json["recovery_codes"]
    assert len(codes) == 8
    # password alone no longer creates a session
    r = client.post("/api/auth/login", json={"email": "mfa@example.com", "password": PW})
    assert r.json["mfa_required"] and "access_token" not in r.json
    assert client.post("/api/auth/mfa", json={"mfa_token": r.json["mfa_token"], "code": "123456"}).status_code == 401
    ok = client.post("/api/auth/mfa", json={"mfa_token": r.json["mfa_token"], "code": totp.now_code(setup["secret"])})
    assert ok.status_code == 200 and ok.json["access_token"] and ok.json["user"]["mfa_enabled"]
    # recovery code works exactly once
    r = client.post("/api/auth/login", json={"email": "mfa@example.com", "password": PW})
    assert client.post("/api/auth/mfa", json={"mfa_token": r.json["mfa_token"], "code": codes[0]}).status_code == 200
    r = client.post("/api/auth/login", json={"email": "mfa@example.com", "password": PW})
    assert client.post("/api/auth/mfa", json={"mfa_token": r.json["mfa_token"], "code": codes[0]}).status_code == 401
    # secret is encrypted at rest
    row = ctx.db.one("SELECT totp_secret_enc FROM users WHERE email = 'mfa@example.com'")
    assert setup["secret"].encode() not in row["totp_secret_enc"]


def test_account_lockout_after_repeated_failures(client, ctx):
    Session(client, email="lock@example.com")
    ctx.limiter.allow = lambda *a, **k: True  # isolate the per-account lockout from per-IP rate limiting
    codes = [client.post("/api/auth/login", json={"email": "lock@example.com", "password": "bad"}).status_code
             for _ in range(10)]
    assert codes == [401] * 10
    r = client.post("/api/auth/login", json={"email": "lock@example.com", "password": PW})
    assert r.status_code == 429 and r.json["error"] == "account_temporarily_locked"
