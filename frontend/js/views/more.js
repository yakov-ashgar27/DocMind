import { api, lockVault, logout, triggerDownload, vaultUnlocked } from "../api.js";
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
      action = h("div", { class: "col tight" },
        h("button", { class: "btn primary sm", onclick: async (e) => {
          e.currentTarget.disabled = true;
          try { const r = await api(`/connectors/${c.key}/sync`, { method: "POST" }); toast(t("synced", { n: r.indexed }), "ok"); navigate("/accounts?r=" + Date.now()); }
          catch (err) { toast(errText(err.code), "bad"); e.currentTarget.disabled = false; }
        } }, t("sync_now")),
        h("button", { class: "btn ghost sm", onclick: async () => { await api(`/connectors/${c.key}`, { method: "DELETE" }); navigate("/accounts?r=" + Date.now()); } }, t("disconnect")));
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
          c.last_synced_at ? h("span", { class: "meta muted" }, t("last_synced", { d: fmtDate(c.last_synced_at) })) : null),
        explain ? h("p", { class: "meta muted" }, explain) : null),
      action));
  }
  root.append(list);
}

export async function categoriesView(root) {
  const cats = await loadCategories(true);
  const v = await api("/vault");
  const locked = new Set(v.locked_categories);
  const toggleLock = async (key, e) => {
    e.stopPropagation();
    const next = new Set(locked);
    next.has(key) ? next.delete(key) : next.add(key);
    try { await api("/vault/categories", { method: "PUT", body: { categories: [...next] } }); navigate("/categories?r=" + Date.now()); }
    catch (err) { if (err.code !== "vault_locked") toast(errText(err.code), "bad"); }
  };
  const input = h("input", { placeholder: t("new_category") });
  root.append(h("div", { class: "page-head" }, h("h1", {}, t("categories"))),
    !v.has_pin ? h("button", { class: "card notice", onclick: () => navigate("/settings") }, icon("lock", 18), h("span", {}, t("set_pin")), icon("chevron", 16)) : null,
    h("div", { class: "cat-grid" }, cats.map((c) => h("div", { class: "cat", role: "button", tabindex: 0,
      onclick: () => navigate(`/library?category=${encodeURIComponent(c.key)}`),
      onkeydown: (e) => { if (e.key === "Enter") navigate(`/library?category=${encodeURIComponent(c.key)}`); } },
      icon(c.icon, 22), h("strong", {}, L(c.name)), h("span", { class: "meta" }, String(c.count)),
      v.has_pin ? h("button", { class: "lock-toggle" + (locked.has(c.key) ? " on" : ""), "aria-pressed": locked.has(c.key) ? "true" : "false",
        "aria-label": `${t("protected")}: ${L(c.name)}`, onclick: (e) => toggleLock(c.key, e) },
        icon(locked.has(c.key) ? "lock" : "unlock", 14), locked.has(c.key) ? t("protected") : "") : null,
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
    await vaultSection(),
    mfaSection(user),
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


async function vaultSection() {
  const v = await api("/vault");
  const box = h("section", { class: "card settings" }, h("h2", {}, icon("lock", 16), " ", t("vault")),
    h("p", { class: "meta muted" }, t("vault_desc")));
  if (!v.has_pin) {
    box.append(h("button", { class: "btn primary", onclick: () => pinDialog(false) }, icon("lock", 16), t("set_pin")));
    return box;
  }
  const cats = await loadCategories();
  box.append(h("div", { class: "setting" }, h("div", { class: "doc-main" }, h("div", { class: "doc-title" }, t("protected_folders")),
    h("div", { class: "meta" }, cats.filter((c) => v.locked_categories.includes(c.key)).map((c) => L(c.name)).join(" · ") || "—")),
    h("button", { class: "btn ghost sm", onclick: () => navigate("/categories") }, t("edit"))));
  box.append(h("div", { class: "row wrap" },
    vaultUnlocked() ? h("button", { class: "btn ghost sm", onclick: () => { lockVault(); render(); } }, icon("lock", 15), t("lock_now")) : null,
    h("button", { class: "btn ghost sm", onclick: () => pinDialog(true) }, t("change_pin")),
    h("button", { class: "btn ghost sm", onclick: removePin }, t("remove_pin"))));
  return box;
}

function pinDialog(changing) {
  const pw = h("input", { type: "password", placeholder: t("password"), autocomplete: "current-password", required: true });
  const p1 = h("input", { type: "password", inputmode: "numeric", placeholder: t("pin"), autocomplete: "new-password", required: true });
  const p2 = h("input", { type: "password", inputmode: "numeric", placeholder: t("pin_confirm"), autocomplete: "new-password", required: true });
  const err = h("p", { class: "form-error", role: "alert" });
  const s = sheet(changing ? t("change_pin") : t("set_pin"), h("form", { class: "form", onsubmit: async (e) => {
    e.preventDefault(); err.textContent = "";
    if (p1.value !== p2.value) { err.textContent = t("pin_mismatch"); return; }
    try {
      await api("/vault/pin", { method: "POST", body: { password: pw.value, pin: p1.value } });
      lockVault(); s.close(); toast(t("saved"), "ok"); render();
    } catch (ex) { err.textContent = errText(ex.code); }
  } }, h("p", { class: "meta muted" }, t("vault_desc")), pw, p1, p2, err, h("button", { class: "btn primary" }, t("save"))));
}

function removePin() {
  const pw = h("input", { type: "password", placeholder: t("password"), autocomplete: "current-password", required: true });
  const err = h("p", { class: "form-error", role: "alert" });
  const s = sheet(t("remove_pin"), h("form", { class: "form", onsubmit: async (e) => {
    e.preventDefault();
    try { await api("/vault/pin", { method: "DELETE", body: { password: pw.value } }); lockVault(); s.close(); render(); }
    catch (ex) { err.textContent = errText(ex.code); }
  } }, pw, err, h("button", { class: "btn danger" }, t("remove_pin"))));
}

function mfaSection(user) {
  const box = h("section", { class: "card settings" }, h("h2", {}, icon("shield", 16), " ", t("mfa")),
    h("p", { class: "meta muted" }, t("mfa_desc")));
  if (user.mfa_enabled) {
    box.append(h("div", { class: "row between" }, h("span", { class: "badge ok" }, icon("check", 13), t("mfa_on")),
      h("button", { class: "btn ghost sm", onclick: disableMfa }, t("disable"))));
  } else {
    box.append(h("button", { class: "btn primary", onclick: enableMfa }, icon("shield", 16), t("enable")));
  }
  return box;
}

function enableMfa() {
  const pw = h("input", { type: "password", placeholder: t("password"), autocomplete: "current-password", required: true });
  const err = h("p", { class: "form-error", role: "alert" });
  const body = h("div", { class: "stack" });
  const s = sheet(t("mfa"), body);
  body.append(h("form", { class: "form", onsubmit: async (e) => {
    e.preventDefault();
    try {
      const setup = await api("/me/2fa/setup", { method: "POST", body: { password: pw.value } });
      step2(setup);
    } catch (ex) { err.textContent = errText(ex.code); }
  } }, pw, err, h("button", { class: "btn primary" }, t("enable"))));

  function step2(setup) {
    const code = h("input", { inputmode: "numeric", autocomplete: "one-time-code", class: "pin-input", required: true, "aria-label": t("code") });
    const err2 = h("p", { class: "form-error", role: "alert" });
    clear(body).append(
      h("p", {}, t("mfa_step1")),
      h("a", { class: "btn ghost", href: setup.otpauth_uri }, icon("link", 15), t("open_auth_app")),
      h("p", { class: "meta muted" }, t("setup_key")),
      h("code", { class: "secret", dir: "ltr" }, setup.secret.replace(/(.{4})/g, "$1 ").trim()),
      h("p", {}, t("mfa_step2")),
      h("form", { class: "form", onsubmit: async (e) => {
        e.preventDefault();
        try {
          const r = await api("/me/2fa/enable", { method: "POST", body: { code: code.value } });
          clear(body).append(h("p", {}, t("recovery")),
            h("div", { class: "recovery", dir: "ltr" }, r.recovery_codes.map((c) => h("code", {}, c))),
            h("button", { class: "btn primary", onclick: () => { s.close(); render(); } }, t("done")));
        } catch (ex) { err2.textContent = errText(ex.code); }
      } }, code, err2, h("button", { class: "btn primary" }, t("verify"))));
    code.focus();
  }
}

function disableMfa() {
  const pw = h("input", { type: "password", placeholder: t("password"), autocomplete: "current-password", required: true });
  const code = h("input", { inputmode: "numeric", placeholder: t("code"), autocomplete: "one-time-code", required: true });
  const err = h("p", { class: "form-error", role: "alert" });
  const s = sheet(t("mfa"), h("form", { class: "form", onsubmit: async (e) => {
    e.preventDefault();
    try { await api("/me/2fa/disable", { method: "POST", body: { password: pw.value, code: code.value } }); s.close(); render(); }
    catch (ex) { err.textContent = errText(ex.code); }
  } }, pw, code, err, h("button", { class: "btn danger" }, t("disable"))));
}
