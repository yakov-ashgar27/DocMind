// Phone edition: same interface as frontend/js/api.js, answered by the on-device engine (core/local.js).
import { handle } from "./core/local.js";
import * as V from "./core/vault.js";

export class ApiError extends Error {
  constructor(code, status, data) { super(code); this.code = code; this.status = status; this.data = data; }
}
let onVaultLocked = async () => false;
let onUnauthorized = () => {};
export function setVaultHandler(fn) { onVaultLocked = fn; }
export function setUnauthorizedHandler(fn) { onUnauthorized = fn; }
export function onVaultChange(fn) { V.session.listeners.add(fn); return () => V.session.listeners.delete(fn); }
export const vaultUnlocked = () => V.vaultOpen();
export const lockVault = () => V.lockVault();
export function setVaultToken() { /* the phone edition keeps the vault key itself in memory */ }

export async function api(path, { method = "GET", body, form, query, raw } = {}, retried = false) {
  try {
    const res = await handle(method, path, { body: body || {}, form, query: query || {} });
    if (raw) {
      if (res instanceof Response) return res;
      return new Response(JSON.stringify(res), { headers: { "content-type": "application/json" } });
    }
    return res;
  } catch (e) {
    const code = e.code || e.message || "error";
    if (code === "vault_locked" && !retried && (await onVaultLocked())) return api(path, { method, body, form, query, raw }, true);
    if (code === "unauthorized") onUnauthorized();
    if (String(code).startsWith("temporarily_locked:")) throw new ApiError("temporarily_locked", 429, { seconds: +code.split(":")[1] });
    throw new ApiError(code, e.status || 400, e.data);
  }
}

const thumbCache = new Map();
export async function thumbUrl(docId) {
  if (thumbCache.has(docId)) return thumbCache.get(docId);
  const p = api(`/documents/${docId}/thumbnail`, { raw: true }).then((r) => r.blob()).then((b) => URL.createObjectURL(b)).catch(() => null);
  thumbCache.set(docId, p);
  return p;
}
export function dropThumb(docId) { thumbCache.delete(docId); }
export function clearThumbs() { thumbCache.clear(); }

export function triggerDownload(url, filename) {
  const a = document.createElement("a");
  a.href = url;
  if (filename) a.download = filename;
  document.body.appendChild(a);
  a.click();
  a.remove();
  setTimeout(() => { if (url.startsWith("blob:")) URL.revokeObjectURL(url); }, 60000);
}

// Native share sheet (WhatsApp, Mail, Files...). Best way to send files from an iPhone.
export const canShareFiles = (files) => !!(navigator.canShare && navigator.share && navigator.canShare({ files }));
export async function shareFiles(files, title) {
  try { await navigator.share({ files, title }); return true; } catch (e) { return e.name === "AbortError"; }
}

export async function logout() { V.lockApp(); }
export function setTokenFromSession() {}
