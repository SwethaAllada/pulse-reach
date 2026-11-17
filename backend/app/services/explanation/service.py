"""Bounded LLM explanation and simulated outreach preview service (`app.services.explanation.service`).

Implements Workstream D3 & D4 of `pulse-reach-backend-execution-plan.md`:
- The LLM is strictly an explanation layer over precomputed deterministic evaluation outputs, never
  a clinical decision-maker.
- Privacy guardrails reject any input containing non-synthetic identifiers (`784-...` Emirates IDs,
  real email domains, or non-`SYNTH-PAT-` display IDs).
- Output guardrails reject any LLM output that invents clinical thresholds, percentages, diagnostic
  claims, or claims `overdue` when `evaluation_status != 'overdue'`, falling back to a deterministic
  template assembled from approved reason descriptions.
- Simulated outreach previews require explicit `contact` consent (`state == 'granted'`), a living
  patient (`is_deceased is False`), and valid contact details (`contact_status == 'valid'`).
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Callable

_SYNTH_PAT_RE = re.compile(r"^SYNTH-PAT-\d{6,}$")
_EMIRATES_ID_RE = re.compile(r"\b784-?\d{4}-?\d{7}-?\d\b")
_PHONE_RE = re.compile(r"\+971[-\s]?\d{1,2}[-\s]?\d{3}[-\s]?\d{4}\b")
_EMAIL_RE = re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b")
_PERCENT_RISK_RE = re.compile(r"\b\d+(\.\d+)?%\s*(risk|chance|probability)\b", re.IGNORECASE)
_DIAGNOSIS_CLAIM_RE = re.compile(
    r"\b(diagnosed with|confirms cancer|definitive diagnosis|prescribe|dosage)\b",
    re.IGNORECASE,
)

REASON_DESCRIPTIONS: dict[str, str] = {
    "missing_date_of_birth": "Date of birth is missing from the record; age-dependent rules cannot be evaluated.",
    "missing_sex": "Sex attribute is missing or unknown; sex-specific eligibility cannot be determined.",
    "missing_required_attribute": "A required eligibility attribute (such as Thiqa membership or smoking history) is missing.",
    "missing_screening_history": "Eligibility criteria are met, but prior screening/visit history is unavailable (`unknown`, never 'not completed').",
    "conflicting_records": "Available records are partial or conflicting; case is routed to a healthcare professional for clinical review.",
    "rule_unresolved": "The governing standard clause or boundary is unresolved in the published standard; routed to clinical review.",
    "rule_reported_not_verified": "The rule comes from a secondary reported source rather than the numbered standard; cannot drive authoritative decisions.",
    "rule_requires_clinical_review": "The governing rule is flagged `requires_clinical_review = true`; no automated recommendation is produced.",
    "rule_item_unresolved": "One or more assessment items on this visit have `verification_status = unresolved` due to a source discrepancy.",
}


class PrivacyViolationError(ValueError):
    """Raised when an explanation request contains non-synthetic or identifying patient data."""


@dataclass(frozen=True)
class BoundedExplanationInput:
    synthetic_patient_id: str
    pathway: str
    standard_name: str
    rule_id: str
    rule_version: str
    source_reference: str
    verification_status: str
    is_authoritative: bool
    evaluation_status: str
    history_status: str
    reason_codes: tuple[str, ...] = ()
    guard_ids: tuple[str, ...] = ()
    open_question_ids: tuple[str, ...] = ()
    next_due_date: str | None = None


@dataclass(frozen=True)
class ExplanationResult:
    synthetic_patient_id: str
    rule_id: str
    rule_version: str
    evaluation_status: str
    is_authoritative: bool
    is_synthetic: bool
    generation_mode: str  # 'llm_grounded' | 'deterministic_fallback'
    summary_text: str
    why_text: str
    missing_or_uncertain_text: str
    rule_citation_text: str
    warnings: tuple[str, ...] = field(default_factory=tuple)


@dataclass(frozen=True)
class OutreachPreviewInput:
    synthetic_patient_id: str
    care_gap_id: str | None
    rule_id: str
    rule_version: str
    channel: str
    language: str
    contact_consent_state: str | None  # 'granted' | 'withdrawn' | 'refused' | None
    contact_status: str  # 'valid' | 'wrong' | 'unverified'
    is_deceased: bool = False


@dataclass(frozen=True)
class OutreachPreviewResult:
    synthetic_patient_id: str
    care_gap_id: str | None
    rule_id: str
    rule_version: str
    allowed: bool
    simulated_only: bool
    blocked_reason: str | None
    preview_message: str | None
    disclaimer: str


class ExplanationService:
    """Bounded explanation adapter with deterministic template fallback."""

    def __init__(self, llm_provider: Callable[[str], str] | None = None) -> None:
        self._llm_provider = llm_provider

    def _validate_privacy(
        self,
        synthetic_patient_id: str,
        extra_strings: tuple[str | None, ...] = (),
    ) -> None:
        if not _SYNTH_PAT_RE.match(synthetic_patient_id) or _EMIRATES_ID_RE.search(
            synthetic_patient_id
        ):
            raise PrivacyViolationError(
                f"synthetic_patient_id must match ^SYNTH-PAT-\\d{{6,}}$ and never contain real identifiers: {synthetic_patient_id!r}"
            )
        for val in extra_strings:
            if not val:
                continue
            if (
                _EMIRATES_ID_RE.search(val)
                or _PHONE_RE.search(val)
                or _EMAIL_RE.search(val)
            ):
                raise PrivacyViolationError(
                    f"Explanation input field contains prohibited personal/contact identifier: {val!r}"
                )

    def _build_deterministic(self, inp: BoundedExplanationInput) -> ExplanationResult:
        status = inp.evaluation_status
        warnings: list[str] = [
            "SYNTHETIC RECORD — Not clinically validated. All outputs require healthcare-professional review."
        ]
        if not inp.is_authoritative:
            warnings.insert(
                0,
                f"Rule {inp.rule_id} is non-authoritative (verification_status={inp.verification_status})"
                + (
                    f"; open questions: {', '.join(inp.open_question_ids)}."
                    if inp.open_question_ids
                    else "."
                ),
            )
        elif inp.open_question_ids:
            warnings.append(f"Linked open questions: {', '.join(inp.open_question_ids)}.")

        if status == "due":
            summary = (
                f"Synthetic participant {inp.synthetic_patient_id} is evaluated as DUE under verified rule "
                f"{inp.rule_id} v{inp.rule_version} ({inp.standard_name})."
            )
        elif status == "completed":
            summary = (
                f"Synthetic participant {inp.synthetic_patient_id} has a documented COMPLETED event within the "
                f"interval defined by {inp.rule_id} v{inp.rule_version}."
            )
        elif status == "upcoming":
            summary = (
                f"Synthetic participant {inp.synthetic_patient_id} is UPCOMING within the configured product "
                f"look-ahead window for {inp.rule_id} v{inp.rule_version} (next due: {inp.next_due_date})."
            )
        elif status == "unknown":
            summary = (
                f"Completion status for {inp.rule_id} v{inp.rule_version} is UNKNOWN because screening/visit "
                f"history is {inp.history_status}. Missing history is never treated as 'not completed' or 'due'."
            )
        elif status == "insufficient_information":
            summary = (
                f"No eligibility result can be produced for {inp.rule_id} v{inp.rule_version} "
                f"(INSUFFICIENT_INFORMATION) because a required attribute is missing."
            )
        elif status == "requires_clinical_review":
            summary = (
                f"Evaluation for {inp.rule_id} v{inp.rule_version} routes to clinical review "
                f"(REQUIRES_CLINICAL_REVIEW). No authoritative automated recommendation is made."
            )
        elif status == "eligible":
            summary = (
                f"Synthetic participant {inp.synthetic_patient_id} satisfies the programme/rule criteria "
                f"for {inp.rule_id} v{inp.rule_version} (ELIGIBLE)."
            )
        else:
            summary = (
                f"Synthetic participant {inp.synthetic_patient_id} is NOT_ELIGIBLE under the criteria of "
                f"{inp.rule_id} v{inp.rule_version}."
            )

        reasons_list = [
            REASON_DESCRIPTIONS.get(rc, f"Reason code: {rc}") for rc in inp.reason_codes
        ]
        why_text = (
            " ".join(reasons_list)
            if reasons_list
            else f"Evaluated deterministically against {inp.rule_id} v{inp.rule_version} with history_status='{inp.history_status}'."
        )

        if status in ("unknown", "insufficient_information", "requires_clinical_review"):
            missing_text = (
                f"History availability is '{inp.history_status}'. "
                f"Guards triggered: {', '.join(inp.guard_ids) if inp.guard_ids else 'none'}. "
                + (
                    f"Open questions: {', '.join(inp.open_question_ids)}."
                    if inp.open_question_ids
                    else "No definitive automated conclusion is permitted."
                )
            )
        else:
            missing_text = (
                f"History availability is '{inp.history_status}'."
                + (
                    f" Item-level guards noted: {', '.join(inp.guard_ids)}."
                    if inp.guard_ids
                    else " All required rule attributes and history were present."
                )
            )

        citation = f"{inp.standard_name} — {inp.source_reference} ({inp.rule_id} v{inp.rule_version})"

        return ExplanationResult(
            synthetic_patient_id=inp.synthetic_patient_id,
            rule_id=inp.rule_id,
            rule_version=inp.rule_version,
            evaluation_status=inp.evaluation_status,
            is_authoritative=inp.is_authoritative,
            is_synthetic=True,
            generation_mode="deterministic_fallback",
            summary_text=summary,
            why_text=why_text,
            missing_or_uncertain_text=missing_text,
            rule_citation_text=citation,
            warnings=tuple(warnings),
        )

    def _validate_llm_output(self, text: str, inp: BoundedExplanationInput) -> bool:
        if not text or not text.strip():
            return False
        if inp.rule_id not in text:
            return False
        if (
            _EMIRATES_ID_RE.search(text)
            or _PHONE_RE.search(text)
            or _EMAIL_RE.search(text)
            or _PERCENT_RISK_RE.search(text)
            or _DIAGNOSIS_CLAIM_RE.search(text)
        ):
            return False
        # Never allow LLM to claim 'overdue' when the deterministic engine did not return 'overdue'
        if inp.evaluation_status != "overdue" and re.search(r"\boverdue\b", text, re.IGNORECASE):
            return False
        # Never allow LLM to claim a non-authoritative rule is clinically approved
        if not inp.is_authoritative and re.search(
            r"\b(clinically approved|authoritative recommendation)\b", text, re.IGNORECASE
        ):
            return False
        return True

    def explain_evaluation(self, inp: BoundedExplanationInput) -> ExplanationResult:
        self._validate_privacy(
            inp.synthetic_patient_id,
            (
                inp.pathway,
                inp.standard_name,
                inp.rule_id,
                inp.rule_version,
                inp.source_reference,
                inp.verification_status,
                inp.evaluation_status,
                inp.history_status,
                inp.next_due_date,
                *inp.reason_codes,
                *inp.guard_ids,
                *inp.open_question_ids,
            ),
        )
        det = self._build_deterministic(inp)
        if self._llm_provider is None:
            return det

        prompt = (
            f"Explain deterministic evaluation for {inp.synthetic_patient_id}: "
            f"rule={inp.rule_id} v{inp.rule_version}, status={inp.evaluation_status}, "
            f"history={inp.history_status}, reasons={list(inp.reason_codes)}, "
            f"guards={list(inp.guard_ids)}, open_questions={list(inp.open_question_ids)}."
        )
        try:
            llm_text = self._llm_provider(prompt)
        except Exception:
            return det

        if not self._validate_llm_output(llm_text, inp):
            return det

        return ExplanationResult(
            synthetic_patient_id=det.synthetic_patient_id,
            rule_id=det.rule_id,
            rule_version=det.rule_version,
            evaluation_status=det.evaluation_status,
            is_authoritative=det.is_authoritative,
            is_synthetic=True,
            generation_mode="llm_grounded",
            summary_text=llm_text.strip(),
            why_text=det.why_text,
            missing_or_uncertain_text=det.missing_or_uncertain_text,
            rule_citation_text=det.rule_citation_text,
            warnings=det.warnings,
        )

    def preview_outreach(self, inp: OutreachPreviewInput) -> OutreachPreviewResult:
        self._validate_privacy(
            inp.synthetic_patient_id,
            (
                inp.care_gap_id,
                inp.rule_id,
                inp.rule_version,
                inp.channel,
                inp.language,
                inp.contact_consent_state,
                inp.contact_status,
            ),
        )
        disclaimer = (
            "SIMULATED OUTREACH PREVIEW ONLY — No real SMS, email, phone call, or push notification "
            "is ever sent by PulseReach."
        )

        if inp.is_deceased:
            return OutreachPreviewResult(
                synthetic_patient_id=inp.synthetic_patient_id,
                care_gap_id=inp.care_gap_id,
                rule_id=inp.rule_id,
                rule_version=inp.rule_version,
                allowed=False,
                simulated_only=True,
                blocked_reason="patient_deceased",
                preview_message=None,
                disclaimer=disclaimer,
            )

        if inp.contact_consent_state is None:
            return OutreachPreviewResult(
                synthetic_patient_id=inp.synthetic_patient_id,
                care_gap_id=inp.care_gap_id,
                rule_id=inp.rule_id,
                rule_version=inp.rule_version,
                allowed=False,
                simulated_only=True,
                blocked_reason="contact_consent_absent",
                preview_message=None,
                disclaimer=disclaimer,
            )

        if inp.contact_consent_state == "withdrawn":
            return OutreachPreviewResult(
                synthetic_patient_id=inp.synthetic_patient_id,
                care_gap_id=inp.care_gap_id,
                rule_id=inp.rule_id,
                rule_version=inp.rule_version,
                allowed=False,
                simulated_only=True,
                blocked_reason="contact_consent_withdrawn",
                preview_message=None,
                disclaimer=disclaimer,
            )

        if inp.contact_consent_state != "granted":
            return OutreachPreviewResult(
                synthetic_patient_id=inp.synthetic_patient_id,
                care_gap_id=inp.care_gap_id,
                rule_id=inp.rule_id,
                rule_version=inp.rule_version,
                allowed=False,
                simulated_only=True,
                blocked_reason=f"contact_consent_{inp.contact_consent_state}",
                preview_message=None,
                disclaimer=disclaimer,
            )

        if inp.contact_status != "valid":
            return OutreachPreviewResult(
                synthetic_patient_id=inp.synthetic_patient_id,
                care_gap_id=inp.care_gap_id,
                rule_id=inp.rule_id,
                rule_version=inp.rule_version,
                allowed=False,
                simulated_only=True,
                blocked_reason=f"contact_details_{inp.contact_status}",
                preview_message=None,
                disclaimer=disclaimer,
            )

        msg = (
            f"[SIMULATED OUTREACH PREVIEW — {inp.channel.upper()} ({inp.language})] "
            f"Dear synthetic participant ({inp.synthetic_patient_id}), our records indicate you may be "
            f"due for preventive screening under rule {inp.rule_id} (v{inp.rule_version}). "
            f"Please consult a licensed healthcare professional to review your eligibility."
        )
        return OutreachPreviewResult(
            synthetic_patient_id=inp.synthetic_patient_id,
            care_gap_id=inp.care_gap_id,
            rule_id=inp.rule_id,
            rule_version=inp.rule_version,
            allowed=True,
            simulated_only=True,
            blocked_reason=None,
            preview_message=msg,
            disclaimer=disclaimer,
        )
