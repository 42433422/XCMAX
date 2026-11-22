"""Bind authenticated product requests to a qualified, replaceable local runtime.

The deployment selects the engine and upstream route. Requests supply neither
credentials nor a provider. Native callers keep their existing path; an admitted
Codex invocation never falls back or replays into another engine.
"""

from __future__ import annotations

import asyncio
import copy
import json
from collections.abc import Callable
from typing import Any, Literal

from sqlalchemy.exc import IntegrityError

from app.application.agent_orchestrator.budget import apply_ai_budget_metadata
from app.application.agent_orchestrator.run_lifecycle import continuation_conversation_error
from app.application.agent_orchestrator.run_models import AgentRun, utc_now_iso
from app.application.agent_orchestrator.run_repository import get_agent_run_repository
from app.application.agent_orchestrator.run_sql_repository import SQLAlchemyAgentRunRepository
from app.application.agent_orchestrator.runtime_context import merge_runtime_context
from app.application.agent_orchestrator.task_context import apply_task_context
from app.application.agent_orchestrator.tool_permission import redact
from app.application.agent_runtime.codex_runtime import run_codex_agent
from app.domain.task_lifecycle.agent_runtime_contract import (
    AgentRuntimeContractError,
    canonical_digest,
    validate_expected_operations,
)
from app.infrastructure.auth.agent_mod_scope import AgentModAuthorizationError, _bound_actor
from app.infrastructure.codex.binding import (
    CodexBindingError,
    CodexBindingStore,
)
from app.infrastructure.codex.local_server import LocalRuntimeServer
from app.infrastructure.codex.policy import (
    RuntimePolicyError,
    RuntimeSettings,
    runtime_settings,
)
from app.infrastructure.codex.tools import CodexToolBridge
from app.utils.operational_errors import RECOVERABLE_ERRORS

_PRIVATE_KEYS = frozenset(
    {
        "runtime_context",
        "token_hashes",
        "model_token",
        "mcp_token",
        "provider_token",
        "api_key",
        "access_token",
        "refresh_token",
        "authorization",
        "proof",
        "secret",
        "password",
    }
)
_CONTEXT_COMPARISON = (
    "user_id",
    "actor_id",
    "tenant_id",
    "local_user_id",
    "mod_id",
    "active_mod_id",
    "_actor_authorization",
    "_mod_authorization",
    "session_id",
    "conversation_id",
    "_conversation_revision",
    "workspace_id",
    "employee_id",
    "employee_tool_allowlist",
    "_employee_gate_contract",
    "workspace_root",
)
_EMPLOYEE_CONTEXT = frozenset(
    {
        "employee_id",
        "employee_tool_allowlist",
        "_employee_gate_contract",
        "workspace_root",
    }
)


def public_runtime_result(value: Any) -> Any:
    """Never expose task authorization bindings or internal callback credentials."""
    if isinstance(value, dict):
        return redact(
            {
                key: public_runtime_result(item)
                for key, item in value.items()
                if not str(key).startswith("_") and str(key).lower() not in _PRIVATE_KEYS
            }
        )
    if isinstance(value, list):
        return [public_runtime_result(item) for item in value]
    return redact(value)


def _failure(code: str, message: str, *, run_id: str = "") -> dict[str, Any]:
    return {
        "handler": "agent",
        "runtime": "codex",
        "run_id": run_id,
        "ok": False,
        "business_completed": False,
        "verified_operations": False,
        "retryable": False,
        "legacy_fallback_allowed": False,
        "output": "",
        "rounds": 0,
        "tool_calls": [],
        "trajectory": [],
        "session_messages": [],
        "run_events": [],
        "error_code": code,
        "exit_status": code,
        "error": message,
    }


