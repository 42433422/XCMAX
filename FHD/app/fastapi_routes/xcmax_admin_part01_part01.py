# mypy: disable-error-code="no-any-return, valid-type"
"""Implementation extracted from the public facade module."""

from __future__ import annotations

import importlib


def _facade():
    return importlib.import_module("app.fastapi_routes.xcmax_admin")


@_facade().router.get("/admin/autonomy/audit-log", response_model=None)
async def autonomy_audit_log(
    request: _facade().Request,
    limit: int = _facade().Query(default=100, ge=1, le=1000),
    risk_level: str | None = None,
    decision: str | None = None,
    veto_only: bool = False,
    since: str | None = None,
    days: int = _facade().Query(default=1, ge=1, le=3650),
):
    """Query the append-only autonomy decision and veto trail."""
    gate = _facade()._require_market_admin_session(request)
    if gate is not None:
        return gate
    from app.application.autonomy.audit_log import list_autonomy_audit, summarize_autonomy_audit
    from app.domain.autonomy.operating_metrics import evaluate_autonomy_window

    items = list_autonomy_audit(
        limit=limit, risk_level=risk_level, decision=decision, veto_only=veto_only, since=since
    )
    summary = summarize_autonomy_audit(days=days)
    return {
        "success": True,
        "append_only": True,
        "items": items,
        "count": len(items),
        "summary": summary,
        "evaluation": evaluate_autonomy_window(days, summary=summary) if days in {30, 90} else None,
    }


@_facade().router.get("/admin/autonomy/actions/pending", response_model=None)
async def admin_pending_autonomy_actions(request: _facade().Request):
    """管理端审批中心：用管理员会话拉取待办（勿走 webhook token）。"""
    gate = _facade()._require_market_admin_session(request)
    if gate is not None:
        return gate
    from app.application.autonomy.approval_resume import list_pending_actions

    items = list_pending_actions()
    return {"ok": True, "count": len(items), "items": items}


@_facade().router.post("/admin/autonomy/actions/{action_id}/resume", response_model=None)
async def admin_resume_autonomy_action(action_id: str, request: _facade().Request):
    gate = _facade()._require_market_admin_session(request)
    if gate is not None:
        return gate
    from app.application.autonomy.approval_resume import (
        ApprovalStateError,
        admin_execution_contract,
        get_action_state,
        resume_action,
    )

    try:
        body = await request.json()
    except _facade().RECOVERABLE_ERRORS:
        body = {}
    if not isinstance(body, dict):
        body = {}
    approver = _facade()._admin_approver_from_session(request)
    current = get_action_state(action_id)
    if current is None:
        return _facade().JSONResponse(
            {"ok": False, "code": "action_not_found", "message": "待审批动作不存在"},
            status_code=409,
        )
    contract = admin_execution_contract(current)
    if not contract["admin_execution_ready"]:
        return _facade().JSONResponse(
            {
                "ok": False,
                "code": str(contract["execution_mode"]),
                "message": str(contract["execution_guidance"]),
                "action": {**current, **contract},
            },
            status_code=409,
        )
    try:
        item = resume_action(
            action_id,
            approver=approver,
            approval_id=str(body.get("approval_id") or ""),
            defer_execution=False,
        )
    except ApprovalStateError as exc:
        return _facade().JSONResponse({"ok": False, "message": str(exc)}, status_code=409)
    if str(item.get("state") or "") != "executed":
        return _facade().JSONResponse(
            {
                "ok": False,
                "code": "execution_failed",
                "message": "审批已记录，但动作执行失败；请查看执行结果后修复。",
                "action": item,
            },
            status_code=502,
        )
    return {"ok": True, "execution_dispatched": True, "action": item}


