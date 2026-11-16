// DocMind phone edition: app shell, first-run setup, passcode lock, auto-lock.
import { api, clearThumbs, setUnauthorizedHandler, setVaultHandler } from "./api.js";
import * as backup from "./core/backup.js";
import * as db from "./core/db.js";
import { onOcrProgress } from "./core/extract.js";
import * as repo from "./core/repo.js";
import * as V from "./core/vault.js";
import { errText, getLang, setLang, t } from "./i18n.js";
import { current, navigate, onRender, route } from "./router.js";
import { loadCategories, loadMeta, store } from "./store.js";
import { append, clear, confirmDialog, h, icon, spinner, toast } from "./ui.js";
import { mountVaultIndicator, promptUnlock } from "./vault.js";
import { assistantView } from "./views/assistant.js";
import { bundleView, bundlesView } from "./views/bundles.js";
import { homeView } from "./views/home.js";
import { documentView, libraryView } from "./views/library.js";
import { memoryView } from "./views/memory.js";
import { accountsView, categoriesView, moreView, settingsView } from "./views/more.js";

route("/home", homeView, "home");
route("/assistant", assistantView, "assistant");
route("/assistant/:id", assistantView, "assistant");
route("/library", libraryView, "library");
route("/doc/:id", documentView, "library");
route("/bundles", bundlesView, "bundles");
route("/bundle/:id", bundleView, "bundles");
route("/more", moreView, "more");
route("/memory", memoryView, "more");
route("/accounts", accountsView, "more");
route("/categories", categoriesView, "more");
route("/settings", settingsView, "more");

const app = document.getElementById("app");
const TABS = [["home", "/home", "home"], ["assistant", "/assistant", "chat"], ["library", "/library", "doc"], ["bundles", "/bundles", "layers"], ["more", "/more", "more"]];

function shell(tab) {
  const nav = h("nav", { class: "tabbar", "aria-label": "main" },
    h("div", { class: "brand" }, h("span", { class: "logo" }, "D"), h("span", {}, "DocMind")),
    TABS.map(([key, href, ic]) => h("a", { href: "#" + href, class: "tab" + (key === tab ? " active" : ""), "aria-current": key === tab ? "page" : null },
      icon(ic, 22), h("span", {}, t("nav_" + key)))));
  const main = h("main", { class: "page" + (tab === "assistant" ? " page-chat" : ""), id: "main" });
  clear(app).append(nav, main);
  return main;
}

let seq = 0;
async function renderRoute() {
  if (!V.session.dek) return lockScreen();
  const r = current();
  if (!r) return navigate("/home");
  const my = ++seq;
  const main = shell(r.tab);
  main.append(h("div", { class: "loading" }, spinner()));
  const content = h("div", { class: "content" });
  content.append = (...c) => append(content, c);
  try {
    await r.view(content, r.params, r.query);
    if (my !== seq) return;
    main.replaceChildren(content);
    window.scrollTo(0, 0);
  } catch (e) {
    if (my !== seq) return;
    console.error(e);
    main.replaceChildren(h("div", { class: "empty" }, icon("alert", 32), h("p", {}, errText(e.code)),
      h("button", { class: "btn ghost", onclick: () => renderRoute() }, t("retry"))));
  }
}

function brand() {
  return h("div", { class: "auth-brand" }, h("img", { class: "app-icon", src: "icons/icon-192.png", alt: "" }), h("h1", {}, "DocMind"));
}
function langSwitch(rerender) {
  return h("div", { class: "seg center" }, ["he", "en"].map((l) => h("button", { class: l === getLang() ? "active" : "", onclick: () => { setLang(l); rerender(); } }, l === "he" ? "עברית" : "English")));
}

