// Phone edition: More, Sources, Categories, Settings (passcode, vault, backup, data).
import { api, canShareFiles, lockVault, shareFiles, triggerDownload, vaultUnlocked } from "../api.js";
import { uploadButtons } from "../components.js";
import * as backup from "../core/backup.js";
import * as db from "../core/db.js";
import * as V from "../core/vault.js";
import * as native from "../native.js";
import * as scanner from "../core/scanner.js";
import { errText, fmtDate, L, setLang, t } from "../i18n.js";
import { navigate, render } from "../router.js";
import { loadCategories, store } from "../store.js";
import { clear, confirmDialog, h, icon, sheet, toast } from "../ui.js";

export async function moreView(root) {
  const items = [["/memory", "brain", t("memory")], ["/accounts", "link", t("accounts")], ["/categories", "folder", t("categories")], ["/settings", "settings", t("settings")]];
  root.append(h("div", { class: "page-head" }, h("h1", {}, t("more"))),
    h("div", { class: "list" }, items.map(([href, ic, label]) =>
      h("button", { class: "list-item", onclick: () => navigate(href) }, icon(ic, 20), h("div", { class: "doc-main" }, h("div", { class: "doc-title" }, label)), icon("chevron", 16)))),
    h("button", { class: "btn ghost block lock-btn", onclick: () => import("../app.js").then((m) => m.lockScreen()) }, icon("lock", 16), t("lock_app")));
}

const STATE_KIND = { always: "ok", connected: "ok", not_connected: "", server_version_only: "" };
const SRC_ICON = { device_files: "phone", whatsapp: "msg", gmail: "mail", gdrive: "cloud" };

