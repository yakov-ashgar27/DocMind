// IndexedDB storage. Every value is already encrypted before it gets here.
const DB_NAME = "docmind";
const VERSION = 1;
export const STORES = ["kv", "docs", "blobs", "records"];

let dbp = null;
function db() {
  if (!dbp) {
    dbp = new Promise((resolve, reject) => {
      const req = indexedDB.open(DB_NAME, VERSION);
      req.onupgradeneeded = () => {
        const d = req.result;
        for (const s of STORES) if (!d.objectStoreNames.contains(s)) d.createObjectStore(s);
      };
      req.onsuccess = () => resolve(req.result);
      req.onerror = () => reject(req.error);
    });
  }
  return dbp;
}

function tx(store, mode, fn) {
  return db().then((d) => new Promise((resolve, reject) => {
    const t = d.transaction(store, mode);
    const s = t.objectStore(store);
    let result;
    Promise.resolve(fn(s)).then((r) => { result = r; });
    t.oncomplete = () => resolve(result);
    t.onerror = () => reject(t.error);
    t.onabort = () => reject(t.error || new Error("aborted"));
  }));
}

const req = (r) => new Promise((resolve, reject) => { r.onsuccess = () => resolve(r.result); r.onerror = () => reject(r.error); });

export const get = (store, key) => db().then((d) => req(d.transaction(store).objectStore(store).get(key)));
export const put = (store, key, value) => tx(store, "readwrite", (s) => { s.put(value, key); });
export const del = (store, key) => tx(store, "readwrite", (s) => { s.delete(key); });
export async function all(store) {
  const d = await db();
  const s = d.transaction(store).objectStore(store);
  const [keys, values] = await Promise.all([req(s.getAllKeys()), req(s.getAll())]);
  return keys.map((k, i) => [k, values[i]]);
}
export async function clearAll() {
  const d = await db();
  await Promise.all(STORES.map((st) => new Promise((resolve, reject) => {
    const t = d.transaction(st, "readwrite");
    t.objectStore(st).clear();
    t.oncomplete = resolve; t.onerror = () => reject(t.error);
  })));
}
export async function persist() {
  // Ask the browser not to evict our data under storage pressure.
  try { return await navigator.storage?.persist?.(); } catch { return false; }
}
