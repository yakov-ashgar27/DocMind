// Document understanding, a port of backend/docmind/services/classifier.py. Runs on the phone.
import C from "../catalog.js";

const { DOC_TYPES, KNOWN_ISSUERS } = C;
const esc = (s) => s.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");

export function norm(s) {
  return (s || "").toLowerCase().replace(/״/g, "\"").replace(/׳/g, "'").replace(/[”“]/g, "\"").replace(/\s+/g, " ");
}

function count(text, kw) {
  if (/^[a-z0-9' \-/<.]+$/.test(kw)) {
    const m = text.match(new RegExp("(?<![a-z])" + esc(kw) + "(?![a-z])", "g"));
    return m ? m.length : 0;
  }
  let n = 0, i = text.indexOf(kw);
  while (i >= 0) { n++; i = text.indexOf(kw, i + kw.length); }
  return n;
}

export function validIsraeliId(num) {
  if (!/^\d{1,9}$/.test(num) || /^0+$/.test(num)) return false;
  const s = num.padStart(9, "0");
  let total = 0;
  for (let i = 0; i < 9; i++) { let d = +s[i] * (1 + (i % 2)); if (d > 9) d -= 9; total += d; }
  return total % 10 === 0;
}

function structural(text) {
  const out = {};
  if (/P<ISR|P<[A-Z]{3}[A-Z<]{5,}/.test(text)) out.passport = 8;
  if (/\bIL\d{2}\s?(?:\d{4}\s?){4}\d{3}\b/.test(text)) out.bank_confirmation = 1.5;
  for (const m of text.matchAll(/(?<!\d)(\d{9})(?!\d)/g)) {
    if (validIsraeliId(m[1])) { out.id_card = (out.id_card || 0) + 1; out.id_appendix = (out.id_appendix || 0) + 0.5; break; }
  }
  return out;
}

export function scoreTypes(text, filename) {
  const t = norm(text), fn = norm(filename);
  const scores = {};
  for (const [key, spec] of Object.entries(DOC_TYPES)) {
    let s = 0;
    for (const [kw, w] of Object.entries(spec.kw)) {
      const hits = count(t, norm(kw));
      if (hits) s += w * (1 + 0.25 * Math.min(hits - 1, 4));
    }
    if (spec.fn.some((h) => fn.includes(h))) s += 3;
    if (s) scores[key] = s;
  }
  for (const [k, v] of Object.entries(structural(text))) scores[k] = (scores[k] || 0) + v;
  if ((scores.id_appendix || 0) >= 5 && scores.id_card) scores.id_card *= 0.6;
  if (scores.reserve_order && scores.reserve_service_confirmation) {
    if (["ימי מילואים", "3010", "days of reserve"].some((k) => t.includes(k))) scores.reserve_order *= 0.5;
    else if (["להתייצב", "report for duty", "צו 8"].some((k) => t.includes(k))) scores.reserve_service_confirmation *= 0.5;
  }
  return scores;
}

export function classify(text, filename, personalHint = null) {
  const scores = scoreTypes(text, filename);
  let best = "unknown", conf = 0;
  const ranked = Object.entries(scores).sort((a, b) => b[1] - a[1]);
  if (ranked.length) {
    const [k, top] = ranked[0];
    const second = ranked[1] ? ranked[1][1] : 0;
    best = k;
    conf = Math.min(0.99, (1 - Math.exp(-top / 6)) * (0.6 + 0.4 * (top - second) / top));
    if (top < 3) { best = "unknown"; conf *= 0.5; }
  }
  if (personalHint && personalHint[1] > Math.max(conf, 0.55)) [best, conf] = personalHint;
  const dates = extractDates(text);
  return {
    doc_type: best, confidence: Math.round(conf * 1000) / 1000, category: DOC_TYPES[best]?.cat || "other",
    issuer: detectIssuer(text), doc_date: dates.doc_date || null, expiry_date: dates.expiry_date || null,
  };
}

export function detectIssuer(text) {
  const t = norm(text);
  let best = null, bestPos = Infinity;
  for (const [pat, name] of KNOWN_ISSUERS) {
    const p = norm(pat);
    let pos;
    if (/^[a-z0-9 \-']+$/.test(p)) {
      const m = new RegExp("(?<![a-z])" + esc(p) + "(?![a-z])").exec(t);
      pos = m ? m.index : -1;
    } else pos = t.indexOf(p);
    if (pos >= 0 && pos < bestPos) { best = name; bestPos = pos; }
  }
  return best;
}

const iso = (y, m, d) => {
  const dt = new Date(Date.UTC(y, m - 1, d));
  if (dt.getUTCFullYear() !== y || dt.getUTCMonth() !== m - 1 || dt.getUTCDate() !== d || y < 1950 || y > 2100) return null;
  return dt.toISOString().slice(0, 10);
};
const EXPIRY_WORDS = ["בתוקף עד", "תוקף עד", "תאריך פקיעה", "פג תוקף", "valid until", "valid thru", "expiry", "expires", "date of expiry", "expiration"];

export function extractDates(text, today = new Date().toISOString().slice(0, 10)) {
  const found = [];
  for (const m of text.matchAll(/(?<!\d)(\d{1,2})[./-](\d{1,2})[./-](\d{4})(?!\d)/g)) { const d = iso(+m[3], +m[2], +m[1]); if (d) found.push([m.index, d]); }
  for (const m of text.matchAll(/(?<!\d)(\d{4})-(\d{2})-(\d{2})(?!\d)/g)) { const d = iso(+m[1], +m[2], +m[3]); if (d) found.push([m.index, d]); }
  for (const m of text.matchAll(/(?<!\d)(\d{1,2})[./](\d{1,2})[./](\d{2})(?![\d./])/g)) {
    const y = +m[3]; const d = iso(y < 70 ? 2000 + y : 1900 + y, +m[2], +m[1]); if (d) found.push([m.index, d]);
  }
  if (!found.length) return {};
  const low = text.toLowerCase();
  let expiry = null;
  for (const w of EXPIRY_WORDS) {
    const i = low.indexOf(w);
    if (i >= 0) {
      const after = found.filter(([pos]) => pos - i >= 0 && pos - i <= 60).map(([, d]) => d);
      if (after.length) { expiry = after[0]; break; }
    }
  }
  const past = found.map(([, d]) => d).filter((d) => d <= today && d !== expiry).sort();
  const out = {};
  if (past.length) out.doc_date = past[past.length - 1];
  if (expiry) out.expiry_date = expiry;
  return out;
}

export function freshness(doc, today = new Date()) {
  const t = today.toISOString().slice(0, 10);
  const days = (a, b) => Math.round((Date.parse(a) - Date.parse(b)) / 86400000);
  if (doc.expiry_date) {
    if (doc.expiry_date < t) return { state: "expired", date: doc.expiry_date };
    if (days(doc.expiry_date, t) <= 60) return { state: "expiring", date: doc.expiry_date };
  }
  const maxAge = DOC_TYPES[doc.doc_type]?.max_age;
  const ref = doc.doc_date || (doc.created_at || "").slice(0, 10);
  if (maxAge && ref) {
    const age = days(t, ref);
    if (age > maxAge) return { state: "maybe_outdated", days: age, max_age: maxAge };
  }
  return { state: "ok" };
}

export function smartName(c, filename, lang) {
  const base = filename.replace(/\.[^.]+$/, "");
  const meaningless = /^(img|image|scan|doc|document|file|photo|pxl|dsc|whatsapp image|screenshot|download|p|wa)?[\s_\-]*[\d_\-\s:.()atw]*$/i.test(base);
  if (!meaningless || c.doc_type === "unknown") return base;
  const parts = [DOC_TYPES[c.doc_type][lang === "he" ? "he" : "en"]];
  if (c.issuer && c.issuer.length <= 20) parts.push(c.issuer);
  return parts.join(" · ");
}
