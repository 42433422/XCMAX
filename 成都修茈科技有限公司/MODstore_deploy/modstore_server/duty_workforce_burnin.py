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
from concurrent.futures import Future
from datetime import UTC, datetime, timezone  # noqa: F401
from pathlib import Path
from typing import Any, Dict

from modstore_server import duty_workforce_burnin_execution as _execution
from modstore_server import duty_workforce_burnin_plan as _planning
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

_recent_attempt_ids = _planning._recent_attempt_ids
_load_manifest = _planning._load_manifest
_candidate_task = _planning._candidate_task
_candidate_direct_task = _planning._candidate_direct_task
build_burn_in_plan = _planning.build_burn_in_plan

validate_burn_in_execution_result = _execution.validate_burn_in_execution_result
_mark_receipt_rejected = _execution._mark_receipt_rejected
_project_root = _execution._project_root
_execute_one = _execution._execute_one
run_burn_in = _execution.run_burn_in
