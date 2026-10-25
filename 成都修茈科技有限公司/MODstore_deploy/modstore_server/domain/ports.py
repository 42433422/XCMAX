"""MODstore domain ports (consolidated)."""

from __future__ import annotations

from typing import Protocol
from modstore_server.domain.analytics.analytics_types import AnalyticsDashboard
from modstore_server.domain.auth.auth_types import PersonalAccessToken
from pathlib import Path
from typing import Any, Protocol
from modstore_server.domain.catalog.catalog_types import CatalogItem
from modstore_server.domain.employee.employee_types import EmployeeExecution, EmployeePack
from modstore_server.domain.knowledge.knowledge_types import KnowledgeIndexRef
from modstore_server.domain.llm.llm_types import LlmCredential
from modstore_server.domain.market.market_types import MarketListing, MarketSearchQuery
from typing import Any, Iterable, Protocol
from .employee_types import Notification, OutboundNotification
from modstore_server.domain.payment_gateway.payment_gateway_types import OrderRef
from modstore_server.domain.refund.refund_types import RefundRequestRef
from modstore_server.domain.wallet.wallet_types import WalletBalance
from modstore_server.domain.workflow.workflow_types import Workflow, WorkflowExecution

# --- analytics ---
class AnalyticsRepository(Protocol):
    """Read-only analytics aggregate for a user."""

    def dashboard_for_user(self, user_id: int) -> AnalyticsDashboard: ...


__all__ = ["AnalyticsRepository"]

# --- auth ---
class PersonalAccessTokenRepository(Protocol):
    def save(self, row: PersonalAccessToken, *, token_digest: str, raw_prefix: str) -> int:
        """Persist and return token row id."""

    def revoke(self, *, user_id: int, token_id: int) -> bool: ...


__all__ = ["PersonalAccessTokenRepository"]

# --- catalog ---
class CatalogRepository(Protocol):
    """Read/write catalog rows (e.g. SQLAlchemy ``CatalogItem``)."""

    def get_by_pkg_id(self, pkg_id: str) -> CatalogItem | None: ...

    def upsert(self, item: CatalogItem, *, price: float) -> None: ...


class CatalogPackageStorage(Protocol):
    """Append-only package blob storage (filesystem or object store)."""

    def append_package(self, record: dict[str, Any], src_file: Path | None) -> dict[str, Any]: ...


__all__ = ["CatalogRepository", "CatalogPackageStorage"]

# --- employee ---
class EmployeeRepository(Protocol):
    """Persistence for employee packs and metadata."""

    def save_pack(self, pack: EmployeePack) -> None: ...

    def get_pack(self, pack_id: str) -> EmployeePack | None: ...


class EmployeeMetricsRepository(Protocol):
    """Execution metrics / audit trail."""

    def record_execution(self, execution: EmployeeExecution) -> None: ...

    def list_recent(self, employee_id: str, *, limit: int = 20) -> list[dict[str, Any]]: ...


__all__ = ["EmployeeRepository", "EmployeeMetricsRepository"]

# --- knowledge ---
class KnowledgeIndexRepository(Protocol):
    def describe(self, ref: KnowledgeIndexRef) -> dict: ...


__all__ = ["KnowledgeIndexRepository"]

# --- llm ---
class LlmCredentialRepository(Protocol):
    def get_for_user(self, user_id: int, provider: str) -> LlmCredential | None: ...

    def save_encrypted_blob(self, user_id: int, provider: str, blob: bytes) -> None: ...


class LlmKeyResolverPort(Protocol):
    """Resolve effective API key / base URL for outbound provider calls."""

    def resolve(self, *, user_id: int, provider: str, model: str) -> dict[str, Any]: ...


__all__ = ["LlmCredentialRepository", "LlmKeyResolverPort"]

# --- market ---
class MarketBrowseRepository(Protocol):
    def search(self, query: MarketSearchQuery) -> list[MarketListing]: ...


__all__ = ["MarketBrowseRepository"]

# --- notification ---
class NotificationRepository(Protocol):
    """Persistence port. Concrete impl lives in
    :mod:`modstore_server.infrastructure.notification`.
    """

    def add(self, outbound: OutboundNotification) -> Notification: ...

    def list_for_user(
        self,
        user_id: int,
        *,
        unread_only: bool = False,
        kind: str | None = None,
        limit: int = 50,
    ) -> list[Notification]: ...

    def mark_read(self, notification_id: int, user_id: int) -> bool: ...

    def mark_all_read(self, user_id: int) -> int: ...

    def count_unread(self, user_id: int) -> int: ...


class RealtimePusher(Protocol):
    """Outbound port for realtime delivery (WebSocket / SSE / push)."""

    def push(self, user_id: int, payload: dict[str, Any]) -> None: ...


__all__ = ["NotificationRepository", "RealtimePusher"]


# ``Iterable`` only kept for re-export from this module if a future port needs it.
_ = Iterable  # noqa: F841 - intentional re-export hook

# --- payment_gateway ---
class PaymentReadRepository(Protocol):
    def get_order(self, order_no: str) -> OrderRef | None: ...


__all__ = ["PaymentReadRepository"]

# --- refund ---
class RefundRepository(Protocol):
    def get(self, refund_id: int) -> RefundRequestRef | None: ...


__all__ = ["RefundRepository"]

# --- wallet ---
class WalletRepository(Protocol):
    def balance(self, user_id: int) -> WalletBalance: ...


__all__ = ["WalletRepository"]

# --- workflow ---
class WorkflowRepository(Protocol):
    def get(self, workflow_id: int) -> Workflow | None: ...

    def save(self, workflow: Workflow) -> None: ...


class WorkflowExecutionRepository(Protocol):
    def save(self, execution: WorkflowExecution) -> None: ...

    def get(self, execution_id: int) -> WorkflowExecution | None: ...

    def list_for_workflow(self, workflow_id: int, *, limit: int = 50) -> list[dict[str, Any]]: ...


__all__ = ["WorkflowRepository", "WorkflowExecutionRepository"]

