"""Customer service reads and authenticated canonical capability mutations."""

from __future__ import annotations

import logging
import os
from typing import Any

from fastapi import HTTPException, Request
from fastapi.responses import JSONResponse

from app.mod_sdk.erp_domain_compat import ERP_DOMAIN_BRIDGE_MOD_ID, _read_manifest
from app.schemas.customer_schema import CustomerCompatMutation as CustomerCompatMutation

logger = logging.getLogger(__name__)


def _truthy_env(name: str) -> bool:
    return (os.environ.get(name) or "").strip().lower() in {"1", "true", "yes", "on"}


def is_erp_customers_via_service_enabled() -> bool:
    if _truthy_env("XCAGI_DISABLE_ERP_CUSTOMERS_VIA_SERVICE"):
        return False
    if _truthy_env("XCAGI_ERP_CUSTOMERS_VIA_SERVICE"):
        return True
    cfg = _read_manifest().get("config") or {}
    if isinstance(cfg, dict) and cfg.get("customers_via_service") is True:
        return True
    return False


def _service():
    from app.bootstrap import get_customer_app_service

    return get_customer_app_service()


def _validated_body(body: dict[str, Any]) -> dict[str, Any]:
    return CustomerCompatMutation.model_validate(body).model_dump(exclude_unset=True)


def _map_body(body: dict[str, Any]) -> dict[str, Any]:
    from app.infrastructure.persistence.compat_db.compat_db_base import _customer_body_name_contact

    name, cp, ph, addr = _customer_body_name_contact(_validated_body(body))
    return {
        "customer_name": name,
        "contact_person": cp or "",
        "contact_phone": ph or "",
        "contact_address": addr or "",
    }


def _write_gate(request: Request | None) -> None:
    from app.infrastructure.persistence.compat_db.compat_db_base import _customers_write_raise

    if request is not None:
        _customers_write_raise(request)


def _stamp(out: dict[str, Any]) -> dict[str, Any]:
    from app.mod_sdk.erp_repository_registry import get_repository_execution_meta

    out["source"] = f"mod:{ERP_DOMAIN_BRIDGE_MOD_ID}"
    out["execution_path"] = "customers_service"
    out.update(get_repository_execution_meta("customers"))
    return out


def customers_list(
    request: Request | None = None,
    *,
    page: int = 1,
    per_page: int = 20,
    keyword: str | None = None,
) -> dict[str, Any]:
    from app.infrastructure.auth.db_token import verify_db_read_token_header

    if request is not None:
        verify_db_read_token_header(request)
    out = _service().get_all(keyword=keyword, page=page, per_page=per_page)
    if not out.get("success"):
        return _stamp(
            {
                "success": False,
                "message": out.get("message", "查询失败"),
                "data": [],
                "total": 0,
            }
        )
    return _stamp(
        {
            "success": True,
            "data": out.get("data") or [],
            "total": int(out.get("total") or 0),
        }
    )


def customers_get(request: Request | None, customer_id: int) -> dict | JSONResponse:
    from app.infrastructure.auth.db_token import verify_db_read_token_header

    if request is not None:
        verify_db_read_token_header(request)
    result = _service().get_by_id(customer_id)
    if result.get("success"):
        return _stamp(result)
    return JSONResponse(result, status_code=404)


def customers_export(request: Request, keyword: str | None = None, template_id: str | None = None):
    from pathlib import Path

    from fastapi.responses import FileResponse

    from app.infrastructure.auth.db_token import verify_db_read_token_header
    from app.utils.path_io.path_utils import get_data_dir
    from app.utils.security.safe_download_path import (
        UnsafeDownloadPathError,
        resolve_under_allowed_dirs,
    )

    verify_db_read_token_header(request)
    result = _service().export_to_excel(keyword=keyword, template_id=template_id)
    if not result.get("success"):
        raise HTTPException(status_code=400, detail=result.get("message") or "客户导出失败")
    try:
        path = resolve_under_allowed_dirs(
            str(result.get("file_path") or ""), [Path(get_data_dir())]
        )
    except UnsafeDownloadPathError as exc:
        raise HTTPException(status_code=500, detail="导出文件路径无效") from exc
    if not path.is_file():
        raise HTTPException(status_code=500, detail="导出文件不存在")
    return FileResponse(
        path,
        filename=result.get("filename"),
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )


def _run_customer_capability(request: Request, action: str, params: dict[str, Any]) -> JSONResponse:
    from app.fastapi_routes.tools_execute import run_tools_execute_agent

    if request is None:
        raise HTTPException(status_code=401, detail="客户操作需要已绑定的登录会话")
    _write_gate(request)
    result, status = run_tools_execute_agent(
        request=request,
        body={"tool_id": "customers", "action": action, "params": params},
        route_path=str(request.url.path),
    )
    return JSONResponse(result, status_code=status)


def customers_create(request: Request, body: dict[str, Any]) -> JSONResponse:
    mapped = _map_body(body)
    if not mapped.get("customer_name"):
        raise HTTPException(status_code=400, detail="客户名称不能为空")
    mapped["unit_name"] = mapped["customer_name"]
    return _run_customer_capability(request, "create", mapped)


def customers_update(request: Request, customer_id: int, body: dict[str, Any]) -> JSONResponse:
    validated = _validated_body(body)
    mapped = _map_body(validated)
    if not mapped.get("customer_name"):
        raise HTTPException(status_code=400, detail="客户名称不能为空")
    if "expected_version" in validated:
        mapped["expected_version"] = validated["expected_version"]
    return _run_customer_capability(request, "update", {"id": customer_id, **mapped})


def customers_delete(request: Request, customer_id: int, cascade: bool = False) -> JSONResponse:
    if cascade:
        from app.infrastructure.auth.dependencies import require_permission

        require_permission("shipment.edit")(request)
        require_permission("product.edit")(request)
    return _run_customer_capability(request, "delete", {"id": customer_id, "force": cascade})


__all__ = [
    "customers_create",
    "customers_delete",
    "customers_export",
    "customers_get",
    "customers_list",
    "customers_update",
    "is_erp_customers_via_service_enabled",
]
