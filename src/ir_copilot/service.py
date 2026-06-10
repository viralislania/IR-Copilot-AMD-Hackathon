"""Service layer — all IR-Copilot capabilities as plain functions.

**Persistence guarantee (production):**
Every ticker queried in live mode is fully persisted to SQLite so that:
  - Subsequent calls for the same ticker never re-hit the live API (within the TTL).
  - Server restarts rebuild the Qdrant wiki index from SQLite without any network calls.
  - Any ticker works — not just the three pre-cached ones.

Data-type TTLs:
  - facts           : 24 h  (market data updates at most daily)
  - wiki_chunks     : 24 h
  - news            : 6 h   (headlines change faster)
  - signals         : 24 h

The FastAPI app and the notebooks both call these functions.
"""
from __future__ import annotations

from typing import List, Optional

from .cache import Cache
from .config import settings
from .corpus import news_items as _live_news, wiki_chunks as _live_wiki, signals as _live_signals
from .embeddings import get_embedder
from .facts import build_fact_store, FactStore
from .llm import get_chat
from .vectorstore import WikiChunk, WikiStore
from .agents.competitor import compare, PeerComparison
from .agents.drafting import draft, render_bundle
from .agents.predictive import predict_questions
from .agents.sentiment import analyze_sentiment, SentimentSnapshot

_cache = Cache()

# Process-level Qdrant index, keyed by frozenset of tickers.
# Rebuilt from SQLite on first access — no live API needed after the first fetch.
_wiki_store: dict[frozenset, WikiStore] = {}


def _period(period: Optional[str]) -> str:
    return period or settings.period


# ── Facts ─────────────────────────────────────────────────────────────────────

def get_fact_store(ticker: str, period: Optional[str] = None) -> FactStore:
    period = _period(period)
    cached = _cache.load_facts(ticker, period)
    if cached:
        return cached
    store = build_fact_store(ticker, period, use_mock=settings.use_mock_data)
    _cache.save_facts(store)
    return store


def get_facts(ticker: str, period: Optional[str] = None) -> dict:
    store = get_fact_store(ticker, period)
    return {"ticker": ticker, "period": store.period, "facts": store.to_records(),
            "gaps": store.gaps}


# ── Wiki chunks (all 6 doc types) ─────────────────────────────────────────────

def _get_wiki_chunks(ticker: str) -> List[dict]:
    """Return wiki chunks for a ticker, loading from SQLite cache or fetching live."""
    cached = _cache.load_ticker_data(ticker, "wiki_chunks", max_age_hours=24)
    if cached is not None:
        return cached
    chunks = _live_wiki(ticker)          # hits mockdata or live API
    if chunks:
        _cache.save_ticker_data(ticker, "wiki_chunks", chunks)
    return chunks


def get_wiki(tickers: List[str]) -> WikiStore:
    """
    Return (or build) the Qdrant wiki for a set of tickers.

    First call for a ticker set:
      - Loads chunks from SQLite (no live API if already cached).
      - Falls back to live fetch if not cached, then saves to SQLite.
      - Builds the in-memory Qdrant index.
    Subsequent calls within the same process: returns the cached WikiStore.
    New process: rebuilds Qdrant from SQLite (no live API needed).
    """
    key = frozenset(t.upper() for t in tickers)
    if key in _wiki_store:
        return _wiki_store[key]

    chunks: List[dict] = []
    for t in sorted(key):
        chunks.extend(_get_wiki_chunks(t))

    w = WikiStore(get_embedder())
    w.ensure_collection(recreate=True)
    if chunks:
        w.upsert([WikiChunk(chunk_id=str(i), **c) for i, c in enumerate(chunks)])
    _wiki_store[key] = w
    return w


def search_wiki(query: str, ticker: Optional[str] = None, k: int = 5) -> List[dict]:
    tickers = [ticker] if ticker else [settings.ticker, *settings.peers]
    return get_wiki(tickers).search(query, ticker=ticker, k=k)


# ── News + signals ─────────────────────────────────────────────────────────────

def _get_news(ticker: str) -> List[dict]:
    cached = _cache.load_ticker_data(ticker, "news", max_age_hours=6)
    if cached is not None:
        return cached
    items = _live_news(ticker)
    if items:
        _cache.save_ticker_data(ticker, "news", items)
    return items


def _get_signals(ticker: str) -> List[dict]:
    cached = _cache.load_ticker_data(ticker, "signals", max_age_hours=24)
    if cached is not None:
        return cached
    sigs = _live_signals(ticker)
    if sigs:
        _cache.save_ticker_data(ticker, "signals", sigs)
    return sigs


# ── High-level capabilities ───────────────────────────────────────────────────

def get_sentiment(ticker: str) -> SentimentSnapshot:
    return analyze_sentiment(ticker, _get_news(ticker))


def get_competitor(ticker: str, period: Optional[str] = None) -> PeerComparison:
    period = _period(period)
    company = get_fact_store(ticker, period)
    peers = {p: get_fact_store(p, period) for p in settings.peers}
    return compare(company, peers)


def get_questions(ticker: str, period: Optional[str] = None) -> List[dict]:
    period = _period(period)
    store = get_fact_store(ticker, period)
    snap = get_sentiment(ticker)
    pc = get_competitor(ticker, period)
    wiki = get_wiki([ticker, *settings.peers])
    qs = predict_questions(store, snap, pc, wiki=wiki, chat=get_chat("analyst"),
                           signals=_get_signals(ticker))
    return [q.model_dump() for q in qs]


def get_draft(ticker: str, period: Optional[str] = None) -> dict:
    period = _period(period)
    store = get_fact_store(ticker, period)
    snap = get_sentiment(ticker)
    pc = get_competitor(ticker, period)
    wiki = get_wiki([ticker, *settings.peers])
    qs = predict_questions(store, snap, pc, wiki=wiki, chat=get_chat("analyst"),
                           signals=_get_signals(ticker))
    bundle = draft(store, snap, pc, qs, chat=get_chat("drafting"))
    rendered = render_bundle(bundle, store)
    from .agents.verify import verify
    report = verify(rendered, store)
    return {"ticker": ticker, "period": period, "rendered": rendered,
            "verification": report.model_dump()}


# ── Cache management ──────────────────────────────────────────────────────────

def list_cached_tickers() -> List[dict]:
    """All tickers in the SQLite cache with freshness info."""
    return _cache.list_cached_tickers()


def invalidate_ticker(ticker: str) -> dict:
    """
    Delete all cached data for a ticker and evict the in-memory Qdrant index.
    The next request for this ticker will re-fetch live.
    """
    result = _cache.invalidate_ticker(ticker)
    t = ticker.upper()
    to_evict = [k for k in _wiki_store if t in k]
    for k in to_evict:
        del _wiki_store[k]
    result["wiki_indices_evicted"] = len(to_evict)
    return result
