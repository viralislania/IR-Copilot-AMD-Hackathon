"""Live data from the real defeatbeta-api (docs/data-sources.md).

Requires Python 3.11+ and network (defeatbeta-api downloads a DuckDB extension + HF parquet on
first use). Column names/units below are verified against the actual package — ratios like
ROE/ROA/ROIC/WACC and margins come back as FRACTIONS (0..1) and are converted to percent here.

Used when USE_MOCK_DATA=false. The offline path reads cached real data from /mock instead.
"""
from __future__ import annotations

from typing import List, Optional

import pandas as pd

from .facts import FactStore

HF_DATASET = "https://huggingface.co/datasets/defeatbeta/yahoo-finance-data"

# metric -> (Ticker method, value column, unit, is_fraction)
METRIC_SPECS = [
    ("ttm_eps", "ttm_eps", "tailing_eps", "USD", False),
    ("ttm_pe", "ttm_pe", "ttm_pe", "x", False),
    ("market_cap", "market_capitalization", "market_capitalization", "USD", False),
    ("ps_ratio", "ps_ratio", "ps_ratio", "x", False),
    ("pb_ratio", "pb_ratio", "pb_ratio", "x", False),
    ("peg_ratio", "peg_ratio", "peg_ratio", "x", False),
    ("roe", "roe", "roe", "%", True),
    ("roa", "roa", "roa", "%", True),
    ("roic", "roic", "roic", "%", True),
    ("wacc", "wacc", "wacc", "%", True),
    ("equity_multiplier", "equity_multiplier", "equity_multiplier", "x", False),
    ("asset_turnover", "asset_turnover", "asset_turnover", "x", False),
]


def _latest(df: pd.DataFrame, value_col: str):
    """Return (value, report_date) for the most recent row."""
    if df is None or df.empty or value_col not in df.columns:
        raise ValueError(f"missing column {value_col!r}")
    d = df.sort_values("report_date") if "report_date" in df.columns else df
    row = d.iloc[-1]
    val = row[value_col]
    if pd.isna(val):
        raise ValueError(f"NaN value for {value_col!r}")
    as_of = str(row["report_date"])[:10] if "report_date" in df.columns else None
    return float(val), as_of


def fetch_facts(ticker: str, period: str) -> FactStore:
    from defeatbeta_api.data.ticker import Ticker
    import datetime as dt

    t = Ticker(ticker)
    store = FactStore(ticker, period)

    def _add(metric, value, unit, method, as_of):
        store.add(metric, value, unit, source=f"defeatbeta-api:{method}",
                  source_url=HF_DATASET,
                  as_of=dt.date.fromisoformat(as_of) if as_of else None)

    for metric, method, col, unit, is_frac in METRIC_SPECS:
        try:
            val, as_of = _latest(getattr(t, method)(), col)
            _add(metric, val * 100 if is_frac else val, unit, method, as_of)
        except Exception as e:  # pragma: no cover
            store.record_gap(metric, f"{type(e).__name__}: {e}")

    # margins + quarterly revenue come from the margin frames (total_revenue lives there)
    try:
        gm = getattr(t, "quarterly_gross_margin")()
        val, as_of = _latest(gm, "gross_margin")
        _add("gross_margin", val * 100, "%", "quarterly_gross_margin", as_of)
        rev, as_of_r = _latest(gm, "total_revenue")
        _add("revenue", rev, "USD", "quarterly_gross_margin.total_revenue", as_of_r)
    except Exception as e:  # pragma: no cover
        store.record_gap("gross_margin/revenue", f"{type(e).__name__}: {e}")
    try:
        om = getattr(t, "quarterly_operating_margin")()
        val, as_of = _latest(om, "operating_margin")
        _add("operating_margin", val * 100, "%", "quarterly_operating_margin", as_of)
    except Exception as e:  # pragma: no cover
        store.record_gap("operating_margin", f"{type(e).__name__}: {e}")

    return store


def fetch_news(ticker: str, limit: int = 20) -> List[dict]:
    """Recent news with REAL article links (the citation URL)."""
    from defeatbeta_api.data.ticker import Ticker
    nl = Ticker(ticker).news().get_news_list()
    nl = nl.sort_values("report_date", ascending=False).head(limit)
    out = []
    for _, r in nl.iterrows():
        out.append({"ticker": ticker, "text": str(r["title"]),
                    "url": str(r.get("link", "")), "publisher": str(r.get("publisher", "")),
                    "date": str(r.get("report_date", ""))[:10], "uuid": str(r.get("uuid", ""))})
    return out


def fetch_transcript_qa(ticker: str, since_year: int, max_calls: int = 6,
                        max_chunks_per_call: int = 6) -> List[dict]:
    """Analyst Q&A paragraphs from recent earnings calls, with real provenance."""
    from defeatbeta_api.data.ticker import Ticker
    tr = Ticker(ticker).earning_call_transcripts()
    lst = tr.get_transcripts_list()
    lst = lst[lst["fiscal_year"] >= since_year].sort_values(
        ["fiscal_year", "fiscal_quarter"], ascending=False).head(max_calls)

    chunks: List[dict] = []
    for _, call in lst.iterrows():
        fy, fq = int(call["fiscal_year"]), int(call["fiscal_quarter"])
        try:
            df = tr.get_transcript(fy, fq)
        except Exception:
            continue
        taken = 0
        for _, p in df.iterrows():
            speaker = str(p.get("speaker", ""))
            content = str(p.get("content", "")).strip()
            is_q = "?" in content and (len(content) > 40)
            if not is_q:
                continue
            chunks.append({
                "ticker": ticker, "doc_type": "transcript",
                "period": f"FY{fy}Q{fq}", "role": "analyst", "speaker": speaker,
                "paragraph": int(p.get("paragraph_number", 0)),
                "text": content[:600],
                "source_url": f"{HF_DATASET} (earning_call_transcripts {ticker} FY{fy}Q{fq}, "
                              f"speaker={speaker}, para={int(p.get('paragraph_number', 0))})",
            })
            taken += 1
            if taken >= max_chunks_per_call:
                break
    return chunks
