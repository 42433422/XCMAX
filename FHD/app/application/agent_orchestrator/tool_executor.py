from __future__ import annotations

import math
import os
import time
from contextlib import nullcontext
from datetime import UTC, datetime, timedelta
from typing import Any

from app.application.agent_orchestrator.param_references import (
    UNRESOLVED_CODE,
    unresolved_placeholders,
)
from app.application.agent_orchestrator.run_models import AgentStep
from app.application.agent_orchestrator.tool_spec import validate_tool_call, validate_tool_result
from app.application.tool_execution_deadline import invocation_deadline
from app.utils.operational_errors import RECOVERABLE_ERRORS

_SQL_TENANT_SCOPED_TOOL_IDS = frozenset(
    {"business_db", "inventory", "shipment_records", "shipment_orders", "document_template", "purchase"}
)  # fmt: skip


_REVIEWED_QUERY_ACTIONS = frozenset({("finance", "ledger_query"), ("products", "exists")})
_QUERY_IDENTITY_FIELDS = frozenset(
    {
        "tenant_id",
        "user_id",
        "actor_id",
        "mod_id",
        "active_mod_id",
        "_runtime_context",
        "_actor_authorization",
        "_mod_authorization",
        "local_user_id",
        "authenticated_local_user_id",
    }
)


def _query_failure(code: str) -> dict[str, Any]:
    return {
        "success": False,
        "error_code": code,
        "outcome": "unknown",
        "retryable": False,
        "message": "查询未能在已授权数据范围内完成",
    }


def _reviewed_query_tenant(spec, params: dict, context: dict):
    """Two audited action policies, not a generic read-only authorization lane."""
    from fastapi import HTTPException

    from app.domain.shared_services.auth_service import get_auth_service
    from app.infrastructure.auth.agent_mod_scope import AgentModAuthorizationError, _bound_actor
    from app.infrastructure.auth.business_scope_gate import check_owned_business_permission

    try:
        actor = _bound_actor(context)
    except AgentModAuthorizationError:
        return None, _query_failure("tool_identity_required")
    if _QUERY_IDENTITY_FIELDS.intersection(params):
        return None, _query_failure("tool_identity_override")
    if spec is None:
        return None, _query_failure("tool_contract_unavailable")
    if (spec.tool_id, spec.action) == ("products", "exists"):
        try:
            tenant = check_owned_business_permission(actor, spec.permission)
            if str(context.get("tenant_id")) != str(tenant):
                return None, _query_failure("tool_scope_unavailable")
        except HTTPException:
            return None, _query_failure("tool_permission_denied")
    elif (spec.tool_id, spec.action) == ("finance", "ledger_query"):
        if spec.permission not in get_auth_service().get_user_permissions(actor):
            return None, _query_failure("tool_permission_denied")
    else:
        return None, _query_failure("tool_contract_unavailable")
    # _bound_actor verifies the signed execution tenant. Never choose an ambient
    # or default tenant to turn a hidden/empty result into confirmed absence.
    tenant = str(context.get("tenant_id") or "")
    if not tenant.isdigit() or int(tenant) <= 0:
        return None, _query_failure("tool_scope_unavailable")
    return int(tenant), None


def _dispatch_reviewed_query(tool_id: str, action: str, params: dict):
    from app.application.agent_orchestrator.worker_repository import WorkerLeaseLost
    from app.application.facades.tools_facade import execute_registered_workflow_tool
    from app.utils.operational_errors import INFRA_TRANSIENT

    try:
        return execute_registered_workflow_tool(tool_id, action, params)
    except (WorkerLeaseLost, TimeoutError, PermissionError):
        # Includes observation/receipt-persistence timeouts. Preserve their owner
        # cancellation and cleanup semantics; never reinterpret them as absence.
        raise
    except INFRA_TRANSIENT:
        return _query_failure("tool_exception")


from contextvars import ContextVar

_catalog_context = ContextVar("controlled_catalog_dispatch", default=None)


def controlled_tool_context(tool_id, action):
    held = _catalog_context.get()
    return dict(held[2]) if held and held[:2] == (tool_id, action) else None


