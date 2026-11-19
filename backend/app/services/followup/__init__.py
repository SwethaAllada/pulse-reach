"""Follow-up, appointment, and referral transition validation service (`T-09`)."""

from app.services.followup.completion import (
    CompletionEvidence,
    CompletionValidationResult,
    evaluate_current_rule,
    validate_completion_evidence,
)
from app.services.followup.service import FollowUpService, FollowUpValidationError

__all__ = [
    "CompletionEvidence",
    "CompletionValidationResult",
    "FollowUpService",
    "FollowUpValidationError",
    "evaluate_current_rule",
    "validate_completion_evidence",
]