def _trusted_context(raw: dict[str, Any]) -> tuple[dict[str, Any], str]:
    if not isinstance(raw, dict):
        raise CodexBindingError("runtime_identity_required", "运行需要可信登录身份")
    context = copy.deepcopy(raw)
    actor = _bound_actor(context)
    owner = str(actor.id)
    if context.get("local_user_id") not in (None, "", actor.id, owner):
        raise CodexBindingError("owner_changed", "会话持久用户与登录身份不一致")
    conversation = str(context.get("conversation_id") or "")
    session = str(context.get("session_id") or "")
    if conversation and session and conversation != session:
        raise CodexBindingError("conversation_changed", "会话标识不一致")
    if (conversation or session) and (
        type(context.get("_conversation_revision")) is not int
        or context["_conversation_revision"] < 0
    ):
        raise CodexBindingError("conversation_changed", "会话缺少可信历史版本")
    turn = context.get("turn_id")
    if not isinstance(turn, str) or not turn.strip() or len(turn) > 160:
        raise CodexBindingError("runtime_request_identity_required", "运行需要稳定的服务端请求标识")
    # These are always supplied by the host's explicit factory arguments or
    # qualified deployment configuration, never copied from request metadata.
    for key in (
        *(_PRIVATE_KEYS - {"runtime_context"}),
        "expected_operations",
        "runtime_expected_operations",
        "runtime_config",
        "runtime_type",
    ):
        context.pop(key, None)
    return context, owner


def _expected(value: list[dict[str, Any]] | None) -> list[dict[str, Any]] | None:
    try:
        return validate_expected_operations(value)
    except AgentRuntimeContractError as exc:
        raise CodexBindingError(exc.code, str(exc)) from exc


def _actions(value: list[str] | None) -> list[str] | None:
    if value is None:
        return None
    if not isinstance(value, list) or any(
        not isinstance(action, str) or not action.strip() or "." not in action for action in value
    ):
        raise CodexBindingError("invalid_allowed_actions", "员工工具授权列表无效")
    return sorted(set(value))


def _same_owner(
    run: AgentRun,
    incoming: dict[str, Any],
    owner: str,
    *,
    ancestor: bool = False,
) -> None:
    original = run.metadata.get("runtime_context") or {}
    if run.user_id != owner:
        raise CodexBindingError("owner_changed", "原任务不属于当前登录账号")
    # Actor seals must match as well as IDs. A different session cannot borrow
    # the authorization frozen into a previous worker's task.
    fields = tuple(
        key for key in _CONTEXT_COMPARISON if not ancestor or key not in _EMPLOYEE_CONTEXT
    )
    for key in fields:
        if original.get(key) != incoming.get(key):
            raise CodexBindingError("owner_changed", "原任务的身份、会话或员工范围已变化")
    merge_runtime_context(run, {key: incoming[key] for key in fields if key in incoming})
    _bound_actor(original)
    if error := continuation_conversation_error(run, original):
        raise CodexBindingError("conversation_changed", error)


def _insert_parent(
    repository: SQLAlchemyAgentRunRepository, run: AgentRun
) -> tuple[AgentRun, bool]:
    """Insert the request identity once; use the existing transaction for Task projection."""
    from app.db.models.agent import AgentRunRecord

    try:
        with repository.transaction() as db:
            db.add(
                AgentRunRecord(
                    run_id=run.run_id,
                    user_id=run.user_id,
                    status=run.status,
                    intent=run.intent,
                    message=run.message,
                    payload_json=json.dumps(run.to_dict(), ensure_ascii=False),
                    created_at=run.created_at,
                    updated_at=run.updated_at,
                )
            )
            db.flush()  # The database primary key fences workers in other processes.
            repository.save_in_session(db, run)
    except IntegrityError:
        previous = repository.get(run.run_id)
        if previous is None:
            raise
        return previous, False
    return repository.get(run.run_id) or run, True


def _duplicate_result(run: AgentRun, request: dict[str, Any]) -> dict[str, Any]:
    if isinstance(request.get("result"), dict):
        return {**public_runtime_result(request["result"]), "deduplicated": True}
    result = _failure(
        "runtime_request_in_progress", "原请求已受理，请读取原任务状态", run_id=run.run_id
    )
    result.update(execution_state=run.status, deduplicated=True, resume_required=True)
    return result


