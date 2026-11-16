// Encrypted document repository + records (checklists, bundles, conversations, ...).
import C from "../catalog.js";
import * as cl from "./classifier.js";
import * as cr from "./crypto.js";
import * as db from "./db.js";
import * as ex from "./extract.js";
import { Index, similarity } from "./search.js";
import { DEFAULT_LOCKED, LocalError, session } from "./vault.js";

const PUB_FIELDS = ["id", "category_key", "doc_type", "status", "source_kind", "is_local", "mime_type", "archived",
  "created_at", "updated_at", "sha256", "protected", "doc_type_source"];
const now = () => new Date().toISOString().replace(/\.\d+Z$/, "+00:00");

// In-memory caches, wiped on lock.
export const cache = { docs: null, index: null, settings: null, records: null };
export function wipeCache() { cache.docs = null; cache.index = null; cache.settings = null; cache.records = null; }
const need = () => { if (!session.dek) throw new LocalError("unauthorized", 401); };

// ---- settings & generic records -------------------------------------------------------------
export async function settings() {
  need();
  if (!cache.settings) {
    const s = await db.get("kv", "settings");
    cache.settings = s ? await cr.openJSON(session.dek, s, "settings") : { locale: "he", display_name: "", locked_categories: DEFAULT_LOCKED };
  }
  return cache.settings;
}
export async function saveSettings(patch) {
  const s = { ...(await settings()), ...patch };
  await db.put("kv", "settings", await cr.sealJSON(session.dek, s, "settings"));
  cache.settings = s;
  return s;
}

export async function records(prefix) {
  need();
  if (!cache.records) {
    cache.records = new Map();
    for (const [k, v] of await db.all("records")) cache.records.set(k, await cr.openJSON(session.dek, v, "rec:" + k));
  }
  return [...cache.records.entries()].filter(([k]) => k.startsWith(prefix)).map(([, v]) => v);
}
export async function getRecord(key) { await records(""); return cache.records.get(key) || null; }
export async function putRecord(key, value) {
  await records("");
  await db.put("records", key, await cr.sealJSON(session.dek, value, "rec:" + key));
  cache.records.set(key, value);
  return value;
}
export async function delRecord(key) { await records(""); await db.del("records", key); cache.records.delete(key); }

// ---- documents ------------------------------------------------------------------------------
export async function lockedCategories() {
  const v = await db.get("kv", "vault");
  return v ? (await settings()).locked_categories || DEFAULT_LOCKED : [];
}

async function docKeyFor(rec) {
  return cr.unwrapDocKey(rec.key, { dek: session.dek, vaultPrivate: session.vaultPriv });
}

async function loadDoc(id, rec) {
  const pub = await cr.openJSON(session.dek, rec.pub, "pub:" + id);
  if (rec.key.kind === "vault" && !session.vaultPriv) return { ...pub, locked: true };
  const k = await docKeyFor(rec);
  const priv = await cr.openJSON(k, rec.priv, "priv:" + id);
  return { ...pub, ...priv, locked: false };
}

export async function docs() {
  need();
  if (!cache.docs) {
    cache.docs = new Map();
    for (const [id, rec] of await db.all("docs")) {
      try { cache.docs.set(id, await loadDoc(id, rec)); } catch (e) { console.warn("doc load failed", id, e); }
    }
  }
  return cache.docs;
}
export async function getDoc(id) { return (await docs()).get(id) || null; }

async function writeDoc(doc, docKey) {
  const pub = Object.fromEntries(PUB_FIELDS.map((f) => [f, doc[f] ?? null]));
  const priv = Object.fromEntries(Object.entries(doc).filter(([k]) => !PUB_FIELDS.includes(k) && k !== "locked"));
  const locked = await lockedCategories();
  const protect = locked.includes(doc.category_key) && !!session.vaultPub;
  pub.protected = protect;
  const key = await cr.wrapDocKey(docKey, { dek: session.dek, vaultPublic: protect ? session.vaultPub : null });
  await db.put("docs", doc.id, {
    pub: await cr.sealJSON(session.dek, pub, "pub:" + doc.id), key,
    priv: await cr.sealJSON(docKey, priv, "priv:" + doc.id),
  });
  // A document that just went into the vault is only readable again once the vault is opened.
  (await docs()).set(doc.id, protect && !session.vaultPriv ? { ...pub, locked: true } : { ...doc, protected: protect, locked: false });
  cache.index = null;
}

