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
    compliance_flags: List[str]


# Reg-FD / Safe-Harbor lint: phrases that suggest unhedged forward promises or selective
# disclosure. Flagged for the human reviewer (not auto-blocking) — a lint, not legal advice.
_RISKY_PHRASES = [
    "guarantee", "guaranteed", "we promise", "will definitely", "certain to", "no risk",
    "risk-free", "off the record", "not yet public", "before the market", "you didn't hear",
    "i can confirm privately",
]


# Fixed legal boilerplate we control — excluded from numeric grounding (contains statute years,
# not financial claims). Still scanned for compliance phrases.
_BOILERPLATE_HEADINGS = {"safe harbor"}


def _all_text(rendered: dict, skip_boilerplate: bool = False) -> str:
    parts = []
    for s in rendered.get("script", []):
        if skip_boilerplate and s.get("heading", "").lower() in _BOILERPLATE_HEADINGS:
            continue
        parts.append(s["text"])
    for sl in rendered.get("deck_outline", []):
        parts.extend(sl["bullets"])
    for q in rendered.get("qa_cheat_sheet", []):
        parts.append(q["suggested_answer"])
    return "\n".join(parts)


def _compliance(rendered: dict, text: str) -> List[str]:
    flags = []
    low = text.lower()
    for phrase in _RISKY_PHRASES:
        if phrase in low:
            flags.append(f"selective-disclosure/forward-looking phrase: '{phrase}'")
    headings = {s.get("heading", "").lower() for s in rendered.get("script", [])}
    if "safe harbor" not in headings:
        flags.append("missing Safe Harbor / forward-looking-statements disclaimer")
    return flags


def verify(rendered: dict, store: FactStore, tol: float = 0.02) -> VerifyReport:
    text = _all_text(rendered)                                  # full text for compliance scan
    numeric = ungrounded_numbers(_all_text(rendered, skip_boilerplate=True), store, tol=tol)

    present = {f.metric for f in store.facts}
    mentioned_required = {m for m in REQUIRED_METRICS if m in present}
    coverage_missing = sorted(REQUIRED_METRICS - mentioned_required)

    compliance_flags = _compliance(rendered, text)

    # Numbers/coverage block the draft; compliance/claim flags surface to the human (non-blocking).
    passed = not numeric and not coverage_missing
    return VerifyReport(passed=passed, numeric_violations=numeric,
                        coverage_missing=coverage_missing, claim_flags=[],
                        compliance_flags=compliance_flags)
