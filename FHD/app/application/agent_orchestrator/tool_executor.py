from __future__ import annotations

import json
import math
import os
import time
from contextlib import nullcontext
from datetime import UTC, datetime, timedelta
from typing import Any, cast

from app.application.agent_orchestrator.param_references import (
    UNRESOLVED_CODE,
    unresolved_placeholders,
)
from app.application.agent_orchestrator.run_models import AgentStep
from app.application.agent_orchestrator.tool_spec import (
    ToolActionSpecV2,
    get_tool_action_spec,
    validate_tool_call,
    validate_tool_result,
)
from app.application.employee_runtime.result_verifier import (
    execution_result_requires_reconciliation,
)
from app.application.tool_execution_deadline import (
    invocation_deadline,
    invocation_requires_reconciliation,
)
from app.utils.operational_errors import RECOVERABLE_ERRORS

_SQL_TENANT_SCOPED_TOOL_IDS = frozenset(
    {
        "business_db",
        "customers",
        "sales",
        "reports",
        "inventory",
        "shipment_records",
        "shipment_orders",
        "document_template",
        "purchase",
        "finance",
        "excel_analysis",
        "employee",
    }
)


_PRODUCT_READ_ACTIONS = frozenset({("products", "exists"), ("products", "query")})
_CUSTOMER_READ_ACTIONS = frozenset({("customers", "query")})
_SHIPMENT_READ_ACTIONS = frozenset({("shipment_records", "query"), ("shipment_records", "list")})
_OWNED_READ_ACTIONS = _PRODUCT_READ_ACTIONS | _CUSTOMER_READ_ACTIONS | _SHIPMENT_READ_ACTIONS
_REVIEWED_QUERY_ACTIONS = frozenset({("finance", "ledger_query")}) | _OWNED_READ_ACTIONS
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


def _reviewed_query_tenant(
    spec: ToolActionSpecV2 | None, params: dict[str, Any], context: dict[str, Any]
) -> tuple[int | None, dict[str, Any] | None]:
    """Explicit audited action policies, not a generic read-only authorization lane."""
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
    if (spec.tool_id, spec.action) in _OWNED_READ_ACTIONS or (
        (spec.tool_id, spec.action) == ("business_db", "read")
        and params.get("entity") == "products"
    ):
        try:
            permission = (
                "customer.view"
                if (spec.tool_id, spec.action) in _CUSTOMER_READ_ACTIONS
                else "shipment.view"
                if (spec.tool_id, spec.action) in _SHIPMENT_READ_ACTIONS
                else "product.view"
            )
            tenant = check_owned_business_permission(actor, permission)
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
    tenant_text = str(context.get("tenant_id") or "")
    if not tenant_text.isdigit() or int(tenant_text) <= 0:
        return None, _query_failure("tool_scope_unavailable")
    return int(tenant_text), None


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

_catalog_context: ContextVar[tuple[str, str, dict[str, Any]] | None] = ContextVar(
    "controlled_catalog_dispatch", default=None
)


def controlled_tool_context(tool_id, action):
    held = _catalog_context.get()
    return dict(held[2]) if held and held[:2] == (tool_id, action) else None


