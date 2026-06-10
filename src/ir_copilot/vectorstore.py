"""Qdrant-backed knowledge wiki — configurable transport (docs/wiki-ingestion.md).

QDRANT_MODE:
  memory : QdrantClient(":memory:")         — in-process, zero setup (default)
  docker : QdrantClient(url=QDRANT_URL)     — remote server (docker run -p 6333:6333 qdrant/qdrant)
  local  : QdrantClient(path=QDRANT_PATH)   — on-disk persistence, no server

Retrieval uses a BM25-blend reranker (no extra deps) that works with every embedding backend:
  hash backend (offline)  : BM25 carries most of the signal (alpha=0.65)
  sentence-transformers   : balanced blend (alpha=0.35)
  vllm (MI300X)           : pure vector is trusted (alpha=0.15)
"""
from __future__ import annotations

import math
import re
import uuid
from collections import Counter
from typing import List, Optional

from pydantic import BaseModel

from .config import settings

_TOKEN_RE = re.compile(r"[a-z0-9]+")

# BM25 params
_K1 = 1.5
_B = 0.75


def _tokenize(text: str) -> list[str]:
    return _TOKEN_RE.findall(text.lower())


def _bm25_score(query_tokens: list[str], doc_tokens: list[str], avg_len: float,
                idf: dict[str, float]) -> float:
    dl = len(doc_tokens)
    tf_map = Counter(doc_tokens)
    score = 0.0
    for t in query_tokens:
        tf = tf_map.get(t, 0)
        if tf == 0:
            continue
        idf_t = idf.get(t, 0.0)
        score += idf_t * (tf * (_K1 + 1)) / (tf + _K1 * (1 - _B + _B * dl / max(1, avg_len)))
    return score


def _bm25_idf(query_tokens: list[str], all_docs: list[list[str]]) -> dict[str, float]:
    N = len(all_docs)
    idf: dict[str, float] = {}
    for t in set(query_tokens):
        df = sum(1 for d in all_docs if t in d)
        idf[t] = math.log((N - df + 0.5) / (df + 0.5) + 1)
    return idf


def _alpha(backend: str) -> float:
    """Weight of BM25 in the blended score (1-alpha = vector weight)."""
    if backend == "hash":
        return 0.65
    if backend == "sentence-transformers":
        return 0.35
    return 0.15   # vllm — strong dense vectors


class BM25Reranker:
    """
    Reranks Qdrant hits by blending the vector cosine score with a BM25 keyword score.
    No external dependencies — pure stdlib math.

    Works best when the pool is over-fetched (fetch 4× k from Qdrant, rerank to k).
    """

    def __init__(self, alpha: Optional[float] = None):
        self.alpha = alpha if alpha is not None else _alpha(settings.embedding_backend)

    def rerank(self, query: str, hits: list[dict], k: int) -> list[dict]:
        if not hits:
            return hits
        qtoks = _tokenize(query)
        if not qtoks:
            return hits[:k]
        doc_tok = [_tokenize(h.get("text", "")) for h in hits]
        avg_len = sum(len(d) for d in doc_tok) / len(doc_tok)
        idf = _bm25_idf(qtoks, doc_tok)
        # normalise BM25 scores to [0,1] across this hit set
        bm25_raw = [_bm25_score(qtoks, dt, avg_len, idf) for dt in doc_tok]
        bm25_max = max(bm25_raw) or 1.0
        scored = []
        for hit, braw in zip(hits, bm25_raw):
            vscore = float(hit.get("score", 0.0))
            bscore = braw / bm25_max
            final = (1 - self.alpha) * vscore + self.alpha * bscore
            scored.append({**hit, "score": round(final, 4),
                           "vector_score": round(vscore, 4),
                           "bm25_score": round(bscore, 4)})
        scored.sort(key=lambda x: -x["score"])
        return scored[:k]


