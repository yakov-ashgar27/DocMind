// "Scan my phone" (Android app): finds documents among photos and in granted folders, keeps only files that
// are recognised as documents, and imports them encrypted. Nothing is uploaded anywhere.
import * as cl from "./classifier.js";
import * as ex from "./extract.js";
import * as native from "../native.js";
import * as repo from "./repo.js";

const SEEN_KEY = "sc:seen";
export const state = { running: false, stop: false, total: 0, done: 0, found: 0, current: "" };
const listeners = new Set();
export const onProgress = (fn) => { listeners.add(fn); return () => listeners.delete(fn); };
const tick = () => listeners.forEach((f) => f({ ...state }));

export async function lastScan() { return (await repo.getRecord(SEEN_KEY))?.at || null; }

export async function run({ months = 18, maxImages = 600 } = {}) {
  if (state.running) return state;
  Object.assign(state, { running: true, stop: false, total: 0, done: 0, found: 0, current: "" });
  tick();
  try {
    const seenRec = (await repo.getRecord(SEEN_KEY)) || { uris: {}, at: null };
    const since = Date.now() - months * 30 * 86400000;
    const res = await native.scan(since, maxImages);
    const items = (res.items || []).filter((it) => seenRec.uris[it.uri] !== it.modified);
    state.total = items.length;
    tick();
    for (const it of items) {
      if (state.stop) break;
      state.current = it.name;
      tick();
      try {
        const bytes = await native.readUri(it.uri);
        const mime = ex.sniff(bytes, it.name);
        if (mime) {
          const r = await ex.extractText(bytes, mime);
          const c = cl.classify(r.text, it.name);
          if (c.doc_type !== "unknown") {
            const source = it.source === "whatsapp" ? "whatsapp" : it.source;
            const d = await repo.ingest(bytes, it.name, source, { pre: r, skipIfExists: true, origin: it.source });
            if (d) state.found++;
          }
        }
      } catch (e) { console.warn("scan item failed", it.name, e); }
      seenRec.uris[it.uri] = it.modified;
      state.done++;
      tick();
      if (state.done % 10 === 0) await repo.putRecord(SEEN_KEY, seenRec);
    }
    seenRec.at = new Date().toISOString();
    await repo.putRecord(SEEN_KEY, seenRec);
  } finally {
    state.running = false;
    state.current = "";
    tick();
  }
  return state;
}

export async function forgetScanned() { await repo.delRecord(SEEN_KEY); }
