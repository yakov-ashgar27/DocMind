import { api } from "./api.js";

export const store = { user: null, meta: null, categories: null };

export async function loadMeta() {
  if (!store.meta) store.meta = await api("/meta");
  return store.meta;
}
export async function loadCategories(force = false) {
  if (!store.categories || force) store.categories = (await api("/categories")).categories;
  return store.categories;
}
export function docTypeLabel(key, lang) {
  return store.meta?.doc_types?.[key]?.[lang] || (lang === "he" ? "לא מזוהה" : "Unclassified");
}
export function categoryOf(key) {
  return (store.categories || []).find((c) => c.key === key);
}
