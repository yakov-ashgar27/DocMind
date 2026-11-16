// Bilingual intent parser, a port of backend/docmind/assistant/intent.py.
import C from "../catalog.js";

const HEB = "\\u0590-\\u05FF";
const PREFIX = "(?:[והבלמשכ]{1,2})?";
const esc = (s) => s.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");

export function detectLang(text, fallback = "he") {
  const heb = (text.match(/[֐-׿]/g) || []).length;
  const lat = (text.match(/[A-Za-z]/g) || []).length;
  if (!heb && !lat) return fallback;
  return heb >= lat ? "he" : "en";
}

const norm = (t) => t.toLowerCase().replace(/״/g, "\"").replace(/׳/g, "'").replace(/–/g, "-").replace(/\s+/g, " ");

function aliasRx(alias) {
  const a = esc(norm(alias));
  if (/[֐-׿]/.test(alias)) return new RegExp(`(?<![${HEB}\\w])${PREFIX}${a}(?![${HEB}])`, "g");
  return new RegExp(`(?<![\\w])${a}(?![\\w])`, "g");
}

// Hebrew construct phrases take the definite article on the LAST word ("אישור ניהול החשבון", "תעודת הזהות").
function variants(alias) {
  const w = alias.split(" ");
  if (w.length > 1 && /[\u0590-\u05FF]/.test(w.at(-1)) && !w.at(-1).startsWith("ה")) return [alias, [...w.slice(0, -1), "ה" + w.at(-1)].join(" ")];
  return [alias];
}
const ALIASES = Object.entries(C.REQUEST_ALIASES).flatMap(([dt, list]) => list.flatMap((a) => variants(a).map((v) => [v, dt, aliasRx(v)])))
  .sort((x, y) => y[0].length - x[0].length);
const PROCS = Object.entries(C.PROCESSES).flatMap(([pk, p]) => p.triggers.flatMap((t) => variants(t).map((v) => [v, pk, aliasRx(v)])))
  .sort((x, y) => y[0].length - x[0].length);

const TASK = [
  /\b(?:documents?|docs|paperwork|everything|what(?:'s| is) needed)\b.*?\bfor\b\s+(?:my |a |an |the |another |this )?(.+)/i,
  /\bprepare\b\s+(?:everything|all|documents?)?.*?\bfor\b\s+(?:my |a |an |the |another |this )?(.+)/i,
  /\b(?:submit|apply for|applying for|application for)\b\s+(?:my |a |an |the |another )?(.+)/i,
  new RegExp(`מסמכים\\s+(?:עבור|בשביל|ל|ל־|ל-)\\s*([${HEB}\\w\\s"'-]+)`),
  new RegExp(`(?:להגיש|להגשת|הגשת|הגשה של|הגשה ל)\\s*([${HEB}\\w\\s"'-]+)`),
  new RegExp(`(?:תכין|תכיני|הכן|להכין)\\s+(?:לי\\s+)?(?:את\\s+)?(?:כל\\s+)?(?:מה ש|המסמכים\\s+)?(?:צריך\\s+)?(?:עבור|בשביל|ל)\\s*([${HEB}\\w\\s"'-]+)`),
];
const AGAIN = /\b(another|again|new|next|once more)\b|נוספת|נוסף|שוב|עוד פעם|חדשה|הבאה/i;
const YES = /^\s*(yes|yep|yeah|sure|ok|okay|please do|do it|confirm|correct|כן|בטח|אישור|מאשר|מאשרת|נכון|סבבה|יאללה|תשמור|שמור)(?![\w֐-׿])/i;
const NO = /^\s*(no|nope|not now|don't|do not|לא|לא תודה|אל תשמור|לא עכשיו)(?![\w֐-׿])/i;
const NOTHING_MORE = /\b(that'?s all|nothing else|no more|that is all|nothing)\b|זה הכל|זהו|אין עוד|לא צריך עוד|שום דבר/i;
const ADDING = /\b(also|add|plus|another document|in addition)\b|גם|בנוסף|תוסיף|תוסיפי|להוסיף|ועוד/i;
const FIND = /^\s*(?:please\s+)?(find|search|where(?:'s| is)|show me|locate)\b|^\s*(תמצא|תמצאי|מצא|חפש|תחפש|תחפשי|איפה|תראה לי|תראי לי)/i;
const GREETING = /^\s*(hi|hello|hey|good (?:morning|evening)|שלום|היי|הי|בוקר טוב|ערב טוב)\W*$/i;
const HELP = /\b(help|what can you do|how does this work)\b|עזרה|מה אתה יודע|מה את יודעת|איך זה עובד/i;

function isOnlyDocNames(s) {
  let n = norm(s);
  for (const [, , rx] of ALIASES) n = n.replace(new RegExp(rx.source, "g"), " ");
  return !n.replace(/[\s,.&]|\band\b|\bmy\b|ו/g, "");
}

export function parse(text, fallbackLang = "he") {
  const it = { lang: detectLang(text, fallbackLang), doc_types: [], process_key: null, custom_purpose: null, free_text: text.trim() };
  let masked = norm(text);
  const blank = (m) => { masked = masked.slice(0, m.index) + " ".repeat(m[0].length) + masked.slice(m.index + m[0].length); };
  for (const [, pk, rx] of PROCS) {
    rx.lastIndex = 0;
    const m = new RegExp(rx.source).exec(masked);
    if (m) { it.process_key = pk; blank(m); break; }
  }
  const found = [];
  for (const [, dt, rx] of ALIASES) {
    for (const m of [...masked.matchAll(new RegExp(rx.source, "g"))]) { found.push([m.index, dt]); blank(m); }
  }
  for (const [, dt] of found.sort((a, b) => a[0] - b[0])) if (!it.doc_types.includes(dt)) it.doc_types.push(dt);
  if (!it.process_key) {
    for (const rx of TASK) {
      const m = rx.exec(text);
      if (m) {
        let p = m[1].trim().replace(/[.?!,]+$/, "");
        p = p.split(/\s+(?:and|ו)?(?:please|בבקשה)\b/)[0].trim();
        if (p.length >= 2 && p.length <= 80 && !isOnlyDocNames(p)) { it.custom_purpose = p; break; }
      }
    }
  }
  it.is_task = !!(it.process_key || it.custom_purpose);
  it.wants_again = AGAIN.test(text);
  it.yes = YES.test(text);
  it.no = NO.test(text) && !it.yes;
  it.nothing_more = NOTHING_MORE.test(text);
  it.adding = ADDING.test(text);
  it.find_only = FIND.test(text) && !it.adding;
  it.greeting = GREETING.test(text);
  it.help = HELP.test(text);
  return it;
}
