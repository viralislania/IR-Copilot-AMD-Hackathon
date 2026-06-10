"""Generate offline mock data from the REAL defeatbeta-api and cache it under mock/data/.

The "mock" path is therefore real, cited evidence (no example.com) — facts, news with real
article links, and analyst Q&A transcript chunks for TSLA / NVDA / AMD over the past ~5 years.

Run on Python 3.11+ with network (defeatbeta-api requirement):
    .venv312/bin/python mock/build_mock_data.py
"""
from __future__ import annotations

import datetime as dt
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from ir_copilot.live import fetch_facts, fetch_news, fetch_transcript_qa  # noqa: E402

TICKERS = ["NVDA", "AMD", "TSLA"]
SINCE_YEAR = dt.date.today().year - 5
DATA_DIR = Path(__file__).resolve().parent / "data"


def period_for(store) -> str:
    eps = store.get("ttm_eps") or (store.facts[0] if store.facts else None)
    if eps and eps.as_of:
        m = eps.as_of.month
        q = (m - 1) // 3 + 1
        return f"FY{eps.as_of.year}Q{q}"
    return "FY2026Q1"


def main():
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    for tk in TICKERS:
        print(f"[{tk}] fetching facts...")
        store = fetch_facts(tk, "TMP")
        period = period_for(store)
        for f in store.facts:
            f.period = period
        print(f"[{tk}] period={period}  facts={len(store.facts)}  gaps={len(store.gaps)}")

        print(f"[{tk}] fetching news...")
        news = fetch_news(tk, limit=20)
        print(f"[{tk}] news={len(news)}")

        print(f"[{tk}] fetching transcript Q&A since {SINCE_YEAR}...")
        chunks = fetch_transcript_qa(tk, since_year=SINCE_YEAR, max_calls=6, max_chunks_per_call=6)
        print(f"[{tk}] transcript_chunks={len(chunks)}")

        payload = {
            "ticker": tk,
            "period": period,
            "fetched_at": dt.date.today().isoformat(),
            "facts": [json.loads(f.model_dump_json()) for f in store.facts],
            "gaps": store.gaps,
            "news": news,
            "transcript_chunks": chunks,
        }
        out = DATA_DIR / f"{tk}.json"
        out.write_text(json.dumps(payload, indent=2))
        print(f"[{tk}] wrote {out}  ({out.stat().st_size//1024} KB)\n")
    print("MOCK_BUILD_OK")


if __name__ == "__main__":
    main()
