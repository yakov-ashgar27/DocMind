# Architecture

## Stack decision

| Considered | Decision | Why |
|---|---|---|
| React Native/Expo | Deferred to Stage 3 | Gallery and Downloads scanning needs native Android storage permissions. The REST API is built so a native client can use it as is. |
| Node/TypeScript backend | **Python + Flask** | The hard parts of this product are OCR, PDF handling, text classification and crypto, and Python has the strongest libraries for them (Tesseract, pdfplumber, pypdf, scikit-learn, `cryptography`). Its type-hinted modules map one-to-one onto the requested services. |
| PostgreSQL | **SQLite now**, Postgres-portable schema | Zero-ops MVP. The schema uses portable types, and `Database` is the only place that knows the dialect. Moving to Postgres means a driver swap plus `ON CONFLICT` and `BLOB→BYTEA` edits. |
| Object storage | Local encrypted blob store (`BlobStore`) | Same interface as S3/GCS (`put`, `get`, `delete`). Files are client-side encrypted before they reach any storage. |
| Background jobs | In-process `ThreadPoolExecutor` | Documents stuck in `processing` are re-queued at startup. Swap for RQ/Celery when running more than one process. |
| Frontend | No-build ES modules SPA | Nothing to compile, a strict CSP (`script-src 'self'`, no inline code), and installable as a PWA. |

## Module map

```
            ┌──────────── api/ (Flask blueprints, auth decorator, signed download links) ────────────┐
            │                                                                                         │
 assistant/ engine ──► intent (he/en)            services/ documents ──► extract (OCR) ──► classifier
            │   └────► discovery ──► connectors/ base (search order) ──► library │ whatsapp │ gmail │ drive
            │                                   └──► knowledge/catalog (acquisition guidance)
            ├────► services/memory (proposals → checklists)  ──► shared_learning (off)
            └────► services/bundles
 security/  crypto (envelope encryption, scrypt) · auth (JWT + refresh rotation) · audit · rate limit
```

## Key flows

**Ingestion.** Upload, then magic-byte sniff, then SHA-256 (exact duplicate check), then encrypt and store. A background worker then runs: text extraction (PDF native text, else rasterise and OCR heb+eng), classification (knowledge scorer plus the personal nearest-neighbour layer), issuer/date/expiry extraction, a smart name, the encrypted thumbnail, near-duplicate check (Jaccard ≥ 0.85 within the same type), and finally search index invalidation.

**Discovery.** For each requirement, `discovery.find_requirement` asks every *searchable* connector in the mandated order (local files, gallery, downloads, WhatsApp, Gmail, Drive). It then de-duplicates (by document id, external ref, and filename+size) and ranks exact-type matches above content matches, and local copies above external ones. A requirement becomes `not_found` only when every searchable source answered. If a source failed, the status is `search_incomplete` and no acquisition advice is shown. Acquisition guidance is attached only after a complete search.

**Memory.** The engine never writes checklists directly. It creates a `memory_proposals` row, and only the user's confirmation (chat "yes", the button, or the Memory screen) applies it. Matching a later request uses the canonical process key first, then trigram overlap with the saved name.

**Statuses.** `found_local`, `found_whatsapp`, `found_gmail`, `found_gdrive`, `found_external_not_downloaded`, `not_found`, `search_incomplete`. Each answer also includes `sources_searched` and `sources_unavailable`.

## Intelligence without sending documents anywhere

- OCR runs locally (Tesseract).
- The classifier is deterministic and explainable (`signals`), and it adapts per user through documents the user has relabelled.
- Search is TF-IDF over decrypted text, built in memory per user and never persisted. The `SearchIndex` seam allows a local embedding model later.
- The optional LLM sees only the request text, and the parsed keys are validated against the catalog.
