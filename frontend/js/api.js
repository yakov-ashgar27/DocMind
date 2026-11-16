// API client. Access token lives only in memory; the refresh token is an httpOnly cookie.
let accessToken = null;
let refreshing = null;
let onUnauthorized = () => {};
let vaultToken = null;
let vaultTimer = null;
let onVaultLocked = async () => false;
const vaultListeners = new Set();

export function setVaultHandler(fn) { onVaultLocked = fn; }
export function onVaultChange(fn) { vaultListeners.add(fn); return () => vaultListeners.delete(fn); }
export function vaultUnlocked() { return !!vaultToken; }
export function setVaultToken(token, ttl) {
  vaultToken = token;
  clearTimeout(vaultTimer);
  if (token) vaultTimer = setTimeout(() => lockVault(), ttl * 1000);
  vaultListeners.forEach((f) => f(!!token));
}
export function lockVault() { if (vaultToken) setVaultToken(null); }
// Lock the vault as soon as the app goes to the background.
document.addEventListener("visibilitychange", () => { if (document.visibilityState === "hidden") lockVault(); });

export class ApiError extends Error {
  constructor(code, status, data) { super(code); this.code = code; this.status = status; this.data = data; }
}

export function setUnauthorizedHandler(fn) { onUnauthorized = fn; }
export function setToken(t) { accessToken = t; }
export function hasToken() { return !!accessToken; }

export async function refreshSession() {
  if (!refreshing) {
    refreshing = fetch("/api/auth/refresh", { method: "POST", credentials: "same-origin" })
      .then(async (r) => {
        if (!r.ok) { accessToken = null; return null; }
        const data = await r.json();
        accessToken = data.access_token;
        scheduleRefresh(data.expires_in);
        return data.user;
      })
      .finally(() => { refreshing = null; });
  }
  return refreshing;
}

let timer = null;
function scheduleRefresh(seconds) {
  clearTimeout(timer);
  timer = setTimeout(() => refreshSession(), Math.max(30, seconds - 60) * 1000);
}

export async function api(path, { method = "GET", body, form, query, raw } = {}, retried = false) {
  let url = "/api" + path;
  if (query) {
    const q = new URLSearchParams(Object.entries(query).filter(([, v]) => v !== undefined && v !== null && v !== ""));
    if ([...q].length) url += "?" + q;
  }
  const headers = {};
  if (accessToken) headers.Authorization = "Bearer " + accessToken;
  if (vaultToken) headers["X-Vault-Token"] = vaultToken;
  let payload;
  if (form) payload = form;
  else if (body !== undefined) { headers["Content-Type"] = "application/json"; payload = JSON.stringify(body); }
  const r = await fetch(url, { method, headers, body: payload, credentials: "same-origin" });
  if (r.status === 401 && !retried && !path.startsWith("/auth/")) {
    const user = await refreshSession();
    if (user) return api(path, { method, body, form, query, raw }, true);
    onUnauthorized();
    throw new ApiError("unauthorized", 401);
  }
  if (r.status === 423 && !retried) {
    if (await onVaultLocked()) return api(path, { method, body, form, query, raw }, true);
    throw new ApiError("vault_locked", 423);
  }
  if (raw) {
    if (!r.ok) throw new ApiError("http_" + r.status, r.status);
    return r;
  }
  const data = r.headers.get("content-type")?.includes("json") ? await r.json() : {};
  if (!r.ok) throw new ApiError(data.error || "http_" + r.status, r.status, data);
  return data;
}

export async function authenticate(kind, body) {
  const data = await api(`/auth/${kind}`, { method: "POST", body });
  if (data.mfa_required) return { mfa_required: true, mfa_token: data.mfa_token };
  accessToken = data.access_token;
  scheduleRefresh(data.expires_in);
  return data.user;
}

export function setTokenFromSession(data) {
  accessToken = data.access_token;
  scheduleRefresh(data.expires_in);
  return data.user;
}

export async function logout() {
  await api("/auth/logout", { method: "POST" }).catch(() => {});
  accessToken = null;
  lockVault();
  clearTimeout(timer);
}

// Authenticated image -> object URL (thumbnails). Cached per session.
const thumbCache = new Map();
export async function thumbUrl(docId) {
  if (thumbCache.has(docId)) return thumbCache.get(docId);
  const p = api(`/documents/${docId}/thumbnail`, { raw: true })
    .then((r) => r.blob()).then((b) => URL.createObjectURL(b)).catch(() => null);
  thumbCache.set(docId, p);
  return p;
}
export function dropThumb(docId) { thumbCache.delete(docId); }

// Native browser download via a short-lived, single-use signed link.
export function triggerDownload(url, filename) {
  const a = document.createElement("a");
  a.href = url;
  if (filename) a.download = filename;
  a.rel = "noopener";
  document.body.appendChild(a);
  a.click();
  a.remove();
}
