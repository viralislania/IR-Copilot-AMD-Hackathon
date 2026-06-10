"""Service layer — all IR-Copilot functionality as plain functions.

The FastAPI app and the notebooks both call these, so every capability is available
programmatically and over HTTP. Results are cached in SQLite.
"""
from __future__ import annotations

from typing import List, Optional

from .config import settings
from .cache import Cache
from .corpus import news_items, wiki_chunks_for
from .embeddings import get_embedder
from .facts import build_fact_store, FactStore
from .llm import get_chat
from .vectorstore import WikiChunk, WikiStore
from .agents.competitor import compare, PeerComparison
from .agents.drafting import draft, render_bundle
from .agents.predictive import predict_questions
from .agents.sentiment import analyze_sentiment, SentimentSnapshot

_cache = Cache()
_wiki_cache: dict[frozenset, WikiStore] = {}


def _period(period: Optional[str]) -> str:
    return period or settings.period


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


def get_wiki(tickers: List[str]) -> WikiStore:
    key = frozenset(t.upper() for t in tickers)
    if key not in _wiki_cache:
        w = WikiStore(get_embedder())
        w.ensure_collection(recreate=True)
        chunks = wiki_chunks_for(sorted(key))
        if chunks:
            w.upsert([WikiChunk(chunk_id=str(i), **c) for i, c in enumerate(chunks)])
        _wiki_cache[key] = w
    return _wiki_cache[key]


def search_wiki(query: str, ticker: Optional[str] = None, k: int = 5) -> List[dict]:
    tickers = [ticker] if ticker else [settings.ticker, *settings.peers]
    return get_wiki(tickers).search(query, ticker=ticker, k=k, doc_type="transcript")


def get_sentiment(ticker: str) -> SentimentSnapshot:
    return analyze_sentiment(ticker, news_items(ticker))


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
    from .corpus import signals as _signals
    qs = predict_questions(store, snap, pc, wiki=wiki, chat=get_chat("analyst"),
                           signals=_signals(ticker))
    return [q.model_dump() for q in qs]


def get_draft(ticker: str, period: Optional[str] = None) -> dict:
    period = _period(period)
    store = get_fact_store(ticker, period)
    snap = get_sentiment(ticker)
    pc = get_competitor(ticker, period)
    wiki = get_wiki([ticker, *settings.peers])
    from .corpus import signals as _signals
    qs = predict_questions(store, snap, pc, wiki=wiki, chat=get_chat("analyst"),
                           signals=_signals(ticker))
    bundle = draft(store, snap, pc, qs, chat=get_chat("drafting"))
    rendered = render_bundle(bundle, store)
    from .agents.verify import verify
    report = verify(rendered, store)
    return {"ticker": ticker, "period": period, "rendered": rendered,
            "verification": report.model_dump()}