def _execute_catalog(step, context):
    from app.application.agent_orchestrator.business_action_ledger import (
        BusinessActionLedger,
        canonical_hash,
    )
    from app.application.agent_orchestrator.catalog_product_edit import (
        existing_action,
        repository,
        source_claim_admission,
        trusted_original,
    )
    from app.application.agent_orchestrator.worker_repository import WorkerLeaseLost
    from app.application.tool_execution_deadline import check_invocation_deadline
    from app.infrastructure.tenant_scope import tenant_scope
    from app.mod_sdk.catalog_product_store import (
        execute_catalog_price,
        factory_for,
        verify_catalog_action,
    )

    params = dict(step.params)
    if _QUERY_IDENTITY_FIELDS.intersection(params) or any(
        k.startswith("_catalog") for k in context
    ):
        return _query_failure("catalog_identity_override")
    claim = None
    factory = None
    ledger = BusinessActionLedger(session_factory=repository()._session_factory)
    try:
        if existing_action(params, context):
            # Historical evidence does not require a new worker or permit HOST
            # reconciliation writes. UNKNOWN remains non-replayable.
            return verify_catalog_action(params, context)
        principal, _, _ = trusted_original(params, context, writing=True)
        check_invocation_deadline()
        # Source -> HOST is the effect path's existing lock order. Obtain the
        # source before claiming, so a concurrent reader cannot strand a fresh
        # ledger owner between claim and effect. Only this server write waits.
        factory = factory_for(principal, lock_timeout=5)
        with tenant_scope(int(principal.tenant_id)), factory.guard():
            check_invocation_deadline()
            trusted_original(params, context, writing=True)
            with source_claim_admission(factory, params, context):
                claim, existing = ledger.claim(step.tool_id, step.action, params, context)
            if existing is None:
                held = {
                    **context,
                    "_catalog_claim_owner": claim.owner,
                    "_controlled_params_sha256": canonical_hash(params),
                }
                token = _catalog_context.set((step.tool_id, step.action, held))
                try:
                    execute_catalog_price(params, step.action, source_factory=factory)
                finally:
                    _catalog_context.reset(token)
        # Existing claims still never dispatch; source-independent readback runs
        # after releasing the physical effect lock, not under a recursive lock.
        return verify_catalog_action(params, context, release=existing is None)
    except (WorkerLeaseLost, TimeoutError, PermissionError):
        raise
    except RECOVERABLE_ERRORS:
        if claim is not None:
            try:
                ledger.mark_unknown(claim, context)
            except RECOVERABLE_ERRORS:
                pass  # Lost session/claim leaves original durable claim non-replayable.
        return {**_query_failure("catalog_verification_required"), "reconciliation_required": True}
    finally:
        if factory is not None:
            factory.engine.dispose()


class AgentToolExecutor:
    def execute_with_deadline(self, step, *, runtime_context, deadline_monotonic):
        from app.application.agent_orchestrator.tool_process import execute_isolated

        if (
            step.tool_id == "dataset_rag"
            and step.action == "rebuild_index"
            and step.params.get("background", True)
        ):
            from app.domain.app_pure.dataset_rag_queue import ensure_host_worker

            ensure_host_worker()
        return execute_isolated(self, step, runtime_context, deadline_monotonic)

    def execute(
        self,
        step: AgentStep,
        *,
        runtime_context: dict[str, Any],
    ) -> dict[str, Any]:
        from app.application.facades.tools_facade import execute_registered_workflow_tool

        params = dict(step.params or {})
        validation = validate_tool_call(step.tool_id, step.action, params)
        if not validation.ok:
            return {
                "success": False,
                "error_code": validation.error_code,
                "message": validation.message,
                "tool_id": validation.tool_id,
                "action": validation.action,
            }
        leftover = unresolved_placeholders(params)
        if leftover:
            return {
                "success": False,
                "error_code": UNRESOLVED_CODE,
                "message": "参数包含未解析的占位符，已拒绝执行：" + "、".join(leftover)[:200],
                "tool_id": validation.tool_id,
                "action": validation.action or step.action,
            }
        if validation.tool_id == "catalog_products_v1":
            return _execute_catalog(step, dict(runtime_context or {}))
        reviewed_query = (validation.tool_id, validation.action) in _REVIEWED_QUERY_ACTIONS
        query_tenant = None
        if reviewed_query:
            query_tenant, denied = _reviewed_query_tenant(
                validation.spec, params, dict(runtime_context or {})
            )
            if denied is not None:
                return denied
        params["_runtime_context"] = dict(runtime_context or {})
        if (validation.tool_id, validation.action) == ("products", "exists"):
            for hint in ("service_source", "route_module"):
                params["_runtime_context"].pop(hint, None)
        action = validation.action or step.action
        runtime_tenant_raw = params["_runtime_context"].get("tenant_id")
        runtime_tenant_id: int | None = query_tenant
        if step.tool_id in _SQL_TENANT_SCOPED_TOOL_IDS and runtime_tenant_raw not in (None, ""):
            try:
                if isinstance(runtime_tenant_raw, bool) or not str(runtime_tenant_raw).isdigit():
                    raise ValueError
                runtime_tenant_id = int(runtime_tenant_raw)
                if runtime_tenant_id <= 0:
                    raise ValueError
            except (TypeError, ValueError):
                return {
                    "success": False,
                    "error_code": "invalid_tenant_context",
                    "message": "任务租户上下文无效，已拒绝执行工具",
                    "tool_id": validation.tool_id,
                    "action": action,
                }

        from app.infrastructure.auth.agent_mod_scope import (
            AgentModAuthorizationError,
            agent_mod_execution_scope,
        )
        from app.infrastructure.tenant_scope import owned_tenant_scope, tenant_scope

        try:
            # Durable/background Agent runs execute outside the originating HTTP
            # request. Restore the authenticated integer tenant recorded in
            # runtime_context so repository/raw-SQL boundaries keep their fail-closed
            # isolation. Dataset/document tools deliberately keep their own opaque
            # string tenant keys and must not be coerced here.
            with (
                agent_mod_execution_scope(params["_runtime_context"].get("_mod_authorization")),
                (
                    owned_tenant_scope(runtime_tenant_id)
                    if (validation.tool_id, action) == ("products", "exists")
                    else tenant_scope(runtime_tenant_id)
                )
                if runtime_tenant_id is not None
                else nullcontext(),
            ):
                result = (
                    _dispatch_reviewed_query(step.tool_id, action, params)
                    if reviewed_query
                    else execute_registered_workflow_tool(step.tool_id, action, params)
                )
        except AgentModAuthorizationError as exc:
            return {
                "success": False,
                "error_code": "mod_authorization_invalid",
                "message": str(exc),
                "tool_id": validation.tool_id,
                "action": action,
            }
        if not isinstance(result, dict):
            return {
                "success": False,
                "error_code": "tool_result_not_object",
                "message": "工具返回值必须是 object",
                "tool_id": validation.tool_id,
                "action": action,
                "raw_result_type": type(result).__name__,
            }

        output_validation = validate_tool_result(validation.tool_id, action, result)
        if not output_validation.ok:
            return {
                "success": False,
                "error_code": output_validation.error_code,
                "message": output_validation.message,
                "tool_id": output_validation.tool_id,
                "action": output_validation.action,
                "raw_success": result.get("success"),
                "raw_message": result.get("message") or result.get("error"),
                "raw_error_code": result.get("error_code"),
                "output_keys": sorted(str(key) for key in result.keys()),
            }
        return result


