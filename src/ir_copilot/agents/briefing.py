"""Grounded prompt context shared by the LLM paths of the Predictive + Drafting agents.

The whole point: let a real LLM (vLLM on the MI300X, or any OpenAI-compatible endpoint) write
natural, intelligent questions and answers — WITHOUT inventing numbers.

How grounding survives LLM generation:
  * The LLM is given a FACT CATALOG mapping each verified figure to a slot token ({{F-00xx}}).
  * It is instructed to use those slot tokens for every number, never to write digits itself.
  * `render_slots()` substitutes the verified values; the Grounding Verifier rejects any number
    that isn't traceable to a fact (drafting then falls back to grounded templates).
  * Question text is validated against an allowed-number set so a stray figure is dropped.
"""
from __future__ import annotations

import json
import re
from typing import List, Optional, Tuple

from ..facts import FactStore, allowed_values, format_value
from .competitor import PeerComparison
from .sentiment import SentimentSnapshot

_LABEL = {
    "gross_margin": "gross margin", "operating_margin": "operating margin", "roe": "ROE",
    "roic": "ROIC", "roa": "ROA", "ttm_eps": "TTM EPS", "ttm_pe": "TTM P/E", "revenue": "revenue",
    "market_cap": "market capitalization", "ps_ratio": "P/S", "pb_ratio": "P/B",
    "peg_ratio": "PEG", "equity_multiplier": "equity multiplier", "asset_turnover": "asset turnover",
}


def label(metric: str) -> str:
    return _LABEL.get(metric, metric.replace("_", " "))


def fact_catalog(store: FactStore) -> str:
    """One line per verified figure: `{{F-0007}} = revenue = $81.61 billion`."""
    lines = []
    for f in store.facts:
        token = "{{" + f.fact_id + "}}"
        lines.append(f"  {token} = {label(f.metric)} = {format_value(f)}")
    return "\n".join(lines)


def allowed_question_numbers(store: FactStore, peer: PeerComparison,
                             signals: Optional[List[dict]]) -> set:
    """Numbers permitted in generated QUESTION text: fact values + peer values + signal YoY %."""
    allowed = set(allowed_values(store))
    for pm in peer.metrics:
        allowed.add(round(pm.company_value, 4))
        for v in pm.peer_values.values():
            allowed.add(round(float(v), 4))
    for s in signals or []:
        pct = abs(float(s.get("change_pct", 0)))
        allowed.add(round(pct, 4))
        allowed.add(round(pct, 0))
    return allowed


def build_evidence(store: FactStore, peer: PeerComparison, sentiment: SentimentSnapshot,
                   signals: Optional[List[dict]],
                   precedents: Optional[List[dict]]) -> Tuple[str, dict]:
    """A tagged, cited evidence brief for the analyst LLM + a tag→source_url map.

    Tags: S* segment/geo swings · L* peer lags · C* sentiment concerns · Q* past analyst questions.
    """
    items: List[Tuple[str, str, str]] = []   # (tag, line, source_url)

    for i, s in enumerate(signals or [], 1):
        verb = "rose" if s.get("direction") == "up" else "declined"
        items.append((f"S{i}",
                      f"{s.get('series','a segment')} {verb} {abs(s.get('change_pct',0)):.0f}% "
                      f"year-over-year", s.get("evidence_url", "")))

    li = 1
    for pm in peer.metrics:
        if pm.metric in (peer.lags or []):
            best = None
            if pm.peer_values:
                best = (max if pm.higher_better else min)(pm.peer_values, key=pm.peer_values.get)
            items.append((f"L{li}",
                          f"{label(pm.metric)} ({pm.company_value}) trails {best or 'peers'} "
                          f"(ranks #{pm.rank} in the peer set)",
                          pm.fact_ids[0] if pm.fact_ids else ""))
            li += 1

    for i, theme in enumerate(sentiment.negative_themes, 1):
        url = next((c.url for c in theme.evidence if c.url), "")
        items.append((f"C{i}", f"Market concern: {theme.label}", url))

    for i, p in enumerate(precedents or [], 1):
        items.append((f"Q{i}",
                      f"Analyst asked on the {p.get('period','prior')} call: \"{p.get('text','')[:160]}\"",
                      p.get("source_url", "")))

    if not items:
        return "(no specific evidence flagged; rely on the figures below)", {}
    brief = "EVIDENCE (cite the bracketed tag in each question's \"evidence\" field):\n" + \
        "\n".join(f"[{t}] {line}" for t, line, _ in items)
    return brief, {t: url for t, line, url in items}


def narrative_context(store: FactStore, peer: PeerComparison,
                      sentiment: SentimentSnapshot) -> str:
    """Talking points (no raw numbers — those come from the FIGURES catalog) for the drafter."""
    leads = ", ".join(label(m) for m in (peer.leads or [])) or "several metrics"
    lags = ", ".join(label(m) for m in (peer.lags or [])) or "none"
    concerns = "; ".join(t.label for t in sentiment.negative_themes) or "no major concerns"
    return (f"Strengths (leads the peer group on): {leads}.\n"
            f"Relative weaknesses (below peer median on): {lags}.\n"
            f"Watch items from market sentiment: {concerns}.")


_FENCE_RE = re.compile(r"```(?:json)?\s*(.*?)```", re.S)


def parse_json(text: str):
    """Robustly pull a JSON array/object out of an LLM response (handles code fences/prose)."""
    if not text:
        return None
    m = _FENCE_RE.search(text)
    if m:
        text = m.group(1)
    text = text.strip()
    for opener, closer in (("[", "]"), ("{", "}")):
        a, b = text.find(opener), text.rfind(closer)
        if a != -1 and b > a:
            try:
                return json.loads(text[a:b + 1])
            except json.JSONDecodeError:
                continue
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return None
