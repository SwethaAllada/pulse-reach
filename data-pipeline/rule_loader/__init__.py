"""Loader and validator for PulseReach versioned clinical rule configuration.

This package only loads, validates and exposes rules. It does not evaluate
patient eligibility (a later phase) and has no dependency on FastAPI or
PostgreSQL.
"""

from .errors import NonAuthoritativeRuleError, RuleConfigError, ValidationIssue
from .loader import default_rules_dir, load_rules
from .models import (
    ALLOWED_VERIFICATION_STATUSES,
    EVALUATION_STATUSES,
    REQUIRED_RULE_METADATA,
    AgeRange,
    Frequency,
    OpenQuestion,
    Rule,
    RuleBundle,
    RuleItem,
    RuleVersionRecord,
    Source,
)

__all__ = [
    "ALLOWED_VERIFICATION_STATUSES",
    "EVALUATION_STATUSES",
    "REQUIRED_RULE_METADATA",
    "AgeRange",
    "Frequency",
    "NonAuthoritativeRuleError",
    "OpenQuestion",
    "Rule",
    "RuleBundle",
    "RuleConfigError",
    "RuleItem",
    "RuleVersionRecord",
    "Source",
    "ValidationIssue",
    "default_rules_dir",
    "load_rules",
]
