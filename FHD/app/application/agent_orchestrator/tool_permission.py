"""Server-side tool authorization and tenant-scoped idempotent replay.

Client fields never grant a tool. A bound session is checked against the
live role permissions, and an employee allowlist is checked again at execution.
"""

from __future__ import annotations

import errno
import json
import os
import sqlite3
import threading
import uuid
from pathlib import Path
from typing import Any, cast

from app.application.agent_orchestrator.run_audit_scope import (
    attach_child_result as attach_child_result,
)
from app.application.agent_orchestrator.run_audit_scope import mutate_run_audit as mutate_run_audit
from app.application.agent_orchestrator.run_audit_scope import read_run_audit as read_run_audit
from app.application.agent_orchestrator.tool_spec import ToolActionSpecV2, get_tool_action_spec
from app.utils.operational_errors import RECOVERABLE_ERRORS

_IDEMPOTENCY: dict[str, dict[str, Any]] = {}
_IDEMPOTENCY_LOCK = threading.Lock()
_LIVE_OWNERS: set[str] = set()
_TENANT_TOOLS: dict[str, set[str]] = {}
_SECRET_PARTS = ("password", "secret", "token", "api_key", "authorization")
_SERVER_FIELDS = frozenset(
    {
        "workspace_root",
        "tenant_id",
        "user_id",
        "employee_id",
        "employee_tool_allowlist",
        "node_outputs",
        "_actor_authorization",
        "_mod_authorization",
        "task_id",
        "run_id",
        "agent_run_id",
        "parent_task_id",
        "parent_run_id",
        "idempotency_key",
        "system_instruction",
    }
)
_UNTRUSTED_CONTROL = frozenset(
    {
        "skip_approval",
        "auto_approve",
        "approved",
        "permission",
        "permissions",
        "system_prompt",
        "grant_tools",
        "employee_tool_allowlist",
        "node_outputs",
        "_actor_authorization",
        "_mod_authorization",
        "_approval_agent_run_required",
        "_bulk_preview_scope",
        "_bulk_preview_scopes",
        "mutation_policy",
    }
)
_FINGERPRINT_SKIP = frozenset(
    {
        "_runtime_context",
        "tenant_id",
        "user_id",
        "actor_id",
        "mod_id",
        "active_mod_id",
        "_actor_authorization",
        "_mod_authorization",
        "local_user_id",
        "authenticated_local_user_id",
        "idempotency_key",
    }
)


def _denial(
    code: str,
    message: str,
    *,
    context: dict[str, Any],
    tool_id: str,
    action: str,
    reason: str,
    event_type: str = "security.tool_permission_denied",
    execution_state: str = "",
) -> dict[str, Any]:
    user_id = str(context.get("user_id") or "")
    task_id = str(context.get("task_id") or context.get("run_id") or "")
    audit = {
        "reason": reason,
        "user_id": user_id,
        "tool_id": tool_id,
        "task_id": task_id,
        "tenant_id": str(context.get("tenant_id") or ""),
        "action": action,
        "execution_state": execution_state,
    }
    try:
        from app.utils.logging.audit_logger import audit_log

        audit_log(
            event_type,
            user_id=user_id or None,
            success=False,
            severity="warning",
            details=audit,
        )
    except RECOVERABLE_ERRORS:
        pass
    return {
        "success": False,
        "error_code": code,
        "outcome": "denied",
        "retryable": False,
        "message": message,
        "tool_id": tool_id,
        "action": action,
        "reason": reason,
        "user_id": user_id,
        "task_id": task_id,
        "audit": audit,
    }


def _allowlist_denial(spec: ToolActionSpecV2, context: dict[str, Any]) -> dict[str, Any] | None:
    raw = context.get("employee_tool_allowlist")
    if raw is None:
        return None
    if not isinstance(raw, (list, tuple, set, frozenset)):
        return _denial(
            "tool_permission_denied",
            "员工工具授权无效，已拒绝执行",
            context=context,
            tool_id=spec.tool_id,
            action=spec.action,
            reason="employee_allowlist_invalid",
        )
    allowed = {str(item) for item in raw}
    if spec.tool_id in allowed or f"{spec.tool_id}.{spec.action}" in allowed:
        return None
    return _denial(
        "tool_permission_denied",
        "AI 员工未被授权调用该工具",
        context=context,
        tool_id=spec.tool_id,
        action=spec.action,
        reason="employee_tool_not_granted",
    )


