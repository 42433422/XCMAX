"""运营线 / 对账 / 合同到期扫描 V1 应用服务。"""

from __future__ import annotations

from typing import Any

from app.infrastructure.gateways import cs_operations as cs

_operations_app_service: OperationsApplicationService | None = None


class OperationsApplicationService:
    def compute_operations_health(self, *args: Any, **kwargs: Any) -> Any:
        return cs.compute_operations_health(*args, **kwargs)

    def run_contract_expiry_scan(self, *args: Any, **kwargs: Any) -> Any:
        return cs.run_contract_expiry_scan(*args, **kwargs)

    def get_reconciliation_status(self, *args: Any, **kwargs: Any) -> Any:
        return cs.get_reconciliation_status(*args, **kwargs)

    def reconciliation_scheduler(self) -> Any:
        return cs.reconciliation_scheduler

    def fhd_payment_reconciliation(self) -> Any:
        return cs.fhd_payment_reconciliation


def get_operations_app_service() -> OperationsApplicationService:
    global _operations_app_service
    if _operations_app_service is None:
        _operations_app_service = OperationsApplicationService()
    return _operations_app_service
