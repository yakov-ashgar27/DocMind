# DocMind: Data Flow & Data Model

Drawn from the code: the SQL migrations in [`backend/docmind/migrations/`](../backend/docmind/migrations/) (the ERD was generated from them, so names match exactly), the services in [`backend/docmind/services/`](../backend/docmind/services/) and the assistant in [`backend/docmind/assistant/`](../backend/docmind/assistant/). These diagrams describe **DocMind Server** (SQLite + an encrypted file store). The phone edition keeps the same kinds of data on the device, in IndexedDB (`docs`, `blobs`, `records`, `kv` stores), encrypted with WebCrypto.

**DFD notation:** rectangles are external entities, numbered rounded boxes are processes, cylinders are data stores.

## DFD Level 0: context diagram

```mermaid
flowchart LR
    U["User"]
    G["Google<br/>Gmail · Drive<br/>(optional, read-only)"]
    L["External LLM<br/>Anthropic · OpenAI<br/>(optional, off by default)"]
    CAL["Calendar app<br/>Google · iPhone · Outlook"]
    SYS(("0<br/>DocMind"))

    U -- "documents, WhatsApp export,<br/>requests, approvals" --> SYS
    SYS -- "found documents, missing list,<br/>bundles, reminders" --> U
    G -- "attachment metadata, files on import" --> SYS
    SYS -- "request wording only<br/>(never documents), with consent" --> L
    L -- "parsed intent" --> SYS
    SYS -- "expiry reminders (.ics)" --> CAL
```

## DFD Level 1

```mermaid
flowchart TB
    U["User"]
    G["Google Gmail / Drive"]
    L["External LLM (optional)"]
    CAL["Calendar app"]

    P1("1.0<br/>Authenticate<br/>password · 2FA · vault PIN")
    P2("2.0<br/>Ingest document<br/>sniff type · encrypt")
    P3("3.0<br/>Understand document<br/>OCR · classify · extract dates")
    P4("4.0<br/>Assistant<br/>detect task · search sources")
    P5("5.0<br/>Personal memory<br/>propose → approve")
    P6("6.0<br/>Bundles & reminders")
    P7("7.0<br/>Connect & index<br/>external sources")

    D1[("D1 Users & sessions")]
    D2[("D2 Encrypted file store<br/>AES-256-GCM per file")]
    D3[("D3 Documents<br/>metadata + encrypted text")]
    D4[("D4 Memory<br/>facts · proposals · checklists")]
    D5[("D5 Bundles")]
    D6[("D6 Conversations")]
    D7[("D7 Connected sources<br/>+ external refs")]
    D8[("D8 Audit log")]
    K[("K Knowledge catalog<br/>30 doc types · 13 processes<br/>(in code)")]

    U -- "credentials, TOTP, PIN" --> P1
    P1 -- "verify / rotate tokens" --> D1
    P1 -- "security events" --> D8
    U -- "files, WhatsApp .zip" --> P2
    P2 -- "encrypted bytes" --> D2
    P2 -- "new document record" --> D3
    D2 -- "decrypted in memory" --> P3
    K -- "type rules, keywords" --> P3
    P3 -- "text, type, issuer, expiry,<br/>duplicates, smart name" --> D3
    U -- "relabel" --> P3
    U -- "request: what do I need for…" --> P4
    P4 -- "wording only, with consent" --> L
    L -- "parsed intent" --> P4
    K -- "process → required documents" --> P4
    D4 -- "saved checklist" --> P4
    D3 -- "matching documents" --> P4
    D7 -- "found-but-not-downloaded" --> P4
    P4 -- "messages (encrypted)" --> D6
    P4 -- "found · missing · official sources" --> U
    P4 -- "proposed checklist" --> P5
    U -- "approve / edit / delete" --> P5
    P5 -- "approved facts & checklists" --> D4
    U -- "select, rename" --> P6
    D3 -- "documents" --> P6
    P6 -- "bundle" --> D5
    P6 -- "files with organised names" --> U
    P6 -- ".ics reminders" --> CAL
    U -- "connect (OAuth 2.0 + PKCE)" --> P7
    G -- "attachment metadata" --> P7
    P7 -- "encrypted tokens, refs" --> D7
    P7 -- "imported file" --> P2
```

## ERD

