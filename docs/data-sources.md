# Data Sources

Financial data comes from **`defeatbeta-api`** (an open-source Yahoo-Finance alternative). It
covers every metric we need for NVDA/AMD/TSLA; `yfinance` remains an optional gap-filler but is
not currently wired.

## defeatbeta-api

- **pip:** `pip install defeatbeta-api` (Python 3.11+; Windows needs WSL/Docker for the
  `cache_httpfs` dependency).
- **Data hosting:** the Hugging Face `yahoo-finance-data` dataset, queried through DuckDB's
  OLAP engine + the `cache_httpfs` extension for sub-second analytical SQL.

```python
from defeatbeta_api.data.ticker import Ticker

t = Ticker("NVDA")
```

### Methods we use (verified against the real package)

The method names below are the **actual** `Ticker` API (confirmed against the local
defeatbeta-api source — earlier guesses like `historical_roe()` were wrong). Each returns a
pandas DataFrame; the value is the last column of the most recent `report_date` row. Ratios and
margins come back as **fractions (0..1)** and are converted to percent in `live.py`.

| Metric | Method | Value column | Unit |
|---|---|---|---|
| TTM EPS | `t.ttm_eps()` | `tailing_eps` | USD |
| TTM PE | `t.ttm_pe()` | `ttm_pe` | x |
| Market cap | `t.market_capitalization()` | `market_capitalization` | USD |
| PS ratio | `t.ps_ratio()` | `ps_ratio` | x |
| PB ratio | `t.pb_ratio()` | `pb_ratio` | x |
| PEG ratio | `t.peg_ratio()` | `peg_ratio` | x |
| ROE | `t.roe()` | `roe` (fraction) | % |
| ROA | `t.roa()` | `roa` (fraction) | % |
| ROIC | `t.roic()` | `roic` (fraction) | % |
| WACC | `t.wacc()` | `wacc` (fraction) | % |
| Equity multiplier | `t.equity_multiplier()` | `equity_multiplier` | x |
| Asset turnover | `t.asset_turnover()` | `asset_turnover` | x |
| Gross margin + revenue | `t.quarterly_gross_margin()` | `gross_margin` (frac), `total_revenue` | %, USD |
| Operating margin | `t.quarterly_operating_margin()` | `operating_margin` (frac) | % |
| Earnings-call transcripts | `t.earning_call_transcripts()` → `.get_transcripts_list()` (`symbol, fiscal_year, fiscal_quarter, report_date`), `.get_transcript(y, q)` (`paragraph_number, speaker, content`) | — | — |
| Stock news | `t.news()` → `.get_news_list()` (`uuid, title, publisher, report_date, type, link`), `.get_news(uuid)` | — | — |
| SEC filings | `t.sec_filing()` | — | — |
| Revenue breakdown | `t.quarterly_revenue_by_breakdown()` | segment/geography | USD |

Implementation: `src/ir_copilot/live.py` (`fetch_facts`,
`fetch_news`, `fetch_transcript_qa`). Each fact records `value`, `unit`, `period`, `source`
(e.g. `defeatbeta-api:roe`), `source_url` (the HF dataset), `as_of`, and a stable `fact_id` —
see [Grounding & Evidence](grounding.md).

### Requirements & offline cache

- **Python 3.11+** and network: defeatbeta-api downloads a DuckDB `cache_httpfs` extension and
  HuggingFace parquet on first use. Use a 3.12 venv (see README).
- **Offline = real cached data.** `mock/build_mock_data.py` fetches facts + news (with real
  article links) + analyst-Q&A transcript chunks for **NVDA / AMD / TSLA** over ~5 years into
  `mock/data/*.json`. With `USE_MOCK_DATA=true`, IR-Copilot reads those — so even offline the
  evidence is real, cited defeatbeta-api data (no placeholder URLs).

## Persistence & caching (SQLite)

IR-Copilot persists with **SQLite** (`artifacts/ir_copilot.sqlite`,
`cache.py`) — a relational `facts` table (grounded financials are
queryable with plain SQL) plus a JSON-blob table for agent outputs. There is **no parquet/duckdb
in IR-Copilot itself**; `duckdb` only appears transitively inside defeatbeta-api. The service
layer checks the SQLite cache before any (re)fetch, so repeated calls and the demo are fast and
reproducible.

> Missing metrics are recorded as explicit `gaps` (never silently dropped). All listed metrics
> return for NVDA/AMD/TSLA, so no `yfinance` fallback is currently wired; it remains an option if
> a future ticker has gaps.

## Demo / fine-tune datasets (Hugging Face & Kaggle)

| Dataset | Use |
|---|---|
| HF `jlh-ibm/earnings_call` | transcripts + labels for RAG & fine-tune |
| HF `lamini/earnings-calls-qa` | (context → analyst Q&A) pairs for [fine-tuning](finetuning.md) |
| HF `financial_phrasebank` | sentiment baseline / FinBERT eval |
| Kaggle Motley-Fool Earnings Transcripts | transcript corpus for the wiki |
| Kaggle stock-tweets datasets | social-sentiment demo source |

These keep the demo fully reproducible without any paid API.
