"""ETL target adapter registry."""

from app.application.etl.errors import EtlError
from app.application.etl.targets.base import (
    PreviewDecision,
    TargetAdapter,
    TargetField,
    json_safe,
)
from app.application.etl.targets.batch import (
    AttendanceAdapter,
    ExportCsvAdapter,
    ExportXlsxAdapter,
    WebhookAdapter,
)
from app.application.etl.targets.customers_products import (
    CustomerAdapter,
    CustomerProductsAdapter,
    ProductAdapter,
)
from app.application.etl.targets.knowledge import KnowledgeAdapter
from app.application.etl.targets.helpers import assert_safe_webhook_url as _assert_safe_webhook_url
from app.application.etl.targets.orders import PurchaseOrderAdapter, ShipmentAdapter

_ADAPTERS: dict[str, TargetAdapter] = {
    adapter.type: adapter
    for adapter in (
        KnowledgeAdapter(),
        CustomerProductsAdapter(),
        CustomerAdapter(),
        ProductAdapter(),
        PurchaseOrderAdapter(),
        ShipmentAdapter(),
        AttendanceAdapter(),
        ExportXlsxAdapter(),
        ExportCsvAdapter(),
        WebhookAdapter(),
    )
}


def get_adapter(target_type: str) -> TargetAdapter:
    adapter = _ADAPTERS.get(str(target_type or "").strip())
    if adapter is None:
        raise EtlError("ETL_TARGET_UNSUPPORTED", f"不支持的目标类型: {target_type}")
    return adapter


def target_capabilities() -> list[dict]:
    return [adapter.capability() for adapter in _ADAPTERS.values()]


__all__ = [
    "PreviewDecision",
    "TargetAdapter",
    "TargetField",
    "get_adapter",
    "json_safe",
    "target_capabilities",
]
