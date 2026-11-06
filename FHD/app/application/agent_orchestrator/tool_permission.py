"""Server-side tool authorization and tenant-scoped idempotent replay.

Client fields never grant a tool. A bound session is checked against the
live role permissions, and an employee allowlist is checked again at execution.
"""

from __future__ import annotations

import json
import os
import sqlite3
import threading
import uuid
from pathlib import Path
from typing import Any

from app.application.agent_orchestrator.tool_spec import ToolActionSpecV2, get_tool_action_spec
from app.utils.operational_errors import RECOVERABLE_ERRORS

_IDEMPOTENCY: dict[str, dict[str, Any]] = {}
_IDEMPOTENCY_LOCK = threading.Lock()
_LIVE_OWNERS: set[str] = set()
_TENANT_TOOLS: dict[str, set[str]] = {}
_SECRET_PARTS = ("password", "secret", "token", "api_key", "authorization")
_SERVER_FIELDS = frozenset(
    {
        "tenant_id",
        "user_id",
        "employee_id",
        "employee_tool_allowlist",
        "_actor_authorization",
        "_mod_authorization",
        "task_id",
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
        "_actor_authorization",
        "_mod_authorization",
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
) -> dict[str, Any]:
    user_id = str(context.get("user_id") or "")
    task_id = str(context.get("task_id") or context.get("run_id") or "")
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
        "audit": {
            "reason": reason,
            "user_id": user_id,
            "tool_id": tool_id,
            "task_id": task_id,
        },
    }


def _allowlist_denial(
    spec: ToolActionSpecV2, context: dict[str, Any]
) -> dict[str, Any] | None:
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


def _tenant_tool_denial(tool_id: str, action: str, context: dict[str, Any]) -> dict[str, Any] | None:
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
    tool_id: str, action: str, context: dict[str, Any] | None
) -> dict[str, Any] | None:
    """Deny when a sealed actor, tenant owner, or employee allowlist does not grant this tool."""
    ctx = dict(context or {})
    tenant_denial = _tenant_tool_denial(tool_id, action, ctx)
    if tenant_denial is not None:
        return tenant_denial
    spec = get_tool_action_spec(tool_id, action)
    if not isinstance(ctx.get("_actor_authorization"), dict) and "employee_tool_allowlist" not in ctx:
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
    if not isinstance(ctx.get("_actor_authorization"), dict):
        return None
    from app.domain.shared_services.auth_service import get_auth_service
    from app.infrastructure.auth.agent_mod_scope import AgentModAuthorizationError, _bound_actor

    try:
        actor = _bound_actor(ctx)
        if not spec.permission or not get_auth_service().has_permission(actor, spec.permission):
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


def _persist_claim(key: str, record: dict[str, Any]) -> None:
    conn = _idempotency_conn()
    if conn is None:
        return
    try:
        output = record.get("output")
        conn.execute(
            "insert into tool_idempotency(scope_key, fingerprint, owner, inflight, output_json) "
            "values (?, ?, ?, ?, ?) "
            "on conflict(scope_key) do update set fingerprint=excluded.fingerprint, "
            "owner=excluded.owner, inflight=excluded.inflight, output_json=excluded.output_json",
            (
                key,
                str(record.get("fingerprint") or ""),
                str(record.get("owner") or ""),
                1 if record.get("inflight") else 0,
                json.dumps(output, ensure_ascii=False) if isinstance(output, dict) else "",
            ),
        )
        conn.commit()
    finally:
        conn.close()


def _delete_claim(key: str) -> None:
    conn = _idempotency_conn()
    if conn is None:
        return
    try:
        conn.execute("delete from tool_idempotency where scope_key = ?", (key,))
        conn.commit()
    finally:
        conn.close()


def _load_claim(key: str) -> dict[str, Any] | None:
    conn = _idempotency_conn()
    if conn is None:
        return None
    try:
        row = conn.execute(
            "select fingerprint, owner, inflight, output_json from tool_idempotency where scope_key = ?",
            (key,),
        ).fetchone()
    finally:
        conn.close()
    if row is None:
        return None
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


def drop_process_idempotency_memory() -> None:
    """Simulate a process restart: memory claims die, the sqlite record remains."""
    with _IDEMPOTENCY_LOCK:
        _IDEMPOTENCY.clear()
        _LIVE_OWNERS.clear()


