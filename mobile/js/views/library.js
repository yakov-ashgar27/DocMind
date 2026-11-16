import { api, dropThumb, triggerDownload } from "../api.js";
import { categorySelect, docCard, docMeta, docTypeSelect, downloadDoc, openPreview, sourceLabel, thumb, uploadButtons } from "../components.js";
import { fmtDate, getLang, L, t, errText } from "../i18n.js";
import { navigate } from "../router.js";
import { docTypeLabel, loadCategories } from "../store.js";
import { clear, confirmDialog, emptyState, fileSize, h, icon, spinner, toast } from "../ui.js";

export async function libraryView(root, params, query) {
  const cats = await loadCategories(true);
  let category = query.get("category") || "";
  let q = query.get("q") || "";
  const list = h("div", { class: "doc-list" });
  const search = h("input", { type: "search", class: "search-input", placeholder: t("search_docs"), value: q, "aria-label": t("search_docs"),
    oninput: debounce(() => { q = search.value; load(); }, 250) });
  const chips = h("div", { class: "chips scroll" });

  function renderChips() {
    clear(chips);
    chips.append(h("button", { class: "chip" + (!category ? " active" : ""), onclick: () => { category = ""; renderChips(); load(); } }, t("all")));
    for (const c of cats.filter((c) => c.count || c.key === category)) {
      chips.append(h("button", { class: "chip" + (category === c.key ? " active" : ""), onclick: () => { category = c.key; renderChips(); load(); } },
        icon(c.icon, 14), L(c.name), h("span", { class: "count" }, String(c.count))));
    }
  }

  let poll;
  async function load() {
    clearTimeout(poll);
    const { documents } = await api("/documents", { query: { q, category } });
    clear(list);
    if (!documents.length) list.append(emptyState(q || category ? "—" : t("empty_library")));
    for (const d of documents) list.append(docCard(d, { onClick: () => navigate(`/doc/${d.id}`) }));
    if (documents.some((d) => d.status === "processing")) poll = setTimeout(() => location.hash.startsWith("#/library") && load(), 2000);
  }

  root.append(
    h("div", { class: "page-head" }, h("h1", {}, t("nav_library")), uploadButtons(() => { loadCategories(true).then((c) => { cats.splice(0, cats.length, ...c); renderChips(); }); load(); }, { compact: true })),
    h("div", { class: "search-wrap" }, icon("search", 18), search),
    chips, list);
  renderChips();
  await load();
}

function debounce(fn, ms) { let tm; return (...a) => { clearTimeout(tm); tm = setTimeout(() => fn(...a), ms); }; }

