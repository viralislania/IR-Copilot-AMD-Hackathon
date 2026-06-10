"""Swappable embedding backends — configured by EMBEDDING_BACKEND in .env.

  hash                  : deterministic hashing embedder, zero downloads (offline demo/tests)
  sentence-transformers : real BAAI/bge-base-en-v1.5 locally
  vllm                  : remote OpenAI-compatible /v1/embeddings on the MI300X
"""
from __future__ import annotations

import hashlib
import math
import re
from typing import List, Protocol

from .config import settings

_TOKEN_RE = re.compile(r"[a-z0-9]+")


class Embedder(Protocol):
    dim: int
    def embed(self, texts: List[str]) -> List[List[float]]: ...


def _normalize(vec: List[float]) -> List[float]:
    norm = math.sqrt(sum(v * v for v in vec)) or 1.0
    return [v / norm for v in vec]


class HashEmbedder:
    """Hashing-trick bag-of-words. No model download; good enough for keyword retrieval demos."""

    def __init__(self, dim: int = 384):
        self.dim = dim

    def _embed_one(self, text: str) -> List[float]:
        vec = [0.0] * self.dim
        for tok in _TOKEN_RE.findall(text.lower()):
            h = int(hashlib.md5(tok.encode()).hexdigest(), 16)
            idx = h % self.dim
            sign = 1.0 if (h >> 8) & 1 else -1.0
            vec[idx] += sign
        return _normalize(vec)

    def embed(self, texts: List[str]) -> List[List[float]]:
        return [self._embed_one(t) for t in texts]


class STEmbedder:
    """Real local embeddings via sentence-transformers (e.g. bge-base, or a fine-tuned model)."""

    def __init__(self, model_name: str):
        from sentence_transformers import SentenceTransformer
        self._model = SentenceTransformer(model_name)
        self.dim = self._model.get_sentence_embedding_dimension()

    def embed(self, texts: List[str]) -> List[List[float]]:
        return [v.tolist() for v in self._model.encode(texts, normalize_embeddings=True)]


class VLLMEmbedder:
    """Remote embeddings from a vLLM OpenAI-compatible endpoint on the MI300X."""

    def __init__(self, base_url: str, model: str, api_key: str, dim: int):
        from openai import OpenAI
        self._client = OpenAI(base_url=base_url, api_key=api_key)
        self._model = model
        self.dim = dim

    def embed(self, texts: List[str]) -> List[List[float]]:
        resp = self._client.embeddings.create(model=self._model, input=texts)
        return [d.embedding for d in resp.data]


def get_embedder() -> Embedder:
    backend = settings.embedding_backend
    if backend == "hash":
        return HashEmbedder(dim=settings.embedding_dim)
    if backend == "sentence-transformers":
        return STEmbedder(settings.embedding_model)
    if backend == "vllm":
        return VLLMEmbedder(settings.embedding_base_url, settings.embedding_model,
                            settings.openai_api_key, settings.embedding_dim)
    raise ValueError(f"unknown EMBEDDING_BACKEND={backend!r}")
