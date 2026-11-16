// Minimal ZIP reader for WhatsApp "Export chat → Include media" archives (stored + deflate).
const MAX_ENTRIES = 300, MAX_TOTAL = 200 * 1024 * 1024;

export async function readZip(u8) {
  const dv = new DataView(u8.buffer, u8.byteOffset, u8.byteLength);
  let eocd = -1;
  for (let i = u8.length - 22; i >= Math.max(0, u8.length - 65557); i--) if (dv.getUint32(i, true) === 0x06054b50) { eocd = i; break; }
  if (eocd < 0) throw new Error("invalid_zip");
  const count = dv.getUint16(eocd + 10, true);
  let p = dv.getUint32(eocd + 16, true);
  if (count > MAX_ENTRIES * 3) throw new Error("zip_too_large");
  const entries = [];
  let total = 0;
  for (let n = 0; n < count; n++) {
    if (dv.getUint32(p, true) !== 0x02014b50) throw new Error("invalid_zip");
    const method = dv.getUint16(p + 10, true), csize = dv.getUint32(p + 20, true), size = dv.getUint32(p + 24, true);
    const nlen = dv.getUint16(p + 28, true), elen = dv.getUint16(p + 30, true), clen = dv.getUint16(p + 32, true);
    const local = dv.getUint32(p + 42, true);
    const name = new TextDecoder().decode(u8.slice(p + 46, p + 46 + nlen));
    entries.push({ name, method, csize, size, local });
    total += size;
    p += 46 + nlen + elen + clen;
  }
  if (total > MAX_TOTAL) throw new Error("zip_too_large");
  return entries.filter((e) => !e.name.endsWith("/")).map((e) => ({
    name: e.name, size: e.size,
    async read() {
      const lnlen = dv.getUint16(e.local + 26, true), lelen = dv.getUint16(e.local + 28, true);
      const start = e.local + 30 + lnlen + lelen;
      const data = u8.slice(start, start + e.csize);
      if (e.method === 0) return data;
      if (e.method !== 8) throw new Error("unsupported_zip_method");
      const stream = new Blob([data]).stream().pipeThrough(new DecompressionStream("deflate-raw"));
      const out = new Uint8Array(await new Response(stream).arrayBuffer());
      if (out.length !== e.size) throw new Error("invalid_zip");
      return out;
    },
  }));
}
