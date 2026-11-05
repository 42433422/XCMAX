"""Safe, repeatable burn-in for unproven duty-roster employees.

The burn-in is intentionally narrower than normal duty execution:

* low/read-only contracts may use a read-only agent; medium contracts are
  eligible only through a reviewed deterministic ``direct_python`` receipt;
* payment, release, external-message and destructive roles are denied by
  contract semantics and by handler type;
* generic ``echo``/``llm_md`` shells do not count as executable capability;
* agent work is forced into read-only mode and must produce a successful,
  programmatically verified observation receipt;
* execution is disabled by default.  The scheduler can still generate a dry
  plan continuously until an operator enables the reviewed runtime switch.

An executor metric is only left in ``success`` when acceptance passes.  Failed
or timed-out burn-ins retain an audit row and are never counted by execution
coverage as proof.
"""

from __future__ import annotations

import json
import logging
import os
import threading
import time
import uuid
from collections import Counter
from concurrent.futures import Future, ThreadPoolExecutor, wait
from datetime import UTC, datetime, timedelta, timezone  # noqa: F401
from pathlib import Path
from typing import Any, Callable, Dict, Iterable, Optional

from modstore_server.duty_workforce_burnin_constants import (
    READ_ONLY_AGENT_TOOLS as _READ_ONLY_AGENT_TOOLS,
)
from modstore_server.duty_workforce_burnin_constants import (
    READ_ONLY_OBSERVATION_TOOLS as _READ_ONLY_OBSERVATION_TOOLS,
)
from modstore_server.models import EmployeeExecutionMetric, get_session_factory
from modstore_server.operational_errors import RECOVERABLE_ERRORS


def validate_burn_in_execution_result(execution: Dict[str, Any]) -> Dict[str, Any]:
    """Strict acceptance gate shared by the executor and burn-in orchestrator."""
    reasons: list[str] = []
    if not isinstance(execution, dict):
        return {"passed": False, "reasons": ["execution_not_object"]}
    if execution.get("handler_failed"):
        reasons.append("executor_handler_failed")
    result = execution.get("result") if isinstance(execution.get("result"), dict) else {}
    verification = (
        result.get("verification") if isinstance(result.get("verification"), dict) else {}
    )
    if verification.get("passed") is not True:
        reasons.append("programmatic_verification_failed")
    outputs = result.get("outputs") if isinstance(result.get("outputs"), list) else []
    agent_outputs = [
        item for item in outputs if isinstance(item, dict) and item.get("handler") == "agent"
    ]
    direct_outputs = [
        item
        for item in outputs
        if isinstance(item, dict) and item.get("handler") == "direct_python"
    ]
    if not agent_outputs and (not direct_outputs):
        reasons.append("no_capability_output")
    for output in outputs:
        if not isinstance(output, dict):
            reasons.append("invalid_handler_output")
            continue
        if output.get("ok") is False or str(output.get("error") or "").strip():
            reasons.append(f"handler_failed:{output.get('handler') or '?'}")
    for output in agent_outputs:
        kinds = {str(item) for item in output.get("tool_call_kinds") or [] if str(item)}
        if not kinds.intersection(_READ_ONLY_OBSERVATION_TOOLS):
            reasons.append("no_successful_read_only_observation")
        if not kinds.issubset(_READ_ONLY_AGENT_TOOLS):
            reasons.append("non_read_only_tool_attempted")
        if int(output.get("tool_call_success_count") or 0) < 1:
            reasons.append("no_successful_tool_call")
        if output.get("change_request_ids"):
            reasons.append("change_request_created")
    for output in direct_outputs:
        body = output.get("output") if isinstance(output.get("output"), dict) else {}
        status = str(body.get("status") or "").strip().lower()
        summary = str(body.get("summary") or "").strip()
        evidence = body.get("evidence") if isinstance(body.get("evidence"), list) else []
        if body.get("ok") is not True:
            reasons.append("direct_python_output_not_ok")
        if status not in {"success", "approved", "completed"}:
            reasons.append("direct_python_status_not_success")
        if len(summary) < 10:
            reasons.append("direct_python_summary_missing")
        if not evidence:
            reasons.append("direct_python_evidence_missing")
        if body.get("read_only") is not True:
            reasons.append("direct_python_not_read_only")
        if body.get("side_effects") != []:
            reasons.append("direct_python_side_effects_present")
    bridge = (
        result.get("change_request_bridge")
        if isinstance(result.get("change_request_bridge"), dict)
        else {}
    )
    if bridge and bridge.get("suppressed") is not True:
        reasons.append("change_request_bridge_not_suppressed")
    if execution.get("change_request_ids") or result.get("change_request_ids"):
        reasons.append("change_request_created")
    unique = list(dict.fromkeys(reasons))
    tool_kinds = sorted(
        {
            str(kind)
            for output in agent_outputs
            for kind in output.get("tool_call_kinds") or []
            if str(kind)
        }
    )
    return {
        "passed": not unique,
        "reasons": unique,
        "verification": {
            "passed": verification.get("passed") is True,
            "summary": str(verification.get("summary") or "")[:500],
        },
        "agent_observation_count": len(agent_outputs),
        "direct_python_receipt_count": len(direct_outputs),
        "tool_call_kinds": tool_kinds,
        "tool_call_success_count": sum(
            (int(output.get("tool_call_success_count") or 0) for output in agent_outputs)
        ),
        "tool_call_failure_count": sum(
            (int(output.get("tool_call_failure_count") or 0) for output in agent_outputs)
        ),
    }