export async function documentView(root, params) {
  const lang = getLang();
  let data;
  try { data = await api(`/documents/${params.id}`); } catch { root.append(emptyState(t("error"))); return; }
  const d = data.document;
  const form = h("form", { class: "form", onsubmit: async (e) => {
    e.preventDefault();
    const fd = new FormData(form);
    const body = {
      display_name: fd.get("display_name"), doc_type: fd.get("doc_type"), category_key: fd.get("category_key"),
      issuer: fd.get("issuer"), doc_date: fd.get("doc_date") || null, expiry_date: fd.get("expiry_date") || null,
      tags: String(fd.get("tags") || "").split(",").map((s) => s.trim()).filter(Boolean),
    };
    if (body.doc_type === d.doc_type) delete body.doc_type;  // only a real change counts as a correction
    try { await api(`/documents/${d.id}`, { method: "PATCH", body }); toast(t("saved"), "ok"); }
    catch (err) { toast(errText(err.code), "bad"); }
  } },
    field(t("name"), h("input", { name: "display_name", value: d.display_name, required: true })),
    h("div", { class: "grid2" },
      field(t("doc_type"), docTypeSelect(d.doc_type)),
      field(t("category"), await categorySelect(d.category_key))),
    h("div", { class: "grid2" },
      field(t("doc_date"), h("input", { type: "date", name: "doc_date", value: d.doc_date || "" })),
      field(t("expiry"), h("input", { type: "date", name: "expiry_date", value: d.expiry_date || "" }))),
    field(t("issuer"), h("input", { name: "issuer", value: d.issuer || "" })),
    field(`${t("tags")} (${t("tags_hint")})`, h("input", { name: "tags", value: (d.tags || []).join(", ") })),
    h("button", { class: "btn primary", type: "submit" }, t("save")));

  const top = h("div", { class: "doc-hero" }, thumb(d, "lg"),
    h("div", { class: "doc-main" },
      h("h1", { class: "doc-h1", dir: "auto" }, d.display_name),
      docMeta(d),
      h("div", { class: "meta muted" }, `${sourceLabel(d.source_kind)} · ${d.original_filename} · ${fileSize(d.size_bytes)} · ${t("added")} ${fmtDate(d.created_at)}`),
      d.doc_type_source === "auto" && d.status === "ready" && d.doc_type !== "unknown"
        ? h("div", { class: "meta muted" }, `${Math.round(d.doc_type_confidence * 100)}% · auto`) : null,
      h("div", { class: "row wrap" },
        h("button", { class: "btn primary sm", onclick: () => openPreview(d) }, icon("eye", 16), t("preview")),
        h("button", { class: "btn ghost sm", onclick: () => downloadDoc(d) }, icon("download", 16), t("download")),
        d.expiry_date ? h("button", { class: "btn ghost sm", title: t("calendar_hint"), onclick: async () => {
          const { url } = await api("/reminders/calendar-link", { method: "POST", body: { document_ids: [d.id] } });
          triggerDownload(url, "docmind-reminder.ics");
        } }, icon("clock", 16), t("add_to_calendar")) : null)));

  root.append(h("div", { class: "page-head" }, h("button", { class: "btn ghost sm", onclick: () => history.back() }, t("back"))), top);

  if (data.duplicate_of) {
    const act = async (action) => { await api(`/documents/${d.id}/duplicate`, { method: "POST", body: { action } }); navigate(`/doc/${d.id}`); };
    root.append(h("div", { class: "card notice warn" },
      h("p", {}, t("dup_of", { name: data.duplicate_of.display_name })),
      h("div", { class: "row wrap" },
        h("button", { class: "btn ghost sm", onclick: () => navigate(`/doc/${data.duplicate_of.id}`) }, t("preview")),
        h("button", { class: "btn ghost sm", onclick: () => act("keep_both") }, t("keep_both")),
        h("button", { class: "btn ghost sm", onclick: () => act("archive_this") }, t("archive_copy")))));
  }
  root.append(h("section", { class: "card" }, form));
  root.append(h("details", { class: "card text-card" }, h("summary", {}, icon("shield", 16), t("extracted_text")),
    h("pre", { dir: "auto" }, data.text_excerpt || "—")));
  root.append(h("div", { class: "row wrap danger-zone" },
    h("button", { class: "btn ghost sm", onclick: async () => { dropThumb(d.id); await api(`/documents/${d.id}/reprocess`, { method: "POST" }); toast(t("processing")); setTimeout(() => navigate(`/doc/${d.id}`), 1500); } }, t("reprocess")),
    h("button", { class: "btn ghost sm", onclick: async () => { await api(`/documents/${d.id}`, { method: "PATCH", body: { archived: !d.archived } }); history.back(); } }, d.archived ? t("unarchive") : t("archive")),
    h("button", { class: "btn danger sm", onclick: async () => {
      if (await confirmDialog(t("confirm_delete_doc"))) {
        await api(`/documents/${d.id}`, { method: "DELETE", body: { confirm: true } });
        navigate("/library");
      }
    } }, icon("trash", 16), t("delete"))));
}

function field(label, input) {
  return h("label", { class: "field" }, h("span", {}, label), input);
}
