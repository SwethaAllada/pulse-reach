"""Schemas for the patient portal (`/api/v1/portal/*`) and staff engagement endpoints.

Patient-facing responses carry machine values (ids, enum codes, ISO dates) plus localized
presentation fields (`*_label`, `*_display`, `title`, `description`) and `locale` / `direction`.
They never include internal staff notes, reviewer identities, reason codes, guard ids, rule
internals or evaluation input snapshots.
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, model_validator

from app.schemas.identity import Locale

Direction = Literal["ltr", "rtl"]
FreeText = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=1000)]
TimeOfDay = Literal["morning", "afternoon", "evening"]
PatientResponse = Literal["will_book", "already_done", "need_help", "not_interested", "question"]


class _In(BaseModel):
    model_config = ConfigDict(extra="forbid")


class LocalizedOut(BaseModel):
    locale: Locale
    direction: Direction


class PortalLinkIn(_In):
    invitation_code: Annotated[str, StringConstraints(strip_whitespace=True, min_length=4, max_length=32)]
    date_of_birth: date


class PortalLinkOut(LocalizedOut):
    linked: bool
    patient_id: str
    message: str


class PortalProfileOut(LocalizedOut):
    patient_id: str
    given_name: str
    family_name: str
    date_of_birth: date | None
    date_of_birth_display: str | None
    sex: str | None
    preferred_language: str
    preferred_channel: str
    region_id: int
    is_synthetic: bool = True
    open_recommendations: int
    upcoming_appointments: int
    open_follow_ups: int
    awaiting_your_reply: int
    open_requests: int


class HistoryItemOut(BaseModel):
    programme: str
    programme_label: str
    status: str
    status_label: str


class ScreeningItemOut(BaseModel):
    kind: Literal["screening", "well_child_visit"]
    programme: str
    programme_label: str
    performed_date: date | None
    performed_date_display: str | None
    status: str
    status_label: str
    results_communicated_date: date | None = None


class HealthSummaryOut(LocalizedOut):
    patient_id: str
    history: list[HistoryItemOut]
    events: list[ScreeningItemOut]
    is_synthetic: bool = True
    disclaimer: str


class EvaluationItemPatientOut(BaseModel):
    rule_id: str
    programme: str
    programme_label: str
    status: str
    status_label: str
    next_due_date: date | None
    next_due_date_display: str | None
    evaluated_at: datetime


class PatientEvaluationHistoryOut(LocalizedOut):
    patient_id: str
    reference_date: date
    reference_date_display: str
    items: list[EvaluationItemPatientOut]
    disclaimer: str


class RecommendationOut(BaseModel):
    recommendation_id: str
    rule_id: str
    programme: str
    programme_label: str
    gap_type: str
    title: str
    description: str
    status: str
    status_label: str
    identified_date: date
    identified_date_display: str
    closed_date: date | None = None
    next_step: str | None
    next_step_text: str


class TimelineItemOut(BaseModel):
    occurred_on: date
    occurred_on_display: str
    event: str
    label: str


class RecommendationDetailOut(LocalizedOut, RecommendationOut):
    evidence: list[str]
    history: list[TimelineItemOut]
    related_follow_up_ids: list[str] = Field(default_factory=list)
    disclaimer: str


class RecommendationsOut(LocalizedOut):
    total: int
    items: list[RecommendationOut]


class RecommendationExplanationOut(LocalizedOut):
    recommendation_id: str
    title: str
    paragraphs: list[str]
    next_step_text: str
    generation_mode: Literal["deterministic_template"] = "deterministic_template"
    disclaimer: str


AssistantTopic = Literal["why", "meaning", "next_steps", "prepare_questions", "appointments", "question"]
PortalAssistantTopic = Literal["overview", "portal_help", "contact_care_team", "question"]
# answer: restates the record; emergency / clinical_question / out_of_scope: screened before any
# model call (deterministic escalation); unavailable: a free-text question the AI could not answer.
AnswerKind = Literal["answer", "emergency", "clinical_question", "out_of_scope", "unavailable"]
AssistantQuestion = Annotated[str, StringConstraints(strip_whitespace=True, min_length=2, max_length=500)]


class _AssistantIn(_In):
    """`question` is required for topic `question` and refused for every other topic. It is
    untrusted text: screened, never stored (only its length and SHA-256 are audited)."""

    question: AssistantQuestion | None = None

    @model_validator(mode="after")
    def _question_matches_topic(self):
        if (self.topic == "question") != (self.question is not None):  # type: ignore[attr-defined]
            raise ValueError("question is required for topic 'question' and not allowed otherwise")
        return self


class PatientAssistantIn(_AssistantIn):
    topic: AssistantTopic


class PortalAssistantIn(_AssistantIn):
    topic: PortalAssistantTopic


class _AssistantOut(LocalizedOut):
    topic_label: str
    answer: list[str]
    generation_mode: Literal["llm_grounded", "deterministic_fallback"]
    answer_kind: AnswerKind = "answer"
    ai_generated: bool = False
    source_note: str
    escalation: str
    disclaimer: str


class PatientAssistantOut(_AssistantOut):
    """Answer about one of the patient's own recommendations. `answer` restates portal facts
    (model text that passed the guardrails, or the deterministic template)."""

    recommendation_id: str
    topic: AssistantTopic


class PortalAssistantOut(_AssistantOut):
    """Portal-level care navigation over the patient's own overview, portal features and
    contact routes."""

    topic: PortalAssistantTopic


class PortalAppointmentOut(BaseModel):
    appointment_id: str
    appointment_type: str
    appointment_type_label: str
    scheduled_datetime: datetime
    scheduled_display: str
    status: str
    status_label: str
    recommendation_id: str | None
    can_request_change: bool


class PortalAppointmentsOut(LocalizedOut):
    total: int
    items: list[PortalAppointmentOut]


class PortalReferralOut(BaseModel):
    referral_id: str
    referral_target: str
    status: str
    status_label: str
    trigger_date: date
    trigger_date_display: str
    initiated_date: date | None
    completed_date: date | None


class PortalReferralsOut(LocalizedOut):
    total: int
    items: list[PortalReferralOut]


class AppointmentRequestIn(_In):
    recommendation_id: str | None = None
    follow_up_id: str | None = None
    preferred_dates: list[date] = Field(default_factory=list, max_length=5)
    preferred_time_of_day: TimeOfDay | None = None
    message: FreeText | None = None


class AppointmentChangeIn(_In):
    action: Literal["cancel", "reschedule"]
    preferred_dates: list[date] = Field(default_factory=list, max_length=5)
    preferred_time_of_day: TimeOfDay | None = None
    message: FreeText | None = None


class AssistanceIn(_In):
    message: FreeText
    preferred_time_of_day: TimeOfDay | None = None


class FollowUpResponseIn(_In):
    response: PatientResponse
    message: FreeText | None = None


class PatientRequestOut(BaseModel):
    request_id: str
    request_type: str
    request_type_label: str
    status: str
    status_label: str
    status_hint: str
    follow_up_id: str | None
    recommendation_id: str | None
    appointment_id: str | None
    change_action: str | None
    change_action_label: str | None
    preferred_dates: list[str]
    preferred_time_of_day: str | None
    message: str | None
    staff_response: str | None
    created_at: datetime
    created_display: str
    updated_at: datetime
    updated_display: str


class PatientRequestDetailOut(LocalizedOut, PatientRequestOut):
    confirmation: str | None = None


class PatientRequestsOut(LocalizedOut):
    total: int
    items: list[PatientRequestOut]


class TaskEventPatientOut(BaseModel):
    event_id: str
    event_type: str
    label: str
    created_at: datetime
    created_display: str
    from_status: str | None = None
    to_status: str | None = None
    response: str | None = None
    response_label: str | None = None
    message: str | None = None
    from_care_team: bool


class PortalFollowUpOut(BaseModel):
    follow_up_id: str
    recommendation_id: str | None
    status: str
    status_label: str
    status_hint: str
    message: str
    due_date: date | None
    due_date_display: str | None
    is_overdue: bool
    reported_completion_pending_verification: bool
    created_at: datetime
    updated_at: datetime
    updated_display: str


class PortalFollowUpsOut(LocalizedOut):
    total: int
    items: list[PortalFollowUpOut]


class PortalFollowUpDetailOut(LocalizedOut, PortalFollowUpOut):
    history: list[TaskEventPatientOut]
    confirmation: str | None = None


class PortalFollowUpHistoryOut(LocalizedOut):
    follow_up_id: str
    items: list[TaskEventPatientOut]


# --- staff ---------------------------------------------------------------------------------

MessageKey = Literal[
    "screening_invitation", "complete_outstanding", "referral_follow_up", "well_child_visit", "general_check_in"
]
TaskStatus = Literal["open", "awaiting_patient", "patient_responded", "in_progress", "completed", "cancelled"]
TaskPriority = Literal["routine", "high", "urgent"]
ContactChannel = Literal["phone", "sms", "email", "in_person", "portal"]
ContactOutcome = Literal["reached", "no_answer", "left_message", "wrong_contact_details", "declined"]


class TaskCreateIn(_In):
    patient_id: str
    care_gap_id: str | None = None
    assigned_to_user_id: str | None = None
    due_date: date | None = None
    message_key: MessageKey = "screening_invitation"
    priority: TaskPriority = "routine"
    patient_visible: bool = True
    staff_note: FreeText | None = None
    language: Locale | None = Field(default=None, description="Defaults to the patient's preferred language.")


class TaskUpdateIn(_In):
    status: Literal["awaiting_patient", "in_progress", "cancelled"] | None = None
    assigned_to_user_id: str | None = None
    due_date: date | None = None
    clear_due_date: bool = False
    priority: TaskPriority | None = None


class TaskNoteIn(_In):
    text: FreeText
    patient_visible: bool = False


class ContactAttemptIn(_In):
    """A contact attempt a staff member made outside PulseReach (documentation only; nothing is sent)."""

    channel: ContactChannel
    outcome: ContactOutcome
    note: FreeText | None = None


class TaskEscalateIn(_In):
    reason: FreeText | None = None


class TaskCompleteIn(_In):
    completion_follow_up_id: str | None = Field(
        default=None,
        description="Required when the task has a care gap: a `completion_documented` follow-up event on that gap.",
    )


class TaskEventOut(BaseModel):
    event_id: str
    event_type: str
    visibility: Literal["patient", "internal"]
    actor_user_id: str
    actor_role: str
    from_status: str | None
    to_status: str | None
    response_code: str | None
    message: str | None
    priority: str | None = None
    contact_channel: str | None = None
    created_at: datetime


class TaskOut(BaseModel):
    task_id: str
    organization_id: str
    patient_id: str
    care_gap_id: str | None
    rule_id: str | None
    assigned_to_user_id: str | None
    created_by_user_id: str
    status: TaskStatus
    priority: TaskPriority
    due_date: date | None
    is_overdue: bool
    is_due_soon: bool
    escalated_at: datetime | None
    language: Locale
    message_key: str
    patient_message: str
    patient_visible: bool
    staff_note: str | None
    patient_reported_completion: bool
    completion_follow_up_id: str | None
    created_at: datetime
    updated_at: datetime
    completed_at: datetime | None


class TaskDetailOut(TaskOut):
    events: list[TaskEventOut]


class PaginatedTasksOut(BaseModel):
    total: int
    limit: int
    offset: int
    items: list[TaskOut]


class TaskWorkloadOut(BaseModel):
    assigned_to_user_id: str | None = Field(description="Null groups the unassigned active tasks.")
    active: int
    overdue: int
    due_soon: int
    urgent: int


class TaskActivityOut(BaseModel):
    """Recent task event without its text (open the task for internal notes and messages)."""

    event_id: str
    task_id: str
    patient_id: str
    event_type: str
    visibility: Literal["patient", "internal"]
    actor_user_id: str
    actor_role: str
    to_status: str | None
    response_code: str | None
    priority: str | None
    contact_channel: str | None
    created_at: datetime


class TaskSummaryOut(BaseModel):
    """Counts over every task in the caller's scope matching the filters (computed server-side)."""

    as_of: date
    due_soon_days: int
    total: int
    active: int
    overdue: int
    due_soon: int
    completed: int
    cancelled: int
    unassigned_active: int
    patient_reported_completion: int
    by_status: dict[str, int]
    active_by_priority: dict[str, int]
    workload: list[TaskWorkloadOut]
    recent_events: list[TaskActivityOut]


