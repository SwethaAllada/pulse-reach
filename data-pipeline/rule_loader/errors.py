"""Exceptions raised by the rule loader."""

from dataclasses import dataclass
from typing import List, Sequence


@dataclass(frozen=True)
class ValidationIssue:
    """One problem found in the rule configuration."""

    location: str  # e.g. "ifhas/ifhas_rules.yaml: rule 'IFHAS-PKG-X'"
    message: str

    def __str__(self) -> str:
        return f"{self.location}: {self.message}"


class RuleConfigError(Exception):
    """Raised when configuration is invalid. Carries every issue found."""

    def __init__(self, issues: Sequence[ValidationIssue]):
        self.issues: List[ValidationIssue] = list(issues)
        lines = [f"Rule configuration is invalid ({len(self.issues)} problem(s)):"]
        lines += [f"  {i + 1}. {issue}" for i, issue in enumerate(self.issues)]
        super().__init__("\n".join(lines))


class NonAuthoritativeRuleError(Exception):
    """Raised when a rule or item that is not authoritative is used for a decision."""

    def __init__(self, subject: str, reasons: Sequence[str]):
        self.subject = subject
        self.reasons = list(reasons)
        super().__init__(
            f"{subject} cannot drive an authoritative clinical decision: "
            + "; ".join(self.reasons)
            + ". Route to clinical review instead."
        )