DocMind Server stores its data in SQLite. Columns ending in `_enc` and keys named `wrapped_*` hold encrypted data (envelope encryption: a per-user data key, wrapped by the server master key, and a per-file key wrapped by the user's key). Tables are shown with keys and main columns, not every column.

### Documents, memory and the assistant

```mermaid
erDiagram
    USERS |o--o{ CATEGORIES : "user_id"
    USERS ||--o{ DOCUMENTS : "user_id"
    DOCUMENTS |o--o{ DOCUMENTS : "duplicate_of"
    USERS ||--o{ CHECKLISTS : "user_id"
    USERS ||--o{ MEMORY_FACTS : "user_id"
    USERS ||--o{ MEMORY_PROPOSALS : "user_id"
    USERS ||--o{ BUNDLES : "user_id"
    CHECKLISTS |o--o{ BUNDLES : "checklist_id"
    BUNDLES ||--o{ BUNDLE_ITEMS : "bundle_id"
    DOCUMENTS |o--o{ BUNDLE_ITEMS : "document_id"
    USERS ||--o{ CONVERSATIONS : "user_id"
    CONVERSATIONS ||--o{ MESSAGES : "conversation_id"
    CATEGORIES ||..o{ DOCUMENTS : "category_key = key (logical)"
    USERS {
        text id PK
        text email
        text password_hash
        blob wrapped_dek
        int token_version
        text vault_pin_hash
        int totp_enabled
    }
    CATEGORIES {
        text id PK
        text user_id FK
        text key
        text name_en
        text name_he
        int is_custom
    }
    DOCUMENTS {
        text id PK
        text user_id FK
        text source_kind
        text display_name
        text mime_type
        text sha256
        text storage_key
        blob wrapped_file_key
        blob text_enc
        text category_key
        text doc_type
        float doc_type_confidence
        text issuer
        text doc_date
        text expiry_date
        text status
        text duplicate_of FK
        text duplicate_kind
    }
    CHECKLISTS {
        text id PK
        text user_id FK
        text name
        text purpose_key
        text items_json
        int version
        int use_count
    }
    MEMORY_FACTS {
        text id PK
        text user_id FK
        text kind
        text key
        text value_json
    }
    MEMORY_PROPOSALS {
        text id PK
        text user_id FK
        text kind
        text payload_json
        text status
    }
    BUNDLES {
        text id PK
        text user_id FK
        text name
        text checklist_id FK
    }
    BUNDLE_ITEMS {
        text id PK
        text bundle_id FK
        int position
        text label
        text doc_type
        text document_id FK
        text custom_filename
        int selected
    }
    CONVERSATIONS {
        text id PK
        text user_id FK
        text title
    }
    MESSAGES {
        text id PK
        text conversation_id FK
        text role
        blob content_enc
    }
```

### Security, sessions and connected sources

```mermaid
erDiagram
    USERS ||--o{ REFRESH_TOKENS : "user_id"
    USERS ||--o{ CONNECTED_SOURCES : "user_id"
    USERS ||--o{ OAUTH_STATES : "user_id"
    USERS ||--o{ EXTERNAL_REFS : "user_id"
    USERS ||..o{ AUDIT_LOG : "user_id (no FK: kept after account deletion)"
    USERS {
        text id PK
        text email
        text password_hash
        blob wrapped_dek
        int token_version
        text vault_pin_hash
        int totp_enabled
    }
    REFRESH_TOKENS {
        text id PK
        text user_id FK
        text token_hash
        text expires_at
        text revoked_at
    }
    CONNECTED_SOURCES {
        text id PK
        text user_id FK
        text kind
        text account_label
        blob tokens_enc
        text scopes
        text status
    }
    OAUTH_STATES {
        text state PK
        text user_id FK
        text kind
        text verifier
    }
    EXTERNAL_REFS {
        text id PK
        text user_id FK
        text kind
        text ref
        text doc_type
        blob meta_enc
    }
    AUDIT_LOG {
        text id PK
        text user_id
        text action
        text target
        text created_at
    }
```

`audit_log` has no foreign key on purpose, so the security history survives account deletion.

### Opt-in shared learning (anonymous, disabled by default)

```mermaid
erDiagram
    SHARED_PATTERNS {
        text process_key PK
        text doc_type PK
        int contributors
    }
    SHARED_CONTRIBUTIONS {
        text contributor_hash PK
        text process_key PK
        text doc_type PK
    }
```

These two tables hold no user ids and no document content: only counts of which document types are needed for which process. `contributor_hash` is a keyed HMAC that cannot be linked back to a user without the server secret.