class CareTeamMemberOut(BaseModel):
    user_id: str
    full_name: str
    role: str
    patient_access: Literal["organization", "assigned"]
    is_self: bool
    can_be_assigned: bool | None = Field(
        default=None, description="With `patient_id`: whether the member may be assigned that patient's task."
    )


class CareTeamOut(BaseModel):
    items: list[CareTeamMemberOut]


class StaffPatientRequestOut(BaseModel):
    request_id: str
    organization_id: str
    patient_id: str
    submitted_by_user_id: str
    request_type: str
    status: str
    task_id: str | None
    care_gap_id: str | None
    appointment_id: str | None
    change_action: str | None
    preferred_dates: list[str]
    preferred_time_of_day: str | None
    message: str | None
    language: Locale
    staff_response: str | None
    internal_note: str | None
    handled_by_user_id: str | None
    created_at: datetime
    updated_at: datetime


class PaginatedStaffRequestsOut(BaseModel):
    total: int
    limit: int
    offset: int
    items: list[StaffPatientRequestOut]


class RequestUpdateIn(_In):
    status: Literal["acknowledged", "scheduled", "declined", "closed"] | None = None
    staff_response: FreeText | None = Field(default=None, description="Visible to the patient.")
    internal_note: FreeText | None = Field(default=None, description="Staff only.")
    appointment_id: str | None = None
