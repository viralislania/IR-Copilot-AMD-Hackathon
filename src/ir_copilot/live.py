"""Live data from the real defeatbeta-api (docs/data-sources.md).

Requires Python 3.11+ and network. Column names/units below are verified against the actual
package. Ratios/margins come back as FRACTIONS (0..1) and are converted to percent here.

Produces three things for the rest of the system:
  * facts          — grounded numbers (ratios, price, income lines, segment/geo revenue)
  * wiki_chunks    — ALL doc types for RAG: transcript | financial | segment | geo | filing | news
  * signals        — structured YoY movers (segments, net income) for question prediction

Offline (USE_MOCK_DATA=true) reads these from mock/data/ instead (built by mock/build_mock_data.py).
"""
from __future__ import annotations

import datetime as dt
from typing import List, Optional, Tuple

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

# income-statement line items to capture as facts (matched case-insensitively by substring)
INCOME_FACT_LINES = [
    ("gross_profit", "gross profit"),
    ("operating_income", "operating income"),
    ("net_income", "net income common"),
    ("rnd_expense", "research"),
]

_MATERIAL_FORMS = {"10-K", "10-Q", "8-K", "S-1", "424B"}


def _latest(df: pd.DataFrame, value_col: str) -> Tuple[float, Optional[str]]:
    if df is None or df.empty or value_col not in df.columns:
        raise ValueError(f"missing column {value_col!r}")
    d = df.sort_values("report_date") if "report_date" in df.columns else df
    row = d.iloc[-1]
    val = row[value_col]
    if pd.isna(val):
        raise ValueError(f"NaN value for {value_col!r}")
    as_of = str(row["report_date"])[:10] if "report_date" in df.columns else None
    return float(val), as_of


def _as_date(s: Optional[str]):
    try:
        return dt.date.fromisoformat(s) if s else None
    except Exception:
        return None


def _to_float(v) -> Optional[float]:
    try:
        f = float(v)
        return f
    except (TypeError, ValueError):
        return None


# ---------------------------------------------------------------- facts
def fetch_facts(ticker: str, period: str) -> FactStore:
    from defeatbeta_api.data.ticker import Ticker

    t = Ticker(ticker)
    store = FactStore(ticker, period)

    def add(metric, value, unit, method, as_of):
        store.add(metric, value, unit, source=f"defeatbeta-api:{method}",
                  source_url=HF_DATASET, as_of=_as_date(as_of))

    # valuation / profitability ratios
    for metric, method, col, unit, is_frac in METRIC_SPECS:
        try:
            val, as_of = _latest(getattr(t, method)(), col)
            add(metric, val * 100 if is_frac else val, unit, method, as_of)
        except Exception as e:  # pragma: no cover
            store.record_gap(metric, f"{type(e).__name__}: {e}")

    # price (latest close)
    try:
        val, as_of = _latest(t.price(), "close")
        add("price", val, "USD", "price.close", as_of)
    except Exception as e:  # pragma: no cover
        store.record_gap("price", f"{type(e).__name__}: {e}")

    # margins + quarterly revenue (total_revenue lives in the margin frames)
    try:
        gm = t.quarterly_gross_margin()
        val, as_of = _latest(gm, "gross_margin")
        add("gross_margin", val * 100, "%", "quarterly_gross_margin", as_of)
        rev, as_of_r = _latest(gm, "total_revenue")
        add("revenue", rev, "USD", "quarterly_gross_margin.total_revenue", as_of_r)
    except Exception as e:  # pragma: no cover
        store.record_gap("gross_margin/revenue", f"{type(e).__name__}: {e}")
    try:
        val, as_of = _latest(t.quarterly_operating_margin(), "operating_margin")
        add("operating_margin", val * 100, "%", "quarterly_operating_margin", as_of)
    except Exception as e:  # pragma: no cover
        store.record_gap("operating_margin", f"{type(e).__name__}: {e}")

    # income-statement line items
    try:
        inc = t.quarterly_income_statement().df()
        qcol = inc.columns[2]  # latest quarter (after 'Breakdown', 'TTM')
        for metric, sub in INCOME_FACT_LINES:
            row = inc[inc["Breakdown"].str.lower().str.contains(sub, na=False)]
            if not row.empty:
                v = _to_float(row.iloc[0][qcol])
                if v is not None:
                    add(metric, v, "USD", f"quarterly_income_statement[{row.iloc[0]['Breakdown']}]",
                        str(qcol)[:10])
    except Exception as e:  # pragma: no cover
        store.record_gap("income_statement", f"{type(e).__name__}: {e}")

    # revenue by segment / geography (latest quarter, one fact per series)
    try:
        br = t.quarterly_revenue_by_breakdown()
        for breakdown_name, prefix in [("Revenue by Segment", "revenue_segment"),
                                       ("Revenue by Geography", "revenue_geo")]:
            sub = br[br["breakdown_name"] == breakdown_name]
            if sub.empty:
                continue
            latest = sub["report_date"].max()
            for _, r in sub[sub["report_date"] == latest].iterrows():
                v = _to_float(r["value"])
                if v is not None:
                    add(f"{prefix}:{r['series_name']}", v, "USD",
                        f"quarterly_revenue_by_breakdown[{breakdown_name}]", str(latest)[:10])
    except Exception as e:  # pragma: no cover
        store.record_gap("revenue_breakdown", f"{type(e).__name__}: {e}")

    return store


