-- 004: vault PIN for protected categories, per-account login lockout, TOTP two-factor auth.
ALTER TABLE users ADD COLUMN vault_pin_hash TEXT;
ALTER TABLE users ADD COLUMN vault_failed INTEGER NOT NULL DEFAULT 0;
ALTER TABLE users ADD COLUMN vault_locked_until TEXT;
ALTER TABLE users ADD COLUMN login_failed INTEGER NOT NULL DEFAULT 0;
ALTER TABLE users ADD COLUMN login_locked_until TEXT;
ALTER TABLE users ADD COLUMN totp_secret_enc BLOB;
ALTER TABLE users ADD COLUMN totp_enabled INTEGER NOT NULL DEFAULT 0;
ALTER TABLE users ADD COLUMN recovery_codes_json TEXT;
