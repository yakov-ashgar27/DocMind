// On-device encryption (WebCrypto). Nothing here ever leaves the phone.
//
// passcode --PBKDF2(600k)--> KEK --wraps--> DEK (AES-256-GCM, app data key)
// each document: random content key Kdoc (AES-256-GCM) encrypts file, thumbnail, text and private metadata
//   Kdoc is wrapped by DEK            (normal documents)
//   Kdoc is wrapped by vault PUBLIC key (RSA-OAEP-3072) for protected folders: anyone holding the app
//   can ADD to the vault, only the vault PIN (which unwraps the RSA private key) can OPEN it.

const enc = new TextEncoder();
const dec = new TextDecoder();
const subtle = crypto.subtle;
export const PBKDF2_ITER = 600000;

export const rand = (n) => crypto.getRandomValues(new Uint8Array(n));
export const b64 = (u8) => btoa(String.fromCharCode(...new Uint8Array(u8)));
export const unb64 = (s) => Uint8Array.from(atob(s), (c) => c.charCodeAt(0));

async function kek(secret, salt, iterations = PBKDF2_ITER) {
  const base = await subtle.importKey("raw", enc.encode(secret), "PBKDF2", false, ["deriveKey"]);
  return subtle.deriveKey({ name: "PBKDF2", salt, iterations, hash: "SHA-256" }, base,
    { name: "AES-GCM", length: 256 }, false, ["encrypt", "decrypt"]);
}

export async function newAesKey() {
  return subtle.generateKey({ name: "AES-GCM", length: 256 }, true, ["encrypt", "decrypt"]);
}

export async function seal(key, data, aad = "") {
  const iv = rand(12);
  const bytes = typeof data === "string" ? enc.encode(data) : data;
  const ct = new Uint8Array(await subtle.encrypt({ name: "AES-GCM", iv, additionalData: enc.encode(aad) }, key, bytes));
  const out = new Uint8Array(13 + ct.length);
  out[0] = 1; out.set(iv, 1); out.set(ct, 13);
  return out;
}

export async function open(key, blob, aad = "") {
  const u8 = blob instanceof Uint8Array ? blob : new Uint8Array(blob);
  if (u8[0] !== 1) throw new Error("bad_ciphertext");
  return new Uint8Array(await subtle.decrypt({ name: "AES-GCM", iv: u8.slice(1, 13), additionalData: enc.encode(aad) }, key, u8.slice(13)));
}

export const sealJSON = (key, obj, aad) => seal(key, JSON.stringify(obj), aad);
export const openJSON = async (key, blob, aad) => JSON.parse(dec.decode(await open(key, blob, aad)));

// ---- passcode-protected app key -----------------------------------------------------------
export async function createAppKey(passcode) {
  const salt = rand(16);
  const dek = await newAesKey();
  const raw = new Uint8Array(await subtle.exportKey("raw", dek));
  const wrapped = await seal(await kek(passcode, salt), raw, "dek");
  raw.fill(0);
  return { record: { salt: b64(salt), wrapped: b64(wrapped), iter: PBKDF2_ITER, v: 1 }, dek: await importAes(dek) };
}

export async function unlockAppKey(record, passcode) {
  const raw = await open(await kek(passcode, unb64(record.salt), record.iter), unb64(record.wrapped), "dek");
  const key = await subtle.importKey("raw", raw, "AES-GCM", false, ["encrypt", "decrypt"]);
  raw.fill(0);
  return key;
}

export async function rewrapAppKey(record, oldPass, newPass) {
  const raw = await open(await kek(oldPass, unb64(record.salt), record.iter), unb64(record.wrapped), "dek");
  const salt = rand(16);
  const wrapped = await seal(await kek(newPass, salt), raw, "dek");
  raw.fill(0);
  return { salt: b64(salt), wrapped: b64(wrapped), iter: PBKDF2_ITER, v: 1 };
}

async function importAes(extractableKey) {
  const raw = await subtle.exportKey("raw", extractableKey);
  return subtle.importKey("raw", raw, "AES-GCM", false, ["encrypt", "decrypt"]);
}

// ---- per-document content keys ------------------------------------------------------------
export async function newDocKey() {
  return newAesKey(); // extractable so it can be wrapped
}

export async function wrapDocKey(docKey, { dek, vaultPublic }) {
  const raw = new Uint8Array(await subtle.exportKey("raw", docKey));
  try {
    if (vaultPublic) return { kind: "vault", w: b64(await subtle.encrypt({ name: "RSA-OAEP" }, vaultPublic, raw)) };
    return { kind: "dek", w: b64(await seal(dek, raw, "dockey")) };
  } finally { raw.fill(0); }
}

export async function unwrapDocKey(wrapped, { dek, vaultPrivate }) {
  let raw;
  if (wrapped.kind === "vault") {
    if (!vaultPrivate) throw new Error("vault_locked");
    raw = new Uint8Array(await subtle.decrypt({ name: "RSA-OAEP" }, vaultPrivate, unb64(wrapped.w)));
  } else {
    raw = await open(dek, unb64(wrapped.w), "dockey");
  }
  const key = await subtle.importKey("raw", raw, "AES-GCM", true, ["encrypt", "decrypt"]);
  raw.fill(0);
  return key;
}

// ---- vault (RSA key pair; private key sealed by the vault PIN) -------------------------------
export async function createVault(pin) {
  const pair = await subtle.generateKey({ name: "RSA-OAEP", modulusLength: 3072, publicExponent: new Uint8Array([1, 0, 1]), hash: "SHA-256" },
    true, ["encrypt", "decrypt"]);
  const pub = await subtle.exportKey("spki", pair.publicKey);
  const priv = new Uint8Array(await subtle.exportKey("pkcs8", pair.privateKey));
  const salt = rand(16);
  const sealed = await seal(await kek(pin, salt), priv, "vault");
  priv.fill(0);
  return { pub: b64(pub), salt: b64(salt), sealed: b64(sealed), iter: PBKDF2_ITER };
}

export async function vaultPublicKey(vault) {
  return subtle.importKey("spki", unb64(vault.pub), { name: "RSA-OAEP", hash: "SHA-256" }, false, ["encrypt"]);
}

export async function unlockVault(vault, pin) {
  const priv = await open(await kek(pin, unb64(vault.salt), vault.iter), unb64(vault.sealed), "vault");
  const key = await subtle.importKey("pkcs8", priv, { name: "RSA-OAEP", hash: "SHA-256" }, false, ["decrypt"]);
  priv.fill(0);
  return key;
}

export async function resealVault(vault, oldPin, newPin) {
  const priv = await open(await kek(oldPin, unb64(vault.salt), vault.iter), unb64(vault.sealed), "vault");
  const salt = rand(16);
  const sealed = await seal(await kek(newPin, salt), priv, "vault");
  priv.fill(0);
  return { ...vault, salt: b64(salt), sealed: b64(sealed), iter: PBKDF2_ITER };
}

export async function sha256hex(bytes) {
  const h = new Uint8Array(await subtle.digest("SHA-256", bytes));
  return [...h].map((b) => b.toString(16).padStart(2, "0")).join("");
}

export function uuid() {
  return [...rand(16)].map((b) => b.toString(16).padStart(2, "0")).join("");
}