def _mark_receipt_rejected(employee_id: str, marker: str, status: str, reason: str) -> bool:
    """Invalidate only the metric emitted for this exact burn-in marker."""
    sf = get_session_factory()
    with sf() as session:
        row = (
            session.query(EmployeeExecutionMetric)
            .filter(
                EmployeeExecutionMetric.employee_id == employee_id,
                EmployeeExecutionMetric.task.like(f"{marker}%"),
                EmployeeExecutionMetric.status.in_(["success", "completed"]),
            )
            .order_by(EmployeeExecutionMetric.id.desc())
            .first()
        )
        if row is None:
            return False
        row.status = str(status or "burnin_rejected")[:32]
        row.error = str(reason or "burn-in acceptance rejected")[:4000]
        session.commit()
        return True


def _project_root() -> str:
    try:
        from modstore_server.workflow_scheduler import _employee_project_root

        return str(_employee_project_root() or "")
    except RECOVERABLE_ERRORS:
        return ""


def _execute_one(
    candidate: Dict[str, Any],
    *,
    run_id: str,
    deadline_epoch: float,
    executor: Callable[..., Dict[str, Any]],
) -> Dict[str, Any]:
    employee_id = str(candidate["employee_id"])
    marker = f"[duty-burn-in:{run_id}:{employee_id}]"
    contract = {
        "employee_id": employee_id,
        "mission": candidate.get("mission"),
        "mode": candidate.get("mode"),
        "risk_level": candidate.get("risk_level"),
        "acceptance": list(candidate.get("acceptance") or []),
    }
    task = _candidate_task(employee_id, contract, marker)
    if "direct_python" in candidate.get("capability_handlers", []):
        task = _candidate_direct_task(employee_id, marker)
    project_root = _project_root()
    from modstore_server.services.llm import resolve_platform_bench_llm

    provider, model = resolve_platform_bench_llm()
    payload: Dict[str, Any] = {
        "trigger": "duty_workforce_burn_in",
        "burn_in": True,
        "burn_in_read_only": True,
        "burn_in_deadline_epoch": float(deadline_epoch),
        "suppress_employee_im": True,
        "suppress_handoff": True,
        "suppress_human_questions": True,
        "suppress_change_requests": True,
        "suppress_lifecycle_events": True,
        "im_reply_managed": True,
        "non_blocking_human_questions": True,
        "allow_medium_risk": False,
        "allow_high_risk": False,
        "allow_high_risk_real_run": False,
        "handler_mode": "agent",
        "multi_step": True,
        "work_contract": contract,
    }
    fixture = (
        candidate.get("burn_in_fixture")
        if isinstance(candidate.get("burn_in_fixture"), dict)
        else {}
    )
    if "direct_python" in candidate.get("capability_handlers", []):
        payload.update(fixture)
        payload["handler"] = "direct_python"
        payload["handler_mode"] = "direct_python"
        payload["multi_step"] = False
    if project_root:
        payload["project_root"] = project_root
    try:
        execution = executor(
            employee_id,
            task,
            payload,
            user_id=0,
            bench_llm_override=(provider, model) if provider and model else None,
        )
    except RECOVERABLE_ERRORS as exc:
        return {
            "employee_id": employee_id,
            "marker": marker,
            "status": "failed",
            "receipt_accepted": False,
            "manifest_sha256": str(candidate.get("manifest_sha256") or ""),
            "contract_sha256": str(candidate.get("contract_sha256") or ""),
            "error": f"{type(exc).__name__}: {str(exc)[:1000]}",
        }
    acceptance = validate_burn_in_execution_result(execution)
    if not acceptance["passed"]:
        reason = ";".join(acceptance["reasons"])[:1000]
        _mark_receipt_rejected(employee_id, marker, "burnin_rejected", reason)
        status = "rejected"
    else:
        status = "accepted"
    return {
        "employee_id": employee_id,
        "marker": marker,
        "status": status,
        "receipt_accepted": bool(acceptance["passed"]),
        "manifest_sha256": str(candidate.get("manifest_sha256") or ""),
        "contract_sha256": str(candidate.get("contract_sha256") or ""),
        "acceptance": acceptance,
        "duration_ms": execution.get("duration_ms"),
        "executed_at": execution.get("executed_at"),
    }


