import os
import secrets
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from docmind.app import create_app  # noqa: E402

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture
def app(tmp_path):
    return create_app({"data_dir": str(tmp_path), "process_sync": True,
                       "master_key": secrets.token_bytes(32), "jwt_secret": secrets.token_bytes(32)})


@pytest.fixture
def ctx(app):
    return app.extensions["docmind"]


@pytest.fixture
def client(app):
    return app.test_client()


class Session:
    def __init__(self, client, email="user@example.com", password="Sup3rSecretPw", locale="he", name="Israel"):
        self.client = client
        r = client.post("/api/auth/register", json={"email": email, "password": password, "display_name": name,
                                                    "locale": locale})
        assert r.status_code == 201, r.json
        self.token = r.json["access_token"]
        self.user = r.json["user"]
        self.conv = None

    @property
    def h(self):
        return {"Authorization": f"Bearer {self.token}"}

    def get(self, url, **kw):
        return self.client.get(url, headers=self.h, **kw)

    def post(self, url, **kw):
        return self.client.post(url, headers=self.h, **kw)

    def patch(self, url, **kw):
        return self.client.patch(url, headers=self.h, **kw)

    def delete(self, url, **kw):
        return self.client.delete(url, headers=self.h, **kw)

    def upload(self, *names, source="upload"):
        files = [(open(FIXTURES / n, "rb"), n) for n in names]
        r = self.post("/api/documents", data={"files": files, "source": source}, content_type="multipart/form-data")
        assert r.status_code == 201, r.json
        return r.json["documents"]

    def say(self, text, new=False):
        if new:
            self.conv = None
        r = self.post("/api/assistant/message", json={"text": text, "conversation_id": self.conv})
        assert r.status_code == 200, r.json
        self.conv = r.json["conversation_id"]
        return r.json


@pytest.fixture
def session(client):
    return Session(client)


@pytest.fixture
def library(session):
    session.upload("IMG_20261115_132411.jpg", "scan_0012.pdf", "document_7.pdf", "file_2026_10.pdf",
                   "download (3).pdf", "Scan_20261109.pdf", "p_2025_06.pdf", "IMG_20261001_090000.jpg")
    return session
