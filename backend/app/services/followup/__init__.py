"""Follow-up, appointment, and referral transition validation service (`T-09`)."""

from app.services.followup.service import FollowUpService, FollowUpValidationError

__all__ = ["FollowUpService", "FollowUpValidationError"]
