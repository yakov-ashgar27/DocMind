"""Gmail + Google Drive via official REST APIs and OAuth 2.0 (authorization code + PKCE).

Read-only scopes. Tokens are encrypted with the user's data key. Requires GOOGLE_CLIENT_ID,
GOOGLE_CLIENT_SECRET and GOOGLE_REDIRECT_URI; without them the connectors report `not_configured`
and are never shown as searched.

Note: gmail.readonly and drive.readonly are Google "restricted" scopes; a public launch needs
Google's OAuth app verification (and a security assessment for Gmail). Testing mode works with up
to 100 listed test users.
"""
from __future__ import annotations

import base64
import hashlib
import json
import secrets
import time
from datetime import datetime, timedelta, timezone
from urllib.parse import urlencode

import requests

from ..db import new_id, now_iso
from ..knowledge.catalog import DOC_TYPES, REQUEST_ALIASES
from ..security import crypto
from ..security.audit import audit
from ..services import classifier
from .base import Availability, Hit, LibraryConnector

AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
TOKEN_URL = "https://oauth2.googleapis.com/token"
REVOKE_URL = "https://oauth2.googleapis.com/revoke"
GMAIL = "https://gmail.googleapis.com/gmail/v1/users/me"
DRIVE = "https://www.googleapis.com/drive/v3"
SCOPES = {
    "gmail": "openid email https://www.googleapis.com/auth/gmail.readonly",
    "gdrive": "openid email https://www.googleapis.com/auth/drive.readonly",
}
HTTP_TIMEOUT = 20


class ConnectorError(Exception):
    def __init__(self, code: str, status: int = 400):
        super().__init__(code)
        self.code = code
        self.status = status


def configured(ctx) -> bool:
    c = ctx.config
    return bool(c.google_client_id and c.google_client_secret and c.google_redirect_uri)


# ---- OAuth ----------------------------------------------------------------------------
def start_oauth(ctx, user, kind: str) -> str:
    if kind not in SCOPES:
        raise ConnectorError("unknown_connector", 404)
    if not configured(ctx):
        raise ConnectorError("not_configured", 409)
    state = secrets.token_urlsafe(32)
    verifier = secrets.token_urlsafe(64)
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()
    ctx.db.execute("DELETE FROM oauth_states WHERE created_at < ?",
                   ((datetime.now(timezone.utc) - timedelta(minutes=15)).isoformat(),))
    ctx.db.insert("oauth_states", {"state": state, "user_id": user["id"], "kind": kind, "verifier": verifier,
                                   "created_at": now_iso()})
    return AUTH_URL + "?" + urlencode({
        "client_id": ctx.config.google_client_id, "redirect_uri": ctx.config.google_redirect_uri,
        "response_type": "code", "scope": SCOPES[kind], "state": state, "access_type": "offline",
        "prompt": "consent", "include_granted_scopes": "false",
        "code_challenge": challenge, "code_challenge_method": "S256",
    })


def finish_oauth(ctx, code: str, state: str) -> tuple[str, str]:
    row = ctx.db.one("SELECT * FROM oauth_states WHERE state = ?", (state,))
    if not row:
        raise ConnectorError("invalid_state")
    ctx.db.execute("DELETE FROM oauth_states WHERE state = ?", (state,))
    if row["created_at"] < (datetime.now(timezone.utc) - timedelta(minutes=15)).replace(microsecond=0).isoformat():
        raise ConnectorError("state_expired")
    r = requests.post(TOKEN_URL, timeout=HTTP_TIMEOUT, data={
        "code": code, "client_id": ctx.config.google_client_id, "client_secret": ctx.config.google_client_secret,
        "redirect_uri": ctx.config.google_redirect_uri, "grant_type": "authorization_code",
        "code_verifier": row["verifier"],
    })
    if r.status_code != 200:
        raise ConnectorError("token_exchange_failed", 502)
    tok = r.json()
    tok["obtained_at"] = int(time.time())
    user = ctx.db.one("SELECT * FROM users WHERE id = ?", (row["user_id"],))
    from ..security.auth import user_dek
    dek = user_dek(ctx, user)
    label = _email_from_id_token(tok.get("id_token"))
    ctx.db.execute("DELETE FROM connected_sources WHERE user_id = ? AND kind = ?", (user["id"], row["kind"]))
    ctx.db.insert("connected_sources", {
        "id": new_id(), "user_id": user["id"], "kind": row["kind"], "account_label": label,
        "tokens_enc": crypto.encrypt_text(dek, json.dumps(tok), f"oauth:{user['id']}:{row['kind']}"),
        "scopes": tok.get("scope", SCOPES[row["kind"]]), "status": "connected", "connected_at": now_iso(),
    })
    audit(ctx, user["id"], "connector.connect", row["kind"], account=label)
    return user["id"], row["kind"]


def _email_from_id_token(id_token: str | None) -> str | None:
    # Display label only (the token came straight from Google's token endpoint over TLS).
    if not id_token:
        return None
    try:
        payload = id_token.split(".")[1]
        return json.loads(base64.urlsafe_b64decode(payload + "=" * (-len(payload) % 4))).get("email")
    except Exception:
        return None


