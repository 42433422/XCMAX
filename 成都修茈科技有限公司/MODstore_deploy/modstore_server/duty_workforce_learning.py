# mypy: disable-error-code="assignment, attr-defined, no-any-return, valid-type"
"""Turn strict duty-workforce burn-in evidence into reusable knowledge.

One failed attempt is only a capability-gap candidate.  A reusable pattern is
written only after the same employee later produces a strict accepted receipt.
The learner reads an append-only audit ledger and persists only allow-listed,
non-secret fields (employee IDs, run IDs, hashes, statuses and reason codes).
"""

from __future__ import annotations

import json
import os
import threading
from pathlib import Path
from typing import Any, Dict, Iterable, Optional

from modstore_server.duty_workforce_evidence import ALLOWED_REASON_CODES as _ALLOWED_REASON_CODES
from modstore_server.duty_workforce_evidence import EMPLOYEE_ID_RE as _EMPLOYEE_ID_RE
from modstore_server.duty_workforce_evidence import audit_path as _audit_path
from modstore_server.duty_workforce_evidence import canonical_sha256 as _canonical_sha256
from modstore_server.duty_workforce_evidence import iso_now as _iso_now
from modstore_server.duty_workforce_evidence import load_audit_rows as _load_audit_rows
from modstore_server.duty_workforce_evidence import resolved_pairs as _resolved_pairs
from modstore_server.duty_workforce_evidence import (
    workforce_gap_path,
)
from modstore_server.llm_crypto import decrypt_secret, encrypt_secret
from modstore_server.self_evolution_knowledge import (
    kb_root,
    record_code_pattern,
)

_RUN_LOCK = threading.Lock()
_ENCRYPTED_GAP_SCHEMA = "xcagi.duty_workforce.capability_gap.encrypted/v1"


def _decode_gap_event(payload: Any) -> tuple[Optional[Dict[str, Any]], bool]:
    if not isinstance(payload, dict):
        return None, False
    if payload.get("schema") != _ENCRYPTED_GAP_SCHEMA:
        return payload, True
    ciphertext = str(payload.get("ciphertext") or "").strip()
    if not ciphertext:
        return None, False
    try:
        decoded = json.loads(decrypt_secret(ciphertext))
    except (RuntimeError, ValueError, json.JSONDecodeError):
        return None, False
    return (decoded, False) if isinstance(decoded, dict) else (None, False)


def _load_gap_events(path: Path) -> tuple[list[Dict[str, Any]], bool]:
    if not path.exists():
        return [], False
    events: list[Dict[str, Any]] = []
    legacy_found = False
    try:
        with path.open("r", encoding="utf-8") as fh:
            for line in fh:
                try:
                    raw = json.loads(line)
                except json.JSONDecodeError:
                    continue
                event, legacy = _decode_gap_event(raw)
                if event is not None:
                    events.append(event)
                    legacy_found = legacy_found or legacy
    except OSError:
        return [], False
    return events, legacy_found


def _encrypted_gap_line(payload: Dict[str, Any]) -> str:
    plaintext = json.dumps(
        payload,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    )
    envelope = {
        "schema": _ENCRYPTED_GAP_SCHEMA,
        "ciphertext": encrypt_secret(plaintext),
    }
    return json.dumps(envelope, ensure_ascii=True, sort_keys=True) + "\n"


def _append_gap_event(path: Path, payload: Dict[str, Any]) -> None:
    encrypted_line = _encrypted_gap_line(payload)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(path, os.O_WRONLY | os.O_APPEND | os.O_CREAT, 0o600)
    with os.fdopen(fd, "a", encoding="utf-8") as fh:
        fh.write(encrypted_line)
    path.chmod(0o600)


def _migrate_legacy_gap_ledger(path: Path) -> None:
    events, legacy_found = _load_gap_events(path)
    if not legacy_found:
        return
    encrypted_lines = [_encrypted_gap_line(event) for event in events]
    tmp = path.with_suffix(path.suffix + ".encrypted.tmp")
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as fh:
        fh.writelines(encrypted_lines)
    tmp.replace(path)
    path.chmod(0o600)


