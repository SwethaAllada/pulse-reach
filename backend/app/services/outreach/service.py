"""Dedicated simulated outreach preview and consent-gating service (`app.services.outreach.service`).

Implements T-01 from `pulse-reach-next-backend-implementation-plan.md`:
- Unknown rules raise `OutreachRuleNotFoundError` (HTTP 404).
- Non-authoritative or review-required rules are blocked (`rule_not_authoritative`).
- Requires a matching open care gap (`no_open_care_gap`) and a `due` evaluation (`evaluation_not_due`).
- Resolves applicable `contact` consent using `v_consent_current` semantics (latest `recorded_at`
  per scope, then latest applicable scope by `(recorded_at, specificity, consent_id)`), so a
  newer withdrawal or refusal always overrides an older grant and mismatched scopes never authorize.
- Blocks unsupported language templates (`template_unavailable`) rather than mislabelling English.
- Uses the actual rule version and always keeps `simulated_only=True`.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Mapping, Sequence

from app.services.explanation.service import (
    ExplanationService,
    OutreachPreviewResult,
)

SUPPORTED_OUTREACH_LANGUAGES: frozenset[str] = frozenset({"en"})

_OUTREACH_DISCLAIMER = (
    "SIMULATED OUTREACH PREVIEW ONLY — No real SMS, email, phone call, or push notification "
    "is ever sent by PulseReach."
)


class OutreachRuleNotFoundError(LookupError):
    """Raised when the requested clinical rule_id does not exist."""


def _parse_recorded_at(val: Any) -> datetime:
    if isinstance(val, datetime):
        return val if val.tzinfo is not None else val.replace(tzinfo=timezone.utc)
    if isinstance(val, str):
        dt = datetime.fromisoformat(val)
        return dt if dt.tzinfo is not None else dt.replace(tzinfo=timezone.utc)
    return datetime.min.replace(tzinfo=timezone.utc)


def _consent_scope_specificity(
    consent: Mapping[str, Any], *, rule_id: str, pathway: str
) -> int | None:
    """Return scope specificity (2=rule, 1=pathway, 0=global) or None if inapplicable."""
    c_rule = consent.get("scope_rule_id")
    c_pathway = consent.get("scope_pathway")

    if c_rule is not None:
        return 2 if c_rule == rule_id else None
    if c_pathway is not None:
        return 1 if c_pathway == pathway else None
    return 0


def resolve_applicable_contact_consent(
    consents: Sequence[Mapping[str, Any]],
    *,
    rule_id: str,
    pathway: str,
) -> Mapping[str, Any] | None:
    """Resolve the current applicable `contact` consent matching `v_consent_current` semantics."""
    # Group by (scope_pathway, scope_rule_id) and keep latest (recorded_at, consent_id) per scope.
    latest_per_scope: dict[tuple[str, str], tuple[int, Mapping[str, Any]]] = {}
    for c in consents:
        if c.get("consent_type") != "contact":
            continue
        spec = _consent_scope_specificity(c, rule_id=rule_id, pathway=pathway)
        if spec is None:
            continue
        scope_key = (str(c.get("scope_pathway") or ""), str(c.get("scope_rule_id") or ""))
        cur = latest_per_scope.get(scope_key)
        c_key = (_parse_recorded_at(c.get("recorded_at")), str(c.get("consent_id") or ""))
        if cur is None:
            latest_per_scope[scope_key] = (spec, c)
        else:
            prev_c = cur[1]
            prev_key = (
                _parse_recorded_at(prev_c.get("recorded_at")),
                str(prev_c.get("consent_id") or ""),
            )
            if c_key > prev_key:
                latest_per_scope[scope_key] = (spec, c)

    if not latest_per_scope:
        return None

    # Among current per-scope consents, the newest recorded_at wins (newer withdrawal overrides
    # older grant); ties at identical timestamp break by scope specificity, then consent_id.
    _, winner = max(
        latest_per_scope.values(),
        key=lambda item: (
            _parse_recorded_at(item[1].get("recorded_at")),
            item[0],
            str(item[1].get("consent_id") or ""),
        ),
    )
    return winner


class OutreachService:
    """Permission-checked simulated outreach preview service."""

    def __init__(self) -> None:
        self._privacy = ExplanationService(llm_provider=None)

    def _blocked(
        self,
        *,
        patient_id: str,
        care_gap_id: str | None,
        rule_id: str,
        rule_version: str,
        reason: str,
    ) -> OutreachPreviewResult:
        return OutreachPreviewResult(
            synthetic_patient_id=patient_id,
            care_gap_id=care_gap_id,
            rule_id=rule_id,
            rule_version=rule_version,
            allowed=False,
            simulated_only=True,
            blocked_reason=reason,
            preview_message=None,
            disclaimer=_OUTREACH_DISCLAIMER,
        )

    def preview_outreach(
        self,
        *,
        patient: Mapping[str, Any],
        rule: Mapping[str, Any] | None,
        rule_id: str,
        evaluations: Sequence[Mapping[str, Any]],
        care_gaps: Sequence[Mapping[str, Any]],
        consents: Sequence[Mapping[str, Any]],
        channel: str,
        language: str,
    ) -> OutreachPreviewResult:
        if rule is None:
            raise OutreachRuleNotFoundError(f"Clinical rule '{rule_id}' not found")

        patient_id = str(patient["patient_id"])
        rule_version = str(rule["rule_version"])
        pathway = str(rule["pathway"])

        open_gap = next(
            (g for g in care_gaps if g.get("rule_id") == rule_id and g.get("status") == "open"),
            None,
        )
        care_gap_id = str(open_gap["care_gap_id"]) if open_gap else None

        self._privacy._validate_privacy(
            patient_id,
            (
                care_gap_id,
                rule_id,
                rule_version,
                channel,
                language,
                str(patient.get("contact_status") or ""),
            ),
        )

        if patient.get("date_of_death") is not None:
            return self._blocked(
                patient_id=patient_id,
                care_gap_id=care_gap_id,
                rule_id=rule_id,
                rule_version=rule_version,
                reason="patient_deceased",
            )

        is_authoritative = bool(rule.get("is_authoritative")) and not bool(
            rule.get("requires_clinical_review")
        )
        if not is_authoritative or rule.get("verification_status") != "verified":
            return self._blocked(
                patient_id=patient_id,
                care_gap_id=care_gap_id,
                rule_id=rule_id,
                rule_version=rule_version,
                reason="rule_not_authoritative",
            )

        if open_gap is None:
            return self._blocked(
                patient_id=patient_id,
                care_gap_id=None,
                rule_id=rule_id,
                rule_version=rule_version,
                reason="no_open_care_gap",
            )

        matching_eval = next((ev for ev in evaluations if ev.get("rule_id") == rule_id), None)
        if matching_eval is None or matching_eval.get("evaluation_status") != "due":
            return self._blocked(
                patient_id=patient_id,
                care_gap_id=care_gap_id,
                rule_id=rule_id,
                rule_version=rule_version,
                reason="evaluation_not_due",
            )

        consent = resolve_applicable_contact_consent(
            consents, rule_id=rule_id, pathway=pathway
        )
        if consent is None:
            return self._blocked(
                patient_id=patient_id,
                care_gap_id=care_gap_id,
                rule_id=rule_id,
                rule_version=rule_version,
                reason="contact_consent_absent",
            )

        consent_state = str(consent.get("state") or "")
        if consent_state == "withdrawn":
            return self._blocked(
                patient_id=patient_id,
                care_gap_id=care_gap_id,
                rule_id=rule_id,
                rule_version=rule_version,
                reason="contact_consent_withdrawn",
            )
        if consent_state == "refused":
            return self._blocked(
                patient_id=patient_id,
                care_gap_id=care_gap_id,
                rule_id=rule_id,
                rule_version=rule_version,
                reason="contact_consent_refused",
            )
        if consent_state != "granted":
            return self._blocked(
                patient_id=patient_id,
                care_gap_id=care_gap_id,
                rule_id=rule_id,
                rule_version=rule_version,
                reason=f"contact_consent_{consent_state}",
            )

        contact_status = str(patient.get("contact_status") or "unverified")
        if contact_status != "valid":
            return self._blocked(
                patient_id=patient_id,
                care_gap_id=care_gap_id,
                rule_id=rule_id,
                rule_version=rule_version,
                reason=f"contact_details_{contact_status}",
            )

        if language not in SUPPORTED_OUTREACH_LANGUAGES:
            return self._blocked(
                patient_id=patient_id,
                care_gap_id=care_gap_id,
                rule_id=rule_id,
                rule_version=rule_version,
                reason="template_unavailable",
            )

        msg = (
            f"[SIMULATED OUTREACH PREVIEW — {channel.upper()} ({language})] "
            f"Dear synthetic participant ({patient_id}), our records indicate you may be "
            f"due for preventive screening under rule {rule_id} (v{rule_version}). "
            f"Please consult a licensed healthcare professional to review your eligibility."
        )
        return OutreachPreviewResult(
            synthetic_patient_id=patient_id,
            care_gap_id=care_gap_id,
            rule_id=rule_id,
            rule_version=rule_version,
            allowed=True,
            simulated_only=True,
            blocked_reason=None,
            preview_message=msg,
            disclaimer=_OUTREACH_DISCLAIMER,
        )
