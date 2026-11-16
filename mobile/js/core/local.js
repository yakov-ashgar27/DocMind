// Local API: same paths and JSON shapes as the server version, answered on the phone.
import C from "../catalog.js";
import * as cl from "./classifier.js";
import * as cr from "./crypto.js";
import * as db from "./db.js";
import * as engine from "./engine.js";
import * as ex from "./extract.js";
import * as repo from "./repo.js";
import * as V from "./vault.js";
import { readZip } from "./zip.js";

const { LocalError } = V;
const now = () => new Date().toISOString().replace(/\.\d+Z$/, "+00:00");
const routes = [];
const on = (method, pattern, fn) => routes.push({ method, rx: new RegExp("^" + pattern.replace(/:(\w+)/g, "(?<$1>[^/]+)") + "$"), fn });

V.session.listeners.add(() => { repo.cache.docs = null; repo.cache.index = null; });

export async function handle(method, path, { body = {}, form = null, query = {} } = {}) {
  for (const r of routes) {
    if (r.method !== method) continue;
    const m = path.match(r.rx);
    if (m) return r.fn({ params: m.groups || {}, body: body || {}, form, query: query || {} });
  }
  throw new LocalError("not_found", 404);
}

const hidden = async () => (V.vaultOpen() ? new Set() : new Set(await repo.lockedCategories()));
async function visible(id) {
  const d = await repo.getDoc(id);
  if (!d) throw new LocalError("not_found", 404);
  if (d.locked) throw new LocalError("vault_locked", 423);
  return d;
}
const blobUrl = (bytes, mime) => URL.createObjectURL(new Blob([bytes], { type: mime }));

// ---- meta / me ------------------------------------------------------------------------------
on("GET", "/meta", async () => ({
  doc_types: Object.fromEntries(Object.entries(C.DOC_TYPES).map(([k, v]) => [k, { en: v.en, he: v.he, category: v.cat }])),
  processes: Object.fromEntries(Object.entries(C.PROCESSES).map(([k, v]) => [k, { en: v.en, he: v.he }])),
  llm: { provider: "none", available: false }, shared_learning_available: false, google_configured: false, edition: "phone",
}));
async function me() {
  const s = await repo.settings();
  return { id: "local", email: null, display_name: s.display_name || "", locale: s.locale || "he", settings: s,
    created_at: s.created_at || null, mfa_enabled: false, vault_pin_set: await V.hasVault() };
}
on("GET", "/me", async () => ({ user: await me() }));
on("PATCH", "/me", async ({ body }) => {
  const patch = {};
  if (["he", "en"].includes(body.locale)) patch.locale = body.locale;
  if (body.display_name) patch.display_name = String(body.display_name).slice(0, 80);
  if ("remember_locations" in body) patch.remember_locations = !!body.remember_locations;
  if ("reminder_days" in body) {
    if (![14, 30, 60, 90].includes(Number(body.reminder_days))) throw new LocalError("invalid_reminder_days");
    patch.reminder_days = Number(body.reminder_days);
  }
  await repo.saveSettings(patch);
  return { user: await me() };
});

// ---- documents --------------------------------------------------------------------------------
on("GET", "/documents", async ({ query }) => {
  let list = [...(await repo.docs()).values()];
  if (query.include_archived !== "1") list = list.filter((d) => !d.archived);
  for (const [f, col] of [["category", "category_key"], ["doc_type", "doc_type"], ["source", "source_kind"]]) if (query[f]) list = list.filter((d) => d[col] === query[f]);
  if (query.duplicates === "1") list = list.filter((d) => d.duplicate_of);
  if (query.from) list = list.filter((d) => !d.locked && (d.doc_date || d.created_at.slice(0, 10)) >= query.from);
  if (query.q?.trim()) {
    const allowed = new Set(list.map((d) => d.id));
    const hits = await repo.search(query.q, { limit: 50, min: 0.1, exclude: await hidden() });
    return { documents: hits.filter(([d]) => allowed.has(d.id)).map(([d, s]) => ({ ...repo.publicDoc(d), score: Math.round(s * 1000) / 1000 })) };
  }
  list.sort((a, b) => (b.created_at || "").localeCompare(a.created_at || ""));
  return { documents: list.map(repo.publicDoc) };
});

