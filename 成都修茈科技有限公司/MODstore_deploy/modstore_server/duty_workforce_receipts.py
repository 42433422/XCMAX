# mypy: disable-error-code="union-attr"
"""Read identity-bound duty-workforce burn-in receipts from the audit ledger."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, Iterator


def _recent_audit_rows(
    audit_path: Path,
    cutoff: datetime,
) -> Iterator[dict[str, Any]]:
    """Yield bounded, parseable audit rows recorded since ``cutoff``."""

    if not audit_path.is_file():
        return
    try:
        lines = audit_path.read_text(encoding="utf-8").splitlines()[-5000:]
    except OSError:
        return
    for line in lines:
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            continue
        if not isinstance(row, dict):
            continue
        recorded_raw = str(row.get("recorded_at") or "").strip()
        if not recorded_raw:
            continue
        try:
            recorded_at = datetime.fromisoformat(recorded_raw.replace("Z", "+00:00"))
        except ValueError:
            continue
        if recorded_at.tzinfo is None:
            recorded_at = recorded_at.replace(tzinfo=UTC)
        if recorded_at.astimezone(UTC) >= cutoff:
            yield row


def fresh_accepted_receipt_identities(
    audit_path: Path,
    window_hours: int,
    now: datetime,
) -> dict[str, set[tuple[str, str]]]:
    """Return only strict, identity-bound burn-in proof from the audit ledger.

    A normal successful employee task is useful operational evidence, but it is
    not proof that a specific reviewed capability passed the narrow burn-in
    contract.  The accepted receipt must identify the same manifest and work
    contract that the planner is about to evaluate.
    """

    observed_at = now if now.tzinfo is not None else now.replace(tzinfo=UTC)
    cutoff = observed_at.astimezone(UTC) - timedelta(hours=max(1, window_hours))
    result: dict[str, set[tuple[str, str]]] = {}
    for row in _recent_audit_rows(audit_path, cutoff):
        if row.get("record_type") == "run_summary":
            continue
        if row.get("status") != "accepted" or row.get("receipt_accepted") is not True:
            continue
        acceptance = row.get("acceptance") if isinstance(row.get("acceptance"), dict) else {}
        if acceptance.get("passed") is not True:
            continue
        employee_id = str(row.get("employee_id") or "").strip()
        manifest_sha = str(row.get("manifest_sha256") or "").strip().lower()
        contract_sha = str(row.get("contract_sha256") or "").strip().lower()
        if not employee_id or len(manifest_sha) != 64 or len(contract_sha) != 64:
            continue
        result.setdefault(employee_id, set()).add((manifest_sha, contract_sha))
    return result


def recent_attempt_manifest_shas(
    audit_path: Path,
    cooldown_hours: int,
    now: datetime,
) -> dict[str, set[str]]:
    """Return manifest identities attempted during the cooldown window."""

    observed_at = now if now.tzinfo is not None else now.replace(tzinfo=UTC)
    cutoff = observed_at.astimezone(UTC) - timedelta(hours=max(1, cooldown_hours))
    result: dict[str, set[str]] = {}
    for row in _recent_audit_rows(audit_path, cutoff):
        if row.get("record_type") == "run_summary":
            continue
        employee_id = str(row.get("employee_id") or "").strip()
        manifest_sha = str(row.get("manifest_sha256") or "").strip().lower()
        if not employee_id or len(manifest_sha) != 64:
            continue
        result.setdefault(employee_id, set()).add(manifest_sha)
    return result
