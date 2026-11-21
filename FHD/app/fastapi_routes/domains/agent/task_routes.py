"""Durable task-center API routes separated from Agent run execution routes."""

from __future__ import annotations

import asyncio
import json
import logging
import threading
import time
from concurrent.futures import Future, wait
from dataclasses import asdict, replace
from typing import Any, Callable, Generic, TypeVar, cast

from fastapi import APIRouter, Body, Depends, HTTPException, Query
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import ValidationError

from app.application.agent_orchestrator import AgentOrchestrator, get_agent_run_repository
from app.application.agent_orchestrator.run_control import run_operation_lock
from app.application.agent_orchestrator.run_models import utc_now_iso
from app.application.agent_orchestrator.run_repository import AgentRunRepository
from app.application.agent_orchestrator.task_dispatcher import get_agent_task_dispatcher
from app.application.agent_orchestrator.task_execution_repository import (
    get_task_execution_repository,
)
from app.application.agent_orchestrator.task_models import (
    mod_id_of_run,
    task_from_run,
    tenant_id_of_run,
)
from app.application.agent_orchestrator.task_progress import task_progress_snapshot
from app.application.agent_orchestrator.unified_task import (
    UnifiedTaskConflictError,
    UnifiedTaskError,
    create_unified_task,
    task_capabilities,
)
from app.application.enterprise_cognition.service import get_cognition_service
from app.domain.enterprise_cognition.contracts import CognitionRequest
from app.fastapi_routes.domains.agent.route_support import (
    authenticated_runtime_context,
    internal_error_response,
    project_execution_failure,
    public_run_dict,
    run_response,
    scoped_tasks,
    success,
    task_scope_matches,
)
from app.infrastructure.auth.agent_mod_scope import AgentModAuthorizationError
from app.infrastructure.auth.agent_principal import AgentPrincipal, require_agent_principal
from app.infrastructure.auth.agent_stream import StreamAuthorizer, require_stream_authorizer
from app.utils.json_safe import json_safe
from app.utils.operational_errors import RECOVERABLE_ERRORS

logger = logging.getLogger(__name__)
router = APIRouter(tags=["agent"])

# 运行写入时会同步建任务记录，这里只需要为历史运行补建一次。
# 前端每秒轮询列表，若每次都扫描近期载荷会持续占用整核。
_BACKFILL_TTL_SECONDS = 60.0
_STREAM_INTERVAL_SECONDS = 1.0
_SNAPSHOT_TTL_SECONDS = 1.0
_TaskCacheKey = tuple[object, object, str]
_Value = TypeVar("_Value")
# The builder owns a shared Future: even cancellation/termination must release
# its waiters and failed cache slot before the original exception propagates.
_TASK_VIEW_BUILD_FAILURES: tuple[type[BaseException], ...] = (BaseException,)


class _TaskViewCache(Generic[_Value]):
    """Bounded completed values and one in-flight builder per storage/identity key."""

    def __init__(self, ttl: float, capacity: int = 64) -> None:
        self._ttl = ttl
        self._capacity = max(1, capacity)
        self._entries: dict[_TaskCacheKey, tuple[float | None, Future[_Value]]] = {}
        self._lock = threading.Lock()

    def get(self, key: _TaskCacheKey, build: Callable[[], _Value]) -> _Value:
        while True:
            with self._lock:
                now = time.monotonic()
                for expired, (completed, _) in list(self._entries.items()):
                    if completed is not None and now - completed > self._ttl:
                        self._entries.pop(expired)
                cached = self._entries.get(key)
                if cached is not None:
                    future = cached[1]
                    owner = False
                    break
                if len(self._entries) >= self._capacity:
                    completed_key = next(
                        (k for k, (completed, _) in self._entries.items() if completed is not None),
                        None,
                    )
                    if completed_key is not None:
                        self._entries.pop(completed_key)
                if len(self._entries) < self._capacity:
                    future = Future()
                    self._entries[key] = (None, future)
                    owner = True
                    break
                pending = next(iter(self._entries.values()))[1]
            # Pending builders are never evicted: that would permit duplicate work.
            wait((pending,))
        if not owner:
            return future.result()
        try:
            value = build()
        except _TASK_VIEW_BUILD_FAILURES as exc:
            with self._lock:
                self._entries.pop(key)
            future.set_exception(exc)
            raise
        with self._lock:
            self._entries[key] = (time.monotonic(), future)
        future.set_result(value)
        return value


