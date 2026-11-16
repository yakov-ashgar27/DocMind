# Source integrations

## Gmail and Google Drive (Stage 2: implemented, needs credentials)
1. In Google Cloud Console, create a project and enable the **Gmail API** and the **Google Drive API**.
2. Configure the OAuth consent screen (External, testing mode). Add your Google account as a test user.
3. Create an OAuth client of type *Web application*, with the redirect URI `http://localhost:8000/api/oauth/google/callback` (or your HTTPS domain).
4. Set the following and restart:
   ```
   GOOGLE_CLIENT_ID=...
   GOOGLE_CLIENT_SECRET=...
   GOOGLE_REDIRECT_URI=http://localhost:8000/api/oauth/google/callback
   ```
5. In the app, go to **More → Connected sources → Gmail → Connect**.

Behaviour: the search queries Gmail as `has:attachment {"<Hebrew and English aliases>"}`, and Drive as `fullText contains` / `name contains`. Results show **"Found externally — not downloaded"**, with a direct link to the exact email or file and a *Download to library* action. That action fetches the attachment through the API, then encrypts, OCRs and classifies it like any upload.

`gmail.readonly` and `drive.readonly` are *restricted* scopes. Up to 100 test users work without review. A public launch needs Google OAuth verification, and for Gmail a third-party security assessment (CASA). Plan for this early.

The Google code was tested here against a mocked API (`tests/test_bundles_connectors.py`). It has not yet been run against live Google accounts, so the first real connection should be treated as an integration test.

## WhatsApp
WhatsApp offers **no official API for reading a personal account's chats or media**. The WhatsApp Business Platform is for businesses messaging customers. Scraping WhatsApp Web or using unofficial clients violates WhatsApp's terms, so DocMind does neither.

Supported routes:
- **Now:** in the chat, tap ⋮ → More → **Export chat** → **Include media**, then choose **Import WhatsApp chat** in DocMind. PDFs and images are imported and tagged with source `whatsapp`.
- **Stage 3 (Android app):** register DocMind as a share target, so a user can long-press a file in WhatsApp → Share → DocMind.

## Android local files and gallery (Stage 3)
The plan is an Expo/React Native client that uses the Storage Access Framework (`ACTION_OPEN_DOCUMENT_TREE`) for user-chosen folders such as Downloads, and the MediaStore/`READ_MEDIA_IMAGES` photo picker for the gallery. OCR stays on-device (ML Kit text recognition, which covers Latin script; Hebrew needs Tesseract on-device or the server path). The client sends documents to the same `/api/documents` endpoint with `source=device_gallery|device_downloads`.

## Adding a connector
Subclass `connectors.base.Connector` (or `LibraryConnector`), set `key`, `order` and `label`, implement `availability()` and `find()`, and add it to `registry()`. Discovery, statuses, de-duplication and the UI's source list pick it up automatically.
