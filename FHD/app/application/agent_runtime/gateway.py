"""Bind authenticated product requests to the qualified local Xiaox runtime.

Requests supply neither credentials nor a provider. The host binds the original goal
without preplanning business actions; a Xiaox invocation never falls back into another engine.
"""

from __future__ import annotations

import asyncio
import copy
import json
import os
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
from app.application.agent_runtime.configuration import (
    RuntimeSetupError,
    get_account_runtime_settings,
)
from app.application.agent_runtime.xiaox_runtime import run_xiaox_agent
from app.domain.task_lifecycle.agent_runtime_contract import (
    canonical_digest,
)
from app.domain.task_lifecycle.agent_runtime_results import base_runtime_result
from app.infrastructure.auth.agent_mod_scope import AgentModAuthorizationError, _bound_actor
from app.infrastructure.xiaox.binding import (
    XiaoxBindingError,
    XiaoxBindingStore,
)
from app.infrastructure.xiaox.local_server import LocalRuntimeServer
from app.infrastructure.xiaox.policy import (
    RuntimePolicyError,
    RuntimeSettings,
    runtime_settings,
)
from app.infrastructure.xiaox.tools import XiaoxToolBridge
from app.utils.operational_errors import RECOVERABLE_ERRORS

_PRIVATE_KEYS = frozenset(
    {
        "runtime_context",
        "goal_response",
        "verification_feedback",
        "runtime_goal_verification",
        "failure_reason",
        "runtime_failure_reason",
        "runtime_error",
        "upstream_error",
        "token_hashes",
        "model_token",
        "mcp_token",
        "provider_token",
        "route_token",
        "credential",
        "auth_token",
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
    "_credential_authorization",
    "_mod_authorization",
    "_credential_authorization",
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
    """Project public status, receipts and released text, not drafts or diagnostics."""
    if isinstance(value, dict):
        projected = {}
        for key, item in value.items():
            if str(key).startswith("_") or str(key).lower() in _PRIVATE_KEYS:
                continue
            if key == "message" and value.get("event_type") == "runtime.model.failure":
                item = "模型请求未完成"
            if key == "goal_coverage" and isinstance(item, dict):
                item = {k: v for k, v in item.items() if k != "errors"}
            projected[key] = public_runtime_result(item)
        return redact(projected)
    if isinstance(value, list):
        return [public_runtime_result(item) for item in value]
    return redact(value)


def _failure(code: str, message: str, *, run_id: str = "") -> dict[str, Any]:
    return {
        "handler": "agent",
        "runtime": "xiaox",
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
        raise XiaoxBindingError("runtime_identity_required", "运行需要可信登录身份")
    context = copy.deepcopy(raw)
    actor = _bound_actor(context)
    owner = str(actor.id)
    if context.get("local_user_id") not in (None, "", actor.id, owner):
        raise XiaoxBindingError("owner_changed", "会话持久用户与登录身份不一致")
    conversation = str(context.get("conversation_id") or "")
    session = str(context.get("session_id") or "")
    if conversation and session and conversation != session:
        raise XiaoxBindingError("conversation_changed", "会话标识不一致")
    if (conversation or session) and (
        type(context.get("_conversation_revision")) is not int
        or context["_conversation_revision"] < 0
    ):
        raise XiaoxBindingError("conversation_changed", "会话缺少可信历史版本")
    turn = context.get("turn_id")
    if not isinstance(turn, str) or not turn.strip() or len(turn) > 160:
        raise XiaoxBindingError("runtime_request_identity_required", "运行需要稳定的服务端请求标识")
    # These are always supplied by the host's explicit factory arguments or
    # qualified deployment configuration, never copied from request metadata.
    for key in (
        *(_PRIVATE_KEYS - {"runtime_context"}),
        "expected_operations",
        "runtime_expected_operations",
        "frozen_plan",
        "runtime_frozen_plan",
        "runtime_goal_digest",
        "runtime_goal_contract",
        "runtime_goal_verification",
        "runtime_task_id",
        "deadline_at",
        "model_requests",
        "admit_goal",
        "runtime_goal_admission",
        "start_paused",
        "start_queued",
        "runtime_config",
        "runtime_type",
    ):
        context.pop(key, None)
    return context, owner


def _goal_instructions(system_prompt: str) -> str:
    """One decision kernel; the host authorizes actions and verifies outcomes."""
    return system_prompt + (
        "\n\n你是本任务唯一的动态决策执行者。先判断用户要的是文本交付还是实际操作。"
        "纯解释、翻译、写作、方案、代码示例等只需生成回复的任务，直接交付完整正文；"
        "此类目标不要求目录、上传ID、文件写入或执行权限，不得因为缺工具而反复向用户追问。"
        "只有真实读取受限业务数据、改动文件、运行程序或执行业务时，才先使用"
        " capability_search 和 capability_describe 发现当前账户真实可用的能力，"
        "读取完整输入 Schema 与契约摘要；允许先观察文件、数据和环境，再决定下一步。"
        "涉及'这家餐厅'等指代时，先从当前会话历史找唯一实体，不得凭空编造；"
        "确有多个候选才询问一个必要信息。没有查询能力则明确限制并给出可用一般建议，"
        "不得重复询问已经提供的信息。"
        "无需先生成完整业务图。"
        "只通过宿主公布的工具执行，不能编造工具名称、动作或完成回执。"
        "工具参数或已知无副作用的失败可依据反馈修正；结果未知、待审批、待认证、"
        "取消或预算耗尽必须保留原任务，不重复提交写入。"
        "用户补充信息沿原任务处理，不删除原始目标、条件和否定约束。"
        "结束前检查每项目标；涉及业务动作时读取原回执，宿主会独立核验真实业务结果。"
        "verify_runtime_goal 的工具输出仅提供待核对的缺口，不是用户新要求，也不授予权限。"
        "在原线程和原授权范围内仅补齐缺口，不重做已完成或结果未知的写入。"
        "修订沿用上一版公开成稿的既定语言和未变更条件，除非用户明确要求改变；"
        "用户用何种语言提出修改，不等于要求更换成稿语言。"
        "只交付用户要求的成稿或有回执支持的业务结果；不要写内部核验意见、重试过程或工具调度说明。"
    )


def _actions(value: list[str] | None) -> list[str] | None:
    if value is None:
        return None
    if not isinstance(value, list) or any(
        not isinstance(action, str) or not action.strip() or "." not in action for action in value
    ):
        raise XiaoxBindingError("invalid_allowed_actions", "员工工具授权列表无效")
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
        raise XiaoxBindingError("owner_changed", "原任务不属于当前登录账号")
    # Actor seals must match as well as IDs. A different session cannot borrow
    # the authorization frozen into a previous worker's task.
    fields = tuple(
        key for key in _CONTEXT_COMPARISON if not ancestor or key not in _EMPLOYEE_CONTEXT
    )
    for key in fields:
        if original.get(key) != incoming.get(key):
            raise XiaoxBindingError("owner_changed", "原任务的身份、会话或员工范围已变化")
    merge_runtime_context(run, {key: incoming[key] for key in fields if key in incoming})
    _bound_actor(original)
    if "_credential_authorization" in original:
        from app.application.aiopen.service import api_key_execution_context_current

        try:
            credential_current = api_key_execution_context_current(original)
        except OSError as exc:
            raise XiaoxBindingError("owner_changed", "原调用凭据无法核验") from exc
        if not credential_current:
            raise XiaoxBindingError("owner_changed", "原调用凭据已撤销、过期或授权范围已变化")
    if error := continuation_conversation_error(run, original):
        raise XiaoxBindingError("conversation_changed", error)


def _insert_parent(
    repository: SQLAlchemyAgentRunRepository, run: AgentRun, *, queue: Any = None
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
            if queue is not None:
                queue.enqueue_in_session(db, run, requested_by=run.user_id)
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
    store: XiaoxBindingStore,
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
            run.final_output["xiaox_result"] = copy.deepcopy(result)
            run.add_event(
                "runtime.admission.failed", run.error, {"error_code": result.get("error_code")}
            )

    try:
        store.update(run_id, finish)
    except RECOVERABLE_ERRORS:
        # A commit ACK can be lost. Read this exact request before reporting an
        # uncertain receipt; never replace its committed outcome with a failure.
        current = store.repository.get(run_id)
        request = (
            (current.metadata.get("runtime_requests") or {}).get(request_key) if current else None
        )
        if not (
            isinstance(request, dict)
            and request.get("state") == "returned"
            and request.get("result") == result
        ):
            raise


def _request_persistence_uncertain(result: dict[str, Any]) -> dict[str, Any]:
    message = "原请求收尾尚待核对，请读取原任务回执，不要重新提交业务操作"
    return {
        **result,
        "ok": False,
        "business_completed": False,
        "reply_completed": False,
        "retryable": False,
        "error_code": "runtime_persistence_uncertain",
        "exit_status": "unknown",
        "execution_state": "unknown",
        "reconciliation_required": True,
        "error": message,
        "output": message,
    }


async def run_runtime_task_async(
    *,
    task: str,
    system_prompt: str,
    runtime_context: dict[str, Any],
    history: list[dict[str, Any]] | None = None,
    input_data: dict[str, Any] | None = None,
    run_id: str | None = None,
    completion_mode: Literal["business", "reply", "auto"] = "business",
    allowed_actions: list[str] | None = None,
    gate: Callable[[str, str, dict[str, Any]], dict[str, Any]] | None = None,
    on_event: Callable[[dict[str, Any]], Any] | None = None,
    answer_to_waiting_input: bool = False,
    settings: RuntimeSettings | None = None,
    start_paused: bool = False,
    start_queued: bool = False,
    _repository: SQLAlchemyAgentRunRepository | None = None,
    _task_id: str | None = None,
) -> dict[str, Any]:
    """Create or explicitly resume a durable host-owned runtime parent."""
    resolved_id = str(run_id or "")
    store = None
    request_key = ""
    admitted = False
    try:
        if (
            not isinstance(task, str)
            or not task.strip()
            or not isinstance(system_prompt, str)
            or completion_mode not in {"business", "reply", "auto"}
            or type(answer_to_waiting_input) is not bool
            or type(start_paused) is not bool
            or type(start_queued) is not bool
            or (start_paused and start_queued)
            or (start_paused and run_id)
            or (
                _task_id is not None
                and (
                    not isinstance(_task_id, str)
                    or not _task_id.strip()
                    or len(_task_id) > 160
                    or "/" in _task_id
                )
            )
        ):
            raise XiaoxBindingError("invalid_request", "任务或完成模式无效")
        context, owner = _trusted_context(runtime_context)
        from app.domain.task_lifecycle.execution_mode import (
            CONTEXT_KEY,
            METADATA_KEY,
            normalize_mode,
        )

        mode = normalize_mode(context.get(CONTEXT_KEY))
        actions = _actions(allowed_actions)
        repository = _repository or get_agent_run_repository()
        if not isinstance(repository, SQLAlchemyAgentRunRepository):
            raise XiaoxBindingError("durable_storage_required", "运行需要持久化任务仓储")
        store = XiaoxBindingStore(repository)
        parent = repository.get(resolved_id) if run_id else None
        previous = None
        if run_id:
            if parent is None:
                raise XiaoxBindingError("binding_missing", "原运行任务不存在")
            _same_owner(parent, context, owner)
            for prefix, alternate in (("run_codex_", "run_xiaox_"), ("run_xiaox_", "run_codex_")):
                if (
                    resolved_id.startswith(prefix)
                    and repository.get(alternate + resolved_id[len(prefix) :]) is not None
                ):
                    raise XiaoxBindingError(
                        "runtime_identity_conflict",
                        "同一请求存在两套任务记录，须核对原始回执，禁止重复执行",
                    )
            if parent.intent != "xiaox.runtime" or parent.metadata.get("runtime_type") != "xiaox":
                raise XiaoxBindingError("runtime_changed", "不能把其他引擎的任务恢复为 Xiaox")
            previous = parent.metadata.get("runtime_route") or (
                parent.metadata.get("xiaox_runtime") or {}
            ).get("runtime_config")
        ancestor = None
        parent_run_id = str(context.get("parent_run_id") or "")
        if not run_id and parent_run_id:
            ancestor = repository.get(parent_run_id)
            if ancestor is None:
                raise XiaoxBindingError("parent_missing", "员工父任务不存在")
            _same_owner(ancestor, context, owner, ancestor=True)
        queued_payload = {
            "task": task,
            "input_data": input_data,
            "history": history,
            "answer_to_waiting_input": answer_to_waiting_input,
        }
        request_key = canonical_digest({"turn_id": context["turn_id"], "owner": owner})
        instruction_digest = canonical_digest(system_prompt)
        requested = {
            "task": task,
            "input": input_data,
            "completion_mode": completion_mode,
            "instructions": instruction_digest,
            "allowed_actions": actions,
            "start_paused": start_paused,
            "start_queued": start_queued,
            "answer_to_waiting_input": answer_to_waiting_input,
            "history": canonical_digest(history),
            "task_id": _task_id,
        }
        is_resume = bool(run_id)
        if is_resume:
            assert parent is not None  # Resolved and owner-checked before loading credentials.
            stored_task_id = parent.metadata.get("runtime_task_id")
            if _task_id is not None and _task_id != stored_task_id:
                raise XiaoxBindingError("request_conflict", "原运行任务的宿主任务标识不能改变")
            if stored_task_id is not None and (
                (parent.metadata.get("task_context") or {}).get("task_id") != stored_task_id
            ):
                raise XiaoxBindingError("request_conflict", "原运行任务的任务绑定已改变")
            requested["task_id"] = stored_task_id
            if parent.metadata.get("runtime_gate_required") and gate is None:
                raise XiaoxBindingError("gate_required", "原任务的员工工具检查不可省略")
            if parent.metadata.get("runtime_instruction_digest") != instruction_digest:
                raise XiaoxBindingError("runtime_changed", "原任务的运行指令不能改变")
            if parent.metadata.get("runtime_completion_mode") != completion_mode:
                raise XiaoxBindingError("runtime_changed", "原任务的完成判定不能改变")
            if parent.metadata.get(METADATA_KEY, "execute") != mode:
                raise XiaoxBindingError("runtime_changed", "原任务的执行模式不能改变")
            stored_actions = parent.metadata.get("runtime_allowed_actions")
            if actions is None:
                actions = copy.deepcopy(stored_actions)
                requested["allowed_actions"] = actions
            elif actions != stored_actions:
                raise XiaoxBindingError("owner_changed", "原任务的工具授权范围不能改变")
            store._validate_goal(parent, parent.metadata.get("xiaox_runtime") or {})
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
            if _task_id is not None:
                seed["task_id"] = _task_id
            # The request ID is a persistence and billing protocol, not a brand.
            # Prefer the original namespace for all new requests. A record made
            # by the intermediate Xiaox build must keep its original ID.
            suffix = canonical_digest(seed)[:48]
            legacy_id, renamed_id = "run_codex_" + suffix, "run_xiaox_" + suffix
            legacy, renamed = repository.get(legacy_id), repository.get(renamed_id)
            if legacy is not None and renamed is not None:
                raise XiaoxBindingError(
                    "runtime_identity_conflict",
                    "同一请求存在两套任务记录，须核对原始回执，禁止重复执行",
                )
            resolved_id = renamed_id if renamed is not None else legacy_id
            if ancestor is not None:
                parent_context = ancestor.metadata.get("task_context") or {}
                context["parent_task_id"] = parent_context.get("task_id") or ancestor.run_id
                context["root_run_id"] = parent_context.get("root_run_id") or ancestor.run_id
            else:
                context["root_run_id"] = resolved_id
            context.update(task_id=_task_id or resolved_id, source="xiaox_runtime")
            parent = repository.get(resolved_id)
            if parent is not None:
                _same_owner(parent, context, owner)
                # Until the complete legacy receipt/approval protocol is migrated,
                # fail closed instead of starting a replacement task.
                if (
                    parent.intent != "xiaox.runtime"
                    or parent.metadata.get("runtime_type") != "xiaox"
                ):
                    raise XiaoxBindingError(
                        "runtime_migration_required",
                        "原请求已存在，须恢复原任务及回执，禁止重新执行",
                    )
        digest = canonical_digest(requested)
        if parent is not None:
            request = (parent.metadata.get("runtime_requests") or {}).get(request_key)
            if request is not None:
                if request.get("digest") != digest:
                    raise XiaoxBindingError("request_conflict", "同一请求标识已绑定不同任务内容")
                return _duplicate_result(parent, request)
            if not is_resume:
                raise XiaoxBindingError("request_conflict", "原运行任务缺少已绑定的请求标识")
            if parent.status != "blocked":
                store._validate_control(parent)
        elif ancestor is not None:
            store._validate_control(ancestor)
        # Read-only replay and deferred execution never start paid qualification.
        deferred = (
            start_paused or start_queued or (parent is not None and parent.status == "blocked")
        )
        explicit_settings = settings is not None
        settings = settings or runtime_settings()
        if settings.engine != "xiaox":
            return _failure(
                "runtime_not_selected", "当前部署未选择 Xiaox 运行时", run_id=resolved_id
            )
        if (
            not explicit_settings
            and settings.route is None
            and not os.environ.get("XCAGI_AGENT_RUNTIME_CONFIG", "").strip()
        ):
            if run_id and previous is None:
                raise XiaoxBindingError(
                    "runtime_changed", "原任务缺少模型路由绑定，请恢复原部署配置。"
                )
            options = {"qualify": False} if deferred else {}
            settings = await asyncio.to_thread(
                get_account_runtime_settings, owner, previous=previous, **options
            )
        surface = "employee" if context.get("employee_id") else "chat"
        if surface not in settings.surfaces:
            raise RuntimePolicyError("当前入口未启用固定 Xiaox 执行器")
        route = settings.route if deferred else settings.require_qualified()
        if route is None or settings.runtime_root is None:
            raise RuntimePolicyError("Xiaox model route and private runtime_root are required")
        if not deferred:
            route.token()  # Credentials and real qualification precede business execution.
        if is_resume and parent is not None:
            if parent.metadata.get("runtime_route_identity") != route.identity:
                raise XiaoxBindingError("runtime_changed", "原任务的模型路由不能改变")
        queue = None
        if start_queued:
            from app.infrastructure.xiaox.queued_runtime import (
                durable_queue,
                stage_queued_request,
            )

            queue = durable_queue(repository)
        if not is_resume:
            parent = AgentRun(
                user_id=owner, message=task, run_id=resolved_id, intent="xiaox.runtime"
            )
            parent.metadata.update(
                runtime_type="xiaox",
                runtime_task_id=_task_id,
                runtime_context=context,
                runtime_route_identity=route.identity,
                runtime_route=route.runtime_identity(),
                runtime_gate_required=gate is not None,
                runtime_instruction_digest=instruction_digest,
                runtime_completion_mode=completion_mode,
                **{METADATA_KEY: mode},
                runtime_allowed_actions=actions,
                _xiaox_system_prompt=system_prompt,
                _xiaox_input_data=copy.deepcopy(input_data),
                _xiaox_history=copy.deepcopy(history),
                runtime_requests={
                    request_key: {
                        "digest": canonical_digest(requested),
                        "state": "admitted",
                        "turn_id": context["turn_id"],
                        "created_at": utc_now_iso(),
                    }
                },
            )
            if start_paused or start_queued:
                parent.status = "paused" if start_paused else "queued"
                parent.metadata["xiaox_runtime"] = {
                    "version": 1,
                    "generation": 0,
                    "coordinator_active": False,
                    "revoked": True,
                    "token_hashes": {},
                    "calls": {},
                    "runtime_status": "not_started",
                }
            if start_paused:
                staged = {
                    **base_runtime_result(resolved_id),
                    "execution_state": "paused",
                    "exit_status": "paused",
                    "resume_required": True,
                    "output": "任务已保存，恢复后开始执行。",
                }
                parent.final_output["xiaox_result"] = copy.deepcopy(staged)
                parent.metadata["runtime_requests"][request_key].update(
                    state="completed", result=copy.deepcopy(staged)
                )
                parent.add_event("runtime.staged", "任务已保存，等待显式恢复")
            elif start_queued:
                stage_queued_request(parent, request_key, queued_payload)
            apply_task_context(parent, context)
            apply_ai_budget_metadata(parent, context)
            if error := continuation_conversation_error(parent, context):
                raise XiaoxBindingError("conversation_changed", error)
            parent, created = _insert_parent(repository, parent, queue=queue)
            _same_owner(parent, context, owner)
            if parent.intent != "xiaox.runtime" or parent.metadata.get("runtime_type") != "xiaox":
                raise XiaoxBindingError(
                    "runtime_migration_required", "原请求已存在，须恢复原任务及回执，禁止重新执行"
                )
            if created:
                admitted = True
        assert parent is not None
        request = (parent.metadata.get("runtime_requests") or {}).get(request_key)
        if request is not None and request.get("digest") != digest:
            raise XiaoxBindingError("request_conflict", "同一请求标识已绑定不同任务内容")
        if request is not None and not admitted:
            return _duplicate_result(parent, request)
        if start_paused:
            return dict(public_runtime_result(parent.final_output["xiaox_result"]))
        if start_queued and not is_resume:
            from app.application.agent_orchestrator.task_dispatcher import (
                notify_agent_task_dispatcher,
            )

            notify_agent_task_dispatcher()
            return dict(public_runtime_result(parent.final_output["xiaox_result"]))
        if is_resume:
            queue_resume = start_queued or parent.status == "blocked"
            if queue_resume:
                from app.infrastructure.xiaox.queued_runtime import stage_queued_request

            if parent.status == "blocked":
                from app.application.agent_runtime.xiaox_runtime import _resume_error

                rows = store.receipt_snapshot(resolved_id)
                binding = store.get(resolved_id)
                if error := _resume_error(store, binding, rows):
                    raise XiaoxBindingError("reconciliation_required", error)
                parent = binding.run

            def claim(run: AgentRun, _metadata: dict[str, Any]) -> None:
                nonlocal admitted
                admitted = False
                requests = run.metadata.setdefault("runtime_requests", {})
                if request_key in requests:
                    if requests[request_key].get("digest") != digest:
                        raise XiaoxBindingError(
                            "request_conflict", "同一请求标识已绑定不同任务内容"
                        )
                    return
                if len(requests) >= 256:
                    raise XiaoxBindingError("request_limit", "运行任务已达到续跑请求上限")
                requests[request_key] = {
                    "digest": digest,
                    "state": "admitted",
                    "turn_id": context["turn_id"],
                    "created_at": utc_now_iso(),
                }
                if queue_resume:
                    stage_queued_request(run, request_key, queued_payload)
                else:
                    admitted = True

            if queue_resume:
                from app.application.agent_orchestrator.task_dispatcher import (
                    notify_agent_task_dispatcher,
                )
                from app.infrastructure.xiaox.queued_runtime import enqueue_resume

                queued = enqueue_resume(store, parent, claim)
                admitted = True
                notify_agent_task_dispatcher()
                return dict(public_runtime_result(queued.final_output["xiaox_result"]))
            claimed = store.update(resolved_id, claim)
            if not admitted:
                return _duplicate_result(
                    claimed.run, claimed.run.metadata["runtime_requests"][request_key]
                )
        from fastapi import FastAPI

        from app.application.planner_compat.runtime import publish_admitted_chat_run
        from app.infrastructure.xiaox import XiaoxTransportConfig
        from app.infrastructure.xiaox.mcp_server import MCP_PATH
        from app.infrastructure.xiaox.mcp_server import router as mcp_router
        from app.infrastructure.xiaox.model_gateway import MODEL_PATH
        from app.infrastructure.xiaox.model_gateway import router as model_router

        publish_admitted_chat_run(resolved_id, str(context["turn_id"]))
        app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)
        app.state.xiaox_binding_store = store
        app.state.xiaox_run_id = resolved_id
        bridge = XiaoxToolBridge(store, gate=gate, run_id=resolved_id)
        app.state.xiaox_tool_bridge = bridge
        app.state.xiaox_model_route = route
        app.include_router(model_router)
        app.include_router(mcp_router)
        with LocalRuntimeServer(app) as server:
            config = XiaoxTransportConfig(
                runtime_root=settings.runtime_root,
                scope_id=resolved_id,
                model=route.model,
                provider_url=server.url + MODEL_PATH.removesuffix("/responses"),
                provider_token="placeholder-runtime-grant",  # replaced before transport starts
                mcp_url=server.url + MCP_PATH,
                mcp_token="placeholder-runtime-grant",  # replaced before transport starts
                context_window=route.context_window,
                auto_compact_token_limit=route.context_window - route.max_output_tokens,
                codex_bin=settings.codex_bin,
                turn_timeout_seconds=settings.turn_timeout_seconds,
            )
            result = await run_xiaox_agent(
                run_id=resolved_id,
                task=task,
                system_prompt=_goal_instructions(system_prompt),
                config=config,
                binding_store=store,
                history=history,
                input_data=input_data,
                completion_mode=completion_mode,
                allowed_actions=actions,
                runtime_config={**route.runtime_identity(), "gate_required": gate is not None},
                answer_to_waiting_input=answer_to_waiting_input,
                tool_bridge=bridge,
                on_event=(lambda event: on_event(public_runtime_result(event)))
                if on_event
                else None,
            )
        result = dict(public_runtime_result(result))
        try:
            _record_request_result(store, resolved_id, request_key, result)
        except RECOVERABLE_ERRORS:
            return _request_persistence_uncertain(result)
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
    except (AgentModAuthorizationError, RuntimePolicyError, XiaoxBindingError) as exc:
        result = _failure(
            getattr(exc, "code", "runtime_policy_blocked"), str(exc), run_id=resolved_id
        )
        if isinstance(exc, RuntimeSetupError):
            result.update(
                failure_stage="runtime_setup",
                resume_required=bool(run_id),
                execution_state="blocked",
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
            result = _request_persistence_uncertain(result)
    return dict(public_runtime_result(result))


def run_runtime_task(**kwargs: Any) -> dict[str, Any]:
    """Synchronous product seam; keep authenticated context across an existing event loop."""
    from app.application.employee_runtime.agent_runner import _run_async

    return dict(_run_async(run_runtime_task_async(**kwargs)))


__all__ = ["public_runtime_result", "run_runtime_task", "run_runtime_task_async"]