def run_burn_in(
    *,
    dry_run: bool = True,
    window_hours: int = 24,
    limit: Optional[int] = None,
    timeout_seconds: Optional[int] = None,
    max_concurrency: Optional[int] = None,
    _plan: Optional[Dict[str, Any]] = None,
    _executor: Optional[Callable[..., Dict[str, Any]]] = None,
) -> Dict[str, Any]:
    """Plan or execute one bounded burn-in wave.

    ``dry_run=False`` still cannot execute unless
    ``MODSTORE_EMPLOYEE_BURN_IN_ENABLED=1`` is present in the effective runtime.
    """
    plan = _plan or build_burn_in_plan(window_hours=window_hours, limit=limit)
    if dry_run:
        return plan
    if not burn_in_execution_enabled():
        return {
            **plan,
            "dry_run": True,
            "execution_blocked": True,
            "blocked_reason": "MODSTORE_EMPLOYEE_BURN_IN_ENABLED is not enabled",
        }
    if not _run_lock.acquire(blocking=False):
        return {
            **plan,
            "dry_run": False,
            "executed": False,
            "reason": "already_running",
        }
    lingering = _lingering_execution_count()
    if lingering:
        _run_lock.release()
        return {
            **plan,
            "dry_run": False,
            "executed": False,
            "reason": "previous_timeout_still_running",
            "lingering_execution_count": lingering,
        }
    limits = burn_in_limits()
    timeout = max(30, min(int(timeout_seconds or limits["timeout_seconds"]), 300))
    concurrency = max(1, min(int(max_concurrency or limits["max_concurrency"]), 2))
    selected = list(plan.get("candidates") or [])[: limits["max_candidates"]]
    run_id = uuid.uuid4().hex[:12]
    results: list[Dict[str, Any]] = []
    executor_fn = _executor
    if executor_fn is None:
        from modstore_server.employee_executor import execute_employee_task

        executor_fn = execute_employee_task
    try:
        for start in range(0, len(selected), concurrency):
            batch = selected[start : start + concurrency]
            pool = ThreadPoolExecutor(max_workers=concurrency, thread_name_prefix="duty-burn-in")
            futures: Dict[Future[Dict[str, Any]], Dict[str, Any]] = {
                pool.submit(
                    _execute_one,
                    item,
                    run_id=run_id,
                    deadline_epoch=time.time() + timeout,
                    executor=executor_fn,
                ): item
                for item in batch
            }
            done, pending = wait(set(futures), timeout=timeout)
            for future in done:
                item = futures[future]
                try:
                    row = future.result()
                except RECOVERABLE_ERRORS as exc:
                    row = {
                        "employee_id": str(item.get("employee_id") or ""),
                        "status": "failed",
                        "receipt_accepted": False,
                        "error": f"orchestrator:{type(exc).__name__}:{str(exc)[:500]}",
                    }
                results.append(row)
                _append_audit({"run_id": run_id, **row})
            for future in pending:
                item = futures[future]
                employee_id = str(item.get("employee_id") or "")
                marker = f"[duty-burn-in:{run_id}:{employee_id}]"
                future.cancel()
                if not future.done():
                    _track_lingering_future(future)
                invalidated = _mark_receipt_rejected(
                    employee_id,
                    marker,
                    "burnin_timeout",
                    f"burn-in exceeded {timeout}s",
                )
                row = {
                    "employee_id": employee_id,
                    "marker": marker,
                    "status": "timeout",
                    "receipt_accepted": False,
                    "manifest_sha256": str(item.get("manifest_sha256") or ""),
                    "contract_sha256": str(item.get("contract_sha256") or ""),
                    "timeout_seconds": timeout,
                    "success_metric_invalidated": invalidated,
                }
                results.append(row)
                _append_audit({"run_id": run_id, **row})
            pool.shutdown(wait=False, cancel_futures=True)
    finally:
        _run_lock.release()
    accepted = sum((1 for item in results if item.get("receipt_accepted") is True))
    summary = {
        "ok": accepted == len(results),
        "dry_run": False,
        "executed": True,
        "run_id": run_id,
        "selected_count": len(selected),
        "completed_count": len(results),
        "accepted_receipt_count": accepted,
        "rejected_or_failed_count": len(results) - accepted,
        "results": sorted(results, key=lambda item: str(item.get("employee_id") or "")),
        "limits": {
            **limits,
            "timeout_seconds": timeout,
            "max_concurrency": concurrency,
        },
        "audit_path": str(burn_in_audit_path()),
    }
    _append_audit(
        {
            "run_id": run_id,
            "record_type": "run_summary",
            "selected_count": len(selected),
            "accepted_receipt_count": accepted,
            "rejected_or_failed_count": len(results) - accepted,
        }
    )
    return summary