def register_tenant_tool(tenant_id: str, tool_id: str) -> None:
    """Record that a tool id may be discovered and executed only by this tenant."""
    _TENANT_TOOLS.setdefault(str(tool_id), set()).add(str(tenant_id))


def discover_tools(tenant_id: str, tool_ids: list[str] | tuple[str, ...]) -> list[str]:
    """Hide tools registered to another tenant. Shared tools stay visible."""
    visible: list[str] = []
    caller = str(tenant_id)
    for tool_id in tool_ids:
        owners = _TENANT_TOOLS.get(str(tool_id))
        if not owners or caller in owners:
            visible.append(str(tool_id))
    return visible


def clear_tenant_tools_for_tests() -> None:
    _TENANT_TOOLS.clear()


def _tenant_tool_denial(
    tool_id: str, action: str, context: dict[str, Any]
) -> dict[str, Any] | None:
    owners = _TENANT_TOOLS.get(str(tool_id))
    if not owners:
        return None
    if str(context.get("tenant_id") or "") in owners:
        return None
    return _denial(
        "tool_permission_denied",
        "工具不在当前企业可用范围内",
        context=context,
        tool_id=str(tool_id or ""),
        action=str(action or ""),
        reason="tenant_tool_forbidden",
    )


def actor_tool_denial(
    tool_id: str,
    action: str,
    context: dict[str, Any] | None,
    params: dict[str, Any] | None = None,
) -> dict[str, Any] | None:
    """Deny when a sealed actor, tenant owner, or employee allowlist does not grant this tool."""
    ctx = dict(context or {})
    tenant_denial = _tenant_tool_denial(tool_id, action, ctx)
    if tenant_denial is not None:
        return tenant_denial
    spec = get_tool_action_spec(tool_id, action)
    if (
        not isinstance(ctx.get("_actor_authorization"), dict)
        and "employee_tool_allowlist" not in ctx
    ):
        return None
    if spec is None:
        return _denial(
            "tool_contract_unavailable",
            "工具契约不可用，已拒绝执行",
            context=ctx,
            tool_id=str(tool_id or ""),
            action=str(action or ""),
            reason="tool_contract_unavailable",
        )
    allow_denial = _allowlist_denial(spec, ctx)
    if allow_denial is not None:
        return allow_denial
    # Catalog receipts keep their own unknown/historical authorization. A live
    # permission check here would turn a revoked write into a fresh denial.
    if str(tool_id) == "catalog_products_v1":
        return None
    if not isinstance(ctx.get("_actor_authorization"), dict):
        return None
    from app.domain.shared_services.auth_service import get_auth_service
    from app.infrastructure.auth.agent_mod_scope import AgentModAuthorizationError, _bound_actor

    try:
        actor = _bound_actor(ctx)
        if tool_id == "memory_v2":
            aliases = {str(actor.id)}
            if not str(actor.username).isdecimal():
                aliases.add(str(actor.username))
            target = str(
                (params or {}).get("user_id")
                or (params or {}).get("userId")
                or ctx.get("user_id")
                or ""
            )
            if target not in aliases:
                return _denial(
                    "tool_permission_denied",
                    "只能操作当前账户的记忆",
                    context=ctx,
                    tool_id=tool_id,
                    action=action,
                    reason="memory_owner_mismatch",
                )
        if getattr(actor, "role", "") == "admin":
            return None
        permission = spec.permission
        if (tool_id, action) == ("business_db", "read") and (params or {}).get(
            "entity"
        ) == "products":
            permission = "product.view"
        if permission and not get_auth_service().has_permission(actor, permission):
            return _denial(
                "tool_permission_denied",
                "权限不足，已拒绝执行工具",
                context=ctx,
                tool_id=spec.tool_id,
                action=spec.action,
                reason="permission_denied",
            )
    except AgentModAuthorizationError:
        return _denial(
            "tool_identity_required",
            "工具任务需要有效的身份授权，请重新登录或授权",
            context=ctx,
            tool_id=spec.tool_id,
            action=spec.action,
            reason="actor_binding_rejected",
        )
    except RECOVERABLE_ERRORS:
        return _denial(
            "tool_permission_denied",
            "权限校验失败，已拒绝执行",
            context=ctx,
            tool_id=spec.tool_id,
            action=spec.action,
            reason="permission_check_failed",
        )
    return None


