"""Turn report bytes into an account-owned, JSON-safe workflow result."""

from email.message import Message
from types import SimpleNamespace
from typing import TYPE_CHECKING, Any

from app.application.agent_orchestrator.execution_identity import current_execution_actor
from app.application.aiopen.api_artifacts import save_api_export
from app.infrastructure.tenant_scope import current_tenant_id

if TYPE_CHECKING:
    from app.services.report_service import ReportService


def export_report_receipt(
    service: "ReportService", params: dict[str, Any], runtime_context: dict[str, Any] | None = None
) -> dict[str, Any]:
    from app.application.agent_orchestrator.task_mod_scope import capture_task_mod_scope

    owner = current_execution_actor()
    tenant = current_tenant_id()
    if not owner or tenant is None:
        return {
            "success": False,
            "code": "REPORT_IDENTITY_REQUIRED",
            "message": "导出报表需要已登录账号与租户身份",
        }
    mod_scope = capture_task_mod_scope(owner, str(tenant)) or {}
    data = params.get("data") or []
    source_id = params.get("data_node_id")
    if source_id:
        source = ((runtime_context or {}).get("node_outputs") or {}).get(str(source_id))
        if (
            not isinstance(source, dict)
            or source.get("success") is not True
            or not isinstance(source.get("data"), list)
        ):
            return {
                "success": False,
                "code": "REPORT_SOURCE_UNAVAILABLE",
                "message": "报表查询结果尚未成功生成，未导出文件",
            }
        data = source["data"]

    result = service.export_to_excel(
        report_type=str(params.get("report_type") or "report"),
        data=data,
        filename=str(params.get("filename") or "report"),
    )
    if not result.get("success"):
        return result
    disposition = Message()
    disposition.add_header(
        "Content-Disposition", "attachment", filename=str(result.get("filename") or "report.xlsx")
    )
    response = SimpleNamespace(
        content=result.get("data"),
        headers={
            "content-type": result.get("content_type") or "application/octet-stream",
            "content-disposition": str(disposition["Content-Disposition"]),
        },
    )
    artifact = save_api_export(
        response,
        {"owner_id": owner, "tenant_id": str(tenant), "mod_id": str(mod_scope.get("mod_id") or "")},
    )
    return {
        "success": True,
        "data": {"artifact": artifact},
        "artifacts": [artifact],
        "message": "报表已生成，可下载",
    }
