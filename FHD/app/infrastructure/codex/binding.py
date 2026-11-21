"""Run-scoped Codex grants on the existing durable AgentRun CAS repository.

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

_KEY = "codex_runtime"
_AUDIENCES = frozenset({"mcp", "model"})
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


class CodexBindingError(ValueError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


def _identity(run: AgentRun) -> str:
    context = run.metadata.get("runtime_context") or {}
    return canonical_digest({"owner": run.user_id, **{k: context.get(k) for k in _IDENTITY_FIELDS}})


@dataclass(frozen=True)
class CodexBinding:
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
class CodexGrant:
    binding: CodexBinding
    mcp_token: str
    model_token: str


class CodexBindingStore:
    def __init__(self, repository: SQLAlchemyAgentRunRepository | None = None) -> None:
        if repository is None:
            from app.application.agent_orchestrator.run_repository import get_agent_run_repository

            resolved = get_agent_run_repository()
        else:
            resolved = repository
        if not isinstance(resolved, SQLAlchemyAgentRunRepository):
            raise CodexBindingError("durable_storage_required", "Codex 运行需要持久化任务仓储")
        self.repository = resolved

    def get(self, run_id: str) -> CodexBinding:
        run = self.repository.get(run_id)
        if run is None or not isinstance(run.metadata.get(_KEY), dict):
            raise CodexBindingError("binding_missing", "Codex 运行绑定不存在")
        return CodexBinding(run)

    def update(
        self,
        run_id: str,
        mutation: Callable[[AgentRun, dict[str, Any]], None],
        *,
        generation: int | None = None,
    ) -> CodexBinding:
        """Retry only pure metadata changes, never replay a business callback."""
        for _ in range(8):
            previous = self.repository.get(run_id)
            if previous is None:
                raise CodexBindingError("binding_missing", "原任务不存在")
            current = copy.deepcopy(previous)
            metadata = current.metadata.setdefault(_KEY, {})
            if generation is not None:
                self._validate_current(current, metadata, generation)
            mutation(current, metadata)
            if self.repository.save_if_unchanged(current, previous):
                return self.get(run_id)
        raise CodexBindingError("binding_conflict", "任务状态已变化，请重新读取")

    @staticmethod
    def _validate_authority(run: AgentRun, metadata: dict[str, Any]) -> None:
        from app.application.agent_orchestrator.run_lifecycle import continuation_conversation_error
        from app.infrastructure.auth.agent_mod_scope import AgentModAuthorizationError, _bound_actor

        context = dict(run.metadata.get("runtime_context") or {})
        try:
            actor = _bound_actor(context)
        except AgentModAuthorizationError as exc:
            raise CodexBindingError("owner_changed", "原登录身份或业务范围已失效") from exc
        if str(actor.id) != str(run.user_id) or (
            metadata.get("identity_digest") and metadata["identity_digest"] != _identity(run)
        ):
            raise CodexBindingError("owner_changed", "运行绑定的账号、租户或能力范围已变化")
        if context.get("session_id") or context.get("conversation_id"):
            if type(context.get("_conversation_revision")) is not int:
                raise CodexBindingError("conversation_changed", "会话运行缺少可信历史版本")
            if error := continuation_conversation_error(run, context):
                raise CodexBindingError("conversation_changed", error)

    def create(
        self,
        run_id: str,
        *,
        ttl_seconds: int = 900,
        allowed_actions: list[str] | None = None,
        runtime_config: dict[str, Any] | None = None,
    ) -> CodexGrant:
        if type(ttl_seconds) is not int or not 30 <= ttl_seconds <= 3600:
            raise CodexBindingError("invalid_ttl", "运行授权有效期必须在 30 至 3600 秒之间")
        config = copy.deepcopy(runtime_config or {})
        if any(x in json.dumps(config).lower() for x in ('"api_key"', '"token"', '"secret"')):
            raise CodexBindingError("invalid_config", "运行配置不得持久化凭据")
        tokens = {audience: f"{run_id}.{secrets.token_urlsafe(32)}" for audience in _AUDIENCES}

        def grant(run: AgentRun, metadata: dict[str, Any]) -> None:
            self._validate_authority(run, metadata)
            self._validate_control(run)
            now = time.time()
            if metadata.get("coordinator_active") and float(metadata.get("expires_at", 0)) > now:
                raise CodexBindingError("binding_conflict", "该任务已有活动的 Codex 执行者")
            if metadata.get("model_reconciliation_required") or any(
                call.get("state") in {"reserved", "unknown"}
                for call in (metadata.get("model_requests") or {}).values()
            ):
                raise CodexBindingError("reconciliation_required", "原模型请求或计量结果尚待核对")
            if "runtime_config" in metadata and metadata["runtime_config"] != config:
                raise CodexBindingError("runtime_changed", "在途任务不能更换运行时或模型配置")
            normalized = sorted(set(allowed_actions)) if allowed_actions is not None else None
            if "allowed_actions" in metadata and metadata["allowed_actions"] != normalized:
                raise CodexBindingError("owner_changed", "续跑不能改变原工具授权范围")
            metadata.update(
                version=1,
                identity_digest=_identity(run),
                runtime_config=config,
                allowed_actions=normalized,
                coordinator_active=True,
                revoked=False,
                expires_at=now + ttl_seconds,
                generation=int(metadata.get("generation", 0)) + 1,
                token_hashes={a: hashlib.sha256(t.encode()).hexdigest() for a, t in tokens.items()},
            )
            metadata.setdefault("calls", {})
            run.metadata["runtime_type"] = "codex"

        binding = self.update(run_id, grant)
        return CodexGrant(binding, tokens["mcp"], tokens["model"])

    def _validate_control(self, run: AgentRun) -> None:
        from app.application.agent_orchestrator.task_models import mod_id_of_run, tenant_id_of_run

        original = run
        seen = set()
        for _ in range(16):
            if run.run_id in seen:
                raise CodexBindingError("owner_changed", "任务父子关联形成循环")
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
                raise CodexBindingError("owner_changed", "原父任务已丢失或归属发生变化")
            run = parent
        raise CodexBindingError("owner_changed", "任务父子关联层级超限")

    def _validate_run_control(self, run: AgentRun) -> None:
        if (
            run.metadata.get("non_retryable")
            or (run.metadata.get("recovery") or {}).get("state") == "manual_reconciliation_required"
        ):
            raise CodexBindingError("reconciliation_required", "业务执行结果尚未确定，禁止重放")
        command = self.repository.latest_task_control(run.run_id)
        if command is not None and command.status in {"requested", "applied"}:
            if command.action in {"cancel", "pause"}:
                code = "cancelled" if command.action == "cancel" else "paused"
                raise CodexBindingError(code, "任务已请求取消或暂停")
        if run.status in {"cancelled", "paused"}:
            raise CodexBindingError(run.status, "任务已取消或暂停")
        if run.status in {"completed", "failed", "rejected", "blocked"}:
            raise CodexBindingError("run_inactive", "任务当前状态不允许继续调用")

    def check_current(self, run_id: str, *, generation: int | None = None) -> CodexBinding:
        binding = self.get(run_id)
        self._validate_current(binding.run, binding.metadata, generation)
        return binding

    def _validate_current(
        self, run: AgentRun, metadata: dict[str, Any], generation: int | None
    ) -> None:
        self._validate_control(run)
        if metadata.get("revoked"):
            code = str(metadata.get("close_reason") or "token_invalid")
            raise CodexBindingError(code, "运行授权已结束")
        if float(metadata.get("expires_at", 0)) <= time.time():
            raise CodexBindingError("token_expired", "运行授权已过期")
        if generation is not None and metadata.get("generation") != generation:
            raise CodexBindingError("token_invalid", "运行授权已被更新")
        self._validate_authority(run, metadata)

    def authenticate(self, token: str, audience: str = "mcp") -> CodexBinding:
        if audience not in _AUDIENCES or not isinstance(token, str) or len(token) > 512:
            raise CodexBindingError("token_invalid", "运行凭据无效")
        run_id, separator, secret = token.partition(".")
        if not separator or len(secret) < 32:
            raise CodexBindingError("token_invalid", "运行凭据无效")
        binding = self.get(run_id)
        expected = str((binding.metadata.get("token_hashes") or {}).get(audience) or "")
        actual = hashlib.sha256(token.encode()).hexdigest()
        if not expected or not hmac.compare_digest(expected, actual):
            raise CodexBindingError("token_invalid", "运行凭据不属于此调用通道")
        return self.check_current(run_id, generation=binding.metadata.get("generation"))

    @contextmanager
    def scope(self, token: str, audience: str = "mcp") -> Iterator[CodexBinding]:
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
            raise CodexBindingError("scope_conflict", "无租户运行不能继承其他企业上下文")
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
    ) -> CodexBinding:
        if not isinstance(thread_id, str) or not thread_id.strip() or len(thread_id) > 256:
            raise CodexBindingError("invalid_thread", "Codex 会话标识无效")

        def record(run: AgentRun, metadata: dict[str, Any]) -> None:
            if metadata.get("thread_id") not in (None, "", thread_id):
                raise CodexBindingError("binding_conflict", "任务已绑定到另一 Codex 会话")
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
    ) -> tuple[dict[str, Any], bool]:
        from app.application.agent_orchestrator.budget import budget_exceeded_payload

        if not isinstance(call_id, str) or not call_id.strip() or len(call_id) > 160:
            raise CodexBindingError("invalid_call", "工具调用标识无效")
        if type(cost_units) is not int or cost_units < 0:
            raise CodexBindingError("invalid_cost", "工具计费契约无效")
        fingerprint = canonical_digest({"tool_id": tool_id, "action": action, "params": params})
        # Business identity belongs to the server. A fresh model call id must not
        # create a second copy of the same effect within the same authorized turn.
        operation = canonical_digest([run_id, fingerprint, call_id if read_only else "effect"])
        child_task_id = f"codex_{operation[:40]}"
        created = False

        def claim(run: AgentRun, metadata: dict[str, Any]) -> None:
            nonlocal created
            created = False
            if metadata.get("waiting_input"):
                raise CodexBindingError("waiting_user", "请先补充原任务所需信息")
            calls = metadata.setdefault("calls", {})
            existing = calls.get(call_id)
            if existing is not None:
                if existing["fingerprint"] != fingerprint:
                    raise CodexBindingError("call_conflict", "同一调用标识不能改变操作内容")
                return
            if len(calls) >= 256:
                raise CodexBindingError("call_limit", "任务工具调用已达到上限")
            prior = next((c for c in calls.values() if c["child_task_id"] == child_task_id), None)
            if prior is not None:
                calls[call_id] = copy.deepcopy(prior)
                return
            if any((c.get("receipt") or {}).get("pending_approval") for c in calls.values()):
                raise CodexBindingError("waiting_user", "请先处理原业务任务的审批")
            if any(
                c.get("state") not in {"completed", "failed", "cancelled", "rejected", "blocked"}
                for c in calls.values()
            ):
                raise CodexBindingError("call_in_progress", "原业务任务尚未结束，请先读取其回执")
            reserved = int(run.metadata.get("reserved_cost_units") or 0)
            if budget_exceeded_payload(
                run, additional_cost_units=reserved + cost_units, scope="codex_child"
            ):
                raise CodexBindingError("budget_exceeded", "父任务剩余预算不足，未创建业务任务")
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
    ) -> CodexBinding:
        def record(run: AgentRun, metadata: dict[str, Any]) -> None:
            call = metadata.get("calls", {}).get(call_id)
            if call is None:
                raise CodexBindingError("call_missing", "调用未持久登记")
            previous_receipt = call.get("receipt") or {}
            if receipt is not None and (previous_receipt.get("child_updated_at") or "") > (
                receipt.get("child_updated_at") or ""
            ):
                return
            if child_run_id:
                if call["child_run_id"] not in ("", child_run_id):
                    raise CodexBindingError("call_conflict", "调用已绑定另一业务任务")
                call["child_run_id"] = child_run_id
                call["state"] = "submitted"
            if receipt is not None:
                call["receipt"] = copy.deepcopy(receipt)
                call["state"] = str(receipt.get("status") or "unknown")
                amount = receipt.get("ai_cost_units_total", 0)
                if type(amount) is not int or amount < 0:
                    raise CodexBindingError("evidence_mismatch", "业务任务计费回执无效")
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
        from app.infrastructure.codex.tools import read_call_receipt

        binding = self.get(run_id)
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
    ) -> CodexBinding:
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
