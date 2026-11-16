// Offline-first shell. App files: network-first (updates apply), OCR engine from the CDN: cache-first
// (downloaded once, then works offline). Documents are never handled here: they live encrypted in IndexedDB.
const VERSION = "docmind-phone-v1";
const SHELL = ["./", "index.html", "manifest.webmanifest", "css/app.css", "icons/icon-192.png", "icons/icon-512.png", "icons/icon.svg",
  "js/app.js", "js/api.js", "js/catalog.js", "js/components.js", "js/i18n.js", "js/router.js", "js/store.js", "js/ui.js", "js/vault.js",
  "js/views/home.js", "js/views/assistant.js", "js/views/library.js", "js/views/bundles.js", "js/views/memory.js", "js/views/more.js",
  "js/core/backup.js", "js/core/classifier.js", "js/core/crypto.js", "js/core/db.js", "js/core/engine.js", "js/core/extract.js",
  "js/core/intent.js", "js/core/local.js", "js/core/repo.js", "js/core/search.js", "js/core/vault.js", "js/core/zip.js",
  "vendor/pdf.min.mjs", "vendor/pdf.worker.min.mjs", "vendor/pdf-lib.esm.min.js"];
const CDN = ["cdn.jsdelivr.net", "tessdata.projectnaptha.com"];

self.addEventListener("install", (e) => e.waitUntil(caches.open(VERSION).then((c) => c.addAll(SHELL)).then(() => self.skipWaiting())));
self.addEventListener("activate", (e) => e.waitUntil(caches.keys()
  .then((ks) => Promise.all(ks.filter((k) => k !== VERSION && k !== "docmind-ocr").map((k) => caches.delete(k)))).then(() => self.clients.claim())));
self.addEventListener("fetch", (e) => {
  const url = new URL(e.request.url);
  if (e.request.method !== "GET") return;
  if (CDN.includes(url.hostname)) {
    e.respondWith(caches.open("docmind-ocr").then(async (c) => {
      const hit = await c.match(e.request);
      if (hit) return hit;
      const r = await fetch(e.request);
      if (r.ok) c.put(e.request, r.clone());
      return r;
    }));
    return;
  }
  if (url.origin !== location.origin) return;
  e.respondWith(fetch(e.request).then((r) => {
    if (r.ok) { const copy = r.clone(); caches.open(VERSION).then((c) => c.put(e.request, copy)); }
    return r;
  }).catch(() => caches.match(e.request, { ignoreSearch: true }).then((m) => m || caches.match("index.html"))));
});
