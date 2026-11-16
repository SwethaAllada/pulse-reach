"""Bounded LLM explanation and simulated outreach preview package (`app.services.explanation`)."""

from app.services.explanation.service import (
    REASON_DESCRIPTIONS,
    BoundedExplanationInput,
    ExplanationResult,
    ExplanationService,
    OutreachPreviewInput,
    OutreachPreviewResult,
    PrivacyViolationError,
)

__all__ = [
    "REASON_DESCRIPTIONS",
    "BoundedExplanationInput",
    "ExplanationResult",
    "ExplanationService",
    "OutreachPreviewInput",
    "OutreachPreviewResult",
    "PrivacyViolationError",
]
