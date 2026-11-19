"""Versioned prompt templates. Bump the version whenever a template's wording changes.

The model only ever receives facts already computed deterministically by the backend (rule
evaluation results, approved reason descriptions, aggregate counts) and is asked to restate
them. It is never asked to decide eligibility, status, risk or clinical content.
"""

from __future__ import annotations

import json
from typing import Any

EXPLANATION_PROMPT_VERSION = "explanation-v2"
OUTREACH_PROMPT_VERSION = "outreach-v2"
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
    + " Always name the rule id exactly as given. In this order, explain: why the person was "
    "identified (evaluation_status, care_gaps, review_origin), the documented evidence, what information is missing "
    "or conflicting, what the rule means (rule_description), and the documented next step. "
    "Refer to the screening by its rule id, not by any disease name. Describe missing or "
    "unavailable history as unknown: never as completed, due or overdue. If "
    "documented_next_step is null, say that no next step is documented. If the "
    "evaluation_status is unknown, insufficient_information or requires_clinical_review, state "
    "that no automated conclusion is made. Write 3 to 6 sentences."
)

OUTREACH_SYSTEM = (
    "You write a short, clear, respectful outreach message from a preventive-care programme to a "
    "person whose contact consent has already been checked. "
    + _COMMON_RULES
    + " Name the programme, give the reason for contact using care_gap_category, and invite the "
    "person to take approved_next_step, and nothing else. Tone '{tone}': supportive means warm "
    "and encouraging; neutral means plain and factual. Do not diagnose or mention any condition, "
    "result, test or risk. Do not say the screening is required, mandatory, due, overdue or "
    "completed, or that the person is eligible. Do not use fear, urgency, pressure or deadlines. "
    "Do not invent appointments, dates, times, facilities, locations, costs, phone numbers, names "
    "or links. Always keep the advice to consult a licensed healthcare professional. Write in the "
    "language with code '{language}'. {channel_format} Maximum {max_chars} characters. Reply "
    "with the message text only."
)
OUTREACH_CHANNEL_FORMAT = {
    "sms": "Format: one short paragraph with no line breaks, suitable for an SMS.",
    "app": "Format: one short paragraph with no line breaks, for an in-app notification.",
    "email": "Format: an e-mail body with a greeting, one or two short paragraphs and a sign-off "
    "from the programme; no subject line.",
    "phone": "Format: one paragraph a care coordinator can read aloud on a phone call.",
}

POPULATION_SYSTEM = (
    "You summarise aggregate counts for preventive-programme managers. "
    + _COMMON_RULES
    + " Use only the numbers that appear in the facts, unchanged; do not compute new numbers, "
    "percentages or trends; do not speculate about causes. Mention that the data are synthetic. "
    "Write 3 to 5 sentences."
)


def facts_json(facts: dict[str, Any]) -> str:
    return "FACTS:\n" + json.dumps(facts, sort_keys=True, default=str, ensure_ascii=False)
