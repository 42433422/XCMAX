# mypy: disable-error-code="no-any-return, valid-type"
"""Implementation extracted from the public facade module."""

from __future__ import annotations

import importlib


def _facade():
    return importlib.import_module("app.legacy.routes.product.compat_routes")


@_facade().router.post("/products/update", response_model=None)
@_facade().router.post("/products/update/", response_model=None, include_in_schema=False)
def products_update(
    request: _facade().Request, body: dict = _facade().Body(default_factory=dict)
) -> dict[str, _facade().Any] | _facade().JSONResponse:
    payload = dict(body or {})
    gate = _facade()._products_compat_preflight(request, "update", payload)
    if gate:
        return gate
    result = _facade()._run_products_compat_agent(
        request=request, action="update", params=payload, route_path="/products/update"
    )
    return _facade().JSONResponse(
        result, status_code=_facade()._products_compat_status_code(result)
    )


@_facade().router.post("/products/add", response_model=None)
@_facade().router.post("/products/add/", response_model=None, include_in_schema=False)
def products_add(
    request: _facade().Request, body: dict = _facade().Body(default_factory=dict)
) -> dict[str, _facade().Any] | _facade().JSONResponse:
    payload = _facade()._normalize_products_create_payload(dict(body or {}))
    gate = _facade()._products_compat_preflight(request, "create", payload)
    if gate:
        return gate
    result = _facade()._run_products_compat_agent(
        request=request, action="create", params=payload, route_path="/products/add"
    )
    return _facade().JSONResponse(
        result, status_code=_facade()._products_compat_status_code(result)
    )


@_facade().router.post("/products/delete", response_model=None)
@_facade().router.post("/products/delete/", response_model=None, include_in_schema=False)
def products_delete(
    request: _facade().Request, body: dict = _facade().Body(default_factory=dict)
) -> dict[str, _facade().Any] | _facade().JSONResponse:
    payload = dict(body or {})
    gate = _facade()._products_compat_preflight(request, "delete", payload)
    if gate:
        return gate
    result = _facade()._run_products_compat_agent(
        request=request, action="delete", params=payload, route_path="/products/delete"
    )
    return _facade().JSONResponse(
        result, status_code=_facade()._products_compat_status_code(result)
    )


@_facade().router.post("/products/batch-delete", response_model=None)
@_facade().router.post("/products/batch-delete/", response_model=None, include_in_schema=False)
def products_batch_delete(
    request: _facade().Request, body: dict = _facade().Body(default_factory=dict)
) -> dict[str, _facade().Any] | _facade().JSONResponse:
    payload = dict(body or {})
    gate = _facade()._products_compat_preflight(request, "batch_delete", payload)
    if gate:
        return gate
    result = _facade()._run_products_compat_agent(
        request=request, action="batch_delete", params=payload, route_path="/products/batch-delete"
    )
    return _facade().JSONResponse(
        result, status_code=_facade()._products_compat_status_code(result)
    )


@_facade().router.get("/products/price-list-export")
@_facade().router.get("/products/price-list-export/", include_in_schema=False)
def products_price_list_export(
    request: _facade().Request,
    unit: str | None = _facade().Query(None),
    keyword: str | None = _facade().Query(None),
    export_date: str | None = _facade().Query(None, description="报价日期 YYYY-MM-DD，默认当天"),
    template_id: str | None = _facade().Query(
        None, description="模板 slug（GET /api/document-templates?role=price_list_docx）"
    ),
) -> _facade().Response:
    _facade().verify_db_read_token_header(request)
    return _facade()._products_price_list_word_response(unit, keyword, export_date, template_id)


@_facade().router.get("/products/export.docx")
@_facade().router.get("/products/export.docx/", include_in_schema=False)
def products_export_docx(
    request: _facade().Request,
    unit: str | None = _facade().Query(None),
    keyword: str | None = _facade().Query(None),
    export_date: str | None = _facade().Query(None, description="报价日期 YYYY-MM-DD，默认当天"),
    template_id: str | None = _facade().Query(
        None, description="模板 slug（GET /api/document-templates?role=price_list_docx）"
    ),
) -> _facade().Response:
    _facade().verify_db_read_token_header(request)
    return _facade()._products_price_list_word_response(unit, keyword, export_date, template_id)


@_facade().router.get("/products/price-list-template-preview")
@_facade().router.get("/products/price-list-template-preview/", include_in_schema=False)
def products_price_list_template_preview(
    request: _facade().Request,
    template_id: str | None = _facade().Query(
        None, description="模板 slug（与 price-list-export 一致）"
    ),
) -> dict:
    from app.infrastructure.documents.price_list_export import (
        build_price_list_template_preview_json,
    )

    _facade().verify_db_read_token_header(request)
    from app.shell.mod_business_scope import business_data_exposed, business_data_hidden_reason

    if not business_data_exposed():
        raise _facade().HTTPException(
            status_code=503, detail=business_data_hidden_reason() or "扩展 Mod 未就绪。"
        )
    return _facade().cast("dict[Any, Any]", build_price_list_template_preview_json(template_id))