from modstore_server.duty_workforce_contracts import (
    load_reviewed_duty_manifest,
    workforce_contract_map,
)
from modstore_server.duty_workforce_receipts import (
    fresh_accepted_receipt_identities,
    recent_attempt_manifest_shas,
)


def _recent_attempt_ids(cooldown_hours: int, now: datetime) -> set[str]:
    cutoff = now.replace(tzinfo=None) - timedelta(hours=max(1, cooldown_hours))
    sf = get_session_factory()
    with sf() as session:
        rows = (
            session.query(EmployeeExecutionMetric.employee_id)
            .filter(
                EmployeeExecutionMetric.task.like("[duty-burn-in:%"),
                EmployeeExecutionMetric.created_at >= cutoff,
            )
            .distinct()
            .all()
        )
    return {str(row[0]) for row in rows if str(row[0] or "").strip()}


def _load_manifest(employee_id: str) -> Dict[str, Any]:
    return load_reviewed_duty_manifest(employee_id)


def _candidate_task(employee_id: str, contract: Dict[str, Any], marker: str) -> str:
    acceptance = [
        str(item).strip() for item in contract.get("acceptance") or [] if str(item).strip()
    ]
    return f"{marker} 执行一次岗位只读巡检回执。岗位：{employee_id}。任务：{str(contract.get('mission') or '').strip()}。必须至少调用一次工作区只读工具获取真实证据；禁止写文件、运行命令、访问外网、发消息、转交任务、创建变更或执行任何业务副作用。验收要求：{'；'.join(acceptance) or '输出可追溯证据'}。认知结果与最终答案都必须使用 JSON 对象，包含 status=success、不少于 10 个字的 summary 和 evidence 字段，并且只能根据工具真实结果下结论；缺证据就明确失败，不得伪造回执。"


def _candidate_direct_task(employee_id: str, marker: str) -> str:
    """Describe only the reviewed deterministic sub-capability being proven."""
    return f"{marker} 执行一次岗位确定性只读子能力回执。岗位：{employee_id}。仅使用 manifest 中已审查的 burn_in_fixture 验证声明的输入输出契约；不得声称完整岗位的写入、构建、派发、发布或外联职责已经执行。输出必须由 direct_python 入口产生，并包含 status=success/approved、不少于 10 个字的 summary、evidence、read_only=true 和 side_effects=[]。"