function setupScreen() {
  const name = h("input", { placeholder: t("name"), autocomplete: "given-name" });
  const p1 = h("input", { type: "password", placeholder: t("passcode"), autocomplete: "new-password", required: true });
  const p2 = h("input", { type: "password", placeholder: t("passcode_confirm"), autocomplete: "new-password", required: true });
  const err = h("p", { class: "form-error", role: "alert" });
  const btn = h("button", { class: "btn primary block", type: "submit" }, t("start"));
  clear(app).append(h("div", { class: "auth" }, h("div", { class: "auth-card" }, brand(),
    h("p", { class: "lead" }, t("tagline")),
    h("div", { class: "card notice ok" }, icon("shield", 18), h("span", {}, t("setup_lead"))),
    h("form", { class: "form", onsubmit: async (e) => {
      e.preventDefault(); err.textContent = "";
      if (p1.value !== p2.value) { err.textContent = t("passcode_mismatch"); return; }
      btn.disabled = true; btn.replaceChildren(spinner());
      try {
        await V.setup(p1.value);
        await repo.saveSettings({ display_name: name.value.trim(), locale: getLang(), created_at: new Date().toISOString(), locked_categories: V.DEFAULT_LOCKED });
        await enter();
      } catch (ex) { err.textContent = errText(ex.code); btn.disabled = false; btn.replaceChildren(t("start")); }
    } }, name, p1, p2, err, btn),
    restoreButton(),
    langSwitch(setupScreen),
    h("p", { class: "meta muted center" }, t("phone_edition")))));
  name.focus();
}

function restoreButton() {
  const input = h("input", { type: "file", accept: ".docmind,application/octet-stream,application/json", class: "visually-hidden", onchange: async () => {
    if (!input.files[0]) return;
    try { await backup.importBackup(input.files[0]); toast(t("saved"), "ok"); lockScreen(); }
    catch (e) { toast(errText(e.code), "bad"); }
  } });
  return h("div", {}, h("button", { class: "linkish", onclick: () => input.click() }, t("restore_backup")), input);
}

function lockScreen() {
  V.lockApp(); repo.wipeCache(); clearThumbs(); store.user = null;
  const pass = h("input", { type: "password", placeholder: t("enter_passcode"), autocomplete: "current-password", required: true, class: "pass-input" });
  const err = h("p", { class: "form-error", role: "alert" });
  const btn = h("button", { class: "btn primary block", type: "submit" }, icon("unlock", 18), t("unlock_app"));
  clear(app).append(h("div", { class: "auth" }, h("div", { class: "auth-card" }, brand(),
    h("form", { class: "form", onsubmit: async (e) => {
      e.preventDefault(); err.textContent = ""; btn.disabled = true;
      try { await V.unlockApp(pass.value); await enter(); }
      catch (ex) {
        err.textContent = ex.code === "temporarily_locked" || String(ex.code).startsWith("temporarily_locked") ? errText("temporarily_locked") : errText(ex.code);
        btn.disabled = false; pass.value = ""; pass.focus();
      }
    } }, pass, err, btn),
    h("details", { class: "forgot" }, h("summary", {}, t("forgot_passcode")), h("p", { class: "meta muted" }, t("forgot_text")), restoreButton(),
      h("button", { class: "btn danger sm", onclick: async () => {
        if (await confirmDialog(t("confirm_erase"))) { await db.clearAll(); location.reload(); }
      } }, t("erase_all"))),
    h("p", { class: "meta muted center" }, icon("shield", 13), " ", t("phone_edition")))));
  pass.focus();
}

async function enter() {
  const s = await repo.settings();
  if (s.locale && s.locale !== getLang()) setLang(s.locale);
  store.user = (await api("/me")).user;
  store.meta = null;
  await Promise.all([loadMeta(), loadCategories(true)]);
  onRender(renderRoute);
  if (!location.hash || location.hash === "#/") navigate("/home"); else renderRoute();
  armAutoLock();
  importSharedFiles();
  importNativeShared();
  refreshPhoneIndex();
}

