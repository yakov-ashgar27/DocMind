// Text extraction on the phone: PDF text (pdf.js, bundled), OCR for photos and scans (tesseract.js,
// Hebrew + English, downloaded once and cached by the service worker). Document bytes never leave the device.

export const SUPPORTED = { "application/pdf": ".pdf", "image/jpeg": ".jpg", "image/png": ".png", "image/webp": ".webp",
  "image/heic": ".heic", "image/avif": ".avif", "image/tiff": ".tiff", "text/plain": ".txt",
  "application/vnd.openxmlformats-officedocument.wordprocessingml.document": ".docx", "application/msword": ".doc" };
const DOCX = "application/vnd.openxmlformats-officedocument.wordprocessingml.document";

const TESSERACT_URL = "https://cdn.jsdelivr.net/npm/tesseract.js@5.1.1/dist/tesseract.min.js";

export function sniff(u8, name = "") {
  const s = (a, b) => String.fromCharCode(...u8.slice(a, b));
  if (s(0, 5) === "%PDF-") return "application/pdf";
  if (u8[0] === 0xff && u8[1] === 0xd8 && u8[2] === 0xff) return "image/jpeg";
  if (u8[0] === 0x89 && s(1, 4) === "PNG") return "image/png";
  if (s(0, 4) === "RIFF" && s(8, 12) === "WEBP") return "image/webp";
  if (s(4, 8) === "ftyp") {
    const brand = s(8, 12);
    if (brand === "avif" || brand === "avis") return "image/avif";
    if (["heic", "heix", "heim", "heis", "hevc", "hevx", "mif1", "msf1"].includes(brand)) return "image/heic";
  }
  if (s(0, 4) === "II*\0" || s(0, 4) === "MM\0*") return "image/tiff";
  if (s(0, 4) === "PK\x03\x04" && name.toLowerCase().endsWith(".docx")) return DOCX;
  if (u8[0] === 0xd0 && u8[1] === 0xcf && u8[2] === 0x11 && u8[3] === 0xe0 && name.toLowerCase().endsWith(".doc")) return "application/msword";
  if (name.toLowerCase().endsWith(".txt")) {
    try { new TextDecoder("utf-8", { fatal: true }).decode(u8.slice(0, 4096)); return "text/plain"; } catch { return null; }
  }
  return null;
}

export function detectLanguage(text) {
  const heb = (text.match(/[֐-׿]/g) || []).length, lat = (text.match(/[A-Za-z]/g) || []).length;
  if (heb + lat < 5) return null;
  if (heb && lat && Math.min(heb, lat) / Math.max(heb, lat) > 0.35) return "mixed";
  return heb > lat ? "he" : "en";
}

const clean = (t) => t.replace(/\f/g, "\n").replace(/[ \t]+/g, " ").replace(/\n{3,}/g, "\n\n").trim();

function fixReversedHebrew(text) {
  const common = ["של", "את", "על", "אישור", "מספר", "תאריך", "שם", "חשבון", "לימודים", "זהות"];
  const cnt = (w) => text.split(w).length - 1;
  const fwd = common.reduce((a, w) => a + cnt(w), 0);
  const rev = common.reduce((a, w) => a + cnt([...w].reverse().join("")), 0);
  if (rev > fwd && rev >= 2) {
    return text.split("\n").map((line) => line.split(" ").map((w) => (/[֐-׿]/.test(w) ? [...w].reverse().join("") : w))
      .reverse().join(" ")).join("\n");
  }
  return text;
}

let pdfjsP = null;
function pdfjs() {
  if (!pdfjsP) {
    pdfjsP = import("../../vendor/pdf.min.mjs").then((m) => {
      m.GlobalWorkerOptions.workerSrc = new URL("../../vendor/pdf.worker.min.mjs", import.meta.url).href;
      return m;
    });
  }
  return pdfjsP;
}

