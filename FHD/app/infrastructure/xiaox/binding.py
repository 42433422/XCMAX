"""Run-scoped Xiaox grants on the existing durable AgentRun CAS repository.

Only product control-plane glue lives here. The external runtime never owns
identity, task approval, or business receipts. Tokens are audience-separated and
only their hashes are persisted; resuming a thread cannot resurrect authority.
"""

from __future__ import annotations

import copy
import hashlib
import hmac
import json
import secrets
import time
from collections.abc import Callable, Iterator
from contextlib import ExitStack, contextmanager
from dataclasses import dataclass
from typing import Any

from app.application.agent_orchestrator.run_models import AgentRun, utc_now_iso
from app.application.agent_orchestrator.run_sql_repository import SQLAlchemyAgentRunRepository
from app.domain.task_lifecycle.agent_runtime_contract import canonical_digest as canonical_digest

_KEY = "xiaox_runtime"
_AUDIENCES = frozenset({"mcp", "model"})
_MAX_TOOL_INVOCATIONS = 1024
_TOOL_LOOP_REPETITIONS = 8
_TOOL_LOOP_MAX_PERIOD = 4
_TOOL_STOP_MESSAGES = {
    "tool_call_budget_exhausted": "原任务工具调用次数已达上限，已确认回执保留",
    "tool_loop_detected": "检测到重复工具调用且结果无进展，已确认回执保留",
}
_IDENTITY_FIELDS = (
    "user_id",
    "actor_id",
    "tenant_id",
    "mod_id",
    "active_mod_id",
    "_actor_authorization",
    "_mod_authorization",
    "session_id",
    "conversation_id",
    "_conversation_revision",
    "workspace_id",
    "workspace_root",
    "parent_run_id",
    "parent_task_id",
    "root_run_id",
    "employee_id",
    "employee_tool_allowlist",
    "_employee_gate_contract",
)


def has_legacy_runtime_binding(run: AgentRun) -> bool:
    """Detect unreconciled persisted runtime protocols, including partial upgrades."""
    return (
        run.intent == "codex.runtime"
        or run.metadata.get("runtime_type") == "codex"
        or "codex_runtime" in run.metadata
        or any(
            key in run.metadata
            for key in (
                "_codex_queued_request",
                "_codex_system_prompt",
                "_codex_input_data",
                "_codex_history",
            )
        )
        or "codex_result" in run.final_output
    )


