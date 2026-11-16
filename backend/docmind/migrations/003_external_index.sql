-- 003: index of documents found in connected cloud sources (metadata only, not downloaded).
-- Filename/subject/sender are encrypted with the user's DEK; only the guessed type is plaintext.
CREATE TABLE external_refs (
    id            TEXT PRIMARY KEY,
    user_id       TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    kind          TEXT NOT NULL,          -- gmail | gdrive
    ref           TEXT NOT NULL,          -- message:attachment id or drive file id
    doc_type      TEXT NOT NULL DEFAULT 'unknown',
    type_score    REAL NOT NULL DEFAULT 0,
    meta_enc      BLOB NOT NULL,          -- {filename, subject, from, date, size, open_url, mime_type}
    indexed_at    TEXT NOT NULL,
    UNIQUE (user_id, kind, ref)
);
CREATE INDEX idx_external_refs_type ON external_refs(user_id, doc_type);
