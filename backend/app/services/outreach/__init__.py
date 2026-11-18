"""Dedicated simulated outreach preview service (`app.services.outreach`)."""

from app.services.outreach.service import (
    OutreachRuleNotFoundError,
    OutreachService,
)

__all__ = [
    "OutreachRuleNotFoundError",
    "OutreachService",
]
