import { api, thumbUrl, triggerDownload } from "./api.js";
import { fmtDate, getLang, L, t, errText } from "./i18n.js";
import { categoryOf, docTypeLabel, loadCategories, store } from "./store.js";
import { h, icon, spinner, toast } from "./ui.js";

const SOURCE_ICON = { upload: "phone", whatsapp_import: "msg", gmail: "mail", gdrive: "cloud" };
const SOURCE_LABEL = {
  upload: { he: "הועלה מהמכשיר", en: "Uploaded" }, whatsapp_import: { he: "וואטסאפ", en: "WhatsApp" },
  gmail: { he: "Gmail", en: "Gmail" }, gdrive: { he: "Google Drive", en: "Google Drive" },
};
export const sourceLabel = (k) => L(SOURCE_LABEL[k]) || k;

export function thumb(doc, size = "md") {
  const box = h("div", { class: `thumb ${size}` }, icon(doc.mime_type === "application/pdf" ? "doc" : "image", 22));
  if (doc.status === "ready" && doc.is_local !== false) {
    thumbUrl(doc.id).then((u) => {
      if (!u) return;
      const img = h("img", { src: u, alt: "", loading: "lazy" });
      box.replaceChildren(img);
    });
  }
  return box;
}

export function freshnessBadge(f) {
  if (!f || f.state === "ok" || f.state === "unknown") return null;
  return h("span", { class: `badge ${f.state === "expired" ? "bad" : "warn"}` }, icon("clock", 13), t("k_" + f.state));
}

export function docMeta(doc) {
  const lang = getLang();
  const bits = [];
  if (doc.status === "processing") return h("div", { class: "meta" }, spinner(), t("processing"));
  if (doc.status === "failed") return h("div", { class: "meta bad" }, icon("alert", 14), t("failed"));
  bits.push(docTypeLabel(doc.doc_type, lang));
  if (doc.issuer) bits.push(doc.issuer);
  if (doc.doc_date) bits.push(fmtDate(doc.doc_date));
  return h("div", { class: "meta" }, icon(SOURCE_ICON[doc.source_kind] || "doc", 14), bits.join(" · "));
}

export function docCard(doc, { onClick, extra } = {}) {
  const badges = [freshnessBadge(doc.freshness)];
  if (doc.duplicate_of) badges.push(h("span", { class: "badge warn" }, t("k_duplicate")));
  if (doc.status === "ready" && doc.doc_type === "unknown") badges.push(h("span", { class: "badge" }, t("k_unclassified")));
  return h("button", { class: "doc-card", onclick: onClick, type: "button" },
    thumb(doc),
    h("div", { class: "doc-main" },
      h("div", { class: "doc-title" }, doc.display_name),
      docMeta(doc),
      h("div", { class: "badges" }, badges)),
    extra || icon("chevron", 18));
}

export function statusPill(status) {
  const kind = status.startsWith("found_external") ? "ext" : status.startsWith("found") ? "ok" : status === "not_found" ? "bad" : "warn";
  const ic = kind === "ok" ? "check" : kind === "ext" ? "cloud" : "alert";
  return h("span", { class: `pill ${kind}` }, icon(ic, 14), t("st_" + status));
}

export async function openPreview(doc) {
  const { url } = await api(`/documents/${doc.id}/link`, { method: "POST", body: { disposition: "inline" } });
  const { sheet } = await import("./ui.js");
  const body = doc.mime_type === "application/pdf"
    ? h("iframe", { class: "preview-frame", src: url, title: doc.display_name })
    : h("img", { class: "preview-img", src: url, alt: doc.display_name });
  sheet(doc.display_name, h("div", { class: "preview" }, body,
    h("div", { class: "row end" }, h("button", { class: "btn ghost", onclick: () => downloadDoc(doc) }, icon("download", 16), t("download")))), { wide: true });
}

export async function downloadDoc(doc) {
  const { url } = await api(`/documents/${doc.id}/link`, { method: "POST", body: {} });
  triggerDownload(url, doc.original_filename);
}

export function uploadButtons(onDone, { compact = false, waOnly = false } = {}) {
  const input = h("input", { type: "file", multiple: true, accept: "application/pdf,image/*,.heic,.heif,.avif,.txt", class: "visually-hidden",
    onchange: async () => {
      if (!input.files.length) return;
      const fd = new FormData();
      for (const f of input.files) fd.append("files", f);
      btn.disabled = true; btn.replaceChildren(spinner(), t("uploading"));
      try {
        const r = await api("/documents", { method: "POST", form: fd });
        toast(t("files_added", { n: r.documents.length }), "ok");
        for (const e of r.errors || []) toast(`${e.filename}: ${errText(e.error)}`, "bad");
        onDone?.(r.documents);
      } catch (e) { toast(errText(e.code), "bad"); }
      finally { btn.disabled = false; btn.replaceChildren(icon("upload", 18), t("upload")); input.value = ""; }
    } });
  const zip = h("input", { type: "file", accept: ".zip,application/zip", class: "visually-hidden",
    onchange: async () => {
      if (!zip.files.length) return;
      const fd = new FormData(); fd.append("file", zip.files[0]);
      try {
        const r = await api("/import/whatsapp", { method: "POST", form: fd });
        toast(t("wa_imported", { n: r.imported.length }), "ok");
        onDone?.();
      } catch (e) { toast(errText(e.code), "bad"); }
      zip.value = "";
    } });
  const btn = h("button", { class: "btn primary", onclick: () => input.click() }, icon("upload", 18), t("upload"));
  const waBtn = h("button", { class: "btn ghost", onclick: () => zip.click() }, icon("msg", 18), compact ? "" : t("import_wa"));
  if (compact) waBtn.setAttribute("aria-label", t("import_wa"));
  if (waOnly) { waBtn.className = "btn ghost sm"; return h("div", { class: "row" }, waBtn, zip); }
  return h("div", { class: "row wrap" }, btn, waBtn, input, zip);
}

export function categoryIcon(key) {
  return categoryOf(key)?.icon || "folder";
}

export async function categorySelect(value) {
  const cats = await loadCategories();
  return h("select", { name: "category_key" }, cats.map((c) => h("option", { value: c.key, selected: c.key === value }, L(c.name))));
}

export function docTypeSelect(value, { includeUnknown = true } = {}) {
  const lang = getLang();
  const entries = Object.entries(store.meta.doc_types).sort((a, b) => a[1][lang].localeCompare(b[1][lang], lang));
  return h("select", { name: "doc_type" },
    includeUnknown ? h("option", { value: "unknown", selected: value === "unknown" }, t("unknown_type")) : null,
    entries.map(([k, v]) => h("option", { value: k, selected: k === value }, v[lang])));
}
