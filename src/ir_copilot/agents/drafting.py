"""Drafting agent (docs/agents.md) — earnings-call script + deck outline + Q&A cheat sheet.

Numbers are SLOTTED ({{F-00xx}}), never written as digits. `render_slots()` substitutes the
verified values, so the draft is grounded by construction.

Two paths, both grounded:
  * LLM (LLM_BACKEND=vllm): the model *writes* the prepared remarks, deck bullets, and CEO/CFO
    answers in natural English, using slot tokens for every figure. The output is grounding-checked
    before use; if the model leaks an ungrounded number, we fall back to templates.
  * Offline (chat=None): deterministic grounded templates.
"""
from __future__ import annotations

from typing import List, Optional

from pydantic import BaseModel

from pydantic import ValidationError

from ..facts import FactStore, render_slots
from .briefing import fact_catalog, narrative_context, parse_json
from .competitor import PeerComparison
from .predictive import Question
from .schemas import LLMDraft
from .sentiment import SentimentSnapshot


METRIC_LABELS = {
    "gross_margin": "gross margin", "operating_margin": "operating margin", "roe": "ROE",
    "roic": "ROIC", "roa": "ROA", "ttm_eps": "TTM EPS", "ttm_pe": "TTM P/E",
    "revenue": "revenue", "market_cap": "market capitalization", "ps_ratio": "P/S",
    "pb_ratio": "P/B", "peg_ratio": "PEG", "equity_multiplier": "equity multiplier",
    "asset_turnover": "asset turnover",
}

# Standard forward-looking-statements (Safe Harbor) language read at the top of every IR call.
SAFE_HARBOR = (
    "Before we begin, a reminder that today's remarks contain forward-looking statements within "
    "the meaning of the Private Securities Litigation Reform Act of 1995. Actual results may "
    "differ materially due to risks described in our SEC filings. All figures are sourced from "
    "reported financials; we undertake no obligation to update forward-looking statements.")


def label(metric: str) -> str:
    return METRIC_LABELS.get(metric, metric.replace("_", " "))


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


def _template_script(store: FactStore, peer: PeerComparison) -> List[ScriptSection]:
    s = store
    lead = ", ".join(label(m) for m in peer.leads) or "several metrics"
    return [
        ScriptSection(heading="Safe Harbor", text=SAFE_HARBOR),
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


def _template_deck(store: FactStore, peer: PeerComparison, sentiment: SentimentSnapshot) -> List[Slide]:
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
        comp_bullets.append(f"{label(pm.metric)}: {s.slot(pm.metric)} — {tag}")
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


def _template_bundle(store, sentiment, peer, questions) -> DraftBundle:
    qa = [q.model_copy(update={"suggested_answer": _answer(q, store, peer)}) for q in questions]
    return DraftBundle(script=_template_script(store, peer),
                       deck_outline=_template_deck(store, peer, sentiment), qa_cheat_sheet=qa)


def _is_grounded(bundle: DraftBundle, store: FactStore) -> bool:
    """True if the rendered bundle contains no ungrounded number (excludes Safe-Harbor boilerplate)."""
    from .verify import verify
    return not verify(render_bundle(bundle, store), store).numeric_violations


def _llm_draft(chat, store: FactStore, sentiment: SentimentSnapshot, peer: PeerComparison,
               questions: List[Question]) -> Optional[DraftBundle]:
    """The model writes the script, deck, and CEO/CFO answers in natural prose, slotting numbers."""
    qlist = "\n".join(f"{i + 1}. {q.text}" for i, q in enumerate(questions))
    system = (
        "You are a senior investor-relations speechwriter producing materials for the CEO and CFO "
        "of a public company's quarterly earnings call. Write natural, confident, compliant prose "
        "in the company's voice (use 'we'/'our'). "
        "CRITICAL GROUNDING RULE: for EVERY number you state, insert the matching slot token from "
        "the FIGURES list exactly as written (e.g. {{F-0007}}) — NEVER write the digits yourself, "
        "and use only figures that appear in the list. "
        "Open the script with a 'Safe Harbor' forward-looking-statements section. "
        "Answer each provided investor question the way a polished CFO would: direct, specific, "
        "reassuring, and grounded in the figures. "
        "Return ONLY JSON of the form: "
        '{"script": [{"heading": str, "text": str}], '
        '"deck": [{"title": str, "bullets": [str]}], '
        '"answers": [str]}  where "answers" aligns 1:1 with the numbered questions.')
    user = (f"Company: {store.ticker}   Reporting period: {store.period}\n"
            f"{narrative_context(store, peer, sentiment)}\n\n"
            f"FIGURES (use these slot tokens for all numbers):\n{fact_catalog(store)}\n\n"
            f"INVESTOR QUESTIONS TO ANSWER (in order):\n{qlist}")
    try:
        resp = chat.complete(system, user, max_tokens=2200, response_model=LLMDraft)
    except Exception as e:  # pragma: no cover
        print(f"[drafting] LLM call failed ({e}); using grounded templates.")
        return None

    data = parse_json(resp)
    try:
        out = LLMDraft.model_validate(data)
    except ValidationError:
        return None

    script = [ScriptSection(heading=s.heading.strip(), text=s.text)
              for s in out.script if s.text.strip()]
    deck = [Slide(title=sl.title.strip(), bullets=[b for b in sl.bullets if b.strip()])
            for sl in out.deck if sl.title.strip()]
    if not script or not deck:
        return None
    if not any("safe harbor" in s.heading.lower() for s in script):
        script.insert(0, ScriptSection(heading="Safe Harbor", text=SAFE_HARBOR))

    qa = []
    for i, q in enumerate(questions):
        ans = out.answers[i].strip() if i < len(out.answers) and out.answers[i].strip() \
            else _answer(q, store, peer)
        qa.append(q.model_copy(update={"suggested_answer": ans}))

    bundle = DraftBundle(script=script, deck_outline=deck, qa_cheat_sheet=qa)
    if not _is_grounded(bundle, store):
        print("[drafting] LLM draft contained an ungrounded number; using grounded templates.")
        return None
    return bundle


def draft(store: FactStore, sentiment: SentimentSnapshot, peer: PeerComparison,
          questions: List[Question], chat=None) -> DraftBundle:
    if chat is not None:
        bundle = _llm_draft(chat, store, sentiment, peer, questions)
        if bundle is not None:
            return bundle
    return _template_bundle(store, sentiment, peer, questions)


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
