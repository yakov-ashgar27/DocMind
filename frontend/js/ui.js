// Tiny DOM helpers. All dynamic text goes through text nodes — no innerHTML with data.
import { t, getLang } from "./i18n.js";

export function h(tag, attrs = {}, ...children) {
  const el = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs || {})) {
    if (v === undefined || v === null || v === false) continue;
    if (k === "class") el.className = v;
    else if (k.startsWith("on")) el.addEventListener(k.slice(2).toLowerCase(), v);
    else if (k === "style" && typeof v === "object") Object.assign(el.style, v);
    else if (v === true) el.setAttribute(k, "");
    else el.setAttribute(k, v);
  }
  append(el, children);
  return el;
}

export function append(el, children) {
  for (const c of children.flat(Infinity)) {
    if (c === null || c === undefined || c === false) continue;
    el.appendChild(c instanceof Node ? c : document.createTextNode(String(c)));
  }
  return el;
}

export function clear(el) { while (el.firstChild) el.removeChild(el.firstChild); return el; }

const P = {
  home: "M3 10.5 12 3l9 7.5V20a1 1 0 0 1-1 1h-5v-6H9v6H4a1 1 0 0 1-1-1z",
  chat: "M4 5h16v11H8l-4 4z",
  doc: "M7 3h7l5 5v13H7zM14 3v5h5",
  layers: "M12 3 2 8l10 5 10-5zM2 13l10 5 10-5M2 17.5l10 5 10-5",
  more: "M5 12h.01M12 12h.01M19 12h.01",
  upload: "M12 16V4M7 9l5-5 5 5M4 20h16",
  search: "M11 18a7 7 0 1 1 0-14 7 7 0 0 1 0 14zM21 21l-5-5",
  check: "M5 12.5 10 17l9-10",
  alert: "M12 8v5M12 17h.01M10.3 3.9 2.4 18a2 2 0 0 0 1.7 3h15.8a2 2 0 0 0 1.7-3L13.7 3.9a2 2 0 0 0-3.4 0z",
  cloud: "M7 18a5 5 0 1 1 1.2-9.9A6 6 0 0 1 19.5 10 4 4 0 0 1 18 18z",
  mail: "M3 6h18v12H3zM3 7l9 6 9-6",
  phone: "M8 2h8a1 1 0 0 1 1 1v18a1 1 0 0 1-1 1H8a1 1 0 0 1-1-1V3a1 1 0 0 1 1-1zM11 18h2",
  image: "M4 5h16v14H4zM4 16l5-5 4 4 3-3 4 4M15 9h.01",
  folder: "M3 6h6l2 2h10v11H3z",
  msg: "M20 12a8 8 0 0 1-11.7 7.1L4 20l1-4.1A8 8 0 1 1 20 12z",
  shield: "M12 3 4 6v6c0 4.5 3.4 8.3 8 9 4.6-.7 8-4.5 8-9V6z",
  brain: "M9 4a3 3 0 0 0-3 3 3 3 0 0 0-2 5 3 3 0 0 0 2 5 3 3 0 0 0 6 1V5a3 3 0 0 0-3-1zM15 4a3 3 0 0 1 3 3 3 3 0 0 1 2 5 3 3 0 0 1-2 5 3 3 0 0 1-6 1",
  trash: "M4 7h16M10 11v6M14 11v6M6 7l1 13h10l1-13M9 7V4h6v3",
  download: "M12 4v12M7 11l5 5 5-5M4 20h16",
  eye: "M2 12s3.5-7 10-7 10 7 10 7-3.5 7-10 7S2 12 2 12zM12 15a3 3 0 1 0 0-6 3 3 0 0 0 0 6z",
  x: "M6 6l12 12M18 6 6 18",
  plus: "M12 5v14M5 12h14",
  chevron: "M9 6l6 6-6 6",
  settings: "M12 15a3 3 0 1 0 0-6 3 3 0 0 0 0 6zM19.4 15a1.7 1.7 0 0 0 .3 1.8l.1.1a2 2 0 1 1-2.8 2.8l-.1-.1a1.7 1.7 0 0 0-1.8-.3 1.7 1.7 0 0 0-1 1.5V21a2 2 0 1 1-4 0v-.1a1.7 1.7 0 0 0-1.1-1.5 1.7 1.7 0 0 0-1.8.3l-.1.1a2 2 0 1 1-2.8-2.8l.1-.1a1.7 1.7 0 0 0 .3-1.8 1.7 1.7 0 0 0-1.5-1H3a2 2 0 1 1 0-4h.1a1.7 1.7 0 0 0 1.5-1.1 1.7 1.7 0 0 0-.3-1.8l-.1-.1a2 2 0 1 1 2.8-2.8l.1.1a1.7 1.7 0 0 0 1.8.3H9a1.7 1.7 0 0 0 1-1.5V3a2 2 0 1 1 4 0v.1a1.7 1.7 0 0 0 1 1.5 1.7 1.7 0 0 0 1.8-.3l.1-.1a2 2 0 1 1 2.8 2.8l-.1.1a1.7 1.7 0 0 0-.3 1.8V9a1.7 1.7 0 0 0 1.5 1H21a2 2 0 1 1 0 4h-.1a1.7 1.7 0 0 0-1.5 1z",
  tag: "M3 12V4h8l10 10-8 8zM7.5 8.5h.01",
  clock: "M12 21a9 9 0 1 0 0-18 9 9 0 0 0 0 18zM12 7v5l3 2",
  lock: "M6 11h12v10H6zM8.5 11V8a3.5 3.5 0 0 1 7 0v3",
  unlock: "M6 11h12v10H6zM8.5 11V8a3.5 3.5 0 0 1 6.8-1.2",
  link: "M10 14a4 4 0 0 0 5.7 0l3-3a4 4 0 0 0-5.7-5.7l-1 1M14 10a4 4 0 0 0-5.7 0l-3 3a4 4 0 0 0 5.7 5.7l1-1",
  send: "M4 12 20 4l-6 16-3-7z",
  sparkle: "M12 3l1.8 5.2L19 10l-5.2 1.8L12 17l-1.8-5.2L5 10l5.2-1.8z",
  id: "M3 5h18v14H3zM8 11a2 2 0 1 0 0-4 2 2 0 0 0 0 4zM5 16c.6-1.8 1.8-2.5 3-2.5s2.4.7 3 2.5M14 9h4M14 13h4",
  school: "M2 9l10-5 10 5-10 5zM6 11v5c3 2 9 2 12 0v-5",
  briefcase: "M3 8h18v12H3zM8 8V5h8v3",
  bank: "M3 10h18L12 4zM5 10v8M9 10v8M15 10v8M19 10v8M3 20h18",
  umbrella: "M3 12a9 9 0 0 1 18 0zM12 12v7a2 2 0 0 0 4 0",
  heart: "M12 20s-7-4.4-9-9a4.6 4.6 0 0 1 9-3 4.6 4.6 0 0 1 9 3c-2 4.6-9 9-9 9z",
  landmark: "M3 21h18M5 21V10M19 21V10M9 21V10M15 21V10M2 10l10-6 10 6",
  plane: "M2 13l20-8-6 16-3-7z",
  scale: "M12 3v18M5 7h14M5 7l-3 7a3 3 0 0 0 6 0zM19 7l-3 7a3 3 0 0 0 6 0zM8 21h8",
};

