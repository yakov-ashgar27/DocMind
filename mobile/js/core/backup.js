// Encrypted backup: the database is already encrypted, so the backup file is just its ciphertext.
// Restoring needs the passcode that was in use when the backup was made.
import * as cr from "./crypto.js";
import * as db from "./db.js";

const MAGIC = "DOCMIND-BACKUP-1";

function toB64(v) {
  if (v instanceof Uint8Array) return { $u8: cr.b64(v) };
  if (v instanceof ArrayBuffer) return { $u8: cr.b64(new Uint8Array(v)) };
  if (Array.isArray(v)) return v.map(toB64);
  if (v && typeof v === "object") return Object.fromEntries(Object.entries(v).map(([k, x]) => [k, toB64(x)]));
  return v;
}
function fromB64(v) {
  if (v && typeof v === "object" && "$u8" in v) return cr.unb64(v.$u8);
  if (Array.isArray(v)) return v.map(fromB64);
  if (v && typeof v === "object") return Object.fromEntries(Object.entries(v).map(([k, x]) => [k, fromB64(x)]));
  return v;
}

export async function exportBackup() {
  const out = { magic: MAGIC, created_at: new Date().toISOString(), stores: {} };
  for (const s of db.STORES) out.stores[s] = (await db.all(s)).filter(([k]) => !String(k).startsWith("fail_")).map(([k, v]) => [k, toB64(v)]);
  const name = `docmind-backup-${new Date().toISOString().slice(0, 10)}.docmind`;
  return new File([JSON.stringify(out)], name, { type: "application/octet-stream" });
}

export async function importBackup(file) {
  let data;
  try { data = JSON.parse(await file.text()); } catch { throw Object.assign(new Error("invalid_backup"), { code: "invalid_backup" }); }
  if (data.magic !== MAGIC || !data.stores?.kv?.some(([k]) => k === "app")) throw Object.assign(new Error("invalid_backup"), { code: "invalid_backup" });
  await db.clearAll();
  for (const [s, rows] of Object.entries(data.stores)) {
    if (!db.STORES.includes(s)) continue;
    for (const [k, v] of rows) await db.put(s, k, fromB64(v));
  }
}
