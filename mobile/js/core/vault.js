// Session: app key (DEK) and vault keys live in memory only while unlocked.
import * as cr from "./crypto.js";
import * as db from "./db.js";

export const session = { dek: null, vaultPub: null, vaultPriv: null, vaultTimer: null, listeners: new Set() };
export const DEFAULT_LOCKED = ["identity", "finance", "medical"];
export const VAULT_TTL = 5 * 60;

export class LocalError extends Error {
  constructor(code, status = 400) { super(code); this.code = code; this.status = status; }
}

// Escalating delay after wrong passcodes / PINs (stored unencrypted on purpose: it must work while locked).
async function guard(kind) {
  const f = (await db.get("kv", "fail_" + kind)) || { n: 0, until: 0 };
  if (f.until > Date.now()) throw new LocalError("temporarily_locked:" + Math.ceil((f.until - Date.now()) / 1000), 429);
  return f;
}
async function fail(kind, f) {
  const n = f.n + 1;
  const delay = n >= 5 ? Math.min(3600, 30 * 2 ** (n - 5)) * 1000 : 0;
  await db.put("kv", "fail_" + kind, { n, until: Date.now() + delay });
}
const ok = (kind) => db.put("kv", "fail_" + kind, { n: 0, until: 0 });

export async function isSetUp() { return !!(await db.get("kv", "app")); }

export async function setup(passcode) {
  if (!/^.{6,64}$/.test(passcode)) throw new LocalError("passcode_too_short");
  const { record, dek } = await cr.createAppKey(passcode);
  await db.put("kv", "app", record);
  session.dek = dek;
  await db.persist();
}

export async function unlockApp(passcode) {
  const f = await guard("app");
  try {
    session.dek = await cr.unlockAppKey(await db.get("kv", "app"), passcode);
  } catch {
    await fail("app", f);
    throw new LocalError("invalid_passcode", 403);
  }
  await ok("app");
  const v = await db.get("kv", "vault");
  session.vaultPub = v ? await cr.vaultPublicKey(v) : null;
}

export async function changePasscode(oldP, newP) {
  if (!/^.{6,64}$/.test(newP)) throw new LocalError("passcode_too_short");
  try { await db.put("kv", "app", await cr.rewrapAppKey(await db.get("kv", "app"), oldP, newP)); }
  catch { throw new LocalError("invalid_passcode", 403); }
}

export function lockApp() {
  session.dek = null;
  lockVault();
}

// ---- vault ----------------------------------------------------------------------------------
const PIN_RE = /^\d{4,12}$/;
export async function hasVault() { return !!(await db.get("kv", "vault")); }

export async function createVault(pin) {
  if (!PIN_RE.test(pin)) throw new LocalError("invalid_pin_format");
  if (new Set(pin).size === 1 || "0123456789012".includes(pin) || "9876543210".includes(pin)) throw new LocalError("pin_too_simple");
  const v = await cr.createVault(pin);
  await db.put("kv", "vault", v);
  session.vaultPub = await cr.vaultPublicKey(v);
}

export async function changeVaultPin(oldPin, newPin) {
  if (!PIN_RE.test(newPin)) throw new LocalError("invalid_pin_format");
  try { await db.put("kv", "vault", await cr.resealVault(await db.get("kv", "vault"), oldPin, newPin)); }
  catch { throw new LocalError("invalid_pin", 403); }
}

export async function unlockVault(pin) {
  const v = await db.get("kv", "vault");
  if (!v) throw new LocalError("no_pin", 409);
  const f = await guard("vault");
  try { session.vaultPriv = await cr.unlockVault(v, pin); }
  catch {
    await fail("vault", f);
    const g = await db.get("kv", "fail_vault");
    throw new LocalError(g.until > Date.now() ? "vault_temporarily_locked" : "invalid_pin", g.until > Date.now() ? 429 : 403);
  }
  await ok("vault");
  clearTimeout(session.vaultTimer);
  session.vaultTimer = setTimeout(lockVault, VAULT_TTL * 1000);
  session.listeners.forEach((f2) => f2(true));
}

export function lockVault() {
  const was = !!session.vaultPriv;
  session.vaultPriv = null;
  clearTimeout(session.vaultTimer);
  if (was) session.listeners.forEach((f) => f(false));
}

export const vaultOpen = () => !!session.vaultPriv;
