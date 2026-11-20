"""Staff AI copilot contracts (`/api/v1/ai/copilot/*`)."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from app.schemas.v1 import AIGenerationOut

CopilotTask = Literal["coordination_summary", "clinical_review", "population_briefing"]


class CopilotIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    language: Literal["en", "ar"] | None = None


class CopilotStepOut(BaseModel):
    code: str
    label: str


class CopilotOut(BaseModel):
    """A review-only draft: it changes nothing and sends nothing. `suggested_next_steps` are
    derived deterministically from existing workflow states (never by the model)."""

    task: CopilotTask
    locale: Literal["en", "ar"]
    direction: Literal["ltr", "rtl"]
    summary: str
    points: list[str] = Field(default_factory=list)
    questions: list[str] = Field(default_factory=list)
    suggested_next_steps: list[CopilotStepOut] = Field(default_factory=list)
    generation_mode: Literal["llm_grounded", "deterministic_fallback"]
    ai_available: bool
    draft_notice: str
    disclaimer: str
    sources: list[str] = Field(default_factory=list)
    ai: AIGenerationOut
