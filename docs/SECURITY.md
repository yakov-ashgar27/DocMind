# Security & privacy

## Data at rest
- **Envelope encryption.** A master key from `DOCMIND_MASTER_KEY` wraps a per-user data key (DEK) and a per-file key. AES-256-GCM is used, with an authenticated context (AAD) that binds each ciphertext to its row id, so ciphertexts cannot be swapped between rows.
- **Encrypted:** file bytes, thumbnails, OCR/extracted text, chat messages and their structured payloads, and OAuth tokens.
- **Plaintext (needed for listing and filtering):** filenames, display names, type, category, issuer, dates and tags. A future hardening step can encrypt these too, using blind indexes.
- **Deletion.** Removing a document overwrites and unlinks the blob and deletes the wrapped key (crypto-shredding). Deleting an account cascades every row; without the wrapped DEK, any remaining ciphertext in backups is unreadable.

## Vault — PIN-protected folders
- The user chooses which categories are protected. Identity, finance and medical are protected by default as soon as a PIN is set.
- While the vault is locked, protected documents are hidden **in every API response**, enforced at a single server-side choke point (an `after_request` redaction of all JSON). Names, filenames, dates, issuers, tags, previews, thumbnails, text, downloads, bundle links, calendar exports and conversation history are all covered. Search ignores their content. The assistant can only say that a matching document exists and is protected.
- File and detail endpoints return `423 vault_locked`; the app then asks for the PIN.
- The PIN is hashed with scrypt. Unlocking issues a 5-minute vault token held only in memory. The app also drops it as soon as it goes to the background.
- After 5 wrong PINs, the vault locks for 15 minutes. Setting or changing the PIN needs the account password, and changing the PIN or un-protecting a folder needs the vault to be unlocked.
- "Sign out of all devices" also invalidates vault tokens.
- Honest scope: the vault is an access gate on top of the encryption at rest that protects everything. It is not a second, PIN-derived encryption layer. That is deliberate, so OCR, search and reminders keep working, and it is listed as a future option in the roadmap.

## Authentication & sessions
- scrypt (N=2^15, r=8) password hashing with constant-time comparison. Unknown emails take the same time as wrong passwords.
- 15-minute HS256 access tokens, held in memory only (never in localStorage).
- A 30-day refresh token in an `httpOnly`, `SameSite=Strict` cookie scoped to `/api/auth`, rotated on every use. Reusing a rotated token revokes **all** of the user's sessions.
- `token_version` makes "sign out of all devices" and password changes revoke access tokens immediately.
- Rate limits apply to register, login, refresh, upload, assistant and download links.
- **Per-account lockout:** after 10 wrong passwords, the account locks for 15 minutes, on top of the per-IP limits.
- **Two-step verification (TOTP, RFC 6238):** works with Google Authenticator, Microsoft Authenticator, 1Password and others. The secret is encrypted with the user's key. Sign-in returns a 5-minute `mfa_token`, and a session starts only after a valid code. There are 8 single-use recovery codes, stored hashed. Turning 2FA off needs both the password and a current code.

## Transport & browser
- Strict CSP (`script-src 'self'`, with no inline scripts or styles, no eval, and `frame-ancestors 'none'`), `nosniff`, `X-Frame-Options: DENY`, `Referrer-Policy: no-referrer`, and HSTS in production. `Cache-Control: no-store` is set on all JSON and file responses.
- The UI builds every element from text nodes; user data never passes through `innerHTML`.
- Files are downloaded and previewed through single-use signed links that expire after 120 seconds. Long-lived tokens never appear in URLs.
- Uploads are type-checked by magic bytes. WhatsApp ZIP imports are capped by member count and total size and read in memory; nothing is extracted to disk paths.

## External services
- No passwords for external services are ever requested. Google uses OAuth 2.0 authorization code + PKCE, read-only scopes and a one-time `state`. Tokens are encrypted, and disconnecting revokes them at Google.
- An LLM is used only if the operator configures one **and** the user turns on consent. It receives the request wording only.
- Shared learning is off globally (`DOCMIND_SHARED_LEARNING`) and per user. When enabled, it shares only canonical (process, document type) pairs. Contributors are recorded as HMAC hashes, and patterns appear only once K ≥ 20 distinct contributors agree.

## Audit
`audit_log` records sign-in and failures, uploads, updates, previews and downloads, deletions, memory decisions, connector events, exports and setting changes. Users can view their own log in Settings.

## Production checklist
- [ ] Set `DOCMIND_ENV=production`, `DOCMIND_MASTER_KEY`, `DOCMIND_JWT_SECRET` (from a KMS or secrets manager), and `DOCMIND_SECURE_COOKIES=1`.
- [ ] Serve behind TLS with a WSGI server (`gunicorn -w 1 --threads 8 'docmind.app:create_app()'`). Keep one worker until the rate limiter and job queue move to Redis.
- [ ] Back up the encrypted blobs and DB; store the master key separately.
- [ ] Get an external penetration test before handling real identity documents at scale.