_BACKFILL_DONE = _TaskViewCache[None](_BACKFILL_TTL_SECONDS)
_SNAPSHOTS = _TaskViewCache[str](_SNAPSHOT_TTL_SECONDS)


def _task_view_key(repository: AgentRunRepository, principal: AgentPrincipal) -> _TaskCacheKey:
    # A desktop repository can keep its identity while its underlying bind changes.
    return (
        repository,
        repository.storage_identity(),
        json.dumps(asdict(principal), ensure_ascii=False, sort_keys=True),
    )


def _cached_task_snapshot(key: _TaskCacheKey, build: Callable[[], str]) -> str:
    return _SNAPSHOTS.get(key, build)


def _backfill_task_records(repository: AgentRunRepository, principal: AgentPrincipal) -> None:
    def backfill() -> None:
        known = repository.task_keys(user_id=principal.user_id)
        for run_id, task_id, tenant_id in repository.recent_task_refs(
            user_id=principal.user_id, tenant_id=principal.tenant_id, limit=200
        ):
            if not task_id or tenant_id != principal.tenant_id or (tenant_id, task_id) in known:
                continue
            run = repository.get(run_id)
            if (
                run is not None
                and run.user_id == principal.user_id
                and tenant_id_of_run(run) == principal.tenant_id
            ):
                repository.save_task(task_from_run(run))
                known.add((tenant_id, task_id))

    try:
        _BACKFILL_DONE.get(_task_view_key(repository, principal), backfill)
    except RECOVERABLE_ERRORS:
        pass


def _task_envelope(
    orchestrator: AgentOrchestrator,
    task: Any,
    *,
    include_runs: bool = True,
    executions: dict[str, Any] | None = None,
    viewer: AgentPrincipal | None = None,
) -> dict[str, Any]:
    if include_runs:
        runs = [
            run
            for run in orchestrator.list_task_runs(user_id=task.user_id, task_id=task.task_id)
            if tenant_id_of_run(run) == task.tenant_id
        ]
        active = next((run for run in runs if run.run_id == task.active_run_id), None)
        active = active or (runs[-1] if runs else None)
    else:
        active = orchestrator.get_run(task.active_run_id) if task.active_run_id else None
        if (
            active is None
            or active.user_id != task.user_id
            or tenant_id_of_run(active) != task.tenant_id
        ):
            active = None
        runs = []
    if executions is None:
        executions = get_task_execution_repository().list_for_run_ids(
            [run.run_id for run in runs] or ([active.run_id] if active is not None else [])
        )
    execution = None
    if active is not None:
        execution = executions.get(active.run_id)
        task = replace(
            task,
            metadata={**task.metadata, "progress": task_progress_snapshot(active, viewer=viewer)},
        )
        active = project_execution_failure(active, execution)
    payload = project_execution_failure(task, execution).to_dict()
    payload["runs"] = [
        public_run_dict(
            project_execution_failure(run, executions.get(run.run_id)),
            read_run=orchestrator.get_run,
        )
        for run in runs
    ]
    payload["active_run"] = (
        public_run_dict(active, read_run=orchestrator.get_run) if active is not None else None
    )
    payload["capabilities"] = task_capabilities(active) if active is not None else {}
    command = orchestrator.latest_task_control(active.run_id) if active is not None else None
    payload["control_command"] = command.to_dict() if command is not None else None
    payload["execution"] = execution.to_dict() if execution is not None else None
    return cast("dict[str, Any]", payload)


def _execution_map(tasks: list[Any]) -> dict[str, Any]:
    run_ids = [str(task.active_run_id or "") for task in tasks if task.active_run_id]
    return get_task_execution_repository().list_for_run_ids(run_ids)


def _task_stream_envelope(task: Any, executions: dict[str, Any]) -> dict[str, Any]:
    execution = executions.get(str(task.active_run_id or ""))
    payload = project_execution_failure(task, execution).to_dict()
    payload.update(
        {
            "runs": [],
            "active_run": None,
            "capabilities": {},
            "control_command": None,
            "execution": execution.to_dict() if execution is not None else None,
        }
    )
    return cast("dict[str, Any]", payload)


def _task_progress_overview(tasks: list[Any]) -> dict[str, int]:
    executions = _execution_map(tasks)
    snapshots = [_task_stream_envelope(task, executions) for task in tasks]
    percents: list[int] = []
    for item in snapshots:
        try:
            value = int((item.get("progress") or {}).get("percent") or 0)
        except (TypeError, ValueError):
            value = 0
        percents.append(max(0, min(100, value)))
    return {
        "task_count": len(snapshots),
        "active_count": sum(
            str(item.get("status") or "") in {"queued", "planning", "running", "retrying", "paused"}
            for item in snapshots
        ),
        "attention_count": sum(
            str(item.get("status") or "") in {"waiting_user", "blocked", "failed"}
            for item in snapshots
        ),
        "completed_count": sum(str(item.get("status") or "") == "completed" for item in snapshots),
        "overall_percent": round(sum(percents) / len(percents)) if percents else 0,
    }


