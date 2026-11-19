"""Output validation for model-generated text. Any violation means the output is discarded and
the deterministic template is used instead."""

from __future__ import annotations

import json
import re
from collections.abc import Iterable
from typing import Any

_EMIRATES_ID_RE = re.compile(r"\b784-?\d{4}-?\d{7}-?\d\b")
_PHONE_RE = re.compile(r"\+\d{3}[\s-]?\d|\b\d{2,3}[\s-]\d{3}[\s-]\d{4}\b|\b\d{9,}\b")
_EMAIL_RE = re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b")
_URL_RE = re.compile(r"https?://|www\.", re.IGNORECASE)
_NUMBER_RE = re.compile(r"\d+(?:[.,]\d+)?")
_CLINICAL_CLAIM_RE = re.compile(
    r"\b(diagnos\w*|you have|has (?:cancer|diabetes|hypertension)|cancer|tumou?r|malignan\w*|"
    r"prescri\w*|dosage|medication|treatment plan|cure)\b",
    re.IGNORECASE,
)
_RISK_RE = re.compile(
    r"\b(risk|likel(?:y|ihood)|probabilit\w*|chance|odds|predict\w*|%|per ?cent)\b", re.IGNORECASE
)
_OVERDUE_RE = re.compile(r"\boverdue\b", re.IGNORECASE)
_APPROVAL_RE = re.compile(r"\b(clinically (?:approved|validated)|authoritative recommendation)\b", re.IGNORECASE)
# Positive status assertions; negated phrasing ("has not been completed", "is not due") passes.
_COMPLETED_RE = re.compile(
    r"(?<!not )(?<!never )\b(?:has|have|had|been|was|were|is|are)\s+(?:already\s+)?"
    r"(?:completed|up[ -]to[ -]date)\b|(?<!not )\bup[ -]to[ -]date\b",
    re.IGNORECASE,
)
_DUE_RE = re.compile(r"(?<!not )\b(?:is|are|now|currently)\s+due\b", re.IGNORECASE)
_ELIGIBLE_RE = re.compile(
    r"\b(?:is|are|remains|considered|deemed)\s+eligible\b|\bmeets?\s+(?:all\s+|the\s+)?(?:\w+\s+)?"
    r"(?:eligibility|criteria)\b",
    re.IGNORECASE,
)


def _numbers(text: str) -> set[str]:
    return {n.replace(",", ".") for n in _NUMBER_RE.findall(text)}


def allowed_numbers(facts: Any) -> set[str]:
    return _numbers(json.dumps(facts, default=str))


def validate_output(
    text: str | None,
    *,
    facts: Any,
    max_chars: int,
    must_contain: Iterable[str] = (),
    allow_risk_words: bool = False,
    allow_overdue: bool = False,
    allow_approval_claims: bool = False,
    allow_completed: bool = True,
    allow_due: bool = True,
    allow_eligibility: bool = True,
) -> list[str]:
    """Return the list of violations (empty = acceptable)."""
    if not text or not text.strip():
        return ["empty_output"]
    out: list[str] = []
    if len(text) > max_chars:
        out.append("too_long")
    if _EMIRATES_ID_RE.search(text) or _EMAIL_RE.search(text) or _PHONE_RE.search(text):
        out.append("personal_identifier")
    if _URL_RE.search(text):
        out.append("link")
    if _CLINICAL_CLAIM_RE.search(text):
        out.append("clinical_claim")
    if not allow_risk_words and _RISK_RE.search(text):
        out.append("risk_or_probability")
    if not allow_overdue and _OVERDUE_RE.search(text):
        out.append("overdue_claim")
    if not allow_approval_claims and _APPROVAL_RE.search(text):
        out.append("approval_claim")
    if not allow_completed and _COMPLETED_RE.search(text):
        out.append("completed_claim")
    if not allow_due and _DUE_RE.search(text):
        out.append("due_claim")
    if not allow_eligibility and _ELIGIBLE_RE.search(text):
        out.append("eligibility_claim")
    invented = _numbers(text) - allowed_numbers(facts)
    if invented:
        out.append("invented_number")
    for needle in must_contain:
        if needle not in text:
            out.append(f"missing:{needle}")
    return out


# --- patient-facing outreach --------------------------------------------------------------

_RECORD_ID_RE = re.compile(r"\bSYNTH-[A-Z]+-\d+\b")
_COERCIVE_RE = re.compile(
    r"\b(must|required|requirement|mandatory|obligat\w*|have to|has to|deadline|urgent\w*|"
    r"immediately|as soon as possible|asap|last chance|final (?:notice|reminder)|penalt\w*|"
    r"fined?|consequences?|failure to|do not ignore)\b",
    re.IGNORECASE,
)
_FEAR_RE = re.compile(
    r"\b(danger\w*|serious(?:ly)?|life[- ]threatening|die|dying|death|deadly|fatal|worr\w*|"
    r"afraid|fear\w*|alarming|scar(?:y|ed)|harm\w*)\b",
    re.IGNORECASE,
)
_LOGISTICS_RE = re.compile(
    r"\b(appointments?|booked|booking|reserved|slot|clinic|hospital|health cent(?:re|er)|"
    r"cent(?:re|er)|facility|branch|address|located|location|free of charge|at no cost|"
    r"no charge|costs?|fees?|price|paid|payment|aed|dirhams?|insurance|covered|today|tomorrow|"
    r"tonight|this week|next week|weekend|monday|tuesday|wednesday|thursday|friday|saturday|"
    r"sunday|january|february|march|april|june|july|august|september|october|november|"
    r"december|a\.m\.|p\.m\.|o'clock|call us on|reply)\b",
    re.IGNORECASE,
)
_MARKDOWN_RE = re.compile(r"(^\s*[-*#>]|\*\*|__|`)", re.MULTILINE)
_NON_LATIN_LETTER_RE = re.compile(r"[\u0600-\u06FF\u0750-\u077F\u0400-\u04FF\u4E00-\u9FFF]")
_SINGLE_PARAGRAPH_CHANNELS = frozenset({"sms", "app", "phone"})


def validate_outreach_output(
    text: str | None, *, facts: Any, channel: str, language: str, max_chars: int
) -> list[str]:
    """Shared checks plus outreach rules: no status/eligibility claims, record ids, coercion,
    fear, invented logistics (appointments, facilities, costs, dates), channel format, language."""
    out = validate_output(
        text, facts=facts, max_chars=max_chars, must_contain=("professional",),
        allow_completed=False, allow_due=False, allow_eligibility=False,
    )
    if not text or not text.strip():
        return out
    checks = (
        (_RECORD_ID_RE, "personal_identifier"),
        (_COERCIVE_RE, "coercive_or_requirement"),
        (_FEAR_RE, "fear_language"),
        (_LOGISTICS_RE, "invented_logistics"),
        (_MARKDOWN_RE, "format_markdown"),
    )
    out += [v for rx, v in checks if rx.search(text) and v not in out]
    if channel in _SINGLE_PARAGRAPH_CHANNELS and "\n" in text.strip():
        out.append("format_line_breaks")
    if language == "en" and _NON_LATIN_LETTER_RE.search(text):
        out.append("language_mismatch")
    return out
