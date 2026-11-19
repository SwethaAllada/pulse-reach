"""AI assistance over deterministic backend results.

The model restates facts the backend has already decided; it never decides them:
- explanations are grounded in the engine's evaluation (status, approved reason descriptions,
  rule citation) - status, reasons, citation and warnings stay the deterministic ones;
- outreach drafts are only produced after the consent/authority gate allowed the preview and are
  always simulated (never sent);
- population insights restate aggregate counts computed by the backend.

Every output is validated (`guardrails.validate_output`); disabled, misconfigured, failing or
rejected generations fall back to the deterministic template, so AI never breaks core features.
"""

from __future__ import annotations

import logging
import time
from collections.abc import Callable
from dataclasses import dataclass, replace
from functools import lru_cache
from typing import Any

from app.core.config import Settings, settings
from app.services.ai.audit import AIAuditLog, sha256
from app.services.ai.guardrails import validate_output
from app.services.ai.prompts import (
    EXPLANATION_PROMPT_VERSION,
    EXPLANATION_SYSTEM,
    OUTREACH_PROMPT_VERSION,
    OUTREACH_SYSTEM,
    POPULATION_PROMPT_VERSION,
    POPULATION_SYSTEM,
    PROMPT_VERSIONS,
    facts_json,
)
from app.services.ai.provider import LLMProvider, LLMProviderError, build_provider
from app.services.explanation import (
    REASON_DESCRIPTIONS,
    BoundedExplanationInput,
    ExplanationResult,
    ExplanationService,
    OutreachPreviewResult,
)

logger = logging.getLogger(__name__)

LLM_GROUNDED = "llm_grounded"
DETERMINISTIC = "deterministic_fallback"

_OUTREACH_MAX_CHARS = {"sms": 320, "app": 400, "email": 700, "phone": 500}
_SIMULATED_BANNER = "[SIMULATED OUTREACH PREVIEW — {channel} ({language})] "


@dataclass(frozen=True)
class AIGenerationMeta:
    feature: str
    generation_mode: str
    prompt_version: str
    provider: str | None
    model: str | None
    fallback_reason: str | None
    violations: tuple[str, ...]
    audit_id: str


@dataclass(frozen=True)
class OutreachDraft:
    message: str
    meta: AIGenerationMeta


@dataclass(frozen=True)
class PopulationInsight:
    facts: dict[str, Any]
    summary_text: str
    meta: AIGenerationMeta