def _gate_state(state: str) -> str:
    from app.domain.task_lifecycle.adapters import (
        LegacyTransitionError,
        canonical_execution_state,
        canonicalize,
    )

    raw = str(state or "").strip().lower()
    mapped = canonical_execution_state(raw)
    if mapped != raw:
        return mapped
    try:
        return canonicalize("agent", raw)
    except LegacyTransitionError:
        return mapped


def _approval_expired(repository: object, run_id: str) -> bool:
    from datetime import UTC, datetime

    lifecycle = getattr(repository, "lifecycle", None)
    if not callable(lifecycle):
        return False
    body = lifecycle(run_id)
    if not isinstance(body, dict):
        return False
    started = str(body.get("approval_requested_at") or "")
    if not started:
        return False
    timeout = float(getattr(repository, "_approval_timeout_seconds", 86400.0) or 0)
    requested = datetime.fromisoformat(started.replace("Z", "+00:00"))
    if requested.tzinfo is None:
        requested = requested.replace(tzinfo=UTC)
    return (datetime.now(UTC) - requested).total_seconds() >= timeout


def approval_execution_denial(
    tool_id: str, action: str, context: dict[str, Any] | None
) -> dict[str, Any] | None:
    """Block a business write while this task is waiting, rejected, cancelled, or expired.

    Caller-supplied approval_id and approved flags are ignored. A task with no
    lifecycle row is an ordinary ERP call and is left alone.
    """
    ctx = dict(context or {})
    task_id = str(ctx.get("task_id") or ctx.get("run_id") or "").strip()
    if not task_id:
        return None
    from app.application.agent_orchestrator.task_execution_repository import (
        locate_task_execution,
    )

    repository, row = locate_task_execution(str(ctx.get("run_id") or task_id), fallback_id=task_id)
    if repository is None or row is None:
        return None
    approval_run_id = str(getattr(row, "run_id", "") or "")
    if task_id not in {approval_run_id, str(getattr(row, "task_id", "") or "")}:
        return _denial(
            "approval_required",
            "执行任务与审批任务不一致，已拒绝执行",
            context=ctx,
            tool_id=str(tool_id or ""),
            action=str(action or ""),
            reason="approval_task_mismatch",
            event_type="security.approval_execution_denied",
        )
    ctx_tenant = str(ctx.get("tenant_id") or "")
    row_tenant = str(getattr(row, "tenant_id", "") or "")
    if ctx_tenant and row_tenant and ctx_tenant != row_tenant:
        return _denial(
            "approval_required",
            "其他租户的审批不能授权本任务",
            context=ctx,
            tool_id=str(tool_id or ""),
            action=str(action or ""),
            reason="approval_tenant_mismatch",
            event_type="security.approval_execution_denied",
            execution_state=str(getattr(row, "state", "") or ""),
        )
    state = _gate_state(str(getattr(row, "state", "") or ""))
    expired = _approval_expired(repository, approval_run_id) or (
        str(getattr(row, "last_error_code", "") or "") == "approval_timeout"
    )
    if state not in {"waiting_approval", "rejected", "cancelled"} and not expired:
        return None
    if expired:
        reason = "approval_expired"
        message = "审批已过期，已拒绝执行"
    elif state == "rejected":
        reason = "approval_rejected"
        message = "任务已驳回，已拒绝执行"
    elif state == "cancelled":
        reason = "approval_cancelled"
        message = "任务已取消，已拒绝执行"
    else:
        reason = "approval_required"
        message = "任务仍在等待审批，已拒绝执行"
    return _denial(
        "approval_required",
        message,
        context=ctx,
        tool_id=str(tool_id or ""),
        action=str(action or ""),
        reason=reason,
        event_type="security.approval_execution_denied",
        execution_state=state,
    )


def _fingerprint(params: dict[str, Any]) -> str:
    from app.application.agent_orchestrator.business_action_ledger import canonical_hash

    visible = {key: value for key, value in params.items() if key not in _FINGERPRINT_SKIP}
    return canonical_hash(visible)


def idempotency_scope_key(
    context: dict[str, Any], tool_id: str, action: str, params: dict[str, Any]
) -> str:
    client_key = str(params.get("idempotency_key") or "").strip()
    server_key = str(context.get("idempotency_key") or "").strip()
    raw = client_key or server_key
    tenant = str(context.get("tenant_id") or "")
    task = str(context.get("task_id") or "").strip()
    run_id = str(context.get("run_id") or "").strip()
    # A client key names one business attempt and must replay after a new run.
    # The per-run server key stays unique when the caller did not supply a key.
    if client_key:
        if not task or task == run_id:
            task = ""
    elif not task:
        task = run_id
    return f"{tenant}:{task}:{tool_id}:{action}:{raw}"


