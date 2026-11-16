import { api, logout, triggerDownload } from "../api.js";
import { uploadButtons } from "../components.js";
import { fmtDate, getLang, L, setLang, t, errText } from "../i18n.js";
import { navigate, render } from "../router.js";
import { loadCategories, store } from "../store.js";
import { clear, confirmDialog, h, icon, sheet, toast } from "../ui.js";

export async function moreView(root) {
  const items = [
    ["/memory", "brain", t("memory")], ["/accounts", "link", t("accounts")], ["/categories", "folder", t("categories")],
    ["/settings", "settings", t("settings")],
  ];
  root.append(h("div", { class: "page-head" }, h("h1", {}, t("more"))),
    h("div", { class: "list" }, items.map(([href, ic, label]) =>
      h("button", { class: "list-item", onclick: () => navigate(href) }, icon(ic, 20), h("div", { class: "doc-main" }, h("div", { class: "doc-title" }, label)), icon("chevron", 16)))));
}

const STATE_KIND = { always: "ok", connected: "ok", not_connected: "", not_configured: "warn", requires_native_app: "", reauth_required: "bad" };
const SRC_ICON = { device_files: "phone", gallery: "image", downloads: "folder", whatsapp: "msg", gmail: "mail", gdrive: "cloud" };

export async function accountsView(root, params, query) {
  if (query.get("connected")) toast(`${query.get("connected")} ✓`, "ok");
  if (query.get("error")) toast(errText(query.get("error")), "bad");
  const { connectors } = await api("/connectors");
  root.append(h("div", { class: "page-head" }, h("h1", {}, t("accounts"))), h("p", { class: "muted" }, t("accounts_intro")));
  const list = h("ol", { class: "sources" });
  for (const c of connectors) {
    const explain = c.state === "not_configured" ? t("exp_not_configured") : c.state === "requires_native_app" ? t("exp_native")
      : c.key === "whatsapp" ? t("exp_whatsapp") : null;
    let action = null;
    if (["gmail", "gdrive"].includes(c.key) && ["not_connected", "reauth_required"].includes(c.state)) {
      action = h("button", { class: "btn primary sm", onclick: async () => {
        try { const { auth_url } = await api(`/connectors/${c.key}/connect`, { method: "POST" }); location.href = auth_url; }
        catch (e) { toast(errText(e.code), "bad"); }
      } }, t("connect"));
    } else if (["gmail", "gdrive"].includes(c.key) && c.state === "connected") {
      action = h("button", { class: "btn ghost sm", onclick: async () => { await api(`/connectors/${c.key}`, { method: "DELETE" }); navigate("/accounts"); } }, t("disconnect"));
    } else if (c.key === "whatsapp") {
      action = uploadButtons(() => navigate("/accounts"), { waOnly: true });
    }
    list.append(h("li", { class: "source" },
      h("div", { class: "source-order" }, String(c.order)),
      h("div", { class: "thumb sm" }, icon(SRC_ICON[c.key] || "doc", 20)),
      h("div", { class: "doc-main" },
        h("div", { class: "doc-title" }, L(c.label), c.account ? h("span", { class: "muted" }, ` · ${c.account}`) : null),
        h("div", { class: "row tight" }, h("span", { class: `badge ${STATE_KIND[c.state] || ""}` }, t("s_" + c.state)),
          c.documents !== undefined ? h("span", { class: "meta" }, `${c.documents} ${t("items")}`) : null,
          c.stage > 1 ? h("span", { class: "meta muted" }, `Stage ${c.stage}`) : null),
        explain ? h("p", { class: "meta muted" }, explain) : null),
      action));
  }
  root.append(list);
}

export async function categoriesView(root) {
  const cats = await loadCategories(true);
  const input = h("input", { placeholder: t("new_category") });
  root.append(h("div", { class: "page-head" }, h("h1", {}, t("categories"))),
    h("div", { class: "cat-grid" }, cats.map((c) => h("div", { class: "cat", role: "button", tabindex: 0,
      onclick: () => navigate(`/library?category=${encodeURIComponent(c.key)}`),
      onkeydown: (e) => { if (e.key === "Enter") navigate(`/library?category=${encodeURIComponent(c.key)}`); } },
      icon(c.icon, 22), h("strong", {}, L(c.name)), h("span", { class: "meta" }, String(c.count)),
      c.is_custom ? h("button", { class: "icon-btn cat-del", "aria-label": t("delete"), onclick: async (e) => {
        e.stopPropagation();
        if (await confirmDialog(`${t("delete")}: ${L(c.name)}?`)) { await api(`/categories/${encodeURIComponent(c.key)}`, { method: "DELETE" }); navigate("/categories?r=" + Date.now()); }
      } }, icon("x", 14)) : null))),
    h("form", { class: "row", onsubmit: async (e) => {
      e.preventDefault();
      if (!input.value.trim()) return;
      try { await api("/categories", { method: "POST", body: { name: input.value } }); navigate("/categories?r=" + Date.now()); }
      catch (err) { toast(errText(err.code), "bad"); }
    } }, input, h("button", { class: "btn primary sm" }, icon("plus", 15), t("add"))));
}