class WikiChunk(BaseModel):
    chunk_id: str
    text: str
    ticker: str
    doc_type: str   # transcript | financial | segment | geo | filing | news | pdf | audio | video
    period: Optional[str] = None
    role: Optional[str] = None    # analyst | exec
    source_url: str = ""
    modality: str = "text"


def make_client():
    """Build a QdrantClient per QDRANT_MODE. Docker/local fall back to memory if unreachable."""
    from qdrant_client import QdrantClient
    mode = settings.qdrant_mode
    if mode == "memory":
        return QdrantClient(":memory:"), "memory"
    if mode == "local":
        settings.qdrant_path.mkdir(parents=True, exist_ok=True)
        return QdrantClient(path=str(settings.qdrant_path)), "local"
    if mode == "docker":
        try:
            client = QdrantClient(url=settings.qdrant_url, timeout=3.0)
            client.get_collections()
            return client, "docker"
        except Exception as e:
            print(f"[vectorstore] docker Qdrant at {settings.qdrant_url} unreachable ({e}); "
                  "falling back to in-memory.")
            return QdrantClient(":memory:"), "memory(fallback)"
    raise ValueError(f"unknown QDRANT_MODE={mode!r}")


class WikiStore:
    def __init__(self, embedder, collection: Optional[str] = None):
        self._embedder = embedder
        self._reranker = BM25Reranker()
        self.collection = collection or settings.qdrant_collection
        self.client, self.mode = make_client()

    def ensure_collection(self, recreate: bool = True) -> None:
        from qdrant_client import models
        exists = self.client.collection_exists(self.collection)
        if exists and recreate:
            self.client.delete_collection(self.collection)
            exists = False
        if not exists:
            self.client.create_collection(
                self.collection,
                vectors_config=models.VectorParams(
                    size=self._embedder.dim, distance=models.Distance.COSINE),
            )

    def upsert(self, chunks: List[WikiChunk]) -> int:
        from qdrant_client import models
        vectors = self._embedder.embed([c.text for c in chunks])
        points = [
            models.PointStruct(id=str(uuid.uuid4()), vector=vec, payload=chunk.model_dump())
            for chunk, vec in zip(chunks, vectors)
        ]
        self.client.upsert(self.collection, points=points)
        return len(points)

    def search(self, query: str, ticker: Optional[str] = None, k: int = 5,
               doc_type: Optional[str] = None, rerank: bool = True) -> List[dict]:
        """
        Search by semantic vector then rerank by BM25 keyword overlap.

        When doc_type is None (cross-type search): fetch 4×k from Qdrant so each document
        type is represented in the pool before BM25 re-orders them.
        When doc_type is specified: fetch 2×k (focused pool is already narrower).
        """
        from qdrant_client import models
        qvec = self._embedder.embed([query])[0]
        must = []
        if ticker:
            must.append(models.FieldCondition(key="ticker", match=models.MatchValue(value=ticker)))
        if doc_type:
            must.append(models.FieldCondition(key="doc_type", match=models.MatchValue(value=doc_type)))
        flt = models.Filter(must=must) if must else None
        fetch = k * (2 if doc_type else 4)   # over-fetch for reranking pool
        hits = self.client.query_points(
            self.collection, query=qvec, query_filter=flt,
            limit=fetch, with_payload=True).points
        results = [{"score": h.score, **h.payload} for h in hits]
        if rerank:
            results = self._reranker.rerank(query, results, k)
        return results[:k]

    def search_each_type(self, query: str, ticker: Optional[str] = None,
                         k_per_type: int = 2) -> List[dict]:
        """Fetch k_per_type results from EACH doc type, then rerank the combined pool."""
        doc_types = ["transcript", "financial", "segment", "geo", "filing", "news"]
        pool: List[dict] = []
        for dt in doc_types:
            pool.extend(self.search(query, ticker=ticker, k=k_per_type,
                                    doc_type=dt, rerank=False))
        return self._reranker.rerank(query, pool, k=k_per_type * len(doc_types))
