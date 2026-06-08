"""Admin 产线事件轨 API（MODstore 挂载）。"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Body
from fastapi.responses import JSONResponse

from modstore_server import six_line_event_router as router_mod
from modstore_server.incident_bus import enqueue as incident_enqueue

router = APIRouter(prefix="/api/admin/production-line", tags=["production-line"])


@router.post("/event")
async def production_line_event(body: dict[str, Any] = Body(...)):
    return JSONResponse({"success": True, "data": router_mod.dispatch(body)})


@router.post("/incident")
async def production_line_incident(body: dict[str, Any] = Body(...)):
    row = incident_enqueue(body)
    return JSONResponse({"success": True, "data": row})


@router.get("/event-rail/status")
async def production_line_event_rail_status():
    return JSONResponse({"success": True, "data": router_mod.status_snapshot()})
