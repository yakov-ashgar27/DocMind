"""Runtime configuration. All secrets come from environment variables."""
from __future__ import annotations

import base64
import os
import secrets
import warnings
from dataclasses import dataclass, field
from pathlib import Path


def _bool(name: str, default: bool = False) -> bool:
    v = os.environ.get(name)
    if v is None:
        return default
    return v.strip().lower() in {"1", "true", "yes", "on"}


@dataclass
class Config:
    data_dir: Path
    db_path: Path
    blob_dir: Path
    master_key: bytes
    jwt_secret: bytes
    env: str = "development"
    access_token_ttl: int = 15 * 60
    refresh_token_ttl: int = 30 * 24 * 3600
    max_upload_bytes: int = 25 * 1024 * 1024
    ocr_languages: str = "heb+eng"
    ocr_max_pdf_pages: int = 6
    process_sync: bool = False  # tests run the pipeline inline
    llm_provider: str = "none"
    llm_api_key: str | None = None
    llm_model: str | None = None
    shared_learning_enabled: bool = False  # global kill-switch, off until hardened
    google_client_id: str | None = None
    google_client_secret: str | None = None
    google_redirect_uri: str | None = None
    secure_cookies: bool = False
    extra: dict = field(default_factory=dict)

    @property
    def is_production(self) -> bool:
        return self.env == "production"


def _load_key(env_name: str, dev_file: Path, env: str) -> bytes:
    raw = os.environ.get(env_name)
    if raw:
        key = base64.urlsafe_b64decode(raw + "=" * (-len(raw) % 4))
        if len(key) != 32:
            raise ValueError(f"{env_name} must be 32 bytes, base64url-encoded")
        return key
    if env == "production":
        raise RuntimeError(f"{env_name} is required in production")
    # Development convenience: persist a generated key next to the data.
    if dev_file.exists():
        return base64.urlsafe_b64decode(dev_file.read_text().strip())
    key = secrets.token_bytes(32)
    dev_file.write_text(base64.urlsafe_b64encode(key).decode())
    os.chmod(dev_file, 0o600)
    warnings.warn(f"{env_name} not set: generated a development key at {dev_file}. "
                  "Never use this in production.", stacklevel=2)
    return key


def load_config(overrides: dict | None = None) -> Config:
    overrides = overrides or {}
    env = overrides.get("env") or os.environ.get("DOCMIND_ENV", "development")
    data_dir = Path(overrides.get("data_dir") or os.environ.get("DOCMIND_DATA_DIR", "./data")).resolve()
    data_dir.mkdir(parents=True, exist_ok=True)
    blob_dir = data_dir / "blobs"
    blob_dir.mkdir(exist_ok=True)
    cfg = Config(
        env=env,
        data_dir=data_dir,
        db_path=data_dir / "docmind.sqlite3",
        blob_dir=blob_dir,
        master_key=overrides.get("master_key") or _load_key("DOCMIND_MASTER_KEY", data_dir / ".dev_master_key", env),
        jwt_secret=overrides.get("jwt_secret") or _load_key("DOCMIND_JWT_SECRET", data_dir / ".dev_jwt_secret", env),
        process_sync=overrides.get("process_sync", _bool("DOCMIND_PROCESS_SYNC")),
        llm_provider=os.environ.get("DOCMIND_LLM_PROVIDER", "none").lower(),
        llm_api_key=os.environ.get("DOCMIND_LLM_API_KEY"),
        llm_model=os.environ.get("DOCMIND_LLM_MODEL"),
        shared_learning_enabled=_bool("DOCMIND_SHARED_LEARNING", False),
        google_client_id=os.environ.get("GOOGLE_CLIENT_ID"),
        google_client_secret=os.environ.get("GOOGLE_CLIENT_SECRET"),
        google_redirect_uri=os.environ.get("GOOGLE_REDIRECT_URI"),
        secure_cookies=_bool("DOCMIND_SECURE_COOKIES", env == "production"),
    )
    for k, v in overrides.items():
        if hasattr(cfg, k):
            setattr(cfg, k, v)
    return cfg