on("POST", "/documents", async ({ form }) => {
  const created = [], errors = [];
  for (const f of form.getAll("files").slice(0, 50)) {
    try {
      if (f.size > repo.MAX_BYTES) throw new LocalError("file_too_large", 413);
      created.push(repo.publicDoc(await repo.ingest(new Uint8Array(await f.arrayBuffer()), f.name, form.get("source") === "whatsapp_import" ? "whatsapp_import" : "upload")));
    } catch (e) { errors.push({ filename: f.name, error: e.code || e.message }); }
  }
  if (!created.length) throw Object.assign(new LocalError(errors[0]?.error || "no_files"), { data: { errors } });
  return { documents: created, errors };
});

on("POST", "/import/whatsapp", async ({ form }) => {
  const file = form.get("file");
  const entries = await readZip(new Uint8Array(await file.arrayBuffer()));
  let chat = null;
  const txt = entries.find((e) => e.name.toLowerCase().endsWith(".txt"));
  if (txt) chat = txt.name.split("/").pop().replace(/\.txt$/i, "").replace("WhatsApp Chat with ", "").replace("WhatsApp Chat - ", "");
  const imported = [], skipped = [];
  for (const e of entries.filter((x) => /\.(pdf|jpe?g|png|webp|heic)$/i.test(x.name))) {
    try { imported.push((await repo.ingest(await e.read(), e.name.split("/").pop(), "whatsapp_import")).id); }
    catch (err) { skipped.push({ name: e.name, reason: err.code || err.message }); }
  }
  return { imported, skipped, chat };
});

on("GET", "/documents/:id", async ({ params }) => {
  const d = await visible(params.id);
  let dup = d.duplicate_of ? await repo.getDoc(d.duplicate_of) : null;
  if (dup?.locked) dup = null;
  const bundles = (await repo.records("bd:")).filter((b) => b.items.some((i) => i.document_id === d.id)).map((b) => ({ id: b.id, name: b.name }));
  return { document: repo.publicDoc(d), text_excerpt: (d.text || "").slice(0, 4000), text_length: (d.text || "").length,
    duplicate_of: dup ? repo.publicDoc(dup) : null, bundles };
});

on("PATCH", "/documents/:id", async ({ params, body }) => {
  const d = await visible(params.id);
  const p = {};
  if (body.display_name?.trim()) p.display_name = body.display_name.trim().slice(0, 180);
  if ("doc_type" in body) {
    if (body.doc_type !== "unknown" && !C.DOC_TYPES[body.doc_type]) throw new LocalError("invalid_doc_type");
    Object.assign(p, { doc_type: body.doc_type, doc_type_source: "user", doc_type_confidence: 1 });
    if (!("category_key" in body)) p.category_key = C.DOC_TYPES[body.doc_type]?.cat || "other";
  }
  if ("category_key" in body) {
    const cats = await categoriesList();
    if (!cats.some((c) => c.key === body.category_key)) throw new LocalError("invalid_category");
    p.category_key = body.category_key;
  }
  if ("tags" in body) p.tags = (body.tags || []).map((x) => String(x).trim().slice(0, 40)).filter(Boolean).slice(0, 20);
  for (const f of ["doc_date", "expiry_date"]) if (f in body) {
    if (body[f] && !/^\d{4}-\d{2}-\d{2}$/.test(body[f])) throw new LocalError("invalid_" + f);
    p[f] = body[f] || null;
  }
  if ("issuer" in body) p.issuer = body.issuer ? String(body.issuer).slice(0, 120) : null;
  if ("archived" in body) p.archived = !!body.archived;
  return { document: repo.publicDoc(await repo.updateDoc(d.id, p)) };
});

