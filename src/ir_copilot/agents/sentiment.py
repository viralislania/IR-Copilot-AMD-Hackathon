"""Market Sentiment agent (docs/sentiment.md).

Classifies news + social posts. Backend: lexicon (offline) or finbert (transformers).
Every theme keeps the source items as evidence — sentiment is as auditable as the financials.
"""
from __future__ import annotations

from typing import List, Optional

from pydantic import BaseModel

from ..config import settings

_POS = {"strong", "record", "beat", "growth", "amazing", "bullish", "optimism", "raise",
        "expanded", "demand", "boosting", "long"}
_NEG = {"concern", "fret", "worried", "risk", "scrutiny", "weighs", "competition",
        "constraints", "overvalued", "restrictions", "negative", "decline", "miss"}

# theme keyword -> human label
_THEME_KEYWORDS = {
    "competition": "Competitive pressure / market share",
    "margin": "Margin sustainability",
    "supply": "Supply constraints",
    "constraints": "Supply constraints",
    "export": "Regulatory / export restrictions",
    "regulatory": "Regulatory / export restrictions",
    "scrutiny": "Regulatory / export restrictions",
    "capex": "AI capex digestion",
    "demand": "Demand strength",
    "guidance": "Guidance",
    "revenue": "Revenue growth",
}


class Citation(BaseModel):
    text: str
    url: str = ""


class Theme(BaseModel):
    label: str
    score: float            # signed: + positive, - negative
    evidence: List[Citation]


class SentimentSnapshot(BaseModel):
    ticker: str
    net_score: float        # -1 .. +1
    positive_themes: List[Theme]
    negative_themes: List[Theme]
    sources: List[Citation]


def _lexicon_polarity(text: str) -> float:
    toks = {t.strip(".,!?$").lower() for t in text.split()}
    pos = len(toks & _POS)
    neg = len(toks & _NEG)
    if pos == neg:
        return 0.0
    return (pos - neg) / max(1, pos + neg)


def _finbert_polarity(texts: List[str]) -> List[float]:
    from transformers import pipeline
    clf = pipeline("text-classification", model="ProsusAI/finbert", top_k=None)
    out = []
    for scores in clf(texts):
        d = {s["label"].lower(): s["score"] for s in scores}
        out.append(d.get("positive", 0.0) - d.get("negative", 0.0))
    return out


def analyze_sentiment(ticker: str, items: List[dict],
                      backend: Optional[str] = None) -> SentimentSnapshot:
    backend = backend or settings.sentiment_backend
    texts = [it["text"] for it in items]
    if backend == "finbert":
        try:
            pols = _finbert_polarity(texts)
        except Exception as e:  # pragma: no cover
            print(f"[sentiment] finbert unavailable ({e}); using lexicon.")
            pols = [_lexicon_polarity(t) for t in texts]
    else:
        pols = [_lexicon_polarity(t) for t in texts]

    # group items into themes by keyword, carrying signed score + evidence
    themes: dict[str, dict] = {}
    for it, pol in zip(items, pols):
        low = it["text"].lower()
        for kw, label in _THEME_KEYWORDS.items():
            if kw in low:
                t = themes.setdefault(label, {"scores": [], "evidence": []})
                t["scores"].append(pol)
                t["evidence"].append(Citation(text=it["text"], url=it.get("url", "")))

    pos_themes, neg_themes = [], []
    for label, t in themes.items():
        avg = sum(t["scores"]) / len(t["scores"])
        theme = Theme(label=label, score=round(avg, 3), evidence=t["evidence"])
        (pos_themes if avg >= 0 else neg_themes).append(theme)

    pos_themes.sort(key=lambda x: -x.score)
    neg_themes.sort(key=lambda x: x.score)
    net = round(sum(pols) / len(pols), 3) if pols else 0.0
    sources = [Citation(text=it["text"], url=it.get("url", "")) for it in items]
    return SentimentSnapshot(ticker=ticker, net_score=net,
                             positive_themes=pos_themes, negative_themes=neg_themes,
                             sources=sources)
