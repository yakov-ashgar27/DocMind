// Composer autocomplete: while typing, suggest processes ("מלגת מילואים" → the documents usually needed)
// and document types ("אישור ל…" → "אישור לימודים"). One tap runs the search. Everything is local (catalog).
import C from "../catalog.js";
import { getLang, t } from "../i18n.js";
import { h, icon } from "../ui.js";

const norm = (s) => s.toLowerCase().replace(/["'״׳.\-_]/g, "").replace(/\s+/g, " ").trim();
const PREFIX = /^(ו?(?:ה|ל|ב|מ|ש|כ)?)/; // Hebrew one-letter prefixes: ל-מלגה, ה-אישור, ב-...

let entries = null;
function build() {
  if (entries) return entries;
  entries = [];
  for (const [key, p] of Object.entries(C.PROCESSES)) {
    entries.push({ kind: "process", key, he: p.he, en: p.en, terms: [p.he, p.en, ...(p.triggers || [])].map(norm), suggested: p.suggested || [] });
  }
  for (const [key, d] of Object.entries(C.DOC_TYPES)) {
    if (key === "unknown" || key === "other") continue;
    entries.push({ kind: "doc", key, he: d.he, en: d.en, terms: [d.he, d.en, ...(C.REQUEST_ALIASES[key] || [])].map(norm) });
  }
  return entries;
}

/** Ranked suggestions for what the user has typed so far (empty text → popular starters). */
export function suggest(text, limit = 5) {
  const all = build();
  const q = norm(text);
  if (!q) return ["reserve_scholarship", "apartment_rental", "job_onboarding", "tax_refund"]
    .map((k) => all.find((e) => e.kind === "process" && e.key === k)).filter(Boolean)
    .concat(all.filter((e) => e.kind === "doc" && e.key === "enrollment_proof")).slice(0, limit);
  // Try the last 1-4 words (the user is usually completing the end of a sentence), with and without a prefix letter.
  const words = q.split(" ");
  const tails = [];
  for (let n = Math.min(4, words.length); n >= 1; n--) {
    const tail = words.slice(-n).join(" ");
    tails.push(tail);
    const stripped = tail.replace(PREFIX, "");
    if (stripped !== tail && stripped.length >= 2) tails.push(stripped);
  }
  const scored = [];
  for (const e of all) {
    let best = 0;
    for (const term of e.terms) {
      for (const tail of tails) {
        if (tail.length < 2) continue;
        if (term === tail) best = Math.max(best, 100 + tail.length);
        else if (term.startsWith(tail)) best = Math.max(best, 60 + tail.length * 2);
        else if (term.split(" ").some((w) => w.startsWith(tail))) best = Math.max(best, 40 + tail.length * 2);
        else if (tail.length >= 3 && term.includes(tail)) best = Math.max(best, 20 + tail.length);
      }
    }
    if (best) scored.push([best + (e.kind === "process" ? 3 : 0), e]);
  }
  const seen = new Set();
  scored.sort((a, b) => b[0] - a[0]);
  const top = scored.length ? scored[0][0] : 0;
  return scored.filter(([sc]) => sc >= top * 0.6).map(([, e]) => e)
    .filter((e) => !seen.has(e.kind + e.key) && seen.add(e.kind + e.key)).slice(0, limit);
}

/** What to send when a suggestion is tapped. */
export function phraseFor(e, lang = getLang()) {
  if (e.kind === "process") return lang === "he" ? `אני צריך מסמכים ל${e.he}` : `I need documents for ${e.en}`;
  return lang === "he" ? `תמצא לי ${e.he}` : `find my ${e.en}`;
}

/** Chip row that follows the composer input. onPick(text) sends. */
export function autocomplete(input, onPick) {
  const bar = h("div", { class: "autocomplete", role: "listbox", "aria-label": t("suggestions") });
  const render = () => {
    const lang = getLang();
    const items = suggest(input.value);
    bar.replaceChildren(...items.map((e) => {
      const usual = e.kind === "process" ? e.suggested.map((d) => C.DOC_TYPES[d]?.[lang]).filter(Boolean) : [];
      return h("button", { class: `ac-chip ${e.kind}`, role: "option", type: "button",
        onclick: () => onPick(phraseFor(e, lang)) },
        icon(e.kind === "process" ? "layers" : "doc", 14),
        h("span", { class: "ac-main" }, h("b", {}, e[lang]),
          usual.length ? h("small", {}, `${t("usually_needed")}: ${usual.slice(0, 4).join(" · ")}${usual.length > 4 ? " …" : ""}`) : null));
    }));
    bar.hidden = !items.length;
  };
  input.addEventListener("input", render);
  input.addEventListener("focus", render);
  render();
  return bar;
}
