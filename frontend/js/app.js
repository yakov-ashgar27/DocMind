import { api, authenticate, refreshSession, setTokenFromSession, setUnauthorizedHandler, setVaultHandler } from "./api.js";
import { mountVaultIndicator, promptUnlock } from "./vault.js";
import { errText, getLang, setLang, t } from "./i18n.js";
import { current, navigate, onRender, route } from "./router.js";
import { loadCategories, loadMeta, store } from "./store.js";
import { append, clear, h, icon, spinner } from "./ui.js";
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
const TABS = [["home", "/home", "home"], ["assistant", "/assistant", "chat"], ["library", "/library", "doc"],
  ["bundles", "/bundles", "layers"], ["more", "/more", "more"]];

function shell(tab) {
  const nav = h("nav", { class: "tabbar", "aria-label": "main" },
    h("div", { class: "brand" }, h("span", { class: "logo" }, "D"), h("span", {}, "DocMind")),
    TABS.map(([key, href, ic]) => h("a", { href: "#" + href, class: "tab" + (key === tab ? " active" : ""), "aria-current": key === tab ? "page" : null },
      icon(ic, 22), h("span", {}, t("nav_" + key)))));
  const main = h("main", { class: "page" + (tab === "assistant" ? " page-chat" : ""), id: "main" });
  clear(app).append(nav, main);
  return main;
}

let renderSeq = 0;
async function renderRoute() {
  if (!store.user) return;
  const r = current();
  if (!r) return navigate("/home");
  const seq = ++renderSeq;
  const main = shell(r.tab);
  main.append(h("div", { class: "loading" }, spinner()));
  const content = h("div", { class: "content" });
  // Views may pass optional (null/false) children; never let them render as text like "null".
  content.append = (...children) => append(content, children);
  try {
    await r.view(content, r.params, r.query);
    if (seq !== renderSeq) return;
    main.replaceChildren(content);
    window.scrollTo(0, 0);
  } catch (e) {
    if (seq !== renderSeq) return;
    console.error(e);
    main.replaceChildren(h("div", { class: "empty" }, icon("alert", 32), h("p", {}, errText(e.code)),
      h("button", { class: "btn ghost", onclick: () => renderRoute() }, t("retry"))));
  }
}

function authScreen(mode = "login") {
  const err = h("p", { class: "form-error", role: "alert" });
  const email = h("input", { type: "email", name: "email", autocomplete: "email", required: true, placeholder: t("email") });
  const pw = h("input", { type: "password", name: "password", autocomplete: mode === "login" ? "current-password" : "new-password", required: true, placeholder: t("password") });
  const name = h("input", { name: "display_name", autocomplete: "given-name", placeholder: t("name") });
  const submit = h("button", { class: "btn primary block", type: "submit" }, mode === "login" ? t("login") : t("register"));
  const form = h("form", { class: "form", onsubmit: async (e) => {
    e.preventDefault();
    err.textContent = ""; submit.disabled = true;
    try {
      const res = await authenticate(mode, mode === "login" ? { email: email.value, password: pw.value }
        : { email: email.value, password: pw.value, display_name: name.value, locale: getLang() });
      if (res.mfa_required) return mfaScreen(res.mfa_token);
      store.user = res;
      await boot(true);
    } catch (ex) { err.textContent = errText(ex.code); submit.disabled = false; }
  } },
    mode === "register" ? name : null, email, pw,
    mode === "register" ? h("p", { class: "meta muted" }, t("pw_hint")) : null, err, submit);
  clear(app).append(h("div", { class: "auth" },
    h("div", { class: "auth-card" },
      h("div", { class: "auth-brand" }, h("span", { class: "logo lg" }, "D"), h("h1", {}, "DocMind")),
      h("p", { class: "lead" }, t("tagline")),
      form,
      h("button", { class: "linkish", onclick: () => authScreen(mode === "login" ? "register" : "login") }, mode === "login" ? t("no_account") : t("have_account")),
      h("div", { class: "seg center" }, ["he", "en"].map((l) => h("button", { class: l === getLang() ? "active" : "", onclick: () => { setLang(l); authScreen(mode); } }, l === "he" ? "עברית" : "English"))),
      h("p", { class: "meta muted center" }, icon("shield", 13), " ", t("privacy_note")))));
  (mode === "register" ? name : email).focus();
}

function mfaScreen(mfaToken) {
  const err = h("p", { class: "form-error", role: "alert" });
  const code = h("input", { inputmode: "numeric", autocomplete: "one-time-code", class: "pin-input", required: true, "aria-label": t("code") });
  const btn = h("button", { class: "btn primary block", type: "submit" }, t("verify"));
  clear(app).append(h("div", { class: "auth" }, h("div", { class: "auth-card" },
    h("div", { class: "auth-brand" }, h("span", { class: "logo lg" }, "D"), h("h1", {}, t("mfa"))),
    h("p", { class: "lead" }, t("mfa_login")),
    h("form", { class: "form", onsubmit: async (e) => {
      e.preventDefault(); btn.disabled = true; err.textContent = "";
      try {
        store.user = await setTokenFromSession(await api("/auth/mfa", { method: "POST", body: { mfa_token: mfaToken, code: code.value } }));
        await boot(true);
      } catch (ex) {
        err.textContent = errText(ex.code); btn.disabled = false; code.value = "";
        if (ex.code === "mfa_expired") setTimeout(() => authScreen(), 1500);
      }
    } }, code, err, btn))));
  code.focus();
}

async function boot(fresh = false) {
  if (!fresh) store.user = await refreshSession();
  if (!store.user) return authScreen();
  if (store.user.locale && store.user.locale !== getLang()) setLang(store.user.locale);
  await Promise.all([loadMeta(), loadCategories(true)]);
  onRender(renderRoute);
  if (!location.hash || location.hash === "#/") navigate("/home"); else renderRoute();
}

setUnauthorizedHandler(() => { store.user = null; authScreen(); });
setVaultHandler(() => promptUnlock());
mountVaultIndicator();
app.replaceChildren(h("div", { class: "loading full" }, spinner()));
boot();

if ("serviceWorker" in navigator) navigator.serviceWorker.register("/sw.js").catch(() => {});
