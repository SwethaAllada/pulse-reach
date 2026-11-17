"""Tests for the bounded LLM explanation and outreach preview service (`app.services.explanation`).

Covers Workstream D3 & D4 of `pulse-reach-backend-execution-plan.md`:
- Valid structured evaluation produces a grounded explanation.
- Unknown history remains described as unknown.
- Blocked/review-flagged rules are never described as approved.
- No patient identifiers (Emirates ID, phone, email, real names) are allowed in LLM inputs.
- Invalid model output (inventing diagnoses, clinical thresholds, or claiming overdue when not overdue)
  is rejected and safely falls back to the deterministic template.
- Provider timeout/failure falls back to deterministic text.
- Outreach preview is blocked when contact consent is absent, withdrawn, or patient is deceased.
- LLM output cannot change the underlying `evaluation_status`.
"""

import pytest

from app.services.explanation import (
    BoundedExplanationInput,
    ExplanationService,
    OutreachPreviewInput,
    PrivacyViolationError,
)


def test_deterministic_explanation_for_due_and_unknown_and_review():
    svc = ExplanationService(llm_provider=None)

    due_in = BoundedExplanationInput(
        synthetic_patient_id="SYNTH-PAT-000001",
        pathway="ifhas",
        standard_name="Standard for the Provision of the Periodic Comprehensive Screening Program for Adults - IFHAS",
        rule_id="IFHAS-PKG-MAMMOGRAPHY-40-75",
        rule_version="1.0.0",
        source_reference="DoH/SD/ADPHC-CHS/IFHAS/V10/2025, Appendix 7, PDF p.21",
        verification_status="verified",
        is_authoritative=True,
        evaluation_status="due",
        history_status="available",
        reason_codes=(),
        guard_ids=(),
        open_question_ids=(),
    )
    res_due = svc.explain_evaluation(due_in)
    assert res_due.evaluation_status == "due"
    assert res_due.generation_mode == "deterministic_fallback"
    assert "IFHAS-PKG-MAMMOGRAPHY-40-75" in res_due.summary_text
    assert res_due.is_synthetic is True

    unk_in = BoundedExplanationInput(
        synthetic_patient_id="SYNTH-PAT-000007",
        pathway="ifhas",
        standard_name="IFHAS V10",
        rule_id="IFHAS-PKG-MAMMOGRAPHY-40-75",
        rule_version="1.0.0",
        source_reference="DoH/SD/ADPHC-CHS/IFHAS/V10/2025, Appendix 7, PDF p.21",
        verification_status="verified",
        is_authoritative=True,
        evaluation_status="unknown",
        history_status="not_available",
        reason_codes=("missing_screening_history",),
        guard_ids=("GUARD-MISSING-HISTORY",),
        open_question_ids=(),
    )
    res_unk = svc.explain_evaluation(unk_in)
    assert res_unk.evaluation_status == "unknown"
    assert "unknown" in res_unk.summary_text.lower()
    assert "not_available" in res_unk.missing_or_uncertain_text or "missing" in res_unk.missing_or_uncertain_text.lower()

    rev_in = BoundedExplanationInput(
        synthetic_patient_id="SYNTH-PAT-000003",
        pathway="ifhas",
        standard_name="IFHAS V10",
        rule_id="IFHAS-PKG-CERVICAL-HPV-30-65",
        rule_version="1.0.0",
        source_reference="DoH/SD/ADPHC-CHS/IFHAS/V10/2025, Appendix 7, PDF p.21",
        verification_status="verified",
        is_authoritative=False,
        evaluation_status="requires_clinical_review",
        history_status="available",
        reason_codes=("rule_requires_clinical_review",),
        guard_ids=("GUARD-RULE-REVIEW-FLAG",),
        open_question_ids=("OQ-IFHAS-CERVICAL-CONFLICT",),
    )
    res_rev = svc.explain_evaluation(rev_in)
    assert res_rev.evaluation_status == "requires_clinical_review"
    assert "clinical review" in res_rev.summary_text.lower()
    assert "OQ-IFHAS-CERVICAL-CONFLICT" in res_rev.warnings[0]


def test_privacy_guard_rejects_identifiers_in_prompt():
    svc = ExplanationService(llm_provider=None)
    bad_in = BoundedExplanationInput(
        synthetic_patient_id="784-1980-1234567-1",
        pathway="ifhas",
        standard_name="IFHAS V10",
        rule_id="IFHAS-PKG-MAMMOGRAPHY-40-75",
        rule_version="1.0.0",
        source_reference="Appendix 7",
        verification_status="verified",
        is_authoritative=True,
        evaluation_status="due",
        history_status="available",
    )
    with pytest.raises(PrivacyViolationError):
        svc.explain_evaluation(bad_in)


