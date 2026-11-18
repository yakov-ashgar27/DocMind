// Phone index (Android app): every document-like file on the phone (Download, Documents, WhatsApp, pictures,
// Word files) is listed, its text extracted ON THE PHONE and kept in an encrypted index, so a search like
// "אישור לימודים" or "תשפ״ז" instantly finds matching files anywhere on the phone. Nothing is imported until the
// user picks it; nothing is uploaded.
import * as cl from "./classifier.js";
import * as ex from "./extract.js";
import * as native from "../native.js";
import * as repo from "./repo.js";
import { Index } from "./search.js";
import * as cr from "./crypto.js";

const META = "pi:meta";          // { v: 2, at }
const SHARDS = 64;               // the index lives in 64 encrypted bundles: opening the app decrypts 64 records, not thousands
const shardKey = (i) => "pi:s:" + i;
const shardOf = (uri) => { let x = 0; for (let i = 0; i < uri.length; i++) x = (x * 31 + uri.charCodeAt(i)) >>> 0; return x % SHARDS; };
export const state = { running: false, stop: false, total: 0, done: 0, docs: 0, current: "" };
const listeners = new Set();
export const onProgress = (fn) => { listeners.add(fn); return () => listeners.delete(fn); };
let lastBg = 0;
const tick = () => {
  listeners.forEach((f) => f({ ...state }));
  // Mirror progress in the Android notification of the background-scan service (throttled).
  if (state.running && Date.now() - lastBg > 1500) { lastBg = Date.now(); native.bgUpdate(state.stage, state.done, state.total, state.docs); }
};
let idx = null;
let all = null;                  // Map uri -> { uri,name,mime,size,modified,source, text, doc_type, ... }
const dirty = new Set();

export async function meta() { return (await repo.getRecord(META)) || { at: null }; }
export async function lastBuilt() { return (await meta()).at; }

async function load() {
  if (all) return all;
  const m = new Map();
  for (let i = 0; i < SHARDS; i++) {
    const sh = await repo.getRecord(shardKey(i));
    if (sh) for (const [u, r] of Object.entries(sh)) m.set(u, r);
  }
  // One-time migration from the first index format (one record per file).
  const old = await repo.getRecord(META);
  if (old && Array.isArray(old.files)) {
    for (const f of old.files) {
      const r = await repo.getRecord("pi:f:" + f.uri);
      m.set(f.uri, { ...f, ...(r || {}) });
      if (r) await repo.delRecord("pi:f:" + f.uri);
      dirty.add(shardOf(f.uri));
    }
    all = m;
    await flush();
    await repo.putRecord(META, { v: 2, at: old.at });
  }
  all = m;
  return all;
}

function put(rec) { all.set(rec.uri, rec); dirty.add(shardOf(rec.uri)); idx = null; }
function drop(uri) { all.delete(uri); dirty.add(shardOf(uri)); idx = null; }
async function flush() {
  if (!dirty.size || !all) return;
  const want = new Set(dirty), buckets = new Map([...want].map((i) => [i, {}]));
  for (const [u, r] of all) { const i = shardOf(u); if (want.has(i)) buckets.get(i)[u] = r; }
  for (const [i, obj] of buckets) { await repo.putRecord(shardKey(i), obj); dirty.delete(i); }
}
async function entries() { return [...(await load()).values()].map((e) => ({ ...e, indexed: e.stage != null })); }
/** Called on app lock: forget the decrypted index from memory (it stays encrypted on the phone). */
export function forget() { if (!state.running) { all = null; idx = null; } }

/**
 * Two stages, so search works within a minute even with thousands of files:
 *  1. every file is listed (names are searchable at once) and PDF/Word text layers are read — no OCR, fast.
 *  2. OCR only where it pays: scanned PDFs (first page) and photos that look like paper documents.
 *     Selfies, landscapes, memes, stickers and tiny images are skipped by a 5 ms pixel test.
 * Incremental: files already done (same modified time) are never read again.
 */
