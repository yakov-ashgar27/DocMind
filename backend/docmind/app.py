"""Application factory."""
from __future__ import annotations

import logging
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from flask import Flask, jsonify, send_from_directory

from .assistant.llm import make_provider
from .config import load_config
from .db import Database, new_id, now_iso
from .knowledge.catalog import CATEGORIES
from .security.audit import RateLimiter
from .security.crypto import BlobStore
from .services.search import SearchIndex

FRONTEND_DIR = Path(__file__).resolve().parents[2] / "frontend"


class AppContext:
    def __init__(self, config):
        self.config = config
        self.db = Database(config.db_path)
        self.blobs = BlobStore(config.blob_dir, config.master_key)
        self.search = SearchIndex(self.db, config.master_key)
        self.executor = ThreadPoolExecutor(max_workers=2, thread_name_prefix="docproc")
        self.llm = make_provider(config)
        self.limiter = RateLimiter()


def _seed_categories(db):
    for key, en, he, icon in CATEGORIES:
        if not db.one("SELECT 1 FROM categories WHERE user_id IS NULL AND key = ?", (key,)):
            db.insert("categories", {"id": new_id(), "user_id": None, "key": key, "name_en": en, "name_he": he,
                                     "icon": icon, "is_custom": 0, "created_at": now_iso()})


def _recover_stuck(ctx):
    """Documents left 'processing' by a crash/restart are re-queued."""
    for d in ctx.db.all("SELECT id, user_id FROM documents WHERE status = 'processing'"):
        from .services.documents import _process_safe
        ctx.executor.submit(_process_safe, ctx, d["user_id"], d["id"])


def create_app(overrides: dict | None = None) -> Flask:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    config = load_config(overrides)
    app = Flask(__name__, static_folder=None)
    app.config["MAX_CONTENT_LENGTH"] = max(config.max_upload_bytes * 10, 250 * 1024 * 1024)
    ctx = AppContext(config)
    ctx.db.migrate()
    _seed_categories(ctx.db)
    app.extensions["docmind"] = ctx
    if not config.process_sync:
        _recover_stuck(ctx)

    from .api import register
    register(app)

    @app.after_request
    def security_headers(resp):
        resp.headers["Content-Security-Policy"] = (
            "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' blob: data:; "
            "frame-src 'self' blob:; object-src 'none'; base-uri 'none'; form-action 'self'; frame-ancestors 'none'")
        resp.headers["X-Content-Type-Options"] = "nosniff"
        resp.headers["X-Frame-Options"] = "DENY"
        resp.headers["Referrer-Policy"] = "no-referrer"
        resp.headers["Permissions-Policy"] = "camera=(self), microphone=(), geolocation=()"
        if config.is_production:
            resp.headers["Strict-Transport-Security"] = "max-age=63072000; includeSubDomains"
        if resp.mimetype == "application/json" or resp.headers.get("Content-Disposition"):
            resp.headers["Cache-Control"] = "no-store"
        return resp

    @app.errorhandler(413)
    def too_large(_):
        return jsonify(error="file_too_large"), 413

    @app.get("/")
    def index():
        return send_from_directory(FRONTEND_DIR, "index.html")

    @app.get("/<path:path>")
    def static_files(path):
        if path.startswith("api/"):
            return jsonify(error="not_found"), 404
        target = (FRONTEND_DIR / path).resolve()
        if FRONTEND_DIR in target.parents and target.is_file():
            return send_from_directory(FRONTEND_DIR, path)
        return send_from_directory(FRONTEND_DIR, "index.html")

    return app
