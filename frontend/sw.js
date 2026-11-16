// Offline shell only. API responses (personal data) are never cached.
const CACHE = "docmind-shell-v2";
const SHELL = ["/", "/css/app.css", "/js/app.js", "/js/api.js", "/js/i18n.js", "/js/ui.js", "/js/router.js",
  "/js/store.js", "/js/components.js", "/js/vault.js", "/js/views/home.js", "/js/views/assistant.js", "/js/views/library.js",
  "/js/views/bundles.js", "/js/views/memory.js", "/js/views/more.js", "/icons/icon.svg", "/manifest.webmanifest"];

self.addEventListener("install", (e) => e.waitUntil(caches.open(CACHE).then((c) => c.addAll(SHELL)).then(() => self.skipWaiting())));
self.addEventListener("activate", (e) => e.waitUntil(
  caches.keys().then((ks) => Promise.all(ks.filter((k) => k !== CACHE).map((k) => caches.delete(k)))).then(() => self.clients.claim())));
self.addEventListener("fetch", (e) => {
  const url = new URL(e.request.url);
  if (e.request.method !== "GET" || url.origin !== location.origin || url.pathname.startsWith("/api/")) return;
  // Network first so deployments take effect immediately; cache is the offline fallback.
  e.respondWith(fetch(e.request).then((r) => {
    const copy = r.clone();
    caches.open(CACHE).then((c) => c.put(e.request, copy));
    return r;
  }).catch(() => caches.match(e.request).then((m) => m || caches.match("/"))));
});
