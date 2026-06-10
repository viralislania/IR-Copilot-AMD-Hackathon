"""Generate offline mock data from the REAL defeatbeta-api and cache it under mock/data/.

The "mock" path is real, cited evidence (no example.com): facts (ratios, price, income lines,
segment/geo revenue), news with real article links, and a multimodal RAG corpus (transcript Q&A,
financial summaries, segment/geo breakdowns, SEC filings, news bodies) for TSLA / NVDA / AMD over
~5 years — plus structured YoY growth signals for question prediction.

Run on Python 3.11+ with network:
    .venv312/bin/python mock/build_mock_data.py
"""
from __future__ import annotations

import datetime as dt
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from ir_copilot.live import (  # noqa: E402
    fetch_facts, fetch_news, fetch_transcript_qa, fetch_financial_chunks,
    fetch_breakdown, fetch_filing_chunks, fetch_news_chunks,
)

TICKERS = ["NVDA", "AMD", "TSLA"]
SINCE_YEAR = dt.date.today().year - 5
DATA_DIR = Path(__file__).resolve().parent / "data"


def period_for(store) -> str:
    eps = store.get("ttm_eps") or (store.facts[0] if store.facts else None)
    if eps and eps.as_of:
        return f"FY{eps.as_of.year}Q{(eps.as_of.month - 1) // 3 + 1}"
    return "FY2026Q1"


def main():
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    for tk in TICKERS:
        print(f"[{tk}] facts...")
        store = fetch_facts(tk, "TMP")
        period = period_for(store)
        for f in store.facts:
            f.period = period

        print(f"[{tk}] news + multimodal chunks...")
        news = fetch_news(tk, limit=20)
        transcripts = fetch_transcript_qa(tk, since_year=SINCE_YEAR, max_calls=6, max_chunks_per_call=6)
        financial = fetch_financial_chunks(tk, period)
        seg_chunks, signals = fetch_breakdown(tk)
        filings = fetch_filing_chunks(tk, limit=12)
        news_chunks = fetch_news_chunks(tk, limit=8)
        wiki_chunks = transcripts + financial + seg_chunks + filings + news_chunks

        counts = {"transcript": len(transcripts), "financial": len(financial),
                  "segment/geo": len(seg_chunks), "filing": len(filings), "news": len(news_chunks)}
        print(f"[{tk}] period={period} facts={len(store.facts)} gaps={len(store.gaps)} "
              f"chunks={counts} signals={len(signals)}")

        payload = {
            "ticker": tk, "period": period, "fetched_at": dt.date.today().isoformat(),
            "facts": [json.loads(f.model_dump_json()) for f in store.facts],
            "gaps": store.gaps, "news": news, "wiki_chunks": wiki_chunks, "signals": signals,
        }
        out = DATA_DIR / f"{tk}.json"
        out.write_text(json.dumps(payload, indent=2))
        print(f"[{tk}] wrote {out} ({out.stat().st_size // 1024} KB)\n")
    print("MOCK_BUILD_OK")


if __name__ == "__main__":
    main()
