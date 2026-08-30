"""Post-execution verifier for bounded storage-retention autonomy actions."""

from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime
from pathlib import Path
from typing import Any

from modstore_server.autonomy_posthoc_helpers import utc

_STORAGE_ACTION = re.compile(r"^storage-pressure:([0-9a-f]{32})$", re.IGNORECASE)
_TERMINAL_STATUSES = frozenset(
    {"recovered", "no_safe_candidates", "pressure_persists", "repair_failed"}
)


def load_storage_pressure_records(
    path: str | Path | None = None,
) -> list[dict[str, Any]]:
    """Load the bounded current and rotated storage self-heal ledgers."""

    if path is None:
        from modstore_server.storage_pressure_self_heal import audit_path

        resolved = audit_path()
    else:
        resolved = Path(path).expanduser()
    sources = (resolved.with_suffix(resolved.suffix + ".1"), resolved)
    records: list[dict[str, Any]] = []
    for source in sources:
        if not source.is_file():
            continue
        try:
            with source.open(encoding="utf-8", errors="replace") as handle:
                for line in handle:
                    try:
                        item = json.loads(line)
                    except (TypeError, ValueError, json.JSONDecodeError):
                        continue
                    if isinstance(item, dict):
                        records.append(item)
        except OSError:
            continue
    return records


def _recorded_timestamp(record: dict[str, Any], key: str) -> datetime | None:
    raw = str(record.get(key) or "").strip()
    if not raw:
        return None
    try:
        return utc(datetime.fromisoformat(raw.replace("Z", "+00:00")))
    except ValueError:
        return None


def verify_storage_pressure_action(
    *,
    action_id: str,
    allowed_at: datetime,
    records: list[dict[str, Any]],
) -> dict[str, Any]:
    """Verify a bounded-retention allow from its later immutable run receipt."""

    match = _STORAGE_ACTION.fullmatch(str(action_id or ""))
    if match is None:
        return {"ok": False, "reason": "unsupported_storage_action_id"}
    run_id = match.group(1).lower()
    record = next(
        (
            item
            for item in reversed(records)
            if str(item.get("run_id") or "").strip().lower() == run_id
        ),
        None,
    )
    if record is None:
        return {"ok": False, "reason": "storage_run_receipt_missing"}

    started_at = _recorded_timestamp(record, "started_at")
    finished_at = _recorded_timestamp(record, "finished_at")
    allowed = utc(allowed_at)
    if started_at is None or finished_at is None or not (started_at <= allowed <= finished_at):
        return {"ok": False, "reason": "storage_run_timeline_mismatch"}
    if (
        record.get("schema_version") != "storage_pressure_self_heal.v1"
        or record.get("policy") != "storage_pressure_low_risk_retention_v1"
        or record.get("action_taken") is not True
        or record.get("decision_audit_written") is not True
        or record.get("audit_written") is not True
    ):
        return {"ok": False, "reason": "storage_run_contract_incomplete"}

    before = record.get("before") if isinstance(record.get("before"), dict) else {}
    after = record.get("after") if isinstance(record.get("after"), dict) else {}
    status = str(record.get("status") or "").strip()
    if not before or not after or before.get("path") != after.get("path"):
        return {"ok": False, "reason": "storage_observation_receipt_incoherent"}
    if status not in _TERMINAL_STATUSES:
        return {"ok": False, "reason": "storage_terminal_status_unsupported"}

    if status == "repair_failed":
        if not str(record.get("error") or "").strip():
            return {"ok": False, "reason": "storage_failure_receipt_incomplete"}
    else:
        retention = record.get("retention") if isinstance(record.get("retention"), dict) else {}
        postcondition = (
            record.get("postcondition") if isinstance(record.get("postcondition"), dict) else {}
        )
        if (
            not retention
            or postcondition.get("logical_retention_verified") is not True
            or postcondition.get("business_notification_scope_unchanged_by_contract") is not True
        ):
            return {"ok": False, "reason": "storage_bounded_scope_receipt_incomplete"}

    digest = hashlib.sha256(
        json.dumps(record, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode(
            "utf-8"
        )
    ).hexdigest()
    return {
        "ok": True,
        "verdict": "no_prohibited_miss",
        "evidence_ref": f"storage-self-heal-run:{run_id}:sha256:{digest[:40]}",
        "reason": f"bounded_storage_run_{status}_receipt_verified",
    }


__all__ = ["load_storage_pressure_records", "verify_storage_pressure_action"]
