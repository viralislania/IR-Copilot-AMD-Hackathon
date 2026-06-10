# Data Sources

Financial data comes primarily from **`defeatbeta-api`** (an open-source Yahoo-Finance
alternative), with **`yfinance`** as a fallback for any gap.

## defeatbeta-api

- **pip:** `pip install defeatbeta-api` (Python 3.11+; Windows needs WSL/Docker for the
  `cache_httpfs` dependency).
- **Data hosting:** the Hugging Face `yahoo-finance-data` dataset, queried through DuckDB's
  OLAP engine + the `cache_httpfs` extension for sub-second analytical SQL.

```python
from defeatbeta_api.data.ticker import Ticker

t = Ticker("NVDA")
```

### Methods we use

| Metric | Method |
|---|---|
| Stock price (OHLCV) | `t.price()` |
| TTM EPS | `t.ttm_eps()` |
| TTM PE | `t.ttm_pe()` |
| Market cap (historical) | `t.historical_market_cap()` |
| PS ratio | `t.historical_ps_ratio()` |
| PB ratio | `t.historical_pb_ratio()` |
| PEG ratio | `t.historical_peg_ratio()` |
| ROE | `t.historical_roe()` |
| ROA | `t.historical_roa()` |
| ROIC | `t.historical_roic()` |
| WACC | `t.historical_wacc()` |
| Equity multiplier | `t.historical_equity_multiplier()` |
| Asset turnover | `t.historical_asset_turnover()` |
| Quarterly income statement | `t.quarterly_income_statement()` (`.print_pretty_table()`) |
| Earnings-call transcripts | `t.earning_call_transcripts()` → `.get_transcripts_list()`, `.get_transcript(year, quarter)` |
| SEC filings | `t.sec_filing()` |
| Stock news | `t.stock_news()` |
| Revenue by segment | `t.revenue_by_segment()` |
| Revenue by geography | `t.revenue_by_geography()` |

### Extraction → Fact Store

```python
def extract_facts(ticker: str, period: str) -> list[FinancialFact]:
    t = Ticker(ticker)
    raw = {
        "ttm_eps": t.ttm_eps(), "ttm_pe": t.ttm_pe(),
        "market_cap": t.historical_market_cap(),
        "ps_ratio": t.historical_ps_ratio(), "pb_ratio": t.historical_pb_ratio(),
        "peg_ratio": t.historical_peg_ratio(),
        "roe": t.historical_roe(), "roa": t.historical_roa(),
        "roic": t.historical_roic(), "wacc": t.historical_wacc(),
        "equity_multiplier": t.historical_equity_multiplier(),
        "asset_turnover": t.historical_asset_turnover(),
        "income_stmt": t.quarterly_income_statement(),
        "revenue_segment": t.revenue_by_segment(),
        "revenue_geo": t.revenue_by_geography(),
    }
    return [to_fact(metric, df, period, ticker) for metric, df in raw.items()]
```

Each `to_fact(...)` records `value`, `unit`, `period`, `source`, `source_url`, `as_of`, and a
stable `fact_id`. See [Grounding & Evidence](grounding.md) for the schema and why this matters.

## yfinance fallback

If a `defeatbeta-api` call is empty or rate-limited, fall back to `yfinance` for the same
field and tag the fact's `source` accordingly, so provenance stays honest.

```python
import yfinance as yf
def fallback_market_cap(ticker: str) -> float | None:
    info = yf.Ticker(ticker).fast_info
    return getattr(info, "market_cap", None)
```

## Caching for a reliable demo

- Pre-fetch the demo ticker(s) into a local **DuckDB** cache so the live demo never depends on
  network latency or upstream availability.
- Cache embeddings and a recorded transcript too (see [Wiki](wiki-ingestion.md)).

## Demo / fine-tune datasets (Hugging Face & Kaggle)

| Dataset | Use |
|---|---|
| HF `jlh-ibm/earnings_call` | transcripts + labels for RAG & fine-tune |
| HF `lamini/earnings-calls-qa` | (context → analyst Q&A) pairs for [fine-tuning](finetuning.md) |
| HF `financial_phrasebank` | sentiment baseline / FinBERT eval |
| Kaggle Motley-Fool Earnings Transcripts | transcript corpus for the wiki |
| Kaggle stock-tweets datasets | social-sentiment demo source |

These keep the demo fully reproducible without any paid API.
