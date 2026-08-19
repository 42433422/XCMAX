"""Founder-autonomy cockpit and unattended public scorecard routes."""

from __future__ import annotations

import asyncio
import hmac
import logging
import os
from typing import Any

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

import app.fastapi_routes.xcmax_admin as admin_routes
from app.utils.operational_errors import RECOVERABLE_ERRORS

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/xcmax", tags=["founder-autonomy"])


async def _build_and_publish_founder_autonomy(
    request: Request,
    *,
    require_admin_session: bool,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Build one scorecard from live evidence and atomically publish its projection."""
    from app.application.autonomy.approval_resume import list_pending_actions
    from app.application.founder_autonomy_status import (
        build_founder_autonomy_snapshot,
        write_public_founder_autonomy_projection,
    )
    from app.application.ops_closure_status import build_ops_closure_status
    from app.fastapi_routes.knowledge_v1 import _knowledge_runtime_snapshot

    machine_authorization = (
        str(request.headers.get("Authorization") or "").strip() if not require_admin_session else ""
    )

    async def _safe_proxy(path: str) -> dict[str, Any]:
        try:
            if require_admin_session:
                payload = await admin_routes._market_admin_proxy(request, "GET", path)
            else:
                payload = await admin_routes._market_admin_proxy(
                    request,
                    "GET",
                    path,
                    require_admin_session=False,
                    authorization_override=machine_authorization,
                )
        except RECOVERABLE_ERRORS as exc:
            logger.warning("founder autonomy evidence unavailable path=%s: %s", path, exc)
            return {}
        return payload if isinstance(payload, dict) else {}

    (
        runtime,
        remote_health,
        employee_autonomy,
        employee_capability,
        customer_value,
        autonomy_audit,
        dead_letters,
        strategic_decisions,
        strategic_council,
        action_board,
    ) = await asyncio.gather(
        _safe_proxy("/api/ops/self-maintenance/status?limit=100"),
        _safe_proxy("/api/admin/duty-graph/health"),
        _safe_proxy("/api/admin/employee-autonomy/dashboard"),
        _safe_proxy(
            "/api/admin/employee-autonomy/execution-coverage"
            "?window_hours=24&production_window_hours=720"
        ),
        _safe_proxy("/api/admin/customer-value/evidence?window_days=90"),
        _safe_proxy("/api/admin/autonomy/evidence?window_days=30&limit=100"),
        _safe_proxy("/api/admin/events/dlq/health"),
        _safe_proxy("/api/xcmax/strategic/decisions?limit=100"),
        _safe_proxy("/api/xcmax/strategic/council/status?limit=20"),
        _safe_proxy("/api/public/action-board"),
    )

    action_board_data = (
        action_board.get("data") if isinstance(action_board.get("data"), dict) else action_board
    )
    if not isinstance(action_board_data, dict):
        action_board_data = {}
    action_board_goal_section = action_board_data.get("goals")
    action_board_goal_summary = (
        action_board_goal_section.get("summary")
        if isinstance(action_board_goal_section, dict)
        else None
    )
    action_board_goals = (
        action_board_goal_summary if isinstance(action_board_goal_summary, dict) else {}
    )

    try:
        knowledge = _knowledge_runtime_snapshot()
    except RECOVERABLE_ERRORS as exc:
        logger.warning("founder autonomy knowledge evidence unavailable: %s", exc)
        knowledge = {}
    try:
        pending_actions = list_pending_actions()
    except RECOVERABLE_ERRORS as exc:
        logger.warning("founder autonomy approvals unavailable: %s", exc)
        pending_actions = []

    closure = build_ops_closure_status(remote_health)
    snapshot = build_founder_autonomy_snapshot(
        runtime=runtime,
        closure=closure,
        approvals={"local_pending": len(pending_actions)},
        knowledge=knowledge,
        goals=action_board_goals,
        customer_value=customer_value,
        autonomy_audit=autonomy_audit,
        employee_autonomy=employee_autonomy,
        employee_capability=employee_capability,
        dead_letters=dead_letters,
        strategic_decisions=strategic_decisions,
        strategic_council=strategic_council,
        surfaces={
            "founder_cockpit": True,
            "approval_center": True,
            "knowledge_base": True,
            "ai_employees": True,
            "goals": bool(action_board_goals),
            "loops": True,
        },
    )
    publication = write_public_founder_autonomy_projection(snapshot)
    if not publication.get("ok"):
        logger.warning(
            "founder autonomy public projection not fully published written=%s errors=%s",
            publication.get("written"),
            publication.get("errors"),
        )
    return snapshot, publication


@router.get("/ops/founder-autonomy", response_model=None)
async def ops_founder_autonomy(request: Request):
    """Aggregate the seven dimensions from live evidence for a signed-in admin."""
    gate = admin_routes._require_market_admin_session(request)
    if gate is not None:
        return gate
    snapshot, _publication = await _build_and_publish_founder_autonomy(
        request,
        require_admin_session=True,
    )
    return {"success": True, "data": snapshot}


@router.post("/ops/strategic-plan", response_model=None)
async def ops_strategic_plan(request: Request):
    """LLM 季度目标分解：回答「这个季度做哪三个功能」。

    Body JSON:
      - goal: 战略目标文本（可选）
      - critique: 反思修正意见（可选）
      - quarter: 如 2026-Q3（可选）
      - use_llm: 默认 true；false 强制启发式
      - persist: 默认 true
    """
    gate = admin_routes._require_market_admin_session(request)
    if gate is not None:
        return gate
    try:
        body = await request.json()
    except RECOVERABLE_ERRORS:
        body = {}
    if not isinstance(body, dict):
        body = {}
    from app.application.autonomy.strategic_plan_app_service import build_quarterly_plan

    plan = await build_quarterly_plan(
        body.get("goal"),
        critique=body.get("critique"),
        quarter=body.get("quarter"),
        use_llm=bool(body.get("use_llm", True)),
        persist=bool(body.get("persist", True)),
    )
    return {"success": True, "data": plan}


@router.get("/ops/strategic-plan/latest", response_model=None)
async def ops_strategic_plan_latest(request: Request):
    """读取最近一次季度战略计划。"""
    gate = admin_routes._require_market_admin_session(request)
    if gate is not None:
        return gate
    from app.application.autonomy.strategic_plan_app_service import latest_plan

    plan = latest_plan()
    return {"success": True, "data": plan}


@router.post("/ops/founder-autonomy/refresh-internal", response_model=None)
async def ops_founder_autonomy_refresh_internal(request: Request):
    """Refresh the public projection with independent machine and market credentials."""
    expected = str(
        os.environ.get("AUTONOMY_WEBHOOK_TOKEN")
        or os.environ.get("MODSTORE_OPS_INGEST_TOKEN")
        or ""
    ).strip()
    supplied = str(request.headers.get("X-Autonomy-Token") or "").strip()
    if not expected or not supplied or not hmac.compare_digest(expected, supplied):
        return JSONResponse(
            {"success": False, "message": "invalid autonomy webhook token"},
            status_code=401,
        )
    authorization = str(request.headers.get("Authorization") or "").strip()
    if not authorization.lower().startswith("bearer "):
        return JSONResponse(
            {"success": False, "message": "market admin bearer is required"},
            status_code=401,
        )

    snapshot, publication = await _build_and_publish_founder_autonomy(
        request,
        require_admin_session=False,
    )
    if not publication.get("ok"):
        return JSONResponse(
            {
                "success": False,
                "message": "founder autonomy projection was not fully published",
                "data": snapshot,
                "publication": publication,
            },
            status_code=503,
        )
    return {"success": True, "data": snapshot, "publication": publication}