export async function updateDoc(id, patch) {
  const doc = await getDoc(id);
  if (!doc) throw new LocalError("not_found", 404);
  if (doc.locked) throw new LocalError("vault_locked", 423);
  const rec = await db.get("docs", id);
  const k = await docKeyFor(rec);
  const next = { ...doc, ...patch, updated_at: now() };
  if (doc.protected && !(await lockedCategories()).includes(next.category_key) && !session.vaultPriv) throw new LocalError("vault_locked", 423);
  await writeDoc(next, k);
  return next;
}

export async function readBytes(id) {
  const doc = await getDoc(id);
  if (!doc) throw new LocalError("not_found", 404);
  if (doc.locked) throw new LocalError("vault_locked", 423);
  const rec = await db.get("docs", id);
  return cr.open(await docKeyFor(rec), await db.get("blobs", id), "file:" + id);
}
export async function readThumb(id) {
  const doc = await getDoc(id);
  if (!doc || doc.locked) return null;
  const t = await db.get("blobs", "t:" + id);
  if (!t) return null;
  return cr.open(await docKeyFor(await db.get("docs", id)), t, "thumb:" + id);
}

export async function deleteDoc(id) {
  const doc = await getDoc(id);
  if (!doc) throw new LocalError("not_found", 404);
  if (doc.locked) throw new LocalError("vault_locked", 423);
  await db.del("docs", id); await db.del("blobs", id); await db.del("blobs", "t:" + id);
  (await docs()).delete(id);
  for (const d of (await docs()).values()) if (d.duplicate_of === id && !d.locked) await updateDoc(d.id, { duplicate_of: null, duplicate_kind: null });
  for (const b of await records("bd:")) {
    let changed = false;
    for (const it of b.items) if (it.document_id === id) { it.document_id = null; changed = true; }
    if (changed) await putRecord("bd:" + b.id, b);
  }
  cache.index = null;
}

// Re-wrap document keys after the set of protected categories changed.
export async function reprotectAll() {
  const locked = await lockedCategories();
  for (const d of (await docs()).values()) {
    const shouldProtect = locked.includes(d.category_key) && !!session.vaultPub;
    if (shouldProtect === !!d.protected) continue;
    if (d.locked) throw new LocalError("vault_locked", 423);
    const k = await docKeyFor(await db.get("docs", d.id));
    await writeDoc(d, k);
  }
}