export async function build({ photoMonths = 0 } = {}) {       // 0 = every photo, any age
  if (!native.isNative || state.running) return state;
  Object.assign(state, { running: true, stop: false, total: 0, done: 0, docs: 0, current: "", stage: 1, skipped: 0 });
  tick();
  try {
    native.bgStart();
    const res = await native.scan(photoMonths ? Date.now() - photoMonths * 30 * 86400000 : 0, 60000);
    const files = (res.items || []).filter((f) => !/\/stickers?\//i.test(f.uri) && !/\.webp$/i.test(f.name));
    await load();
    const seen = new Set(files.map((f) => f.uri));
    for (const u of [...all.keys()]) if (!seen.has(u)) drop(u);            // deleted from the phone
    const fresh = (f) => { const e = all.get(f.uri); return e && e.stage != null && e.modified === f.modified; };
    state.docs = [...all.values()].filter((e) => e.doc_type && e.doc_type !== "unknown").length;
    let lastFlush = Date.now();
    const maybeFlush = async (force = false) => { if (force || Date.now() - lastFlush > 30000) { await flush(); lastFlush = Date.now(); } };

    // ---- stage 1: every file listed (names searchable) + PDF text layers and Word, no OCR
    const s1 = files.filter((f) => !fresh(f)).sort((a, b) => isImg(a) - isImg(b) || b.modified - a.modified);
    Object.assign(state, { stage: 1, total: s1.length, done: 0 });
    tick();
    for (const f of s1) {
      if (state.stop) break;
      let rec = { ...f, text: "", doc_type: "unknown", confidence: 0, stage: 1 };
      if (isImg(f)) rec.needsOcr = f.size >= 40000;          // decided in stage 2; tiny images are icons/stickers
      else rec = await read(f, rec, { ocr: false });
      put(rec);
      state.done++;
      if (state.done % 10 === 0 || !isImg(f)) { tick(); await maybeFlush(); }
    }
    await maybeFlush(true);
    if (!state.stop) await repo.putRecord(META, { v: 2, at: new Date().toISOString() });

    // ---- stage 2: OCR, newest first, document folders before the camera roll
    const s2 = files.filter((f) => all.get(f.uri)?.needsOcr)
      .sort((a, b) => (a.source === "gallery") - (b.source === "gallery") || b.modified - a.modified);
    Object.assign(state, { stage: 2, total: s2.length, done: 0 });
    tick();
    for (const f of s2) {
      if (state.stop) break;
      state.current = f.name;
      let rec = { ...all.get(f.uri), needsOcr: false, stage: 2 };
      try {
        if (isImg(f)) {
          const bytes = await native.readUri(f.uri);
          const look = await ex.looksLikeDocument(bytes, ex.sniff(bytes, f.name) || f.mime);
          if (!look.doc) { rec.photo = true; state.skipped++; }
          else rec = await read(f, rec, { ocr: true, quick: true }, bytes);
        } else rec = await read(f, rec, { ocr: true, quick: true });
      } catch (e) { rec.error = String(e.message || e).slice(0, 60); }
      put(rec);
      state.done++;
      tick();
      await maybeFlush();
    }
    await maybeFlush(true);
    await repo.putRecord(META, { v: 2, at: new Date().toISOString() });
  } finally {
    try { await flush(); } catch { /* locked meanwhile */ }
    state.running = false;
    state.current = "";
    native.bgStop();
    tick();
  }
  return state;
}

const isImg = (f) => (f.mime || "").startsWith("image/");

async function read(f, rec, opts, bytes = null) {
  try {
    bytes = bytes || (await native.readUri(f.uri));
    const mime = ex.sniff(bytes, f.name);
    if (!mime) return rec;
    const r = await ex.extractText(bytes, mime, opts);
    const c = cl.classify(r.text, f.name);
    const was = rec.doc_type && rec.doc_type !== "unknown";
    rec = { ...rec, text: r.text.slice(0, 5000), needsOcr: !!r.needsOcr, doc_type: c.doc_type, confidence: c.confidence,
      issuer: c.issuer, doc_date: c.doc_date, expiry_date: c.expiry_date, category: c.category, sha: await cr.sha256hex(bytes) };
    if (c.doc_type !== "unknown" && !was) state.docs++;
  } catch (e) { rec.error = String(e.message || e).slice(0, 60); }
  return rec;
}

async function index() {
  if (!idx) {
    const imported = new Set([...(await repo.docs()).values()].map((d) => d.origin).filter(Boolean));
    const libShas = new Set([...(await repo.docs()).values()].map((d) => d.sha256).filter(Boolean));
    const list = (await entries()).filter((e) => !imported.has(e.uri) && !(e.sha && libShas.has(e.sha)));
    idx = new Index(list.map((e) => ({
      doc: { id: e.uri, display_name: e.name, original_filename: e.name, doc_type: e.doc_type || "unknown",
        category_key: e.category || "other", issuer: e.issuer, tags: [e.source], _e: e },
      text: e.text || "" })));
  }
  return idx;
}
export function invalidate() { idx = null; }

/** Search the phone. docType (optional) boosts files recognised as that type. */
export async function search(query, { docType = null, limit = 8 } = {}) {
  if (!native.isNative) return [];
  const ix = await index();
  const scored = new Map();
  for (const [d, s] of ix.search(query, { limit: 60, min: 0.06 })) scored.set(d.id, { e: d._e, score: s });
  if (docType && docType !== "unknown") {
    for (const d of ix.docs) if (d.doc_type === docType) {
      const cur = scored.get(d.id);
      scored.set(d.id, { e: d._e, score: (cur ? cur.score : 0) + 0.5 + (d._e.confidence || 0) * 0.3 });
    }
  }
  // Filename-only fallback for files whose text isn't indexed yet.
  const q = query.toLowerCase().split(/\s+/).filter((w) => w.length > 1);
  for (const d of ix.docs) {
    if (scored.has(d.id) || !q.length) continue;
    const n = d.display_name.toLowerCase();
    const hits = q.filter((w) => n.includes(w)).length;
    if (hits / q.length >= 0.5) scored.set(d.id, { e: d._e, score: 0.15 + 0.2 * (hits / q.length) });
  }
  return [...scored.values()].sort((a, b) => b.score - a.score || b.e.modified - a.e.modified).slice(0, limit)
    .map(({ e, score }) => ({ uri: e.uri, name: e.name, mime: e.mime, size: e.size, modified: e.modified, source: e.source,
      doc_type: e.doc_type || "unknown", doc_date: e.doc_date || null, issuer: e.issuer || null, indexed: e.indexed,
      snippet: snippet(e.text || "", query), score: Math.round(score * 1000) / 1000 }));
}

function snippet(text, query) {
  if (!text) return "";
  const words = query.split(/\s+/).filter((w) => w.length > 1);
  let i = -1;
  for (const w of words) { i = text.indexOf(w); if (i >= 0) break; }
  const start = Math.max(0, (i < 0 ? 0 : i) - 30);
  return text.slice(start, start + 110).replace(/\s+/g, " ").trim();
}

/** Import chosen phone files into the encrypted library. */
export async function importFiles(uris) {
  const out = [];
  for (const uri of uris) {
    const e = (await load()).get(uri);
    if (!e) continue;
    const bytes = await native.readUri(uri);
    const pre = e.text ? { text: e.text, ocr: false, language: ex.detectLanguage(e.text) } : null;
    const d = await repo.ingest(bytes, e.name, e.source === "whatsapp" ? "whatsapp" : e.source, { pre, origin: uri });
    if (d) out.push(d.id);
  }
  idx = null;
  return out;
}

export async function stats() {
  const list = await entries();
  return { files: list.length, indexed: list.filter((e) => e.indexed).length,
    documents: list.filter((e) => e.doc_type && e.doc_type !== "unknown").length };
}
// Recognised documents that are not in the library yet; one file per distinct content (no duplicate imports).
export async function recognisedUris() {
  const docs = [...(await repo.docs()).values()];
  const origins = new Set(docs.map((d) => d.origin).filter(Boolean));
  const shas = new Set(docs.map((d) => d.sha256).filter(Boolean));
  const out = [];
  for (const e of await entries()) {
    if (!e.doc_type || e.doc_type === "unknown" || origins.has(e.uri) || (e.sha && shas.has(e.sha))) continue;
    if (e.sha) shas.add(e.sha);
    out.push(e.uri);
  }
  return out;
}
