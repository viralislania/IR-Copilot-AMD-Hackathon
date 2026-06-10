"""Drafting agent (docs/agents.md) — script + deck outline + Q&A cheat sheet.

Numbers are SLOTTED ({{F-00xx}}), never generated. The renderer substitutes verified values,
so the draft is grounded by construction. Mock mode templates; vllm mode would draft prose but
is held to the same slot discipline.
"""
from __future__ import annotations

from typing import List

from pydantic import BaseModel

from ..facts import FactStore, render_slots
from .competitor import PeerComparison
from .predictive import Question
from .sentiment import SentimentSnapshot


class ScriptSection(BaseModel):
    heading: str
    text: str            # contains {{F-00xx}} slots


class Slide(BaseModel):
    title: str
    bullets: List[str]


class DraftBundle(BaseModel):
    script: List[ScriptSection]
    deck_outline: List[Slide]
    qa_cheat_sheet: List[Question]


def _script(store: FactStore, peer: PeerComparison) -> List[ScriptSection]:
    s = store
    lead = ", ".join(peer.leads) or "several metrics"
    return [
        ScriptSection(heading="Opening", text=(
            f"Thank you for joining our {s.period} earnings call. We delivered revenue of "
            f"{s.slot('revenue')} with TTM EPS of {s.slot('ttm_eps')}, reflecting continued "
            f"execution.")),
        ScriptSection(heading="Profitability", text=(
            f"Gross margin was {s.slot('gross_margin')} and operating margin was "
            f"{s.slot('operating_margin')}, supported by strong return on equity of "
            f"{s.slot('roe')} and ROIC of {s.slot('roic')}.")),
        ScriptSection(heading="Competitive position", text=(
            f"We continue to lead our peer group on {lead}. Our market capitalization stands at "
            f"{s.slot('market_cap')}.")),
    ]


def _deck(store: FactStore, peer: PeerComparison, sentiment: SentimentSnapshot) -> List[Slide]:
    s = store
    comp_bullets = []
    for pm in peer.metrics:
        if pm.metric in peer.leads:
            tag = "leads peer set"
        elif pm.metric in peer.lags:
            tag = "below peer median"
        else:
            tag = "mid-pack vs peers"
        # value comes from a verified slot; rank is described in words (no bare counts)
        comp_bullets.append(f"{pm.metric.replace('_', ' ')}: {s.slot(pm.metric)} — {tag}")
    return [
        Slide(title="Financial Highlights", bullets=[
            f"Revenue {s.slot('revenue')}", f"TTM EPS {s.slot('ttm_eps')}",
            f"Gross margin {s.slot('gross_margin')}", f"Operating margin {s.slot('operating_margin')}"]),
        Slide(title="Returns & Valuation", bullets=[
            f"ROE {s.slot('roe')}", f"ROIC {s.slot('roic')}", f"Market cap {s.slot('market_cap')}",
            f"TTM PE {s.slot('ttm_pe')}"]),
        Slide(title="Competitive Position", bullets=comp_bullets or ["peer comparison unavailable"]),
        Slide(title="Market Sentiment & Watch Items",
              bullets=[t.label for t in sentiment.negative_themes] or ["no major concerns"]),
    ]


def _answer(q: Question, store: FactStore, peer: PeerComparison) -> str:
    """Grounded suggested answer; references slots so the figure is verified."""
    if "margin" in q.text.lower():
        return (f"Our gross margin is {store.slot('gross_margin')} and operating margin "
                f"{store.slot('operating_margin')}; we have a clear roadmap to expand both.")
    if "concern" in q.text.lower() or "addressing" in q.text.lower():
        return ("We monitor this closely; our guidance and capital allocation reflect a "
                "conservative stance while we invest for durable growth.")
    return (f"We are confident in our position, with revenue of {store.slot('revenue')} and "
            f"ROIC of {store.slot('roic')}.")


def draft(store: FactStore, sentiment: SentimentSnapshot, peer: PeerComparison,
          questions: List[Question], chat=None) -> DraftBundle:
    qa = []
    for q in questions:
        qa.append(q.model_copy(update={"suggested_answer": _answer(q, store, peer)}))
    return DraftBundle(script=_script(store, peer), deck_outline=_deck(store, peer, sentiment),
                       qa_cheat_sheet=qa)


def render_bundle(bundle: DraftBundle, store: FactStore) -> dict:
    """Render all slots to verified values for display / verification."""
    return {
        "script": [{"heading": s.heading, "text": render_slots(s.text, store)}
                   for s in bundle.script],
        "deck_outline": [{"title": sl.title, "bullets": [render_slots(b, store) for b in sl.bullets]}
                         for sl in bundle.deck_outline],
        "qa_cheat_sheet": [{"question": q.text,
                            "suggested_answer": render_slots(q.suggested_answer, store),
                            "difficulty": q.difficulty, "evidence": q.evidence}
                           for q in bundle.qa_cheat_sheet],
    }
