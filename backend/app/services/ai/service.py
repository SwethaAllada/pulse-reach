"""AI assistance over deterministic backend results.

The model restates facts the backend has already decided; it never decides them:
- explanations are grounded in the engine's evaluation (status, approved reason descriptions,
  rule citation) - status, reasons, citation and warnings stay the deterministic ones;
- outreach drafts are only produced after the consent/authority gate allowed the preview and are
  always simulated (never sent);
- population insights restate aggregate counts computed by the backend;
- the patient assistant restates the portal facts of one recommendation (or, portal-wide, of the
  patient's own open recommendations and portal features) for its own patient;
- the staff copilot restates role-scoped facts the caller may already read (no free text, no notes).

Every output is validated (`guardrails.validate_output`); disabled, misconfigured, failing or
rejected generations fall back to the deterministic template, so AI never breaks core features.
"""

from __future__ import annotations

import json
import logging
import time
from collections.abc import Callable
from dataclasses import dataclass, replace
from functools import lru_cache
from typing import Any

from app.core.config import Settings, settings
from app.db.session import get_engine
from app.services.ai.audit import AIAuditLog, AIAuditRecord, PostgresAIAuditLog, sha256
from app.services.ai.guardrails import (
    parse_copilot_output,
    validate_copilot_output,
    validate_outreach_output,
    validate_output,
    validate_portal_answer,
)
from app.services.ai.prompts import (
    EXPLANATION_PROMPT_VERSION,
    EXPLANATION_SYSTEM,
    OUTREACH_CHANNEL_FORMAT,
    OUTREACH_LANGUAGE_RULES,
    OUTREACH_PROMPT_VERSION,
    OUTREACH_SYSTEM,
    PATIENT_ASSISTANT_LANGUAGE_RULES,
    PATIENT_ASSISTANT_PROMPT_VERSION,
    PATIENT_ASSISTANT_SYSTEM,
    PATIENT_ASSISTANT_TOPICS,
    POPULATION_PROMPT_VERSION,
    POPULATION_SYSTEM,
    PORTAL_ASSISTANT_PROMPT_VERSION,
    PORTAL_ASSISTANT_SYSTEM,
    PORTAL_ASSISTANT_TOPICS,
    PROMPT_VERSIONS,
    STAFF_COPILOT_LANGUAGE_RULES,
    STAFF_COPILOT_PROMPT_VERSION,
    STAFF_COPILOT_SYSTEM,
    STAFF_COPILOT_TASKS,
    facts_json,
    question_payload,
)
from app.services.ai.provider import LLMProvider, LLMProviderError, build_provider
from app.services.explanation import (
    REASON_DESCRIPTIONS,
    BoundedExplanationInput,
    ExplanationResult,
    ExplanationService,
)
from app.services.explanation.context import ExplanationContext
from app.services.outreach.drafting import OutreachDraftGate

logger = logging.getLogger(__name__)

LLM_GROUNDED = "llm_grounded"
DETERMINISTIC = "deterministic_fallback"
NOT_GENERATED = "not_generated"

