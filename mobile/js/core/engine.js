// Dialogue engine, a port of backend/docmind/assistant/engine.py (+ discovery). Runs on the phone.
import C from "../catalog.js";
import * as cl from "./classifier.js";
import * as cr from "./crypto.js";
import { parse } from "./intent.js";
import * as repo from "./repo.js";

const { DOC_TYPES, PROCESSES, ACQUISITION, TEXTS } = C;
const now = () => new Date().toISOString().replace(/\.\d+Z$/, "+00:00");
const t = (key, lang, vars = {}) => Object.entries(vars).reduce((s, [k, v]) => s.replaceAll(`{${k}}`, v), TEXTS[key][lang]);
const label = (dt, lang) => DOC_TYPES[dt]?.[lang] || (lang === "he" ? "מסמך לא מזוהה" : "Unclassified document");
const joinList = (items, lang) => items.length <= 1 ? (items[0] || "") : items.slice(0, -1).join(", ") + (lang === "he" ? " ו" : " and ") + items.at(-1);
const slug = (s) => s.toLowerCase().replace(/[^\p{L}\p{N}]+/gu, "-").replace(/^-|-$/g, "").slice(0, 60) || "task";

export const SOURCES = [
  { key: "device_files", order: 1, label: { en: "Documents on this phone", he: "מסמכים בטלפון הזה" }, kinds: ["upload", "gallery", "downloads", "folder"], status: "found_local" },
  { key: "whatsapp", order: 4, label: { en: "WhatsApp (imported chats)", he: "וואטסאפ (צ'אטים שיובאו)" }, kinds: ["whatsapp_import", "whatsapp"], status: "found_whatsapp" },
];
export const UNAVAILABLE = [
  { key: "gmail", order: 5, label: { en: "Gmail", he: "Gmail" }, state: "server_version_only" },
  { key: "gdrive", order: 6, label: { en: "Google Drive", he: "Google Drive" }, state: "server_version_only" },
];

function acquisition(dt, lang) {
  const a = ACQUISITION[dt];
  if (!a) return null;
  return { ...a[lang], ...(a.url ? { url: a.url } : {}) };
}

async function hiddenCats() {
  const { vaultOpen } = await import("./vault.js");
  return vaultOpen() ? new Set() : new Set(await repo.lockedCategories());
}

async function findRequirement(dt, lbl, lang) {
  const all = [...(await repo.docs()).values()].filter((d) => !d.archived && !d.duplicate_of && (d.status === "ready" || d.locked));
  const hits = [];
  for (const src of SOURCES) {
    if (dt && dt !== "unknown") {
      all.filter((d) => src.kinds.includes(d.source_kind) && d.doc_type === dt)
        .sort((a, b) => (b.doc_date || b.created_at || "").localeCompare(a.doc_date || a.created_at || "") || (b.doc_type_confidence || 0) - (a.doc_type_confidence || 0))
        .forEach((d) => hits.push({ source: src.key, status: src.status, score: d.doc_type_confidence || 0, match: "exact_type", document: repo.publicDoc(d), external: null }));
    }
  }
  if (!hits.length) {
    const q = dt in DOC_TYPES ? [DOC_TYPES[dt].en, DOC_TYPES[dt].he, ...(C.REQUEST_ALIASES[dt] || [])].join(" ") : lbl;
    for (const [d, s] of await repo.search(q, { limit: 5, min: 0.22, exclude: await hiddenCats() })) {
      const src = SOURCES.find((x) => x.kinds.includes(d.source_kind));
      if (!src || d.duplicate_of || (dt && !["unknown", dt].includes(d.doc_type))) continue;
      hits.push({ source: src.key, status: src.status, score: s, match: "content_match", document: repo.publicDoc(d), external: null });
    }
  }
  const memo = dt ? await repo.getRecord("mf:loc:" + dt) : null;
  const req = { doc_type: dt, label: lbl || label(dt, lang) };
  if (!hits.length) {
    return { requirement: req, status: "not_found", best: null, alternatives: [], acquisition: dt ? acquisition(dt, lang) : null,
      previously_found_in: memo ? { source: memo.source, at: memo.at } : null };
  }
  const order = ["found_local", "found_whatsapp"];
  hits.sort((a, b) => (a.match === "content_match") - (b.match === "content_match") || order.indexOf(a.status) - order.indexOf(b.status) || b.score - a.score);
  const best = hits[0];
  return { requirement: req, status: best.status, best, alternatives: hits.slice(1, 4), freshness: best.document.locked ? { state: "unknown" } : cl.freshness(best.document),
    uncertain: best.match === "content_match", acquisition: null, previously_found_in: memo ? { source: memo.source, at: memo.at } : null };
}