class AIService:
    def __init__(
        self,
        provider: LLMProvider | None,
        *,
        provider_status: str = "disabled",
        max_output_tokens: int = 400,
        audit: AIAuditLog | None = None,
    ) -> None:
        self._provider = provider
        self._provider_status = provider_status
        self._max_tokens = max_output_tokens
        self.audit = audit or AIAuditLog()
        self._explanations = ExplanationService(llm_provider=None)

    def status(self) -> dict[str, Any]:
        return {
            "llm_enabled": self._provider is not None,
            "status": self._provider_status,
            "provider": getattr(self._provider, "name", None),
            "model": getattr(self._provider, "model", None),
            "prompt_versions": dict(PROMPT_VERSIONS),
        }

    # -- core -------------------------------------------------------------------------------

    def _generate(
        self,
        *,
        feature: str,
        prompt_version: str,
        system: str,
        facts: dict[str, Any],
        subject: dict[str, Any],
        validate: Callable[[str], list[str]],
    ) -> tuple[str | None, AIGenerationMeta]:
        user = facts_json(facts)
        text: str | None = None
        violations: list[str] = []
        latency: float | None = None
        model = getattr(self._provider, "model", None)
        if self._provider is None:
            reason: str | None = "llm_disabled" if self._provider_status == "disabled" else "llm_misconfigured"
        else:
            start = time.perf_counter()
            try:
                completion = self._provider.complete(system=system, user=user, max_tokens=self._max_tokens)
                text, model = completion.text.strip(), completion.model
                violations = validate(text)
                reason = "output_rejected" if violations else None
            except LLMProviderError as exc:
                reason = "provider_error"
                logger.warning("LLM provider error for %s: %s", feature, exc)
            except Exception:  # never let an adapter bug break a core endpoint
                reason = "provider_error"
                logger.exception("Unexpected LLM provider failure for %s", feature)
            latency = round((time.perf_counter() - start) * 1000, 2)
        accepted = text if reason is None else None
        rec = self.audit.record(
            feature=feature,
            subject=subject,
            prompt_version=prompt_version,
            provider=getattr(self._provider, "name", None),
            model=model,
            generation_mode=LLM_GROUNDED if accepted else DETERMINISTIC,
            fallback_reason=reason,
            violations=tuple(violations),
            input_sha256=sha256(system + "\n" + user),
            output_sha256=sha256(text),
            latency_ms=latency,
        )
        meta = AIGenerationMeta(
            feature=feature,
            generation_mode=rec.generation_mode,
            prompt_version=prompt_version,
            provider=rec.provider,
            model=model,
            fallback_reason=reason,
            violations=tuple(violations),
            audit_id=rec.audit_id,
        )
        return accepted, meta

    # -- explanation ------------------------------------------------------------------------

    def explain(self, inp: BoundedExplanationInput) -> tuple[ExplanationResult, AIGenerationMeta]:
        det = self._explanations.explain_evaluation(inp)  # privacy-validated deterministic result
        facts = {
            "rule_id": inp.rule_id,
            "rule_version": inp.rule_version,
            "standard": inp.standard_name,
            "source_reference": inp.source_reference,
            "rule_is_authoritative": inp.is_authoritative,
            "verification_status": inp.verification_status,
            "evaluation_status": inp.evaluation_status,
            "history_status": inp.history_status,
            "reasons": [REASON_DESCRIPTIONS.get(rc, rc) for rc in inp.reason_codes],
            "open_question_ids": list(inp.open_question_ids),
            "next_due_date": inp.next_due_date,
        }
        text, meta = self._generate(
            feature="explanation",
            prompt_version=EXPLANATION_PROMPT_VERSION,
            system=EXPLANATION_SYSTEM,
            facts=facts,
            subject={"patient_id": inp.synthetic_patient_id, "rule_id": inp.rule_id},
            validate=lambda t: validate_output(
                t,
                facts=facts,
                max_chars=900,
                must_contain=(inp.rule_id,),
                allow_overdue=inp.evaluation_status == "overdue",
                allow_approval_claims=False,
            ),
        )
        if text is None:
            return det, meta
        return replace(det, generation_mode=LLM_GROUNDED, summary_text=text), meta

    # -- outreach ---------------------------------------------------------------------------

    def draft_outreach(
        self, preview: OutreachPreviewResult, *, channel: str, language: str, programme: str
    ) -> OutreachDraft | None:
        """Draft a simulated message for an *allowed* preview; None when the gate blocked it."""
        if not preview.allowed or not preview.preview_message:
            return None
        banner = _SIMULATED_BANNER.format(channel=channel.upper(), language=language)
        max_chars = _OUTREACH_MAX_CHARS.get(channel, 320)
        template_body = preview.preview_message.removeprefix(banner).strip()
        facts = {
            "channel": channel,
            "language": language,
            "programme": programme,
            "approved_template": template_body,
        }
        text, meta = self._generate(
            feature="outreach_draft",
            prompt_version=OUTREACH_PROMPT_VERSION,
            system=OUTREACH_SYSTEM.format(max_chars=max_chars),
            facts=facts,
            subject={"patient_id": preview.synthetic_patient_id, "rule_id": preview.rule_id,
                     "care_gap_id": preview.care_gap_id},
            validate=lambda t: validate_output(
                t, facts=facts, max_chars=max_chars,
                must_contain=() if "professional" not in template_body else ("professional",),
            ),
        )
        return OutreachDraft(message=banner + (text or template_body), meta=meta)

    # -- population ------------------------------------------------------------------------

    def population_insight(self, facts: dict[str, Any]) -> PopulationInsight:
        deterministic = _deterministic_population_summary(facts)
        text, meta = self._generate(
            feature="population_insight",
            prompt_version=POPULATION_PROMPT_VERSION,
            system=POPULATION_SYSTEM,
            facts=facts,
            subject={"run_id": facts.get("run_id"), "evaluation_run_id": facts.get("evaluation_run_id")},
            validate=lambda t: validate_output(t, facts=facts, max_chars=1200, must_contain=("synthetic",)),
        )
        return PopulationInsight(facts=facts, summary_text=text or deterministic, meta=meta)


def _deterministic_population_summary(f: dict[str, Any]) -> str:
    parts = [
        f"This synthetic population has {f['total_patients']} people "
        f"({f['n_adults']} adults, {f['n_children']} children) evaluated on {f['reference_date']}.",
        f"There are {f['open_care_gaps_count']} open care gaps",
    ]
    by_pathway = f.get("open_gaps_by_pathway") or {}
    if by_pathway:
        parts[-1] += " (" + ", ".join(f"{k}: {v}" for k, v in sorted(by_pathway.items())) + ")."
    else:
        parts[-1] += "."
    by_type = f.get("open_gaps_by_type") or {}
    if by_type:
        parts.append("By gap type: " + ", ".join(f"{k}: {v}" for k, v in sorted(by_type.items())) + ".")
    parts.append(
        f"{f['unknown_history_patients_count']} people have unknown screening history and "
        f"{f['review_flagged_patients_count']} have at least one result requiring clinical review."
    )
    return " ".join(parts)


@lru_cache(maxsize=1)
def get_ai_service() -> AIService:
    return build_ai_service(settings)


def build_ai_service(cfg: Settings) -> AIService:
    provider, status = build_provider(cfg)
    if cfg.llm_enabled and provider is None:
        logger.warning("LLM_ENABLED is true but the provider is %s; using deterministic templates", status)
    return AIService(provider, provider_status=status, max_output_tokens=cfg.llm_max_output_tokens)