@router.get("/api/agent/tasks", response_model=None)
def list_agent_tasks(
    limit: int = Query(default=50, ge=1, le=200),
    include_archived: bool = Query(default=False),
    principal: AgentPrincipal = Depends(require_agent_principal),
) -> dict[str, Any] | JSONResponse:
    try:
        repository = get_agent_run_repository()
        orchestrator = AgentOrchestrator(repository=repository)
        _backfill_task_records(repository, principal)
        tasks = scoped_tasks(
            orchestrator,
            principal=principal,
            limit=limit,
            include_archived=include_archived,
        )
        executions = _execution_map(tasks)
        return success(
            [
                _task_envelope(
                    orchestrator,
                    task,
                    include_runs=False,
                    executions=executions,
                    viewer=principal,
                )
                for task in tasks
            ],
            count=len(tasks),
        )
    except RECOVERABLE_ERRORS:
        return internal_error_response("list agent tasks")


def _stored_task_replay(run: Any) -> tuple[dict[str, Any], int] | None:
    context = getattr(run, "metadata", {}) or {}
    runtime = context.get("runtime_context") if isinstance(context, dict) else {}
    checkpoint = runtime.get("cross_module_checkpoint") if isinstance(runtime, dict) else {}
    if not isinstance(checkpoint, dict):
        return None
    from app.application.agent_orchestrator.cross_module_chain import (
        load_cross_module_http_result,
    )

    stored = load_cross_module_http_result(
        str(checkpoint.get("tenant_id") or ""),
        str(checkpoint.get("idempotency_key") or ""),
    )
    if stored is None:
        return None
    return dict(stored["body"]), int(stored.get("http_status") or 200)


@router.get("/api/agent/task-runtime", response_model=None)
def get_agent_task_runtime(
    principal: AgentPrincipal = Depends(require_agent_principal),
) -> dict[str, Any] | JSONResponse:
    try:
        snapshot = get_agent_task_dispatcher().snapshot()
        orchestrator = AgentOrchestrator()
        active_count = 0
        for item in cast(list[dict[str, Any]], snapshot["active"]):
            run = orchestrator.get_run(str(item["run_id"]))
            if (
                run is not None
                and run.user_id == principal.user_id
                and tenant_id_of_run(run) == principal.tenant_id
                and mod_id_of_run(run)
                == str((principal.mod_authorization or {}).get("mod_id") or "")
            ):
                active_count += 1
        tasks = scoped_tasks(
            AgentOrchestrator(),
            principal=principal,
            limit=200,
            include_archived=False,
        )
        executor = {}
        if principal.is_admin:
            import socket

            from app.infrastructure.workspace import workspace_root

            executor = {
                "executor": {
                    "host": socket.gethostname(),
                    "workspace_root": str(workspace_root()),
                    "engine": "langgraph",
                }
            }
        return success(
            {
                "running": bool(snapshot["running"]),
                "max_workers": int(cast(Any, snapshot["max_workers"])),
                "active_count": active_count,
                "progress": _task_progress_overview(tasks),
                **executor,
            }
        )
    except RECOVERABLE_ERRORS:
        return internal_error_response("get agent task runtime")