async function searchAll(items, lang) {
  const plan = { searched: SOURCES.map(({ key, label: l, order }) => ({ key, label: l, order, state: "connected" })),
    unavailable: UNAVAILABLE, failed: [] };
  const results = [];
  for (const i of items) results.push(await findRequirement(i.doc_type, i.label, lang));
  return { plan, results };
}

// ---- memory -------------------------------------------------------------------------------------
async function propose(kind, payload) {
  for (const p of await repo.records("pr:")) {
    if (p.status === "pending" && p.purpose_key === payload.purpose_key) await repo.putRecord("pr:" + p.id, { ...p, status: "superseded" });
  }
  const p = { id: cr.uuid(), kind, status: "pending", created_at: now(), ...payload };
  await repo.putRecord("pr:" + p.id, p);
  return p;
}

export async function resolveProposal(id, accept) {
  const p = await repo.getRecord("pr:" + id);
  if (!p) throw Object.assign(new Error("not_found"), { status: 404, code: "not_found" });
  if (p.status !== "pending") throw Object.assign(new Error("already_resolved"), { status: 409, code: "already_resolved" });
  const res = { status: accept ? "accepted" : "rejected", kind: p.kind };
  if (accept) {
    if (p.kind === "create_checklist") {
      const c = { id: cr.uuid(), name: p.name, purpose_key: p.purpose_key, items: p.items, version: 1, use_count: 1,
        created_at: now(), updated_at: now(), last_used_at: now() };
      await repo.putRecord("cl:" + c.id, c);
      res.checklist_id = c.id;
    } else {
      const c = await repo.getRecord("cl:" + p.checklist_id);
      if (!c) throw Object.assign(new Error("checklist_gone"), { status: 409, code: "checklist_gone" });
      await repo.putRecord("cl:" + c.id, { ...c, items: p.items, version: c.version + 1, updated_at: now() });
      res.checklist_id = c.id;
    }
  }
  await repo.putRecord("pr:" + id, { ...p, status: res.status, resolved_at: now() });
  return res;
}

const grams = (s) => { s = s.toLowerCase().replace(/\s+/g, " "); const g = new Set(); for (let i = 0; i + 3 <= s.length; i++) g.add(s.slice(i, i + 3)); return g; };
async function matchChecklist(pk, text) {
  const rows = await repo.records("cl:");
  if (pk) { const r = rows.find((x) => x.purpose_key === pk); if (r) return r; }
  let best = null, bestS = 0;
  const g = grams(text);
  for (const r of rows) {
    const rg = grams(r.name);
    if (!rg.size) continue;
    const s = [...rg].filter((x) => g.has(x)).length / rg.size;
    if (s > bestS) { best = r; bestS = s; }
  }
  return bestS >= 0.7 ? best : null;
}

