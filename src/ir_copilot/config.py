"""Central configuration — every setting comes from .env (never hard-coded).

Import `settings` anywhere:
    from ir_copilot.config import settings
    settings.ticker, settings.qdrant_mode, ...
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from dotenv import load_dotenv


def project_root() -> Path:
    """Walk up from this file to the repo root (where requirements.txt / .env live)."""
    here = Path(__file__).resolve()
    for d in here.parents:
        if (d / "requirements.txt").exists() or (d / ".env").exists():
            return d
    return Path.cwd()


ROOT = project_root()
load_dotenv(ROOT / ".env")


def _get(key: str, default: str = "") -> str:
    return os.getenv(key, default)


def _flag(key: str, default: str = "false") -> bool:
    return os.getenv(key, default).strip().lower() in ("1", "true", "yes", "on")


def _path(key: str, default: str) -> Path:
    p = Path(os.getenv(key, default))
    return p if p.is_absolute() else (ROOT / p)


@dataclass(frozen=True)
class Settings:
    # demo target
    ticker: str
    period: str
    use_mock_data: bool
    peers: list[str]

    # paths
    artifacts_dir: Path
    data_dir: Path

    # vector store
    qdrant_mode: str          # memory | docker | local
    qdrant_url: str
    qdrant_path: Path
    qdrant_collection: str

    # embeddings
    embedding_backend: str    # hash | sentence-transformers | vllm
    embedding_dim: int
    embedding_base_url: str
    embedding_model: str

    # sentiment
    sentiment_backend: str    # lexicon | finbert

    # llm
    llm_backend: str          # mock | vllm
    openai_api_key: str
    drafting_base_url: str
    drafting_model: str
    analyst_base_url: str
    analyst_model: str
    verifier_base_url: str
    verifier_model: str


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    peers = [p.strip().upper() for p in _get("PEER_TICKERS", "AMD,INTC,AVGO").split(",") if p.strip()]
    return Settings(
        ticker=_get("DEMO_TICKER", "NVDA"),
        period=_get("DEMO_PERIOD", "FY2026Q1"),
        use_mock_data=_flag("USE_MOCK_DATA", "true"),
        peers=peers,
        artifacts_dir=_path("ARTIFACTS_DIR", "artifacts"),
        data_dir=_path("DATA_DIR", "data"),
        qdrant_mode=_get("QDRANT_MODE", "memory").lower(),
        qdrant_url=_get("QDRANT_URL", "http://localhost:6333"),
        qdrant_path=_path("QDRANT_PATH", "artifacts/qdrant"),
        qdrant_collection=_get("QDRANT_COLLECTION", "ir_wiki"),
        embedding_backend=_get("EMBEDDING_BACKEND", "hash").lower(),
        embedding_dim=int(_get("EMBEDDING_DIM", "384")),
        embedding_base_url=_get("EMBEDDING_BASE_URL", "http://mi300x-node:8002/v1"),
        embedding_model=_get("EMBEDDING_MODEL", "BAAI/bge-base-en-v1.5"),
        sentiment_backend=_get("SENTIMENT_BACKEND", "finbert").lower(),
        llm_backend=_get("LLM_BACKEND", "mock").lower(),
        openai_api_key=_get("OPENAI_API_KEY", "EMPTY"),
        drafting_base_url=_get("DRAFTING_BASE_URL", "http://mi300x-node:8000/v1"),
        drafting_model=_get("DRAFTING_MODEL", "meta-llama/Llama-3.1-70B-Instruct"),
        analyst_base_url=_get("ANALYST_BASE_URL", "http://mi300x-node:8001/v1"),
        analyst_model=_get("ANALYST_MODEL", "qpredict"),
        verifier_base_url=_get("VERIFIER_BASE_URL", "http://mi300x-node:8003/v1"),
        verifier_model=_get("VERIFIER_MODEL", "meta-llama/Llama-3.1-8B-Instruct"),
    )


settings = get_settings()
