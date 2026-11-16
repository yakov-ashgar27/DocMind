import base64
import io
import json

import pytest
from pypdf import PdfReader

from docmind.connectors import google
from docmind.db import new_id, now_iso
from docmind.security import crypto
from docmind.services import shared_learning


def make_bundle(s):
    r = s.say("Find my identity card, proof of enrollment and bank confirmation", new=True)
    action = [a for a in r["actions"] if a["type"] == "create_bundle"][0]
    return s.post("/api/bundles", json=action["payload"]).json["bundle"]


def test_bundle_individual_downloads_with_organised_names(library, client):
    b = make_bundle(library)
    assert [i["document"]["doc_type"] for i in b["items"]] == ["id_card", "enrollment_proof", "bank_confirmation"]
    names = [i["download_filename"] for i in b["items"]]
    assert names[0] == "01_Identity card.jpg" and names[1].startswith("02_") and names[1].endswith(".pdf")
    # rename one + deselect another
    b = library.patch(f"/api/bundles/{b['id']}/items/{b['items'][1]['id']}",
                      json={"custom_filename": "Enrollment 2026-27"}).json["bundle"]
    b = library.patch(f"/api/bundles/{b['id']}/items/{b['items'][2]['id']}", json={"selected": False}).json["bundle"]
    links = library.post(f"/api/bundles/{b['id']}/links", json={}).json["links"]
    assert [l["filename"] for l in links] == ["01_Identity card.jpg", "Enrollment 2026-27.pdf"]
    for l in links:  # separate original files, no ZIP
        r = client.get(l["url"])
        assert r.status_code == 200 and "attachment" in r.headers["Content-Disposition"]
        assert r.headers["Content-Type"] in ("image/jpeg", "application/pdf")
    one = library.post(f"/api/bundles/{b['id']}/links", json={"item_ids": [b["items"][2]["id"]]}).json["links"]
    assert len(one) == 1


def test_combined_pdf_is_optional(library, client):
    b = make_bundle(library)
    url = library.post(f"/api/bundles/{b['id']}/combined-link").json["url"]
    r = client.get(url)
    assert r.status_code == 200
    assert len(PdfReader(io.BytesIO(r.data)).pages) == 3


def test_deleting_bundle_keeps_documents(library):
    b = make_bundle(library)
    n = len(library.get("/api/documents").json["documents"])
    library.delete(f"/api/bundles/{b['id']}")
    assert len(library.get("/api/documents").json["documents"]) == n


def test_bundle_remembers_locations(library):
    make_bundle(library)
    facts = library.get("/api/memory").json["facts"]
    assert {f["key"] for f in facts if f["kind"] == "doc_location"} >= {"id_card", "enrollment_proof"}


# ---- Gmail connector with mocked Google APIs ------------------------------------------------
class FakeResp:
    def __init__(self, data, status=200, content=b""):
        self._d, self.status_code, self.content = data, status, content

    def json(self):
        return self._d


@pytest.fixture
def gmail(library, ctx, monkeypatch):
    ctx.config.google_client_id, ctx.config.google_client_secret = "cid", "secret"
    ctx.config.google_redirect_uri = "http://localhost/api/oauth/google/callback"
    user = ctx.db.one("SELECT * FROM users")
    from docmind.security.auth import user_dek
    dek = user_dek(ctx, user)
    tok = {"access_token": "at", "refresh_token": "rt", "expires_in": 3600, "obtained_at": 10 ** 10}
    ctx.db.insert("connected_sources", {"id": new_id(), "user_id": user["id"], "kind": "gmail", "account_label": "me@gmail.com",
                                        "tokens_enc": crypto.encrypt_text(dek, json.dumps(tok), f"oauth:{user['id']}:gmail"),
                                        "scopes": "gmail.readonly", "status": "connected", "connected_at": now_iso()})
    import sys
    from pathlib import Path
    sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))
    from make_sample_docs import text_pdf
    pdf = text_pdf(["EXAMPLE SOFTWARE LTD", "FORM 106 - ANNUAL SALARY SUMMARY", "Tax year 2025",
                    "Employee: Israel Example", "Issued: 15/03/2026"])
    calls = []

    def fake_get(url, params=None, headers=None, timeout=None):
        calls.append((url, params))
        assert headers["Authorization"] == "Bearer at"
        if url.endswith("/messages"):
            if "newer_than:5y" in params["q"]:  # background index walk, two pages
                return FakeResp({"messages": [{"id": "m1"}], "nextPageToken": "p2"} if "pageToken" not in params
                                else {"messages": [{"id": "m2"}]})
            return FakeResp({"messages": [{"id": "m1"}]})
        if url.endswith("/messages/m2"):
            return FakeResp({"id": "m2", "snippet": "",
                             "payload": {"headers": [{"name": "Subject", "value": "אישור ניהול חשבון"}],
                                         "parts": [{"filename": "ishur.pdf", "mimeType": "application/pdf",
                                                    "body": {"attachmentId": "att2", "size": 1234}}]}})
        if url.endswith("/messages/m1"):
            return FakeResp({"id": "m1", "snippet": "your 106 form attached",
                             "payload": {"headers": [{"name": "Subject", "value": "טופס 106 לשנת 2025"},
                                                     {"name": "From", "value": "payroll@example.com"}],
                                         "parts": [{"filename": "106_2025.pdf", "mimeType": "application/pdf",
                                                    "body": {"attachmentId": "att1", "size": len(pdf)}}]}})
        if url.endswith("/attachments/att1"):
            return FakeResp({"data": base64.urlsafe_b64encode(pdf).decode()})
        raise AssertionError(url)

    monkeypatch.setattr(google.requests, "get", fake_get)
    return calls