def recover_idempotent_claims() -> dict[str, int]:
    """Drop crashed in-flight claims. Stored successes stay replayable and are not successes-by-default."""
    cleared = 0
    replayable = 0
    conn = _idempotency_conn()
    if conn is None:
        with _IDEMPOTENCY_LOCK:
            for key, record in list(_IDEMPOTENCY.items()):
                if record.get("output"):
                    replayable += 1
                    continue
                if record.get("inflight") and record.get("owner") not in _LIVE_OWNERS:
                    _IDEMPOTENCY.pop(key, None)
                    cleared += 1
        return {"cleared_unknown": cleared, "replayable": replayable}
    try:
        rows = conn.execute(
            "select scope_key, owner, inflight, output_json from tool_idempotency"
        ).fetchall()
        for key, owner, inflight, output_json in rows:
            if output_json:
                replayable += 1
                continue
            if inflight and owner not in _LIVE_OWNERS:
                conn.execute("delete from tool_idempotency where scope_key = ?", (key,))
                cleared += 1
        conn.commit()
    finally:
        conn.close()
    with _IDEMPOTENCY_LOCK:
        for key in list(_IDEMPOTENCY):
            if key not in _LIVE_OWNERS and not (_IDEMPOTENCY[key].get("output")):
                if _IDEMPOTENCY[key].get("inflight"):
                    _IDEMPOTENCY.pop(key, None)
    return {"cleared_unknown": cleared, "replayable": replayable}


def begin_idempotent_replay(
    context: dict[str, Any], tool_id: str, action: str, params: dict[str, Any]
) -> tuple[str, dict[str, Any] | None]:
    """Return a cached success, or claim the key. Failures stay retryable."""
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
        current = _IDEMPOTENCY.get(key)
        if current is None:
            loaded = _load_claim(key)
            if loaded is not None:
                if loaded.get("inflight") and loaded.get("owner") not in _LIVE_OWNERS:
                    _delete_claim(key)
                    loaded = None
                else:
                    current = loaded
                    _IDEMPOTENCY[key] = current
        if current and current.get("fingerprint") != fingerprint:
            return key, _denial(
                "idempotency_conflict",
                "相同幂等键不能改用新的执行参数",
                context=context,
                tool_id=tool_id,
                action=action,
                reason="idempotency_conflict",
            )
        cached = current.get("output") if current else None
        if isinstance(cached, dict) and cached.get("success") is True:
            return key, dict(cached)
        if current and current.get("inflight") and current.get("owner") in _LIVE_OWNERS:
            return key, _denial(
                "idempotency_in_progress",
                "相同幂等键的调用正在执行",
                context=context,
                tool_id=tool_id,
                action=action,
                reason="idempotency_in_progress",
            )
        owner = uuid.uuid4().hex
        _LIVE_OWNERS.add(owner)
        record = {"fingerprint": fingerprint, "inflight": True, "output": None, "owner": owner}
        _IDEMPOTENCY[key] = record
        _persist_claim(key, record)
    return key, None


def finish_idempotent_replay(key: str, output: dict[str, Any]) -> None:
    if not key:
        return
    with _IDEMPOTENCY_LOCK:
        current = _IDEMPOTENCY.get(key)
        if current is None:
            return
        owner = str(current.get("owner") or "")
        _LIVE_OWNERS.discard(owner)
        if output.get("success") is True:
            current["output"] = dict(output)
            current["inflight"] = False
            _persist_claim(key, current)
            return
        _IDEMPOTENCY.pop(key, None)
        _delete_claim(key)


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
    empty_list = payload == [] and action not in {"read", "query", "list"}
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
    sealed = dict(context or {})
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
        "_actor_authorization": parent.get("_actor_authorization"),
        "_mod_authorization": parent.get("_mod_authorization"),
        "employee_id": employee_id,
        "employee_tool_allowlist": list(allowlist),
        "system_instruction": str(parent.get("system_instruction") or ""),
    }


def overlay_resume_context(stored: dict[str, Any] | None, incoming: dict[str, Any] | None) -> dict[str, Any]:
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
    return redact(
        {
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
    )


def attach_child_result(parent: Any, child: Any) -> bool:
    """Parent can read the child final result only inside the same tenant."""
    parent_tenant = str((parent.metadata.get("runtime_context") or {}).get("tenant_id") or "")
    child_context = child.metadata.get("runtime_context") or {}
    child_tenant = str(child_context.get("tenant_id") or "")
    if not parent_tenant or parent_tenant != child_tenant:
        return False
    parent.metadata.setdefault("child_results", {})[child.run_id] = {
        "status": child.status,
        "final_output": child.final_output,
        "parent_task_id": child_context.get("parent_task_id"),
        "parent_run_id": child_context.get("parent_run_id"),
        "tenant_id": child_tenant,
        "employee_id": child_context.get("employee_id"),
    }
    return True


def read_run_audit(run: Any, *, reader_tenant: str) -> dict[str, Any] | None:
    """Ordinary users cannot read another tenant's tool audit."""
    owner = str((run.metadata.get("runtime_context") or {}).get("tenant_id") or "")
    if not owner or str(reader_tenant) != owner:
        return None
    return {
        "run_id": run.run_id,
        "tenant_id": owner,
        "events": [event.to_dict() for event in run.events],
    }


def mutate_run_audit(run: Any, *, reader_tenant: str, message: str) -> bool:
    """Refuse writes to another tenant's audit log."""
    if read_run_audit(run, reader_tenant=reader_tenant) is None:
        return False
    run.add_event("audit.note", message, {"tenant_id": str(reader_tenant)})
    return True