def test_mocked_llm_output_validation_and_fallback_on_unsafe_or_failed_provider():
    base_in = BoundedExplanationInput(
        synthetic_patient_id="SYNTH-PAT-000007",
        pathway="ifhas",
        standard_name="IFHAS V10",
        rule_id="IFHAS-PKG-MAMMOGRAPHY-40-75",
        rule_version="1.0.0",
        source_reference="DoH/SD/ADPHC-CHS/IFHAS/V10/2025, Appendix 7, PDF p.21",
        verification_status="verified",
        is_authoritative=True,
        evaluation_status="unknown",
        history_status="not_available",
        reason_codes=("missing_screening_history",),
        guard_ids=("GUARD-MISSING-HISTORY",),
    )

    # 1. Valid grounded LLM output
    svc_ok = ExplanationService(
        llm_provider=lambda prompt: (
            "Rule IFHAS-PKG-MAMMOGRAPHY-40-75 v1.0.0 evaluated as unknown because screening history is missing."
        )
    )
    res_ok = svc_ok.explain_evaluation(base_in)
    assert res_ok.generation_mode == "llm_grounded"
    assert res_ok.evaluation_status == "unknown"

    # 2. Unsafe LLM output claiming 'overdue' or 'diagnosed' -> rejected & falls back to deterministic
    svc_unsafe = ExplanationService(
        llm_provider=lambda prompt: "The patient is overdue and diagnosed with high risk (85% risk)."
    )
    res_fallback = svc_unsafe.explain_evaluation(base_in)
    assert res_fallback.generation_mode == "deterministic_fallback"
    assert res_fallback.evaluation_status == "unknown"
    assert "overdue" not in res_fallback.summary_text.lower()

    # 3. Provider timeout/exception -> falls back safely to deterministic
    def _failing_provider(prompt: str) -> str:
        raise TimeoutError("LLM provider timed out")

    svc_err = ExplanationService(llm_provider=_failing_provider)
    res_err = svc_err.explain_evaluation(base_in)
    assert res_err.generation_mode == "deterministic_fallback"
    assert res_err.evaluation_status == "unknown"


def test_outreach_preview_permission_and_safety_checks():
    svc = ExplanationService(llm_provider=None)

    # Allowed when contact consent is granted, patient alive, valid contact, open care gap
    allowed = svc.preview_outreach(
        OutreachPreviewInput(
            synthetic_patient_id="SYNTH-PAT-000001",
            care_gap_id="SYNTH-GAP-000001",
            rule_id="IFHAS-PKG-MAMMOGRAPHY-40-75",
            rule_version="1.0.0",
            channel="sms",
            language="en",
            contact_consent_state="granted",
            contact_status="valid",
            is_deceased=False,
        )
    )
    assert allowed.allowed is True
    assert allowed.simulated_only is True
    assert allowed.blocked_reason is None
    assert "SIMULATED OUTREACH PREVIEW" in allowed.preview_message

    # Blocked when consent is withdrawn, refused, or absent (None)
    for bad_consent in (None, "withdrawn", "refused"):
        blocked = svc.preview_outreach(
            OutreachPreviewInput(
                synthetic_patient_id="SYNTH-PAT-000021",
                care_gap_id="SYNTH-GAP-000010",
                rule_id="IFHAS-PKG-MAJOR-40-64",
                rule_version="1.0.0",
                channel="sms",
                language="en",
                contact_consent_state=bad_consent,
                contact_status="valid",
                is_deceased=False,
            )
        )
        assert blocked.allowed is False
        assert blocked.preview_message is None
        assert blocked.blocked_reason is not None

    # Blocked when patient is deceased
    deceased = svc.preview_outreach(
        OutreachPreviewInput(
            synthetic_patient_id="SYNTH-PAT-000022",
            care_gap_id="SYNTH-GAP-000011",
            rule_id="IFHAS-PKG-MAJOR-40-64",
            rule_version="1.0.0",
            channel="sms",
            language="en",
            contact_consent_state="granted",
            contact_status="valid",
            is_deceased=True,
        )
    )
    assert deceased.allowed is False
    assert deceased.blocked_reason == "patient_deceased"


def test_privacy_guard_scans_all_input_fields_and_llm_must_cite_rule_id():
    svc = ExplanationService(llm_provider=None)
    leaked_field_in = BoundedExplanationInput(
        synthetic_patient_id="SYNTH-PAT-000001",
        pathway="ifhas",
        standard_name="IFHAS V10",
        rule_id="IFHAS-PKG-MAMMOGRAPHY-40-75",
        rule_version="1.0.0",
        source_reference="Patient contact +971-50-123-4567 or patient@gmail.com",
        verification_status="verified",
        is_authoritative=True,
        evaluation_status="due",
        history_status="available",
    )
    with pytest.raises(PrivacyViolationError):
        svc.explain_evaluation(leaked_field_in)

    # LLM output that omits rule_id must be rejected and fall back to deterministic template
    svc_missing_rule = ExplanationService(
        llm_provider=lambda prompt: "Screening history is missing so status is unknown."
    )
    valid_in = BoundedExplanationInput(
        synthetic_patient_id="SYNTH-PAT-000007",
        pathway="ifhas",
        standard_name="IFHAS V10",
        rule_id="IFHAS-PKG-MAMMOGRAPHY-40-75",
        rule_version="1.0.0",
        source_reference="DoH/SD/ADPHC-CHS/IFHAS/V10/2025, Appendix 7, PDF p.21",
        verification_status="verified",
        is_authoritative=True,
        evaluation_status="unknown",
        history_status="not_available",
        reason_codes=("missing_screening_history",),
        guard_ids=("GUARD-MISSING-HISTORY",),
    )
    res = svc_missing_rule.explain_evaluation(valid_in)
    assert res.generation_mode == "deterministic_fallback"

