-- 001: initial schema. Portable SQL (SQLite now, PostgreSQL-compatible types where possible).

CREATE TABLE users (
    id              TEXT PRIMARY KEY,
    email           TEXT NOT NULL UNIQUE,
    password_hash   TEXT NOT NULL,
    display_name    TEXT NOT NULL,
    locale          TEXT NOT NULL DEFAULT 'he',
    wrapped_dek     BLOB NOT NULL,            -- per-user data key, wrapped by master key
    settings_json   TEXT NOT NULL DEFAULT '{}',
    created_at      TEXT NOT NULL,
    token_version   INTEGER NOT NULL DEFAULT 0 -- bump to revoke every session
);

CREATE TABLE refresh_tokens (
    id          TEXT PRIMARY KEY,
    user_id     TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    token_hash  TEXT NOT NULL UNIQUE,
    user_agent  TEXT,
    created_at  TEXT NOT NULL,
    expires_at  TEXT NOT NULL,
    revoked_at  TEXT
);

CREATE TABLE categories (
    id          TEXT PRIMARY KEY,
    user_id     TEXT REFERENCES users(id) ON DELETE CASCADE,  -- NULL = built-in
    key         TEXT NOT NULL,
    name_en     TEXT NOT NULL,
    name_he     TEXT NOT NULL,
    icon        TEXT NOT NULL DEFAULT 'folder',
    is_custom   INTEGER NOT NULL DEFAULT 0,
    created_at  TEXT NOT NULL,
    UNIQUE (user_id, key)
);

CREATE TABLE documents (
    id                  TEXT PRIMARY KEY,
    user_id             TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    source_kind         TEXT NOT NULL,          -- upload | whatsapp_import | gmail | gdrive ...
    source_ref          TEXT,                   -- external id (message id, drive file id)
    source_url          TEXT,                   -- deep link to the exact email/file (external only)
    is_local            INTEGER NOT NULL DEFAULT 1, -- 0 = found externally, bytes not downloaded yet
    original_filename   TEXT NOT NULL,
    display_name        TEXT NOT NULL,
    mime_type           TEXT NOT NULL,
    size_bytes          INTEGER NOT NULL DEFAULT 0,
    sha256              TEXT,
    storage_key         TEXT,
    wrapped_file_key    BLOB,
    text_enc            BLOB,                   -- extracted/OCR text, encrypted with user DEK
    text_chars          INTEGER NOT NULL DEFAULT 0,
    ocr_used            INTEGER NOT NULL DEFAULT 0,
    language            TEXT,
    category_key        TEXT NOT NULL DEFAULT 'other',
    doc_type            TEXT NOT NULL DEFAULT 'unknown',
    doc_type_confidence REAL NOT NULL DEFAULT 0,
    doc_type_source     TEXT NOT NULL DEFAULT 'auto', -- auto | user
    issuer              TEXT,
    doc_date            TEXT,
    expiry_date         TEXT,
    tags_json           TEXT NOT NULL DEFAULT '[]',
    status              TEXT NOT NULL DEFAULT 'processing', -- processing | ready | failed
    error               TEXT,
    duplicate_of        TEXT REFERENCES documents(id) ON DELETE SET NULL,
    duplicate_kind      TEXT,                   -- exact | near
    archived            INTEGER NOT NULL DEFAULT 0,
    created_at          TEXT NOT NULL,
    updated_at          TEXT NOT NULL
);
CREATE INDEX idx_documents_user ON documents(user_id, archived);
CREATE INDEX idx_documents_type ON documents(user_id, doc_type);
CREATE INDEX idx_documents_sha ON documents(user_id, sha256);

-- Personal memory: user-approved task templates (checklists).
CREATE TABLE checklists (
    id            TEXT PRIMARY KEY,
    user_id       TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    name          TEXT NOT NULL,
    purpose_key   TEXT NOT NULL,
    items_json    TEXT NOT NULL,       -- [{doc_type, label, note}]
    version       INTEGER NOT NULL DEFAULT 1,
    use_count     INTEGER NOT NULL DEFAULT 0,
    created_at    TEXT NOT NULL,
    updated_at    TEXT NOT NULL,
    last_used_at  TEXT
);