def execute_with_tool_deadline(
    executor: Any, step: AgentStep, *, runtime_context: dict[str, Any], timeout_seconds: float
) -> dict[str, Any]:
    """Propagate deadlines; workers restore scopes, strict custom adapters must be bounded."""
    timeout = float(timeout_seconds)
    if not math.isfinite(timeout) or timeout <= 0:
        return {"success": False, "error_code": "invalid_tool_timeout", "retryable": False}
    started = time.monotonic()
    deadline = started + timeout
    context = dict(runtime_context)
    context.update(
        {
            "timeout_seconds": timeout,
            "deadline_monotonic": deadline,
            "deadline_utc": (datetime.now(UTC) + timedelta(seconds=timeout)).isoformat(),
        }
    )
    bounded = getattr(executor, "execute_with_deadline", None)
    required = os.environ.get("XCAGI_AGENT_TOOL_HARD_TIMEOUT_REQUIRED", "").strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }
    if required and not callable(bounded):
        return {
            "success": False,
            "error_code": "tool_deadline_unsupported",
            "retryable": False,
            "message": "工具缺少可取消/隔离的有界执行适配器，已拒绝执行",
        }
    result: Any = None
    try:
        with invocation_deadline(deadline) as invocation:
            result = (
                bounded(step, runtime_context=context, deadline_monotonic=deadline)
                if callable(bounded)
                else executor.execute(step, runtime_context=context)
            )
    except TimeoutError:
        pass
    except RECOVERABLE_ERRORS as exc:
        if not invocation.uncertain:
            raise
        result = {
            "error_code": "tool_exception_after_unknown_io",
            "exception_type": type(exc).__name__,
        }
    else:
        if (
            time.monotonic() <= deadline
            and isinstance(result, dict)
            and not invocation.uncertain
            and result.get("outcome") != "unknown"
            and not result.get("reconciliation_required")
        ):
            if (
                step.tool_id == "business_db"
                and step.action == "write"
                and result.get("success") is True
                and isinstance(step.params.get("payload"), dict)
            ):
                from app.domain.shared_services.tools_workflow_common import (
                    _remember_business_db_target,
                )

                _remember_business_db_target(
                    context,
                    str(step.params.get("entity") or ""),
                    str(step.params.get("operation") or "create"),
                    result,
                )
            return result
    return {
        "success": False,
        "error_code": "tool_timeout_unknown",
        "reconciliation_evidence": result if isinstance(result, dict) else {},
        "io_reconciliation": list(invocation.uncertain),
        "outcome": "unknown",
        "retryable": False,
        "reconciliation_required": True,
        "message": "工具超时，业务结果未知；必须核对原调用，不可自动重试",
    }
