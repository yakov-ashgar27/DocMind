import { api } from "../api.js";
import { docCard, downloadDoc, freshnessBadge, openPreview, sourceLabel, statusPill, thumb } from "../components.js";
import { fmtDate, getLang, L, t, errText } from "../i18n.js";
import { h, icon, clear, sheet, spinner, toast } from "../ui.js";
import { navigate } from "../router.js";

let convId = null;

export async function assistantView(root, params, query) {
  if (params.id) convId = params.id;
  if (query.get("new")) convId = null;
  const thread = h("div", { class: "thread", "aria-live": "polite" });
  const input = h("textarea", { class: "composer-input", rows: 1, placeholder: t("ask_placeholder"), "aria-label": t("ask_placeholder"),
    oninput: () => { input.style.height = "auto"; input.style.height = Math.min(input.scrollHeight, 140) + "px"; },
    onkeydown: (e) => { if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); submit(); } } });
  const sendBtn = h("button", { class: "send-btn", "aria-label": t("send"), onclick: () => submit() }, icon("send", 20));

  const header = h("div", { class: "page-head" },
    h("h1", {}, t("nav_assistant")),
    h("div", { class: "row" },
      h("button", { class: "btn ghost sm", onclick: showHistory }, icon("clock", 16), t("history")),
      h("button", { class: "btn ghost sm", onclick: () => { convId = null; navigate("/assistant?new=1"); } }, icon("plus", 16), t("new_chat"))));
  root.append(header, thread, h("div", { class: "composer" }, input, sendBtn));

  async function submit(text) {
    text = (text ?? input.value).trim();
    if (!text) return;
    input.value = ""; input.style.height = "auto";
    thread.append(userBubble(text));
    const pending = h("div", { class: "bubble assistant typing" }, spinner());
    thread.append(pending);
    scroll();
    try {
      const r = await api("/assistant/message", { method: "POST", body: { text, conversation_id: convId } });
      convId = r.conversation_id;
      history.replaceState(null, "", `#/assistant/${convId}`);
      pending.replaceWith(assistantBubble(r, submit));
    } catch (e) {
      pending.replaceWith(h("div", { class: "bubble assistant error" }, errText(e.code)));
    }
    scroll();
  }
  function scroll() { requestAnimationFrame(() => thread.lastElementChild?.scrollIntoView({ behavior: "smooth", block: "end" })); }

  if (convId) {
    try {
      const { messages } = await api(`/conversations/${convId}`);
      for (const m of messages) {
        thread.append(m.role === "user" ? userBubble(m.text) : assistantBubble({ text: m.text, ...m.payload }, submit, true));
      }
      scroll();
    } catch { convId = null; }
  }
  if (!thread.childElementCount) thread.append(welcome(submit));
  const preset = query.get("q");
  if (preset) { history.replaceState(null, "", "#/assistant"); submit(preset); }
  else input.focus({ preventScroll: true });
}

function welcome(submit) {
  const lang = getLang();
  const examples = lang === "he"
    ? ["אני צריך מסמכים למלגת מילואים", "תכין לי את כל מה שצריך להרשמה ללימודים", "תמצא את תעודת הזהות ואישור הלימודים", "תמצא את אישור ניהול החשבון האחרון"]
    : ["I need documents for my military reserve benefits", "Prepare everything required for my university registration", "Find my identity card and proof of enrollment", "Find my latest bank confirmation"];
  return h("div", { class: "welcome" },
    h("div", { class: "welcome-mark" }, icon("sparkle", 26)),
    h("p", { class: "lead" }, t("tagline")),
    h("div", { class: "examples" }, examples.map((e) => h("button", { class: "example", onclick: () => submit(e) }, e))));
}

function userBubble(text) { return h("div", { class: "bubble user", dir: "auto" }, text); }