def _record_request_result(
    store: CodexBindingStore,
    run_id: str,
    request_key: str,
    result: dict[str, Any],
    *,
    failed_before_execution: bool = False,
) -> None:
    def finish(run: AgentRun, metadata: dict[str, Any]) -> None:
        request = run.metadata["runtime_requests"][request_key]
        request.update(state="returned", result=copy.deepcopy(result), returned_at=utc_now_iso())
        if (
            failed_before_execution
            and not metadata.get("coordinator_active")
            and run.status in {"queued", "planning"}
        ):
            run.status = "blocked"
            run.error = str(result.get("error") or "运行未能启动")
            run.final_output["codex_result"] = copy.deepcopy(result)
            run.add_event(
                "runtime.admission.failed", run.error, {"error_code": result.get("error_code")}
            )

    store.update(run_id, finish)


async def run_runtime_task_async(
    *,
    task: str,
    system_prompt: str,
    runtime_context: dict[str, Any],
    history: list[dict[str, Any]] | None = None,
    input_data: dict[str, Any] | None = None,
    run_id: str | None = None,
    completion_mode: Literal["business", "reply"] = "business",
    allowed_actions: list[str] | None = None,
    gate: Callable[..., dict[str, Any]] | None = None,
    on_event: Callable[[dict[str, Any]], Any] | None = None,
    answer_to_waiting_input: bool = False,
    settings: RuntimeSettings | None = None,
    expected_operations: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Create or explicitly resume a durable host-owned runtime parent."""
    resolved_id = str(run_id or "")
    store = None
    request_key = ""
    admitted = False
    try:
        settings = settings or runtime_settings()
        if settings.engine != "codex":
            return _failure(
                "runtime_not_selected", "当前部署未选择 Codex 运行时", run_id=resolved_id
            )
        route = settings.require_qualified()
        route.token()  # Fail before persisting a runnable parent if credentials are unavailable.
        if settings.runtime_root is None:
            raise RuntimePolicyError("Codex private runtime_root is required")
        if (
            not isinstance(task, str)
            or not task.strip()
            or not isinstance(system_prompt, str)
            or completion_mode not in {"business", "reply"}
            or type(answer_to_waiting_input) is not bool
        ):
            raise CodexBindingError("invalid_request", "任务或完成模式无效")
        context, owner = _trusted_context(runtime_context)
        expected = _expected(expected_operations)
        actions = _actions(allowed_actions)
        repository = get_agent_run_repository()
        if not isinstance(repository, SQLAlchemyAgentRunRepository):
            raise CodexBindingError("durable_storage_required", "运行需要持久化任务仓储")
        store = CodexBindingStore(repository)
        request_key = canonical_digest({"turn_id": context["turn_id"], "owner": owner})
        instruction_digest = canonical_digest(system_prompt)
        requested = {
            "task": task,
            "input": input_data,
            "completion_mode": completion_mode,
            "instructions": instruction_digest,
            "allowed_actions": actions,
            "expected_operations": expected,
            "answer_to_waiting_input": answer_to_waiting_input,
            "history": canonical_digest(history),
        }
        is_resume = bool(run_id)
        if is_resume:
            parent = repository.get(resolved_id)
            if parent is None:
                raise CodexBindingError("binding_missing", "原运行任务不存在")
            _same_owner(parent, context, owner)
            if parent.intent != "codex.runtime" or parent.metadata.get("runtime_type") != "codex":
                raise CodexBindingError("runtime_changed", "不能把其他引擎的任务恢复为 Codex")
            if parent.metadata.get("runtime_route_identity") != route.identity:
                raise CodexBindingError("runtime_changed", "原任务的模型路由不能改变")
            if parent.metadata.get("runtime_gate_required") and gate is None:
                raise CodexBindingError("gate_required", "原任务的员工工具检查不可省略")
            if parent.metadata.get("runtime_instruction_digest") != instruction_digest:
                raise CodexBindingError("runtime_changed", "原任务的运行指令不能改变")
            if parent.metadata.get("runtime_completion_mode") != completion_mode:
                raise CodexBindingError("runtime_changed", "原任务的完成判定不能改变")
            stored_actions = parent.metadata.get("runtime_allowed_actions")
            if actions is None:
                actions = copy.deepcopy(stored_actions)
                requested["allowed_actions"] = actions
            elif actions != stored_actions:
                raise CodexBindingError("owner_changed", "原任务的工具授权范围不能改变")
            stored_expected = parent.metadata.get("runtime_expected_operations")
            if expected is None:
                expected = copy.deepcopy(stored_expected)
                requested["expected_operations"] = expected
            elif expected != stored_expected:
                raise CodexBindingError("request_conflict", "不能改变原任务冻结的业务目标")
        else:
            # Authorization revisions and mutable tool configuration must not
            # turn a repeated client request into a new executable task.
            seed = {
                key: context.get(key)
                for key in (
                    "tenant_id",
                    "mod_id",
                    "active_mod_id",
                    "employee_id",
                    "parent_run_id",
                    "node_id",
                    "step_id",
                    "turn_id",
                )
            }
            seed["owner"] = owner
            resolved_id = "run_codex_" + canonical_digest(seed)[:48]
            parent_run_id = str(context.get("parent_run_id") or "")
            if parent_run_id:
                ancestor = repository.get(parent_run_id)
                if ancestor is None:
                    raise CodexBindingError("parent_missing", "员工父任务不存在")
                _same_owner(ancestor, context, owner, ancestor=True)
                parent_context = ancestor.metadata.get("task_context") or {}
                context["parent_task_id"] = parent_context.get("task_id") or ancestor.run_id
                context["root_run_id"] = parent_context.get("root_run_id") or ancestor.run_id
            else:
                context["root_run_id"] = resolved_id
            context.update(task_id=resolved_id, source="codex_runtime")
            parent = AgentRun(
                user_id=owner, message=task, run_id=resolved_id, intent="codex.runtime"
            )
            parent.metadata.update(
                runtime_type="codex",
                runtime_context=context,
                runtime_route_identity=route.identity,
                runtime_gate_required=gate is not None,
                runtime_instruction_digest=instruction_digest,
                runtime_expected_operations=expected,
                runtime_completion_mode=completion_mode,
                runtime_allowed_actions=actions,
                _codex_system_prompt=system_prompt,
                _codex_input_data=copy.deepcopy(input_data),
                runtime_requests={
                    request_key: {
                        "digest": canonical_digest(requested),
                        "state": "admitted",
                        "turn_id": context["turn_id"],
                        "created_at": utc_now_iso(),
                    }
                },
            )
            apply_task_context(parent, context)
            apply_ai_budget_metadata(parent, context)
            if error := continuation_conversation_error(parent, context):
                raise CodexBindingError("conversation_changed", error)
            parent, created = _insert_parent(repository, parent)
            _same_owner(parent, context, owner)
            if created:
                admitted = True
        digest = canonical_digest(requested)
        request = (parent.metadata.get("runtime_requests") or {}).get(request_key)
        if request is not None and request.get("digest") != digest:
            raise CodexBindingError("request_conflict", "同一请求标识已绑定不同任务内容")
        if request is not None and not admitted:
            return _duplicate_result(parent, request)
        if is_resume:

            def claim(run: AgentRun, _metadata: dict[str, Any]) -> None:
                nonlocal admitted
                admitted = False
                requests = run.metadata.setdefault("runtime_requests", {})
                if request_key in requests:
                    if requests[request_key].get("digest") != digest:
                        raise CodexBindingError(
                            "request_conflict", "同一请求标识已绑定不同任务内容"
                        )
                    return
                if len(requests) >= 256:
                    raise CodexBindingError("request_limit", "运行任务已达到续跑请求上限")
                requests[request_key] = {
                    "digest": digest,
                    "state": "admitted",
                    "turn_id": context["turn_id"],
                    "created_at": utc_now_iso(),
                }
                admitted = True

            claimed = store.update(resolved_id, claim)
            if not admitted:
                return _duplicate_result(
                    claimed.run, claimed.run.metadata["runtime_requests"][request_key]
                )
        from fastapi import FastAPI

        from app.infrastructure.codex import CodexTransportConfig
        from app.infrastructure.codex.mcp_server import MCP_PATH
        from app.infrastructure.codex.mcp_server import router as mcp_router
        from app.infrastructure.codex.model_gateway import MODEL_PATH
        from app.infrastructure.codex.model_gateway import router as model_router

        app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)
        app.state.codex_binding_store = store
        app.state.codex_run_id = resolved_id
        app.state.codex_tool_bridge = CodexToolBridge(store, gate=gate, run_id=resolved_id)
        app.state.codex_model_route = route
        app.include_router(model_router)
        app.include_router(mcp_router)
        with LocalRuntimeServer(app) as server:
            config = CodexTransportConfig(
                runtime_root=settings.runtime_root,
                scope_id=resolved_id,
                model=route.model,
                provider_url=server.url + MODEL_PATH.removesuffix("/responses"),
                provider_token="placeholder-runtime-grant",  # replaced before transport starts,
                mcp_url=server.url + MCP_PATH,
                mcp_token="placeholder-runtime-grant",  # replaced before transport starts,
                context_window=route.context_window,
                auto_compact_token_limit=route.context_window - route.max_output_tokens,
                codex_bin=settings.codex_bin,
                turn_timeout_seconds=settings.turn_timeout_seconds,
            )
            result = await run_codex_agent(
                run_id=resolved_id,
                task=task,
                system_prompt=system_prompt,
                config=config,
                binding_store=store,
                history=history,
                input_data=input_data,
                completion_mode=completion_mode,
                allowed_actions=actions,
                runtime_config={**route.runtime_identity(), "gate_required": gate is not None},
                answer_to_waiting_input=answer_to_waiting_input,
                on_event=(lambda event: on_event(public_runtime_result(event)))
                if on_event
                else None,
            )
        result = dict(public_runtime_result(result))
        _record_request_result(store, resolved_id, request_key, result)
        return result
    except asyncio.CancelledError:
        if store is not None and admitted:
            try:
                store.update(
                    resolved_id,
                    lambda run, metadata: run.metadata["runtime_requests"][request_key].update(
                        state="interrupted"
                    ),
                )
            except RECOVERABLE_ERRORS:
                pass  # Preserve cancellation; durable coordinator receipts remain authoritative.
        raise
    except (AgentModAuthorizationError, RuntimePolicyError, CodexBindingError) as exc:
        result = _failure(
            getattr(exc, "code", "runtime_policy_blocked"), str(exc), run_id=resolved_id
        )
    except RECOVERABLE_ERRORS:
        result = _failure(
            "runtime_unavailable", "运行未能完成，原任务状态与回执已保留", run_id=resolved_id
        )
    if store is not None and admitted:
        try:
            _record_request_result(
                store, resolved_id, request_key, result, failed_before_execution=True
            )
        except RECOVERABLE_ERRORS:
            result.update(
                error_code="runtime_persistence_uncertain",
                exit_status="unknown",
                reconciliation_required=True,
            )
    return dict(public_runtime_result(result))


def run_runtime_task(**kwargs: Any) -> dict[str, Any]:
    """Synchronous product seam; keep authenticated context across an existing event loop."""
    from app.application.employee_runtime.agent_runner import _run_async

    return dict(_run_async(run_runtime_task_async(**kwargs)))


__all__ = ["public_runtime_result", "run_runtime_task", "run_runtime_task_async"]