# ---------------------------------------------------------------- news (for sentiment)
def fetch_news(ticker: str, limit: int = 20) -> List[dict]:
    from defeatbeta_api.data.ticker import Ticker
    nl = Ticker(ticker).news().get_news_list().sort_values("report_date", ascending=False).head(limit)
    return [{"ticker": ticker, "text": str(r["title"]), "url": str(r.get("link", "")),
             "publisher": str(r.get("publisher", "")), "date": str(r.get("report_date", ""))[:10],
             "uuid": str(r.get("uuid", ""))} for _, r in nl.iterrows()]


# ---------------------------------------------------------------- wiki chunks (RAG: all doc types)
def fetch_transcript_qa(ticker: str, since_year: int, max_calls: int = 6,
                        max_chunks_per_call: int = 6) -> List[dict]:
    """Analyst Q&A from recent calls. Role is classified per speaker (P1 fix), not assumed."""
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
            if not _is_analyst_question(speaker, content):
                continue
            chunks.append({
                "ticker": ticker, "doc_type": "transcript", "modality": "transcript",
                "period": f"FY{fy}Q{fq}", "role": "analyst", "speaker": speaker,
                "paragraph": int(p.get("paragraph_number", 0)), "text": content[:600],
                "source_url": f"{HF_DATASET} (earning_call_transcripts {ticker} FY{fy}Q{fq}, "
                              f"speaker={speaker}, para={int(p.get('paragraph_number', 0))})",
            })
            taken += 1
            if taken >= max_chunks_per_call:
                break
    return chunks


_EXEC_HINTS = ("chief", "officer", "ceo", "cfo", "president", "founder", "vp ", "head of",
               "treasurer", "operator")


def _is_analyst_question(speaker: str, content: str) -> bool:
    """Heuristic: a question ('?') from someone who is NOT an exec/operator."""
    if "?" not in content or len(content) < 40:
        return False
    s = speaker.lower()
    if any(h in s for h in _EXEC_HINTS):
        return False
    return True


def fetch_financial_chunks(ticker: str, period: str) -> List[dict]:
    """Income-statement narrative with YoY — grounds revenue/margin/net-income claims."""
    from defeatbeta_api.data.ticker import Ticker
    try:
        inc = Ticker(ticker).quarterly_income_statement().df()
    except Exception:
        return []
    cols = list(inc.columns)
    if len(cols) < 7:
        return []
    qcol, yoy_col = cols[2], cols[6]  # latest quarter vs same quarter prior year

    def line(sub):
        row = inc[inc["Breakdown"].str.lower().str.contains(sub, na=False)]
        if row.empty:
            return None, None
        return _to_float(row.iloc[0][qcol]), _to_float(row.iloc[0][yoy_col])

    parts = []
    for label, sub in [("Total revenue", "total revenue"), ("Gross profit", "gross profit"),
                       ("Operating income", "operating income"), ("Net income", "net income common")]:
        cur, prev = line(sub)
        if cur is None:
            continue
        yoy = f" ({(cur - prev) / prev * 100:+.0f}% YoY)" if prev else ""
        parts.append(f"{label} ${cur/1e9:.2f}B{yoy}")
    if not parts:
        return []
    return [{"ticker": ticker, "doc_type": "financial", "modality": "table", "period": period,
             "text": f"{ticker} {period} income statement ({qcol}): " + "; ".join(parts) + ".",
             "source_url": f"{HF_DATASET} (quarterly_income_statement {ticker})"}]