def _idempotency_path() -> Path | None:
    raw = os.environ.get("XCAGI_TOOL_IDEMPOTENCY_PATH", "").strip()
    if raw.lower() in {"0", "off", "memory", "none"}:
        return None
    if not raw:
        # Tests stay in memory unless they point this path at an isolated file.
        if os.environ.get("PYTEST_CURRENT_TEST"):
            return None
        from app.utils.path_io.path_utils import get_app_data_dir

        raw = str(Path(get_app_data_dir()) / "tool-idempotency.sqlite")
    path = Path(raw)
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


def _idempotency_conn() -> sqlite3.Connection | None:
    path = _idempotency_path()
    if path is None:
        return None
    conn = sqlite3.connect(path, timeout=5, check_same_thread=False)
    conn.execute(
        "create table if not exists tool_idempotency("
        "scope_key text primary key, fingerprint text, owner text, "
        "inflight integer, output_json text)"
    )
    return conn


def _stored_claim(row: tuple[Any, ...]) -> dict[str, Any]:
    output = None
    if row[3]:
        try:
            parsed = json.loads(row[3])
        except json.JSONDecodeError:
            parsed = None
        output = parsed if isinstance(parsed, dict) else None
    return {
        "fingerprint": row[0],
        "owner": row[1],
        "inflight": bool(row[2]),
        "output": output,
    }


def _try_claim(key: str, record: dict[str, Any]) -> dict[str, Any] | None:
    """Atomically insert a claim, or read the record that already owns the key."""
    conn = _idempotency_conn()
    if conn is None:
        return _IDEMPOTENCY.get(key)
    try:
        with conn:
            inserted = conn.execute(
                "insert into tool_idempotency(scope_key, fingerprint, owner, inflight, output_json) "
                "values (?, ?, ?, 1, '') on conflict(scope_key) do nothing",
                (key, record["fingerprint"], record["owner"]),
            ).rowcount
            if inserted == 1:
                return None
            row = conn.execute(
                "select fingerprint, owner, inflight, output_json "
                "from tool_idempotency where scope_key = ?",
                (key,),
            ).fetchone()
            if row is None:
                raise RuntimeError("工具幂等记录不可用，已拒绝重复执行")
            return _stored_claim(row)
    finally:
        conn.close()


def _tool_output_json(output: dict[str, Any]) -> str:
    from app.application.agent_orchestrator.tool_process import dump_tool_output

    return dump_tool_output(output)


def _finish_claim(key: str, owner: str, output: dict[str, Any] | None) -> None:
    """Only the worker that claimed a key may settle it or release a known failure."""
    conn = _idempotency_conn()
    if conn is None:
        return
    try:
        with conn:
            if output is None:
                changed = conn.execute(
                    "delete from tool_idempotency where scope_key = ? and owner = ? and inflight = 1",
                    (key, owner),
                ).rowcount
            else:
                changed = conn.execute(
                    "update tool_idempotency set inflight = 0, output_json = ? "
                    "where scope_key = ? and owner = ? and inflight = 1",
                    (_tool_output_json(output), key, owner),
                ).rowcount
            if changed != 1:
                raise RuntimeError("工具幂等执行权已变化，必须核验原调用结果")
    finally:
        conn.close()


def _retained_result(output: dict[str, Any]) -> dict[str, Any] | None:
    from app.application.employee_runtime.result_verifier import (
        execution_result_requires_reconciliation,
    )

    if (
        execution_result_requires_reconciliation(output)
        or str(output.get("execution_status") or "").lower()
        in {"unknown", "timeout", "timed_out", "interrupted"}
        or "unknown" in str(output.get("error_code") or "").lower()
        or (output.get("success") is not True and output.get("success") is not False)
    ):
        return {
            **output,
            "success": False,
            "outcome": "unknown",
            "retryable": False,
            "reconciliation_required": True,
        }
    return dict(output) if output.get("success") is True else None


def drop_process_idempotency_memory() -> None:
    """Simulate a process restart: memory claims die, the sqlite record remains."""
    with _IDEMPOTENCY_LOCK:
        _IDEMPOTENCY.clear()
        _LIVE_OWNERS.clear()


