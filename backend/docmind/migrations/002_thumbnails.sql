-- 002: encrypted thumbnails stored alongside documents.
ALTER TABLE documents ADD COLUMN thumb_key TEXT;
ALTER TABLE documents ADD COLUMN wrapped_thumb_key BLOB;
