"""Semantic-ish search over a user's documents.

Character n-gram TF-IDF (robust to Hebrew prefixes like ה/ו/ב/ל and to OCR noise) over filename,
display name, bilingual type/category labels, issuer, tags and decrypted text. The index is built
in memory per user on demand and invalidated on every document change; plaintext is never written
to disk. The `Embedder` seam lets a neural embedding model replace TF-IDF without API changes.
"""
from __future__ import annotations

import json
import re
import threading

from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity

from ..knowledge.catalog import CATEGORIES, DOC_TYPES, REQUEST_ALIASES
from ..security import crypto

_CAT = {k: (en, he) for k, en, he, _ in CATEGORIES}


def doc_search_text(doc: dict, text: str) -> str:
    t = DOC_TYPES.get(doc["doc_type"], {})
    cat = _CAT.get(doc["category_key"], ("", ""))
    aliases = " ".join(REQUEST_ALIASES.get(doc["doc_type"], []))
    tags = " ".join(json.loads(doc.get("tags_json") or "[]"))
    head = " ".join(filter(None, [doc["display_name"], doc["original_filename"], t.get("en"), t.get("he"),
                                  aliases, cat[0], cat[1], doc.get("issuer"), tags]))
    # Metadata is repeated so it weighs more than incidental words deep in the body text.
    return f"{head} {head} {text[:6000]}"


def _normalise(s: str) -> str:
    s = s.lower().replace("״", "\"").replace("׳", "'")
    return re.sub(r"\s+", " ", s)


class SearchIndex:
    def __init__(self, db, master_key: bytes):
        self.db = db
        self.master_key = master_key
        self._cache: dict[str, tuple] = {}
        self._lock = threading.Lock()

    def invalidate(self, user_id: str) -> None:
        with self._lock:
            self._cache.pop(user_id, None)

    def _build(self, user_id: str, dek: bytes):
        docs = self.db.all("SELECT * FROM documents WHERE user_id = ? AND archived = 0 AND status = 'ready'",
                           (user_id,))
        if not docs:
            return [], None, None
        corpus = [_normalise(doc_search_text(d, crypto.decrypt_text(dek, d["text_enc"], f"doctext:{d['id']}")))
                  for d in docs]
        vec = TfidfVectorizer(analyzer="char_wb", ngram_range=(2, 4), sublinear_tf=True, min_df=1)
        matrix = vec.fit_transform(corpus)
        return docs, vec, matrix

    def _get(self, user_id: str, dek: bytes):
        with self._lock:
            hit = self._cache.get(user_id)
        if hit:
            return hit
        built = self._build(user_id, dek)
        with self._lock:
            self._cache[user_id] = built
        return built

    def search(self, user_id: str, dek: bytes, query: str, limit: int = 20, min_score: float = 0.08) -> list[tuple[dict, float]]:
        docs, vec, matrix = self._get(user_id, dek)
        if not docs or not query.strip():
            return []
        sims = cosine_similarity(vec.transform([_normalise(query)]), matrix)[0]
        ranked = sorted(zip(docs, sims), key=lambda x: -x[1])
        return [(d, float(s)) for d, s in ranked[:limit] if s >= min_score]

    def nearest_labelled(self, user_id: str, dek: bytes, text: str, filename: str) -> tuple[str, float] | None:
        """Personal classifier layer: nearest document the user labelled themselves (text-to-text)."""
        labelled = self.db.all("SELECT id, doc_type, text_enc FROM documents WHERE user_id = ? AND doc_type_source = 'user' "
                               "AND status = 'ready' AND archived = 0 ORDER BY updated_at DESC LIMIT 500", (user_id,))
        texts = [_normalise(crypto.decrypt_text(dek, d["text_enc"], f"doctext:{d['id']}")) for d in labelled]
        pairs = [(d, t) for d, t in zip(labelled, texts) if len(t) >= 10]
        if not pairs or len(text.strip()) < 10:
            return None
        vec = TfidfVectorizer(analyzer="char_wb", ngram_range=(2, 4), sublinear_tf=True)
        m = vec.fit_transform([t for _, t in pairs] + [_normalise(text)])
        sims = cosine_similarity(m[-1], m[:-1])[0]
        j = int(sims.argmax())
        return pairs[j][0]["doc_type"], float(sims[j])