on("DELETE", "/documents/:id", async ({ params, body }) => {
  if (body.confirm !== true) throw new LocalError("confirmation_required");
  await visible(params.id);
  await repo.deleteDoc(params.id);
  return { ok: true };
});
on("POST", "/documents/:id/reprocess", async ({ params }) => {
  await visible(params.id);
  const d = await repo.updateDoc(params.id, { status: "processing" });
  repo.queue(params.id);
  return { document: repo.publicDoc(d) };
});
on("POST", "/documents/:id/duplicate", async ({ params, body }) => {
  await visible(params.id);
  if (["keep_both", "not_duplicate"].includes(body.action)) await repo.updateDoc(params.id, { duplicate_of: null, duplicate_kind: null });
  else if (body.action === "archive_this") await repo.updateDoc(params.id, { archived: true });
  else throw new LocalError("invalid_action");
  return { document: repo.publicDoc(await repo.getDoc(params.id)) };
});
on("GET", "/documents/:id/thumbnail", async ({ params }) => {
  const t = await repo.readThumb(params.id);
  if (!t) throw new LocalError("no_thumbnail", 404);
  return new Response(new Blob([t], { type: "image/jpeg" }));
});
on("POST", "/documents/:id/link", async ({ params }) => {
  const d = await visible(params.id);
  return { url: blobUrl(await repo.readBytes(d.id), d.mime_type), filename: d.original_filename, mime: d.mime_type };
});

// ---- assistant ------------------------------------------------------------------------------
on("POST", "/assistant/message", async ({ body }) => {
  if (!(body.text || "").trim()) throw new LocalError("empty_message");
  return engine.respond(body.conversation_id, body.text);
});
on("GET", "/conversations", async () => ({
  conversations: (await repo.records("cv:")).sort((a, b) => b.updated_at.localeCompare(a.updated_at)).slice(0, 50)
    .map(({ id, title, created_at, updated_at }) => ({ id, title, created_at, updated_at })),
}));
on("GET", "/conversations/:id", async ({ params }) => {
  const c = await repo.getRecord("cv:" + params.id);
  if (!c) throw new LocalError("not_found", 404);
  return { conversation: { id: c.id, title: c.title, created_at: c.created_at }, messages: c.messages };
});
on("DELETE", "/conversations/:id", async ({ params }) => { await repo.delRecord("cv:" + params.id); return { ok: true }; });

// ---- memory -----------------------------------------------------------------------------------
const cleanItems = (items, lang) => {
  const out = [], seen = new Set();
  for (const it of items || []) {
    const dt = C.DOC_TYPES[it.doc_type] ? it.doc_type : null;
    const label = (it.label || (dt ? C.DOC_TYPES[dt][lang] : "")).trim().slice(0, 120);
    const key = dt || label.toLowerCase();
    if (!label || seen.has(key)) continue;
    seen.add(key);
    out.push({ doc_type: dt, label, note: it.note || null });
  }
  return out;
};
on("GET", "/memory", async () => ({
  checklists: (await repo.records("cl:")).sort((a, b) => (b.last_used_at || b.updated_at).localeCompare(a.last_used_at || a.updated_at)),
  facts: (await repo.records("mf:")).map((f) => ({ ...f, value: { source: f.source } })),
  proposals: (await repo.records("pr:")).filter((p) => p.status === "pending"),
}));
on("PATCH", "/memory/checklists/:id", async ({ params, body }) => {
  const c = await repo.getRecord("cl:" + params.id);
  if (!c) throw new LocalError("not_found", 404);
  const next = { ...c, updated_at: now() };
  if (body.name?.trim()) next.name = body.name.trim().slice(0, 120);
  if (body.items) {
    next.items = cleanItems(body.items, (await repo.settings()).locale || "he");
    if (!next.items.length) throw new LocalError("checklist_needs_items");
    next.version = c.version + 1;
  }
  return { checklist: await repo.putRecord("cl:" + c.id, next) };
});
on("DELETE", "/memory/checklists/:id", async ({ params }) => { await repo.delRecord("cl:" + params.id); return { ok: true }; });
on("POST", "/memory/proposals/:id", async ({ params, body }) => {
  try { return await engine.resolveProposal(params.id, !!body.accept); }
  catch (e) { throw new LocalError(e.code || "error", e.status || 400); }
});
on("DELETE", "/memory/facts/:id", async ({ params }) => {
  for (const f of await repo.records("mf:")) if (f.id === params.id) await repo.delRecord("mf:loc:" + f.key);
  return { ok: true };
});
on("DELETE", "/memory", async ({ body }) => {
  if (body.confirm !== true) throw new LocalError("confirmation_required");
  for (const p of ["cl:", "pr:", "mf:"]) for (const r of await repo.records(p)) await repo.delRecord(p + (p === "mf:" ? "loc:" + r.key : r.id));
  return { ok: true };
});

