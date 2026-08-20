# mypy: disable-error-code="valid-type, attr-defined, no-any-return"
# isort: skip_file
"""Implementation extracted from the public facade module."""

from __future__ import annotations

from modstore_server.operational_errors import RECOVERABLE_ERRORS
import importlib
from modstore_server.workflow_api_part02_part01_part01 import PublishVersionBody
from modstore_server.workflow_api_part02_part01_part01 import WorkflowExecuteBody
from modstore_server.workflow_api_part02_part01_part01 import WorkflowTriggerBody


def _facade():
    return importlib.import_module("modstore_server.workflow_api")


@_facade().router.post("/{workflow_id}/execute", summary="执行工作流")
async def execute_workflow(
    workflow_id: int,
    body: WorkflowExecuteBody,
    db: _facade().Session = _facade().Depends(_facade().get_db),
    user: _facade().User = _facade().Depends(_facade()._get_current_user),
):
    """生产执行：结果写入 workflow_executions（引擎内不落重复执行行）。"""
    from modstore_server.workflow_engine import execute_workflow as engine_execute

    workflow = (
        db.query(_facade().Workflow)
        .filter(_facade().Workflow.id == workflow_id, _facade().Workflow.user_id == user.id)
        .first()
    )
    if not workflow:
        raise _facade().HTTPException(404, "工作流不存在")
    if not workflow.is_active:
        raise _facade().HTTPException(400, "工作流未激活")
    execution = _facade().WorkflowExecution(
        workflow_id=workflow_id,
        user_id=user.id,
        status="running",
        input_data=_facade().json.dumps(body.input_data or {}),
    )
    db.add(execution)
    db.commit()
    db.refresh(execution)
    sf = _facade().get_session_factory()
    with sf() as qdb:
        _facade().require_llm_credit(qdb, user.id, 1)
    failure_message: _facade().Optional[str] = None
    try:
        output_data = engine_execute(workflow_id, body.input_data or {}, user_id=user.id)
        execution.status = "completed"
        execution.output_data = _facade().json.dumps(output_data)
        execution.completed_at = _facade().datetime.now(_facade().timezone.utc)
        try:
            with sf() as qdb2:
                _facade().consume_llm_credit(qdb2, user.id, 1)
        except RECOVERABLE_ERRORS:
            pass
    except RECOVERABLE_ERRORS as e:
        failure_message = str(e)
        execution.status = "failed"
        execution.error_message = failure_message
        execution.completed_at = _facade().datetime.now(_facade().timezone.utc)
    db.commit()
    try:
        from modstore_server import webhook_dispatcher
        from modstore_server.eventing.contracts import (
            WORKFLOW_EXECUTION_COMPLETED,
            WORKFLOW_EXECUTION_FAILED,
        )

        event_name = WORKFLOW_EXECUTION_FAILED if failure_message else WORKFLOW_EXECUTION_COMPLETED
        webhook_dispatcher.publish_event(
            event_name,
            aggregate_id=str(execution.id),
            data={
                "workflow_id": int(workflow_id),
                "execution_id": int(execution.id),
                "user_id": int(user.id),
                "status": execution.status,
                "error": failure_message or "",
                "started_at": execution.started_at.isoformat(),
                "completed_at": (
                    execution.completed_at.isoformat() if execution.completed_at else ""
                ),
            },
            source="modstore-workflow-api",
        )
    except RECOVERABLE_ERRORS:
        pass
    if failure_message is not None:
        raise _facade().HTTPException(500, failure_message)
    return {
        "id": execution.id,
        "workflow_id": execution.workflow_id,
        "status": execution.status,
        "input_data": _facade().json.loads(execution.input_data),
        "output_data": _facade().json.loads(execution.output_data or "{}"),
        "started_at": execution.started_at.isoformat(),
        "completed_at": execution.completed_at.isoformat() if execution.completed_at else None,
    }


@_facade().router.get("/{workflow_id}/executions", summary="获取工作流执行记录")
async def get_workflow_executions(
    workflow_id: int,
    limit: int = _facade().Query(50, ge=1, le=100),
    offset: int = _facade().Query(0, ge=0),
    db: _facade().Session = _facade().Depends(_facade().get_db),
    user: _facade().User = _facade().Depends(_facade()._get_current_user),
):
    """获取工作流的执行记录"""
    workflow = (
        db.query(_facade().Workflow)
        .filter(_facade().Workflow.id == workflow_id, _facade().Workflow.user_id == user.id)
        .first()
    )
    if not workflow:
        raise _facade().HTTPException(404, "工作流不存在")
    executions = (
        db.query(_facade().WorkflowExecution)
        .filter(_facade().WorkflowExecution.workflow_id == workflow_id)
        .order_by(_facade().WorkflowExecution.started_at.desc())
        .limit(limit)
        .offset(offset)
        .all()
    )
    return [
        {
            "id": e.id,
            "status": e.status,
            "input_data": _facade().json.loads(e.input_data or "{}"),
            "output_data": _facade().json.loads(e.output_data or "{}"),
            "error_message": e.error_message,
            "started_at": e.started_at.isoformat(),
            "completed_at": e.completed_at.isoformat() if e.completed_at else None,
        }
        for e in executions
    ]