export async function accountsView(root) {
  if (native.isNative) return nativeSourcesView(root);
  const { connectors } = await api("/connectors");
  root.append(h("div", { class: "page-head" }, h("h1", {}, t("accounts"))), h("p", { class: "muted" }, t("accounts_intro")));
  const list = h("ol", { class: "sources" });
  for (const c of connectors) {
    const explain = c.key === "device_files" ? t("exp_device") : c.key === "whatsapp" ? t("exp_whatsapp") : t("exp_server_only");
    const action = c.key === "whatsapp" ? uploadButtons(() => navigate("/accounts?r=" + Date.now()), { waOnly: true })
      : c.key === "device_files" ? uploadButtons(() => navigate("/accounts?r=" + Date.now()), { compact: true }).firstChild : null;
    list.append(h("li", { class: "source" },
      h("div", { class: "source-order" }, String(c.order)),
      h("div", { class: "thumb sm" }, icon(SRC_ICON[c.key] || "doc", 20)),
      h("div", { class: "doc-main" },
        h("div", { class: "doc-title" }, L(c.label)),
        h("div", { class: "row tight" }, h("span", { class: `badge ${STATE_KIND[c.state] || ""}` }, t("s_" + c.state)),
          c.documents !== undefined ? h("span", { class: "meta" }, `${c.documents} ${t("items")}`) : null),
        h("p", { class: "meta muted" }, explain)),
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
      onclick: () => navigate(`/library?category=${encodeURIComponent(c.key)}`) },
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
  const { user } = await api("/me");
  const s = user.settings || {};
  const update = async (patch) => { store.user = (await api("/me", { method: "PATCH", body: patch })).user; toast(t("saved"), "ok"); };
  const toggle = (key, value) => {
    const el = h("input", { type: "checkbox", role: "switch", checked: !!value, onchange: () => update({ [key]: el.checked }) });
    return h("label", { class: "switch" }, el, h("span", { class: "slider" }));
  };
  const select = (key, opts, val, fmt) => h("select", { class: "compact", onchange: (e) => update({ [key]: Number(e.target.value) }) },
    opts.map((n) => h("option", { value: n, selected: val === n }, fmt(n))));
  root.append(h("div", { class: "page-head" }, h("h1", {}, t("settings"))),
    h("div", { class: "card notice ok" }, icon("shield", 18), h("span", {}, t("privacy_note"))),
    h("section", { class: "card settings" },
      setting(t("name"), null, h("input", { class: "compact", value: user.display_name || "", onchange: (e) => update({ display_name: e.target.value }) })),
      setting(t("language"), null, h("div", { class: "seg" }, ["he", "en"].map((l) => h("button", { class: l === user.locale ? "active" : "",
        onclick: async () => { setLang(l); await update({ locale: l }); render(); } }, l === "he" ? "עברית" : "English")))),
      setting(t("remember_locations"), null, toggle("remember_locations", s.remember_locations !== false)),
      setting(t("reminder_days"), t("calendar_hint"), select("reminder_days", [14, 30, 60, 90], s.reminder_days || 60, (n) => t("days", { n })))),
    await vaultSection(),
    backupSection(),
    h("section", { class: "card settings" }, h("h2", {}, icon("lock", 16), " ", t("security")),
      setting(t("auto_lock"), null, h("select", { class: "compact", onchange: (e) => update({ auto_lock_minutes: Number(e.target.value) }) },
        [1, 5, 10, 30].map((n) => h("option", { value: n, selected: (s.auto_lock_minutes || 10) === n }, t("minutes", { n }))))),
      h("div", { class: "row wrap" },
        h("button", { class: "btn ghost sm", onclick: changePasscode }, t("change_passcode")),
        h("button", { class: "btn ghost sm", onclick: () => import("../app.js").then((m) => m.lockScreen()) }, icon("lock", 15), t("lock_app")))),
    h("p", { class: "meta muted" }, t("storage_note")),
    h("div", { class: "row end danger-zone" }, h("button", { class: "btn danger sm", onclick: async () => {
      if (await confirmDialog(t("confirm_erase"))) { await db.clearAll(); location.reload(); }
    } }, icon("trash", 16), t("erase_device"))));
}

function setting(title, desc, control) {
  return h("div", { class: "setting" }, h("div", { class: "doc-main" }, h("div", { class: "doc-title" }, title), desc ? h("div", { class: "meta muted" }, desc) : null), control);
}

function backupSection() {
  return h("section", { class: "card settings" }, h("h2", {}, icon("download", 16), " ", t("backup")),
    h("p", { class: "meta muted" }, t("backup_desc")),
    h("div", { class: "row wrap" }, h("button", { class: "btn primary sm", onclick: async () => {
      const file = await backup.exportBackup();
      if (canShareFiles([file]) && (await shareFiles([file], "DocMind backup"))) return;
      triggerDownload(URL.createObjectURL(file), file.name);
      toast(t("backup_ready"), "ok");
    } }, icon("download", 15), t("make_backup"))));
}

function changePasscode() {
  const cur = h("input", { type: "password", placeholder: t("current_passcode"), autocomplete: "current-password", required: true });
  const p1 = h("input", { type: "password", placeholder: t("new_passcode"), autocomplete: "new-password", required: true });
  const p2 = h("input", { type: "password", placeholder: t("passcode_confirm"), autocomplete: "new-password", required: true });
  const err = h("p", { class: "form-error", role: "alert" });
  const s = sheet(t("change_passcode"), h("form", { class: "form", onsubmit: async (e) => {
    e.preventDefault(); err.textContent = "";
    if (p1.value !== p2.value) { err.textContent = t("passcode_mismatch"); return; }
    try { await V.changePasscode(cur.value, p1.value); s.close(); toast(t("saved"), "ok"); }
    catch (ex) { err.textContent = errText(ex.code); }
  } }, cur, p1, p2, err, h("button", { class: "btn primary" }, t("save"))));
}

async function vaultSection() {
  const v = await api("/vault");
  const box = h("section", { class: "card settings" }, h("h2", {}, icon("lock", 16), " ", t("vault")), h("p", { class: "meta muted" }, t("vault_desc")));
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
    h("button", { class: "btn ghost sm", onclick: async () => {
      if (await confirmDialog(t("remove_pin") + "?")) { try { await api("/vault/pin", { method: "DELETE" }); render(); } catch (e) { if (e.code !== "vault_locked") toast(errText(e.code), "bad"); } }
    } }, t("remove_pin"))));
  return box;
}

function pinDialog(changing) {
  const cur = changing ? h("input", { type: "password", inputmode: "numeric", placeholder: t("current_pin"), required: true }) : null;
  const p1 = h("input", { type: "password", inputmode: "numeric", placeholder: t("pin"), autocomplete: "new-password", required: true });
  const p2 = h("input", { type: "password", inputmode: "numeric", placeholder: t("pin_confirm"), autocomplete: "new-password", required: true });
  const err = h("p", { class: "form-error", role: "alert" });
  const s = sheet(changing ? t("change_pin") : t("set_pin"), h("form", { class: "form", onsubmit: async (e) => {
    e.preventDefault(); err.textContent = "";
    if (p1.value !== p2.value) { err.textContent = t("pin_mismatch"); return; }
    try {
      await api("/vault/pin", { method: "POST", body: { pin: p1.value, current_pin: cur?.value } });
      lockVault(); s.close(); toast(t("saved"), "ok"); render();
    } catch (ex) { err.textContent = errText(ex.code); }
  } }, h("p", { class: "meta muted" }, t("vault_desc")), cur, p1, p2, err, h("button", { class: "btn primary" }, t("save"))));
}


