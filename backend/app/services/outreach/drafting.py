"""Pre-generation gate and approved content for AI-assisted outreach drafts.

Every check runs before any model call, in this order: channel supported -> language supported ->
consent/authority gate (`OutreachService.preview_outreach`: deceased, rule authority, open gap,
`due` evaluation, current `contact` consent granted and not expired, valid contact details) ->
requested care gap is that open gap -> channel permitted for the consenting recipient -> the gap
has a documented next step. A failure returns a reason and no draft, never a fallback template.

The consent schema records no channel scope, so channel permission is derived from the person's
recorded contact preference (`preferred_channel`) and the presence of contact details for it.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping, Sequence

from app.services.care_pathway import recommended_pathway
from app.services.explanation.service import OutreachPreviewResult
from app.services.outreach.service import (
    SUPPORTED_OUTREACH_LANGUAGES,
    resolve_applicable_contact_consent,
)

SUPPORTED_CHANNELS: tuple[str, ...] = ("sms", "phone", "email", "app")
APPROVED_TONES: tuple[str, ...] = ("supportive", "neutral")
CHANNEL_MAX_CHARS = {"sms": 320, "app": 400, "email": 700, "phone": 500}
_CHANNEL_CONTACT_FIELD = {
    "sms": "phone_synthetic",
    "phone": "phone_synthetic",
    "email": "email_synthetic",
    "app": "registered_profile_id",
}

PROGRAMME_NAMES = {
    "ifhas": "IFHAS preventive screening programme",
    "well_child": "Well-Child preventive care programme",
}
PROGRAMME_NAMES_AR = {
    "ifhas": "برنامج الفحص الوقائي IFHAS",
    "well_child": "برنامج رعاية الطفل السليم الوقائي",
}
_GAP_CATEGORY_TEXT = {
    ("ifhas", "no_documented_screening"): "no preventive screening is documented for you",
    ("well_child", "no_documented_screening"): "no well-child visit is documented",
    ("ifhas", "partial_completion"): "some parts of your preventive screening are not yet documented",
    ("well_child", "partial_completion"): "some parts of the well-child visit are not yet documented",
    ("ifhas", "visit_not_attended"): "a planned preventive visit is not documented as attended",
    ("well_child", "visit_not_attended"): "a planned well-child visit is not documented as attended",
    ("ifhas", "referral_not_initiated"): "a follow-up step noted in your record is not yet documented",
    ("well_child", "referral_not_initiated"): "a follow-up step noted in the record is not yet documented",
}
_GAP_CATEGORY_TEXT_AR = {
    ("ifhas", "no_documented_screening"): "لا يوجد فحص وقائي موثّق لك",
    ("well_child", "no_documented_screening"): "لا توجد زيارة موثّقة للطفل السليم",
    ("ifhas", "partial_completion"): "بعض أجزاء فحصك الوقائي غير موثّقة بعد",
    ("well_child", "partial_completion"): "بعض أجزاء زيارة الطفل السليم غير موثّقة بعد",
    ("ifhas", "visit_not_attended"): "زيارة وقائية مخططة غير موثّقة على أنها تمت",
    ("well_child", "visit_not_attended"): "زيارة مخططة للطفل السليم غير موثّقة على أنها تمت",
    ("ifhas", "referral_not_initiated"): "خطوة متابعة مذكورة في سجلك غير موثّقة بعد",
    ("well_child", "referral_not_initiated"): "خطوة متابعة مذكورة في السجل غير موثّقة بعد",
}
_NEXT_STEP_TEXT_AR = {
    "offer_screening_package": "التواصل مع مقدّم الرعاية الوقائية لترتيب فحص البرنامج",
    "complete_outstanding_components": "التواصل مع مقدّم الرعاية الوقائية لاستكمال الأجزاء المتبقية",
    "schedule_well_child_visit": "التواصل مع مقدّم الرعاية الوقائية لترتيب زيارة الطفل السليم",
    "initiate_referral": "التواصل مع مقدّم الرعاية الوقائية بشأن خطوة المتابعة المذكورة في سجلك",
}
_NEXT_STEP_TEXT = {
    "offer_screening_package": "contact your preventive-care provider to arrange the programme screening",
    "complete_outstanding_components": "contact your preventive-care provider to complete the remaining parts",
    "schedule_well_child_visit": "contact your preventive-care provider to arrange the well-child visit",
    "initiate_referral": "contact your preventive-care provider about the follow-up step in your record",
}


@dataclass(frozen=True)
class OutreachDraftGate:
    allowed: bool
    blocked_reason: str | None
    patient_id: str
    rule_id: str
    rule_version: str | None
    care_gap_id: str | None
    channel: str
    language: str
    tone: str
    recipient: str | None = None
    contact_consent_id: str | None = None
    next_step: dict[str, Any] | None = None
    facts: dict[str, Any] = field(default_factory=dict)
    deterministic_body: str | None = None
    run_id: str | None = None  # synthetic run of the patient record (durable audit reference)

    @property
    def max_chars(self) -> int:
        return CHANNEL_MAX_CHARS.get(self.channel, 320)

    @property
    def audit_subject(self) -> dict[str, Any]:
        return {"patient_id": self.patient_id, "rule_id": self.rule_id, "care_gap_id": self.care_gap_id}

    @property
    def audit_extra(self) -> dict[str, Any]:
        return {"channel": self.channel, "language": self.language, "tone": self.tone,
                "recipient": self.recipient, "contact_consent_id": self.contact_consent_id}


def pre_consent_block(channel: str, language: str) -> str | None:
    if channel not in SUPPORTED_CHANNELS:
        return "channel_unsupported"
    if language not in SUPPORTED_OUTREACH_LANGUAGES:
        return "language_unsupported"
    return None


def deterministic_draft(facts: Mapping[str, Any], channel: str) -> str:
    if facts.get("language") == "ar":
        opening = "مرحبًا، أتواصل معك هاتفيًا من" if channel == "phone" else "مرحبًا، معك"
        return (
            f"{opening} {facts['programme']}. تُظهر سجلاتنا أن {facts['care_gap_category']}. "
            f"ندعوك إلى {facts['approved_next_step']}. لأي استفسار، يُرجى استشارة مختص رعاية صحية مرخّص."
        )
    opening = "Hello, I am calling from" if channel == "phone" else "Hello, this is"
    return (
        f"{opening} the {facts['programme']}. Our records show that {facts['care_gap_category']}. "
        f"We invite you to {facts['approved_next_step']}. For any questions, please consult a "
        "licensed healthcare professional."
    )


def gate_outreach_draft(
    *,
    preview: OutreachPreviewResult,
    patient: Mapping[str, Any],
    consents: Sequence[Mapping[str, Any]],
    rule: Mapping[str, Any],
    care_gaps: Sequence[Mapping[str, Any]],
    channel: str,
    language: str,
    tone: str,
    requested_care_gap_id: str | None,
) -> OutreachDraftGate:
    """Run the post-consent checks on an existing preview gate result (see module docstring)."""
    base = dict(patient_id=preview.synthetic_patient_id, rule_id=preview.rule_id,
                rule_version=preview.rule_version, care_gap_id=preview.care_gap_id,
                channel=channel, language=language, tone=tone, run_id=patient.get("run_id"))

    def blocked(reason: str, **kw: Any) -> OutreachDraftGate:
        return OutreachDraftGate(allowed=False, blocked_reason=reason, **{**base, **kw})

    if not preview.allowed:
        return blocked(str(preview.blocked_reason))
    if requested_care_gap_id is not None and requested_care_gap_id != preview.care_gap_id:
        return blocked("care_gap_not_open", care_gap_id=requested_care_gap_id)

    consent = resolve_applicable_contact_consent(consents, rule_id=preview.rule_id, pathway=str(rule["pathway"]))
    if consent is None or consent.get("state") != "granted":  # fail closed; the preview gate checked too
        return blocked("contact_consent_absent")
    if consent.get("guardian_id") or consent.get("applies_to") == "child_by_guardian":
        return blocked("guardian_contact_not_supported")
    if patient.get("preferred_channel") != channel:
        return blocked("channel_not_permitted")
    if not patient.get(_CHANNEL_CONTACT_FIELD[channel]):
        return blocked("contact_details_missing_for_channel")

    gap = next(g for g in care_gaps if g.get("care_gap_id") == preview.care_gap_id)
    step = recommended_pathway(gap, rule)
    pathway = str(rule["pathway"])
    arabic = language == "ar"
    category = (_GAP_CATEGORY_TEXT_AR if arabic else _GAP_CATEGORY_TEXT).get((pathway, str(gap.get("gap_type"))))
    step_text = (_NEXT_STEP_TEXT_AR if arabic else _NEXT_STEP_TEXT).get(step.get("next_step") or "")
    if step["status"] != "documented_next_step" or category is None or step_text is None:
        return blocked("no_supported_next_step", next_step=step)

    facts = {
        "programme": (PROGRAMME_NAMES_AR if arabic else PROGRAMME_NAMES)[pathway],
        "care_gap_category": category,
        "approved_next_step": step_text,
        "channel": channel,
        "language": language,
        "tone": tone,
    }
    return OutreachDraftGate(
        allowed=True, blocked_reason=None, **base, recipient="patient",
        contact_consent_id=str(consent.get("consent_id")), next_step=step, facts=facts,
        deterministic_body=deterministic_draft(facts, channel),
    )
