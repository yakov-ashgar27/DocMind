"""Database access + forward-only migrations."""
from __future__ import annotations

import sqlite3
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path

MIGRATIONS_DIR = Path(__file__).parent / "migrations"


def now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def new_id() -> str:
    return uuid.uuid4().hex


class Database:
    """Thin wrapper: one connection per thread, row access by column name."""

    def __init__(self, path: Path):
        self.path = Path(path)
        self._local = threading.local()

    def conn(self) -> sqlite3.Connection:
        c = getattr(self._local, "conn", None)
        if c is None:
            c = sqlite3.connect(self.path, timeout=30, isolation_level=None)
            c.row_factory = sqlite3.Row
            c.execute("PRAGMA foreign_keys = ON")
            c.execute("PRAGMA journal_mode = WAL")
            c.execute("PRAGMA busy_timeout = 30000")
            self._local.conn = c
        return c

    def execute(self, sql: str, params: tuple | dict = ()) -> sqlite3.Cursor:
        return self.conn().execute(sql, params)

    def one(self, sql: str, params: tuple | dict = ()) -> dict | None:
        row = self.execute(sql, params).fetchone()
        return dict(row) if row else None

    def all(self, sql: str, params: tuple | dict = ()) -> list[dict]:
        return [dict(r) for r in self.execute(sql, params).fetchall()]

    def insert(self, table: str, values: dict) -> None:
        cols = ", ".join(values)
        marks = ", ".join("?" for _ in values)
        self.execute(f"INSERT INTO {table} ({cols}) VALUES ({marks})", tuple(values.values()))

    def update(self, table: str, row_id: str, values: dict) -> None:
        sets = ", ".join(f"{k} = ?" for k in values)
        self.execute(f"UPDATE {table} SET {sets} WHERE id = ?", (*values.values(), row_id))

    def transaction(self):
        return _Tx(self.conn())

    def migrate(self) -> list[str]:
        c = self.conn()
        c.execute("CREATE TABLE IF NOT EXISTS schema_migrations (version TEXT PRIMARY KEY, applied_at TEXT NOT NULL)")
        applied = {r[0] for r in c.execute("SELECT version FROM schema_migrations")}
        ran = []
        for f in sorted(MIGRATIONS_DIR.glob("*.sql")):
            if f.stem in applied:
                continue
            c.execute("BEGIN")
            try:
                for stmt in _split_sql(f.read_text()):
                    c.execute(stmt)
                c.execute("INSERT INTO schema_migrations VALUES (?, ?)", (f.stem, now_iso()))
                c.execute("COMMIT")
            except Exception:
                c.execute("ROLLBACK")
                raise
            ran.append(f.stem)
        return ran


def _split_sql(sql: str) -> list[str]:
    lines = [ln for ln in sql.splitlines() if not ln.strip().startswith("--")]
    return [s.strip() for s in "\n".join(lines).split(";") if s.strip()]


class _Tx:
    def __init__(self, conn):
        self.conn = conn

    def __enter__(self):
        self.conn.execute("BEGIN IMMEDIATE")
        return self.conn

    def __exit__(self, exc_type, *_):
        self.conn.execute("ROLLBACK" if exc_type else "COMMIT")
        return False