def fetch_breakdown(ticker: str) -> Tuple[List[dict], List[dict]]:
    """Returns (wiki_chunks, signals) for segment/geography/platform breakdowns with YoY."""
    from defeatbeta_api.data.ticker import Ticker
    try:
        br = Ticker(ticker).quarterly_revenue_by_breakdown()
    except Exception:
        return [], []
    REV_FLOOR = 5e8     # ignore sub-$0.5B lines (taxonomy noise / discontinued series)
    YOY_CAP = 200.0     # ignore swings beyond ±200% (series appeared/disappeared / reclassified)
    chunks, signals = [], []
    specs = [("Revenue by Segment", "segment", "revenue_segment"),
             ("Revenue by Geography", "geo", "revenue_geo"),
             ("Revenue by Market Platform", "segment", "revenue_platform")]
    for breakdown_name, doc_type, metric_prefix in specs:
        sub = br[br["breakdown_name"] == breakdown_name]
        if sub.empty:
            continue
        latest = sorted(sub["report_date"].unique())[-1]
        lines = []
        for _, r in sub[sub["report_date"] == latest].sort_values("value", ascending=False).iterrows():
            series, cur = str(r["series_name"]), _to_float(r["value"])
            if cur is None or cur < REV_FLOOR:
                continue
            # per-series YoY: this series' own value ~4 quarters before its latest date
            hist = sub[sub["series_name"] == series].sort_values("report_date")
            prev = _to_float(hist.iloc[-5]["value"]) if len(hist) >= 5 else None
            yoy = (cur - prev) / prev * 100 if (prev and prev >= REV_FLOOR) else None
            phrase = series if series.lower().endswith(("revenue", "segment")) else f"{series} revenue"
            lines.append(f"{phrase} ${cur/1e9:.2f}B" + (f" ({yoy:+.0f}% YoY)" if yoy is not None else ""))
            if yoy is not None and 15 <= abs(yoy) <= YOY_CAP:
                signals.append({"label": f"{phrase} ({breakdown_name})", "series": phrase,
                                "metric": metric_prefix, "change_pct": round(yoy, 1),
                                "direction": "up" if yoy >= 0 else "down",
                                "evidence_url": f"{HF_DATASET} (quarterly_revenue_by_breakdown "
                                                f"{ticker} {breakdown_name})"})
        if lines:
            chunks.append({"ticker": ticker, "doc_type": doc_type, "modality": "table",
                           "period": str(latest)[:10],
                           "text": f"{ticker} {breakdown_name} ({str(latest)[:10]}): " + "; ".join(lines) + ".",
                           "source_url": f"{HF_DATASET} (quarterly_revenue_by_breakdown {ticker} {breakdown_name})"})
    # keep the top movers by magnitude
    signals.sort(key=lambda s: -abs(s["change_pct"]))
    return chunks, signals[:6]


def fetch_filing_chunks(ticker: str, limit: int = 12) -> List[dict]:
    """Recent material SEC filings (10-K/10-Q/8-K…) with real sec.gov URLs."""
    from defeatbeta_api.data.ticker import Ticker
    try:
        sf = Ticker(ticker).sec_filing()
    except Exception:
        return []
    sf = sf[sf["form_type"].isin(_MATERIAL_FORMS)].sort_values("filing_date", ascending=False).head(limit)
    out = []
    for _, r in sf.iterrows():
        out.append({"ticker": ticker, "doc_type": "filing", "modality": "filing",
                    "period": str(r.get("report_date", ""))[:10],
                    "text": f"{ticker} SEC {r['form_type']} — {r.get('form_type_description','')} "
                            f"filed {str(r['filing_date'])[:10]} (period {str(r.get('report_date',''))[:10]}).",
                    "source_url": str(r.get("filing_url", ""))})
    return out


def fetch_news_chunks(ticker: str, limit: int = 8) -> List[dict]:
    """Top news with article bodies (real links) — sentiment drivers + citeable evidence."""
    from defeatbeta_api.data.ticker import Ticker
    news = Ticker(ticker).news()
    nl = news.get_news_list().sort_values("report_date", ascending=False).head(limit)
    out = []
    for _, r in nl.iterrows():
        body = ""
        try:
            paras = news.get_news(str(r["uuid"])).iloc[0]["news"]
            body = " ".join(p.get("paragraph", "") for p in paras[:2])
        except Exception:
            body = str(r["title"])
        out.append({"ticker": ticker, "doc_type": "news", "modality": "news",
                    "period": str(r.get("report_date", ""))[:10],
                    "text": f"{r['title']} — {body}"[:600], "source_url": str(r.get("link", ""))})
    return out


def fetch_wiki_chunks(ticker: str, since_year: Optional[int] = None) -> List[dict]:
    """All RAG doc types for a ticker (used live; offline reads the cached equivalent)."""
    since_year = since_year or (dt.date.today().year - 5)
    chunks = fetch_transcript_qa(ticker, since_year=since_year)
    chunks += fetch_financial_chunks(ticker, period="latest")
    seg_chunks, _ = fetch_breakdown(ticker)
    chunks += seg_chunks
    chunks += fetch_filing_chunks(ticker)
    chunks += fetch_news_chunks(ticker)
    return chunks