@_facade().router.post("/admin/autonomy/actions/{action_id}/reject", response_model=None)
async def admin_reject_autonomy_action(action_id: str, request: _facade().Request):
    gate = _facade()._require_market_admin_session(request)
    if gate is not None:
        return gate
    from app.application.autonomy.approval_resume import ApprovalStateError, reject_action

    try:
        body = await request.json()
    except _facade().RECOVERABLE_ERRORS:
        body = {}
    if not isinstance(body, dict):
        body = {}
    approver = _facade()._admin_approver_from_session(request)
    if not approver:
        return _facade().JSONResponse(
            {"ok": False, "message": "approver is required"}, status_code=400
        )
    try:
        item = reject_action(
            action_id,
            approver=approver,
            reason=str(body.get("reason") or ""),
            approval_id=str(body.get("approval_id") or ""),
        )
    except ApprovalStateError as exc:
        return _facade().JSONResponse({"ok": False, "message": str(exc)}, status_code=409)
    return {"ok": True, "action": item}


@_facade().router.get("/admin/autonomy/health", response_model=None)
async def admin_autonomy_health(request: _facade().Request):
    """Admin-session health for autonomy approval service (avoids /api/ops vite→modstore proxy)."""
    gate = _facade()._require_market_admin_session(request)
    if gate is not None:
        return gate
    return {"ok": True, "service": "ops-autonomy-approval", "via": "xcmax-admin"}


@_facade().router.get("/admin/autonomy/overview", response_model=None)
async def admin_autonomy_overview(request: _facade().Request):
    """One-shot autonomy dashboard payload for the admin console."""
    gate = _facade()._require_market_admin_session(request)
    if gate is not None:
        return gate
    from app.application import self_maintenance_app_service as sm_svc
    from app.application.autonomy.admin_overview import (
        closure_gap_count,
        extract_loop_run_summary,
        list_deploy_events,
        operating_metrics_windows,
    )
    from app.application.autonomy.approval_resume import list_pending_actions
    from app.application.autonomy.audit_log import list_autonomy_audit, summarize_autonomy_audit
    from app.application.ops_closure_status import build_ops_closure_status

    audit_items = list_autonomy_audit(limit=20)
    audit_summary = summarize_autonomy_audit(days=30)
    metrics = operating_metrics_windows()
    deploy = list_deploy_events(limit=20)
    pending = list_pending_actions()
    runtime: dict[str, _facade().Any] = {}
    try:
        runtime = await sm_svc.get_runtime_status_local(limit=40)
    except _facade().RECOVERABLE_ERRORS as exc:
        _facade().logger.warning("autonomy overview runtime status failed: %s", exc)
        runtime = {"ok": False, "error": str(exc)}
    closure: dict[str, _facade().Any] = {}
    try:
        closure = {
            "success": True,
            "data": build_ops_closure_status(await _facade()._remote_duty_health(request)),
        }
    except _facade().RECOVERABLE_ERRORS as exc:
        _facade().logger.warning("autonomy overview closure status failed: %s", exc)
        closure = {"success": False, "error": str(exc)}
    return {
        "ok": True,
        "health": {"ok": True, "service": "ops-autonomy-approval"},
        "pending": {"count": len(pending), "items": pending[:20]},
        "audit": {"items": audit_items, "count": len(audit_items), "summary": audit_summary},
        "loop": extract_loop_run_summary(runtime if isinstance(runtime, dict) else {}),
        "runtime": runtime,
        "closure": {"gap_count": closure_gap_count(closure), "payload": closure},
        "deploy_events": deploy,
        "operating_metrics": metrics,
    }


@_facade().router.get("/admin/autonomy/deploy-events", response_model=None)
async def admin_autonomy_deploy_events(
    request: _facade().Request,
    limit: int = _facade().Query(default=20, ge=1, le=200),
    since_cursor: str | None = None,
):
    gate = _facade()._require_market_admin_session(request)
    if gate is not None:
        return gate
    from app.application.autonomy.admin_overview import list_deploy_events

    data = list_deploy_events(limit=limit, since_cursor=since_cursor)
    return {"ok": True, **data}


@_facade().router.get("/admin/autonomy/operating-metrics", response_model=None)
async def admin_autonomy_operating_metrics(request: _facade().Request):
    gate = _facade()._require_market_admin_session(request)
    if gate is not None:
        return gate
    from app.application.autonomy.admin_overview import operating_metrics_windows

    return {"ok": True, **operating_metrics_windows()}


