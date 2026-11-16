"""LLM provider abstraction.

Privacy contract: the assistant only ever sends the user's *request text* plus the list of
document-type keys, and only when (a) a provider is configured by the operator and (b) the user
has switched on “AI assistance” in Settings. Document contents, filenames and emails are never
sent. The local engine works fully without any provider.
"""
from __future__ import annotations

import json
import logging
import re

import requests

from ..knowledge.catalog import DOC_TYPES, PROCESSES

log = logging.getLogger(__name__)

SYSTEM = (
    "You map a user's request about personal documents to JSON. Reply with JSON only: "
    '{"doc_types": [...], "process_key": string|null, "custom_purpose": string|null}. '
    "doc_types must be chosen only from: " + ", ".join(DOC_TYPES) + ". "
    "process_key only from: " + ", ".join(PROCESSES) + ". Never invent other keys."
)


class LLMProvider:
    name = "none"
    available = False

    def complete(self, system: str, user: str) -> str | None:
        return None

    def parse_intent(self, text: str) -> dict | None:
        raw = self.complete(SYSTEM, text[:1000])
        if not raw:
            return None
        m = re.search(r"\{.*\}", raw, re.S)
        if not m:
            return None
        try:
            data = json.loads(m.group(0))
        except json.JSONDecodeError:
            return None
        # Validate strictly against the catalog; anything else is dropped.
        return {
            "doc_types": [d for d in data.get("doc_types") or [] if d in DOC_TYPES],
            "process_key": data.get("process_key") if data.get("process_key") in PROCESSES else None,
            "custom_purpose": (data.get("custom_purpose") or None) and str(data["custom_purpose"])[:80],
        }


class AnthropicProvider(LLMProvider):
    name = "anthropic"
    available = True

    def __init__(self, api_key: str, model: str | None):
        self.api_key, self.model = api_key, model or "claude-haiku-5-5"

    def complete(self, system, user):
        try:
            r = requests.post("https://api.anthropic.com/v1/messages", timeout=20, headers={
                "x-api-key": self.api_key, "anthropic-version": "2023-06-01", "content-type": "application/json"},
                json={"model": self.model, "max_tokens": 300, "system": system,
                      "messages": [{"role": "user", "content": user}]})
            r.raise_for_status()
            return "".join(b.get("text", "") for b in r.json().get("content", []))
        except Exception as e:
            log.warning("anthropic call failed: %s", e)
            return None


class OpenAIProvider(LLMProvider):
    name = "openai"
    available = True

    def __init__(self, api_key: str, model: str | None):
        self.api_key, self.model = api_key, model or "gpt-4o-mini"

    def complete(self, system, user):
        try:
            r = requests.post("https://api.openai.com/v1/chat/completions", timeout=20,
                              headers={"Authorization": f"Bearer {self.api_key}"},
                              json={"model": self.model, "max_tokens": 300,
                                    "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}]})
            r.raise_for_status()
            return r.json()["choices"][0]["message"]["content"]
        except Exception as e:
            log.warning("openai call failed: %s", e)
            return None


def make_provider(cfg) -> LLMProvider:
    if cfg.llm_provider == "anthropic" and cfg.llm_api_key:
        return AnthropicProvider(cfg.llm_api_key, cfg.llm_model)
    if cfg.llm_provider == "openai" and cfg.llm_api_key:
        return OpenAIProvider(cfg.llm_api_key, cfg.llm_model)
    return LLMProvider()
