"""Business HTTP projections of the authenticated capability execution contract.

A configured X-FHD-Business-Key remains an additional gateway check. Business
execution always requires a bound account and the shared permission policy.
"""

from __future__ import annotations

import os
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Header, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field

from app.fastapi_routes.tools_execute import run_tools_execute_agent

router = APIRouter(prefix="/api/business", tags=["business-bridge"])


def _expected_business_key() -> str:
    return (os.environ.get("FHD_BUSINESS_API_KEY") or "").strip()


def require_fhd_business_key(
    x_fhd_business_key: Annotated[str | None, Header(alias="X-FHD-Business-Key")] = None,
) -> None:
    exp = _expected_business_key()
    if not exp:
        return
    got = (x_fhd_business_key or "").strip()
    if got != exp:
        raise HTTPException(status_code=401, detail="invalid X-FHD-Business-Key")


BusinessKeyDep = Annotated[None, Depends(require_fhd_business_key)]


class PrintLabelBody(BaseModel):
    model_config = ConfigDict(extra="allow")

    job_id: str | None = None
    document_name: str = "document"
    printer_id: str = "default"
    copies: int = 1


@router.post("/print/label")
async def business_print_label(
    request: Request,
    body: PrintLabelBody,
    _: BusinessKeyDep,
) -> JSONResponse:
    return _run_business_event_agent(
        request=request,
        action="print_label",
        params=body.model_dump(exclude={"job_id"} - body.model_fields_set),
        route_path="/api/business/print/label",
    )


class InventoryUpdateBody(BaseModel):
    model_config = ConfigDict(extra="allow")

    product_id: str
    warehouse_id: str = "default"
    delta: int = 0
    reason: str = "api_business"
    new_quantity: int = 0


@router.post("/inventory/update")
async def business_inventory_update(
    request: Request,
    body: InventoryUpdateBody,
    _: BusinessKeyDep,
) -> JSONResponse:
    return _run_business_event_agent(
        request=request,
        action="inventory_update",
        params=body.model_dump(),
        route_path="/api/business/inventory/update",
    )


class OcrRecognizeBody(BaseModel):
    model_config = ConfigDict(extra="allow")

    request_id: str | None = None
    image_url: str
    ocr_type: str = "general"


def _run_business_event_agent(
    *,
    request: Request,
    action: str,
    params: dict[str, Any],
    route_path: str,
) -> JSONResponse:
    result, status = run_tools_execute_agent(
        request=request,
        body={
            "tool_id": "business_event",
            "action": action,
            "params": params,
            "request_id": params.get("request_id"),
        },
        route_path=route_path,
    )
    return JSONResponse(result, status_code=status)


@router.post("/ocr/recognize")
async def business_ocr_recognize(
    request: Request,
    body: OcrRecognizeBody,
    _: BusinessKeyDep,
) -> JSONResponse:
    request_id = (body.request_id or request.headers.get("Idempotency-Key") or "").strip()
    result, status = run_tools_execute_agent(
        request=request,
        body={
            "tool_id": "ocr",
            "action": "request",
            "request_id": request_id,
            "params": {
                "request_id": request_id,
                "image_url": body.image_url.strip(),
                "ocr_type": (body.ocr_type or "general").strip(),
            },
        },
        route_path="/api/business/ocr/recognize",
    )
    return JSONResponse(result, status_code=status)


class ShipmentCreateBody(BaseModel):
    model_config = ConfigDict(extra="allow")

    unit_name: str
    items: list[dict[str, Any]] = Field(default_factory=list)
    contact_person: str = ""
    contact_phone: str = ""


@router.post("/shipment/create")
async def business_shipment_create(
    request: Request,
    body: ShipmentCreateBody,
    _: BusinessKeyDep,
) -> JSONResponse:
    payload = {
        "unit_name": body.unit_name.strip(),
        "items": body.items,
        "contact_person": body.contact_person.strip(),
        "contact_phone": body.contact_phone.strip(),
    }
    return _run_business_event_agent(
        request=request,
        action="shipment_create",
        params=payload,
        route_path="/api/business/shipment/create",
    )


@router.get("/health")
async def business_health(_: BusinessKeyDep) -> dict[str, Any]:
    return {"success": True, "business_api": "up", "key_required": bool(_expected_business_key())}