def _existing_learning_keys() -> set[str]:
    directory = kb_root() / "patterns"
    if not directory.exists():
        return set()
    keys: set[str] = set()
    for path in directory.glob("*.json"):
        try:
            with path.open("r", encoding="utf-8") as fh:
                payload = json.load(fh)
        except (OSError, json.JSONDecodeError):
            continue
        metadata = payload.get("metadata") if isinstance(payload, dict) else None
        key = str((metadata or {}).get("workforce_learning_key") or "").strip()
        if key:
            keys.add(key)
    return keys


def _existing_gap_keys(path: Path) -> set[str]:
    keys: set[str] = set()
    events, _legacy_found = _load_gap_events(path)
    for payload in events:
        key = str(payload.get("gap_key") or "")
        if key:
            keys.add(key)
    return keys


def _gap_evidence(row: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "contract_sha256": row["contract_sha256"],
        "employee_id": row["employee_id"],
        "evidence_ref": row["evidence_ref"],
        "manifest_sha256": row["manifest_sha256"],
        "reasons": row["reasons"],
        "status": row["status"],
    }


def _gap_key(row: Dict[str, Any]) -> str:
    return _canonical_sha256(_gap_evidence(row))


def _append_gap_candidates(
    unresolved: Dict[str, list[Dict[str, Any]]], path: Path
) -> tuple[int, int]:
    existing = _existing_gap_keys(path)
    written = 0
    skipped = 0
    for employee_id in sorted(unresolved):
        row = unresolved[employee_id][-1]
        evidence = _gap_evidence(row)
        gap_key = _gap_key(row)
        if gap_key in existing:
            skipped += 1
            continue
        payload = {
            "schema": "xcagi.duty_workforce.capability_gap/v1",
            "record_type": "candidate",
            "observed_at": _iso_now(),
            "source_recorded_at": row["recorded_at"],
            "gap_key": gap_key,
            **evidence,
        }
        _append_gap_event(path, payload)
        existing.add(gap_key)
        written += 1
    return written, skipped


def _remediation_plan(gap_key: str, employee_id: str) -> Dict[str, Any]:
    """Build one deterministic, path-safe implementation plan for an existing employee."""

    module_name = employee_id.replace("-", "_")
    employee_root = f"FHD/mods/_employees/{employee_id}"
    return {
        "schema": "xcagi.duty_workforce.remediation_plan/v1",
        "task_id": f"workforce-gap-{gap_key[:16]}",
        "kind": "repair_existing_employee_capability",
        "employee_id": employee_id,
        "target_files": [
            f"{employee_root}/manifest.json",
            f"{employee_root}/backend/employees/{module_name}.py",
        ],
        "focused_tests": [
            "成都修茈科技有限公司/MODstore_deploy/tests/test_employee_direct_contracts.py",
            "成都修茈科技有限公司/MODstore_deploy/tests/test_duty_workforce_learning.py",
        ],
        "acceptance_requirements": [
            "deterministic_direct_fixture_approved",
            "read_only_true",
            "side_effects_empty",
            "later_strict_burnin_receipt_accepted",
        ],
        "requires_runtime_provenance": True,
        "auto_close": False,
        "closure_event": "later_strict_burnin_receipt_accepted",
    }


def _gap_ledger_state(
    path: Path,
) -> tuple[Dict[str, Dict[str, Any]], set[str], set[str]]:
    candidates: Dict[str, Dict[str, Any]] = {}
    resolved: set[str] = set()
    planned: set[str] = set()
    events, _legacy_found = _load_gap_events(path)
    for payload in events:
        gap_key = str(payload.get("gap_key") or "").strip()
        if not gap_key:
            continue
        record_type = str(payload.get("record_type") or "candidate").strip()
        if record_type == "resolved":
            resolved.add(gap_key)
        elif record_type == "remediation_plan":
            planned.add(gap_key)
        elif record_type == "candidate":
            candidates[gap_key] = payload
    return candidates, resolved, planned


