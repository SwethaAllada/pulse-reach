"""Structured, immutable rule objects returned by the loader."""

from dataclasses import dataclass, field
from typing import Any, Dict, Iterable, List, Mapping, Optional, Tuple

from .errors import NonAuthoritativeRuleError

ALLOWED_VERIFICATION_STATUSES = ("verified", "reported", "unresolved")

EVALUATION_STATUSES = (
    "eligible",
    "not_eligible",
    "due",
    "upcoming",
    "overdue",
    "completed",
    "unknown",
    "insufficient_information",
    "requires_clinical_review",
)

# Mandatory metadata on every rule (section 6 of the Phase 2 brief).
REQUIRED_RULE_METADATA = (
    "rule_id",
    "pathway",
    "rule_version",
    "source_name",
    "source_version",
    "source_reference",
    "verification_status",
    "effective_date",
    "last_reviewed",
    "description",
)

OPTIONAL_RULE_KEYS = (
    "rule_type",
    "effective_date_note",
    "requires_clinical_review",
    "open_question_ids",
    "history",
    "notes",
    "spec",
)

# spec keys that hold lists of assessment items (visit rules).
ITEM_LIST_KEYS = ("preventive_assessments", "developmental_assessments", "follow_up_requirements")


def _non_authoritative_reasons(status: str, requires_review: bool) -> List[str]:
    reasons = []
    if status != "verified":
        reasons.append(f"verification_status is '{status}' (only 'verified' may drive decisions)")
    if requires_review:
        reasons.append("it is flagged requires_clinical_review")
    return reasons


@dataclass(frozen=True)
class AgeRange:
    """Age band exactly as printed; boundary semantics are unresolved (OQ-COMMON-AGE-CALC)."""

    min_years: Optional[int]
    max_years: Optional[int]
    as_printed: str


@dataclass(frozen=True)
class Frequency:
    type: str  # "recurring" | "once_per_lifetime"
    interval_value: Optional[int]
    interval_unit: Optional[str]
    as_printed: str

    @property
    def is_one_time(self) -> bool:
        return self.type == "once_per_lifetime"


@dataclass(frozen=True)
class RuleVersionRecord:
    """A superseded version of a rule, preserved for history."""

    rule_version: str
    source_reference: str
    verification_status: str
    last_reviewed: str
    change_summary: str


@dataclass(frozen=True)
class RuleItem:
    """An assessment or follow-up item inside a rule (e.g. one test at one visit)."""

    category: str  # which spec list it came from
    code: str
    description: str
    source_reference: str
    verification_status: str
    condition: Optional[str] = None
    components: Tuple[str, ...] = ()
    rule_refs: Tuple[str, ...] = ()
    open_question_ids: Tuple[str, ...] = ()
    notes: Optional[str] = None

    @property
    def is_authoritative(self) -> bool:
        return self.verification_status == "verified"

    def require_authoritative(self) -> "RuleItem":
        if not self.is_authoritative:
            raise NonAuthoritativeRuleError(
                f"Item '{self.code}'", _non_authoritative_reasons(self.verification_status, False)
            )
        return self