// ---- bundles ------------------------------------------------------------------------------------
const ext = (d) => {
  const m = d.original_filename.match(/\.([A-Za-z0-9]{1,5})$/);
  return m ? "." + m[1].toLowerCase() : (ex.SUPPORTED[d.mime_type] || "");
};
const sanitize = (n) => n.replace(/[\x00-\x1f<>:"/\\|?*]/g, "_").replace(/\s+/g, " ").trim().replace(/^\.+|\.+$/g, "").slice(0, 150) || "document";
function itemFilename(it, pos, d) {
  let base = it.custom_filename || `${String(pos + 1).padStart(2, "0")}_${it.label}`;
  if (it.custom_filename && base.toLowerCase().endsWith(ext(d))) base = base.slice(0, -ext(d).length);
  return sanitize(base) + ext(d);
}
async function bundleView(b) {
  const items = [];
  for (const [pos, it] of b.items.entries()) {
    const d = it.document_id ? await repo.getDoc(it.document_id) : null;
    items.push({ id: it.id, position: pos, label: it.label, doc_type: it.doc_type, selected: it.selected !== false,
      custom_filename: it.custom_filename || null, document: d ? repo.publicDoc(d) : null,
      download_filename: d ? itemFilename(it, pos, d) : null });
  }
  return { id: b.id, name: b.name, created_at: b.created_at, updated_at: b.updated_at, items };
}
const getBundle = async (id) => { const b = await repo.getRecord("bd:" + id); if (!b) throw new LocalError("not_found", 404); return b; };
const saveBundle = async (b) => { b.updated_at = now(); await repo.putRecord("bd:" + b.id, b); return { bundle: await bundleView(b) }; };

on("GET", "/bundles", async () => ({
  bundles: (await repo.records("bd:")).sort((a, b) => b.updated_at.localeCompare(a.updated_at))
    .map((b) => ({ id: b.id, name: b.name, items: b.items.length, ready: b.items.filter((i) => i.document_id).length, created_at: b.created_at, updated_at: b.updated_at })),
}));
on("POST", "/bundles", async ({ body }) => {
  if (!(body.name || "").trim()) throw new LocalError("name_required");
  const b = { id: cr.uuid(), name: body.name.trim().slice(0, 120), items: [], created_at: now(), updated_at: now() };
  const s = await repo.settings();
  for (const it of body.items || []) {
    if (it.document_id && !(await repo.getDoc(it.document_id))) throw new LocalError("document_not_found", 404);
    b.items.push({ id: cr.uuid(), label: (it.label || "").slice(0, 120) || "Document", doc_type: it.doc_type || null, document_id: it.document_id || null, selected: true });
    if (it.document_id && s.remember_locations !== false) {
      const d = await repo.getDoc(it.document_id);
      if (d?.doc_type) await repo.putRecord("mf:loc:" + d.doc_type, { id: cr.uuid(), kind: "doc_location", key: d.doc_type, source: d.source_kind, at: now(), updated_at: now() });
    }
  }
  return saveBundle(b);
});
on("GET", "/bundles/:id", async ({ params }) => ({ bundle: await bundleView(await getBundle(params.id)) }));
on("PATCH", "/bundles/:id", async ({ params, body }) => { const b = await getBundle(params.id); if (body.name?.trim()) b.name = body.name.trim().slice(0, 120); return saveBundle(b); });
on("DELETE", "/bundles/:id", async ({ params }) => { await getBundle(params.id); await repo.delRecord("bd:" + params.id); return { ok: true }; });
on("POST", "/bundles/:id/items", async ({ params, body }) => {
  const b = await getBundle(params.id);
  if (body.document_id && !(await repo.getDoc(body.document_id))) throw new LocalError("document_not_found", 404);
  b.items.push({ id: cr.uuid(), label: (body.label || "Document").slice(0, 120), doc_type: body.doc_type || null, document_id: body.document_id || null, selected: true });
  return saveBundle(b);
});
on("PATCH", "/bundles/:id/items/:item", async ({ params, body }) => {
  const b = await getBundle(params.id);
  const it = b.items.find((i) => i.id === params.item);
  if (!it) throw new LocalError("item_not_found", 404);
  if ("custom_filename" in body) it.custom_filename = body.custom_filename?.trim() ? sanitize(body.custom_filename) : null;
  if (body.label?.trim()) it.label = body.label.trim().slice(0, 120);
  if ("selected" in body) it.selected = !!body.selected;
  if ("document_id" in body) {
    if (body.document_id && !(await repo.getDoc(body.document_id))) throw new LocalError("document_not_found", 404);
    it.document_id = body.document_id || null;
  }
  return saveBundle(b);
});
on("DELETE", "/bundles/:id/items/:item", async ({ params }) => {
  const b = await getBundle(params.id);
  b.items = b.items.filter((i) => i.id !== params.item);
  return saveBundle(b);
});
async function bundleFiles(id, onlyIds) {
  const b = await bundleView(await getBundle(id));
  const out = [];
  for (const it of b.items) {
    if ((onlyIds?.length && !onlyIds.includes(it.id)) || (!onlyIds?.length && !it.selected) || !it.document) continue;
    if (it.document.locked) throw new LocalError("vault_locked", 423);
    out.push({ item_id: it.id, filename: it.download_filename, mime: it.document.mime_type, bytes: await repo.readBytes(it.document.id) });
  }
  return { bundle: b, files: out };
}
on("POST", "/bundles/:id/links", async ({ params, body }) => {
  const { files } = await bundleFiles(params.id, body.item_ids);
  return { links: files.map((f) => ({ item_id: f.item_id, filename: f.filename, mime: f.mime, url: blobUrl(f.bytes, f.mime),
    file: new File([f.bytes], f.filename, { type: f.mime }) })) };
});
on("POST", "/bundles/:id/combined-link", async ({ params }) => {
  const { bundle, files } = await bundleFiles(params.id);
  if (!files.length) throw new LocalError("nothing_to_combine", 409);
  const { PDFDocument } = await import("../../vendor/pdf-lib.esm.min.js");
  const out = await PDFDocument.create();
  for (const f of files) {
    if (f.mime === "application/pdf") {
      const src = await PDFDocument.load(f.bytes, { ignoreEncryption: true });
      (await out.copyPages(src, src.getPageIndices())).forEach((p) => out.addPage(p));
    } else if (f.mime.startsWith("image/")) {
      const jpg = await out.embedJpg(await ex.imageAsJpeg(f.bytes, f.mime));
      const page = out.addPage([595, 842]);
      const s = Math.min(555 / jpg.width, 802 / jpg.height);
      page.drawImage(jpg, { x: (595 - jpg.width * s) / 2, y: (842 - jpg.height * s) / 2, width: jpg.width * s, height: jpg.height * s });
    }
  }
  const bytes = await out.save();
  const name = sanitize(bundle.name) + ".pdf";
  return { url: blobUrl(bytes, "application/pdf"), filename: name, file: new File([bytes], name, { type: "application/pdf" }) };
});

// ---- categories ----------------------------------------------------------------------------------
async function categoriesList() {
  const custom = (await repo.settings()).custom_categories || [];
  return [...C.CATEGORIES.map((c) => ({ key: c.key, name: { en: c.en, he: c.he }, icon: c.icon, is_custom: false })),
    ...custom.map((c) => ({ key: c.key, name: { en: c.name, he: c.name }, icon: "tag", is_custom: true }))];
}
on("GET", "/categories", async () => {
  const counts = {};
  for (const d of (await repo.docs()).values()) if (!d.archived) counts[d.category_key] = (counts[d.category_key] || 0) + 1;
  return { categories: (await categoriesList()).map((c) => ({ ...c, id: c.key, count: counts[c.key] || 0 })) };
});
on("POST", "/categories", async ({ body }) => {
  const name = (body.name || "").trim().slice(0, 60);
  if (!name) throw new LocalError("name_required");
  const key = "c_" + name.toLowerCase().replace(/[^\p{L}\p{N}]+/gu, "_").replace(/^_|_$/g, "").slice(0, 40);
  if ((await categoriesList()).some((c) => c.key === key)) throw new LocalError("category_exists", 409);
  const s = await repo.settings();
  await repo.saveSettings({ custom_categories: [...(s.custom_categories || []), { key, name }] });
  return { key };
});
on("DELETE", "/categories/:key", async ({ params }) => {
  const s = await repo.settings();
  if (!(s.custom_categories || []).some((c) => c.key === params.key)) throw new LocalError("not_found", 404);
  for (const d of (await repo.docs()).values()) if (d.category_key === params.key) await repo.updateDoc(d.id, { category_key: "other" });
  await repo.saveSettings({ custom_categories: s.custom_categories.filter((c) => c.key !== params.key) });
  return { ok: true };
});

// ---- sources ----------------------------------------------------------------------------------------
on("GET", "/connectors", async () => {
  const all = [...(await repo.docs()).values()];
  const n = (k) => all.filter((d) => d.source_kind === k).length;
  return { connectors: [
    { key: "device_files", order: 1, label: { en: "Documents on this phone", he: "מסמכים בטלפון הזה" }, stage: 1, state: "always", searchable: true, documents: n("upload") },
    { key: "whatsapp", order: 4, label: { en: "WhatsApp (imported chats)", he: "וואטסאפ (צ'אטים שיובאו)" }, stage: 1, state: n("whatsapp_import") ? "connected" : "not_connected", searchable: true, documents: n("whatsapp_import") },
    ...engine.UNAVAILABLE.map((u) => ({ ...u, stage: 2, searchable: false })),
  ] };
});

// ---- reminders ------------------------------------------------------------------------------------
async function upcoming() {
  const lead = (await repo.settings()).reminder_days || 60;
  const today = new Date(); today.setHours(0, 0, 0, 0);
  const horizon = new Date(today.getTime() + lead * 86400000).toISOString().slice(0, 10);
  return [...(await repo.docs()).values()].filter((d) => !d.locked && !d.archived && !d.duplicate_of && d.expiry_date && d.expiry_date <= horizon)
    .sort((a, b) => a.expiry_date.localeCompare(b.expiry_date))
    .map((d) => { const days = Math.round((Date.parse(d.expiry_date) - today.getTime()) / 86400000);
      return { document: repo.publicDoc(d), expiry_date: d.expiry_date, days_left: days, state: days < 0 ? "expired" : "expiring" }; });
}
on("GET", "/reminders", async () => ({ reminders: await upcoming(), lead_days: (await repo.settings()).reminder_days || 60 }));
on("POST", "/reminders/calendar-link", async ({ body }) => {
  const s = await repo.settings();
  const lang = s.locale || "he", lead = s.reminder_days || 60;
  const ids = body.document_ids || [];
  const docs = [...(await repo.docs()).values()].filter((d) => !d.locked && !d.archived && d.expiry_date && (!ids.length || ids.includes(d.id)));
  const escI = (x) => x.replace(/\\/g, "\\\\").replace(/;/g, "\\;").replace(/,/g, "\\,").replace(/\n/g, "\\n");
  const ymd = (d) => d.toISOString().slice(0, 10).replace(/-/g, "");
  const stamp = new Date().toISOString().replace(/[-:]/g, "").replace(/\.\d+/, "");
  const fold = (line) => { const enc = new TextEncoder(); if (enc.encode(line).length <= 75) return line; const parts = []; let cur = "";
    for (const ch of line) { if (enc.encode(cur + ch).length > (parts.length ? 74 : 75)) { parts.push(cur); cur = ""; } cur += ch; } parts.push(cur); return parts.join("\r\n "); };
  const lines = ["BEGIN:VCALENDAR", "VERSION:2.0", "PRODID:-//DocMind//Document reminders//HE", "CALSCALE:GREGORIAN", "METHOD:PUBLISH", "X-WR-CALNAME:DocMind"];
  for (const d of docs) {
    const exp = new Date(d.expiry_date + "T00:00:00Z");
    const lbl = C.DOC_TYPES[d.doc_type]?.[lang] || d.display_name;
    const pretty = d.expiry_date.split("-").reverse().join(".");
    const summary = lang === "he" ? `לחדש: ${lbl} (פג תוקף ${pretty})` : `Renew: ${lbl} (expires ${d.expiry_date})`;
    const start = new Date(Math.max(exp.getTime() - lead * 86400000, Date.now()));
    lines.push("BEGIN:VEVENT", `UID:docmind-${d.id}@docmind.local`, `DTSTAMP:${stamp}`, `DTSTART;VALUE=DATE:${ymd(start)}`,
      `DTEND;VALUE=DATE:${ymd(new Date(start.getTime() + 86400000))}`, `SUMMARY:${escI(summary)}`, "TRANSP:TRANSPARENT",
      "BEGIN:VALARM", "ACTION:DISPLAY", `DESCRIPTION:${escI(summary)}`, "TRIGGER:PT9H", "END:VALARM", "END:VEVENT");
  }
  lines.push("END:VCALENDAR");
  const text = lines.map(fold).join("\r\n") + "\r\n";
  return { url: blobUrl(new TextEncoder().encode(text), "text/calendar"), filename: "docmind-reminders.ics" };
});

// ---- dashboard ----------------------------------------------------------------------------------
on("GET", "/dashboard", async () => {
  const docs = [...(await repo.docs()).values()].filter((d) => !d.archived);
  const attention = [];
  for (const d of docs) {
    if (d.locked) continue;
    const f = cl.freshness(d);
    if (["expired", "expiring", "maybe_outdated"].includes(f.state)) attention.push({ kind: f.state, document: repo.publicDoc(d) });
    else if (d.duplicate_of) attention.push({ kind: "duplicate", document: repo.publicDoc(d) });
    else if (d.status === "failed") attention.push({ kind: "failed", document: repo.publicDoc(d) });
    else if (d.status === "ready" && d.doc_type === "unknown") attention.push({ kind: "unclassified", document: repo.publicDoc(d) });
  }
  const order = { expired: 0, failed: 1, duplicate: 2, expiring: 3, maybe_outdated: 4, unclassified: 5 };
  attention.sort((a, b) => order[a.kind] - order[b.kind]);
  const bundles = (await handle("GET", "/bundles")).bundles;
  const checklists = (await handle("GET", "/memory")).checklists;
  return {
    totals: { documents: docs.length, processing: repo.processing.size, checklists: checklists.length, bundles: bundles.length },
    attention: attention.slice(0, 8), recent_documents: docs.sort((a, b) => b.created_at.localeCompare(a.created_at)).slice(0, 6).map(repo.publicDoc),
    bundles: bundles.slice(0, 4), checklists: checklists.slice(0, 4), proposals: (await repo.records("pr:")).filter((p) => p.status === "pending"),
    reminders: (await upcoming()).slice(0, 5),
  };
});

// ---- vault --------------------------------------------------------------------------------------
const vaultStatus = async () => ({ has_pin: await V.hasVault(), locked_categories: await repo.lockedCategories(), default_locked: V.DEFAULT_LOCKED,
  unlocked: V.vaultOpen(), ttl: V.VAULT_TTL });
on("GET", "/vault", vaultStatus);
on("POST", "/vault/pin", async ({ body }) => {
  if (await V.hasVault()) {
    if (!V.vaultOpen()) throw new LocalError("vault_locked", 423);
    await V.changeVaultPin(String(body.current_pin || ""), String(body.pin || ""));
  } else {
    await V.createVault(String(body.pin || ""));
    const s = await repo.settings();
    if (!s.locked_categories) await repo.saveSettings({ locked_categories: V.DEFAULT_LOCKED });
    await repo.reprotectAll();
  }
  return vaultStatus();
});
on("DELETE", "/vault/pin", async () => {
  if (!V.vaultOpen()) throw new LocalError("vault_locked", 423);
  await repo.saveSettings({ locked_categories: [] });
  await repo.reprotectAll();          // re-wrap every protected document with the app key first
  await db.del("kv", "vault");
  V.session.vaultPub = null;
  V.lockVault();
  await repo.saveSettings({ locked_categories: V.DEFAULT_LOCKED });
  return vaultStatus();
});
on("PUT", "/vault/categories", async ({ body }) => {
  if (!V.vaultOpen()) throw new LocalError("vault_locked", 423);
  const valid = new Set((await categoriesList()).map((c) => c.key));
  const keys = [...new Set((body.categories || []).filter((k) => valid.has(k)))].sort();
  await repo.saveSettings({ locked_categories: keys });
  await repo.reprotectAll();
  return { ...(await vaultStatus()), locked_categories: keys };
});
on("POST", "/vault/unlock", async ({ body }) => {
  await V.unlockVault(String(body.pin || ""));
  repo.cache.docs = null; repo.cache.index = null;
  return { vault_token: "local", expires_in: V.VAULT_TTL };
});

// ---- export (metadata only) -------------------------------------------------------------------------
on("GET", "/me/export", async () => ({
  exported_at: now(), documents: [...(await repo.docs()).values()].map(repo.publicDoc).map(({ text_chars, ...d }) => d),
  checklists: await repo.records("cl:"), bundles: (await handle("GET", "/bundles")).bundles,
}));