// ---- engine ----------------------------------------------------------------------------------------
export async function respond(convId, text) {
  text = (text || "").trim().slice(0, 2000);
  const st = await repo.settings();
  let conv = convId ? await repo.getRecord("cv:" + convId) : null;
  if (!conv) conv = { id: cr.uuid(), title: null, state: {}, messages: [], created_at: now(), updated_at: now() };
  const it = parse(text, st.locale || "he");
  const lang = it.lang;
  conv.messages.push({ id: cr.uuid(), role: "user", text, payload: null, created_at: now() });
  const reply = await route(conv, it, lang, st);
  reply.lang = lang;
  reply.conversation_id = conv.id;
  reply.message_id = cr.uuid();
  const { text: rtext, conversation_id, ...payload } = reply;
  conv.messages.push({ id: reply.message_id, role: "assistant", text: rtext, payload, created_at: now() });
  conv.title = conv.title || text.slice(0, 80);
  conv.updated_at = now();
  await repo.putRecord("cv:" + conv.id, conv);
  return reply;
}

const nothingMoreQR = (lang) => [{ label: t("nothing_more", lang), send: lang === "he" ? "זה הכל" : "that's all" }];

async function route(conv, it, lang, st) {
  const s = conv.state;
  if (s.pending_proposal && (it.yes || it.no) && !it.doc_types.length && !it.is_task) return resolveInChat(conv, it.yes, lang);
  if (s.awaiting_checklist && !it.is_task) {
    const task = s.awaiting_checklist;
    if (it.doc_types.length) return runTask(conv, task, it.doc_types.map((d) => ({ doc_type: d, label: label(d, lang) })), lang, null);
    if (it.yes && task.suggested?.length) return runTask(conv, task, task.suggested.map((d) => ({ doc_type: d, label: label(d, lang) })), lang, null);
    return askChecklist(conv, task, lang, true);
  }
  const task = s.active_task;
  if (task && it.doc_types.length && !it.is_task && !it.find_only) return addToTask(conv, task, it.doc_types, lang);
  if (task && (it.nothing_more || it.no) && !it.is_task) {
    const { results } = await searchAll(task.items, lang);
    return { text: t("complete", lang), blocks: [], actions: [bundleAction(task.label, results, lang)], quick_replies: [] };
  }
  if (it.is_task) return startTask(conv, it, lang);
  if (it.doc_types.length) return find(it.doc_types, lang);
  if (it.greeting) return { text: t("greeting", lang, { name: st.display_name || "" }), blocks: [], quick_replies: starters(lang) };
  if (it.help) return { text: t("help", lang), blocks: [], quick_replies: starters(lang) };
  return freeSearch(it.free_text, lang);
}

async function startTask(conv, it, lang) {
  const pk = it.process_key || "custom:" + slug(it.custom_purpose);
  const task = { purpose_key: pk, label: it.process_key ? PROCESSES[pk][lang] : it.custom_purpose };
  conv.state = {};
  const checklist = await matchChecklist(it.process_key ? pk : null, it.free_text);
  if (checklist) {
    await repo.putRecord("cl:" + checklist.id, { ...checklist, use_count: checklist.use_count + 1, last_used_at: now() });
    const extra = it.doc_types.filter((d) => !checklist.items.some((i) => i.doc_type === d));
    const reply = await runTask(conv, { purpose_key: checklist.purpose_key, label: checklist.name }, checklist.items, lang, checklist);
    if (extra.length) {
      const follow = await addToTask(conv, conv.state.active_task, extra, lang);
      reply.blocks.push(...follow.blocks);
      reply.text += "\n\n" + follow.text;
    }
    return reply;
  }
  if (it.doc_types.length) return runTask(conv, task, it.doc_types.map((d) => ({ doc_type: d, label: label(d, lang) })), lang, null);
  return askChecklist(conv, task, lang);
}

function suggestedFor(pk, exclude = []) {
  return (PROCESSES[pk]?.suggested || []).filter((d) => !exclude.includes(d));
}

async function suggestionBlock(types, lang, mode = "add") {
  const have = new Set([...(await repo.docs()).values()].filter((d) => !d.archived).map((d) => d.doc_type));
  return { type: "suggestions", mode, note: t("suggestions_note", lang), items: types.map((d) => ({ doc_type: d, label: label(d, lang), in_library: have.has(d) })) };
}

