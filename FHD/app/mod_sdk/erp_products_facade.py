"""Canonical product admission and the existing product read service."""

from __future__ import annotations

import logging
import os
from typing import Any, cast

from fastapi import HTTPException, Request
from fastapi.responses import JSONResponse

from app.mod_sdk.erp_domain_compat import ERP_DOMAIN_BRIDGE_MOD_ID, _read_manifest

logger = logging.getLogger(__name__)


def _truthy_env(name: str) -> bool:
    return (os.environ.get(name) or "").strip().lower() in {"1", "true", "yes", "on"}


def is_erp_products_via_service_enabled() -> bool:
    if _truthy_env("XCAGI_DISABLE_ERP_PRODUCTS_VIA_SERVICE"):
        return False
    if _truthy_env("XCAGI_ERP_PRODUCTS_VIA_SERVICE"):
        return True
    cfg = _read_manifest().get("config") or {}
    if isinstance(cfg, dict) and cfg.get("products_via_service") is True:
        return True
    return False


def _service():
    from app.bootstrap import get_products_service

    return get_products_service()


def _map_create_body(body: dict[str, Any]) -> dict[str, Any]:
    from app.domain.app_pure.excel_imports import _norm_model

    name = str(body.get("name") or "").strip()
    spec = str(body.get("specification") or "").strip()
    mn = str(body.get("model_number") or body.get("product_code") or "").strip()
    if not mn:
        mn = _norm_model("", name, spec)
    price = body.get("unit_price", body.get("price", 0))
    price = 0 if price == "" else price
    return {
        "name": name,
        "specification": spec,
        "product_code": mn,
        "unit_price": price,
        "quantity": body.get("quantity", 0),
        "unit": str(body.get("unit") or "个").strip() or "个",
        "description": body.get("description") or "",
        "category": body.get("category") or "",
        "brand": body.get("brand") or "",
    }


def _write_gate(request: Request | None) -> dict | None:
    from app.infrastructure.persistence.compat_db.compat_db_base import (
        _business_mod_json_block,
        _products_write_raise,
    )

    if request is not None:
        _products_write_raise(request)
    return _business_mod_json_block()


def products_list(
    request: Request | None = None,
    *,
    page: int = 1,
    per_page: int = 20,
    keyword: str | None = None,
    unit: str | None = None,
) -> dict[str, Any]:
    from app.infrastructure.auth.db_token import verify_db_read_token_header

    if request is not None:
        verify_db_read_token_header(request)
    out = _service().get_products(
        unit_name=unit,
        keyword=keyword,
        page=page,
        per_page=per_page,
    )
    if not out.get("success"):
        return {
            "success": False,
            "message": out.get("message", "查询失败"),
            "data": [],
            "total": 0,
        }
    payload: dict[str, Any] = {
        "success": True,
        "data": out.get("data") or [],
        "total": int(out.get("total") or 0),
    }
    payload["source"] = f"mod:{ERP_DOMAIN_BRIDGE_MOD_ID}"
    payload["execution_path"] = "products_service"
    from app.mod_sdk.erp_repository_registry import get_repository_execution_meta

    payload.update(get_repository_execution_meta("products"))
    return payload


def products_get(request: Request, product_id: int) -> dict | JSONResponse:
    from app.infrastructure.auth.db_token import verify_db_read_token_header

    verify_db_read_token_header(request)
    result = _service().get_product(product_id)
    if result.get("success"):
        data = result.get("data")
        if hasattr(data, "to_dict"):
            result = {**result, "data": data.to_dict()}
        result["source"] = f"mod:{ERP_DOMAIN_BRIDGE_MOD_ID}"
        result["execution_path"] = "products_service"
        return cast("dict[Any, Any] | JSONResponse", result)
    return JSONResponse(result, status_code=404)


def products_product_names(keyword: str = "") -> dict[str, Any]:
    out = _service().get_product_names(keyword=keyword or None)
    out["source"] = f"mod:{ERP_DOMAIN_BRIDGE_MOD_ID}"
    out["execution_path"] = "products_service"
    return cast("dict[str, Any]", out)


def _run_product_capability(request: Request, action: str, body: dict[str, Any]) -> JSONResponse:
    from app.fastapi_routes.tools_execute import run_tools_execute_agent
    from app.legacy.routes.product.mutation_flow import _normalize_products_create_payload

    if request is None:
        raise HTTPException(status_code=401, detail="产品操作需要已绑定的登录会话")
    gate = _write_gate(request)
    if gate:
        return JSONResponse(gate, status_code=403)
    params = _normalize_products_create_payload(body) if action == "create" else dict(body)
    result, status = run_tools_execute_agent(
        request=request,
        body={"tool_id": "products", "action": action, "params": params},
        route_path=str(request.url.path),
    )
    return JSONResponse(result, status_code=status)


def products_add(request: Request, body: dict[str, Any]) -> JSONResponse:
    return _run_product_capability(request, "create", body)


def products_update(request: Request, body: dict[str, Any]) -> JSONResponse:
    return _run_product_capability(request, "update", body)


def products_delete(request: Request, body: dict[str, Any]) -> JSONResponse:
    return _run_product_capability(request, "delete", body)


def products_batch_delete(request: Request, body: dict[str, Any]) -> JSONResponse:
    return _run_product_capability(request, "batch_delete", body)


def products_batch(request: Request, body: dict[str, Any]) -> JSONResponse:
    products = body.get("products") or []
    if not isinstance(products, list) or not products:
        raise HTTPException(status_code=400, detail="products 必须为非空数组")
    mapped = [_map_create_body(p) if isinstance(p, dict) else p for p in products]
    return _run_product_capability(request, "batch_create", {"products": mapped})


__all__ = [
    "is_erp_products_via_service_enabled",
    "products_add",
    "products_batch",
    "products_batch_delete",
    "products_delete",
    "products_get",
    "products_list",
    "products_product_names",
    "products_update",
]
