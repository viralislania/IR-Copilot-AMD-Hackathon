"""SQLite cache (stdlib `sqlite3` — no parquet/duckdb/pyarrow dependency).

Two roles:
  * a relational `facts` table — grounded financials are queryable with plain SQL
  * a generic `blobs` key/value table — JSON for sentiment/comparison/draft/wiki payloads

`duckdb` is only ever used transitively by defeatbeta-api itself; IR-Copilot persists with sqlite.
"""
from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import List, Optional

from .config import settings
from .facts import FinancialFact, FactStore


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
            c.execute("""
                CREATE TABLE IF NOT EXISTS blobs (
                    namespace TEXT, key TEXT, json TEXT,
                    PRIMARY KEY (namespace, key))""")

    # ---- facts ----
    def save_facts(self, store: FactStore) -> int:
        rows = [(f.ticker, f.period, f.fact_id, f.metric, f.value, f.unit,
                 f.source, f.source_url, f.as_of.isoformat()) for f in store.facts]
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
                               source=r["source"], source_url=r["source_url"], as_of=r["as_of"])
                 for r in rows]
        return FactStore.from_facts(ticker, period, facts)

    # ---- generic JSON blobs ----
    def put(self, namespace: str, key: str, obj) -> None:
        payload = obj.model_dump_json() if hasattr(obj, "model_dump_json") else json.dumps(obj, default=str)
        with self._conn() as c:
            c.execute("INSERT OR REPLACE INTO blobs VALUES (?,?,?)", (namespace, key, payload))

    def get(self, namespace: str, key: str):
        with self._conn() as c:
            row = c.execute("SELECT json FROM blobs WHERE namespace=? AND key=?",
                            (namespace, key)).fetchone()
        return json.loads(row["json"]) if row else None
