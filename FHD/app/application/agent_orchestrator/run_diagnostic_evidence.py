"""Privacy-bounded evidence stored in the existing immutable work-order context.

The reproduction scope is the diagnostic classification, not business execution.
Only fields consumed by the existing classifier are projected into a versioned
snapshot; prompts, parameters, outputs, credentials and account names stay out.
The digest detects corruption, not authenticity: the existing SSOT owns access
and immutable incident history. Replay never loads a task or executes a tool.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import math
import re
from datetime import UTC, datetime
from types import SimpleNamespace
from typing import Any

from app.application.agent_orchestrator.task_models import mod_id_of_run, tenant_id_of_run

_PROTOCOL = "xcagi.agent-diagnostic-reproduction.v1"
_SCOPE = "diagnostic_classification"
_STATES = frozenset(
    [
        "queued",
        "claimed",
        "planning",
        "running",
        "retrying",
        "submitted",
        "accepted",
        "waiting_user",
        "waiting_input",
        "waiting_approval",
        "waiting_auth",
        "paused",
        "blocked",
        "unknown",
        "failed",
        "timed_out",
        "completed",
        "succeeded",
        "cancelled",
        "rejected",
        "pending",
        "reserved",
        "settled",
    ]
)
_STAGES = frozenset(
    [
        "model",
        "planning",
        "planner",
        "tool",
        "business",
        "persistence",
        "database",
        "storage",
        "goal_verification",
        "verification",
        "quality_control",
        "collaboration",
        "handoff",
        "delivery",
        "runtime",
    ]
)
_PUBLIC_CODES = frozenset(
    [
        "runtime_budget_exhausted",
        "runtime_policy_blocked",
        "permission_denied",
        "invalid_params",
        "context_window_exceeded",
        "model_request_timeout",
        "model_request_failed",
        "model_response_invalid",
        "llm_timeout",
        "rate_limited",
        "goal_verification_timeout",
        "goal_verification_unavailable",
        "goal_evidence_pending",
        "goal_evidence_conflict",
        "verification_source_unavailable",
        "database_locked",
        "sqlite_locked",
        "database_unavailable",
        "tool_timeout",
        "delivery_unavailable",
        "model_usage_unknown",
        "business_outcome_unknown",
        "outcome_unknown",
        "worker_lease_expired",
        "active_deadline_exceeded",
        "verification_lease_expired",
        "queue_overdue",
        "progress_stalled",
        "unclassified_failure",
        "child_receipt_missing",
    ]
)
_CONTROL_CODES = _PUBLIC_CODES | {"goal_verification_required", "runtime_failed"}
_LAYERS = frozenset(
    [
        "runtime",
        "model",
        "planning",
        "tool",
        "persistence",
        "verification",
        "collaboration",
        "delivery",
        "unknown",
    ]
)
_KINDS = (
    _PUBLIC_CODES
    | {f"{layer}_failed" for layer in _LAYERS}
    | {
        "lease_expired",
        "deadline_exceeded",
    }
)
_IDENTIFIER = re.compile(r"^(?:run|task|evt|call|step|req)_[0-9a-f]{32}$")
_HASH_REFERENCE = re.compile(r"^sha256:[0-9a-f]{64}$")


def diagnostic_digest(value: Any) -> str:
    """Keep the existing work-order digest and deduplication encoding stable."""
    return hashlib.sha256(
        json.dumps(value, ensure_ascii=False, sort_keys=True, default=str).encode()
    ).hexdigest()


def _dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _reference(value: Any) -> str:
    text = str(value or "")
    if not text or _IDENTIFIER.fullmatch(text) or _HASH_REFERENCE.fullmatch(text):
        return text
    return f"sha256:{diagnostic_digest(text)}"


def _revision(value: Any) -> str | None:
    text = str(value or "")
    return text if re.fullmatch(r"[0-9a-f]{40}", text) else None


def _clock(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    try:
        if isinstance(value, str):
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
            value = (
                parsed.replace(tzinfo=UTC).timestamp()
                if parsed.tzinfo is None
                else parsed.timestamp()
            )
        result = float(value)
        return result if math.isfinite(result) and result > 0 else None
    except (TypeError, ValueError, OverflowError):
        return None


def _number(value: Any) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise ValueError("diagnostic clock or threshold is not finite")
    return float(value)


def _enum(value: Any, allowed: frozenset[str]) -> str:
    text = str(value or "")
    return text if not text or text in allowed else "unrecognized"


def _code(value: Any) -> str:
    text = str(value or "")
    return text if not text or text in _CONTROL_CODES else "unclassified_failure"


def _model_states(runtime: dict[str, Any]) -> dict[str, Any]:
    return {
        "reconciliation_required": bool(runtime.get("model_reconciliation_required")),
        "request_states": sorted(
            {
                _enum(request.get("state"), _STATES)
                for request in _dict(runtime.get("model_requests")).values()
                if isinstance(request, dict)
            }
        ),
    }


def _inputs(run, execution, *, now, stale_after_seconds, missing_child_refs):
    metadata = run.metadata
    runtime = _dict(metadata.get("xiaox_runtime"))
    result = _dict(run.final_output.get("xiaox_result")) or run.final_output
    children = list(_dict(metadata.get("child_results")).values())
    children += list(_dict(runtime.get("calls")).values())
    checks = {
        (
            _enum(call.status, _STATES),
            _enum(_dict(call.metadata.get("verification")).get("status"), _STATES),
        )
        for call in run.tool_calls
    }
    return {
        "now": _number(now),
        "stale_after_seconds": _number(stale_after_seconds),
        "missing_child_refs": sorted({_reference(value) for value in missing_child_refs}),
        "run": {
            "status": _enum(run.status, _STATES),
            "created_at": _clock(run.created_at),
            "updated_at": _clock(run.updated_at),
            "failure_stage": _enum(metadata.get("runtime_failure_stage"), _STAGES),
            "failure_kind": _code(metadata.get("runtime_failure_kind")),
            "goal_error_code": _code(
                _dict(metadata.get("runtime_goal_verification")).get("error_code")
            ),
            "result": {
                "ok": bool(result.get("ok")),
                "execution_state": _enum(result.get("execution_state"), _STATES),
                "exit_status": _code(result.get("exit_status")),
                "error_code": _code(result.get("error_code")),
            },
            "xiaox": {
                "coordinator_active": runtime.get("coordinator_active") is True,
                "waiting_input": bool(runtime.get("waiting_input")),
                "deadline_at": _clock(runtime.get("deadline_at")),
                **_model_states(runtime),
            },
            "codex": _model_states(_dict(metadata.get("codex_runtime"))),
            "child_states": sorted(
                {
                    _enum(str(child.get("status") or child.get("state")), _STATES)
                    for child in children
                    if isinstance(child, dict)
                }
            ),
            "tool_verification_states": [
                {"status": status, "verification_status": verification}
                for status, verification in sorted(checks)
            ],
            "verification_lease_until": _clock(
                _dict(metadata.get("verification_recovery")).get("lease_until")
            ),
        },
        "execution": None
        if execution is None
        else {
            "state": _enum(execution.state, _STATES),
            **{
                key: _clock(getattr(execution, key, None))
                for key in ("heartbeat_at", "lease_expires_at", "available_at")
            },
        },
    }


def _restore(inputs):
    """Anonymous, inert views of the classifier's existing input shapes."""
    saved = inputs["run"]
    runtimes = {
        key: {
            "model_reconciliation_required": saved[key]["reconciliation_required"],
            "model_requests": {
                str(index): {"state": state}
                for index, state in enumerate(saved[key]["request_states"])
            },
        }
        for key in ("xiaox", "codex")
    }
    runtimes["xiaox"].update(
        {key: saved["xiaox"][key] for key in ("coordinator_active", "waiting_input", "deadline_at")}
    )
    run = SimpleNamespace(
        status=saved["status"],
        created_at=saved["created_at"],
        updated_at=saved["updated_at"],
        final_output=saved["result"],
        metadata={
            "xiaox_runtime": runtimes["xiaox"],
            "codex_runtime": runtimes["codex"],
            "runtime_failure_stage": saved["failure_stage"],
            "runtime_failure_kind": saved["failure_kind"],
            "runtime_goal_verification": {"error_code": saved["goal_error_code"]},
            "verification_recovery": {"lease_until": saved["verification_lease_until"]},
            "child_results": {
                str(index): {"state": state} for index, state in enumerate(saved["child_states"])
            },
        },
        tool_calls=[
            SimpleNamespace(
                status=check["status"],
                metadata={"verification": {"status": check["verification_status"]}},
            )
            for check in saved["tool_verification_states"]
        ],
    )
    execution = None if inputs["execution"] is None else SimpleNamespace(**inputs["execution"])
    return run, execution