// ---- OCR ------------------------------------------------------------------------------------
let workerP = null;
function loadScript(src) {
  return new Promise((resolve, reject) => {
    if (window.Tesseract) return resolve();
    const s = document.createElement("script");
    s.src = src; s.async = true; s.crossOrigin = "anonymous";
    s.onload = resolve; s.onerror = () => reject(new Error("ocr_unavailable"));
    document.head.appendChild(s);
  });
}
export let ocrProgress = () => {};
export function onOcrProgress(fn) { ocrProgress = fn; }
async function ocrWorker() {
  if (!workerP) {
    workerP = (async () => {
      const { info, isNative } = await import("../native.js");
      if (isNative && info().bundledOcr) {
        // Android app: the OCR engine and Hebrew/English language data ship inside the APK (works offline).
        // If this WebView can't load them from inside a worker, fall back to the one-time CDN download.
        try {
          const base = new URL("../../vendor/tesseract/", import.meta.url).href;
          await loadScript(base + "tesseract.min.js");
          const w = await Promise.race([
            window.Tesseract.createWorker(["heb", "eng"], 1, { workerPath: base + "worker.min.js", corePath: base + "core",
              langPath: base + "lang", logger: (m) => ocrProgress(m) }),
            new Promise((_, rej) => setTimeout(() => rej(new Error("bundled_ocr_timeout")), 60000)),
          ]);
          return w;
        } catch (e) { console.warn("bundled OCR unavailable, using CDN", e); }
      }
      await loadScript(TESSERACT_URL);
      return window.Tesseract.createWorker(["heb", "eng"], 1, { logger: (m) => ocrProgress(m) });
    })().catch((e) => { workerP = null; throw Object.assign(new Error("ocr_unavailable"), { cause: e }); });
  }
  return workerP;
}
async function ocrCanvas(canvas) {
  const w = await ocrWorker();
  const { data } = await w.recognize(canvas);
  return data.text || "";
}

export async function decodeImage(u8, mime) {
  const blob = new Blob([u8], { type: mime });
  try { return await createImageBitmap(blob, { imageOrientation: "from-image" }); } catch { /* fall through */ }
  const url = URL.createObjectURL(blob);
  try {
    const img = new Image();
    img.src = url;
    await img.decode();
    return img;
  } catch { throw new Error(mime === "image/heic" ? "heic_not_supported_on_this_device" : "image_decode_failed"); }
  finally { setTimeout(() => URL.revokeObjectURL(url), 1000); }
}

function toCanvas(img, maxSide = 2000, minSide = 1600) {
  const w0 = img.width, h0 = img.height;
  let f = Math.min(1, maxSide / Math.max(w0, h0));
  if (Math.max(w0, h0) < minSide) f = minSide / Math.max(w0, h0);
  const c = document.createElement("canvas");
  c.width = Math.round(w0 * f); c.height = Math.round(h0 * f);
  const ctx = c.getContext("2d");
  ctx.fillStyle = "#fff"; ctx.fillRect(0, 0, c.width, c.height);
  ctx.drawImage(img, 0, 0, c.width, c.height);
  return c;
}

async function renderPdfPage(page, scale) {
  const viewport = page.getViewport({ scale });
  const c = document.createElement("canvas");
  c.width = Math.ceil(viewport.width); c.height = Math.ceil(viewport.height);
  const ctx = c.getContext("2d");
  ctx.fillStyle = "#fff"; ctx.fillRect(0, 0, c.width, c.height);
  await page.render({ canvasContext: ctx, canvas: c, viewport }).promise;
  return c;
}

async function docxText(u8) {
  const { readZip } = await import("./zip.js");
  const entry = (await readZip(u8)).find((e) => e.name === "word/document.xml");
  if (!entry) throw new Error("invalid_docx");
  let xml = new TextDecoder().decode(await entry.read());
  xml = xml.replace(/<\/w:p>/g, "\n").replace(/<w:tab\/>/g, " ").replace(/<[^>]+>/g, "");
  const ta = document.createElement("textarea");
  ta.innerHTML = xml; // decode &amp; etc. (textarea content is never rendered as HTML)
  return ta.value;
}