def _owner_liveness(owner: str) -> str:
    """alive, dead, or unknown. A live pid is never treated as a timeout."""
    pid_text, separator, _token = str(owner or "").partition(":")
    if not separator or not pid_text.isdigit():
        return "unknown"
    pid = int(pid_text)
    if pid <= 0:
        return "unknown"
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return "dead"
    except PermissionError:
        return "alive"
    except OSError as exc:
        if exc.errno == errno.ESRCH:
            return "dead"
        if exc.errno == errno.EPERM:
            return "alive"
        return "unknown"
    return "alive"


def _customer_create_effect(
    tenant: str, params: dict[str, Any], *, key: str, fingerprint: str, receipted: bool
) -> tuple[str, dict[str, Any] | None]:
    """Resolve a transaction-bound row id; a matching name is not an operation receipt."""
    name = str(
        params.get("unit_name") or params.get("customer_name") or params.get("name") or ""
    ).strip()
    if not tenant.isdigit() or int(tenant) <= 0 or not name:
        return "unknown", None
    tenant_id = int(tenant)
    phone = params.get("contact_phone")
    person = params.get("contact_person")
    address = params.get("contact_address", params.get("address"))
    from sqlalchemy.exc import SQLAlchemyError

    lookup_errors = RECOVERABLE_ERRORS + (SQLAlchemyError,)
    try:
        from sqlalchemy import select

        from app.application.customer_app_service import get_customers_session
        from app.application.customer_creation_receipt import CUSTOMER_CREATE_RECEIPTS
        from app.db.models.purchase_unit import PurchaseUnit
        from app.domain.task_lifecycle.control import SessionBook

        session = get_customers_session()
        try:
            receipt = SessionBook(session).get(CUSTOMER_CREATE_RECEIPTS, tenant, key)
            customer_id = receipt.get("customer_id")
            if type(customer_id) is not int or customer_id <= 0:
                if not receipted:
                    return "unknown", None
                existing = session.execute(
                    select(PurchaseUnit.id)
                    .where(PurchaseUnit.unit_name == name, PurchaseUnit.tenant_id == tenant_id)
                    .limit(1)
                    .execution_options(skip_tenant_filter=True)
                ).first()
                return ("absent" if existing is None else "unknown"), None
            if receipt.get("fingerprint") != fingerprint:
                return "unknown", None
            row = session.execute(
                select(PurchaseUnit)
                .where(PurchaseUnit.id == customer_id, PurchaseUnit.tenant_id == tenant_id)
                .execution_options(skip_tenant_filter=True)
            ).scalar_one_or_none()
            if row is None:
                return "unknown", None
            if str(row.tenant_id) != tenant or str(row.unit_name or "") != name:
                return "unknown", None
            for expected, actual in (
                (phone, row.contact_phone),
                (person, row.contact_person),
                (address, row.address),
            ):
                if expected not in (None, "") and str(actual or "") != str(expected):
                    return "unknown", None
            data = {
                "id": int(row.id),
                "customer_name": row.unit_name,
                "contact_person": row.contact_person or "",
                "contact_phone": row.contact_phone or "",
                "contact_address": row.address or "",
                "tenant_id": int(row.tenant_id),
                "version": int(row.version),
            }
        finally:
            session.close()
    except lookup_errors:
        return "unknown", None
    return "matched", {
        "success": True,
        "created": True,
        "id": data["id"],
        "data": data,
        "message": "客户创建成功",
    }


def _claim_transaction(statements: list[tuple[str, tuple[Any, ...]]]) -> int:
    """Run one immediate transaction. The last statement's rowcount is the result."""
    conn = _idempotency_conn()
    if conn is None:
        return 0
    try:
        conn.execute("begin immediate")
        changed = 0
        for sql, args in statements:
            changed = conn.execute(sql, args).rowcount
        conn.commit()
        return int(changed)
    except sqlite3.Error:
        conn.rollback()
        return 0
    finally:
        conn.close()


def _complete_dead_claim(key: str, owner: str, output: dict[str, Any]) -> bool:
    changed = _claim_transaction(
        [
            (
                "update tool_idempotency set inflight = 0, output_json = ? "
                "where scope_key = ? and owner = ? and inflight = 1",
                (_tool_output_json(output), key, owner),
            )
        ]
    )
    return changed == 1