@router.post("/api/agent/tasks", response_model=None)
def create_agent_task(
    body: dict[str, Any] = Body(default_factory=dict),
    principal: AgentPrincipal = Depends(require_agent_principal),
) -> dict[str, Any] | JSONResponse:
    data = body or {}
    params = data.get("params") or {}
    runtime_context_raw = data.get("runtime_context") or {}
    if not isinstance(params, dict) or not isinstance(runtime_context_raw, dict):
        return JSONResponse(
            {"success": False, "message": "params 与 runtime_context 必须是对象"},
            status_code=400,
        )
    runtime_context = authenticated_runtime_context(runtime_context_raw, principal)
    try:
        if (
            runtime_context.get("source") == "admin_employee_workspace"
            and data.get("tool_id") == "employee"
        ):
            from app.application.employee_runtime.loader import candidate_pack_ids
            from app.application.employee_runtime.tool_scope import host_employee_denial

            employee_input = params.get("input")
            denial = host_employee_denial(
                candidate_pack_ids(str(params.get("employee_id") or params.get("pack_id") or "")),
                employee_input if isinstance(employee_input, dict) else {},
                runtime_context,
            )
            if denial:
                return JSONResponse(
                    {
                        "success": False,
                        "message": denial["error"],
                        "error_code": denial["error_code"],
                    },
                    status_code=403,
                )
        task_id = str(data.get("task_id") or "").strip()
        if not task_id or len(task_id) > 160 or "/" in task_id:
            return JSONResponse(
                {
                    "success": False,
                    "message": "task_id 不能为空、不能含 /，且长度不能超过 160",
                },
                status_code=400,
            )
        message = str(data.get("message") or data.get("title") or "")
        with run_operation_lock(f"task:{principal.user_id}:{task_id}"):
            result = create_unified_task(
                orchestrator=AgentOrchestrator(),
                user_id=principal.user_id,
                task_id=task_id,
                title=str(data.get("title") or ""),
                message=message,
                tool_id=str(data.get("tool_id") or ""),
                action=str(data.get("action") or ""),
                params=params,
                runtime_context=runtime_context,
            )
            from app.application.agent_orchestrator.cross_module_chain import (
                begin_cross_module_http,
                is_cross_module_client_task,
            )

            if not result.deduplicated and is_cross_module_client_task(message, params):
                begin_cross_module_http(
                    AgentOrchestrator(),
                    result.run,
                    params=params,
                    runtime_context=runtime_context,
                )
                refreshed = AgentOrchestrator().get_run(result.run.run_id)
                if refreshed is not None:
                    result = type(result)(run=refreshed, deduplicated=False)
            else:
                from app.application.agent_orchestrator.cross_module_chain import (
                    project_rejected_approval,
                )

                projected = project_rejected_approval(result.run)
                replay = _stored_task_replay(projected)
                if result.deduplicated and replay is not None:
                    body, status_code = replay
                    body["deduplicated"] = True
                    body["idempotent_replay"] = True
                    return JSONResponse(body, status_code=status_code)
                result = type(result)(run=projected, deduplicated=result.deduplicated)
        response = run_response(result.run, principal=principal)
        response["deduplicated"] = result.deduplicated
        accepted = {"queued", "waiting_user", "waiting_approval"}
        return JSONResponse(response, status_code=202 if result.run.status in accepted else 200)
    except UnifiedTaskConflictError:
        return JSONResponse({"success": False, "message": "任务状态冲突"}, status_code=409)
    except UnifiedTaskError as exc:
        return JSONResponse(
            {"success": False, "message": str(exc) or "任务参数无效"}, status_code=400
        )
    except RuntimeError:
        error_response = internal_error_response("create agent task")
        error_response.status_code = 503
        return error_response
    except RECOVERABLE_ERRORS:
        return internal_error_response("create agent task")


@router.get("/api/agent/tasks/events/stream", response_model=None)
async def stream_agent_tasks(
    once: bool = Query(default=False),
    principal: AgentPrincipal = Depends(require_agent_principal),
    authorize: StreamAuthorizer = Depends(require_stream_authorizer),
) -> StreamingResponse:
    repository = get_agent_run_repository()
    orchestrator = AgentOrchestrator(repository=repository)

    def encode_snapshot() -> str:
        tasks = scoped_tasks(
            orchestrator,
            principal=principal,
            limit=200,
            include_archived=False,
        )
        executions = _execution_map(tasks)
        snapshot = [_task_stream_envelope(task, executions) for task in tasks]
        return json.dumps(json_safe(snapshot), ensure_ascii=False, sort_keys=True)

    def cached_snapshot() -> str:
        return _cached_task_snapshot(_task_view_key(repository, principal), encode_snapshot)

    async def event_stream():
        previous = ""
        deadline = time.monotonic() + 60.0
        while time.monotonic() < deadline:
            if not await authorize():
                break
            # Blocking store reads must stay off the event loop that serves every other request.
            # 多个任务中心连接（重连、多个页面）共享同一份快照，避免每个连接
            # 每 250 毫秒各自重建一次完整任务列表。
            encoded = await asyncio.to_thread(cached_snapshot)
            if encoded != previous:
                if not await authorize():
                    break
                previous = encoded
                yield f"event: task.snapshot\ndata: {encoded}\n\n"
            if once:
                break
            await asyncio.sleep(_STREAM_INTERVAL_SECONDS)
        yield "event: stream.closed\ndata: {}\n\n"

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@router.get("/api/agent/tasks/{task_id}", response_model=None)
def get_agent_task(
    task_id: str,
    principal: AgentPrincipal = Depends(require_agent_principal),
) -> dict[str, Any] | JSONResponse:
    try:
        orchestrator = AgentOrchestrator()
        task = orchestrator.get_task(
            user_id=principal.user_id,
            task_id=task_id,
            tenant_id=principal.tenant_id,
        )
        if task is None or not task_scope_matches(orchestrator, task, principal):
            return JSONResponse({"success": False, "message": "任务不存在"}, status_code=404)
        active = orchestrator.get_run(str(task.active_run_id or ""))
        if active is not None:
            from app.application.agent_orchestrator.cross_module_chain import (
                project_rejected_approval,
            )

            project_rejected_approval(active)
            task = (
                orchestrator.get_task(
                    user_id=principal.user_id,
                    task_id=task_id,
                    tenant_id=principal.tenant_id,
                )
                or task
            )
        return success(_task_envelope(orchestrator, task, viewer=principal))
    except RECOVERABLE_ERRORS:
        return internal_error_response("get agent task")


