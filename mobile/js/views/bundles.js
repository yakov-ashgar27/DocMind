import { api, canShareFiles, shareFiles, triggerDownload } from "../api.js";
import { docMeta, freshnessBadge, openPreview, thumb } from "../components.js";
import { fmtDate, getLang, t, errText } from "../i18n.js";
import { navigate } from "../router.js";
import { docTypeLabel, store } from "../store.js";
import { clear, confirmDialog, emptyState, h, icon, sheet, spinner, toast } from "../ui.js";

export async function bundlesView(root) {
  const { bundles } = await api("/bundles");
  root.append(h("div", { class: "page-head" }, h("h1", {}, t("bundles")),
    h("button", { class: "btn primary sm", onclick: newBundle }, icon("plus", 16), t("bundle_new"))));
  if (!bundles.length) {
    root.append(emptyState(getLang() === "he"
      ? "תיק מסמכים נוצר מתוך שיחה עם העוזר (“יצירת תיק מסמכים”) או ידנית."
      : "Bundles are created from an assistant answer (“Create bundle”) or manually.",
      h("button", { class: "btn ghost", onclick: () => navigate("/assistant") }, icon("chat", 16), t("nav_assistant"))));
    return;
  }
  root.append(h("div", { class: "list" }, bundles.map((b) =>
    h("button", { class: "list-item", onclick: () => navigate(`/bundle/${b.id}`) },
      h("div", { class: "thumb sm" }, icon("layers", 20)),
      h("div", { class: "doc-main" }, h("div", { class: "doc-title" }, b.name),
        h("div", { class: "meta" }, `${b.ready}/${b.items} · ${fmtDate(b.updated_at)}`),
        h("div", { class: "progress" }, h("span", { style: { width: `${b.items ? (100 * b.ready) / b.items : 0}%` } }))),
      icon("chevron", 16)))));
}

async function newBundle() {
  const input = h("input", { placeholder: t("bundle_name"), required: true });
  const s = sheet(t("bundle_new"), h("form", { class: "form", onsubmit: async (e) => {
    e.preventDefault();
    const { bundle } = await api("/bundles", { method: "POST", body: { name: input.value, items: [] } });
    s.close();
    navigate(`/bundle/${bundle.id}`);
  } }, input, h("button", { class: "btn primary" }, t("save"))));
  input.focus();
}

