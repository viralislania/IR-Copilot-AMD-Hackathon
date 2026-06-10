"""Qdrant-backed knowledge wiki — configurable transport (docs/wiki-ingestion.md).

QDRANT_MODE:
  memory : QdrantClient(":memory:")          — in-process, zero setup (default)
  docker : QdrantClient(url=QDRANT_URL)       — remote server (docker run -p 6333:6333 qdrant/qdrant)
  local  : QdrantClient(path=QDRANT_PATH)     — on-disk persistence, no server
"""
from __future__ import annotations

import uuid
from typing import List, Optional

from pydantic import BaseModel

from .config import settings


class WikiChunk(BaseModel):
    chunk_id: str
    text: str
    ticker: str
    doc_type: str            # transcript | filing | news | pdf | image | audio | video
    period: Optional[str] = None
    role: Optional[str] = None   # analyst | exec
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
            client.get_collections()  # probe
            return client, "docker"
        except Exception as e:
            print(f"[vectorstore] docker Qdrant at {settings.qdrant_url} unreachable ({e}); "
                  f"falling back to in-memory.")
            return QdrantClient(":memory:"), "memory(fallback)"
    raise ValueError(f"unknown QDRANT_MODE={mode!r}")


class WikiStore:
    def __init__(self, embedder, collection: Optional[str] = None):
        self._embedder = embedder
        self.collection = collection or settings.qdrant_collection
        self.client, self.mode = make_client()

    def ensure_collection(self, recreate: bool = True):
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

    def upsert(self, chunks: List[WikiChunk]):
        from qdrant_client import models
        vectors = self._embedder.embed([c.text for c in chunks])
        points = [
            models.PointStruct(
                id=str(uuid.uuid4()),
                vector=vec,
                payload=chunk.model_dump(),
            )
            for chunk, vec in zip(chunks, vectors)
        ]
        self.client.upsert(self.collection, points=points)
        return len(points)

    def search(self, query: str, ticker: Optional[str] = None, k: int = 5,
               doc_type: Optional[str] = None) -> List[dict]:
        from qdrant_client import models
        qvec = self._embedder.embed([query])[0]
        must = []
        if ticker:
            must.append(models.FieldCondition(key="ticker", match=models.MatchValue(value=ticker)))
        if doc_type:
            must.append(models.FieldCondition(key="doc_type", match=models.MatchValue(value=doc_type)))
        flt = models.Filter(must=must) if must else None
        hits = self.client.query_points(
            self.collection, query=qvec, query_filter=flt, limit=k, with_payload=True).points
        return [{"score": h.score, **h.payload} for h in hits]