def load_open_workforce_gaps(
    *, path: Optional[Path] = None, limit: int = 100
) -> list[Dict[str, Any]]:
    """Return current unresolved, redacted capability gaps from the event ledger."""

    source = Path(path) if path is not None else workforce_gap_path()
    candidates, resolved, planned = _gap_ledger_state(source)
    rows: list[Dict[str, Any]] = []
    for gap_key, payload in candidates.items():
        if gap_key in resolved:
            continue
        employee_id = str(payload.get("employee_id") or "").strip()
        if not _EMPLOYEE_ID_RE.fullmatch(employee_id):
            continue
        reasons = [
            str(item)
            for item in payload.get("reasons") or []
            if str(item) in _ALLOWED_REASON_CODES
            or str(item) in {"handler_failed:agent", "handler_failed:direct_python"}
        ]
        row = {
            "gap_key": gap_key,
            "employee_id": employee_id,
            "evidence_ref": str(payload.get("evidence_ref") or ""),
            "reasons": reasons,
            "status": str(payload.get("status") or "rejected"),
            "observed_at": str(payload.get("observed_at") or ""),
            "source_recorded_at": str(payload.get("source_recorded_at") or ""),
        }
        if gap_key in planned:
            row["remediation"] = _remediation_plan(gap_key, employee_id)
        rows.append(row)
    rows.sort(key=lambda item: (item["observed_at"], item["employee_id"]))
    return rows[-max(1, min(int(limit), 500)) :]


def _append_gap_resolutions(pairs: Iterable[Dict[str, Any]], path: Path) -> tuple[int, int]:
    candidates, resolved, _planned = _gap_ledger_state(path)
    written = 0
    skipped = 0
    for pair in pairs:
        accepted = pair["accepted"]
        for failure in pair["failures"]:
            gap_key = _gap_key(failure)
            if gap_key not in candidates or gap_key in resolved:
                skipped += 1
                continue
            payload = {
                "schema": "xcagi.duty_workforce.capability_gap_resolution/v1",
                "record_type": "resolved",
                "resolved_at": _iso_now(),
                "gap_key": gap_key,
                "employee_id": accepted["employee_id"],
                "accepted_evidence_ref": accepted["evidence_ref"],
                "accepted_run_id": accepted["run_id"],
                "resolution": "later_strict_burnin_receipt_accepted",
            }
            _append_gap_event(path, payload)
            resolved.add(gap_key)
            written += 1
    return written, skipped


def _append_gap_remediation_plans(path: Path) -> tuple[int, int]:
    candidates, resolved, planned = _gap_ledger_state(path)
    written = 0
    skipped = 0
    for gap_key, candidate in sorted(candidates.items()):
        if gap_key in resolved or gap_key in planned:
            skipped += 1
            continue
        employee_id = str(candidate.get("employee_id") or "").strip()
        if not _EMPLOYEE_ID_RE.fullmatch(employee_id):
            skipped += 1
            continue
        plan = _remediation_plan(gap_key, employee_id)
        payload = {
            "schema": "xcagi.duty_workforce.remediation_plan_event/v1",
            "record_type": "remediation_plan",
            "planned_at": _iso_now(),
            "gap_key": gap_key,
            "employee_id": employee_id,
            "plan_sha256": _canonical_sha256(plan),
        }
        _append_gap_event(path, payload)
        planned.add(gap_key)
        written += 1
    return written, skipped