export async function bundleView(root, params) {
  let b = (await api(`/bundles/${params.id}`)).bundle;
  const lang = getLang();
  const body = h("div");
  root.append(h("div", { class: "page-head" }, h("button", { class: "btn ghost sm", onclick: () => navigate("/bundles") }, t("back"))), body);

  function render() {
    clear(body);
    const name = h("input", { class: "title-input", value: b.name, "aria-label": t("bundle_name"),
      onchange: async () => { b = (await api(`/bundles/${b.id}`, { method: "PATCH", body: { name: name.value } })).bundle; toast(t("saved"), "ok"); } });
    const selected = b.items.filter((i) => i.selected && i.document?.is_local);
    const progress = h("div", { class: "meta" });
    const dlBtn = h("button", { class: "btn primary", disabled: !selected.length, onclick: async () => {
      dlBtn.disabled = true;
      const { links } = await api(`/bundles/${b.id}/links`, { method: "POST", body: {} });
      // Separate original files, one after another (no ZIP).
      for (let i = 0; i < links.length; i++) {
        progress.textContent = t("downloading", { i: i + 1, n: links.length });
        triggerDownload(links[i].url, links[i].filename);
        await new Promise((r) => setTimeout(r, 700));
      }
      progress.textContent = "";
      dlBtn.disabled = false;
    } }, icon("download", 18), t("download_selected", { n: selected.length }));
    body.append(
      name,
      h("div", { class: "meta muted" }, `${b.items.filter((i) => i.document).length}/${b.items.length} · ${fmtDate(b.updated_at)}`),
      h("div", { class: "bundle-items" }, b.items.map(itemRow)),
      h("button", { class: "btn ghost add-item", onclick: () => pickDocument(null) }, icon("plus", 16), t("add_item")),
      h("div", { class: "download-bar" }, dlBtn,
        "share" in navigator ? h("button", { class: "btn ghost", disabled: !selected.length, onclick: async (e) => {
          e.currentTarget.disabled = true;
          const { links } = await api(`/bundles/${b.id}/links`, { method: "POST", body: {} });
          const files = links.map((l) => l.file);
          if (canShareFiles(files)) await shareFiles(files, b.name);
          else for (const l of links) { triggerDownload(l.url, l.filename); await new Promise((r) => setTimeout(r, 700)); }
          e.currentTarget.disabled = false;
        } }, icon("send", 17), t("share_all", { n: selected.length })) : null,
        h("button", { class: "btn ghost sm", disabled: !selected.length, onclick: async () => {
          const r = await api(`/bundles/${b.id}/combined-link`, { method: "POST" });
          if (r.file && canShareFiles([r.file]) && matchMedia("(pointer: coarse)").matches) await shareFiles([r.file], r.filename);
          else triggerDownload(r.url, r.filename);
        } }, t("combined_pdf")), progress),
      h("div", { class: "row end" }, h("button", { class: "btn danger sm", onclick: async () => {
        if (await confirmDialog(lang === "he" ? "למחוק את התיק? המסמכים עצמם יישארו בספרייה." : "Delete this bundle? The documents stay in your library.")) {
          await api(`/bundles/${b.id}`, { method: "DELETE" });
          navigate("/bundles");
        }
      } }, icon("trash", 16), t("delete"))));
  }

  function itemRow(it) {
    const d = it.document;
    const patch = async (p) => { b = (await api(`/bundles/${b.id}/items/${it.id}`, { method: "PATCH", body: p })).bundle; render(); };
    const check = h("input", { type: "checkbox", checked: it.selected && !!d?.is_local, disabled: !d?.is_local, "aria-label": it.label,
      onchange: () => patch({ selected: check.checked }) });
    const row = h("div", { class: "bundle-item" + (d ? "" : " missing") }, check);
    if (d?.locked) {
      row.append(thumb(d, "sm"), h("div", { class: "doc-main" }, h("div", { class: "req-label" }, it.label),
        h("button", { class: "linkish", onclick: () => import("../vault.js").then((v) => v.unlockAndRefresh()) }, icon("lock", 14), " ", t("locked_hint"))));
    } else if (d) {
      const fname = h("input", { class: "fname", dir: "ltr", value: it.download_filename, "aria-label": t("rename_file"),
        onchange: () => patch({ custom_filename: fname.value }) });
      row.append(thumb(d, "sm"), h("div", { class: "doc-main" },
        h("div", { class: "req-label" }, it.label),
        fname,
        h("div", { class: "badges" }, freshnessBadge(d.freshness), d.is_local ? null : h("span", { class: "badge warn" }, t("not_local")))),
        h("div", { class: "row tight" },
          h("button", { class: "icon-btn", "aria-label": t("preview"), onclick: () => openPreview(d) }, icon("eye", 18)),
          h("button", { class: "icon-btn", "aria-label": t("download"), disabled: !d.is_local, onclick: async () => {
            const { links } = await api(`/bundles/${b.id}/links`, { method: "POST", body: { item_ids: [it.id] } });
            if (links[0]) triggerDownload(links[0].url, links[0].filename);
          } }, icon("download", 18)),
          h("button", { class: "icon-btn", "aria-label": t("remove"), onclick: async () => {
            b = (await api(`/bundles/${b.id}/items/${it.id}`, { method: "DELETE" })).bundle; render();
          } }, icon("x", 18))));
    } else {
      row.append(h("div", { class: "thumb sm" }, icon("alert", 20)), h("div", { class: "doc-main" },
        h("div", { class: "req-label" }, it.label),
        h("button", { class: "linkish", onclick: () => pickDocument(it) }, t("missing_doc"))),
        h("button", { class: "icon-btn", "aria-label": t("remove"), onclick: async () => {
          b = (await api(`/bundles/${b.id}/items/${it.id}`, { method: "DELETE" })).bundle; render();
        } }, icon("x", 18)));
    }
    return row;
  }

  async function pickDocument(item) {
    const { documents } = await api("/documents", { query: item?.doc_type ? { doc_type: item.doc_type } : {} });
    let docs = documents;
    if (item?.doc_type && !docs.length) docs = (await api("/documents")).documents;
    const s = sheet(t("choose_doc"), h("div", { class: "doc-list" }, docs.length ? docs.map((d) =>
      h("button", { class: "doc-card", onclick: async () => {
        s.close();
        if (item) b = (await api(`/bundles/${b.id}/items/${item.id}`, { method: "PATCH", body: { document_id: d.id } })).bundle;
        else b = (await api(`/bundles/${b.id}/items`, { method: "POST", body: { label: docTypeLabel(d.doc_type, lang) === docTypeLabel("x", lang) ? d.display_name : docTypeLabel(d.doc_type, lang), doc_type: d.doc_type, document_id: d.id } })).bundle;
        render();
      } }, thumb(d), h("div", { class: "doc-main" }, h("div", { class: "doc-title" }, d.display_name), docMeta(d)))) : emptyState(t("empty_library"))));
  }
  render();
}
