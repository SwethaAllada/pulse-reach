"""Deterministic follow-up, appointment, and referral transition validation (`T-09`)."""

from __future__ import annotations

from datetime import date
from typing import Any

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

    def evaluate_outreach_consent(
        self,
        *,
        patient: dict[str, Any],
        consents: list[dict[str, Any]],
        pathway: str,
        rule_id: str,
        rule_meta: dict[str, Any] | None = None,
        care_gap: dict[str, Any] | None = None,
    ) -> tuple[bool, str | None, str | None]:
        """Return `(allowed, contact_consent_id, blocked_reason)` using D18 consent rules."""
        meta = rule_meta or {
            "rule_id": rule_id,
            "rule_version": "1.0",
            "pathway": pathway,
            "is_authoritative": True,
        }
        gap_list = (
            [care_gap]
            if care_gap is not None
            else [{"care_gap_id": "SYNTH-GAP-000001", "rule_id": rule_id, "status": "open"}]
        )
        res = self._outreach.preview_outreach(
            patient=patient,
            rule=meta,
            rule_id=rule_id,
            evaluations=[
                {
                    "rule_id": rule_id,
                    "rule_version": meta.get("rule_version", "1.0"),
                    "evaluation_status": "due",
                }
            ],
            care_gaps=gap_list,
            consents=consents,
            channel=patient.get("preferred_channel", "sms"),
            language=patient.get("preferred_language", "en"),
        )
        contact_consents = [
            c
            for c in consents
            if c.get("consent_type") == "contact"
            and c.get("state") == "granted"
            and c.get("scope_pathway") in (None, pathway)
        ]
        consent_id = (
            max(contact_consents, key=lambda c: (c["recorded_at"], c["consent_id"]))["consent_id"]
            if contact_consents
            else None
        )
        return res.allowed, consent_id, res.blocked_reason
