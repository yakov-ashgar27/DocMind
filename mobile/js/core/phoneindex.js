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

const META = "pi:meta";          // { at, files: [{uri,name,mime,size,modified,source}] }
const key = (uri) => "pi:f:" + uri;
export const state = { running: false, stop: false, total: 0, done: 0, docs: 0, current: "" };
const listeners = new Set();
export const onProgress = (fn) => { listeners.add(fn); return () => listeners.delete(fn); };
const tick = () => listeners.forEach((f) => f({ ...state }));
let idx = null;

export async function meta() { return (await repo.getRecord(META)) || { at: null, files: [] }; }
export async function lastBuilt() { return (await meta()).at; }

async function entries() {
  const m = await meta();
  const out = [];
  for (const f of m.files) {
    const e = await repo.getRecord(key(f.uri));
    out.push({ ...f, ...(e || {}), indexed: !!e });
  }
  return out;
}

/** List the phone's files (fast, metadata only) then extract text file by file (documents first, photos last). */
export async function build({ photoMonths = 18 } = {}) {
  if (!native.isNative || state.running) return state;
  Object.assign(state, { running: true, stop: false, total: 0, done: 0, docs: 0, current: "" });
  tick();
  try {
    const res = await native.scan(Date.now() - photoMonths * 30 * 86400000, 5000);
    const files = res.items || [];
    await repo.putRecord(META, { at: (await meta()).at, files });
    const prio = (f) => (f.mime.startsWith("image/") ? (f.source === "gallery" ? 2 : 1) : 0);
    const todo = [];
    for (const f of files) {
      const e = await repo.getRecord(key(f.uri));
      if (!e || e.modified !== f.modified) todo.push(f);
    }
    todo.sort((a, b) => prio(a) - prio(b) || b.modified - a.modified);
    state.total = todo.length;
    state.docs = (await entries()).filter((e) => e.doc_type && e.doc_type !== "unknown").length;
    tick();
    for (const f of todo) {
      if (state.stop) break;
      state.current = f.name;
      tick();
      let rec = { uri: f.uri, modified: f.modified, text: "", doc_type: "unknown", confidence: 0 };
      try {
        const bytes = await native.readUri(f.uri);
        const mime = ex.sniff(bytes, f.name);
        if (mime) {
          const r = await ex.extractText(bytes, mime);
          const c = cl.classify(r.text, f.name);
          rec = { ...rec, text: r.text.slice(0, 5000), doc_type: c.doc_type, confidence: c.confidence, issuer: c.issuer,
            doc_date: c.doc_date, expiry_date: c.expiry_date, category: c.category, sha: await cr.sha256hex(bytes) };
          if (c.doc_type !== "unknown") state.docs++;
        }
      } catch (e) { rec.error = String(e.message || e).slice(0, 60); }
      await repo.putRecord(key(f.uri), rec);
      idx = null;
      state.done++;
      tick();
    }
    const m = await meta();
    await repo.putRecord(META, { ...m, at: new Date().toISOString() });
  } finally {
    state.running = false;
    state.current = "";
    tick();
  }
  return state;
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
    const e = (await entries()).find((x) => x.uri === uri);
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
  const all = await entries();
  return { files: all.length, indexed: all.filter((e) => e.indexed).length,
    documents: all.filter((e) => e.doc_type && e.doc_type !== "unknown").length };
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