def build_burn_in_plan(
    *,
    window_hours: int = 24,
    limit: Optional[int] = None,
    now: Optional[datetime] = None,
    _contracts: Optional[Dict[str, Dict[str, Any]]] = None,
    _manifests: Optional[Dict[str, Dict[str, Any]]] = None,
    _proven_ids: Optional[Iterable[str]] = None,
    _recent_ids: Optional[Iterable[str]] = None,
    _recent_manifest_shas: Optional[Dict[str, Iterable[str]]] = None,
) -> Dict[str, Any]:
    """Build a dry plan without invoking an employee or producing a receipt."""
    observed_at = now or datetime.now(timezone.utc)
    limits = burn_in_limits()
    max_candidates = max(
        1, min(int(limit or limits["max_candidates"]), limits["max_candidates"], 8)
    )
    contracts = _contracts if _contracts is not None else workforce_contract_map()
    proven_override = {str(item) for item in _proven_ids} if _proven_ids is not None else None
    accepted_receipts = (
        {}
        if proven_override is not None
        else fresh_accepted_receipt_identities(burn_in_audit_path(), window_hours, observed_at)
    )
    recent = (
        {str(item) for item in _recent_ids}
        if _recent_ids is not None
        else _recent_attempt_ids(limits["cooldown_hours"], observed_at)
    )
    recent_manifest_shas = (
        {
            str(employee_id): {str(value).strip().lower() for value in values if str(value).strip()}
            for (employee_id, values) in _recent_manifest_shas.items()
        }
        if _recent_manifest_shas is not None
        else recent_attempt_manifest_shas(
            burn_in_audit_path(), limits["cooldown_hours"], observed_at
        )
    )
    manifests = _manifests or {}
    candidates: list[Dict[str, Any]] = []
    skipped: list[Dict[str, str]] = []
    fresh_proven_count = 0
    for employee_id in sorted(contracts):
        contract = dict(contracts[employee_id] or {})
        contract.setdefault("employee_id", employee_id)
        try:
            manifest = manifests.get(employee_id) or _load_manifest(employee_id)
        except RECOVERABLE_ERRORS as exc:
            skipped.append(
                {
                    "employee_id": employee_id,
                    "reason": f"manifest_unavailable:{type(exc).__name__}",
                }
            )
            continue
        manifest_sha256 = _payload_sha256(manifest)
        contract_sha256 = _payload_sha256(contract)
        has_fresh_proof = (
            employee_id in proven_override
            if proven_override is not None
            else (manifest_sha256, contract_sha256) in accepted_receipts.get(employee_id, set())
        )
        if has_fresh_proof:
            fresh_proven_count += 1
            skipped.append({"employee_id": employee_id, "reason": "fresh_receipt_exists"})
            continue
        if employee_id in recent:
            attempted_shas = recent_manifest_shas.get(employee_id) or set()
            if not attempted_shas or manifest_sha256 in attempted_shas:
                skipped.append({"employee_id": employee_id, "reason": "attempt_cooldown"})
                continue
        eligibility = assess_burn_in_eligibility(employee_id, contract, manifest)
        if eligibility.get("eligible") is not True:
            skipped.append(
                {
                    "employee_id": employee_id,
                    "reason": str(eligibility.get("reason") or "blocked"),
                }
            )
            continue
        candidates.append(
            {
                "employee_id": employee_id,
                "risk_level": str(eligibility.get("risk_level") or ""),
                "mode": str(contract.get("mode") or ""),
                "mission": str(contract.get("mission") or ""),
                "acceptance": list(contract.get("acceptance") or []),
                "handlers": list(eligibility.get("handlers") or []),
                "capability_handlers": list(eligibility.get("capability_handlers") or []),
                "manifest_source": "reviewed_duty_ssot",
                "manifest_sha256": manifest_sha256,
                "contract_sha256": contract_sha256,
                "forced_read_only": True,
                "burn_in_fixture": dict(eligibility.get("burn_in_fixture") or {}),
                "prohibited_semantics_fixture_override": bool(
                    eligibility.get("prohibited_semantics_fixture_override")
                ),
                "high_risk_fixture_only": bool(eligibility.get("high_risk_fixture_only")),
            }
        )
    selected = candidates[:max_candidates]
    deferred = candidates[max_candidates:]
    if deferred:
        skipped.extend(
            ({"employee_id": item["employee_id"], "reason": "per_run_limit"} for item in deferred)
        )
    reason_counts = Counter((item["reason"].split(":", 1)[0] for item in skipped))
    return {
        "ok": True,
        "dry_run": True,
        "execution_enabled": burn_in_execution_enabled(),
        "observed_at": observed_at.isoformat(),
        "window_hours": max(1, int(window_hours)),
        "planned_count": len(contracts),
        "fresh_proven_count": fresh_proven_count,
        "candidate_count_before_limit": len(candidates),
        "max_eventual_new_receipts": len(candidates),
        "selected_count": len(selected),
        "estimated_new_receipts": len(selected),
        "candidates": selected,
        "skipped": skipped,
        "skip_reason_counts": dict(sorted(reason_counts.items())),
        "limits": limits,
        "safety": {
            "forced_read_only": True,
            "external_network": False,
            "external_messages": False,
            "handoff": False,
            "change_requests": False,
            "high_risk_read_only_direct": any(
                (item.get("high_risk_fixture_only") for item in selected)
            ),
            "medium_risk_read_only_direct": any(
                (
                    item.get("risk_level") == "medium"
                    and item.get("capability_handlers") == ["direct_python"]
                    for item in selected
                )
            ),
            "medium_or_high_risk_side_effects": False,
            "prohibited_semantics_fixture_override": any(
                (item.get("prohibited_semantics_fixture_override") for item in selected)
            ),
            "payment_release_delete_roles": False,
            "generic_shells_count_as_receipts": False,
        },
    }


