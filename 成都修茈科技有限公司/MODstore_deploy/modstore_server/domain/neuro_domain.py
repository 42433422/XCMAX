"""Named bounded contexts used by the MODstore Neuro-DDD refactor."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class NeuroDomainName(str, Enum):
    AUTH = "auth"
    CATALOG = "catalog"
    EMPLOYEE = "employee"
    WORKFLOW = "workflow"
    PAYMENT_GATEWAY = "payment_gateway"
    NOTIFICATION = "notification"
    LLM = "llm"
    WALLET = "wallet"
    REFUND = "refund"
    KNOWLEDGE = "knowledge"
    MARKET = "market"
    WEBHOOK = "webhook"


@dataclass(frozen=True)
class NeuroDomainBoundary:
    name: NeuroDomainName
    owner_module: str
    description: str