function assistantBubble(r, submit, historic = false) {
  const el = h("div", { class: "bubble assistant", dir: "auto" });
  for (const line of (r.text || "").split("\n")) if (line.trim()) el.append(h("p", {}, line));
  for (const b of r.blocks || []) {
    if (b.type === "requirements") el.append(requirementsBlock(b));
    if (b.type === "suggestions") el.append(suggestionsBlock(b, submit, historic));
    if (b.type === "proposal") el.append(proposalBlock(b, submit, historic));
    if (b.type === "documents") el.append(h("div", { class: "doc-list" }, b.documents.map((d) => docCard(d, { onClick: () => navigate(`/doc/${d.id}`) }))));
  }
  const actions = (r.actions || []).filter((a) => a.type === "create_bundle" || a.type === "open_upload");
  if (actions.length) {
    el.append(h("div", { class: "row wrap actions" }, actions.map((a) => a.type === "create_bundle"
      ? h("button", { class: "btn primary sm", onclick: async (e) => {
          e.currentTarget.disabled = true;
          try {
            const { bundle } = await api("/bundles", { method: "POST", body: a.payload });
            toast(t("bundle_created"), "ok");
            navigate(`/bundle/${bundle.id}`);
          } catch (err) { toast(errText(err.code), "bad"); e.currentTarget.disabled = false; }
        } }, icon("layers", 16), a.label)
      : h("button", { class: "btn primary sm", onclick: () => navigate("/library") }, icon("upload", 16), t("upload")))));
  }
  if (!historic && r.quick_replies?.length) {
    const qr = h("div", { class: "chips" }, r.quick_replies.map((q) =>
      h("button", { class: "chip", onclick: () => { qr.remove(); submit(q.send); } }, q.label)));
    el.append(qr);
  }
  return el;
}

function requirementsBlock(b) {
  const lang = getLang();
  const card = h("div", { class: "req-card" });
  if (b.title) card.append(h("div", { class: "req-title" }, b.title));
  for (const r of b.results) card.append(requirementRow(r));
  const foot = h("div", { class: "req-foot" },
    h("div", {}, icon("search", 14), `${t("searched")}: `, b.sources_searched.map((s) => L(s.label)).join(" · ")));
  const nc = b.sources_unavailable.filter((s) => s.state === "not_connected" || s.state === "not_configured");
  if (nc.length) foot.append(h("div", { class: "muted" }, `${t("not_connected")}: `, nc.map((s) => L(s.label)).join(" · "), " ",
    h("a", { href: "#/accounts" }, t("connect"))));
  card.append(foot);
  return card;
}

