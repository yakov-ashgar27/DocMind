// Android app integration (window.DocMindNative). In a normal browser every function here is a no-op.
const N = typeof window !== "undefined" ? window.DocMindNative : null;
export const isNative = !!N;
const listeners = {};

if (isNative) {
  window.__docmindNative = (event, data) => (listeners[event] || []).forEach((fn) => fn(data));
}
export function onNative(event, fn) { (listeners[event] ||= []).push(fn); }
function once(event) { return new Promise((resolve) => { const fn = (d) => { listeners[event] = listeners[event].filter((x) => x !== fn); resolve(d); }; onNative(event, fn); }); }

export function info() {
  if (!isNative) return { platform: "web", media: false, folders: [], bundledOcr: false };
  try { return JSON.parse(N.info()); } catch { return { platform: "android", media: false, folders: [], bundledOcr: false }; }
}
export async function requestMedia() { const p = once("permission"); N.requestMedia(); return (await p).media; }
export async function addFolder(kind) { const p = once("folder"); N.addFolder(kind); return (await p).ok; }
export function removeFolder(uri) { N.removeFolder(uri); }
export async function scan(sinceMs, maxImages) { const p = once("scan"); N.scan(sinceMs, maxImages); return p; }
export function takeShared() { try { return JSON.parse(N.takeShared()); } catch { return []; } }

const b64url = (s) => btoa(unescape(encodeURIComponent(s))).replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/, "");
export async function readUri(uri) {
  const r = await fetch(`/native/file/${b64url(uri)}`);
  if (!r.ok) throw new Error("file_unavailable");
  return new Uint8Array(await r.arrayBuffer());
}

async function toB64(blob) {
  const buf = new Uint8Array(await blob.arrayBuffer());
  let s = "";
  for (let i = 0; i < buf.length; i += 0x8000) s += String.fromCharCode(...buf.subarray(i, i + 0x8000));
  return btoa(s);
}
export async function saveBlob(blob, name, mime) { return N.saveFile(name, mime || blob.type || "application/octet-stream", await toB64(blob)); }
export async function shareBlobs(files) {
  const payload = [];
  for (const f of files) payload.push({ name: f.name, mime: f.type || "application/octet-stream", b64: await toB64(f) });
  return N.shareFiles(JSON.stringify(payload)) === "ok";
}
