# DocMind — Intelligent Personal Document Assistant

[![Open in GitHub Codespaces](https://github.com/codespaces/badge.svg)](https://codespaces.new/yakov-ashgar27/DocMind)

🌐 **Website:** https://yakov-ashgar27.github.io/DocMind/ · 🤖 **Android app (APK):** https://yakov-ashgar27.github.io/DocMind/DocMind.apk (mirror: [GitHub release](https://github.com/yakov-ashgar27/DocMind/releases/download/android-latest/DocMind.apk)) · 📱 **Web app (iPhone/any phone):** https://yakov-ashgar27.github.io/DocMind/app/

## Two editions

| | 📱 **Phone edition** (`mobile/`, Android app in `android/`) | 💻 **DocMind Server** (`backend/` + `frontend/`) |
|---|---|---|
| Install | Android: download the APK (built free by GitHub Actions). iPhone/any phone: open the link, then "Add to Home Screen" | Your computer, Docker or Codespaces |
| Automatic phone scan (gallery, Downloads, WhatsApp folder), Share → DocMind | Android app ✅ | — |
| Where documents live | Encrypted on the phone only (IndexedDB + WebCrypto) | Encrypted on your computer |
| Hebrew OCR, assistant, memory, bundles, vault, reminders, WhatsApp import | ✅ | ✅ |
| Gmail and Google Drive | — | ✅ |
| Server needed | No | Yes (yours) |

Both editions share one knowledge base (`backend/docmind/knowledge/catalog.py`, exported to `mobile/js/catalog.js`), and CI verifies that they classify documents and understand requests identically (`scripts/parity_check.py`).

**Phone edition security:** a passcode derives the key with PBKDF2 (600k iterations), so without it nothing can be decrypted. Every document has its own AES-256-GCM key. Protected folders wrap those keys with an RSA-3072 vault key whose private half is sealed by the vault PIN, so documents can be *added* to the vault without the PIN, but only the PIN opens them. The app auto-locks, slows down repeated wrong passcodes, and makes encrypted backup files for moving to a new phone. OCR (tesseract.js) is downloaded once from a CDN and then cached. Document bytes never leave the device.

**Android app: whole-phone scan.** The first scan indexes the whole phone (all folders, any age, memory card) and can take a while; search works during it. It keeps running with the screen off (an ongoing notification shows progress), and the index is kept permanently, so later scans only read new files. Two things to know:
1. **Don't swipe DocMind away from recent apps while it scans**, because that stops the scan. Turning the screen off or switching apps is fine. If it is stopped, it resumes where it left off next time.
2. **Battery saving** (Samsung and others) can pause background work. Tap **"Allow background activity"** on the scan screen (Android's own dialog), or set Settings → Apps → DocMind → Battery → **Unrestricted**.

> Tell it what you need. It finds what you have, remembers what you need, and helps you obtain what is missing.

DocMind is a working Stage 1 product. It is a mobile-first web app (installable PWA) with full Hebrew RTL and English, on a modular Python backend. The backend provides encrypted storage, on-device OCR, automatic classification, semantic search, a bilingual assistant, consent-based personal memory, and document bundles.

## What works today (Stage 1, plus part of Stages 2 and 3)

| Area | Status |
|---|---|
| Accounts: scrypt passwords, 15-min JWT access tokens, rotating refresh cookie with reuse detection, sign out everywhere, rate limits | ✅ working, tested |
| Encrypted storage: AES-256-GCM per-file keys and per-user data keys (envelope encryption); OCR text and chat history encrypted too; crypto-shredding on delete | ✅ |
| Upload of PDF, JPG, PNG, WEBP, TIFF and TXT, with magic-byte sniffing (client MIME type ignored) | ✅ |
| On-device OCR, Hebrew and English (Tesseract), rotation retry, and OCR for scanned PDFs | ✅ |
| Classification into 30 document types and 12 categories (plus custom ones), with 13 common Israeli processes, including Israeli ID check digit, IBAN and passport MRZ signals | ✅ |
| Issuer, document date and expiry extraction; "may be outdated" flags | ✅ |
| Smart names for meaningless filenames (`IMG_20261115_132411.jpg` becomes "תעודת זהות") | ✅ |
| Personal classifier: a document you relabel teaches it about similar documents | ✅ |
| **Vault:** PIN-protected folders (identity, finance and medical by default, configurable), hidden in every response until unlocked; auto-lock after 5 minutes or when the app is left | ✅ |
| **Two-step verification** (Authenticator app, recovery codes), per-account lockout | ✅ |
| Exact and near duplicate detection; nothing is ever deleted automatically | ✅ |
| Natural-language and content search (character n-gram TF-IDF, robust to Hebrew prefixes and OCR noise), with filters for category, type, source, issuer, dates and tags | ✅ |
| Hebrew/English assistant: task detection, "which documents were required?", search of every source, statuses, official sources for missing documents | ✅ |
| Personal memory: checklists saved only after you approve; reused next time with "has anything changed?"; any change goes through a proposal; can be inspected, edited and deleted | ✅ |
| Bundles: preview, select, rename, download each file **individually** with organised names; optional combined PDF | ✅ |
| WhatsApp: import of an exported chat (.zip with media), the officially supported route | ✅ |
| iPhone HEIC and AVIF photos (decoded locally via libheif) | ✅ |
| Expiry reminders on the dashboard, plus a standard calendar file (.ics) for Google Calendar, iPhone or Outlook; reminder window is configurable | ✅ |
| Background index of Gmail/Drive attachments (encrypted metadata only, nothing downloaded) for fast discovery | ⚙️ tested with a mocked Google API |
| Gmail and Google Drive: OAuth 2.0 + PKCE, read-only search, "found but not downloaded" status, link to the exact email, import into the library | ⚙️ implemented and tested against a mocked Google API; needs your OAuth credentials (see `docs/INTEGRATIONS.md`) |
| Shared aggregate learning: k-anonymous, opt-in, process keys only | 🔒 built and **disabled by default** |
| External LLM (Anthropic or OpenAI) behind a provider abstraction; sends request wording only, never documents | ⚙️ optional, off unless configured **and** the user consents |
| Android gallery/downloads scanning | ⏳ Stage 3 (needs the native app); the UI says so honestly |

The assistant never claims to have searched a source it could not search. Each answer lists the sources searched and the ones that are not connected.

## Quick start

**🇮🇱 Hebrew step-by-step guide, including connecting Gmail for free: [`docs/SETUP_HE.md`](docs/SETUP_HE.md)**

Everything DocMind uses is free and open source; there are no paid services.

Requirements: Python 3.11+, Tesseract 5 with `heb` and `eng` traineddata, poppler-utils (`pdftoppm`), and optionally ImageMagick with libheif for iPhone photos.

```bash
# Debian/Ubuntu system packages
sudo apt install tesseract-ocr tesseract-ocr-heb poppler-utils imagemagick
./start.sh        # Windows: double-click start.bat
# then open http://localhost:8000
```

**Install on your phone:** DocMind is an installable PWA (Chrome reports it installable). Reach your own computer privately over HTTPS with Tailscale's free Personal plan (`tailscale serve --bg 8000`), then use "Install app" / "Add to Home Screen". Step-by-step instructions are in `docs/SETUP_HE.md`.

Or with Docker (free):

```bash
cp .env.example .env    # fill in the keys
docker compose up --build
```

Development keys are generated automatically in `./data/`. For anything real, set the variables in `.env.example`.

Sample documents (clearly fictional, stamped SAMPLE) are in `backend/tests/fixtures/`. To regenerate them:

```bash
python scripts/make_sample_docs.py backend/tests/fixtures
```

### Tests

```bash
cd backend && pip install -r requirements-dev.txt && python -m pytest -q   # security, pipeline, assistant, bundles, connectors, reminders
python ../scripts/ui_check.py http://localhost:8000 /tmp/shots   # headless browser walkthrough + screenshots
```

## Project layout

```
backend/
  docmind/
    app.py                 app factory, security headers, static frontend
    config.py              env-driven config (secrets never in code)
    db.py + migrations/    SQLite (Postgres-portable SQL), forward-only migrations
    security/              crypto (envelope encryption, scrypt), auth (JWT/refresh), audit + rate limit
    services/              extract (OCR), classifier, search, documents, memory, bundles, shared_learning
    assistant/             intent (he/en parser), discovery (cross-source search), engine (dialogue), llm, texts
    connectors/            base (search order + honest availability), google (Gmail/Drive OAuth)
    knowledge/catalog.py   document types, processes, official acquisition guidance
    api/                   REST endpoints
  tests/                   pytest suite + fictional fixtures
frontend/                  no-build ES-module SPA, RTL-first CSS, PWA manifest + service worker
docs/                      ARCHITECTURE, API, SECURITY, INTEGRATIONS, ROADMAP, SETUP_HE (Hebrew guide), screenshots/
.github/workflows/ci.yml   GitHub Actions: runs the full test suite on every push
Dockerfile, docker-compose.yml, start.sh, start.bat
scripts/                   sample document generator, UI walkthrough
```

See `docs/ARCHITECTURE.md` for the design decisions and `docs/ROADMAP.md` for the remaining stages.
