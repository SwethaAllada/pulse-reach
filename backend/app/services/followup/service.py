"""Deterministic follow-up, appointment, and referral transition validation (`T-09`)."""

from __future__ import annotations

from datetime import date
from typing import Any

from app.services.followup.completion import (
    CompletionEvidence,
    CompletionValidationResult,
    validate_completion_evidence,
)
from app.services.evaluation.engine import RuleEvaluationResult
from app.services.outreach.service import OutreachService


class FollowUpValidationError(ValueError):
    """Raised when a follow-up, appointment, or referral transition violates governance."""


_APPOINTMENT_TRANSITIONS: dict[str, frozenset[str]] = {
    "scheduled": frozenset(
        {"attended", "no_show", "cancelled_by_patient", "cancelled_by_facility", "rescheduled"}
    ),
    "rescheduled": frozenset(
        {"attended", "no_show", "cancelled_by_patient", "cancelled_by_facility", "rescheduled"}
    ),
    "attended": frozenset(),
    "no_show": frozenset(),
    "cancelled_by_patient": frozenset(),
    "cancelled_by_facility": frozenset(),
}

_REFERRAL_TRANSITIONS: dict[str, frozenset[str]] = {
    "pending": frozenset({"initiated", "declined", "cancelled"}),
    "initiated": frozenset({"completed", "declined", "cancelled"}),
    "completed": frozenset(),
    "declined": frozenset(),
    "cancelled": frozenset(),
}


class FollowUpService:
    """Validates care-gap follow-ups, appointments, and referral state transitions."""

    def __init__(self, outreach_service: OutreachService | None = None) -> None:
        self._outreach = outreach_service or OutreachService()

    def validate_appointment_transition(self, current_status: str, new_status: str) -> None:
        allowed = _APPOINTMENT_TRANSITIONS.get(current_status)
        if allowed is None or new_status not in allowed:
            raise FollowUpValidationError(
                f"Cannot transition appointment from '{current_status}' to '{new_status}'."
            )

    def validate_referral_create(
        self,
        *,
        ifhas_screening_id: str | None,
        well_child_visit_id: str | None,
        assessment_id: str | None,
        status: str,
        trigger_date: date,
        initiated_date: date | None,
        completed_date: date | None,
    ) -> None:
        source_count = sum(
            1 for x in (ifhas_screening_id, well_child_visit_id, assessment_id) if x is not None
        )
        if source_count != 1:
            raise FollowUpValidationError(
                "Referral must link to exactly one source event "
                "(ifhas_screening_id, well_child_visit_id, or assessment_id)."
            )
        if status not in _REFERRAL_TRANSITIONS:
            raise FollowUpValidationError(f"Unsupported referral status '{status}'.")
        self._validate_referral_dates(
            status=status,
            trigger_date=trigger_date,
            initiated_date=initiated_date,
            completed_date=completed_date,
        )

    def validate_referral_transition(
        self,
        current_status: str,
        new_status: str,
        *,
        trigger_date: date,
        initiated_date: date | None,
        completed_date: date | None,
    ) -> None:
        allowed = _REFERRAL_TRANSITIONS.get(current_status)
        if allowed is None or new_status not in allowed:
            raise FollowUpValidationError(
                f"Cannot transition referral from '{current_status}' to '{new_status}'."
            )
        self._validate_referral_dates(
            status=new_status,
            trigger_date=trigger_date,
            initiated_date=initiated_date,
            completed_date=completed_date,
        )

    @staticmethod
    def _validate_referral_dates(
        *,
        status: str,
        trigger_date: date,
        initiated_date: date | None,
        completed_date: date | None,
    ) -> None:
        if status in ("initiated", "completed") and initiated_date is None:
            raise FollowUpValidationError(
                f"Referral status '{status}' requires initiated_date."
            )
        if initiated_date is not None and initiated_date < trigger_date:
            raise FollowUpValidationError("initiated_date cannot precede trigger_date.")
        if status == "completed" and completed_date is None:
            raise FollowUpValidationError("Referral status 'completed' requires completed_date.")
        if completed_date is not None:
            if initiated_date is None or completed_date < initiated_date:
                raise FollowUpValidationError(
                    "completed_date requires initiated_date and must be on or after initiated_date."
                )

    def validate_gap_completion(
        self, *, documented_evidence: bool, evidence_reference: str | None
    ) -> None:
        if not documented_evidence or not (evidence_reference and evidence_reference.strip()):
            raise FollowUpValidationError(
                "Closing a care gap as 'closed_completed' requires documented completion evidence "
                "(documented_evidence=True and non-empty evidence_reference)."
            )

    def validate_completion_evidence(
        self,
        *,
        gap: dict[str, Any],
        rule: dict[str, Any] | None,
        evidence: CompletionEvidence | None,
        documented_evidence: bool,
        evidence_reference: str | None,
        as_of: date,
        current_evaluation: RuleEvaluationResult | None,
    ) -> CompletionValidationResult:
        """Shared completion-evidence gate used by every path that closes a gap as completed."""
        return validate_completion_evidence(
            gap=gap,
            rule=rule,
            evidence=evidence,
            documented_evidence=documented_evidence,
            evidence_reference=evidence_reference,
            as_of=as_of,
            current_evaluation=current_evaluation,
        )

    def evaluate_outreach_consent(
        self,
        *,
        patient: dict[str, Any],
        consents: list[dict[str, Any]],
        rule_meta: dict[str, Any] | None,
        care_gap: dict[str, Any],
        evaluations: list[dict[str, Any]],
    ) -> tuple[bool, str | None, str | None]:
        """Return `(allowed, contact_consent_id, blocked_reason)` using D18 consent rules.

        Every input is required: nothing (authority, open gap, `due` evaluation) is assumed.
        """
        from app.services.outreach.service import resolve_applicable_contact_consent

        if rule_meta is None:
            return False, None, "rule_not_found"
        res = self._outreach.preview_outreach(
            patient=patient,
            rule=rule_meta,
            rule_id=care_gap["rule_id"],
            evaluations=evaluations,
            care_gaps=[care_gap],
            consents=consents,
            channel=patient.get("preferred_channel", "sms"),
            language=patient.get("preferred_language", "en"),
        )
        resolved = resolve_applicable_contact_consent(
            consents, rule_id=care_gap["rule_id"], pathway=rule_meta["pathway"]
        )
        consent_id = (
            str(resolved["consent_id"])
            if resolved is not None and resolved.get("state") == "granted"
            else None
        )
        return res.allowed, consent_id, res.blocked_reason

    def outreach_attempt_outcome(
        self, *, allowed: bool, consent_id: str | None, blocked_reason: str | None
    ) -> tuple[str, str, str | None, str | None]:
        """Map the consent gate to `(event_type, outcome_status, consent_id, suppression_reason)`.

        Outreach is simulated: an authorised attempt is recorded as `simulated_not_sent`, never as
        sent or delivered. A missing message template (`template_unavailable`) is a content gap,
        not a lack of authorisation, so a consented attempt is still recorded as authorised.
        Anything else - including absent, withdrawn or refused consent - is suppressed.
        """
        if consent_id and (allowed or blocked_reason == "template_unavailable"):
            return "outreach_attempted", "simulated_not_sent", consent_id, None
        return "outreach_suppressed", "suppressed", None, blocked_reason or "contact_consent_absent"
