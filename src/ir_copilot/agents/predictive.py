"""Predictive Analyst agent (docs/agents.md, docs/finetuning.md) — the fine-tune target.

Predicts the hardest investor questions from: peer lags, negative sentiment themes, and
retrieved precedent analyst questions (RAG over the wiki). Every question carries evidence.
Mock mode = deterministic, grounded templates; vllm mode = the (fine-tuned) model phrases/ranks.
"""
from __future__ import annotations

from typing import List, Optional

from pydantic import BaseModel

from ..facts import FactStore, format_value
from .competitor import PeerComparison
from .sentiment import SentimentSnapshot

_METRIC_LABEL = {
    "gross_margin": "gross margin", "operating_margin": "operating margin", "roe": "ROE",
    "roic": "ROIC", "roa": "ROA", "ttm_eps": "EPS", "revenue": "revenue",
}


class Question(BaseModel):
    text: str
    difficulty: float          # 0..1
    rationale: str
    evidence: List[str]        # fact_ids + wiki chunk source_urls
    suggested_answer: str = ""


def _from_lags(store: FactStore, peer: PeerComparison) -> List[Question]:
    qs = []
    for pm in peer.metrics:
        if pm.metric not in peer.lags:
            continue
        label = _METRIC_LABEL.get(pm.metric, pm.metric)
        best_peer = None
        if pm.peer_values:
            best_peer = (max if pm.higher_better else min)(pm.peer_values, key=pm.peer_values.get)
        gap = abs(pm.delta_vs_best)
        diff = min(1.0, 0.4 + gap / (abs(pm.company_value) + 1e-6))
        qs.append(Question(
            text=f"Your {label} trails {best_peer or 'peers'} — what is the path to close the gap?",
            difficulty=round(diff, 2),
            rationale=f"Company {label} ({pm.company_value}) ranks #{pm.rank} in the peer set.",
            evidence=pm.fact_ids,
        ))
    return qs


def _from_signals(signals) -> List[Question]:
    """Hardest questions come from big segment/geo swings — the data-driven signal (P1)."""
    qs = []
    for s in signals or []:
        pct = abs(s.get("change_pct", 0))
        verb = "rose" if s.get("direction") == "up" else "declined"
        series = s.get("series", "a segment")
        qs.append(Question(
            text=f"{series} {verb} {pct:.0f}% year-over-year — what is driving that and how "
                 f"durable is it?",
            difficulty=round(min(1.0, 0.55 + pct / 200), 2),
            rationale=f"{series} revenue moved {s.get('change_pct')}% YoY (segment breakdown).",
            evidence=[s.get("evidence_url", "")],
        ))
    return qs


def _from_sentiment(sentiment: SentimentSnapshot) -> List[Question]:
    qs = []
    for theme in sentiment.negative_themes:
        ev = [c.url for c in theme.evidence if c.url]
        qs.append(Question(
            text=f"Investors are concerned about {theme.label.lower()}. How are you addressing it?",
            difficulty=round(min(1.0, 0.5 + abs(theme.score) / 2), 2),
            rationale=f"Negative sentiment theme (score {theme.score}).",
            evidence=ev,
        ))
    return qs


def _question_sentence(text: str) -> str:
    """Extract the actual question from an analyst paragraph (last sentence ending in '?')."""
    import re
    sentences = re.split(r"(?<=[.?!])\s+", text.strip())
    qs = [s for s in sentences if s.endswith("?")]
    return (qs[-1] if qs else text).strip()[:240]


def _from_wiki(wiki, ticker: str, k: int = 6) -> List[Question]:
    """Predict from REAL analyst questions asked on past calls (retrieved from the wiki)."""
    if wiki is None:
        return []
    seed = "gross margin guidance revenue growth competition demand supply capital allocation risk"
    out = []
    for h in wiki.search(seed, ticker=ticker, k=k, doc_type="transcript"):
        out.append(Question(
            text=_question_sentence(h["text"]),
            difficulty=round(min(1.0, 0.55 + max(0.0, h.get("score", 0.0)) / 2), 2),
            rationale=f"Asked by an analyst on the {h.get('period','prior')} call.",
            evidence=[h.get("source_url", "")],
        ))
    return out


def _attach_precedent(questions: List[Question], wiki, ticker: str) -> None:
    """Enrich lag/sentiment questions with a retrieved precedent analyst question (RAG)."""
    if wiki is None:
        return
    for q in questions:
        if q.evidence and any("earning_call_transcripts" in e for e in q.evidence):
            continue  # already a wiki-sourced question
        hits = wiki.search(q.text, ticker=ticker, k=1, doc_type="transcript")
        if hits:
            q.evidence.append(hits[0].get("source_url", ""))
            q.rationale += f" Precedent: \"{hits[0]['text'][:90]}...\""


def predict_questions(store: FactStore, sentiment: SentimentSnapshot,
                      peer: PeerComparison, wiki=None, chat=None,
                      signals=None, top_k: int = 8) -> List[Question]:
    questions = (_from_signals(signals) + _from_lags(store, peer) + _from_sentiment(sentiment)
                 + _from_wiki(wiki, store.ticker))
    _attach_precedent(questions, wiki, store.ticker)

    # de-dup, rank by difficulty
    seen, ranked = set(), []
    for q in sorted(questions, key=lambda x: -x.difficulty):
        if q.text in seen:
            continue
        seen.add(q.text)
        ranked.append(q)

    if chat is not None and ranked:
        # vllm path: let the (fine-tuned) model refine phrasing/ordering. Grounding unchanged.
        bullet = "\n".join(f"- {q.text}" for q in ranked[:top_k])
        try:
            refined = chat.complete(
                system="You are an IR analyst. Rewrite each investor question to be sharp and "
                       "specific. Keep the same order and count. Return one question per line.",
                user=bullet)
            lines = [ln.strip("-* ").strip() for ln in refined.splitlines() if ln.strip()]
            for q, line in zip(ranked, lines):
                q.text = line
        except Exception as e:  # pragma: no cover
            print(f"[predictive] vllm refine failed ({e}); keeping templated questions.")

    return ranked[:top_k]
