// Character n-gram TF-IDF search (2–4 grams, sublinear tf, cosine), in memory only.
import C from "../catalog.js";

const CAT = Object.fromEntries(C.CATEGORIES.map((c) => [c.key, c]));
const norm = (s) => (s || "").toLowerCase().replace(/״/g, "\"").replace(/׳/g, "'").replace(/\s+/g, " ");

export function docSearchText(doc, text) {
  const t = C.DOC_TYPES[doc.doc_type] || {};
  const cat = CAT[doc.category_key] || {};
  const head = [doc.display_name, doc.original_filename, t.en, t.he, ...(C.REQUEST_ALIASES[doc.doc_type] || []),
    cat.en, cat.he, doc.issuer, ...(doc.tags || [])].filter(Boolean).join(" ");
  return `${head} ${head} ${(text || "").slice(0, 6000)}`;
}

function grams(s) {
  const out = new Map();
  for (const word of norm(s).split(" ")) {
    if (!word) continue;
    const w = ` ${word} `;
    for (let n = 2; n <= 4; n++) for (let i = 0; i + n <= w.length; i++) {
      const g = w.slice(i, i + n);
      out.set(g, (out.get(g) || 0) + 1);
    }
  }
  return out;
}

export class Index {
  constructor(entries) { // entries: [{doc, text}]
    this.docs = entries.map((e) => e.doc);
    const tfs = entries.map((e) => grams(docSearchText(e.doc, e.text)));
    const df = new Map();
    for (const tf of tfs) for (const g of tf.keys()) df.set(g, (df.get(g) || 0) + 1);
    const N = tfs.length;
    this.idf = (g) => Math.log((1 + N) / (1 + (df.get(g) || 0))) + 1;
    this.vecs = tfs.map((tf) => this.vector(tf));
  }
  vector(tf) {
    const v = new Map();
    let norm2 = 0;
    for (const [g, c] of tf) { const w = (1 + Math.log(c)) * this.idf(g); v.set(g, w); norm2 += w * w; }
    const n = Math.sqrt(norm2) || 1;
    for (const [g, w] of v) v.set(g, w / n);
    return v;
  }
  search(query, { limit = 20, min = 0.08, exclude = new Set() } = {}) {
    if (!query.trim() || !this.docs.length) return [];
    const q = this.vector(grams(query));
    const out = [];
    this.vecs.forEach((v, i) => {
      if (exclude.has(this.docs[i].category_key)) return;
      let s = 0;
      for (const [g, w] of q) { const x = v.get(g); if (x) s += w * x; }
      if (s >= min) out.push([this.docs[i], s]);
    });
    return out.sort((a, b) => b[1] - a[1]).slice(0, limit);
  }
}

export function similarity(a, b) {
  const idx = new Index([{ doc: { doc_type: "", category_key: "" }, text: a }]);
  const va = idx.vector(grams(a)), vb = idx.vector(grams(b));
  let s = 0;
  for (const [g, w] of va) { const x = vb.get(g); if (x) s += w * x; }
  return s;
}