// ---- Android app: scan the phone --------------------------------------------------------------------
export function scanCard(compact = false) {
  const status = h("p", { class: "meta" });
  const bar = h("div", { class: "progress", hidden: true }, h("span", { style: { width: "0%" } }));
  const btn = h("button", { class: "btn primary block" }, icon("search", 18), t("scan_now"));
  const show = (s) => {
    if (s.running) {
      bar.hidden = false;
      bar.firstChild.style.width = `${s.total ? Math.round((100 * s.done) / s.total) : 3}%`;
      status.textContent = t("scanning", { done: s.done, total: s.total || "…" }) + (s.found ? ` · ${s.found} ✓` : "");
      btn.replaceChildren(icon("x", 18), t("scan_stop"));
    } else {
      bar.hidden = true;
      btn.replaceChildren(icon("search", 18), t("scan_now"));
    }
  };
  btn.onclick = async () => {
    if (scanner.state.running) { scanner.state.stop = true; return; }
    const inf = native.info();
    if (!inf.allFiles && !inf.media && !inf.folders.length) await native.requestAllFiles();
    const r = await scanner.run();
    toast(t("scan_done", { n: r.found }), "ok");
    render();
  };
  const off = scanner.onProgress(show);
  scanner.lastScan().then((d) => { if (!scanner.state.running) status.textContent = d ? t("last_scan", { d: fmtDate(d) }) : t("never_scanned"); });
  show(scanner.state);
  const card = h("section", { class: "card scan-card" }, h("h2", {}, icon("search", 16), " ", t("scan_phone")),
    compact ? null : h("p", { class: "meta muted" }, t("scan_desc")), bar, status, btn);
  new MutationObserver((_, obs) => { if (!document.body.contains(card)) { off(); obs.disconnect(); } }).observe(document.body, { childList: true, subtree: true });
  return card;
}

async function nativeSourcesView(root) {
  const inf = native.info();
  const row = (ic, title, desc, ok, action) => h("li", { class: "source" },
    h("div", { class: "thumb sm" }, icon(ic, 20)),
    h("div", { class: "doc-main" }, h("div", { class: "doc-title" }, title),
      ok ? h("span", { class: "badge ok" }, icon("check", 12), t("granted")) : null,
      h("p", { class: "meta muted" }, desc)),
    action);
  const folderOf = (kind) => inf.folders.filter((f) => f.kind === kind);
  const folderBtn = (kind) => h("button", { class: "btn ghost sm", onclick: async () => { await native.addFolder(kind); render(); } }, t("choose_folder"));
  const granted = (kind) => folderOf(kind).map((f) => h("div", { class: "row tight meta" }, icon("folder", 13), f.label,
    h("button", { class: "icon-btn", "aria-label": t("remove"), onclick: () => { native.removeFolder(f.uri); render(); } }, icon("x", 13))));
  root.append(h("div", { class: "page-head" }, h("h1", {}, t("accounts"))),
    scanCard(),
    h("ol", { class: "sources" },
      row("folder", t("all_files"), t("all_files_desc"), inf.allFiles,
        inf.allFiles ? null : h("button", { class: "btn primary sm", onclick: async () => { await native.requestAllFiles(); render(); } }, t("allow"))),
      row("image", t("src_gallery"), t("src_gallery_desc"), inf.media,
        inf.media ? null : h("button", { class: "btn primary sm", onclick: async () => { await native.requestMedia(); render(); } }, t("allow"))),
      row("download", t("src_downloads"), t("src_downloads_desc"), folderOf("downloads").length, h("div", { class: "col tight" }, folderBtn("downloads"), granted("downloads"))),
      row("msg", t("src_whatsapp"), t("src_whatsapp_desc"), folderOf("whatsapp").length, h("div", { class: "col tight" }, folderBtn("whatsapp"), granted("whatsapp"))),
      row("folder", t("src_other"), "", folderOf("folder").length, h("div", { class: "col tight" }, folderBtn("folder"), granted("folder"))),
      row("send", t("share_in"), t("src_share_desc"), true, null),
      row("mail", "Gmail", t("exp_server_only"), false, null)),
    h("div", { class: "row end" }, h("button", { class: "btn ghost sm", onclick: async () => { await scanner.forgetScanned(); toast(t("saved"), "ok"); } }, t("rescan_all"))));
}
