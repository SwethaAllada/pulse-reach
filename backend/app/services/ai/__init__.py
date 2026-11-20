"""AI assistance layer (explanations, simulated outreach drafts, population insights, patient assistant)."""

from app.services.ai.audit import AIAuditLog, AIAuditRecord, DuplicateReviewError, PostgresAIAuditLog
from app.services.ai.provider import LLMCompletion, LLMProvider, LLMProviderError, build_provider
from app.services.ai.service import (
    DETERMINISTIC,
    LLM_GROUNDED,
    AIGenerationMeta,
    AIService,
    OutreachDraft,
    PopulationInsight,
    build_ai_service,
    get_ai_service,
)

__all__ = [
    "AIAuditLog",
    "AIAuditRecord",
    "AIGenerationMeta",
    "AIService",
    "DuplicateReviewError",
    "PostgresAIAuditLog",
    "DETERMINISTIC",
    "LLMCompletion",
    "LLMProvider",
    "LLMProviderError",
    "LLM_GROUNDED",
    "OutreachDraft",
    "PopulationInsight",
    "build_ai_service",
    "build_provider",
    "get_ai_service",
]