def test_gmail_found_but_not_downloaded_then_import(library, gmail):
    conns = {c["key"]: c for c in library.get("/api/connectors").json["connectors"]}
    assert conns["gmail"]["state"] == "connected" and conns["gdrive"]["state"] == "not_connected"
    r = library.say("I need my form 106", new=True)
    block = [b for b in r["blocks"] if b["type"] == "requirements"][0]
    res = block["results"][0]
    assert res["status"] == "found_external_not_downloaded"
    ext = res["best"]["external"]
    assert ext["open_url"] == "https://mail.google.com/mail/u/0/#all/m1" and ext["filename"] == "106_2025.pdf"
    assert [s["key"] for s in block["sources_searched"]] == ["device_files", "gmail"]
    q = [p for u, p in gmail if u.endswith("/messages")][0]["q"]
    assert q.startswith("has:attachment {") and "טופס 106" in q
    doc = library.post("/api/connectors/gmail/import", json={"ref": ext["ref"]}).json["document"]
    assert doc["source_kind"] == "gmail" and doc["is_local"]
    r2 = library.say("I need my form 106", new=True)
    assert [b for b in r2["blocks"] if b["type"] == "requirements"][0]["results"][0]["status"] == "found_gmail"


def test_oauth_start_uses_pkce_and_state(library, ctx):
    ctx.config.google_client_id, ctx.config.google_client_secret = "cid", "secret"
    ctx.config.google_redirect_uri = "http://localhost/cb"
    url = library.post("/api/connectors/gdrive/connect").json["auth_url"]
    assert "code_challenge_method=S256" in url and "drive.readonly" in url and "state=" in url


def test_unconfigured_google_is_never_reported_as_searched(library):
    r = library.say("find my passport", new=True)
    block = [b for b in r["blocks"] if b["type"] == "requirements"][0]
    assert {s["key"]: s["state"] for s in block["sources_unavailable"]}["gmail"] == "not_configured"
    assert "gmail" not in [s["key"] for s in block["sources_searched"]]


# ---- shared learning ----------------------------------------------------------------------
def test_shared_learning_off_by_default_and_k_anonymous(ctx, client):
    from tests.conftest import Session
    s = Session(client, email="sl@example.com")
    user = ctx.db.one("SELECT * FROM users WHERE email = 'sl@example.com'")
    assert shared_learning.contribute(ctx, user, "reserve_scholarship", ["id_card"]) == 0
    ctx.config.shared_learning_enabled = True
    assert shared_learning.contribute(ctx, user, "reserve_scholarship", ["id_card"]) == 0  # not opted in
    s.patch("/api/me", json={"shared_learning_opt_in": True})
    user = ctx.db.one("SELECT * FROM users WHERE email = 'sl@example.com'")
    assert shared_learning.contribute(ctx, user, "reserve_scholarship", ["passport"]) == 1
    assert shared_learning.contribute(ctx, user, "reserve_scholarship", ["passport"]) == 0  # counted once
    assert shared_learning.contribute(ctx, user, "custom:my-secret-task", ["passport"]) == 0  # free text never shared
    assert shared_learning.suggestions(ctx, "reserve_scholarship") == []  # below k
    ctx.db.execute("UPDATE shared_patterns SET contributors = 25")
    assert shared_learning.suggestions(ctx, "reserve_scholarship") == ["passport"]
    assert "sl@example.com" not in json.dumps(ctx.db.all("SELECT * FROM shared_contributions"))


def test_background_index_finds_without_live_query(library, gmail, ctx, monkeypatch):
    r = library.post("/api/connectors/gmail/sync").json
    assert r["indexed"] == 2
    rows = ctx.db.all("SELECT doc_type, meta_enc FROM external_refs ORDER BY ref")
    assert [x["doc_type"] for x in rows] == ["tax_form_106", "bank_confirmation"]
    assert b"106" not in rows[0]["meta_enc"]  # metadata encrypted at rest
    # Live search returns nothing now; the index still answers.
    monkeypatch.setattr(google.GmailConnector, "search_remote", lambda *a, **k: [])
    res = library.say("I need my form 106", new=True)
    block = [b for b in res["blocks"] if b["type"] == "requirements"][0]
    assert block["results"][0]["status"] == "found_external_not_downloaded"
    assert block["results"][0]["best"]["external"]["indexed"] is True
    library.delete("/api/connectors/gmail")
    assert ctx.db.one("SELECT COUNT(*) n FROM external_refs")["n"] == 0
