# mypy: disable-error-code="valid-type, attr-defined, no-any-return"
# isort: skip_file
"""Implementation extracted from the public facade module."""

from __future__ import annotations

from modstore_server.operational_errors import RECOVERABLE_ERRORS
import importlib


def _facade():
    return importlib.import_module("modstore_server.workflow_api")


@_facade().router.post(
    "/{workflow_id}/versions/{version_id}/rollback",
    summary="回滚到指定版本（重建节点/边，不动触发器）",
)
async def rollback_workflow_version(
    workflow_id: int,
    version_id: int,
    db: _facade().Session = _facade().Depends(_facade().get_db),
    user: _facade().User = _facade().Depends(_facade()._get_current_user),
):
    workflow = (
        db.query(_facade().Workflow)
        .filter(_facade().Workflow.id == workflow_id, _facade().Workflow.user_id == user.id)
        .first()
    )
    if not workflow:
        raise _facade().HTTPException(404, "工作流不存在")
    target = (
        db.query(_facade().WorkflowVersion)
        .filter(
            _facade().WorkflowVersion.id == version_id,
            _facade().WorkflowVersion.workflow_id == workflow_id,
        )
        .first()
    )
    if not target:
        raise _facade().HTTPException(404, "版本不存在")
    try:
        snapshot = _facade().json.loads(target.graph_snapshot or "{}")
    except _facade().json.JSONDecodeError as exc:
        raise _facade().HTTPException(500, f"版本 snapshot 损坏: {exc}") from exc
    _facade()._restore_workflow_from_snapshot(db, workflow, snapshot)
    db.query(_facade().WorkflowVersion).filter(
        _facade().WorkflowVersion.workflow_id == workflow_id,
        _facade().WorkflowVersion.is_current.is_(True),
    ).update({_facade().WorkflowVersion.is_current: False})
    target.is_current = True
    db.commit()
    return {"ok": True, "version_no": target.version_no}


@_facade().router.get("/executions/{execution_id}", summary="获取执行详情")
async def get_execution_detail(
    execution_id: int,
    db: _facade().Session = _facade().Depends(_facade().get_db),
    user: _facade().User = _facade().Depends(_facade()._get_current_user),
):
    """获取工作流执行的详细信息"""
    execution = (
        db.query(_facade().WorkflowExecution)
        .join(_facade().Workflow)
        .filter(
            _facade().WorkflowExecution.id == execution_id,
            _facade().Workflow.user_id == user.id,
        )
        .first()
    )
    if not execution:
        raise _facade().HTTPException(404, "执行记录不存在")
    return {
        "id": execution.id,
        "workflow_id": execution.workflow_id,
        "status": execution.status,
        "input_data": _facade().json.loads(execution.input_data or "{}"),
        "output_data": _facade().json.loads(execution.output_data or "{}"),
        "error_message": execution.error_message,
        "started_at": execution.started_at.isoformat(),
        "completed_at": execution.completed_at.isoformat() if execution.completed_at else None,
    }


@_facade().workflow_hooks_router.post(
    "/webhook/{trigger_key}",
    summary="公开 Webhook 触发工作流（需在触发器 config 配置 secret）",
)
async def public_webhook_run_workflow(
    trigger_key: str,
    request: _facade().Request,
    db: _facade().Session = _facade().Depends(_facade().get_db),
):
    """外部系统无需用户 JWT：匹配 ``WorkflowTrigger.trigger_key``，校验 ``X-Workflow-Secret`` 与触发器
    ``config_json.secret`` 一致后执行；请求 JSON 作为 ``input_data``。
    """
    key = (trigger_key or "").strip()
    trig = (
        db.query(_facade().WorkflowTrigger)
        .filter(
            _facade().WorkflowTrigger.trigger_key == key,
            _facade().WorkflowTrigger.trigger_type == "webhook",
            _facade().WorkflowTrigger.is_active.is_(True),
        )
        .first()
    )
    if not trig:
        raise _facade().HTTPException(404, "触发器不存在或未启用")
    cfg: _facade().Dict[str, _facade().Any] = {}
    try:
        raw_cfg = _facade().json.loads(trig.config_json or "{}")
        if isinstance(raw_cfg, dict):
            cfg = raw_cfg
    except _facade().json.JSONDecodeError:
        cfg = {}
    secret = str(cfg.get("secret") or "").strip()
    if secret:
        hdr = (request.headers.get("X-Workflow-Secret") or "").strip()
        if not _facade().hmac.compare_digest(hdr, secret):
            raise _facade().HTTPException(403, "Webhook secret mismatch")
    elif _facade().os.environ.get("MODSTORE_REQUIRE_WEBHOOK_SECRET", "").strip().lower() in (
        "1",
        "true",
        "yes",
    ):
        raise _facade().HTTPException(
            400,
            "请在触发器 config 中配置 secret，或关闭 MODSTORE_REQUIRE_WEBHOOK_SECRET",
        )
    try:
        body = await request.json()
    except RECOVERABLE_ERRORS:
        body = {}
    if not isinstance(body, dict):
        body = {}
    try:
        return _facade().run_workflow_for_trigger(
            workflow_id=int(trig.workflow_id),
            user_id=int(trig.user_id),
            input_data=body,
        )
    except RECOVERABLE_ERRORS as e:
        raise _facade().HTTPException(500, str(e)) from e