def disconnect(ctx, user, dek, kind: str) -> None:
    row = ctx.db.one("SELECT * FROM connected_sources WHERE user_id = ? AND kind = ?", (user["id"], kind))
    if not row:
        return
    try:
        tok = json.loads(crypto.decrypt_text(dek, row["tokens_enc"], f"oauth:{user['id']}:{kind}"))
        requests.post(REVOKE_URL, params={"token": tok.get("refresh_token") or tok.get("access_token")},
                      timeout=HTTP_TIMEOUT)
    except Exception:
        pass  # local deletion below still removes our copy of the credentials
    ctx.db.execute("DELETE FROM connected_sources WHERE id = ?", (row["id"],))
    audit(ctx, user["id"], "connector.disconnect", kind)


def _access_token(ctx, user, dek, kind: str) -> str:
    row = ctx.db.one("SELECT * FROM connected_sources WHERE user_id = ? AND kind = ?", (user["id"], kind))
    if not row:
        raise ConnectorError("not_connected", 409)
    aad = f"oauth:{user['id']}:{kind}"
    tok = json.loads(crypto.decrypt_text(dek, row["tokens_enc"], aad))
    if time.time() < tok["obtained_at"] + tok.get("expires_in", 0) - 60:
        return tok["access_token"]
    if not tok.get("refresh_token"):
        raise ConnectorError("reauth_required", 409)
    r = requests.post(TOKEN_URL, timeout=HTTP_TIMEOUT, data={
        "client_id": ctx.config.google_client_id, "client_secret": ctx.config.google_client_secret,
        "refresh_token": tok["refresh_token"], "grant_type": "refresh_token"})
    if r.status_code != 200:
        ctx.db.execute("UPDATE connected_sources SET status = 'reauth_required' WHERE id = ?", (row["id"],))
        raise ConnectorError("reauth_required", 409)
    new = r.json()
    tok.update(access_token=new["access_token"], expires_in=new.get("expires_in", 3600), obtained_at=int(time.time()))
    ctx.db.execute("UPDATE connected_sources SET tokens_enc = ?, status = 'connected' WHERE id = ?",
                   (crypto.encrypt_text(dek, json.dumps(tok), aad), row["id"]))
    return tok["access_token"]


def _get(ctx, user, dek, kind, url, **params):
    r = requests.get(url, params=params, timeout=HTTP_TIMEOUT,
                     headers={"Authorization": f"Bearer {_access_token(ctx, user, dek, kind)}"})
    if r.status_code == 401:
        raise ConnectorError("reauth_required", 409)
    if r.status_code != 200:
        raise ConnectorError(f"{kind}_api_error_{r.status_code}", 502)
    return r


def _terms(doc_type: str | None, query: str) -> list[str]:
    if doc_type in DOC_TYPES:
        terms = [DOC_TYPES[doc_type]["he"], DOC_TYPES[doc_type]["en"], *REQUEST_ALIASES.get(doc_type, [])]
    else:
        terms = [query]
    seen, out = set(), []
    for t in terms:
        t = t.replace('"', "").replace("'", "").replace("\\", "").strip()
        if len(t) >= 3 and t.lower() not in seen:
            seen.add(t.lower())
            out.append(t)
    return out[:6]


def _external_score(doc_type, text):
    if not doc_type or doc_type not in DOC_TYPES:
        return 0.3
    s = classifier.score_types(text, "").get(doc_type, 0)
    return min(0.95, 0.25 + s / 12)


# ---- Connectors -------------------------------------------------------------------------
class _GoogleConnector(LibraryConnector):
    kind = ""
    stage = 2

    def availability(self, ctx, user):
        if not configured(ctx):
            return Availability("not_configured", False)
        row = ctx.db.one("SELECT status, account_label, last_synced_at FROM connected_sources WHERE user_id = ? AND kind = ?",
                         (user["id"], self.kind))
        if not row:
            return Availability("not_connected", False)
        return Availability(row["status"], row["status"] == "connected",
                            {"account": row["account_label"], "last_synced_at": row["last_synced_at"]})

    def find(self, ctx, user, dek, doc_type, query):
        hits = super().find(ctx, user, dek, doc_type, query)  # already-downloaded copies
        if not self.availability(ctx, user).searchable:
            return hits
        refs = {r["source_ref"] for r in ctx.db.all(
            "SELECT source_ref FROM documents WHERE user_id = ? AND source_kind = ?", (user["id"], self.kind))}
        for ext in self.search_remote(ctx, user, dek, doc_type, query):
            if ext["ref"] in refs:
                continue
            hits.append(Hit(self.key, "found_external_not_downloaded", ext.pop("score"), "external", external=ext))
        ctx.db.execute("UPDATE connected_sources SET last_synced_at = ? WHERE user_id = ? AND kind = ?",
                       (now_iso(), user["id"], self.kind))
        return hits