_NO_ELIGIBILITY_CLAIM_STATUSES = frozenset(
    {"not_eligible", "insufficient_information", "requires_clinical_review"}
)

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
    message: str  # simulated banner + body
    meta: AIGenerationMeta
    body: str = ""  # editable text without the banner


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
        audit: AIAuditLog | PostgresAIAuditLog | None = None,
        configured_provider: str | None = None,
    ) -> None:
        self._provider = provider
        self._provider_status = provider_status
        self._configured_provider = configured_provider or getattr(provider, "name", None)
        self._max_tokens = max_output_tokens
        self.audit = audit or AIAuditLog()
        self._explanations = ExplanationService(llm_provider=None)

    def status(self) -> dict[str, Any]:
        """Configuration plus the outcome of the most recent provider call (no probe, no secrets)."""
        try:
            last = self.audit.last_provider_call()
        except Exception:  # status must never fail because the audit store is unavailable
            logger.warning("AI audit store unavailable; provider call history unknown", exc_info=True)
            last = None
        if self._provider is None:
            availability = "disabled" if self._provider_status == "disabled" else "misconfigured"
        elif last is None:
            availability = "configured_unverified"
        else:
            availability = "last_call_failed" if last.fallback_reason == "provider_error" else "last_call_succeeded"
        failed = last is not None and last.fallback_reason == "provider_error"
        return {
            "last_provider_error": (last.extra.get("provider_error_kind") or "unknown") if failed else None,
            "llm_enabled": self._provider is not None,
            "status": self._provider_status,
            "availability": availability,
            "configured_provider": self._configured_provider,
            "provider": getattr(self._provider, "name", None),
            "model": getattr(self._provider, "model", None),
            "last_provider_call_at": last.recorded_at if last else None,
            "last_provider_outcome": (last.fallback_reason or last.generation_mode) if last else None,
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
        extra: dict[str, Any] | None = None,
        fallback_text: str | None = None,
        run_id: str | None = None,
        actor: dict[str, Any] | None = None,
        user: str | None = None,
        json_mode: bool = False,
        skip_reason: str | None = None,
    ) -> tuple[str | None, AIGenerationMeta]:
        """`user` overrides the default `FACTS:` payload (e.g. facts plus a delimited, untrusted
        question); `skip_reason` (e.g. `blocked:prompt_injection`) answers without any provider call."""
        user = user if user is not None else facts_json(facts)
        text: str | None = None
        violations: list[str] = []
        latency: float | None = None
        diagnostics: dict[str, Any] = {}
        model = getattr(self._provider, "model", None)
        if skip_reason is not None:
            reason: str | None = skip_reason
        elif self._provider is None:
            reason = "llm_disabled" if self._provider_status == "disabled" else "llm_misconfigured"
        else:
            start = time.perf_counter()
            try:
                completion = self._provider.complete(
                    system=system, user=user, max_tokens=self._max_tokens, **({"json_mode": True} if json_mode else {})
                )
                text, model = completion.text.strip(), completion.model
                if getattr(completion, "attempts", 1) > 1:
                    diagnostics["provider_attempts"] = completion.attempts
                violations = validate(text)
                reason = "output_rejected" if violations else None
            except LLMProviderError as exc:
                reason = "provider_error"
                diagnostics["provider_error_kind"] = getattr(exc, "kind", "unknown")
                logger.warning("LLM provider error for %s: %s", feature, exc)
            except Exception:  # never let an adapter bug break a core endpoint
                reason = "provider_error"
                diagnostics["provider_error_kind"] = "adapter_error"
                logger.exception("Unexpected LLM provider failure for %s", feature)
            latency = round((time.perf_counter() - start) * 1000, 2)
        accepted = text if reason is None else None
        called = skip_reason is None and self._provider is not None
        rec = self.audit.record(
            feature=feature,
            subject=subject,
            prompt_version=prompt_version,
            provider=getattr(self._provider, "name", None) if called else None,
            model=model if called else None,
            generation_mode=(LLM_GROUNDED if accepted else DETERMINISTIC),
            fallback_reason=reason,
            violations=tuple(violations),
            input_sha256=sha256(system + "\n" + user) if skip_reason is None else None,
            output_sha256=sha256(text),
            latency_ms=latency,
            # `returned_sha256` fingerprints the text actually returned (model or fallback).
            extra={**(extra or {}), **(actor or {}), **diagnostics,
                   **({"returned_sha256": sha256(accepted or fallback_text)}
                      if fallback_text is not None else {})},
            run_id=run_id,
        )
        meta = AIGenerationMeta(
            feature=feature,
            generation_mode=rec.generation_mode,
            prompt_version=prompt_version,
            provider=rec.provider,
            model=rec.model,
            fallback_reason=reason,
            violations=tuple(violations),
            audit_id=rec.audit_id,
        )
        return accepted, meta

    # -- explanation ------------------------------------------------------------------------

    def explain(
        self,
        inp: BoundedExplanationInput,
        context: ExplanationContext | None = None,
        *,
        run_id: str | None = None,
        actor: dict[str, Any] | None = None,
    ) -> tuple[ExplanationResult, AIGenerationMeta]:
        """Deterministic result plus, when accepted, a validated generated summary.

        `context` (evidence, missing/conflicting information, rule meaning, next step) is built
        deterministically from stored records; only its de-identified `provider_facts()` are sent.
        """
        det = self._explanations.explain_evaluation(inp)  # privacy-validated deterministic result
        facts: dict[str, Any] = {
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
        subject: dict[str, Any] = {"patient_id": inp.synthetic_patient_id, "rule_id": inp.rule_id}
        if context is not None:
            facts.update(context.provider_facts())
            subject.update(context.references)
        status = inp.evaluation_status
        completed = status == "completed" or (context is not None and context.has_documented_completion)
        text, meta = self._generate(
            feature="explanation",
            prompt_version=EXPLANATION_PROMPT_VERSION,
            system=EXPLANATION_SYSTEM,
            facts=facts,
            subject=subject,
            run_id=run_id,
            actor=actor,
            validate=lambda t: validate_output(
                t,
                facts=facts,
                max_chars=1200,
                must_contain=(inp.rule_id,),
                allow_overdue=status == "overdue",
                allow_approval_claims=False,
                allow_completed=completed,
                allow_due=status in ("due", "overdue"),
                allow_eligibility=status not in _NO_ELIGIBILITY_CLAIM_STATUSES,
            ),
        )
        if text is None:
            return det, meta
        return replace(det, generation_mode=LLM_GROUNDED, summary_text=text), meta

    # -- outreach ---------------------------------------------------------------------------

    def draft_outreach(
        self, gate: OutreachDraftGate, *, actor: dict[str, Any] | None = None
    ) -> OutreachDraft | None:
        """Draft a simulated message for an *allowed* gate; None (and no model call) otherwise.

        The model only sees `gate.facts` (programme, gap category, approved next step, channel,
        language, tone); the fallback is the deterministic draft built from the same facts.
        """
        if not gate.allowed or not gate.deterministic_body:
            self.record_outreach_blocked(gate, actor=actor)
            return None
        max_chars = gate.max_chars
        text, meta = self._generate(
            feature="outreach_draft",
            prompt_version=OUTREACH_PROMPT_VERSION,
            system=OUTREACH_SYSTEM.format(
                max_chars=max_chars, tone=gate.tone, language=gate.language,
                language_rules=OUTREACH_LANGUAGE_RULES[gate.language],
                channel_format=OUTREACH_CHANNEL_FORMAT[gate.channel],
            ),
            facts=gate.facts,
            subject=gate.audit_subject,
            validate=lambda t: validate_outreach_output(
                t, facts=gate.facts, channel=gate.channel, language=gate.language, max_chars=max_chars
            ),
            extra=gate.audit_extra,
            fallback_text=gate.deterministic_body,
            run_id=gate.run_id,
            actor=actor,
        )
        body = text or gate.deterministic_body
        banner = _SIMULATED_BANNER.format(channel=gate.channel.upper(), language=gate.language)
        return OutreachDraft(message=banner + body, meta=meta, body=body)

    def record_outreach_blocked(
        self, gate: OutreachDraftGate, *, actor: dict[str, Any] | None = None
    ) -> AIAuditRecord:
        """Audit a draft request refused before generation (the provider is never called)."""
        return self.audit.record(
            feature="outreach_draft", subject=gate.audit_subject, prompt_version=OUTREACH_PROMPT_VERSION,
            provider=None, model=None, generation_mode=NOT_GENERATED,
            fallback_reason=f"blocked:{gate.blocked_reason}", violations=(), input_sha256=None,
            output_sha256=None, latency_ms=None, extra={**gate.audit_extra, **(actor or {})},
            run_id=gate.run_id,
        )

    def record_outreach_review(
        self,
        *,
        subject: dict[str, Any],
        extra: dict[str, Any],
        decision: str,
        run_id: str | None,
        violations: tuple[str, ...] = (),
        session: Any = None,
    ) -> AIAuditRecord:
        """Audit a human approval/rejection; stores a message fingerprint, never the text.

        Raises `DuplicateReviewError` if the draft already has an approved/rejected review.
        """
        return self.audit.record(
            feature="outreach_review", subject=subject, prompt_version=OUTREACH_PROMPT_VERSION,
            provider=None, model=None, generation_mode=f"human_{decision}", fallback_reason=None,
            violations=violations, input_sha256=None, output_sha256=extra.get("message_sha256"),
            latency_ms=None, extra=extra, run_id=run_id, session=session,
        )

    # -- population ------------------------------------------------------------------------

    def population_insight(
        self, facts: dict[str, Any], *, actor: dict[str, Any] | None = None
    ) -> PopulationInsight:
        deterministic = _deterministic_population_summary(facts)
        text, meta = self._generate(
            feature="population_insight",
            prompt_version=POPULATION_PROMPT_VERSION,
            system=POPULATION_SYSTEM,
            facts=facts,
            subject={"run_id": facts.get("run_id"), "evaluation_run_id": facts.get("evaluation_run_id")},
            run_id=facts.get("run_id"),
            actor=actor,
            validate=lambda t: validate_output(t, facts=facts, max_chars=1200, must_contain=("synthetic",)),
        )
        return PopulationInsight(facts=facts, summary_text=text or deterministic, meta=meta)

    # -- patient assistant -----------------------------------------------------------------

    def patient_assistant(
        self,
        facts: dict[str, Any],
        *,
        topic: str,
        language: str,
        fallback: list[str],
        allow_completed: bool,
        subject: dict[str, Any],
        run_id: str | None,
        actor: dict[str, Any] | None = None,
        question: str | None = None,
        skip_reason: str | None = None,
    ) -> tuple[list[str], AIGenerationMeta]:
        """Plain-language answer to a portal topic about one recommendation.

        `facts` are the minimum, de-identified portal facts already shown to the patient (no names,
        ids, dates of birth, free text or staff notes); `fallback` is the deterministic answer built
        from the same facts and is returned whenever the model is disabled, fails or is rejected.
        `question` (topic `question`) is screened by the caller and sent as a delimited untrusted
        block; `skip_reason` answers with the fallback without calling the provider.
        """
        return self._patient_answer(
            feature="patient_assistant", prompt_version=PATIENT_ASSISTANT_PROMPT_VERSION,
            system=PATIENT_ASSISTANT_SYSTEM.format(
                topic_instruction=PATIENT_ASSISTANT_TOPICS[topic], language=language,
                language_rules=PATIENT_ASSISTANT_LANGUAGE_RULES[language], max_chars=900,
            ),
            facts=facts, topic=topic, language=language, fallback=fallback, allow_completed=allow_completed,
            subject=subject, run_id=run_id, actor=actor, question=question, skip_reason=skip_reason,
        )

    def portal_assistant(
        self,
        facts: dict[str, Any],
        *,
        topic: str,
        language: str,
        fallback: list[str],
        subject: dict[str, Any],
        run_id: str | None,
        actor: dict[str, Any] | None = None,
        question: str | None = None,
        skip_reason: str | None = None,
    ) -> tuple[list[str], AIGenerationMeta]:
        """Portal-level care navigation (overview, portal help, contacting the care team, questions)
        over the patient's own de-identified portal facts; same guardrails and fallback rules."""
        return self._patient_answer(
            feature="portal_assistant", prompt_version=PORTAL_ASSISTANT_PROMPT_VERSION,
            system=PORTAL_ASSISTANT_SYSTEM.format(
                topic_instruction=PORTAL_ASSISTANT_TOPICS[topic], language=language,
                language_rules=PATIENT_ASSISTANT_LANGUAGE_RULES[language], max_chars=900,
            ),
            facts=facts, topic=topic, language=language, fallback=fallback, allow_completed=False,
            subject=subject, run_id=run_id, actor=actor, question=question, skip_reason=skip_reason,
        )

    def _patient_answer(
        self, *, feature: str, prompt_version: str, system: str, facts: dict[str, Any], topic: str,
        language: str, fallback: list[str], allow_completed: bool, subject: dict[str, Any],
        run_id: str | None, actor: dict[str, Any] | None, question: str | None, skip_reason: str | None,
    ) -> tuple[list[str], AIGenerationMeta]:
        max_chars = 900
        extra: dict[str, Any] = {"topic": topic, "language": language}
        if question is not None:  # the question itself is never stored, only its size and fingerprint
            extra.update(question_chars=len(question), question_sha256=sha256(question))
        text, meta = self._generate(
            feature=feature,
            prompt_version=prompt_version,
            system=system,
            facts=facts,
            user=question_payload(facts, question),
            subject=subject,
            validate=lambda t: validate_portal_answer(
                t, facts=facts, language=language, max_chars=max_chars, allow_completed=allow_completed
            ),
            extra=extra,
            fallback_text="\n".join(fallback),
            run_id=run_id,
            actor=actor,
            skip_reason=skip_reason,
        )
        if text is None:
            return fallback, meta
        return [line.strip() for line in text.splitlines() if line.strip()], meta

    # -- staff copilot ---------------------------------------------------------------------

    def staff_copilot(
        self,
        facts: dict[str, Any],
        *,
        task: str,
        language: str,
        fallback: dict[str, Any],
        subject: dict[str, Any],
        run_id: str | None,
        actor: dict[str, Any] | None = None,
    ) -> tuple[dict[str, Any], AIGenerationMeta]:
        """Role-scoped summary `{"summary", "points", "questions"}` of facts the caller may already
        see. The model's JSON is parsed strictly and every field is validated; otherwise the
        deterministic `fallback` built from the same facts is returned. Nothing is changed or sent."""
        audience, instruction = STAFF_COPILOT_TASKS[task]
        text, meta = self._generate(
            feature="staff_copilot",
            prompt_version=STAFF_COPILOT_PROMPT_VERSION,
            system=STAFF_COPILOT_SYSTEM.format(
                audience=audience, task_instruction=instruction, language=language,
                language_rules=STAFF_COPILOT_LANGUAGE_RULES[language],
            ),
            facts=facts,
            subject=subject,
            validate=lambda t: validate_copilot_output(t, facts=facts, language=language),
            extra={"task": task, "language": language},
            fallback_text=json.dumps(fallback, sort_keys=True, ensure_ascii=False),
            run_id=run_id,
            actor=actor,
            json_mode=True,
        )
        parsed = parse_copilot_output(text) if text is not None else None
        return (parsed if parsed is not None else fallback), meta


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
        f"{f['review_flagged_patients_count']} have records that need clinical review."
    )
    if "rule_review_patients_count" in f:
        parts.append(
            f"{f['rule_review_patients_count']} have at least one applicable rule that is itself "
            "awaiting clinical review."
        )
    return " ".join(parts)


@lru_cache(maxsize=1)
def get_ai_service() -> AIService:
    return build_ai_service(settings)


def build_ai_service(cfg: Settings) -> AIService:
    provider, status = build_provider(cfg)
    if cfg.llm_enabled and provider is None:
        logger.warning("LLM_ENABLED is true but the provider is %s; using deterministic templates", status)
    return AIService(
        provider,
        provider_status=status,
        max_output_tokens=cfg.llm_max_output_tokens,
        configured_provider=cfg.llm_provider if cfg.llm_enabled else None,
        audit=PostgresAIAuditLog(get_engine) if cfg.data_source == "db" else AIAuditLog(),
    )


def _ai_available(meta: AIGenerationMeta) -> bool:
    """True when a provider is configured and the call did not fail (a guardrail rejection still
    means the AI is reachable; the standard text is shown either way)."""
    return meta.provider is not None and meta.fallback_reason != "provider_error"
