"""Regression tests for T-01: Outreach preview safety and consent/scope resolution."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.services.explanation import PrivacyViolationError
from app.services.outreach import OutreachRuleNotFoundError, OutreachService

client = TestClient(app)


def _base_patient(patient_id: str = "SYNTH-PAT-000001", **overrides):
    p = {
        "patient_id": patient_id,
        "contact_status": "valid",
        "date_of_death": None,
    }
    p.update(overrides)
    return p


def _base_rule(rule_id: str = "IFHAS-PKG-MAMMOGRAPHY-40-75", **overrides):
    r = {
        "rule_id": rule_id,
        "rule_version": "2.3.0",
        "pathway": "ifhas",
        "is_authoritative": True,
        "requires_clinical_review": False,
        "verification_status": "verified",
    }
    r.update(overrides)
    return r


def _base_eval(rule_id: str = "IFHAS-PKG-MAMMOGRAPHY-40-75", **overrides):
    ev = {
        "evaluation_id": "SYNTH-EVL-000001",
        "rule_id": rule_id,
        "rule_version": "2.3.0",
        "evaluation_status": "due",
    }
    ev.update(overrides)
    return ev


def _base_gap(rule_id: str = "IFHAS-PKG-MAMMOGRAPHY-40-75", **overrides):
    g = {
        "care_gap_id": "SYNTH-GAP-000001",
        "rule_id": rule_id,
        "rule_version": "2.3.0",
        "status": "open",
    }
    g.update(overrides)
    return g


def _consent(
    consent_id: str,
    state: str,
    recorded_at: datetime,
    *,
    consent_type: str = "contact",
    scope_pathway: str | None = None,
    scope_rule_id: str | None = None,
):
    return {
        "consent_id": consent_id,
        "consent_type": consent_type,
        "state": state,
        "scope_pathway": scope_pathway,
        "scope_rule_id": scope_rule_id,
        "recorded_at": recorded_at,
    }


def test_unknown_rule_raises_not_found():
    svc = OutreachService()
    with pytest.raises(OutreachRuleNotFoundError):
        svc.preview_outreach(
            patient=_base_patient(),
            rule=None,
            rule_id="NONEXISTENT-RULE",
            evaluations=[],
            care_gaps=[],
            consents=[],
            channel="sms",
            language="en",
        )


def test_non_authoritative_rule_is_blocked_with_real_version():
    svc = OutreachService()
    res = svc.preview_outreach(
        patient=_base_patient(),
        rule=_base_rule(
            rule_id="IFHAS-PKG-CERVICAL-HPV-30-65",
            rule_version="3.1.0",
            is_authoritative=False,
            requires_clinical_review=True,
        ),
        rule_id="IFHAS-PKG-CERVICAL-HPV-30-65",
        evaluations=[
            _base_eval(rule_id="IFHAS-PKG-CERVICAL-HPV-30-65", evaluation_status="requires_clinical_review")
        ],
        care_gaps=[],
        consents=[
            _consent("SYNTH-CON-1", "granted", datetime(2026, 1, 1, tzinfo=timezone.utc))
        ],
        channel="sms",
        language="en",
    )
    assert res.allowed is False
    assert res.blocked_reason == "rule_not_authoritative"
    assert res.rule_version == "3.1.0"
    assert res.preview_message is None


def test_missing_open_care_gap_is_blocked():
    svc = OutreachService()
    res = svc.preview_outreach(
        patient=_base_patient(),
        rule=_base_rule(),
        rule_id="IFHAS-PKG-MAMMOGRAPHY-40-75",
        evaluations=[_base_eval(evaluation_status="due")],
        care_gaps=[_base_gap(status="closed_completed")],
        consents=[
            _consent("SYNTH-CON-1", "granted", datetime(2026, 1, 1, tzinfo=timezone.utc))
        ],
        channel="sms",
        language="en",
    )
    assert res.allowed is False
    assert res.blocked_reason == "no_open_care_gap"
    assert res.rule_version == "2.3.0"


def test_non_due_evaluation_is_blocked():
    svc = OutreachService()
    res = svc.preview_outreach(
        patient=_base_patient(),
        rule=_base_rule(),
        rule_id="IFHAS-PKG-MAMMOGRAPHY-40-75",
        evaluations=[_base_eval(evaluation_status="completed")],
        care_gaps=[_base_gap(status="open")],
        consents=[
            _consent("SYNTH-CON-1", "granted", datetime(2026, 1, 1, tzinfo=timezone.utc))
        ],
        channel="sms",
        language="en",
    )
    assert res.allowed is False
    assert res.blocked_reason == "evaluation_not_due"


def test_newer_withdrawal_or_refusal_overrides_older_grant():
    svc = OutreachService()
    # Even if the older grant appears *last* in the input list, recorded_at determines precedence.
    older_grant = _consent("SYNTH-CON-1", "granted", datetime(2026, 1, 1, tzinfo=timezone.utc))
    newer_withdrawal = _consent("SYNTH-CON-2", "withdrawn", datetime(2026, 6, 1, tzinfo=timezone.utc))

    res = svc.preview_outreach(
        patient=_base_patient(),
        rule=_base_rule(),
        rule_id="IFHAS-PKG-MAMMOGRAPHY-40-75",
        evaluations=[_base_eval()],
        care_gaps=[_base_gap()],
        consents=[newer_withdrawal, older_grant],
        channel="sms",
        language="en",
    )
    assert res.allowed is False
    assert res.blocked_reason == "contact_consent_withdrawn"

    newer_refusal = _consent("SYNTH-CON-3", "refused", datetime(2026, 7, 1, tzinfo=timezone.utc))
    res_ref = svc.preview_outreach(
        patient=_base_patient(),
        rule=_base_rule(),
        rule_id="IFHAS-PKG-MAMMOGRAPHY-40-75",
        evaluations=[_base_eval()],
        care_gaps=[_base_gap()],
        consents=[older_grant, newer_refusal],
        channel="sms",
        language="en",
    )
    assert res_ref.allowed is False
    assert res_ref.blocked_reason == "contact_consent_refused"


def test_consent_for_different_pathway_or_rule_does_not_authorize():
    svc = OutreachService()
    other_pathway = _consent(
        "SYNTH-CON-1",
        "granted",
        datetime(2026, 6, 1, tzinfo=timezone.utc),
        scope_pathway="well_child",
    )
    other_rule = _consent(
        "SYNTH-CON-2",
        "granted",
        datetime(2026, 6, 2, tzinfo=timezone.utc),
        scope_pathway="ifhas",
        scope_rule_id="IFHAS-PKG-MAJOR-40-64",
    )
    res = svc.preview_outreach(
        patient=_base_patient(),
        rule=_base_rule(rule_id="IFHAS-PKG-MAMMOGRAPHY-40-75", pathway="ifhas"),
        rule_id="IFHAS-PKG-MAMMOGRAPHY-40-75",
        evaluations=[_base_eval(rule_id="IFHAS-PKG-MAMMOGRAPHY-40-75")],
        care_gaps=[_base_gap(rule_id="IFHAS-PKG-MAMMOGRAPHY-40-75")],
        consents=[other_pathway, other_rule],
        channel="sms",
        language="en",
    )
    assert res.allowed is False
    assert res.blocked_reason == "contact_consent_absent"


def test_arabic_language_without_approved_template_is_blocked():
    svc = OutreachService()
    res = svc.preview_outreach(
        patient=_base_patient(),
        rule=_base_rule(),
        rule_id="IFHAS-PKG-MAMMOGRAPHY-40-75",
        evaluations=[_base_eval()],
        care_gaps=[_base_gap()],
        consents=[_consent("SYNTH-CON-1", "granted", datetime(2026, 1, 1, tzinfo=timezone.utc))],
        channel="sms",
        language="ar",
    )
    assert res.allowed is False
    assert res.blocked_reason == "template_unavailable"
    assert res.preview_message is None


def test_privacy_violation_rejected_by_outreach_service():
    svc = OutreachService()
    with pytest.raises(PrivacyViolationError):
        svc.preview_outreach(
            patient=_base_patient(patient_id="784-1990-1234567-1"),
            rule=_base_rule(),
            rule_id="IFHAS-PKG-MAMMOGRAPHY-40-75",
            evaluations=[_base_eval()],
            care_gaps=[_base_gap()],
            consents=[],
            channel="sms",
            language="en",
        )


def test_api_outreach_preview_unknown_rule_returns_404_and_non_authoritative_blocked():
    r_404 = client.post(
        "/api/v1/outreach/preview",
        json={
            "patient_id": "SYNTH-PAT-000001",
            "rule_id": "DOES-NOT-EXIST",
            "channel": "sms",
            "language": "en",
        },
    )
    assert r_404.status_code == 404

    r_non_auth = client.post(
        "/api/v1/outreach/preview",
        json={
            "patient_id": "SYNTH-PAT-000003",
            "rule_id": "IFHAS-PKG-CERVICAL-HPV-30-65",
            "channel": "sms",
            "language": "en",
        },
    )
    assert r_non_auth.status_code == 200
    body = r_non_auth.json()
    assert body["allowed"] is False
    assert body["blocked_reason"] == "rule_not_authoritative"

    r_ar = client.post(
        "/api/v1/outreach/preview",
        json={
            "patient_id": "SYNTH-PAT-000001",
            "rule_id": "IFHAS-PKG-MAMMOGRAPHY-40-75",
            "channel": "sms",
            "language": "ar",
        },
    )
    assert r_ar.status_code == 200
    assert r_ar.json()["allowed"] is False
    assert r_ar.json()["blocked_reason"] == "template_unavailable"
