import { api, triggerDownload } from "../api.js";
import { docCard, uploadButtons } from "../components.js";
import { fmtDate, getLang, t } from "../i18n.js";
import { navigate } from "../router.js";
import { store } from "../store.js";
import { h, icon } from "../ui.js";

export async function homeView(root) {
  const d = await api("/dashboard");
  const ask = h("input", { class: "ask-input", type: "text", placeholder: t("ask_placeholder"), "aria-label": t("ask_placeholder"),
    onkeydown: (e) => { if (e.key === "Enter" && ask.value.trim()) go(); } });
  const go = () => navigate(`/assistant?new=1&q=${encodeURIComponent(ask.value.trim())}`);

  root.append(
    h("section", { class: "hero" },
      h("h1", {}, t("hello", { name: store.user.display_name })),
      h("p", { class: "muted" }, t("tagline")),
      h("div", { class: "ask" }, icon("sparkle", 20), ask, h("button", { class: "send-btn", "aria-label": t("send"), onclick: () => ask.value.trim() && go() }, icon("send", 20)))),
    h("section", { class: "stats" },
      stat(t("documents"), d.totals.documents, "/library", "doc"),
      stat(t("bundles"), d.totals.bundles, "/bundles", "layers"),
      stat(t("checklists"), d.totals.checklists, "/memory", "brain")));

  if (d.proposals.length) {
    root.append(h("section", { class: "card notice", onclick: () => navigate("/memory") },
      icon("brain", 18), h("span", {}, `${t("pending")}: ${d.proposals.length}`), icon("chevron", 16)));
  }

  if (d.checklists.length) {
    root.append(section(t("start_from_memory"), h("div", { class: "chips" }, d.checklists.map((c) =>
      h("button", { class: "chip big", onclick: () => navigate(`/assistant?new=1&q=${encodeURIComponent(c.name)}`) }, icon("brain", 15), c.name)))));
  }

  if (!d.totals.documents) {
    root.append(h("section", { class: "card onboarding" }, h("p", {}, t("empty_library")), uploadButtons(() => navigate("/library"))));
    return;
  }

  if (d.reminders?.length) {
    root.append(section(t("reminders"), h("div", { class: "list" }, d.reminders.map((r) =>
      h("button", { class: "list-item", onclick: () => navigate(`/doc/${r.document.id}`) },
        h("div", { class: `thumb sm ${r.state === "expired" ? "bad" : "warn"}` }, icon("clock", 20)),
        h("div", { class: "doc-main" }, h("div", { class: "doc-title" }, r.document.display_name),
          h("div", { class: "meta" }, `${fmtDate(r.expiry_date)} · ${r.days_left < 0 ? t("expired_ago", { n: -r.days_left }) : t("days_left", { n: r.days_left })}`)),
        icon("chevron", 16)))),
      h("button", { class: "btn ghost sm", onclick: async () => {
        const { url } = await api("/reminders/calendar-link", { method: "POST", body: {} });
        triggerDownload(url, "docmind-reminders.ics");
      } }, icon("clock", 15), t("all_to_calendar"))));
  }

  if (d.attention.length) {
    root.append(section(t("needs_attention"), h("div", { class: "doc-list" }, d.attention.map((a) =>
      docCard(a.document, { onClick: () => navigate(`/doc/${a.document.id}`),
        extra: h("span", { class: `badge ${a.kind === "expired" || a.kind === "failed" ? "bad" : "warn"}` }, t("k_" + a.kind)) })))));
  }
  if (d.bundles.length) {
    root.append(section(t("bundles"), h("div", { class: "list" }, d.bundles.map((b) =>
      h("button", { class: "list-item", onclick: () => navigate(`/bundle/${b.id}`) }, icon("layers", 20),
        h("div", { class: "doc-main" }, h("div", { class: "doc-title" }, b.name), h("div", { class: "meta" }, `${b.ready}/${b.items}`)),
        icon("chevron", 16))))));
  }
  root.append(section(t("recent"), h("div", { class: "doc-list" }, d.recent_documents.map((doc) =>
    docCard(doc, { onClick: () => navigate(`/doc/${doc.id}`) })))));
  if (d.totals.processing) setTimeout(() => location.hash === "#/home" && navigate("/home"), 2500);
}

function stat(label, n, href, ic) {
  return h("button", { class: "stat", onclick: () => navigate(href) }, icon(ic, 18), h("strong", {}, String(n)), h("span", {}, label));
}

function section(title, body) {
  return h("section", { class: "section" }, h("h2", {}, title), body);
}