export async function settingsView(root) {
  const lang = getLang();
  const { user } = await api("/me");
  const meta = store.meta;
  const s = user.settings || {};
  const update = async (patch) => {
    const r = await api("/me", { method: "PATCH", body: patch });
    store.user = r.user;
    toast(t("saved"), "ok");
  };
  const toggle = (key, value, { disabled = false } = {}) => {
    const el = h("input", { type: "checkbox", role: "switch", checked: !!value, disabled, onchange: () => update({ [key]: el.checked }) });
    return h("label", { class: "switch" }, el, h("span", { class: "slider" }));
  };
  root.append(h("div", { class: "page-head" }, h("h1", {}, t("settings"))),
    h("div", { class: "card notice ok" }, icon("shield", 18), h("span", {}, t("privacy_note"))),
    h("section", { class: "card settings" },
      setting(t("language"), null, h("div", { class: "seg" },
        ["he", "en"].map((l) => h("button", { class: l === lang ? "active" : "", onclick: async () => { setLang(l); await update({ locale: l }); render(); } }, l === "he" ? "עברית" : "English")))),
      setting(t("ai_consent"), meta.llm.available ? t("ai_consent_desc") : t("ai_unavailable"),
        toggle("ai_provider_consent", s.ai_provider_consent, { disabled: !meta.llm.available })),
      setting(t("remember_locations"), null, toggle("remember_locations", s.remember_locations !== false)),
      setting(t("reminder_days"), t("calendar_hint"), h("select", { class: "compact", onchange: (e) => update({ reminder_days: Number(e.target.value) }) },
        [14, 30, 60, 90].map((n) => h("option", { value: n, selected: (s.reminder_days || 60) === n }, t("days", { n }))))),
      setting(t("shared"), t("shared_desc"), toggle("shared_learning_opt_in", s.shared_learning_opt_in, { disabled: !meta.shared_learning_available }))),
    h("section", { class: "card settings" }, h("h2", {}, t("security")),
      h("div", { class: "row wrap" },
        h("button", { class: "btn ghost sm", onclick: changePassword }, t("change_pw")),
        h("button", { class: "btn ghost sm", onclick: showAudit }, t("audit")),
        h("button", { class: "btn ghost sm", onclick: async () => {
          const data = await api("/me/export");
          const url = URL.createObjectURL(new Blob([JSON.stringify(data, null, 2)], { type: "application/json" }));
          triggerDownload(url, "docmind-export.json");
          setTimeout(() => URL.revokeObjectURL(url), 5000);
        } }, t("export")),
        h("button", { class: "btn ghost sm", onclick: async () => { await api("/me/logout-all", { method: "POST" }); await logout(); location.reload(); } }, t("logout_all")),
        h("button", { class: "btn ghost sm", onclick: async () => { await logout(); location.reload(); } }, t("logout")))),
    h("div", { class: "row end danger-zone" }, h("button", { class: "btn danger sm", onclick: deleteAccount }, icon("trash", 16), t("delete_account"))),
    h("p", { class: "meta muted center" }, `${user.email} · ${fmtDate(user.created_at)}`));
}

function setting(title, desc, control) {
  return h("div", { class: "setting" }, h("div", { class: "doc-main" }, h("div", { class: "doc-title" }, title), desc ? h("div", { class: "meta muted" }, desc) : null), control);
}

function changePassword() {
  const cur = h("input", { type: "password", placeholder: t("current_pw"), autocomplete: "current-password", required: true });
  const nw = h("input", { type: "password", placeholder: t("new_pw"), autocomplete: "new-password", required: true });
  const s = sheet(t("change_pw"), h("form", { class: "form", onsubmit: async (e) => {
    e.preventDefault();
    try { await api("/me/password", { method: "POST", body: { current_password: cur.value, new_password: nw.value } }); s.close(); await logout(); location.reload(); }
    catch (err) { toast(errText(err.code), "bad"); }
  } }, cur, nw, h("p", { class: "meta muted" }, t("pw_hint")), h("button", { class: "btn primary" }, t("save"))));
}

async function showAudit() {
  const { events } = await api("/me/audit");
  sheet(t("audit"), h("div", { class: "list" }, events.map((e) => h("div", { class: "list-item static" },
    h("div", { class: "doc-main" }, h("div", { class: "doc-title mono" }, e.action), h("div", { class: "meta" }, `${fmtDate(e.created_at)} ${e.created_at.slice(11, 16)} · ${e.ip || ""}`))))));
}

function deleteAccount() {
  const pw = h("input", { type: "password", placeholder: t("password"), required: true, autocomplete: "current-password" });
  const s = sheet(t("delete_account"), h("form", { class: "form", onsubmit: async (e) => {
    e.preventDefault();
    try { await api("/me", { method: "DELETE", body: { password: pw.value } }); s.close(); await logout(); location.reload(); }
    catch (err) { toast(errText(err.code), "bad"); }
  } }, h("p", {}, t("confirm_delete_account")), pw, h("button", { class: "btn danger" }, t("delete_account"))));
}