def _execute_catalog(step: AgentStep, context: dict[str, Any]) -> dict[str, Any]:
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
        from app.utils.resilience.rate_limiter import (
            RateLimitBackendError,
            check_rate_limit,
            ensure_rate_limit_backend,
        )

        context_for_limit = runtime_context if isinstance(runtime_context, dict) else {}
        tenant = context_for_limit.get("tenant_id") or context_for_limit.get("user_id") or "shared"
        endpoint = f"agent-tool:{step.tool_id}.{step.action}"
        try:
            ensure_rate_limit_backend()
            admission = check_rate_limit(str(tenant), endpoint, max_requests=120, window_seconds=60)
        except RateLimitBackendError:
            return {
                "success": False,
                "error_code": "tool_rate_limit_backend_unavailable",
                "retryable": True,
                "execution_status": "not_started",
                "message": "工具限流服务暂不可用，本次操作未执行。",
            }
        if not admission.get("allowed", True):
            return {
                "success": False,
                "error_code": "tool_rate_limited",
                "retryable": True,
                "execution_status": "not_started",
                "retry_after": max(1, int(admission.get("retry_after") or 60)),
                "message": "该工具调用过于频繁，请稍后再试。",
            }
        from app.application.facades.tools_facade import execute_registered_workflow_tool

        raw_params = dict(step.params or {})
        client_identity = bool(_QUERY_IDENTITY_FIELDS.intersection(raw_params))
        params = dict(raw_params)
        deadline = (runtime_context or {}).get("deadline_monotonic")
        if isinstance(deadline, (int, float)) and time.monotonic() > float(deadline):
            return {
                "success": False,
                "error_code": "tool_timeout_unknown",
                "outcome": "unknown",
                "retryable": False,
                "execution_status": "timeout",
                "message": "工具超时，业务结果未知；必须核对原调用，不可自动重试",
            }
        if (runtime_context or {}).get("cancel_requested") is True:
            return {
                "success": False,
                "error_code": "tool_cancelled",
                "retryable": False,
                "execution_status": "cancelled",
                "message": "工具调用已取消",
            }
        spec = get_tool_action_spec(step.tool_id, step.action)
        schema_properties: set[str] = set()
        if spec is not None and isinstance(spec.input_schema, dict):
            raw_properties = spec.input_schema.get("properties")
            if isinstance(raw_properties, dict):
                schema_properties = {str(key) for key in raw_properties}
        for control_key in (
            "skip_approval",
            "auto_approve",
            "approved",
            "permission",
            "permissions",
            "system_prompt",
            "employee_tool_allowlist",
            "_actor_authorization",
            "tenant_id",
            "user_id",
        ):
            # Dataset tools declare tenant_id as a scoped business field.
            # Identity fields that are not in the tool schema stay stripped.
            if control_key in {"tenant_id", "user_id"} and control_key in schema_properties:
                continue
            params.pop(control_key, None)
        context = dict(runtime_context or {})
        required = (
            set((spec.input_schema or {}).get("required") or []) if spec is not None else set()
        )
        if "user_id" in required and context.get("user_id") not in (None, ""):
            params["user_id"] = str(context["user_id"])
        if "tenant_id" in required and context.get("tenant_id") not in (None, ""):
            params["tenant_id"] = context["tenant_id"]
        leftover = unresolved_placeholders(params)
        if leftover:
            return {
                "success": False,
                "error_code": UNRESOLVED_CODE,
                "message": "参数包含未解析的占位符，已拒绝执行：" + "、".join(leftover)[:200],
                "tool_id": step.tool_id,
                "action": step.action,
            }
        validation = validate_tool_call(step.tool_id, step.action, params)
        if not validation.ok:
            return {
                "success": False,
                "error_code": validation.error_code,
                "message": validation.message,
                "tool_id": validation.tool_id,
                "action": validation.action,
            }
        from app.application.chat_turn_guard import _is_mutation

        guard_policy = str((runtime_context or {}).get("mutation_policy") or "")
        guard_action = validation.action or step.action
        if _is_mutation(f"{validation.tool_id} {guard_action}", json.dumps(params, default=str)):
            if guard_policy in {"block", "model_only"} or (
                guard_policy == "allow_once"
                and (validation.tool_id, guard_action)
                not in {("customers", "batch_delete"), ("products", "batch_delete")}
            ):
                return {
                    "success": False,
                    "error_code": "mutation_blocked",
                    "message": "当前轮次未授权该写入。",
                }
        from app.application.agent_orchestrator.tool_permission import (
            actor_tool_denial,
            approval_execution_denial,
        )

        denied = actor_tool_denial(
            validation.tool_id,
            validation.action or step.action,
            dict(runtime_context or {}),
            params,
        )
        if denied is not None:
            return denied
        approval_denied = approval_execution_denial(
            validation.tool_id, validation.action or step.action, dict(runtime_context or {})
        )
        if approval_denied is not None:
            return approval_denied
        if validation.tool_id == "catalog_products_v1":
            return _execute_catalog(step, dict(runtime_context or {}))
        product_db_read = (validation.tool_id, validation.action) == (
            "business_db",
            "read",
        ) and params.get("entity") == "products"
        reviewed_query = (
            validation.tool_id,
            validation.action,
        ) in _REVIEWED_QUERY_ACTIONS or product_db_read
        if reviewed_query and client_identity:
            return _query_failure("tool_identity_override")
        query_tenant = None
        if reviewed_query:
            query_tenant, denied = _reviewed_query_tenant(
                validation.spec, params, dict(runtime_context or {})
            )
            if denied is not None:
                return denied
        params["_runtime_context"] = dict(runtime_context or {})
        if (
            validation.tool_id,
            validation.action,
        ) in _OWNED_READ_ACTIONS or product_db_read:
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

        from app.application.agent_orchestrator.worker_repository import WorkerLeaseLost
        from app.infrastructure.auth.agent_mod_scope import (
            AgentModAuthorizationError,
            agent_mod_execution_scope,
        )
        from app.infrastructure.tenant_scope import owned_tenant_scope, tenant_scope

        result: Any = None
        idem_key = ""
        try:
            # Durable/background Agent runs execute outside the originating HTTP
            # request. Restore the authenticated integer tenant recorded in
            # runtime_context so repository/raw-SQL boundaries keep their fail-closed
            # isolation. Dataset/document tools deliberately keep their own opaque
            # string tenant keys and must not be coerced here.
            scope = (
                owned_tenant_scope(runtime_tenant_id)
                if ((validation.tool_id, action) in _OWNED_READ_ACTIONS or product_db_read)
                and isinstance(runtime_tenant_id, int)
                else tenant_scope(runtime_tenant_id)
            )
            with (
                agent_mod_execution_scope(params["_runtime_context"].get("_mod_authorization")),
                scope if runtime_tenant_id is not None else nullcontext(),
            ):
                from app.application.agent_orchestrator.tool_permission import (
                    _fingerprint,
                    begin_idempotent_replay,
                    finish_idempotent_replay,
                )

                context_key = str(params["_runtime_context"].get("idempotency_key") or "")
                client_key = str(params.get("idempotency_key") or "")
                idem_key, replay = (
                    begin_idempotent_replay(
                        params["_runtime_context"], validation.tool_id, action, params
                    )
                    if client_key
                    or context_key
                    or (validation.spec is not None and validation.spec.idempotent)
                    else ("", None)
                )
                if replay is not None:
                    return replay
                from app.application.customer_creation_receipt import customer_creation_claim

                receipt_scope = (
                    customer_creation_claim(
                        idem_key, _fingerprint(params), str(runtime_tenant_id or "")
                    )
                    if idem_key and (validation.tool_id, action) == ("customers", "create")
                    else nullcontext()
                )
                try:
                    from app.infrastructure.llm.model_admission import model_rate_limit_scope

                    with receipt_scope, model_rate_limit_scope(params["_runtime_context"]):
                        guarded_batch = (validation.tool_id, action) in {
                            ("customers", "batch_delete"),
                            ("products", "batch_delete"),
                        } and params["_runtime_context"].get("mutation_policy") == "allow_once"
                        if guarded_batch:
                            from app.application.workflow.guarded_batch_delete import (
                                execute_guarded_batch_delete,
                            )

                            scopes = params["_runtime_context"].get("_bulk_preview_scopes")
                            digest = (
                                scopes.get(validation.tool_id) if isinstance(scopes, dict) else None
                            )
                            if not isinstance(digest, str) or not digest:
                                return {
                                    "success": False,
                                    "error_code": "preview_required",
                                    "message": "删除范围未确认，请重新预览。",
                                }
                            params["_runtime_context"]["_bulk_preview_scope"] = {
                                "tool": validation.tool_id,
                                "digest": digest,
                            }
                            result = execute_guarded_batch_delete(
                                tool_id=validation.tool_id, action=action, params=params
                            )
                        else:
                            result = (
                                _dispatch_reviewed_query(step.tool_id, action, params)
                                if reviewed_query
                                else execute_registered_workflow_tool(step.tool_id, action, params)
                            )
                except (WorkerLeaseLost, TimeoutError, PermissionError, RuntimeError):
                    raise
                except RECOVERABLE_ERRORS as exc:
                    result = {
                        "success": False,
                        "error_code": "tool_exception",
                        "message": "工具执行失败",
                        "exception_type": type(exc).__name__,
                        "outcome": "unknown",
                        "retryable": False,
                        "reconciliation_required": True,
                    }
                finally:
                    if idem_key and not isinstance(result, dict):
                        finish_idempotent_replay(
                            idem_key,
                            {
                                "success": False,
                                "error_code": "tool_execution_interrupted",
                                "outcome": "unknown",
                                "retryable": False,
                                "reconciliation_required": True,
                            },
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
                "outcome": "unknown",
                "retryable": False,
                "reconciliation_required": True,
            }
        from app.application.agent_orchestrator.tool_permission import (
            classify_http_status,
            finish_idempotent_replay,
            reject_empty_business_result,
        )

        status_code = result.get("status_code", result.get("http_status"))
        try:
            status_value = int(status_code) if status_code not in (None, "") else 0
        except (TypeError, ValueError):
            status_value = 0
        if status_value >= 400:
            result = {**result, **classify_http_status(status_value)}
        empty = reject_empty_business_result(result, action=action)
        if empty is not None:
            result = {**empty, "outcome": "unknown", "reconciliation_required": True}

        output_validation = validate_tool_result(validation.tool_id, action, result)
        if not output_validation.ok:
            # A completed read with an invalid response is a contract failure.
            # Mutations and any pre-existing uncertainty must retain their claim.
            requires_reconciliation = (
                validation.spec is None
                or not validation.spec.read_only
                or invocation_requires_reconciliation()
                or execution_result_requires_reconciliation(result)
                or result.get("outcome_unknown") is True
                or str(result.get("execution_status") or "").lower()
                in {"unknown", "timeout", "timed_out", "interrupted"}
                or "unknown" in str(result.get("error_code") or "").lower()
            )
            result = {
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
            if requires_reconciliation:
                result.update(outcome="unknown", retryable=False, reconciliation_required=True)
        if idem_key:
            finish_idempotent_replay(idem_key, result)
        return cast("dict[str, Any]", result)


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
    from app.utils.resilience.rate_limiter import (
        ToolCircuitOpenError,
        ToolConcurrencyLimitError,
        tool_execution_slot,
    )

    try:
        tenant_id = (
            runtime_context.get("tenant_id")
            or runtime_context.get("local_user_id")
            or runtime_context.get("actor_id")
            or "shared"
        )
        with tool_execution_slot(
            f"{step.tool_id}.{step.action}", tenant_id=str(tenant_id)
        ) as record_result:
            with invocation_deadline(deadline) as invocation:
                result = (
                    bounded(step, runtime_context=context, deadline_monotonic=deadline)
                    if callable(bounded)
                    else executor.execute(step, runtime_context=context)
                )
            record_result(result)
    except TimeoutError:
        pass
    except ToolConcurrencyLimitError:
        return {
            "success": False,
            "error_code": "tool_concurrency_limited",
            "retryable": True,
            "execution_status": "not_started",
            "message": "工具并发已达上限，本次操作尚未开始，请稍后重试。",
        }
    except ToolCircuitOpenError as exc:
        return {
            "success": False,
            "error_code": "tool_circuit_open",
            "retryable": True,
            "retry_after": exc.retry_after,
            "execution_status": "not_started",
            "message": "该工具暂时不可用，本次操作尚未开始，请稍后重试。",
        }
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
            and (
                result.get("outcome") != "unknown"
                or result.get("error_code")
                in {
                    "tool_identity_required",
                    "tool_identity_override",
                    "tool_permission_denied",
                    "tool_contract_unavailable",
                    "tool_scope_unavailable",
                    "catalog_identity_override",
                }
            )
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
