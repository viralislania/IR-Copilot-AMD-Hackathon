"""Evidence corpus — REAL defeatbeta-api data (no placeholder URLs).

Offline (USE_MOCK_DATA=true): reads cached real data from mock/data/ (built by
mock/build_mock_data.py). Live (false): fetches fresh from defeatbeta-api. Either way every
news item carries its real article link and every transcript chunk carries real provenance
(ticker / fiscal period / speaker / paragraph + the HF dataset).
"""
from __future__ import annotations

from typing import List

from .config import settings
from . import mockdata


def news_items(ticker: str) -> List[dict]:
    """Recent news headlines with real article links — the sentiment + evidence source."""
    if settings.use_mock_data:
        return mockdata.load_news(ticker)
    from .live import fetch_news
    return fetch_news(ticker, limit=20)


def transcript_chunks(ticker: str) -> List[dict]:
    """Analyst Q&A transcript chunks with real provenance — the wiki source."""
    if settings.use_mock_data:
        return mockdata.load_transcript_chunks(ticker)
    from .live import fetch_transcript_qa
    import datetime as dt
    return fetch_transcript_qa(ticker, since_year=dt.date.today().year - 5)


def wiki_chunks_for(tickers: List[str]) -> List[dict]:
    out: List[dict] = []
    for tk in tickers:
        out.extend(transcript_chunks(tk))
    return out


# Backward-compatible module attrs (real cached data), precomputed only in offline mode so
# importing this module never triggers live network fetches. Used by notebooks.
if settings.use_mock_data:
    _TK = mockdata.available_tickers()
    TRANSCRIPT_CHUNKS: List[dict] = wiki_chunks_for(_TK)
    NEWS_HEADLINES: List[dict] = [it for tk in _TK for it in news_items(tk)]
else:
    TRANSCRIPT_CHUNKS = []
    NEWS_HEADLINES = []
SOCIAL_POSTS: List[dict] = []  # no real social source wired; sentiment uses real news only
