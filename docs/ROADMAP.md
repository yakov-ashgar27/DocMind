# Roadmap

## Stage 1: done
Authentication, upload, encrypted library, OCR (he+en), classification, natural-language search, the assistant, consent-based checklists, bundles with individual downloads, an optional combined PDF, duplicate and outdated detection, WhatsApp export import, privacy controls, audit log, and 44 automated tests.

## Stage 2: code complete, needs live verification
- Gmail and Drive connectors (OAuth + PKCE, search, deep links, import). **Next step:** register an OAuth client, connect a real account, and verify Hebrew query quality on real mail.
- ✅ Background index of Gmail/Drive attachments (encrypted metadata only).

## Stage 3
- Expo Android app: SAF folder access, the photo picker, a share target from WhatsApp and Files, and on-device OCR.
- Smarter contextual suggestions, such as "your last application also used a previous scholarship approval".
- ✅ Expiry reminders (dashboard + .ics calendar export). Next: web push notifications (free, VAPID).

## Security options for later
- An optional PIN-derived encryption layer for vault documents (trade-off: their content would not be searchable while locked).
- Web push notifications (free, VAPID) for expiry reminders.
- Biometric unlock (WebAuthn / passkeys) for the vault on phones.

## Stage 4
- Enable shared learning after a privacy review (k-anonymity is already in place; consider adding differential-privacy noise).
- More providers (OneDrive, Dropbox, iCloud via share).
- Postgres, Redis (rate limits and job queue), S3 with KMS, horizontal scaling.
- Encrypted metadata with blind indexes, an external security audit, and SOC 2 groundwork.

## Known limitations (honest list)
- The assistant's local engine understands requests through a curated bilingual lexicon of 24 document types and 8 processes, plus free-form "documents for X" tasks. Unusual phrasings fall back to content search. The optional LLM provider covers more phrasings without sending documents.
- Classification and freshness rules are heuristic. They have been tested on fictional sample documents, not yet on a corpus of real ones. Confidence is shown, and users can correct the type; corrections improve future classification.
- HEIC/AVIF photos are decoded with ImageMagick (libheif); installing `pillow-heif` is optional and faster.
- PDF preview uses the browser's built-in viewer.
- Single-process deployment (in-memory rate limiting and job queue).
