"""Normalize and admit product writes before their shared Agent submission."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from logging import Logger

from fastapi import HTTPException, Request
from fastapi.responses import JSONResponse

from .port_contracts import Payload, ProductAgentCall, ProductServiceFacade


def _normalize_products_create_payload(payload: Payload) -> Payload:
    data = dict(payload or {})
    name = str(
        data.get("name")
        or data.get("product_name")
        or data.get("name_or_model")
        or data.get("model_number")
        or data.get("product_code")
        or ""
    ).strip()
    if name:
        data.setdefault("name", name)
        data.setdefault("product_name", name)
        data.setdefault("name_or_model", name)
    data.setdefault("unit_name", data.get("unit") or "个")
    return data


def _http_exception_result(exc: HTTPException) -> Payload:
    return {
        "success": False,
        "message": str(exc.detail),
        "status_code": int(exc.status_code),
        "error_code": "http_exception",
    }


def response_status(result: Payload, recoverable_errors: tuple[type[Exception], ...]) -> int:
    if result.get("success"):
        return 200
    status_code = result.get("status_code")
    if status_code is None:
        parsed = 0
    else:
        try:
            parsed = int(status_code)
        except recoverable_errors:
            parsed = 0
    if 400 <= parsed < 600:
        return parsed
    return (
        500 if str(result.get("error_code") or "") in {"tool_exception", "http_exception"} else 200
    )


def service_enabled(
    factory: Callable[[], ProductServiceFacade],
    recoverable_errors: tuple[type[Exception], ...],
    logger: Logger,
) -> bool:
    try:
        return bool(factory().is_erp_products_via_service_enabled())
    except recoverable_errors:
        logger.debug("products compat service flag check skipped", exc_info=True)
        return False


def mutation_preflight(
    request: Request,
    action: str,
    payload: Payload,
    *,
    via_service: Callable[[], bool],
    verify_write: Callable[[Request], None],
    business_block: Callable[[], dict | None],
    parse_id: Callable[[object], int | None],
) -> dict | None:
    if via_service():
        return None
    verify_write(request)
    gate = business_block()
    if gate:
        return gate
    if action in {"update", "delete"}:
        pid = parse_id(payload.get("id"))
        if pid is None:
            raise HTTPException(status_code=400, detail="id 无效或缺失")
        payload["id"] = pid
    if action == "batch_delete":
        ids = payload.get("ids") or payload.get("product_ids") or []
        if not isinstance(ids, list) or not ids:
            raise HTTPException(status_code=400, detail="ids 须为非空数组")
        payload["ids"] = ids
    return None


@dataclass(frozen=True)
class ProductMutations:
    normalize_create: Callable[[Payload], Payload]
    preflight: Callable[[Request, str, Payload], dict | None]
    run_agent: ProductAgentCall
    status_code: Callable[[Payload], int]
    response: Callable[[Payload, int], JSONResponse]

    def submit(
        self, request: Request, body: Payload, *, action: str, route_path: str
    ) -> Payload | JSONResponse:
        payload = dict(body or {})
        if action == "create":
            payload = self.normalize_create(payload)
        gate = self.preflight(request, action, payload)
        if gate:
            return gate
        result = self.run_agent(
            request=request, action=action, params=payload, route_path=route_path
        )
        return self.response(result, self.status_code(result))
