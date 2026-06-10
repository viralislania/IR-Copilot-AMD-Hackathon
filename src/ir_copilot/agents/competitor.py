"""Competitor Comparison agent (docs/competitor.md).

Benchmarks the company vs peers on the same metrics, before drafting. Peer values are grounded
FinancialFacts too, so the comparison is fully cited. Lags feed the Predictive Analyst.
"""
from __future__ import annotations

from statistics import median
from typing import List

from pydantic import BaseModel

from ..facts import FactStore

# Direction: True = higher is better, False = lower is better.
HIGHER_BETTER = {
    "roe": True, "roa": True, "roic": True, "gross_margin": True, "operating_margin": True,
    "asset_turnover": True, "ttm_eps": True, "revenue": True,
    "wacc": False, "ttm_pe": False, "ps_ratio": False, "pb_ratio": False,
    "peg_ratio": False, "equity_multiplier": False,
}
DEFAULT_METRICS = ["gross_margin", "operating_margin", "roe", "roic", "roa", "ttm_eps"]


class PeerMetric(BaseModel):
    metric: str
    higher_better: bool
    company_value: float
    peer_values: dict          # {ticker: value}
    rank: int                  # 1 = best in the peer+company set
    delta_vs_best: float       # company_value - best_value (signed)
    fact_ids: List[str]


class PeerComparison(BaseModel):
    company: str
    peers: List[str]
    metrics: List[PeerMetric]
    leads: List[str]           # metrics where the company ranks #1
    lags: List[str]            # metrics where the company is below the peer-set median


def compare(company_store: FactStore, peer_stores: dict[str, FactStore],
            metrics: List[str] | None = None) -> PeerComparison:
    metrics = metrics or DEFAULT_METRICS
    company = company_store.ticker
    peers = list(peer_stores.keys())
    out_metrics: List[PeerMetric] = []
    leads, lags = [], []

    for metric in metrics:
        cf = company_store.get(metric)
        if cf is None:
            continue
        hb = HIGHER_BETTER.get(metric, True)
        peer_values, fact_ids = {}, [cf.fact_id]
        for pt, ps in peer_stores.items():
            pf = ps.get(metric)
            if pf is not None:
                peer_values[pt] = pf.value
                fact_ids.append(pf.fact_id)

        all_vals = [cf.value] + list(peer_values.values())
        best = max(all_vals) if hb else min(all_vals)
        # rank: 1 = best
        ordered = sorted(all_vals, reverse=hb)
        rank = ordered.index(cf.value) + 1
        med = median(list(peer_values.values())) if peer_values else cf.value

        out_metrics.append(PeerMetric(
            metric=metric, higher_better=hb, company_value=cf.value,
            peer_values=peer_values, rank=rank,
            delta_vs_best=round(cf.value - best, 4), fact_ids=fact_ids))

        if rank == 1:
            leads.append(metric)
        below_median = cf.value < med if hb else cf.value > med
        if below_median:
            lags.append(metric)

    return PeerComparison(company=company, peers=peers, metrics=out_metrics,
                          leads=leads, lags=lags)