// Files shared to DocMind from other apps (Android share sheet) wait in the inbox until unlock.
async function importSharedFiles() {
  if (!("caches" in window)) return;
  const inbox = await caches.open("docmind-share-inbox");
  const keys = await inbox.keys();
  if (!keys.length) return;
  let n = 0;
  for (const req of keys) {
    const res = await inbox.match(req);
    const name = decodeURIComponent(res.headers.get("x-name") || "document");
    const blob = await res.blob();
    try {
      const fd = new FormData();
      if (/\.zip$/i.test(name) || blob.type === "application/zip") { fd.append("file", new File([blob], name)); await api("/import/whatsapp", { method: "POST", form: fd }); }
      else { fd.append("files", new File([blob], name, { type: blob.type })); await api("/documents", { method: "POST", form: fd }); }
      n++;
    } catch (e) { toast(`${name}: ${errText(e.code)}`, "bad"); }
    await inbox.delete(req);
  }
  if (n) { toast(t("files_added", { n }), "ok"); navigate("/library"); }
}

// Android app: keep the phone index fresh (incremental: only new or changed files are read).
async function refreshPhoneIndex() {
  const native = await import("./native.js");
  if (!native.isNative) return;
  const inf = native.info();
  if (!inf.allFiles && !inf.media && !inf.folders.length) return;
  const pi = await import("./core/phoneindex.js");
  const last = await pi.lastBuilt();
  if (last && Date.now() - Date.parse(last) < 6 * 3600000) return;
  setTimeout(() => pi.build().catch(() => {}), 3000);
}

// Android app: files shared to DocMind ("Share → DocMind") are imported after unlock.
async function importNativeShared() {
  const native = await import("./native.js");
  if (!native.isNative || !V.session.dek) return;
  const items = native.takeShared();
  let n = 0;
  for (const it of items) {
    try {
      const bytes = await native.readUri(it.uri);
      if (/\.zip$/i.test(it.name) || it.mime === "application/zip") {
        const fd = new FormData(); fd.append("file", new File([bytes], it.name)); await api("/import/whatsapp", { method: "POST", form: fd });
      } else await repo.ingest(bytes, it.name, "upload");
      n++;
    } catch (e) { toast(`${it.name}: ${errText(e.code || e.message)}`, "bad"); }
  }
  if (n) { toast(t("files_added", { n }), "ok"); navigate("/library"); }
}
import("./native.js").then((native) => {
  if (!native.isNative) return;
  native.onNative("shared", () => importNativeShared());
  window.addEventListener("docmind-saved", (e) => toast(e.detail.res === "saved" ? t("saved_to_downloads") : t("saved"), e.detail.res === "error" ? "bad" : "ok"));
});

// Auto-lock: after N minutes in the background (default 2) or of inactivity (default 10).
let hiddenAt = 0, idleTimer = null;
function armAutoLock() {
  const reset = () => {
    clearTimeout(idleTimer);
    if (V.session.dek) idleTimer = setTimeout(lockScreen, ((store.user?.settings?.auto_lock_minutes) || 10) * 60000);
  };
  ["pointerdown", "keydown", "scroll"].forEach((ev) => addEventListener(ev, reset, { passive: true }));
  reset();
}
document.addEventListener("visibilitychange", () => {
  if (document.visibilityState === "hidden") { hiddenAt = Date.now(); V.lockVault(); }
  else if (V.session.dek && hiddenAt && Date.now() - hiddenAt > 2 * 60000) lockScreen();
});

let ocrToastShown = false;
onOcrProgress((m) => {
  if (!ocrToastShown && /loading|initializ/i.test(m.status || "")) { ocrToastShown = true; toast(t("ocr_loading")); }
});

setUnauthorizedHandler(() => lockScreen());
setVaultHandler(() => promptUnlock());
mountVaultIndicator();
app.replaceChildren(h("div", { class: "loading full" }, spinner()));
V.isSetUp().then((ok) => (ok ? lockScreen() : setupScreen()));

if ("serviceWorker" in navigator && !window.DocMindNative) navigator.serviceWorker.register("sw.js").catch(() => {});
export { lockScreen };