export function icon(name, size = 20) {
  const ns = "http://www.w3.org/2000/svg";
  const svg = document.createElementNS(ns, "svg");
  svg.setAttribute("viewBox", "0 0 24 24");
  svg.setAttribute("width", size);
  svg.setAttribute("height", size);
  svg.setAttribute("aria-hidden", "true");
  svg.setAttribute("class", "icon" + (name === "chevron" ? " flip-rtl" : ""));
  const p = document.createElementNS(ns, "path");
  p.setAttribute("d", P[name] || P.doc);
  svg.appendChild(p);
  return svg;
}

let toastTimer;
export function toast(msg, kind = "info") {
  let el = document.getElementById("toast");
  if (!el) { el = h("div", { id: "toast", role: "status", "aria-live": "polite" }); document.body.appendChild(el); }
  el.className = "toast show " + kind;
  el.textContent = msg;
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => el.classList.remove("show"), 3200);
}

// Bottom sheet / dialog
export function sheet(title, content, { wide = false } = {}) {
  const close = () => { overlay.classList.remove("open"); setTimeout(() => overlay.remove(), 200); document.removeEventListener("keydown", onKey); };
  const onKey = (e) => { if (e.key === "Escape") close(); };
  const panel = h("div", { class: "sheet" + (wide ? " wide" : ""), role: "dialog", "aria-modal": "true", "aria-label": title },
    h("div", { class: "sheet-head" }, h("h2", {}, title),
      h("button", { class: "icon-btn", "aria-label": t("close"), onclick: close }, icon("x"))),
    h("div", { class: "sheet-body" }, content));
  const overlay = h("div", { class: "overlay", onclick: (e) => { if (e.target === overlay) close(); } }, panel);
  document.body.appendChild(overlay);
  document.addEventListener("keydown", onKey);
  requestAnimationFrame(() => overlay.classList.add("open"));
  return { close, panel };
}

export function confirmDialog(message, { danger = true, okLabel } = {}) {
  return new Promise((resolve) => {
    let done = false;
    const s = sheet(t("delete"), h("div", { class: "stack" },
      h("p", {}, message),
      h("div", { class: "row end" },
        h("button", { class: "btn ghost", onclick: () => { done = true; s.close(); resolve(false); } }, t("cancel")),
        h("button", { class: "btn " + (danger ? "danger" : "primary"), onclick: () => { done = true; s.close(); resolve(true); } }, okLabel || t("delete")))));
    const obs = new MutationObserver(() => { if (!document.body.contains(s.panel) && !done) { resolve(false); obs.disconnect(); } });
    obs.observe(document.body, { childList: true });
  });
}

export function spinner() { return h("span", { class: "spinner", "aria-hidden": "true" }); }

export function emptyState(text, action) {
  return h("div", { class: "empty" }, icon("doc", 36), h("p", {}, text), action || null);
}

export function fileSize(n) {
  if (n < 1024) return n + " B";
  if (n < 1024 * 1024) return (n / 1024).toFixed(0) + " KB";
  return (n / 1024 / 1024).toFixed(1) + " MB";
}

export function dirArrow() { return getLang() === "he" ? "←" : "→"; }