// ---- ingestion ------------------------------------------------------------------------------
const safeName = (n) => (n || "document").replace(/\\/g, "/").split("/").pop().replace(/[\x00-\x1f<>:"|?*]/g, "_").trim().slice(0, 180) || "document";
export const MAX_BYTES = 25 * 1024 * 1024;

export async function ingest(bytes, filename, source = "upload") {
  need();
  if (!bytes.length) throw new LocalError("empty_file");
  if (bytes.length > MAX_BYTES) throw new LocalError("file_too_large", 413);
  filename = safeName(filename);
  const mime = ex.sniff(bytes, filename);
  if (!mime) throw new LocalError("unsupported_file_type", 415);
  const sha = await cr.sha256hex(bytes);
  const dup = [...(await docs()).values()].find((d) => d.sha256 === sha && !d.duplicate_of);
  const id = cr.uuid();
  const k = await cr.newDocKey();
  await db.put("blobs", id, await cr.seal(k, bytes, "file:" + id));
  const doc = {
    id, source_kind: source, is_local: true, original_filename: filename, display_name: filename.replace(/\.[^.]+$/, ""),
    mime_type: mime, size_bytes: bytes.length, sha256: sha, category_key: "other", doc_type: "unknown",
    doc_type_confidence: 0, doc_type_source: "auto", status: "processing", archived: false, tags: [],
    duplicate_of: dup ? dup.id : null, duplicate_kind: dup ? "exact" : null, text: "", created_at: now(), updated_at: now(),
  };
  await writeDoc(doc, k);
  queue(id);
  return doc;
}

// One document at a time: OCR is heavy on a phone.
const pending = [];
let running = false;
export const processing = new Set();
export function queue(id) { pending.push(id); processing.add(id); pump(); }
async function pump() {
  if (running) return;
  running = true;
  while (pending.length) {
    const id = pending.shift();
    try { await processDoc(id); } catch (e) { console.warn(e); }
    processing.delete(id);
  }
  running = false;
}

async function personalHint(text) {
  const labelled = [...(await docs()).values()].filter((d) => d.doc_type_source === "user" && !d.locked && (d.text || "").length >= 10);
  if (!labelled.length || text.trim().length < 10) return null;
  let best = null, bestS = 0;
  for (const d of labelled) { const s = similarity(text, d.text); if (s > bestS) { best = d; bestS = s; } }
  return best ? [best.doc_type, bestS] : null;
}

export async function processDoc(id) {
  if (!session.dek) return;
  const doc = await getDoc(id);
  if (!doc || doc.locked) return;
  const bytes = await readBytes(id);
  const k = await docKeyFor(await db.get("docs", id));
  try {
    const r = await ex.extractText(bytes, doc.mime_type);
    const c = cl.classify(r.text, doc.original_filename, await personalHint(r.text));
    const lang = (await settings()).locale || "he";
    const next = { ...doc, text: r.text, text_chars: r.text.length, ocr_used: r.ocr, language: r.language,
      doc_type: c.doc_type, doc_type_confidence: c.confidence, category_key: c.category, issuer: c.issuer,
      doc_date: c.doc_date, expiry_date: c.expiry_date, status: "ready", error: null, updated_at: now() };
    if (c.doc_type !== "unknown" && doc.display_name === doc.original_filename.replace(/\.[^.]+$/, "")) next.display_name = cl.smartName(c, doc.original_filename, lang);
    if (!next.duplicate_of && c.doc_type !== "unknown" && r.text.length >= 40) {
      const words = (t) => new Set((t.toLowerCase().match(/[\p{L}\p{N}]{3,}/gu) || []));
      const a = words(r.text);
      for (const o of (await docs()).values()) {
        if (o.id === id || o.locked || o.doc_type !== c.doc_type || o.duplicate_of || o.archived || o.status !== "ready") continue;
        const b = words(o.text || "");
        const inter = [...a].filter((w) => b.has(w)).length;
        if (a.size && b.size && inter / new Set([...a, ...b]).size >= 0.85) { next.duplicate_of = o.id; next.duplicate_kind = "near"; break; }
      }
    }
    await writeDoc(next, k);
  } catch (e) {
    const code = e.message === "ocr_unavailable" ? "ocr_unavailable" : (e.message || "failed").slice(0, 80);
    await writeDoc({ ...doc, status: code === "ocr_unavailable" ? "ready" : "failed", error: code,
      ...(code === "ocr_unavailable" ? (() => { const c = cl.classify("", doc.original_filename); return { doc_type: c.doc_type, category_key: c.category }; })() : {}),
      updated_at: now() }, k);
  }
  const t = await ex.thumbnail(bytes, doc.mime_type);
  if (t) await db.put("blobs", "t:" + id, await cr.seal(k, t, "thumb:" + id));
}

// ---- search ----------------------------------------------------------------------------------
export async function index() {
  if (!cache.index) {
    const entries = [...(await docs()).values()].filter((d) => !d.archived && d.status === "ready" && !d.locked).map((d) => ({ doc: d, text: d.text }));
    cache.index = new Index(entries);
  }
  return cache.index;
}
export async function search(q, opts) { return (await index()).search(q, opts); }

export function publicDoc(d) {
  if (d.locked) {
    return { ...Object.fromEntries(["id", "category_key", "doc_type", "status", "source_kind", "is_local", "mime_type", "archived"].map((k) => [k, d[k]])),
      locked: true, display_name: null, original_filename: null, tags: [], freshness: { state: "unknown" } };
  }
  const { text, sha256, ...rest } = d;
  return { ...rest, tags: d.tags || [], text_chars: (text || "").length, status: processing.has(d.id) && d.status === "processing" ? "processing" : d.status,
    freshness: cl.freshness(d) };
}

export const CATS = C.CATEGORIES;
