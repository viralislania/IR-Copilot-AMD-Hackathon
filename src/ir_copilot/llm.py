"""Swappable LLM client — configured by LLM_BACKEND in .env.

  mock : agents use deterministic, grounded templates (offline; no endpoint needed)
  vllm : agents call OpenAI-compatible chat endpoints on the MI300X (docs/rocm-vllm.md)

Agents call `get_chat(role)`; when it returns None they run their deterministic path.
This keeps every notebook runnable offline while staying one env-flip away from real models.
"""
from __future__ import annotations

from typing import Optional

from .config import settings

_ROLES = {
    "drafting": (settings.drafting_base_url, settings.drafting_model),
    "analyst": (settings.analyst_base_url, settings.analyst_model),
    "verifier": (settings.verifier_base_url, settings.verifier_model),
}


class ChatLLM:
    def __init__(self, base_url: str, model: str, api_key: str):
        from openai import OpenAI
        self._client = OpenAI(base_url=base_url, api_key=api_key)
        self.model = model

    def complete(self, system: str, user: str, temperature: float = 0.2,
                 max_tokens: int = 1024) -> str:
        resp = self._client.chat.completions.create(
            model=self.model,
            messages=[{"role": "system", "content": system},
                      {"role": "user", "content": user}],
            temperature=temperature, max_tokens=max_tokens,
        )
        return resp.choices[0].message.content or ""


def is_mock() -> bool:
    return settings.llm_backend == "mock"


def get_chat(role: str) -> Optional[ChatLLM]:
    """Return a chat client for the role, or None in mock mode."""
    if is_mock():
        return None
    if role not in _ROLES:
        raise ValueError(f"unknown LLM role {role!r}; expected one of {list(_ROLES)}")
    base_url, model = _ROLES[role]
    return ChatLLM(base_url, model, settings.openai_api_key)
