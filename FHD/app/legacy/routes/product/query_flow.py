"""Product reads preserve Mod, service and legacy fallback ownership."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from logging import Logger

from fastapi import HTTPException, Request
from fastapi.responses import JSONResponse

from .port_contracts import Payload, ProductListDispatcher, ProductLookup, ProductServiceFacade


@dataclass(frozen=True)
class ProductQueries:
    verify_read: Callable[[Request], None]
    legacy_list: Callable[[int, int, str | None, str | None], tuple[list[dict], int, str | None]]
    business_block: Callable[[], dict | None]
    dispatcher_factory: Callable[[], ProductListDispatcher]
    service_factory: Callable[[], ProductServiceFacade]
    lookup_factory: Callable[[], ProductLookup]
    recoverable_errors: tuple[type[Exception], ...]
    logger: Logger

    def list(
        self, request: Request, page: int, per_page: int, keyword: str | None, unit: str | None
    ) -> Payload:
        try:
            mod_out = self.dispatcher_factory()(
                "products",
                "list",
                request=request,
                page=page,
                per_page=per_page,
                keyword=keyword,
                unit=unit,
            )
            if mod_out is not None:
                return mod_out
        except self.recoverable_errors:
            self.logger.debug("erp domain products.list dispatch skipped", exc_info=True)
        try:
            service = self.service_factory()
            if service.is_erp_products_via_service_enabled():
                return service.products_list(
                    request, page=page, per_page=per_page, keyword=keyword, unit=unit
                )
        except self.recoverable_errors:
            self.logger.debug("products list via service skipped", exc_info=True)
        self.verify_read(request)
        try:
            items, total, schema_hint = self.legacy_list(page, per_page, keyword, unit)
            out: Payload = {"success": True, "data": items, "total": total}
            if schema_hint:
                out["schema_hint"] = schema_hint
            return out
        except self.recoverable_errors:
            self.logger.exception("products list failed (postgresql)")
            return {
                "success": False,
                "message": "产品服务暂时不可用，请稍后重试",
                "data": [],
                "total": 0,
            }

    def get(self, request: Request, product_id: int) -> Payload | JSONResponse:
        try:
            service = self.service_factory()
            if service.is_erp_products_via_service_enabled():
                return service.products_get(request, product_id)
        except self.recoverable_errors:
            self.logger.debug("products get via service skipped", exc_info=True)
        self.verify_read(request)
        result = self.lookup_factory().get_product(product_id)
        return result if result.get("success") else JSONResponse(result, status_code=404)

    def resolve_name_hints(self, request: Request, body: Payload) -> Payload:
        self.verify_read(request)
        raw = body.get("hints") or body.get("names") or []
        if not isinstance(raw, list):
            return {"success": False, "message": "hints 须为字符串数组", "data": []}
        hints = [str(value).strip() for value in raw if str(value).strip()]
        if not hints:
            return {"success": False, "message": "hints 不能为空", "data": []}
        gate = self.business_block()
        if gate:
            return {**gate, "data": []}
        raise HTTPException(
            status_code=501,
            detail="products/resolve-name-hints 未启用：product_name_resolve 模块已在清理过程中被移除，请使用销售合同流程中的 name_hint 解析能力。",
        )