async function askChecklist(conv, task, lang, again = false) {
  const suggested = suggestedFor(task.purpose_key);
  task.suggested = suggested;
  conv.state = { awaiting_checklist: task };
  const blocks = suggested.length ? [await suggestionBlock(suggested, lang, "checklist")] : [];
  const quick = suggested.length ? [{ label: t("use_suggestions", lang), send: lang === "he" ? "כן" : "yes" }] : [];
  return { text: t(again ? "ask_checklist_again" : "ask_checklist", lang, { task: task.label }), blocks, quick_replies: quick };
}

function summary(plan, results, lang) {
  const found = results.filter((r) => r.status.startsWith("found")).length;
  const lines = [t("searched_summary", lang, { found, total: results.length, sources: joinList(plan.searched.map((s) => s.label[lang]), lang) })];
  const outdated = results.filter((r) => ["expired", "maybe_outdated"].includes(r.freshness?.state)).length;
  if (outdated) lines.push(t("outdated_note", lang, { n: outdated }));
  return lines;
}
async function hintBlock(results) {
  if (!results.some((r) => r.status === "not_found")) return null;
  const native = await import("../native.js");
  if (native.isNative) {
    const scanner = await import("./scanner.js");
    if (await scanner.lastScan()) return null;
    return { type: "hint", key: "hint_scan", action: { label_key: "hint_scan_btn", href: "#/accounts" } };
  }
  return { type: "hint", key: "hint_web", action: { label_key: "hint_upload", href: "#/library" } };
}
const resultsBlock = (plan, results, title = null) => ({ type: "requirements", title, results, sources_searched: plan.searched,
  sources_unavailable: plan.unavailable, sources_failed: [] });
function bundleAction(taskLabel, results, lang) {
  const d = new Date();
  return { type: "create_bundle", label: t("create_bundle", lang), payload: {
    name: `${taskLabel} – ${String(d.getDate()).padStart(2, "0")}.${String(d.getMonth() + 1).padStart(2, "0")}.${d.getFullYear()}`,
    items: results.map((r) => ({ label: r.requirement.label, doc_type: r.requirement.doc_type, document_id: r.best?.document?.id || null })) } };
}

async function runTask(conv, task, items, lang, checklist) {
  const { plan, results } = await searchAll(items, lang);
  task = { ...task, items, checklist_id: checklist?.id || null };
  conv.state = { active_task: task };
  const lines = checklist ? [t("remembered", lang, { name: checklist.name, n: items.length })] : [];
  lines.push(...summary(plan, results, lang));
  const blocks = [resultsBlock(plan, results, task.label)];
  const hint = await hintBlock(results);
  if (hint) blocks.push(hint);
  const suggested = suggestedFor(task.purpose_key, items.map((i) => i.doc_type));
  if (suggested.length) blocks.push(await suggestionBlock(suggested, lang));
  if (!checklist) {
    const p = await propose("create_checklist", { name: task.label, purpose_key: task.purpose_key, items });
    conv.state.pending_proposal = p.id;
    blocks.push({ type: "proposal", proposal: p, question: t("propose_save", lang, { task: task.label }),
      accept_label: t("remember_yes", lang), reject_label: t("remember_no", lang) });
    lines.push(t("additional", lang));
  } else lines.push(t("anything_changed", lang));
  const quick = nothingMoreQR(lang).concat(suggested.slice(0, 3).map((d) => ({ label: "+ " + label(d, lang), send: (lang === "he" ? "צריך גם " : "also ") + label(d, lang) })));
  return { text: lines.join("\n"), blocks, actions: [bundleAction(task.label, results, lang)], quick_replies: quick };
}

