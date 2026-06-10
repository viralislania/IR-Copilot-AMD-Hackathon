"""Financial Fact Store — the grounding backbone (docs/grounding.md).

Numbers live ONLY here. Agents receive fact_ids and write slots ({{F-0003}}); the renderer
substitutes verified values. Nothing is ever silently dropped — gaps are recorded.
"""
from __future__ import annotations

import datetime as dt
import json
import re
from pathlib import Path
from typing import Optional

import pandas as pd
from pydantic import BaseModel

# (metric, defeatbeta-api Ticker method, unit) — confirmed in docs/data-sources.md
SPECS: list[tuple[str, str, str]] = [
    ("ttm_eps", "ttm_eps", "USD"),
    ("ttm_pe", "ttm_pe", "x"),
    ("market_cap", "historical_market_cap", "USD"),
    ("ps_ratio", "historical_ps_ratio", "x"),
    ("pb_ratio", "historical_pb_ratio", "x"),
    ("peg_ratio", "historical_peg_ratio", "x"),
    ("roe", "historical_roe", "%"),
    ("roa", "historical_roa", "%"),
    ("roic", "historical_roic", "%"),
    ("wacc", "historical_wacc", "%"),
    ("equity_multiplier", "historical_equity_multiplier", "x"),
    ("asset_turnover", "historical_asset_turnover", "x"),
]

UNITS = {m: u for m, _, u in SPECS} | {
    "revenue": "USD", "gross_margin": "%", "operating_margin": "%"}

MOCK_URL = "https://huggingface.co/datasets/defeat-beta/yahoo-finance-data"

# Deterministic demo snapshots (illustrative). Used when use_mock or a live call fails.
MOCK_SNAPSHOTS: dict[str, dict[str, float]] = {
    "NVDA": {"ttm_eps": 3.10, "ttm_pe": 38.5, "market_cap": 3.02e12, "ps_ratio": 28.4,
             "pb_ratio": 45.1, "peg_ratio": 1.2, "roe": 91.3, "roa": 55.2, "roic": 78.0,
             "wacc": 11.5, "equity_multiplier": 1.65, "asset_turnover": 0.95,
             "revenue": 44.06e9, "gross_margin": 75.0, "operating_margin": 64.9},
    "AMD":  {"ttm_eps": 1.10, "ttm_pe": 95.0, "market_cap": 2.70e11, "ps_ratio": 11.5,
             "pb_ratio": 4.8, "peg_ratio": 1.6, "roe": 6.5, "roa": 3.9, "roic": 4.2,
             "wacc": 10.8, "equity_multiplier": 1.30, "asset_turnover": 0.42,
             "revenue": 24.30e9, "gross_margin": 51.0, "operating_margin": 7.0},
    "INTC": {"ttm_eps": -0.40, "ttm_pe": 0.0, "market_cap": 9.50e10, "ps_ratio": 1.8,
             "pb_ratio": 0.9, "peg_ratio": 0.0, "roe": -2.5, "roa": -1.1, "roic": -0.8,
             "wacc": 9.5, "equity_multiplier": 2.05, "asset_turnover": 0.30,
             "revenue": 53.10e9, "gross_margin": 40.0, "operating_margin": -2.0},
    "AVGO": {"ttm_eps": 4.20, "ttm_pe": 60.0, "market_cap": 1.20e12, "ps_ratio": 22.0,
             "pb_ratio": 13.0, "peg_ratio": 1.4, "roe": 18.0, "roa": 6.5, "roic": 9.0,
             "wacc": 10.0, "equity_multiplier": 2.40, "asset_turnover": 0.28,
             "revenue": 51.60e9, "gross_margin": 63.0, "operating_margin": 30.0},
}


class FinancialFact(BaseModel):
    fact_id: str
    ticker: str
    metric: str
    period: str
    value: float
    unit: str
    source: str
    source_url: Optional[str] = None
    as_of: dt.date


class FactStore:
    def __init__(self, ticker: str, period: str):
        self.ticker, self.period = ticker, period
        self._facts: list[FinancialFact] = []
        self.gaps: list[dict] = []
        self._n = 0

    @classmethod
    def from_facts(cls, ticker: str, period: str, facts: list) -> "FactStore":
        """Rebuild a store from a list of FinancialFact (e.g. from serialized graph state)."""
        s = cls(ticker, period)
        s._facts = [f if isinstance(f, FinancialFact) else FinancialFact(**f) for f in facts]
        s._n = len(s._facts)
        return s

    def add(self, metric, value, unit, source, source_url=None, as_of=None) -> FinancialFact:
        self._n += 1
        fact = FinancialFact(
            fact_id=f"F-{self._n:04d}", ticker=self.ticker, metric=metric,
            period=self.period, value=float(value), unit=unit, source=source,
            source_url=source_url, as_of=as_of or dt.date.today())
        self._facts.append(fact)
        return fact

    def record_gap(self, metric, reason):
        self.gaps.append({"metric": metric, "reason": str(reason)[:160]})

    @property
    def facts(self) -> list[FinancialFact]:
        return self._facts

    def get(self, metric) -> Optional[FinancialFact]:
        return next((f for f in self._facts if f.metric == metric), None)

    def by_id(self, fact_id) -> Optional[FinancialFact]:
        return next((f for f in self._facts if f.fact_id == fact_id), None)

    def slot(self, metric) -> str:
        """Return the slot token ({{F-00xx}}) for a metric, for the drafting agent."""
        f = self.get(metric)
        return f"{{{{{f.fact_id}}}}}" if f else "{{?}}"

    def value(self, metric) -> Optional[float]:
        f = self.get(metric)
        return f.value if f else None

    def to_dataframe(self) -> pd.DataFrame:
        return pd.DataFrame([f.model_dump() for f in self._facts])

    def save(self, directory: Path) -> tuple[Path, Path]:
        directory.mkdir(parents=True, exist_ok=True)
        pq = directory / f"{self.ticker}_{self.period}.parquet"
        js = directory / f"{self.ticker}_{self.period}.json"
        self.to_dataframe().to_parquet(pq, index=False)
        js.write_text(json.dumps([json.loads(f.model_dump_json()) for f in self._facts], indent=2))
        return pq, js