def _finding(value: dict[str, Any] | None) -> dict[str, Any] | None:
    if value is None:
        return None
    if value["layer"] not in _LAYERS or value["kind"] not in _KINDS:
        raise ValueError("diagnostic finding is outside the public schema")
    safe = {
        "layer": value["layer"],
        "kind": value["kind"],
        "code": value["code"] if value["code"] in _PUBLIC_CODES else "unclassified_failure",
    }
    if "missing_child_refs" in value:
        safe["missing_child_refs"] = sorted(
            {_reference(ref) for ref in value["missing_child_refs"]}
        )
    return safe


def build_reproduction(
    run, execution=None, *, now, stale_after_seconds=300.0, missing_child_refs=()
):
    """Freeze only the allowlisted classifier input; unknown error prose is lost."""
    from app.application.agent_orchestrator.run_diagnostics import diagnose_run

    inputs = _inputs(
        run,
        execution,
        now=now,
        stale_after_seconds=stale_after_seconds,
        missing_child_refs=missing_child_refs,
    )
    expected = _finding(
        diagnose_run(
            run,
            execution,
            now=now,
            stale_after_seconds=stale_after_seconds,
            missing_child_refs=missing_child_refs,
        )
    )
    snapshot = {"protocol": _PROTOCOL, "scope": _SCOPE, "inputs": inputs, "expected": expected}
    snapshot["sha256"] = diagnostic_digest(snapshot)
    # A new classifier dependency must be explicitly added to this projection;
    # never publish evidence which cannot reproduce the observed public result.
    replay_reproduction(snapshot)
    return snapshot


