"""Pydantic response schemas for the LLM (drafting + predictive) paths.

These are used two ways:
  1. As the `response_format` JSON schema sent to the model (vLLM guided decoding / OpenAI
     structured outputs), so the model is constrained to emit valid JSON.
  2. As the validation model for the returned text — a malformed response raises
     `ValidationError` and the agent falls back to grounded templates.
"""
from __future__ import annotations

from typing import List

from pydantic import BaseModel, Field


# ── Predictive Analyst ──────────────────────────────────────────────────────────
class PredictedQuestionLLM(BaseModel):
    question: str
    evidence: str = ""                 # evidence tag (e.g. "S1", "L1", "C1", "Q1")
    difficulty: float = 0.7            # 0..1


class PredictedQuestionsLLM(BaseModel):
    questions: List[PredictedQuestionLLM] = Field(default_factory=list)


# ── Drafting ────────────────────────────────────────────────────────────────────
class LLMScriptSection(BaseModel):
    heading: str
    text: str                          # natural prose; numbers as {{F-00xx}} slot tokens


class LLMSlide(BaseModel):
    title: str
    bullets: List[str] = Field(default_factory=list)


class LLMDraft(BaseModel):
    script: List[LLMScriptSection] = Field(default_factory=list)
    deck: List[LLMSlide] = Field(default_factory=list)
    answers: List[str] = Field(default_factory=list)   # 1:1 with the input questions
