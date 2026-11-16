"""Deterministic clinical rule evaluation package (`app.services.evaluation`)."""

from app.services.evaluation.engine import (
    ENGINE_VERSION,
    AssessmentFact,
    CareGapFact,
    ComponentResultFact,
    ConsentFact,
    EvaluationEngine,
    FiredReason,
    PatientContext,
    PatientEvaluationSummary,
    ReferralFact,
    RuleEvaluationResult,
    ScreeningEventFact,
    VisitEventFact,
)

__all__ = [
    "ENGINE_VERSION",
    "AssessmentFact",
    "CareGapFact",
    "ComponentResultFact",
    "ConsentFact",
    "EvaluationEngine",
    "FiredReason",
    "PatientContext",
    "PatientEvaluationSummary",
    "ReferralFact",
    "RuleEvaluationResult",
    "ScreeningEventFact",
    "VisitEventFact",
]
