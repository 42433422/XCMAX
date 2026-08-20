# mypy: disable-error-code="union-attr"
"""Read and normalize strict duty-workforce burn-in evidence."""

from __future__ import annotations

import hashlib
import json
import os
import re
from collections import deque
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Dict, Iterable, Optional

from modstore_server.self_evolution_knowledge import kb_root

_HASH_RE = re.compile(r"^[0-9a-f]{64}$")
EMPLOYEE_ID_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{0,100}$")
_RUN_ID_RE = re.compile(r"^[a-zA-Z0-9_-]{1,64}$")
_FAILURE_STATUSES = frozenset({"failed", "rejected", "timeout"})
ALLOWED_REASON_CODES = frozenset(
    {
        "change_request_bridge_not_suppressed",
        "change_request_created",
        "direct_python_evidence_missing",
        "direct_python_not_read_only",
        "direct_python_output_not_ok",
        "direct_python_side_effects_present",
        "direct_python_status_not_success",
        "direct_python_summary_missing",
        "execution_not_object",
        "executor_handler_failed",
        "invalid_handler_output",
        "no_capability_output",
        "no_successful_read_only_observation",
        "no_successful_tool_call",
        "non_read_only_tool_attempted",
        "programmatic_verification_failed",
        "tool_call_failure",
    }
)


def iso_now() -> str:
    return datetime.now(UTC).isoformat()


def audit_path() -> Path:
    from modstore_server.duty_workforce_burnin import burn_in_audit_path

    return burn_in_audit_path()


def workforce_gap_path() -> Path:
    raw = str(os.environ.get("MODSTORE_DUTY_WORKFORCE_GAP_PATH") or "").strip()
    return (
        Path(raw).expanduser() if raw else kb_root() / "gaps" / "duty_workforce_burnin_gaps.jsonl"
    )


def canonical_sha256(payload: Any) -> str:
    raw = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _valid_hash(value: Any) -> str:
    text = str(value or "").strip().lower()
    return text if _HASH_RE.fullmatch(text) else ""


def _reason_codes(row: Dict[str, Any]) -> list[str]:
    acceptance = row.get("acceptance") if isinstance(row.get("acceptance"), dict) else {}
    values = acceptance.get("reasons") if isinstance(acceptance.get("reasons"), list) else []
    reasons = []
    for item in values:
        code = str(item).strip()
        if code in ALLOWED_REASON_CODES or code in {
            "handler_failed:agent",
            "handler_failed:direct_python",
        }:
            reasons.append(code)
    if reasons:
        return list(dict.fromkeys(reasons))[:20]
    status = str(row.get("status") or "").strip().lower()
    return [f"burnin_{status}"] if status in _FAILURE_STATUSES else []


def _safe_recorded_at(value: Any) -> str:
    raw = str(value or "").strip()
    if not raw:
        return ""
    try:
        parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return ""
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC).isoformat()


def _normalized_row(row: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    if not isinstance(row, dict) or row.get("record_type") == "run_summary":
        return None
    employee_id = str(row.get("employee_id") or "").strip()
    run_id = str(row.get("run_id") or "").strip()
    status = str(row.get("status") or "").strip().lower()
    manifest_sha = _valid_hash(row.get("manifest_sha256"))
    contract_sha = _valid_hash(row.get("contract_sha256"))
    if (
        not EMPLOYEE_ID_RE.fullmatch(employee_id)
        or not _RUN_ID_RE.fullmatch(run_id)
        or not manifest_sha
        or not contract_sha
    ):
        return None
    accepted = row.get("receipt_accepted") is True and status == "accepted"
    failed = row.get("receipt_accepted") is False and status in _FAILURE_STATUSES
    if not accepted and not failed:
        return None
    return {
        "accepted": accepted,
        "contract_sha256": contract_sha,
        "employee_id": employee_id,
        "evidence_ref": f"duty-burnin:{run_id}:{employee_id}",
        "manifest_sha256": manifest_sha,
        "reasons": _reason_codes(row),
        "recorded_at": _safe_recorded_at(row.get("recorded_at")),
        "run_id": run_id,
        "status": status,
    }


def load_audit_rows(path: Path, *, max_rows: int = 20000) -> list[Dict[str, Any]]:
    if not path.exists():
        return []
    rows: deque[Dict[str, Any]] = deque(maxlen=max(1, max_rows))
    try:
        with path.open("r", encoding="utf-8") as handle:
            for line in handle:
                try:
                    payload = json.loads(line)
                except json.JSONDecodeError:
                    continue
                row = _normalized_row(payload) if isinstance(payload, dict) else None
                if row is not None:
                    rows.append(row)
    except OSError:
        return []
    return list(rows)


def resolved_pairs(
    rows: Iterable[Dict[str, Any]],
) -> tuple[list[Dict[str, Any]], Dict[str, list[Dict[str, Any]]]]:
    pending: Dict[str, list[Dict[str, Any]]] = {}
    pairs: list[Dict[str, Any]] = []
    for row in rows:
        employee_id = str(row["employee_id"])
        if not row.get("accepted"):
            pending.setdefault(employee_id, []).append(row)
            continue
        failures = pending.pop(employee_id, [])
        if failures:
            pairs.append({"accepted": row, "failures": failures[-10:]})
    return pairs, pending