def _latest_numeric(obj) -> float:
    """Best-effort: most recent numeric value from a defeatbeta-api result."""
    df = getattr(obj, "data", obj)
    if isinstance(df, pd.DataFrame) and not df.empty:
        num = df.select_dtypes("number")
        if num.shape[1]:
            return float(num.iloc[-1, -1])
    if isinstance(obj, (int, float)):
        return float(obj)
    raise ValueError(f"could not parse numeric from {type(obj).__name__}")


def build_fact_store(ticker: str, period: str, use_mock: bool = True) -> FactStore:
    """Build a FactStore from defeatbeta-api, falling back to the mock snapshot per metric."""
    store = FactStore(ticker, period)
    mock = MOCK_SNAPSHOTS.get(ticker.upper(), {})

    ticker_obj = None
    if not use_mock:
        try:
            from defeatbeta_api.data.ticker import Ticker
            ticker_obj = Ticker(ticker)
        except Exception as e:  # pragma: no cover - network/runtime dependent
            store.record_gap("_init", f"defeatbeta-api unavailable: {e}")

    for metric, method, unit in SPECS:
        if ticker_obj is not None:
            try:
                val = _latest_numeric(getattr(ticker_obj, method)())
                store.add(metric, val, unit, source=f"defeatbeta-api:{method}")
                continue
            except Exception as e:  # pragma: no cover
                store.record_gap(metric, f"live fetch failed: {e}")
        if metric in mock:
            store.add(metric, mock[metric], unit, source="mock:defeatbeta-snapshot", source_url=MOCK_URL)
        else:
            store.record_gap(metric, "no live value and no mock")

    for metric in ("revenue", "gross_margin", "operating_margin"):
        if store.get(metric) is None and metric in mock:
            store.add(metric, mock[metric], UNITS[metric],
                      source="mock:defeatbeta-snapshot", source_url=MOCK_URL)
    return store


# ---- Slot rendering (the model writes {{F-00xx}}; we substitute verified values) ----
def format_value(f: FinancialFact) -> str:
    v = f.value
    if f.unit == "USD":
        if abs(v) >= 1e12:
            return f"${v / 1e12:.2f} trillion"
        if abs(v) >= 1e9:
            return f"${v / 1e9:.2f} billion"
        return f"${v:,.2f}"
    if f.unit == "%":
        return f"{v:.1f}%"
    if f.unit == "x":
        return f"{v:.1f}x"
    return f"{v}"


_SLOT_RE = re.compile(r"\{\{(F-\d+)\}\}")


def render_slots(text: str, store: "FactStore") -> str:
    def sub(m):
        f = store.by_id(m.group(1))
        return format_value(f) if f else m.group(0)
    return _SLOT_RE.sub(sub, text)


# ---- Grounding helpers (used by the verifier) ----
# Only standalone numbers — ignore digits embedded in tokens like "FY2026Q1" or "Q1".
_NUM_RE = re.compile(r"(?<![A-Za-z0-9])-?\d[\d,]*\.?\d*(?![A-Za-z0-9])")
REQUIRED_METRICS = {"revenue", "ttm_eps", "gross_margin", "operating_margin", "market_cap"}


def extract_numbers(text: str) -> list[float]:
    out = []
    for tok in _NUM_RE.findall(text):
        try:
            out.append(float(tok.replace(",", "")))
        except ValueError:
            pass
    return out


def allowed_values(store: FactStore) -> set[float]:
    vals: set[float] = set()
    for f in store.facts:
        vals.add(round(f.value, 4))
        if f.unit == "USD" and abs(f.value) >= 1e9:
            vals.add(round(f.value / 1e9, 4))
            vals.add(round(f.value / 1e12, 4))
        if f.unit == "%":
            vals.add(round(f.value / 100, 4))
    return vals


def ungrounded_numbers(text: str, store: FactStore, tol: float = 0.02) -> list[float]:
    allowed = allowed_values(store)
    return [n for n in extract_numbers(text)
            if not any(abs(n - a) <= tol * max(1.0, abs(a)) for a in allowed)]