def _replace_dead_claim(key: str, owner: str, fingerprint: str, new_owner: str) -> bool:
    conn = _idempotency_conn()
    if conn is None:
        return False
    try:
        conn.execute("begin immediate")
        deleted = conn.execute(
            "delete from tool_idempotency where scope_key = ? and owner = ? and inflight = 1",
            (key, owner),
        ).rowcount
        if deleted != 1:
            conn.rollback()
            return False
        inserted = conn.execute(
            "insert into tool_idempotency(scope_key, fingerprint, owner, inflight, output_json) "
            "values (?, ?, ?, 1, '')",
            (key, fingerprint, new_owner),
        ).rowcount
        if inserted != 1:
            conn.rollback()
            return False
        conn.commit()
        return True
    except sqlite3.Error:
        conn.rollback()
        return False
    finally:
        conn.close()


def _reread_claim(key: str) -> dict[str, Any] | None:
    conn = _idempotency_conn()
    if conn is None:
        return _IDEMPOTENCY.get(key)
    try:
        row = conn.execute(
            "select fingerprint, owner, inflight, output_json from tool_idempotency where scope_key = ?",
            (key,),
        ).fetchone()
    except sqlite3.Error:
        return None
    finally:
        conn.close()
    if row is None:
        return None
    return _stored_claim(row)


def recover_idempotent_claims() -> dict[str, int]:
    """Retain unfinished claims: another process may still run or have committed an effect."""
    report = {"cleared_unknown": 0, "retained_unknown": 0, "replayable": 0}
    with _IDEMPOTENCY_LOCK:
        conn = _idempotency_conn()
        try:
            records = (
                (
                    _stored_claim(row)
                    for row in conn.execute(
                        "select fingerprint, owner, inflight, output_json from tool_idempotency"
                    )
                )
                if conn is not None
                else iter(_IDEMPOTENCY.values())
            )
            for record in records:
                output = record.get("output")
                saved = _retained_result(output) if isinstance(output, dict) else None
                if not record.get("inflight") and saved and saved.get("success") is True:
                    report["replayable"] += 1
                else:
                    report["retained_unknown"] += 1
        finally:
            if conn is not None:
                conn.close()
    return report


def begin_idempotent_replay(
    context: dict[str, Any], tool_id: str, action: str, params: dict[str, Any]
) -> tuple[str, dict[str, Any] | None]:
    """Return a stored result or atomically claim a new key. Unknown effects cannot replay."""
    key = idempotency_scope_key(context, tool_id, action, params)
    if key.endswith(":"):
        return "", None
    try:
        fingerprint = _fingerprint(params)
    except RECOVERABLE_ERRORS:
        return key, _denial(
            "idempotency_conflict",
            "幂等参数无法校验，已拒绝执行",
            context=context,
            tool_id=tool_id,
            action=action,
            reason="idempotency_fingerprint_rejected",
        )
    with _IDEMPOTENCY_LOCK:
        receipt_marker = (
            "customer-receipt-v1:" if (tool_id, action) == ("customers", "create") else ""
        )
        owner = f"{os.getpid()}:{receipt_marker}{uuid.uuid4().hex}"
        record = {"fingerprint": fingerprint, "inflight": True, "output": None, "owner": owner}
        current = _try_claim(key, record)
        if current is None:
            _IDEMPOTENCY[key] = record
            _LIVE_OWNERS.add(owner)
            return key, None
        if current.get("fingerprint") != fingerprint:
            return key, _denial(
                "idempotency_conflict",
                "相同幂等键不能改用新的执行参数",
                context=context,
                tool_id=tool_id,
                action=action,
                reason="idempotency_conflict",
            )
        cached = current.get("output")
        saved = _retained_result(cached) if isinstance(cached, dict) else None
        if not current.get("inflight") and saved is not None:
            return key, saved
        if (
            current.get("inflight")
            and tool_id == "customers"
            and action == "create"
            and _owner_liveness(str(current.get("owner") or "")) == "dead"
        ):
            effect, receipt = _customer_create_effect(
                str(context.get("tenant_id") or ""),
                params,
                key=key,
                fingerprint=fingerprint,
                receipted=":customer-receipt-v1:" in str(current.get("owner") or ""),
            )
            owner = str(current.get("owner") or "")
            if effect == "matched" and receipt is not None:
                if _complete_dead_claim(key, owner, receipt):
                    current["inflight"] = False
                    current["output"] = receipt
                    _IDEMPOTENCY[key] = current
                    return key, receipt
                latest = _reread_claim(key)
                replay = latest.get("output") if isinstance(latest, dict) else None
                restored = _retained_result(replay) if isinstance(replay, dict) else None
                if restored is not None and restored.get("success") is True:
                    return key, restored
            elif effect == "absent":
                new_owner = f"{os.getpid()}:{receipt_marker}{uuid.uuid4().hex}"
                if _replace_dead_claim(key, owner, fingerprint, new_owner):
                    record["owner"] = new_owner
                    _IDEMPOTENCY[key] = record
                    _LIVE_OWNERS.add(new_owner)
                    return key, None
                latest = _reread_claim(key)
                if latest is not None and str(latest.get("owner") or "") != owner:
                    saved_latest = latest.get("output")
                    restored = (
                        _retained_result(saved_latest) if isinstance(saved_latest, dict) else None
                    )
                    if not latest.get("inflight") and restored is not None:
                        return key, restored
                    if _owner_liveness(str(latest.get("owner") or "")) == "alive":
                        return key, {
                            **_denial(
                                "idempotency_in_progress",
                                "相同幂等键的调用仍在执行或结果待核验，不可重复执行",
                                context=context,
                                tool_id=tool_id,
                                action=action,
                                reason="idempotency_in_progress",
                            ),
                            "outcome": "unknown",
                            "reconciliation_required": True,
                        }
        code = (
            "idempotency_in_progress" if current.get("inflight") else "idempotency_outcome_unknown"
        )
        return key, {
            **_denial(
                code,
                "相同幂等键的调用仍在执行或结果待核验，不可重复执行",
                context=context,
                tool_id=tool_id,
                action=action,
                reason=code,
            ),
            "outcome": "unknown",
            "reconciliation_required": True,
        }