@router.post("/api/agent/tasks/{task_id}/read", response_model=None)
def mark_agent_task_read(
    task_id: str,
    principal: AgentPrincipal = Depends(require_agent_principal),
) -> dict[str, Any] | JSONResponse:
    """Acknowledge a completed workspace result without clearing approval attention."""
    try:
        orchestrator = AgentOrchestrator()
        task = orchestrator.get_task(
            user_id=principal.user_id,
            task_id=task_id,
            tenant_id=principal.tenant_id,
        )
        if task is None or not task_scope_matches(orchestrator, task, principal):
            return JSONResponse({"success": False, "message": "工作区不存在"}, status_code=404)
        if task.attention_state == "result_unread":
            task.attention_state = ""
            task.metadata = {**dict(task.metadata or {}), "read_at": utc_now_iso()}
            task = orchestrator.save_task(task)
        return success(_task_envelope(orchestrator, task, include_runs=False, viewer=principal))
    except RECOVERABLE_ERRORS:
        return internal_error_response("mark agent task read")


@router.post("/api/agent/tasks/{task_id}/archive", response_model=None)
def archive_agent_task(
    task_id: str,
    principal: AgentPrincipal = Depends(require_agent_principal),
) -> dict[str, Any] | JSONResponse:
    try:
        orchestrator = AgentOrchestrator()
        owned = orchestrator.get_task(
            user_id=principal.user_id,
            task_id=task_id,
            tenant_id=principal.tenant_id,
        )
        if owned is None or not task_scope_matches(orchestrator, owned, principal):
            return JSONResponse({"success": False, "message": "任务不存在"}, status_code=404)
        if owned.status not in {"completed", "failed", "cancelled"}:
            return JSONResponse(
                {"success": False, "message": "只有终态任务可以归档"},
                status_code=409,
            )
        archived = orchestrator.archive_task(
            user_id=principal.user_id,
            task_id=task_id,
            tenant_id=principal.tenant_id,
        )
        return success(archived.to_dict() if archived is not None else owned.to_dict())
    except RECOVERABLE_ERRORS:
        return internal_error_response("archive agent task")


__all__ = ["router"]


@router.post("/api/enterprise/cognition", tags=["enterprise-cognition"])
def cognition(
    body: CognitionRequest,
    principal: AgentPrincipal = Depends(require_agent_principal),
) -> dict[str, Any]:
    context = authenticated_runtime_context({"source": "enterprise_cognition_api"}, principal)
    try:
        result = get_cognition_service().invoke(body.action, body.params, context=context)
        if body.action == "plan":
            return run_response(result, principal=principal)
        verified = (
            result.get("observation_verified") is True
            if body.action == "evaluate"
            else result.get("current_state_verified") is True
            if body.action == "query"
            else True
        )
        return {"success": verified, "data": result}
    except (AgentModAuthorizationError, PermissionError) as exc:
        raise HTTPException(403, "当前账号无权访问该企业状态或任务") from exc
    except ValidationError as exc:
        raise HTTPException(422, "企业认知请求参数无效") from exc
    except ValueError as exc:
        raise HTTPException(409, "实体、目标、指标或原任务请求不一致") from exc
    except RECOVERABLE_ERRORS as exc:
        logger.exception("enterprise cognition request unavailable")
        raise HTTPException(503, "企业状态或原任务回执暂不可用，请保留原请求编号核对") from exc
