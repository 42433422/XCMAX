"""六线事件轨 HTTP API（全景 live + operations_line 桥接）。"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Body
from fastapi.responses import JSONResponse

from app.application.six_line_event_app_service import get_six_line_event_app_service

admin_router = APIRouter(prefix="/api/admin/production-line", tags=["production-line-event"])
xcmax_router = APIRouter(prefix="/api/xcmax/production-line", tags=["production-line-event"])


def _post_event(body: dict[str, Any]) -> JSONResponse:
    data = get_six_line_event_app_service().dispatch(body)
    return JSONResponse({"success": True, "data": data})


def _status() -> JSONResponse:
    return JSONResponse(
        {"success": True, "data": get_six_line_event_app_service().status_snapshot()}
    )


def _backlog_preview(limit: int) -> JSONResponse:
    items = get_six_line_event_app_service().list_backlog_for_digest(limit=limit)
    return JSONResponse({"success": True, "data": {"items": items, "count": len(items)}})


@admin_router.post("/event")
@xcmax_router.post("/event")
async def production_line_event(body: dict[str, Any] = Body(...)):
    return _post_event(body)


@admin_router.get("/event-rail/status")
@xcmax_router.get("/event-rail/status")
async def production_line_event_rail_status():
    return _status()


@admin_router.get("/event-rail/backlog")
@xcmax_router.get("/event-rail/backlog")
async def production_line_event_backlog(limit: int = 50):
    return _backlog_preview(limit)


def _time_rail_graph() -> JSONResponse:
    from app.application.time_rail_app_service import get_time_rail_app_service

    return JSONResponse({"success": True, "data": get_time_rail_app_service().graph_payload()})


async def _time_rail_status(node_id: str | None = None) -> JSONResponse:
    from app.application.time_rail_app_service import (
        TimeRailStatusUnavailableError,
        get_time_rail_app_service,
    )

    try:
        data = await get_time_rail_app_service().runtime_status(node_id=node_id)
        return JSONResponse({"success": True, "data": data})
    except TimeRailStatusUnavailableError as exc:
        return JSONResponse(
            {"success": False, "error": str(exc), "data": None},
            status_code=503,
        )


@admin_router.get("/time-rail/graph")
@xcmax_router.get("/time-rail/graph")
async def production_line_time_rail_graph():
    return _time_rail_graph()


@admin_router.get("/time-rail/status")
@xcmax_router.get("/time-rail/status")
async def production_line_time_rail_status(node_id: str | None = None):
    return await _time_rail_status(node_id)