from modstore_server import duty_workforce_burnin_policy as _policy

logger = logging.getLogger(__name__)

_audit_lock = threading.Lock()
_run_lock = threading.Lock()
_lingering_lock = threading.Lock()
_lingering_futures: set[Future[Dict[str, Any]]] = set()


def _env_bool(name: str, default: bool = False) -> bool:
    raw = str(os.environ.get(name) or ("1" if default else "0")).strip().lower()
    return raw in {"1", "true", "yes", "on"}


def _bounded_int(name: str, default: int, minimum: int, maximum: int) -> int:
    try:
        value = int(str(os.environ.get(name) or default).strip())
    except (TypeError, ValueError):
        value = default
    return max(minimum, min(maximum, value))


def burn_in_execution_enabled() -> bool:
    """Real execution is fail-closed and off until explicitly reviewed."""

    return _env_bool("MODSTORE_EMPLOYEE_BURN_IN_ENABLED", False)


def burn_in_scheduler_enabled() -> bool:
    return _env_bool("MODSTORE_EMPLOYEE_BURN_IN_SCHEDULER_ENABLED", True)


def burn_in_limits() -> Dict[str, int]:
    return {
        "max_candidates": _bounded_int("MODSTORE_EMPLOYEE_BURN_IN_MAX_PER_RUN", 2, 1, 8),
        "max_concurrency": _bounded_int("MODSTORE_EMPLOYEE_BURN_IN_MAX_CONCURRENCY", 1, 1, 2),
        "timeout_seconds": _bounded_int("MODSTORE_EMPLOYEE_BURN_IN_TIMEOUT_SECONDS", 240, 30, 300),
        "cooldown_hours": _bounded_int("MODSTORE_EMPLOYEE_BURN_IN_COOLDOWN_HOURS", 6, 1, 168),
    }


def _runtime_dir() -> Path:
    raw = str(os.environ.get("MODSTORE_RUNTIME_DIR") or "/tmp/modstore_runtime").strip()
    return Path(raw).expanduser()


def burn_in_audit_path() -> Path:
    raw = str(os.environ.get("MODSTORE_EMPLOYEE_BURN_IN_AUDIT_PATH") or "").strip()
    return Path(raw).expanduser() if raw else _runtime_dir() / "duty_workforce_burnin.jsonl"


def _append_audit(payload: Dict[str, Any]) -> None:
    row = {
        "schema": "xcagi.duty_workforce_burnin.audit/v1",
        "recorded_at": datetime.now(UTC).isoformat(),
        **payload,
    }
    path = burn_in_audit_path()
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with _audit_lock, path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(row, ensure_ascii=False, sort_keys=True, default=str) + "\n")
    except OSError:
        logger.exception("duty burn-in audit write failed path=%s", path)


def _track_lingering_future(future: Future[Dict[str, Any]]) -> None:
    with _lingering_lock:
        _lingering_futures.add(future)

    def _done(done: Future[Dict[str, Any]]) -> None:
        with _lingering_lock:
            _lingering_futures.discard(done)

    future.add_done_callback(_done)


def _lingering_execution_count() -> int:
    with _lingering_lock:
        return sum(1 for future in _lingering_futures if not future.done())


_actions_config = _policy._actions_config
_extract_handlers = _policy._extract_handlers
_contract_semantics = _policy._contract_semantics
_payload_sha256 = _policy._payload_sha256
_prohibited_contract_reason = _policy._prohibited_contract_reason
assess_burn_in_eligibility = _policy.assess_burn_in_eligibility
