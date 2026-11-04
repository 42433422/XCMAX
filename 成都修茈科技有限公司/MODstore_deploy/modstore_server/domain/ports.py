"""MODstore domain ports barrel (compat re-exports).

Canonical Protocol definitions live in ``domain/<ctx>/port_contracts.py``.
This module keeps ``from modstore_server.domain.ports import ...`` working
for application-layer call sites without growing per-context ``ports.py`` counts.
"""

from __future__ import annotations

from modstore_server.domain.analytics.port_contracts import AnalyticsRepository
from modstore_server.domain.auth.port_contracts import PersonalAccessTokenRepository
from modstore_server.domain.catalog.port_contracts import (
    CatalogPackageStorage,
    CatalogRepository,
)
from modstore_server.domain.employee.port_contracts import (
    EmployeeMetricsRepository,
    EmployeeRepository,
)
from modstore_server.domain.knowledge.port_contracts import KnowledgeIndexRepository
from modstore_server.domain.llm.port_contracts import (
    LlmCredentialRepository,
    LlmKeyResolverPort,
)
from modstore_server.domain.market.port_contracts import MarketBrowseRepository
from modstore_server.domain.notification.port_contracts import (
    NotificationRepository,
    RealtimePusher,
)
from modstore_server.domain.payment_gateway.port_contracts import PaymentReadRepository
from modstore_server.domain.refund.port_contracts import RefundRepository
from modstore_server.domain.wallet.port_contracts import WalletRepository
from modstore_server.domain.workflow.port_contracts import (
    WorkflowExecutionRepository,
    WorkflowRepository,
)

# Back-compat aliases used by older call sites / docs
MarketRepository = MarketBrowseRepository
PaymentGatewayPort = PaymentReadRepository

__all__ = [
    "AnalyticsRepository",
    "PersonalAccessTokenRepository",
    "CatalogRepository",
    "CatalogPackageStorage",
    "EmployeeRepository",
    "EmployeeMetricsRepository",
    "KnowledgeIndexRepository",
    "LlmCredentialRepository",
    "LlmKeyResolverPort",
    "MarketBrowseRepository",
    "MarketRepository",
    "NotificationRepository",
    "RealtimePusher",
    "PaymentReadRepository",
    "PaymentGatewayPort",
    "RefundRepository",
    "WalletRepository",
    "WorkflowRepository",
    "WorkflowExecutionRepository",
]