// Legacy Word (.doc): readable UTF-16LE runs (Hebrew/Latin/digits) inside the binary.
function docText(u8) {
  const even = u8.length - (u8.length % 2);
  const text = new TextDecoder("utf-16le").decode(u8.subarray(0, even));
  const runs = text.match(/[\u0590-\u05FF\u0020-\u007E\r]{4,}/g) || [];
  return runs.filter((r) => /[\u0590-\u05FFA-Za-z]{2}/.test(r)).join("\n").replace(/\r/g, "\n");
}

export async function extractText(u8, mime, { maxPages = 4 } = {}) {
  if (mime === DOCX) { const t = clean(await docxText(u8)); return { text: t, ocr: false, language: detectLanguage(t) }; }
  if (mime === "application/msword") { const t = clean(docText(u8)); return { text: t, ocr: false, language: detectLanguage(t) }; }
  if (mime === "text/plain") { const t = new TextDecoder().decode(u8); return { text: t, ocr: false, language: detectLanguage(t) }; }
  if (mime.startsWith("image/")) {
    const img = await decodeImage(u8, mime);
    const text = clean(await ocrCanvas(toCanvas(img)));
    return { text, ocr: true, language: detectLanguage(text) };
  }
  if (mime === "application/pdf") {
    const lib = await pdfjs();
    const pdf = await lib.getDocument({ data: u8.slice(), isEvalSupported: false }).promise;
    const parts = [];
    for (let i = 1; i <= Math.min(pdf.numPages, maxPages * 3); i++) {
      const tc = await (await pdf.getPage(i)).getTextContent();
      parts.push(tc.items.map((it) => it.str + (it.hasEOL ? "\n" : " ")).join(""));
    }
    let text = fixReversedHebrew(clean(parts.join("\n")));
    if (text.replace(/\s/g, "").length >= 40) return { text, ocr: false, language: detectLanguage(text), pages: pdf.numPages };
    const ocrParts = [];
    for (let i = 1; i <= Math.min(pdf.numPages, maxPages); i++) ocrParts.push(await ocrCanvas(await renderPdfPage(await pdf.getPage(i), 2)));
    text = clean(ocrParts.join("\n")) || text;
    return { text, ocr: true, language: detectLanguage(text), pages: pdf.numPages };
  }
  throw new Error("unsupported_file_type");
}

export async function thumbnail(u8, mime) {
  try {
    let src;
    if (mime === "application/pdf") {
      const lib = await pdfjs();
      const pdf = await lib.getDocument({ data: u8.slice(), isEvalSupported: false }).promise;
      src = await renderPdfPage(await pdf.getPage(1), 0.6);
    } else if (mime.startsWith("image/")) src = await decodeImage(u8, mime);
    else return null;
    const f = Math.min(1, 360 / Math.max(src.width, src.height));
    const c = document.createElement("canvas");
    c.width = Math.round(src.width * f); c.height = Math.round(src.height * f);
    const ctx = c.getContext("2d");
    ctx.fillStyle = "#fff"; ctx.fillRect(0, 0, c.width, c.height);
    ctx.drawImage(src, 0, 0, c.width, c.height);
    const blob = await new Promise((r) => c.toBlob(r, "image/jpeg", 0.72));
    return blob ? new Uint8Array(await blob.arrayBuffer()) : null;
  } catch { return null; }
}

// Image -> one-page PDF for the optional combined PDF.
export async function imageAsJpeg(u8, mime) {
  if (mime === "image/jpeg") return u8;
  const img = await decodeImage(u8, mime);
  const c = toCanvas(img, 2400, 0);
  const blob = await new Promise((r) => c.toBlob(r, "image/jpeg", 0.9));
  return new Uint8Array(await blob.arrayBuffer());
}
