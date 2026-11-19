"""Versioned prompt templates. Bump the version whenever a template's wording changes.

The model only ever receives facts already computed deterministically by the backend (rule
evaluation results, approved reason descriptions, aggregate counts) and is asked to restate
them. It is never asked to decide eligibility, status, risk or clinical content.
"""

from __future__ import annotations

import json
from typing import Any

EXPLANATION_PROMPT_VERSION = "explanation-v1"
OUTREACH_PROMPT_VERSION = "outreach-v1"
POPULATION_PROMPT_VERSION = "population-v1"

PROMPT_VERSIONS = {
    "explanation": EXPLANATION_PROMPT_VERSION,
    "outreach_draft": OUTREACH_PROMPT_VERSION,
    "population_insight": POPULATION_PROMPT_VERSION,
}

_COMMON_RULES = (
    "Use ONLY the facts in the JSON below. Do not diagnose. Do not estimate risk, likelihood or "
    "probability. Do not add clinical facts, thresholds, numbers, dates, tests or recommendations "
    "that are not in the facts. Do not contradict or change any status in the facts. All records "
    "are synthetic. Reply with plain text only, no lists, no markdown."
)

EXPLANATION_SYSTEM = (
    "You explain a deterministic, rule-based preventive-care evaluation to a care coordinator. "
    + _COMMON_RULES
    + " Always name the rule id exactly as given. If the evaluation_status is unknown, "
    "insufficient_information or requires_clinical_review, state that no automated conclusion "
    "is made. Write 2 to 4 sentences."
)

OUTREACH_SYSTEM = (
    "You rewrite an approved, consent-checked outreach template into a short, polite message "
    "inviting a person to contact their preventive-care provider. "
    + _COMMON_RULES
    + " Do not mention any condition, result or test by name beyond the programme name given. "
    "Do not promise an appointment. Keep the advice to consult a licensed healthcare "
    "professional. Do not include names, phone numbers, e-mails or links. "
    "Maximum {max_chars} characters."
)

POPULATION_SYSTEM = (
    "You summarise aggregate counts for preventive-programme managers. "
    + _COMMON_RULES
    + " Use only the numbers that appear in the facts, unchanged; do not compute new numbers, "
    "percentages or trends; do not speculate about causes. Mention that the data are synthetic. "
    "Write 3 to 5 sentences."
)


def facts_json(facts: dict[str, Any]) -> str:
    return "FACTS:\n" + json.dumps(facts, sort_keys=True, default=str, ensure_ascii=False)
