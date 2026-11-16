import { api } from "../api.js";
import { docTypeSelect, sourceLabel } from "../components.js";
import { fmtDate, getLang, t } from "../i18n.js";
import { navigate } from "../router.js";
import { docTypeLabel } from "../store.js";
import { clear, confirmDialog, emptyState, h, icon, toast } from "../ui.js";

export async function memoryView(root) {
  const lang = getLang();
  const body = h("div");
  root.append(h("div", { class: "page-head" }, h("h1", {}, t("memory"))), h("p", { class: "muted" }, t("memory_intro")), body);

  async function load() {
    const m = await api("/memory");
    clear(body);
    if (m.proposals.length) {
      body.append(h("h2", {}, t("pending")), h("div", { class: "list" }, m.proposals.map((p) => h("div", { class: "card proposal" },
        h("div", { class: "proposal-q" }, icon("brain", 18), p.name),
        h("ul", { class: "proposal-items" }, p.items.map((i) => h("li", {}, i.label))),
        h("div", { class: "row" },
          h("button", { class: "btn primary sm", onclick: async () => { await api(`/memory/proposals/${p.id}`, { method: "POST", body: { accept: true } }); load(); } }, t("remember")),
          h("button", { class: "btn ghost sm", onclick: async () => { await api(`/memory/proposals/${p.id}`, { method: "POST", body: { accept: false } }); load(); } }, t("not_now")))))));
    }
    body.append(h("h2", {}, t("checklists")));
    if (!m.checklists.length) body.append(emptyState(lang === "he"
      ? "עדיין אין רשימות שמורות. כשתכין/י מסמכים למשימה, אציע לזכור את הרשימה."
      : "No saved checklists yet. When you prepare documents for a task, I'll offer to remember the list."));
    for (const c of m.checklists) body.append(checklistCard(c, load));

    const locs = m.facts.filter((f) => f.kind === "doc_location");
    if (locs.length) {
      body.append(h("h2", {}, t("locations")), h("div", { class: "list" }, locs.map((f) => h("div", { class: "list-item static" },
        icon("folder", 18), h("div", { class: "doc-main" }, h("div", { class: "doc-title" }, docTypeLabel(f.key, lang)),
          h("div", { class: "meta" }, `${sourceLabel(f.value.source)} · ${fmtDate(f.updated_at)}`)),
        h("button", { class: "icon-btn", "aria-label": t("delete"), onclick: async () => { await api(`/memory/facts/${f.id}`, { method: "DELETE" }); load(); } }, icon("trash", 16))))));
    }
    body.append(h("div", { class: "row end danger-zone" }, h("button", { class: "btn danger sm", onclick: async () => {
      if (await confirmDialog(t("confirm_wipe"))) { await api("/memory", { method: "DELETE", body: { confirm: true } }); load(); }
    } }, icon("trash", 16), t("wipe_memory"))));
  }
  await load();
}

function checklistCard(c, reload) {
  const lang = getLang();
  let editing = false;
  let items = c.items.map((i) => ({ ...i }));
  const card = h("div", { class: "card checklist" });
  function render() {
    clear(card);
    const nameEl = editing ? h("input", { class: "title-input sm", value: c.name }) : h("h3", {}, c.name);
    card.append(h("div", { class: "row between" }, nameEl,
      h("div", { class: "row tight" },
        !editing ? h("button", { class: "btn ghost sm", onclick: () => navigate(`/assistant?new=1&q=${encodeURIComponent(c.name)}`) }, icon("chat", 15), lang === "he" ? "להתחיל" : "Start") : null,
        h("button", { class: "btn ghost sm", onclick: async () => {
          if (editing) {
            await api(`/memory/checklists/${c.id}`, { method: "PATCH", body: { name: nameEl.value, items } });
            toast(t("saved"), "ok");
            return reload();
          }
          editing = true; render();
        } }, editing ? t("save") : t("edit")))));
    card.append(h("div", { class: "meta" }, `v${c.version} · ${t("used_times", { n: c.use_count })} · ${fmtDate(c.last_used_at || c.updated_at)}`));
    const ul = h("ul", { class: "check-items" });
    items.forEach((it, idx) => ul.append(h("li", {}, icon("check", 15), h("span", {}, it.label),
      editing ? h("button", { class: "icon-btn", "aria-label": t("remove"), onclick: () => { items.splice(idx, 1); render(); } }, icon("x", 15)) : null)));
    card.append(ul);
    if (editing) {
      const sel = docTypeSelect(null, { includeUnknown: false });
      card.append(h("div", { class: "row" }, sel, h("button", { class: "btn ghost sm", onclick: () => {
        if (!items.some((i) => i.doc_type === sel.value)) items.push({ doc_type: sel.value, label: docTypeLabel(sel.value, lang) });
        render();
      } }, icon("plus", 15), t("add"))),
      h("div", { class: "row end" }, h("button", { class: "btn danger sm", onclick: async () => {
        if (await confirmDialog(`${t("delete")}: ${c.name}?`)) { await api(`/memory/checklists/${c.id}`, { method: "DELETE" }); reload(); }
      } }, icon("trash", 15), t("delete"))));
    }
  }
  render();
  return card;
}
