"""Reader for the cached REAL defeatbeta-api data under mock/data/ (built by mock/build_mock_data.py).

This is what the offline path (USE_MOCK_DATA=true) uses, so even offline the evidence is real,
cited defeatbeta-api data for TSLA / NVDA / AMD — never placeholder URLs.
"""
from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import List, Optional

from .config import ROOT
from .facts import FinancialFact, FactStore

MOCK_DIR = ROOT / "mock" / "data"


@lru_cache(maxsize=16)
def _load(ticker: str) -> Optional[dict]:
    p = MOCK_DIR / f"{ticker.upper()}.json"
    return json.loads(p.read_text()) if p.exists() else None


def available_tickers() -> List[str]:
    if not MOCK_DIR.exists():
        return []
    return sorted(p.stem.upper() for p in MOCK_DIR.glob("*.json"))


def has(ticker: str) -> bool:
    return _load(ticker) is not None


def period_for(ticker: str) -> Optional[str]:
    d = _load(ticker)
    return d["period"] if d else None


def load_fact_store(ticker: str, period: Optional[str] = None) -> Optional[FactStore]:
    d = _load(ticker)
    if not d:
        return None
    facts = [FinancialFact(**f) for f in d["facts"]]
    store = FactStore.from_facts(ticker, period or d["period"], facts)
    if period:
        for f in store.facts:
            f.period = period
    return store


def load_news(ticker: str) -> List[dict]:
    d = _load(ticker)
    return list(d["news"]) if d else []


def load_transcript_chunks(ticker: str) -> List[dict]:
    d = _load(ticker)
    return list(d["transcript_chunks"]) if d else []