async function addToTask(conv, task, types, lang) {
  const existing = new Set(task.items.map((i) => i.doc_type));
  const fresh = types.filter((d) => !existing.has(d)).map((d) => ({ doc_type: d, label: label(d, lang) }));
  if (!fresh.length) return { text: t("additional", lang), blocks: [], quick_replies: [] };
  const { plan, results } = await searchAll(fresh, lang);
  task.items = task.items.concat(fresh);
  conv.state.active_task = task;
  const lines = [t("added_items", lang, { items: joinList(fresh.map((n) => n.label), lang) }), ...summary(plan, results, lang)];
  const blocks = [resultsBlock(plan, results)];
  const row = task.checklist_id ? await repo.getRecord("cl:" + task.checklist_id) : null;
  if (row) {
    const p = await propose("update_checklist", { checklist_id: row.id, name: row.name, purpose_key: row.purpose_key, items: task.items, added: fresh });
    conv.state.pending_proposal = p.id;
    blocks.push({ type: "proposal", proposal: p, question: t("propose_update", lang, { name: row.name, added: joinList(fresh.map((n) => n.label), lang) }),
      accept_label: t("update_yes", lang), reject_label: t("update_no", lang) });
  } else {
    const p = await propose("create_checklist", { name: task.label, purpose_key: task.purpose_key, items: task.items });
    conv.state.pending_proposal = p.id;
    blocks.push({ type: "proposal", proposal: p, question: t("propose_save", lang, { task: task.label }),
      accept_label: t("remember_yes", lang), reject_label: t("remember_no", lang) });
  }
  lines.push(t("additional", lang));
  const all = await searchAll(task.items, lang);
  return { text: lines.join("\n"), blocks, actions: [bundleAction(task.label, all.results, lang)], quick_replies: nothingMoreQR(lang) };
}

async function resolveInChat(conv, accept, lang) {
  const pid = conv.state.pending_proposal;
  delete conv.state.pending_proposal;
  let res;
  try { res = await resolveProposal(pid, accept); } catch { return { text: t("additional", lang), blocks: [] }; }
  const task = conv.state.active_task || {};
  if (accept && res.checklist_id) { task.checklist_id = res.checklist_id; conv.state.active_task = task; }
  const key = accept ? (res.kind === "create_checklist" ? "saved" : "updated") : "not_saved";
  return { text: t(key, lang, { task: task.label || "" }) + "\n" + t("additional", lang), blocks: [], quick_replies: nothingMoreQR(lang) };
}

async function find(types, lang) {
  const items = types.map((d) => ({ doc_type: d, label: label(d, lang) }));
  const { plan, results } = await searchAll(items, lang);
  const lines = [t("find_summary", lang, { sources: joinList(plan.searched.map((s) => s.label[lang]), lang) }), ...summary(plan, results, lang).slice(1), t("anything_else", lang)];
  const actions = items.length > 1 ? [bundleAction(joinList(items.map((i) => i.label), lang).slice(0, 60), results, lang)] : [];
  const hint = await hintBlock(results);
  return { text: lines.join("\n"), blocks: [resultsBlock(plan, results), ...(hint ? [hint] : [])], actions, quick_replies: [] };
}

async function freeSearch(text, lang) {
  const all = [...(await repo.docs()).values()].filter((d) => !d.archived);
  if (!all.length) return { text: t("empty_library", lang), blocks: [], actions: [{ type: "open_upload", label: "+" }] };
  const hits = await repo.search(text, { limit: 6, min: 0.12, exclude: await hiddenCats() });
  if (!hits.length) return { text: t("free_none", lang), blocks: [], quick_replies: starters(lang) };
  return { text: t("free_results", lang), blocks: [{ type: "documents", documents: hits.map(([d, s]) => ({ ...repo.publicDoc(d), score: Math.round(s * 1000) / 1000 })) }] };
}

function starters(lang) {
  return lang === "he"
    ? [{ label: "מסמכים למלגת מילואים", send: "אני צריך מסמכים למלגת מילואים" }, { label: "אישור ניהול חשבון", send: "תמצא לי את אישור ניהול החשבון" },
      { label: "תעודת זהות וספח", send: "תמצא את תעודת הזהות והספח" }]
    : [{ label: "Reserve scholarship documents", send: "I need documents for a military reserve scholarship" },
      { label: "Bank confirmation", send: "Find my latest bank confirmation" }, { label: "ID card + appendix", send: "Find my identity card and appendix" }];
}