def _record_pair(pair: Dict[str, Any], *, existing: set[str]) -> Optional[Dict[str, Any]]:
    accepted = pair["accepted"]
    failures = list(pair["failures"])
    evidence = {
        "accepted": {
            key: accepted[key]
            for key in (
                "contract_sha256",
                "employee_id",
                "evidence_ref",
                "manifest_sha256",
                "recorded_at",
                "run_id",
            )
        },
        "failures": [
            {
                key: row[key]
                for key in (
                    "contract_sha256",
                    "evidence_ref",
                    "manifest_sha256",
                    "reasons",
                    "recorded_at",
                    "run_id",
                    "status",
                )
            }
            for row in failures
        ],
    }
    learning_key = _canonical_sha256(evidence)
    if learning_key in existing:
        return None

    latest_failure = failures[-1]
    unchanged_contract = all(
        row["manifest_sha256"] == accepted["manifest_sha256"]
        and row["contract_sha256"] == accepted["contract_sha256"]
        for row in failures
    )
    if unchanged_contract:
        pattern = "workforce_burnin_cooldown_retry_verified"
        summary = (
            "An unchanged reviewed employee contract failed strict burn-in and later passed; "
            "retain the failure evidence and retry only after the safety cooldown before editing capability code."
        )
    else:
        pattern = "workforce_burnin_contract_revision_verified"
        summary = (
            "A revised reviewed employee manifest or contract later passed the same strict burn-in; "
            "reuse the earlier acceptance reasons as regression checks for equivalent revisions."
        )
    recorded = record_code_pattern(
        pattern=pattern,
        before=json.dumps(evidence["failures"], ensure_ascii=False, sort_keys=True),
        after=json.dumps(evidence["accepted"], ensure_ascii=False, sort_keys=True),
        summary=summary,
        metadata={
            "accepted_evidence_ref": accepted["evidence_ref"],
            "accepted_run_id": accepted["run_id"],
            "employee_id": accepted["employee_id"],
            "failure_evidence_refs": [row["evidence_ref"] for row in failures],
            "failure_reason_codes": sorted(
                {reason for row in failures for reason in row["reasons"]}
            ),
            "latest_failure_run_id": latest_failure["run_id"],
            "source": "duty_workforce_burnin.audit/v1",
            "verified_by_later_accepted_receipt": True,
            "workforce_learning_key": learning_key,
        },
    )
    existing.add(learning_key)
    return recorded


def run_duty_workforce_learning(
    *, audit_path: Optional[Path] = None, gap_path: Optional[Path] = None
) -> Dict[str, Any]:
    """Learn from resolved burn-in attempts and persist unresolved gaps."""

    if not _RUN_LOCK.acquire(blocking=False):
        return {
            "ok": True,
            "skipped": True,
            "reason": "already_running",
            "schema": "xcagi.duty_workforce.learning/v1",
        }
    try:
        source = Path(audit_path) if audit_path is not None else _audit_path()
        gaps = Path(gap_path) if gap_path is not None else workforce_gap_path()
        rows = _load_audit_rows(source)
        if not source.exists():
            return {
                "ok": True,
                "skipped": True,
                "reason": "audit_missing",
                "schema": "xcagi.duty_workforce.learning/v1",
                "audit_path": str(source),
            }
        _migrate_legacy_gap_ledger(gaps)
        pairs, unresolved = _resolved_pairs(rows)
        gap_written, gap_skipped = _append_gap_candidates(unresolved, gaps)
        resolution_written, resolution_skipped = _append_gap_resolutions(pairs, gaps)
        plan_written, plan_skipped = _append_gap_remediation_plans(gaps)
        existing = _existing_learning_keys()
        knowledge_paths: list[str] = []
        skipped_existing = 0
        pattern_counts: Dict[str, int] = {}
        for pair in pairs:
            recorded = _record_pair(pair, existing=existing)
            if recorded is None:
                skipped_existing += 1
                continue
            knowledge_paths.append(str(recorded.get("_path") or ""))
            pattern = str(recorded.get("pattern") or "")
            pattern_counts[pattern] = pattern_counts.get(pattern, 0) + 1
        return {
            "ok": True,
            "schema": "xcagi.duty_workforce.learning/v1",
            "audit_path": str(source),
            "audit_row_count": len(rows),
            "gap_path": str(gaps),
            "unresolved_employee_count": len(unresolved),
            "gap_candidate_written_count": gap_written,
            "gap_candidate_skipped_count": gap_skipped,
            "gap_resolution_written_count": resolution_written,
            "gap_resolution_skipped_count": resolution_skipped,
            "remediation_plan_written_count": plan_written,
            "remediation_plan_skipped_count": plan_skipped,
            "open_gap_count": len(load_open_workforce_gaps(path=gaps)),
            "resolved_pair_count": len(pairs),
            "knowledge_written_count": len(knowledge_paths),
            "knowledge_skipped_existing_count": skipped_existing,
            "knowledge_paths": knowledge_paths,
            "pattern_counts": dict(sorted(pattern_counts.items())),
        }
    finally:
        _RUN_LOCK.release()


__all__ = [
    "load_open_workforce_gaps",
    "run_duty_workforce_learning",
    "workforce_gap_path",
]