def replay_reproduction(snapshot: dict[str, Any]) -> dict[str, Any] | None:
    """Verify a frozen v1 snapshot and run the existing classifier without I/O."""
    from app.application.agent_orchestrator.run_diagnostics import diagnose_run

    try:
        if (
            not isinstance(snapshot, dict)
            or set(snapshot) != {"protocol", "scope", "inputs", "expected", "sha256"}
            or snapshot["protocol"] != _PROTOCOL
            or snapshot["scope"] != _SCOPE
            or not isinstance(snapshot["sha256"], str)
        ):
            raise ValueError("unsupported diagnostic reproduction schema")
        body = {key: value for key, value in snapshot.items() if key != "sha256"}
        if not hmac.compare_digest(diagnostic_digest(body), snapshot["sha256"]):
            raise ValueError("diagnostic reproduction digest mismatch")
        inputs = snapshot["inputs"]
        run, execution = _restore(inputs)
        now = _number(inputs["now"])
        stale_after_seconds = _number(inputs["stale_after_seconds"])
        missing_child_refs = tuple(inputs["missing_child_refs"])
        options = {
            "now": now,
            "stale_after_seconds": stale_after_seconds,
            "missing_child_refs": missing_child_refs,
        }
        if diagnostic_digest(_inputs(run, execution, **options)) != diagnostic_digest(inputs):
            raise ValueError("diagnostic reproduction contains noncanonical or private fields")
        result = _finding(
            diagnose_run(
                run,
                execution,
                now=now,
                stale_after_seconds=stale_after_seconds,
                missing_child_refs=missing_child_refs,
            )
        )
        if diagnostic_digest(result) != diagnostic_digest(snapshot["expected"]):
            raise ValueError("diagnostic reproduction no longer matches its recorded finding")
        return result
    except (AttributeError, KeyError, TypeError, OverflowError) as exc:
        raise ValueError("invalid diagnostic reproduction snapshot") from exc


def build_diagnostic_evidence(
    run,
    execution,
    finding,
    *,
    now,
    observer_sha,
    payload_sha,
    stale_after_seconds=300.0,
    missing_child_refs=(),
):
    from app.application.agent_orchestrator.task_context import ensure_run_trace

    context = _dict(run.metadata.get("task_context"))
    source_event = next(
        (
            event
            for event in reversed(run.events)
            if _revision(event.data.get("source_sha"))
            and event.event_type
            in {"run.started", "runtime.started", "runtime.xiaox.started", "run.observed"}
        ),
        None,
    )
    source = source_event.data["source_sha"] if source_event else None
    persistence = next(
        (event for event in reversed(run.events) if event.event_type == "run.state_changed"), None
    )
    reproduction = build_reproduction(
        run,
        execution,
        now=now,
        stale_after_seconds=stale_after_seconds,
        missing_child_refs=missing_child_refs or finding.get("missing_child_refs", ()),
    )
    if _finding(finding) != reproduction["expected"]:
        raise ValueError("diagnostic finding changed before evidence capture")
    safe = {
        "protocol": "xcagi.agent-diagnostic.v1",
        "observed_at": datetime.fromtimestamp(now, UTC).isoformat(),
        "observer_source_sha": _revision(observer_sha),
        "execution_source_sha": _revision(source),
        "execution_source_status": "recorded" if source else "unavailable",
        "execution_source_event_id": _reference(source_event.event_id) if source_event else None,
        "persistence_source_sha": _revision(persistence.data.get("source_sha"))
        if persistence
        else None,
        "run_id": _reference(run.run_id),
        "task_id": _reference(context.get("task_id") or run.run_id),
        "scope_sha256": diagnostic_digest((tenant_id_of_run(run), run.user_id, mod_id_of_run(run))),
        "trace_id": ensure_run_trace(run, live=False)["trace_id"],
        "run_status": _enum(run.status, _STATES),
        **_finding(finding),
        "reported_code_sha256": diagnostic_digest(finding["code"]),
        "source_payload_sha256": payload_sha,
        "source_payload_retained": False,
        "source_event_ids": [_reference(event.event_id) for event in run.events[-12:]],
        "missing_child_refs": [
            _reference(value) for value in finding.get("missing_child_refs", ())
        ],
        "created_at": _clock(run.created_at),
        "updated_at": _clock(run.updated_at),
        "execution": {
            key: _clock(getattr(execution, key, None))
            for key in ("heartbeat_at", "lease_expires_at", "available_at")
        },
        "business_replay_allowed": False,
        "reproduction": reproduction,
        "diagnosis": "suspected"
        if finding["kind"]
        in {
            "progress_stalled",
            "queue_overdue",
            "lease_expired",
            "deadline_exceeded",
            "child_receipt_missing",
        }
        else "reported_failure",
    }
    safe["execution"]["state"] = _enum(execution.state, _STATES) if execution is not None else None
    return safe