-- Other personal memory facts (where documents were found, preferences, workflow notes).
CREATE TABLE memory_facts (
    id          TEXT PRIMARY KEY,
    user_id     TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    kind        TEXT NOT NULL,   -- doc_location | preference | workflow | date
    key         TEXT NOT NULL,
    value_json  TEXT NOT NULL,
    created_at  TEXT NOT NULL,
    updated_at  TEXT NOT NULL,
    UNIQUE (user_id, kind, key)
);

-- Proposed memory changes awaiting explicit confirmation. Never applied silently.
CREATE TABLE memory_proposals (
    id            TEXT PRIMARY KEY,
    user_id       TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    kind          TEXT NOT NULL,      -- create_checklist | update_checklist
    payload_json  TEXT NOT NULL,
    status        TEXT NOT NULL DEFAULT 'pending', -- pending | accepted | rejected
    created_at    TEXT NOT NULL,
    resolved_at   TEXT
);

CREATE TABLE bundles (
    id            TEXT PRIMARY KEY,
    user_id       TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    name          TEXT NOT NULL,
    checklist_id  TEXT REFERENCES checklists(id) ON DELETE SET NULL,
    created_at    TEXT NOT NULL,
    updated_at    TEXT NOT NULL
);

CREATE TABLE bundle_items (
    id              TEXT PRIMARY KEY,
    bundle_id       TEXT NOT NULL REFERENCES bundles(id) ON DELETE CASCADE,
    position        INTEGER NOT NULL,
    label           TEXT NOT NULL,
    doc_type        TEXT,
    document_id     TEXT REFERENCES documents(id) ON DELETE SET NULL,
    custom_filename TEXT,
    selected        INTEGER NOT NULL DEFAULT 1
);

CREATE TABLE conversations (
    id          TEXT PRIMARY KEY,
    user_id     TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    title       TEXT,
    state_json  TEXT NOT NULL DEFAULT '{}',
    created_at  TEXT NOT NULL,
    updated_at  TEXT NOT NULL
);

CREATE TABLE messages (
    id               TEXT PRIMARY KEY,
    conversation_id  TEXT NOT NULL REFERENCES conversations(id) ON DELETE CASCADE,
    role             TEXT NOT NULL,      -- user | assistant
    content_enc      BLOB NOT NULL,      -- encrypted with user DEK
    payload_enc      BLOB,               -- structured result (encrypted)
    created_at       TEXT NOT NULL
);

CREATE TABLE connected_sources (
    id              TEXT PRIMARY KEY,
    user_id         TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    kind            TEXT NOT NULL,      -- gmail | gdrive
    account_label   TEXT,
    tokens_enc      BLOB,               -- OAuth tokens, encrypted with user DEK
    scopes          TEXT,
    status          TEXT NOT NULL DEFAULT 'connected',
    connected_at    TEXT NOT NULL,
    last_synced_at  TEXT,
    UNIQUE (user_id, kind)
);

CREATE TABLE oauth_states (
    state       TEXT PRIMARY KEY,
    user_id     TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    kind        TEXT NOT NULL,
    verifier    TEXT NOT NULL,
    created_at  TEXT NOT NULL
);

CREATE TABLE audit_log (
    id          TEXT PRIMARY KEY,
    user_id     TEXT,
    action      TEXT NOT NULL,
    target      TEXT,
    ip          TEXT,
    user_agent  TEXT,
    meta_json   TEXT NOT NULL DEFAULT '{}',
    created_at  TEXT NOT NULL
);
CREATE INDEX idx_audit_user ON audit_log(user_id, created_at);

-- Aggregate, anonymised learning. Only canonical (process_key, doc_type) counts, no content,
-- no user ids. Populated only when the global flag AND per-user opt-in are both on.
CREATE TABLE shared_patterns (
    process_key   TEXT NOT NULL,
    doc_type      TEXT NOT NULL,
    contributors  INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (process_key, doc_type)
);
CREATE TABLE shared_contributions (
    contributor_hash TEXT NOT NULL,   -- keyed HMAC, unlinkable to user id without server secret
    process_key      TEXT NOT NULL,
    doc_type         TEXT NOT NULL,
    PRIMARY KEY (contributor_hash, process_key, doc_type)
);