@_facade().router.get("/admin/autonomy/github-items", response_model=None)
async def admin_autonomy_github_items(
    request: _facade().Request, limit: int = _facade().Query(default=30, ge=1, le=100)
):
    gate = _facade()._require_market_admin_session(request)
    if gate is not None:
        return gate
    from app.application.autonomy.admin_overview import list_github_human_items

    return {"ok": True, **list_github_human_items(limit=limit)}


@_facade().router.get("/admin/autonomy/cross-tier-gate", response_model=None)
async def admin_autonomy_cross_tier_gate(request: _facade().Request):
    gate = _facade()._require_market_admin_session(request)
    if gate is not None:
        return gate
    from app.application.autonomy.admin_overview import evaluate_cross_tier_gate_snapshot

    return {"ok": True, **evaluate_cross_tier_gate_snapshot(None)}


@_facade().router.get("/admin/autonomy/audit-cross-tier", response_model=None)
async def admin_autonomy_audit_cross_tier(
    request: _facade().Request,
    tier: str = _facade().Query(default="server"),
    limit: int = _facade().Query(default=50, ge=1, le=300),
):
    gate = _facade()._require_market_admin_session(request)
    if gate is not None:
        return gate
    from app.application.autonomy.admin_overview import read_cross_tier_audit

    return {"ok": True, **read_cross_tier_audit(tier=tier, limit=limit)}


@_facade().router.post("/admin/autonomy/self-maintenance/run", response_model=None)
async def admin_force_self_maintenance_run(request: _facade().Request):
    """Admin break-glass: force one self-maintenance loop via local MODstore."""
    gate = _facade()._require_market_admin_session(request)
    if gate is not None:
        return gate
    from app.application import self_maintenance_app_service as sm_svc

    try:
        body = await request.json()
    except _facade().RECOVERABLE_ERRORS:
        body = {}
    if not isinstance(body, dict):
        body = {}
    reason = (
        str(body.get("reason") or "admin_console_force_run").strip() or "admin_console_force_run"
    )
    try:
        result = await sm_svc.force_run_local(reason=reason)
        return {"ok": True, "result": result}
    except _facade().RECOVERABLE_ERRORS as exc:
        _facade().logger.warning("admin force self-maintenance failed: %s", exc)
        return _facade().JSONResponse({"ok": False, "message": str(exc)}, status_code=502)


def _release_train_snapshot() -> dict[str, _facade().Any]:
    """读取 release_train SSOT；优先 modstore 模块，回退 FHD/config JSON。"""
    from pathlib import Path

    def _default_snapshot(*, note: str | None = None) -> dict[str, _facade().Any]:
        data: dict[str, _facade().Any] = {
            "epoch": "1.0.0.0",
            "current": "1.0.0.1",
            "started_at": "2026-06-04",
            "day_index": 0,
        }
        if note:
            data["note"] = note
        return data

    def _from_file(path: Path) -> dict[str, _facade().Any]:
        if not path.is_file():
            return _default_snapshot(note="ssot missing")
        try:
            raw = _facade().json.loads(path.read_text(encoding="utf-8"))
            if isinstance(raw, dict):
                return raw
        except _facade().RECOVERABLE_ERRORS as exc:
            _facade().logger.warning("release-train json read failed: %s", exc)
        return _default_snapshot()

    mono = (_facade().os.environ.get("XCMAX_MONOREPO_ROOT") or "").strip()
    if mono:
        path = Path(mono).expanduser().resolve() / "FHD" / "config" / "release_train.json"
        return _from_file(path)
    try:
        from modstore_server.release_train import snapshot_public

        return _facade().cast("dict[str, Any]", snapshot_public())
    except _facade().RECOVERABLE_ERRORS:
        pass
    path = Path(__file__).resolve().parents[2] / "config" / "release_train.json"
    return _from_file(path)