def finish_idempotent_replay(key: str, output: dict[str, Any]) -> None:
    if not key:
        return
    with _IDEMPOTENCY_LOCK:
        current = _IDEMPOTENCY.get(key)
        if current is None:
            return
        owner = str(current.get("owner") or "")
        if owner not in _LIVE_OWNERS or not owner.startswith(f"{os.getpid()}:"):
            return
        saved = _retained_result(output)
        _finish_claim(key, owner, saved)
        _LIVE_OWNERS.discard(owner)
        if saved is not None:
            current["output"] = saved
            current["inflight"] = False
            return
        _IDEMPOTENCY.pop(key, None)


def clear_idempotent_replay_for_tests() -> None:
    with _IDEMPOTENCY_LOCK:
        _IDEMPOTENCY.clear()
        _LIVE_OWNERS.clear()
    conn = _idempotency_conn()
    if conn is None:
        return
    try:
        conn.execute("delete from tool_idempotency")
        conn.commit()
    finally:
        conn.close()


def redact(value: Any) -> Any:
    """Mask secrets before they are written to tool logs."""
    if isinstance(value, dict):
        masked: dict[str, Any] = {}
        for key, item in value.items():
            lowered = str(key).lower()
            if any(part in lowered for part in _SECRET_PARTS):
                masked[str(key)] = "***"
            else:
                masked[str(key)] = redact(item)
        return masked
    if isinstance(value, list):
        return [redact(item) for item in value]
    if isinstance(value, str) and value.lower().startswith(("sk-", "bearer ")):
        return "***"
    return value


def classify_http_status(status: int) -> dict[str, Any]:
    """Map upstream HTTP statuses onto retry and success policy."""
    code = int(status)
    if code in {401, 403}:
        return {"success": False, "error_code": "tool_auth_failure", "retryable": False}
    if code == 429:
        return {"success": False, "error_code": "tool_rate_limited", "retryable": True}
    if code == 503:
        return {"success": False, "error_code": "tool_unavailable", "retryable": True}
    if code == 400:
        return {"success": False, "error_code": "tool_bad_request", "retryable": False}
    if code == 404:
        return {"success": False, "error_code": "tool_not_found", "retryable": False}
    if code >= 500:
        return {"success": False, "error_code": "tool_upstream_failure", "retryable": False}
    if code >= 400:
        return {"success": False, "error_code": "tool_http_failure", "retryable": False}
    return {}


def reject_empty_business_result(result: dict[str, Any], *, action: str) -> dict[str, Any] | None:
    """Null, blank, and empty mutation payloads are not a successful business result."""
    if result.get("success") is not True:
        return None
    if "data" in result:
        payload = result.get("data")
    elif "result" in result:
        payload = result.get("result")
    else:
        return None
    empty_list = payload == [] and action not in {
        "read",
        "query",
        "list",
        "ledger_query",
        "exists",
    }
    if payload is None or payload == "" or empty_list:
        return {
            **result,
            "success": False,
            "error_code": "empty_business_result",
            "retryable": False,
            "message": "空结果不能当作业务成功",
        }
    return None