class XiaoxBindingError(ValueError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


def _tool_observation(name: str, result: dict[str, Any]) -> dict[str, Any]:
    if name != "execute_action":
        return result
    # Compare business facts, not fresh child/call IDs or accounting timestamps.
    # Preserve the entire tool output: changing business data is real progress.
    return {
        **{
            key: result.get(key)
            for key in ("success", "verified", "status", "execution", "error_code", "artifacts")
        },
        "tool_calls": [
            {key: row.get(key) for key in ("tool_id", "action", "params", "output", "status")}
            for row in result.get("tool_calls") or []
        ],
    }


def _identity(run: AgentRun) -> str:
    context = run.metadata.get("runtime_context") or {}
    identity = {"owner": run.user_id, **{k: context.get(k) for k in _IDENTITY_FIELDS}}
    if "_credential_authorization" in context:
        identity["_credential_authorization"] = context["_credential_authorization"]
    return canonical_digest(identity)


@dataclass(frozen=True)
class XiaoxBinding:
    run: AgentRun

    @property
    def run_id(self) -> str:
        return self.run.run_id

    @property
    def context(self) -> dict[str, Any]:
        return copy.deepcopy(self.run.metadata.get("runtime_context") or {})

    @property
    def metadata(self) -> dict[str, Any]:
        return copy.deepcopy(self.run.metadata[_KEY])

    @property
    def thread_id(self) -> str:
        return str(self.metadata.get("thread_id") or "")


@dataclass(frozen=True)
class XiaoxGrant:
    binding: XiaoxBinding
    mcp_token: str
    model_token: str


class XiaoxBindingStore:
    def __init__(self, repository: SQLAlchemyAgentRunRepository | None = None) -> None:
        if repository is None:
            from app.application.agent_orchestrator.run_repository import get_agent_run_repository

            resolved = get_agent_run_repository()
        else:
            resolved = repository
        if not isinstance(resolved, SQLAlchemyAgentRunRepository):
            raise XiaoxBindingError("durable_storage_required", "Xiaox 运行需要持久化任务仓储")
        self.repository = resolved

    @staticmethod
    def _reject_legacy_binding(run: AgentRun) -> None:
        # Do not initialize a second ledger over a pre-upgrade binding,
        # including cleanup/error paths, before reconciling its effects.
        if has_legacy_runtime_binding(run):
            raise XiaoxBindingError(
                "runtime_migration_required", "原运行绑定尚待迁移，禁止重建运行状态"
            )

    def get(self, run_id: str) -> XiaoxBinding:
        run = self.repository.get(run_id)
        if run is None:
            raise XiaoxBindingError("binding_missing", "Xiaox 运行绑定不存在")
        self._reject_legacy_binding(run)
        if not isinstance(run.metadata.get(_KEY), dict):
            raise XiaoxBindingError("binding_missing", "Xiaox 运行绑定不存在")
        return XiaoxBinding(run)

    def update(
        self,
        run_id: str,
        mutation: Callable[[AgentRun, dict[str, Any]], None],
        *,
        generation: int | None = None,
    ) -> XiaoxBinding:
        """Retry only pure metadata changes, never replay a business callback."""
        for _ in range(8):
            previous = self.repository.get(run_id)
            if previous is None:
                raise XiaoxBindingError("binding_missing", "原任务不存在")
            self._reject_legacy_binding(previous)
            current = copy.deepcopy(previous)
            metadata = current.metadata.setdefault(_KEY, {})
            if generation is not None:
                self._validate_current(current, metadata, generation)
            mutation(current, metadata)
            if self.repository.save_if_unchanged(current, previous):
                return self.get(run_id)
        raise XiaoxBindingError("binding_conflict", "任务状态已变化，请重新读取")

    @staticmethod
    def _validate_goal(run: AgentRun, metadata: dict[str, Any]) -> str:
        from app.domain.task_lifecycle.agent_runtime_contract import validate_runtime_goal

        legacy_unstarted = (
            "version" not in metadata
            and type(metadata.get("generation")) is int
            and metadata["generation"] == 0
            and metadata.get("runtime_status") == "not_started"
            and metadata.get("coordinator_active") is False
            and metadata.get("revoked") is True
            and not any(
                metadata.get(key)
                for key in (
                    "calls",
                    "token_hashes",
                    "thread_id",
                    "model_requests",
                    "active_started_at",
                    "active_seconds",
                    "model_reconciliation_required",
                )
            )
        )
        if (
            metadata
            and not legacy_unstarted
            and (type(metadata.get("version")) is not int or metadata["version"] != 1)
        ):
            raise XiaoxBindingError(
                "runtime_contract_unsupported", "原运行绑定版本不受支持，请保留原件并核对兼容性"
            )
        if not run.metadata.get("runtime_goal_contract"):
            if metadata.get("calls") or run.metadata.get("runtime_goal_digest"):
                raise XiaoxBindingError("goal_changed", "原任务目标合同已丢失")
            return ""  # Initial host binding only; claim_call requires the contract.
        try:
            digest = validate_runtime_goal(run)
        except (TypeError, ValueError, KeyError) as exc:
            raise XiaoxBindingError("goal_changed", "原任务目标或授权范围已变化") from exc
        if metadata.get("goal_digest", digest) not in {"", digest}:
            raise XiaoxBindingError("goal_changed", "原任务目标合同不能改变")
        return digest

    @staticmethod
    def _validate_authority(run: AgentRun, metadata: dict[str, Any]) -> None:
        from app.application.agent_orchestrator.run_lifecycle import continuation_conversation_error
        from app.infrastructure.auth.agent_mod_scope import AgentModAuthorizationError, _bound_actor

        context = dict(run.metadata.get("runtime_context") or {})
        try:
            actor = _bound_actor(context)
        except AgentModAuthorizationError as exc:
            raise XiaoxBindingError("owner_changed", "原登录身份或业务范围已失效") from exc
        if str(actor.id) != str(run.user_id) or (
            metadata.get("identity_digest") and metadata["identity_digest"] != _identity(run)
        ):
            raise XiaoxBindingError("owner_changed", "运行绑定的账号、租户或能力范围已变化")
        if "_credential_authorization" in context:
            from app.application.aiopen.service import api_key_execution_context_current

            try:
                credential_current = api_key_execution_context_current(context)
            except OSError as exc:
                raise XiaoxBindingError("owner_changed", "原调用凭据无法核验") from exc
            if not credential_current:
                raise XiaoxBindingError("owner_changed", "原调用凭据已撤销、过期或授权范围已变化")
        if context.get("session_id") or context.get("conversation_id"):
            if type(context.get("_conversation_revision")) is not int:
                raise XiaoxBindingError("conversation_changed", "会话运行缺少可信历史版本")
            if error := continuation_conversation_error(run, context):
                raise XiaoxBindingError("conversation_changed", error)
        XiaoxBindingStore._validate_goal(run, metadata)

    def create(
        self,
        run_id: str,
        *,
        ttl_seconds: int = 900,
        allowed_actions: list[str] | None = None,
        runtime_config: dict[str, Any] | None = None,
    ) -> XiaoxGrant:
        if type(ttl_seconds) is not int or not 30 <= ttl_seconds <= 3600:
            raise XiaoxBindingError("invalid_ttl", "运行授权有效期必须在 30 至 3600 秒之间")
        config = copy.deepcopy(runtime_config or {})
        if any(x in json.dumps(config).lower() for x in ('"api_key"', '"token"', '"secret"')):
            raise XiaoxBindingError("invalid_config", "运行配置不得持久化凭据")
        tokens = {audience: f"{run_id}.{secrets.token_urlsafe(32)}" for audience in _AUDIENCES}

        def grant(run: AgentRun, metadata: dict[str, Any]) -> None:
            self._validate_authority(run, metadata)
            self._validate_control(run)
            now = time.time()
            if metadata.get("coordinator_active") and float(metadata.get("expires_at", 0)) > now:
                raise XiaoxBindingError("binding_conflict", "该任务已有活动的 Xiaox 执行者")
            if metadata.get("model_reconciliation_required") or any(
                call.get("state") in {"reserved", "unknown"}
                for call in (metadata.get("model_requests") or {}).values()
            ):
                raise XiaoxBindingError("reconciliation_required", "原模型请求或计量结果尚待核对")
            if "runtime_config" in metadata and metadata["runtime_config"] != config:
                raise XiaoxBindingError("runtime_changed", "在途任务不能更换运行时或模型配置")
            normalized = sorted(set(allowed_actions)) if allowed_actions is not None else None
            if "allowed_actions" in metadata and metadata["allowed_actions"] != normalized:
                raise XiaoxBindingError("owner_changed", "续跑不能改变原工具授权范围")
            metadata.update(
                version=1,
                identity_digest=_identity(run),
                goal_digest=self._validate_goal(run, metadata),
                runtime_config=config,
                allowed_actions=normalized,
                coordinator_active=True,
                revoked=False,
                expires_at=now + ttl_seconds,
                generation=int(metadata.get("generation", 0)) + 1,
                token_hashes={a: hashlib.sha256(t.encode()).hexdigest() for a, t in tokens.items()},
            )
            metadata.setdefault("calls", {})
            run.metadata["runtime_type"] = "xiaox"

        binding = self.update(run_id, grant)
        return XiaoxGrant(binding, tokens["mcp"], tokens["model"])

    def _validate_control(self, run: AgentRun) -> None:
        from app.application.agent_orchestrator.task_models import mod_id_of_run, tenant_id_of_run

        original = run
        seen = set()
        for _ in range(16):
            if run.run_id in seen:
                raise XiaoxBindingError("owner_changed", "任务父子关联形成循环")
            seen.add(run.run_id)
            self._validate_run_control(run)
            parent_id = str((run.metadata.get("runtime_context") or {}).get("parent_run_id") or "")
            if not parent_id:
                return
            parent = self.repository.get(parent_id)
            if (
                parent is None
                or parent.user_id != original.user_id
                or (
                    tenant_id_of_run(parent) != tenant_id_of_run(original)
                    or mod_id_of_run(parent) != mod_id_of_run(original)
                )
            ):
                raise XiaoxBindingError("owner_changed", "原父任务已丢失或归属发生变化")
            run = parent
        raise XiaoxBindingError("owner_changed", "任务父子关联层级超限")

    def _validate_run_control(self, run: AgentRun) -> None:
        if (
            run.metadata.get("non_retryable")
            or (run.metadata.get("recovery") or {}).get("state") == "manual_reconciliation_required"
        ):
            raise XiaoxBindingError("reconciliation_required", "业务执行结果尚未确定，禁止重放")
        command = self.repository.latest_task_control(run.run_id)
        if command is not None and command.status in {"requested", "applied"}:
            if command.action in {"cancel", "pause"}:
                code = "cancelled" if command.action == "cancel" else "paused"
                raise XiaoxBindingError(code, "任务已请求取消或暂停")
        if run.status in {"cancelled", "paused"}:
            raise XiaoxBindingError(run.status, "任务已取消或暂停")
        if run.status in {"completed", "failed", "rejected", "blocked"}:
            raise XiaoxBindingError("run_inactive", "任务当前状态不允许继续调用")

    def check_current(self, run_id: str, *, generation: int | None = None) -> XiaoxBinding:
        binding = self.get(run_id)
        self._validate_current(binding.run, binding.metadata, generation)
        return binding

    def _validate_current(
        self, run: AgentRun, metadata: dict[str, Any], generation: int | None
    ) -> None:
        self._validate_control(run)
        if metadata.get("revoked"):
            code = str(metadata.get("close_reason") or "token_invalid")
            raise XiaoxBindingError(code, "运行授权已结束")
        if float(metadata.get("expires_at", 0)) <= time.time():
            raise XiaoxBindingError("token_expired", "运行授权已过期")
        if metadata.get("active_started_at") is not None and (
            float(metadata.get("deadline_at", 0)) <= time.time()
        ):
            raise XiaoxBindingError("runtime_budget_exhausted", "原任务运行时长预算已耗尽")
        if generation is not None and metadata.get("generation") != generation:
            raise XiaoxBindingError("token_invalid", "运行授权已被更新")
        self._validate_authority(run, metadata)

    def authenticate(self, token: str, audience: str = "mcp") -> XiaoxBinding:
        if audience not in _AUDIENCES or not isinstance(token, str) or len(token) > 512:
            raise XiaoxBindingError("token_invalid", "运行凭据无效")
        run_id, separator, secret = token.partition(".")
        if not separator or len(secret) < 32:
            raise XiaoxBindingError("token_invalid", "运行凭据无效")
        binding = self.get(run_id)
        expected = str((binding.metadata.get("token_hashes") or {}).get(audience) or "")
        actual = hashlib.sha256(token.encode()).hexdigest()
        if not expected or not hmac.compare_digest(expected, actual):
            raise XiaoxBindingError("token_invalid", "运行凭据不属于此调用通道")
        binding = self.check_current(run_id, generation=binding.metadata.get("generation"))
        reason = (binding.metadata.get("tool_call_limit") or {}).get("reason")
        if audience == "model" and reason in _TOOL_STOP_MESSAGES:
            raise XiaoxBindingError(reason, _TOOL_STOP_MESSAGES[reason])
        return binding

    def admit_tool_invocation(
        self, run_id: str, name: str, arguments: dict[str, Any], *, generation: int
    ) -> XiaoxBinding:
        """Charge every MCP operation to the original SQL task, including discovery."""
        from app.infrastructure.xiaox.tool_names import XIAOX_TOOL_NAMES

        if name not in XIAOX_TOOL_NAMES or not isinstance(arguments, dict):
            raise XiaoxBindingError("invalid_arguments", "运行工具或参数无效")
        denied = ""

        def admit(run: AgentRun, metadata: dict[str, Any]) -> None:
            nonlocal denied
            denied = ""
            count = metadata.get("tool_invocation_count", len(metadata.get("calls") or {}))
            if type(count) is not int or count < 0:
                raise XiaoxBindingError("invalid_budget", "原任务工具调用计数无效")
            reason = (metadata.get("tool_call_limit") or {}).get("reason")
            if count >= _MAX_TOOL_INVOCATIONS:
                denied = "tool_call_budget_exhausted"
            elif reason in _TOOL_STOP_MESSAGES and name not in {"task_evidence", "request_input"}:
                denied = reason
            if denied:
                if reason != denied:
                    metadata["tool_call_limit"] = {"reason": denied, "used_tool_calls": count}
                    run.add_event(
                        "runtime.tool.stopped", _TOOL_STOP_MESSAGES[denied], {"reason": denied}
                    )
                return
            metadata["tool_invocation_count"] = count + 1

        binding = self.update(run_id, admit, generation=generation)
        if denied:
            raise XiaoxBindingError(denied, _TOOL_STOP_MESSAGES[denied])
        return binding

    def observe_tool_result(
        self,
        run_id: str,
        name: str,
        arguments: dict[str, Any],
        result: dict[str, Any],
        *,
        generation: int,
    ) -> None:
        """Bound repeated observations without treating receipt polling as a loop."""
        if (
            name == "request_input"
            or result.get("reconciliation_required")
            or result.get("status") == "unknown"
        ):
            return
        polling = name == "task_evidence" or (
            result.get("in_progress")
            or result.get("pending_approval")
            or result.get("needs_user_input")
            or result.get("status") in {"claimed", "running", "waiting_user", "waiting_approval"}
        )
        signature = canonical_digest(
            [
                name,
                {k: v for k, v in arguments.items() if k != "call_id"},
                _tool_observation(name, result),
            ]
        )

        def observe(run: AgentRun, metadata: dict[str, Any]) -> None:
            from app.domain.task_lifecycle.agent_runtime_contract import goal_answers

            answers = canonical_digest(goal_answers(run))
            history = list(metadata.get("tool_observation_history") or [])
            if metadata.get("tool_observation_answers", answers) != answers:
                history = []
            if polling:
                # New asynchronous work or a changed original receipt is progress;
                # repeated polling of the same receipt neither clears nor grows a loop.
                call = (metadata.get("calls") or {}).get(arguments.get("call_id")) or {}
                key = str(call.get("child_task_id") or result.get("task_id") or "")
                observations = metadata.setdefault("tool_receipt_observations", {})
                receipt_digest = canonical_digest(_tool_observation("execute_action", result))
                if key and observations.get(key) != receipt_digest:
                    observations[key] = receipt_digest
                    history = []
                metadata.update(tool_observation_history=history, tool_observation_answers=answers)
                return
            history = (history + [signature])[-(_TOOL_LOOP_MAX_PERIOD * _TOOL_LOOP_REPETITIONS) :]
            metadata.update(tool_observation_history=history, tool_observation_answers=answers)
            for period in range(1, _TOOL_LOOP_MAX_PERIOD + 1):
                size = period * _TOOL_LOOP_REPETITIONS
                if (
                    len(history) >= size
                    and history[-size:] == history[-period:] * _TOOL_LOOP_REPETITIONS
                ):
                    if not metadata.get("tool_call_limit"):
                        metadata["tool_call_limit"] = {
                            "reason": "tool_loop_detected",
                            "period": period,
                            "repetitions": _TOOL_LOOP_REPETITIONS,
                            "used_tool_calls": metadata.get("tool_invocation_count", 0),
                        }
                        run.add_event(
                            "runtime.tool.stopped",
                            _TOOL_STOP_MESSAGES["tool_loop_detected"],
                            {"reason": "tool_loop_detected", "period": period},
                        )
                    break

        self.update(run_id, observe, generation=generation)

    @contextmanager
    def scope(self, token: str, audience: str = "mcp") -> Iterator[XiaoxBinding]:
        """Rebuild request context for every callback, including reused HTTP connections."""
        from app.domain.aiopen.principal import ScreenPrincipal
        from app.http.request_context import reset_current_http_request, set_current_http_request
        from app.infrastructure.aiopen.principal_context import screen_principal_scope
        from app.infrastructure.auth.agent_mod_scope import agent_mod_execution_scope
        from app.infrastructure.llm.model_admission import model_rate_limit_scope
        from app.infrastructure.request_context import reset_current_request, set_current_request
        from app.infrastructure.tenant_scope import (
            owned_tenant_id,
            owned_tenant_scope,
            tenant_scope,
        )
        from app.request_active_mod_ctx import (
            reset_request_active_mod_id,
            set_request_active_mod_id,
        )

        binding = self.authenticate(token, audience)
        context = binding.context
        tenant = str(context.get("tenant_id") or "")
        if not (tenant.isdigit() and int(tenant) > 0) and owned_tenant_id() is not None:
            raise XiaoxBindingError("scope_conflict", "无租户运行不能继承其他企业上下文")
        with ExitStack() as stack:
            stack.callback(reset_current_http_request, set_current_http_request(None))
            stack.callback(reset_current_request, set_current_request(None))
            stack.callback(reset_request_active_mod_id, set_request_active_mod_id(""))
            stack.enter_context(agent_mod_execution_scope(context.get("_mod_authorization")))
            stack.enter_context(
                owned_tenant_scope(int(tenant))
                if tenant.isdigit() and int(tenant) > 0
                else tenant_scope(None)
            )
            stack.enter_context(
                screen_principal_scope(ScreenPrincipal.from_ids(binding.run.user_id, tenant))
            )
            stack.enter_context(
                model_rate_limit_scope({**context, "tenant_id": tenant or "unscoped"})
            )
            yield binding

    def record_thread(
        self, run_id: str, thread_id: str, *, generation: int | None = None
    ) -> XiaoxBinding:
        if not isinstance(thread_id, str) or not thread_id.strip() or len(thread_id) > 256:
            raise XiaoxBindingError("invalid_thread", "Xiaox 会话标识无效")

        def record(run: AgentRun, metadata: dict[str, Any]) -> None:
            if metadata.get("thread_id") not in (None, "", thread_id):
                raise XiaoxBindingError("binding_conflict", "任务已绑定到另一 Xiaox 会话")
            metadata["thread_id"] = thread_id

        return self.update(run_id, record, generation=generation)

    def claim_call(
        self,
        run_id: str,
        call_id: str,
        *,
        tool_id: str,
        action: str,
        params: dict[str, Any],
        read_only: bool,
        generation: int,
        cost_units: int = 0,
        isolated_artifact: bool = False,
    ) -> tuple[dict[str, Any], bool]:
        from app.application.agent_orchestrator.budget import budget_exceeded_payload

        if not isinstance(call_id, str) or not call_id.strip() or len(call_id) > 160:
            raise XiaoxBindingError("invalid_call", "工具调用标识无效")
        if type(cost_units) is not int or cost_units < 0:
            raise XiaoxBindingError("invalid_cost", "工具计费契约无效")
        fingerprint = canonical_digest({"tool_id": tool_id, "action": action, "params": params})
        # Business identity belongs to the server. A fresh model call id must not
        # create a second copy of the same effect within the same authorized turn.
        operation = canonical_digest([run_id, fingerprint, call_id if read_only else "effect"])
        # Task identity is a persistence protocol, not the display name.
        child_task_id = f"codex_{operation[:40]}"
        renamed_task_id = f"xiaox_{operation[:40]}"
        created = False

        def claim(run: AgentRun, metadata: dict[str, Any]) -> None:
            nonlocal created
            created = False
            if metadata.get("waiting_input"):
                raise XiaoxBindingError("waiting_user", "请先补充原任务所需信息")
            if not run.metadata.get("runtime_goal_contract"):
                raise XiaoxBindingError("goal_required", "原任务缺少持久目标合同")
            if not read_only and run.metadata.get("runtime_completion_mode") == "reply":
                raise XiaoxBindingError("goal_mismatch", "回复任务不能申请业务写入")
            calls = metadata.setdefault("calls", {})
            existing = calls.get(call_id)
            if existing is not None and existing["fingerprint"] != fingerprint:
                raise XiaoxBindingError("call_conflict", "同一调用标识不能改变操作内容")
            matches = [
                c for c in calls.values() if c["child_task_id"] in (child_task_id, renamed_task_id)
            ]
            if len({c["child_task_id"] for c in matches}) > 1 or any(
                c["fingerprint"] != fingerprint for c in matches
            ):
                raise XiaoxBindingError(
                    "reconciliation_required", "同一业务操作存在冲突的历史子任务，禁止重放"
                )
            if existing is not None:
                return
            if len(calls) >= 256:
                raise XiaoxBindingError("call_limit", "任务工具调用已达到上限")
            if matches:
                calls[call_id] = copy.deepcopy(matches[0])
                return
            level = (run.metadata.get("runtime_context") or {}).get("execution_autonomy_level")
            # Isolated file outputs retain write receipts and reservations, but
            # they do not spend the enterprise's business mutation allowance.
            business_write = not read_only and not isolated_artifact
            if business_write and level == 1:
                raise XiaoxBindingError(
                    "autonomy_level_denied", "本企业当前为 L1，仅可对话和只读查询"
                )
            if (
                business_write
                and level == 2
                and (
                    tool_id in {"xcmax_workflow", "employee"}
                    or any(
                        not (item.get("read_only") or item.get("isolated_artifact"))
                        for item in calls.values()
                    )
                )
            ):
                raise XiaoxBindingError(
                    "autonomy_level_denied", "L2 每项任务仅允许一次明确的业务操作"
                )
            # Existing calls above only read their durable receipt. New work must
            # wait until the model that proposed it has a settled usage receipt.
            model_calls = (metadata.get("model_requests") or {}).values()
            if metadata.get("model_reconciliation_required") or any(
                item.get("state") == "unknown" for item in model_calls
            ):
                raise XiaoxBindingError(
                    "reconciliation_required", "原模型计量结果尚待核对，未创建业务任务"
                )
            if any(item.get("state") == "reserved" for item in model_calls):
                raise XiaoxBindingError(
                    "call_in_progress", "原模型请求尚未结束，请先等待其计量回执"
                )
            if any((c.get("receipt") or {}).get("pending_approval") for c in calls.values()):
                raise XiaoxBindingError("waiting_user", "请先处理原业务任务的审批")
            if any(
                c.get("state") not in {"completed", "failed", "cancelled", "rejected", "blocked"}
                for c in calls.values()
            ):
                raise XiaoxBindingError("call_in_progress", "原业务任务尚未结束，请先读取其回执")
            reserved = int(run.metadata.get("reserved_cost_units") or 0)
            if budget_exceeded_payload(
                run, additional_cost_units=reserved + cost_units, scope="xiaox_child"
            ):
                raise XiaoxBindingError("budget_exceeded", "父任务剩余预算不足，未创建业务任务")
            budget = run.metadata.get("ai_cost_budget_units")
            capacity = (
                None
                if budget is None
                else max(
                    int(budget) - int(run.metadata.get("ai_cost_units_total") or 0) - reserved, 0
                )
            )
            # Give the only active child its entire remaining envelope. Its
            # nested model/tool calls cannot race the parent model for that money.
            reservation = cost_units if capacity is None else capacity
            run.metadata["reserved_cost_units"] = reserved + reservation
            calls[call_id] = {
                "fingerprint": fingerprint,
                "tool_id": tool_id,
                "action": action,
                "params": copy.deepcopy(params),
                "child_task_id": child_task_id,
                "child_run_id": "",
                "state": "claimed",
                "receipt": {},
                "read_only": read_only,
                **({"isolated_artifact": True} if isolated_artifact else {}),
                "created_at": utc_now_iso(),
                "generation": generation,
                "reservation_units": reservation,
                "reservation_state": "held",
                "accounted_cost_units": 0,
                "budget_units": capacity,
            }
            created = True

        binding = self.update(run_id, claim, generation=generation)
        return binding.metadata["calls"][call_id], created

    def record_call(
        self,
        run_id: str,
        call_id: str,
        *,
        child_run_id: str = "",
        receipt: dict[str, Any] | None = None,
    ) -> XiaoxBinding:
        def record(run: AgentRun, metadata: dict[str, Any]) -> None:
            self._validate_goal(run, metadata)
            call = metadata.get("calls", {}).get(call_id)
            if call is None:
                raise XiaoxBindingError("call_missing", "调用未持久登记")
            original_run_id = call["child_run_id"] or child_run_id
            if receipt is not None and (
                receipt.get("task_id") != call["child_task_id"]
                or receipt.get("run_id") != original_run_id
                or (not original_run_id and receipt.get("status") not in {"claimed", "unknown"})
            ):
                raise XiaoxBindingError("evidence_mismatch", "业务回执与原任务或执行标识不一致")
            previous_receipt = call.get("receipt") or {}
            if (
                receipt is not None
                and (receipt.get("status") != "unknown" or receipt.get("child_updated_at"))
                and (previous_receipt.get("child_updated_at") or "")
                > (receipt.get("child_updated_at") or "")
            ):
                # A delayed observation cannot reverse newer child evidence.
                # Unversioned unknowns (for example a missing child) still block.
                return
            if child_run_id:
                if call["child_run_id"] not in ("", child_run_id):
                    raise XiaoxBindingError("call_conflict", "调用已绑定另一业务任务")
                call["child_run_id"] = child_run_id
                call["state"] = "submitted"
            if receipt is not None:
                call["receipt"] = copy.deepcopy(receipt)
                call["state"] = str(receipt.get("status") or "unknown")
                amount = receipt.get("ai_cost_units_total", 0)
                if type(amount) is not int or amount < 0:
                    raise XiaoxBindingError("evidence_mismatch", "业务任务计费回执无效")
                delta = max(amount - int(call.get("accounted_cost_units") or 0), 0)
                reserve = int(call.get("reservation_units") or 0)
                release = min(reserve, delta)
                if call["state"] in {"completed", "failed", "cancelled", "rejected", "blocked"}:
                    release = reserve
                    call["reservation_state"] = "settled"
                call["reservation_units"] = reserve - release
                call["accounted_cost_units"] = max(
                    amount, int(call.get("accounted_cost_units") or 0)
                )
                run.metadata["reserved_cost_units"] = max(
                    int(run.metadata.get("reserved_cost_units") or 0) - release, 0
                )
                run.metadata["ai_cost_units_total"] = (
                    int(run.metadata.get("ai_cost_units_total") or 0) + delta
                )
                from app.application.agent_orchestrator.budget import refresh_ai_budget_metadata

                refresh_ai_budget_metadata(run)
                if call["state"] == "unknown":
                    run.metadata["non_retryable"] = True
                    run.metadata["recovery"] = {"state": "manual_reconciliation_required"}
            for key, row in metadata["calls"].items():
                if key != call_id and row["child_task_id"] == call["child_task_id"]:
                    metadata["calls"][key] = copy.deepcopy(call)

        return self.update(run_id, record)

    def receipt_snapshot(self, run_id: str) -> list[dict[str, Any]]:
        from app.infrastructure.xiaox.receipts import read_call_receipt

        binding = self.get(run_id)
        self._validate_goal(binding.run, binding.metadata)
        receipts = []
        for call_id, call in binding.metadata.get("calls", {}).items():
            receipt = read_call_receipt(self, binding, call)
            saved = self.record_call(
                run_id, call_id, child_run_id=receipt.get("run_id", ""), receipt=receipt
            )
            receipts.append({"call_id": call_id, **saved.metadata["calls"][call_id]})
        return receipts

    def close(
        self,
        run_id: str,
        reason: str = "cancelled",
        *,
        generation: int | None = None,
        release_coordinator: bool = True,
    ) -> XiaoxBinding:
        def revoke(run: AgentRun, metadata: dict[str, Any]) -> None:
            if generation is not None and metadata.get("generation") != generation:
                return
            metadata.update(
                revoked=True,
                coordinator_active=False
                if release_coordinator
                else bool(metadata.get("coordinator_active")),
                token_hashes={},
                close_reason=reason,
                closed_at=utc_now_iso(),
            )

        return self.update(run_id, revoke)