class GmailConnector(_GoogleConnector):
    key = "gmail"
    kind = "gmail"
    order = 5
    label = {"en": "Gmail", "he": "Gmail"}
    source_kinds = ("gmail",)
    found_status = "found_gmail"

    def search_remote(self, ctx, user, dek, doc_type, query):
        terms = _terms(doc_type, query)
        q = "has:attachment {" + " ".join(f'"{t}"' for t in terms) + "}"
        msgs = _get(ctx, user, dek, "gmail", f"{GMAIL}/messages", q=q, maxResults=10).json().get("messages", [])
        out = []
        for m in msgs:
            full = _get(ctx, user, dek, "gmail", f"{GMAIL}/messages/{m['id']}", format="full").json()
            headers = {h["name"].lower(): h["value"] for h in full.get("payload", {}).get("headers", [])}
            subject = headers.get("subject", "")
            for part in _walk_parts(full.get("payload", {})):
                fn = part.get("filename")
                att = part.get("body", {}).get("attachmentId")
                if not fn or not att or not (fn.lower().endswith((".pdf", ".jpg", ".jpeg", ".png"))):
                    continue
                score = _external_score(doc_type, f"{subject} {full.get('snippet', '')} {fn}")
                out.append({"kind": "gmail", "ref": f"{m['id']}:{att}", "message_id": m["id"], "attachment_id": att,
                            "filename": fn, "subject": subject, "from": headers.get("from"), "date": headers.get("date"),
                            "size": part.get("body", {}).get("size"),
                            "open_url": f"https://mail.google.com/mail/u/0/#all/{m['id']}", "score": score})
        return sorted(out, key=lambda e: -e["score"])[:8]

    def download(self, ctx, user, dek, ref: str) -> tuple[bytes, str]:
        msg_id, att_id = ref.split(":", 1)
        full = _get(ctx, user, dek, "gmail", f"{GMAIL}/messages/{msg_id}", format="full").json()
        fn = next((p["filename"] for p in _walk_parts(full.get("payload", {}))
                   if p.get("body", {}).get("attachmentId") == att_id), "attachment")
        data = _get(ctx, user, dek, "gmail", f"{GMAIL}/messages/{msg_id}/attachments/{att_id}").json()["data"]
        return base64.urlsafe_b64decode(data + "=" * (-len(data) % 4)), fn


def _walk_parts(part):
    yield part
    for p in part.get("parts", []) or []:
        yield from _walk_parts(p)


class DriveConnector(_GoogleConnector):
    key = "gdrive"
    kind = "gdrive"
    order = 6
    label = {"en": "Google Drive", "he": "Google Drive"}
    source_kinds = ("gdrive",)
    found_status = "found_gdrive"

    def search_remote(self, ctx, user, dek, doc_type, query):
        terms = _terms(doc_type, query)
        clauses = " or ".join(f"fullText contains '{t}' or name contains '{t}'" for t in terms)
        q = f"({clauses}) and trashed = false"
        files = _get(ctx, user, dek, "gdrive", f"{DRIVE}/files", q=q, pageSize=10,
                     fields="files(id,name,mimeType,modifiedTime,webViewLink,size)").json().get("files", [])
        out = []
        for f in files:
            out.append({"kind": "gdrive", "ref": f["id"], "file_id": f["id"], "filename": f["name"],
                        "mime_type": f.get("mimeType"), "date": f.get("modifiedTime"), "size": f.get("size"),
                        "open_url": f.get("webViewLink"), "score": _external_score(doc_type, f["name"]) + 0.1})
        return out

    def download(self, ctx, user, dek, ref: str) -> tuple[bytes, str]:
        meta = _get(ctx, user, dek, "gdrive", f"{DRIVE}/files/{ref}", fields="name,mimeType").json()
        if meta["mimeType"].startswith("application/vnd.google-apps."):
            r = _get(ctx, user, dek, "gdrive", f"{DRIVE}/files/{ref}/export", mimeType="application/pdf")
            return r.content, meta["name"] + ".pdf"
        return _get(ctx, user, dek, "gdrive", f"{DRIVE}/files/{ref}", alt="media").content, meta["name"]


def import_external(ctx, user, dek, kind: str, ref: str) -> dict:
    """Download an external hit into the encrypted library (explicit user action)."""
    from ..services import documents as docsvc
    conn = {"gmail": GmailConnector, "gdrive": DriveConnector}.get(kind)
    if not conn:
        raise ConnectorError("unknown_connector", 404)
    existing = ctx.db.one("SELECT * FROM documents WHERE user_id = ? AND source_kind = ? AND source_ref = ?",
                          (user["id"], kind, ref))
    if existing:
        return existing
    data, filename = conn().download(ctx, user, dek, ref)
    doc = docsvc.ingest(ctx, user, dek, data, filename, source_kind=kind, source_ref=ref)
    if kind == "gmail":
        ctx.db.update("documents", doc["id"], {"source_url": f"https://mail.google.com/mail/u/0/#all/{ref.split(':')[0]}"})
    audit(ctx, user["id"], "connector.import", doc["id"], kind=kind)
    return ctx.db.one("SELECT * FROM documents WHERE id = ?", (doc["id"],))