def seal_server_context(context: dict[str, Any] | None) -> dict[str, Any]:
    """Drop client control fields. Server identity and tenant stay as already bound."""
    from app.infrastructure.workspace import workspace_root

    sealed = dict(context or {})
    # Rebind legacy persisted runs as well as new HTTP requests at execution.
    sealed["workspace_root"] = str(workspace_root())
    for key in _UNTRUSTED_CONTROL:
        if key not in _SERVER_FIELDS:
            sealed.pop(key, None)
    return sealed


def merge_turn_context(server: dict[str, Any], turn: dict[str, Any] | None) -> dict[str, Any]:
    """Untrusted documents, mail, and tool text stay data and cannot change authority."""
    merged = dict(server or {})
    untrusted: list[dict[str, str]] = [
        item for item in list(merged.get("untrusted_sources") or []) if isinstance(item, dict)
    ]
    for key, value in dict(turn or {}).items():
        if key in _SERVER_FIELDS or key in _UNTRUSTED_CONTROL:
            continue
        if key == "untrusted_sources" and isinstance(value, list):
            for item in value:
                if isinstance(item, dict):
                    untrusted.append(
                        {
                            "source": str(item.get("source") or "unknown")[:40],
                            "text": str(item.get("text") or "")[:4000],
                        }
                    )
            continue
        if key in {"message", "document", "knowledge", "email", "excel", "ticket"}:
            untrusted.append({"source": key, "text": str(value)[:4000]})
            continue
        merged[key] = value
    merged["untrusted_sources"] = untrusted
    merged["context_summary"] = {
        "system": str(merged.get("system_instruction") or ""),
        "data": untrusted,
    }
    return merged


def absorb_tool_output(context: dict[str, Any], output: dict[str, Any]) -> dict[str, Any]:
    """Tool text is an untrusted observation, never a new permission or system instruction."""
    return merge_turn_context(
        context,
        {
            "untrusted_sources": [
                {
                    "source": "tool_output",
                    "text": json.dumps(output, ensure_ascii=False, default=str)[:4000],
                }
            ]
        },
    )


def handoff_runtime_context(
    parent: dict[str, Any],
    *,
    employee_id: str,
    allowlist: list[str],
    parent_task_id: str,
    parent_run_id: str,
) -> dict[str, Any]:
    """Child employees keep the parent tenant and task, and receive only their own allowlist."""
    return {
        "tenant_id": parent.get("tenant_id"),
        "user_id": parent.get("user_id"),
        "task_id": parent.get("task_id") or parent_task_id,
        "parent_task_id": parent_task_id,
        "parent_run_id": parent_run_id,
        **{
            key: parent[key]
            for key in ("workspace_id", "workspace_path", "root_run_id")
            if key in parent
        },
        "_actor_authorization": parent.get("_actor_authorization"),
        "_mod_authorization": parent.get("_mod_authorization"),
        "employee_id": employee_id,
        "employee_tool_allowlist": list(allowlist),
        "system_instruction": str(parent.get("system_instruction") or ""),
    }


def overlay_resume_context(
    stored: dict[str, Any] | None, incoming: dict[str, Any] | None
) -> dict[str, Any]:
    """Resume may add notes. It cannot replace tenant, actor, or employee authority."""
    merged = dict(stored or {})
    for key, value in dict(incoming or {}).items():
        if key in _SERVER_FIELDS and merged.get(key) not in (None, "", [], {}):
            continue
        if key in _UNTRUSTED_CONTROL:
            continue
        merged[key] = value
    return merged


def execution_trace(
    *,
    trace_id: str,
    task_id: str,
    parent_task_id: str,
    tenant_id: str,
    user_id: str,
    employee_id: str,
    tool_id: str,
    tool_version: str,
    execution_id: str,
    started_at: str,
    finished_at: str,
    execution_status: str,
    error_code: str,
    retry_count: int,
) -> dict[str, Any]:
    traced: dict[str, Any] = {
        "trace_id": trace_id,
        "task_id": task_id,
        "parent_task_id": parent_task_id,
        "tenant_id": tenant_id,
        "user_id": user_id,
        "employee_id": employee_id,
        "tool_id": tool_id,
        "tool_name": tool_id,
        "tool_version": tool_version,
        "execution_id": execution_id,
        "started_at": started_at,
        "finished_at": finished_at,
        "execution_status": execution_status,
        "error_code": error_code,
        "retry_count": retry_count,
    }
    return cast("dict[str, Any]", redact(traced))
