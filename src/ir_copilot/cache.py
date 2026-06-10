"""SQLite persistence for IR-Copilot (stdlib sqlite3 — no parquet/duckdb/pyarrow).

Tables:
  facts        — grounded financial facts, queryable with plain SQL
  ticker_data  — all other live-fetched data per ticker (wiki chunks, news, signals)
                 with a `fetched_at` timestamp so TTL checks work
  blobs        — generic key/value JSON store (drafts, agent outputs)

Any ticker queried in production is fully persisted here, so subsequent calls
(and server restarts) never re-hit the live API unless the TTL has expired.
"""
from __future__ import annotations

import datetime as dt
import json
import sqlite3
from pathlib import Path
from typing import List, Optional

from .config import settings
from .facts import FinancialFact, FactStore

# How long cached market data is considered fresh.
# Market data (financials, segments, news) updates at most daily.
DEFAULT_TTL_HOURS = 24


def _default_path() -> Path:
    return settings.artifacts_dir / "ir_copilot.sqlite"


class Cache:
    def __init__(self, path: Optional[Path] = None):
        self.path = Path(path) if path else _default_path()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._init()

    def _conn(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.path)
        conn.row_factory = sqlite3.Row
        return conn

    def _init(self) -> None:
        with self._conn() as c:
            c.execute("""
                CREATE TABLE IF NOT EXISTS facts (
                    ticker TEXT, period TEXT, fact_id TEXT,
                    metric TEXT, value REAL, unit TEXT,
                    source TEXT, source_url TEXT, as_of TEXT,
                    PRIMARY KEY (ticker, period, fact_id))""")
            # data_type: "wiki_chunks" | "news" | "signals"
            c.execute("""
                CREATE TABLE IF NOT EXISTS ticker_data (
                    ticker TEXT, data_type TEXT, json TEXT,
                    fetched_at TEXT,
                    PRIMARY KEY (ticker, data_type))""")
            c.execute("""
                CREATE TABLE IF NOT EXISTS blobs (
                    namespace TEXT, key TEXT, json TEXT,
                    PRIMARY KEY (namespace, key))""")

    # ── facts ──────────────────────────────────────────────────────────────────
    def save_facts(self, store: FactStore) -> int:
        rows = [(f.ticker, f.period, f.fact_id, f.metric, f.value, f.unit,
                 f.source, f.source_url, f.as_of.isoformat() if f.as_of else None)
                for f in store.facts]
        with self._conn() as c:
            c.execute("DELETE FROM facts WHERE ticker=? AND period=?", (store.ticker, store.period))
            c.executemany("INSERT INTO facts VALUES (?,?,?,?,?,?,?,?,?)", rows)
        return len(rows)

    def load_facts(self, ticker: str, period: str) -> Optional[FactStore]:
        with self._conn() as c:
            rows = c.execute(
                "SELECT * FROM facts WHERE ticker=? AND period=? ORDER BY fact_id",
                (ticker, period)).fetchall()
        if not rows:
            return None
        facts = [FinancialFact(fact_id=r["fact_id"], ticker=r["ticker"], metric=r["metric"],
                               period=r["period"], value=r["value"], unit=r["unit"],
                               source=r["source"], source_url=r["source_url"],
                               as_of=r["as_of"]) for r in rows]
        return FactStore.from_facts(ticker, period, facts)

    # ── ticker data (wiki_chunks / news / signals) ─────────────────────────────
    def save_ticker_data(self, ticker: str, data_type: str, data: list) -> None:
        """Persist a list of dicts for (ticker, data_type)."""
        payload = json.dumps(data, default=str)
        now = dt.datetime.utcnow().isoformat()
        with self._conn() as c:
            c.execute("INSERT OR REPLACE INTO ticker_data VALUES (?,?,?,?)",
                      (ticker.upper(), data_type, payload, now))

    def load_ticker_data(self, ticker: str, data_type: str,
                         max_age_hours: float = DEFAULT_TTL_HOURS) -> Optional[list]:
        """Return cached data or None if missing or older than max_age_hours."""
        with self._conn() as c:
            row = c.execute(
                "SELECT json, fetched_at FROM ticker_data WHERE ticker=? AND data_type=?",
                (ticker.upper(), data_type)).fetchone()
        if not row:
            return None
        try:
            fetched = dt.datetime.fromisoformat(row["fetched_at"])
            age = (dt.datetime.utcnow() - fetched).total_seconds() / 3600
            if age > max_age_hours:
                return None
        except Exception:
            return None
        return json.loads(row["json"])

    def ticker_data_age_hours(self, ticker: str, data_type: str) -> Optional[float]:
        """Return age of cached data in hours, or None if not cached."""
        with self._conn() as c:
            row = c.execute(
                "SELECT fetched_at FROM ticker_data WHERE ticker=? AND data_type=?",
                (ticker.upper(), data_type)).fetchone()
        if not row:
            return None
        try:
            fetched = dt.datetime.fromisoformat(row["fetched_at"])
            return (dt.datetime.utcnow() - fetched).total_seconds() / 3600
        except Exception:
            return None

    def invalidate_ticker(self, ticker: str) -> dict:
        """Delete all cached data for a ticker. Returns counts deleted."""
        t = ticker.upper()
        with self._conn() as c:
            fc = c.execute("SELECT COUNT(*) FROM facts WHERE ticker=?", (t,)).fetchone()[0]
            c.execute("DELETE FROM facts WHERE ticker=?", (t,))
            dc = c.execute("SELECT COUNT(*) FROM ticker_data WHERE ticker=?", (t,)).fetchone()[0]
            c.execute("DELETE FROM ticker_data WHERE ticker=?", (t,))
        return {"ticker": t, "facts_deleted": fc, "data_entries_deleted": dc}

    def list_cached_tickers(self) -> List[dict]:
        """Summary of every ticker in the cache with freshness info."""
        with self._conn() as c:
            fact_rows = c.execute(
                "SELECT ticker, COUNT(*) as n, MAX(as_of) as latest "
                "FROM facts GROUP BY ticker").fetchall()
            data_rows = c.execute(
                "SELECT ticker, data_type, fetched_at FROM ticker_data").fetchall()
        fact_map = {r["ticker"]: {"fact_count": r["n"], "latest_as_of": r["latest"]}
                    for r in fact_rows}
        data_map: dict[str, dict] = {}
        for r in data_rows:
            data_map.setdefault(r["ticker"], {})[r["data_type"]] = r["fetched_at"]
        tickers = sorted(set(fact_map) | set(data_map))
        result = []
        for t in tickers:
            entry: dict = {"ticker": t}
            entry.update(fact_map.get(t, {"fact_count": 0}))
            entry["cached_data"] = data_map.get(t, {})
            result.append(entry)
        return result

    # ── generic blobs ──────────────────────────────────────────────────────────
    def put(self, namespace: str, key: str, obj) -> None:
        payload = (obj.model_dump_json() if hasattr(obj, "model_dump_json")
                   else json.dumps(obj, default=str))
        with self._conn() as c:
            c.execute("INSERT OR REPLACE INTO blobs VALUES (?,?,?)", (namespace, key, payload))

    def get(self, namespace: str, key: str):
        with self._conn() as c:
            row = c.execute("SELECT json FROM blobs WHERE namespace=? AND key=?",
                            (namespace, key)).fetchone()
        return json.loads(row["json"]) if row else None
