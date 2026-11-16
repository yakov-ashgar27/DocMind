const routes = [];
let renderFn = null;

export function route(pattern, view, tab) {
  const keys = [];
  const rx = new RegExp("^" + pattern.replace(/:(\w+)/g, (_, k) => { keys.push(k); return "([^/]+)"; }) + "$");
  routes.push({ rx, keys, view, tab });
}

export function navigate(path) {
  if (location.hash === "#" + path) render();
  else location.hash = path;
}

export function current() {
  const raw = location.hash.slice(1) || "/home";
  const [path, qs] = raw.split("?");
  for (const r of routes) {
    const m = path.match(r.rx);
    if (m) {
      const params = Object.fromEntries(r.keys.map((k, i) => [k, decodeURIComponent(m[i + 1])]));
      return { ...r, params, query: new URLSearchParams(qs || "") };
    }
  }
  return null;
}

export function onRender(fn) { renderFn = fn; }
export function render() { renderFn?.(); }
window.addEventListener("hashchange", () => render());
