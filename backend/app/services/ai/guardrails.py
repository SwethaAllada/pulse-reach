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
    invented = _numbers(text) - allowed_numbers(facts)
    if invented:
        out.append("invented_number")
    for needle in must_contain:
        if needle not in text:
            out.append(f"missing:{needle}")
    return out
