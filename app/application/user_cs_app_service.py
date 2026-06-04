"""用户客服 / CRM / 财务发票 V1 应用服务。"""

from __future__ import annotations

from typing import Any

from app.infrastructure.gateways import cs_operations as cs

_user_cs_app_service: "UserCsApplicationService | None" = None


class UserCsApplicationService:
    """客服管道、CRM 发票、统一账本等 HTTP 用例入口。"""

    def list_crm_invoices(self, *args: Any, **kwargs: Any) -> Any:
        return cs.list_crm_invoices(*args, **kwargs)

    def get_crm_invoice_by_id(self, *args: Any, **kwargs: Any) -> Any:
        return cs.get_crm_invoice_by_id(*args, **kwargs)

    def issue_crm_invoice_for_pipeline(self, *args: Any, **kwargs: Any) -> Any:
        return cs.issue_crm_invoice_for_pipeline(*args, **kwargs)

    def get_opportunity_by_market_user(self, *args: Any, **kwargs: Any) -> Any:
        return cs.get_opportunity_by_market_user(*args, **kwargs)

    def load_pipeline(self, *args: Any, **kwargs: Any) -> Any:
        return cs.load_pipeline(*args, **kwargs)

    def save_pipeline(self, doc: Any, *, strict_crm: bool | None = None, **kwargs: Any) -> Any:
        return cs.save_pipeline(doc, strict_crm=strict_crm, **kwargs)

    def crm_connect(self) -> tuple[Any, Any]:
        return cs._connect, cs.ensure_crm_schema

    def archive_from_crm_invoice(self, *args: Any, **kwargs: Any) -> Any:
        return cs.archive_from_crm_invoice(*args, **kwargs)

    def list_ledger(self, *args: Any, **kwargs: Any) -> Any:
        return cs.list_ledger(*args, **kwargs)

    def summarize_ledger(self, *args: Any, **kwargs: Any) -> Any:
        return cs.summarize_ledger(*args, **kwargs)

    def rebuild_ledger_archive(self, *args: Any, **kwargs: Any) -> Any:
        return cs.rebuild_ledger_archive(*args, **kwargs)

    def signoff_backend_info(self, *args: Any, **kwargs: Any) -> Any:
        return cs.signoff_backend_info(*args, **kwargs)


def get_user_cs_app_service() -> UserCsApplicationService:
    global _user_cs_app_service
    if _user_cs_app_service is None:
        _user_cs_app_service = UserCsApplicationService()
    return _user_cs_app_service
