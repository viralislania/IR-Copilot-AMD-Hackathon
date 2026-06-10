"""Grounding Verifier (docs/grounding.md) — blocks ungrounded numbers / missing metrics.

Runs on the RENDERED draft (slots already substituted). Any number not traceable to the Fact
Store is a violation; any missing required metric is a coverage gap. On failure the graph loops
back to drafting.
"""
from __future__ import annotations

from typing import List

from pydantic import BaseModel

from ..facts import FactStore, REQUIRED_METRICS, ungrounded_numbers


class VerifyReport(BaseModel):
    passed: bool
    numeric_violations: List[float]
    coverage_missing: List[str]
    claim_flags: List[str]


def _all_text(rendered: dict) -> str:
    parts = []
    for s in rendered.get("script", []):
        parts.append(s["text"])
    for sl in rendered.get("deck_outline", []):
        parts.extend(sl["bullets"])
    for q in rendered.get("qa_cheat_sheet", []):
        parts.append(q["suggested_answer"])
    return "\n".join(parts)


def verify(rendered: dict, store: FactStore, tol: float = 0.02) -> VerifyReport:
    text = _all_text(rendered)
    numeric = ungrounded_numbers(text, store, tol=tol)

    present = {f.metric for f in store.facts}
    mentioned_required = {m for m in REQUIRED_METRICS if m in present}
    coverage_missing = sorted(REQUIRED_METRICS - mentioned_required)

    passed = not numeric and not coverage_missing
    return VerifyReport(passed=passed, numeric_violations=numeric,
                        coverage_missing=coverage_missing, claim_flags=[])