function requirementRow(r) {
  const row = h("div", { class: "req-row" });
  const head = h("div", { class: "req-head" }, h("span", { class: "req-label" }, r.requirement.label), statusPill(r.status));
  row.append(head);
  const best = r.best;
  if (best?.document?.locked) {
    row.append(h("button", { class: "req-doc locked-row", onclick: () => import("../vault.js").then((v) => v.unlockAndRefresh()) },
      thumb(best.document, "sm"),
      h("div", { class: "doc-main" }, h("div", { class: "doc-title" }, t("locked_doc")), h("div", { class: "meta" }, t("locked_hint"))),
      icon("unlock", 18)));
  } else if (best?.document) {
    const d = best.document;
    row.append(h("div", { class: "req-doc" },
      thumb(d, "sm"),
      h("div", { class: "doc-main" },
        h("button", { class: "linkish", onclick: () => navigate(`/doc/${d.id}`) }, d.display_name),
        h("div", { class: "meta" }, [d.issuer, d.doc_date && fmtDate(d.doc_date), sourceLabel(d.source_kind)].filter(Boolean).join(" · ")),
        h("div", { class: "badges" }, freshnessBadge(r.freshness), r.uncertain ? h("span", { class: "badge warn" }, t("uncertain")) : null)),
      h("div", { class: "row tight" },
        h("button", { class: "icon-btn", "aria-label": t("preview"), onclick: () => openPreview(d) }, icon("eye", 18)),
        h("button", { class: "icon-btn", "aria-label": t("download"), onclick: () => downloadDoc(d) }, icon("download", 18)))));
  } else if (best?.external) {
    const x = best.external;
    row.append(h("div", { class: "req-doc ext" },
      h("div", { class: "thumb sm" }, icon(x.kind === "gmail" ? "mail" : "cloud", 20)),
      h("div", { class: "doc-main" },
        h("div", { class: "doc-title" }, x.filename),
        h("div", { class: "meta" }, [x.subject, x.date].filter(Boolean).join(" · ")),
        h("div", { class: "meta muted" }, t("not_local"))),
      h("div", { class: "col tight" },
        x.open_url ? h("a", { class: "btn ghost sm", href: x.open_url, target: "_blank", rel: "noopener noreferrer" }, icon("link", 14),
          x.kind === "gmail" ? t("open_email") : t("open_file")) : null,
        h("button", { class: "btn primary sm", onclick: async (e) => {
          e.currentTarget.disabled = true;
          try {
            const { document } = await api(`/connectors/${x.kind}/import`, { method: "POST", body: { ref: x.ref } });
            toast(t("saved"), "ok");
            navigate(`/doc/${document.id}`);
          } catch (err) { toast(errText(err.code), "bad"); e.currentTarget.disabled = false; }
        } }, icon("download", 14), t("download_to_library")))));
  } else if (r.acquisition) {
    const a = r.acquisition;
    row.append(h("div", { class: "acq" },
      h("div", { class: "acq-label" }, icon("landmark", 14), t("suggested_source")),
      h("div", { class: "acq-source" }, a.source),
      h("p", {}, a.how),
      a.url ? h("a", { href: a.url, target: "_blank", rel: "noopener noreferrer" }, t("official_site"), " ↗") : null));
  }
  if (r.previously_found_in && !best) {
    row.append(h("div", { class: "meta muted" }, t("previously_found", { src: sourceLabel(r.previously_found_in.source) })));
  }
  if (r.alternatives?.length) {
    const alts = r.alternatives.filter((a) => a.document && !a.document.locked);
    if (alts.length) {
      const det = h("details", { class: "alts" }, h("summary", {}, `${t("alternatives")} (${alts.length})`),
        alts.map((a) => h("button", { class: "alt", onclick: () => navigate(`/doc/${a.document.id}`) },
          a.document.display_name, " · ", fmtDate(a.document.doc_date || a.document.created_at))));
      row.append(det);
    }
  }
  return row;
}

function suggestionsBlock(b, submit, historic) {
  const lang = getLang();
  return h("div", { class: "suggest" },
    h("div", { class: "suggest-note" }, icon("sparkle", 14), b.note),
    h("div", { class: "chips" }, b.items.map((it) => h("button", { class: "chip suggestion", disabled: historic,
      onclick: (e) => { e.currentTarget.disabled = true; submit((lang === "he" ? "צריך גם " : "also ") + it.label); } },
      h("span", { class: "chip-tag" }, t("suggestion")), it.label, it.in_library ? h("span", { class: "dot ok", title: t("in_library") }) : null))));
}

function proposalBlock(b, submit, historic) {
  const lang = getLang();
  const p = b.proposal;
  const box = h("div", { class: "proposal" },
    h("div", { class: "proposal-q" }, icon("brain", 18), b.question),
    h("ul", { class: "proposal-items" }, p.items.map((i) => h("li", {}, i.label))));
  if (!historic) {
    box.append(h("div", { class: "row" },
      h("button", { class: "btn primary sm", onclick: () => { box.querySelectorAll("button").forEach((x) => (x.disabled = true)); submit(lang === "he" ? "כן" : "yes"); } }, b.accept_label),
      h("button", { class: "btn ghost sm", onclick: () => { box.querySelectorAll("button").forEach((x) => (x.disabled = true)); submit(lang === "he" ? "לא" : "no"); } }, b.reject_label)));
  }
  return box;
}

async function showHistory() {
  const { conversations } = await api("/conversations");
  const list = h("div", { class: "list" }, conversations.length ? conversations.map((c) =>
    h("button", { class: "list-item", onclick: () => { s.close(); navigate(`/assistant/${c.id}`); } },
      h("div", { class: "doc-main" }, h("div", { class: "doc-title", dir: "auto" }, c.title || "—"), h("div", { class: "meta" }, fmtDate(c.updated_at))),
      icon("chevron", 16))) : h("p", { class: "muted" }, t("nothing_yet")));
  const s = sheet(t("history"), list);
}