@_facade().router.get("/{workflow_id}/triggers", summary="获取工作流触发器")
async def list_workflow_triggers(
    workflow_id: int,
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
    rows = (
        db.query(_facade().WorkflowTrigger)
        .filter(_facade().WorkflowTrigger.workflow_id == workflow_id)
        .all()
    )
    return [
        {
            "id": r.id,
            "trigger_type": r.trigger_type,
            "trigger_key": r.trigger_key,
            "config": _facade().json.loads(r.config_json or "{}"),
            "is_active": r.is_active,
        }
        for r in rows
    ]


@_facade().router.post("/{workflow_id}/triggers", summary="新增工作流触发器")
async def create_workflow_trigger(
    workflow_id: int,
    body: WorkflowTriggerBody,
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
    row = _facade().WorkflowTrigger(
        workflow_id=workflow_id,
        user_id=user.id,
        trigger_type=body.trigger_type.strip().lower(),
        trigger_key=(body.trigger_key or "").strip(),
        config_json=_facade().json.dumps(body.config or {}),
        is_active=body.is_active,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    if (row.trigger_type or "").strip().lower() == "cron":
        from modstore_server.workflow_scheduler import refresh_cron_trigger

        refresh_cron_trigger(row.id)
    return {"id": row.id, "ok": True}


@_facade().router.delete("/{workflow_id}/triggers/{trigger_id}", summary="删除或停用工作流触发器")
async def delete_workflow_trigger(
    workflow_id: int,
    trigger_id: int,
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
    row = (
        db.query(_facade().WorkflowTrigger)
        .filter(
            _facade().WorkflowTrigger.id == trigger_id,
            _facade().WorkflowTrigger.workflow_id == workflow_id,
        )
        .first()
    )
    if not row:
        raise _facade().HTTPException(404, "触发器不存在")
    row.is_active = False
    db.commit()
    from modstore_server.workflow_scheduler import unregister_cron_trigger

    unregister_cron_trigger(trigger_id)
    return {"ok": True}


@_facade().router.post(
    "/{workflow_id}/webhook-run",
    summary="Webhook 方式触发执行工作流（需已配置 webhook 触发器）",
)
async def webhook_run_workflow(
    workflow_id: int,
    body: _facade().Dict[str, _facade().Any],
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
    trig = (
        db.query(_facade().WorkflowTrigger)
        .filter(
            _facade().WorkflowTrigger.workflow_id == workflow_id,
            _facade().WorkflowTrigger.trigger_type == "webhook",
            _facade().WorkflowTrigger.is_active.is_(True),
        )
        .first()
    )
    if not trig:
        raise _facade().HTTPException(400, "该工作流未配置激活的 webhook 触发器")
    try:
        return _facade().run_workflow_for_trigger(
            workflow_id=workflow_id, user_id=user.id, input_data=body or {}
        )
    except RECOVERABLE_ERRORS as e:
        raise _facade().HTTPException(500, str(e)) from e


@_facade().router.post("/{workflow_id}/versions/publish", summary="发布工作流版本（快照当前图）")
async def publish_workflow_version(
    workflow_id: int,
    body: PublishVersionBody,
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
    snapshot = _facade()._serialize_workflow_snapshot(db, workflow)
    if not snapshot["nodes"]:
        raise _facade().HTTPException(400, "当前图为空，无法发布版本")
    last = (
        db.query(_facade().WorkflowVersion)
        .filter(_facade().WorkflowVersion.workflow_id == workflow_id)
        .order_by(_facade().WorkflowVersion.version_no.desc())
        .first()
    )
    next_no = int(last.version_no) + 1 if last else 1
    db.query(_facade().WorkflowVersion).filter(
        _facade().WorkflowVersion.workflow_id == workflow_id,
        _facade().WorkflowVersion.is_current.is_(True),
    ).update({_facade().WorkflowVersion.is_current: False})
    row = _facade().WorkflowVersion(
        workflow_id=workflow_id,
        user_id=user.id,
        version_no=next_no,
        note=(body.note or "").strip(),
        graph_snapshot=_facade().json.dumps(snapshot, ensure_ascii=False),
        is_current=True,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return {
        "id": row.id,
        "version_no": row.version_no,
        "note": row.note,
        "is_current": row.is_current,
        "created_at": row.created_at.isoformat(),
    }


@_facade().router.get("/{workflow_id}/versions", summary="工作流版本列表（按 version_no 倒序）")
async def list_workflow_versions(
    workflow_id: int,
    limit: int = _facade().Query(50, ge=1, le=100),
    offset: int = _facade().Query(0, ge=0),
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
    rows = (
        db.query(_facade().WorkflowVersion)
        .filter(_facade().WorkflowVersion.workflow_id == workflow_id)
        .order_by(_facade().WorkflowVersion.version_no.desc())
        .limit(limit)
        .offset(offset)
        .all()
    )
    return [
        {
            "id": r.id,
            "version_no": r.version_no,
            "note": r.note or "",
            "is_current": bool(r.is_current),
            "created_at": r.created_at.isoformat(),
        }
        for r in rows
    ]


@_facade().router.get(
    "/{workflow_id}/versions/{version_id}",
    summary="工作流版本详情（含 graph_snapshot）",
)
async def get_workflow_version(
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
    row = (
        db.query(_facade().WorkflowVersion)
        .filter(
            _facade().WorkflowVersion.id == version_id,
            _facade().WorkflowVersion.workflow_id == workflow_id,
        )
        .first()
    )
    if not row:
        raise _facade().HTTPException(404, "版本不存在")
    try:
        snapshot = _facade().json.loads(row.graph_snapshot or "{}")
    except _facade().json.JSONDecodeError:
        snapshot = {}
    return {
        "id": row.id,
        "version_no": row.version_no,
        "note": row.note or "",
        "is_current": bool(row.is_current),
        "created_at": row.created_at.isoformat(),
        "graph_snapshot": snapshot,
    }
