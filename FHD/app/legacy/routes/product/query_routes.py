"""Product read endpoints, unit choices and name resolution."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any, cast

from fastapi import APIRouter, Body, Query, Request
from fastapi.responses import JSONResponse

from .query_flow import ProductQueries


class ProductQueryRoutes:
    """Product read endpoints, unit choices and name resolution."""

    def __init__(
        self,
        *,
        queries: Callable[[], ProductQueries],
        verify_read: Callable[[Request], None],
        product_units: Callable[[], dict[str, Any]],
        shipment_units: Callable[[], dict[str, Any]],
        purchase_units: Callable[[], object],
    ) -> None:
        router = self.router = APIRouter()

        @router.get("/products/units")
        def products_units(request: Request) -> dict:
            verify_read(request)
            return cast("dict[Any, Any]", product_units())

        self.products_units = products_units

        @router.get("/shipment/shipment-records/units")
        @router.get("/shipment/shipment-records/units/", include_in_schema=False)
        def shipment_records_units() -> dict:
            return shipment_units()

        self.shipment_records_units = shipment_records_units

        @router.get("/mod/taiyangniao-pro/shipment/shipment-records/units")
        @router.get(
            "/mod/taiyangniao-pro/shipment/shipment-records/units/", include_in_schema=False
        )
        def taiyangniao_shipment_records_units_host_alias() -> dict:
            """Stable host alias for desktop clients with independently updated private Mods."""
            from app.domain.catalog.attendance_reference_data import attendance_unit_names

            units = attendance_unit_names(product_units())
            return {"success": True, "data": units, "units": units, "source": "host_compat"}

        self.taiyangniao_shipment_records_units_host_alias = (
            taiyangniao_shipment_records_units_host_alias
        )

        @router.get("/purchase_units")
        @router.get("/purchase_units/", include_in_schema=False)
        def purchase_units_list() -> dict:
            return {"success": True, "data": purchase_units()}

        self.purchase_units_list = purchase_units_list

        @router.get("/products/list")
        def products_list(
            request: Request,
            page: int = Query(default=1, ge=1),
            per_page: int = Query(default=20, ge=1, le=2000),
            keyword: str | None = Query(None),
            unit: str | None = Query(None),
        ) -> dict:
            return queries().list(request, page, per_page, keyword, unit)

        self.products_list = products_list

        @router.get("/products/{product_id:int}", response_model=None)
        @router.get("/products/{product_id:int}/", response_model=None, include_in_schema=False)
        def products_get_by_id(request: Request, product_id: int) -> dict | JSONResponse:
            return queries().get(request, product_id)

        self.products_get_by_id = products_get_by_id

        @router.post("/products/resolve-name-hints")
        @router.post("/products/resolve-name-hints/", include_in_schema=False)
        def products_resolve_name_hints(
            request: Request, body: dict = Body(default_factory=dict)
        ) -> dict:
            return queries().resolve_name_hints(request, body)

        self.products_resolve_name_hints = products_resolve_name_hints