@dataclass(frozen=True)
class Rule:
    rule_id: str
    pathway: str
    rule_version: str
    source_name: str
    source_version: str
    source_reference: str
    verification_status: str
    effective_date: Optional[str]
    last_reviewed: str
    description: str
    rule_type: Optional[str] = None
    effective_date_note: Optional[str] = None
    requires_clinical_review: bool = False
    open_question_ids: Tuple[str, ...] = ()
    history: Tuple[RuleVersionRecord, ...] = ()
    notes: Optional[str] = None
    spec: Mapping[str, Any] = field(default_factory=dict)
    items: Tuple[RuleItem, ...] = ()

    # -- authority -----------------------------------------------------------
    # Authority is always derived, never configured: only a verified rule that
    # is not flagged for clinical review may drive an authoritative decision.
    @property
    def non_authoritative_reasons(self) -> List[str]:
        return _non_authoritative_reasons(self.verification_status, self.requires_clinical_review)

    @property
    def is_authoritative(self) -> bool:
        return not self.non_authoritative_reasons

    def require_authoritative(self) -> "Rule":
        """Return self, or raise NonAuthoritativeRuleError. Call before using a rule to decide."""
        if not self.is_authoritative:
            raise NonAuthoritativeRuleError(f"Rule '{self.rule_id}'", self.non_authoritative_reasons)
        return self

    # -- items ---------------------------------------------------------------
    def items_in(self, category: str) -> Tuple[RuleItem, ...]:
        return tuple(i for i in self.items if i.category == category)

    @property
    def authoritative_items(self) -> Tuple[RuleItem, ...]:
        return tuple(i for i in self.items if i.is_authoritative)

    @property
    def unresolved_items(self) -> Tuple[RuleItem, ...]:
        return tuple(i for i in self.items if not i.is_authoritative)

    # -- typed views over spec (screening packages) --------------------------
    @property
    def age_range(self) -> AgeRange:
        age = self.spec.get("eligibility", {}).get("age")
        if not age:
            raise KeyError(f"Rule '{self.rule_id}' has no eligibility.age in its spec")
        return AgeRange(age.get("min_years"), age.get("max_years"), age.get("as_printed", ""))

    @property
    def sexes(self) -> Tuple[str, ...]:
        return tuple(self.spec.get("eligibility", {}).get("sex", ()))

    @property
    def frequency(self) -> Frequency:
        freq = self.spec.get("frequency")
        if not freq:
            raise KeyError(f"Rule '{self.rule_id}' has no frequency in its spec")
        interval = freq.get("interval") or {}
        return Frequency(freq["type"], interval.get("value"), interval.get("unit"), freq.get("as_printed", ""))


@dataclass(frozen=True)
class OpenQuestion:
    id: str
    category: str
    status: str
    title: str
    detail: str
    affects: Tuple[str, ...] = ()
    resolve_via: Optional[str] = None


@dataclass(frozen=True)
class Source:
    source_name: str
    source_version: str
    document_ref: str
    publication_date: Optional[str]
    effective_date: Optional[str]
    effective_date_note: Optional[str]
    url: Optional[str]


@dataclass(frozen=True)
class RuleBundle:
    """Everything loaded from a rules directory."""

    rules: Tuple[Rule, ...]
    open_questions: Mapping[str, OpenQuestion]
    sources: Tuple[Source, ...]
    evaluation_statuses: Tuple[str, ...]
    status_definitions: Mapping[str, Any]
    config_versions: Mapping[str, str]

    def get(self, rule_id: str) -> Rule:
        for rule in self.rules:
            if rule.rule_id == rule_id:
                return rule
        raise KeyError(f"Unknown rule_id '{rule_id}'")

    def by_pathway(self, pathway: str) -> Tuple[Rule, ...]:
        return tuple(r for r in self.rules if r.pathway == pathway)

    def by_type(self, rule_type: str, pathway: Optional[str] = None) -> Tuple[Rule, ...]:
        return tuple(
            r for r in self.rules if r.rule_type == rule_type and (pathway is None or r.pathway == pathway)
        )

    def authoritative_rules(self, pathway: Optional[str] = None) -> Tuple[Rule, ...]:
        return tuple(r for r in self.rules if r.is_authoritative and (pathway is None or r.pathway == pathway))

    def require_authoritative(self, rule_id: str) -> Rule:
        return self.get(rule_id).require_authoritative()

    def counts_by_verification_status(self, pathway: Optional[str] = None) -> Dict[str, int]:
        counts = {s: 0 for s in ALLOWED_VERIFICATION_STATUSES}
        for rule in self.rules:
            if pathway is None or rule.pathway == pathway:
                counts[rule.verification_status] += 1
        return counts

    def rules_requiring_clinical_review(self, pathway: Optional[str] = None) -> Tuple[Rule, ...]:
        return tuple(r for r in self.rules if r.requires_clinical_review and (pathway is None or r.pathway == pathway))
