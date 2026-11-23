"""Application boundary for Memory v2 routes and agent workflow metadata."""

from __future__ import annotations

import json
import os
import stat
from pathlib import Path
from typing import Any

from app.application.agent_orchestrator.business_action_ledger import canonical_hash
from app.application.user_memory.retrieve import build_memory_context as build_memory_context
from app.application.user_memory.retrieve import search as search
from app.application.user_memory.write import normalize_memory_text as normalize_memory_text
from app.application.user_memory.write import remember as remember


def get_user_memory_service() -> Any:
    from app.domain.shared_services.user_memory_service import (
        get_user_memory_service as _get_service,
    )

    return _get_service()


def get_memory_v2_action_meta(action: str) -> dict[str, Any] | None:
    from app.services.tools_execution.registry import get_workflow_tool_registry

    registry = get_workflow_tool_registry()
    value = dict((registry.get("memory_v2") or {}).get("actions") or {}).get(action)
    return value if isinstance(value, dict) else None


def _memory_source():
    from app.application.user_memory.policy import MemoryPolicy, PolicyPorts
    from app.domain.shared_services import user_memory_service as memory
    from app.infrastructure.user_memory.json_storage import JsonMemoryStorage
    from app.infrastructure.user_memory.persistence import MemoryRepository

    path = memory.configured_memory_path()
    store = memory.UserMemoryStore._instance
    if store is not None:
        repository = store._repository
        if (
            not isinstance(repository, MemoryRepository)
            or repository.storage_type != "json"
            or not isinstance(repository._backend, JsonMemoryStorage)
        ):
            raise ValueError("memory verification requires the original JSON repository")
        path = repository._backend.path
    path = path.absolute()
    if path != path.resolve():
        raise ValueError("memory snapshot path changed")
    policy = MemoryPolicy(
        PolicyPorts(
            types=lambda: memory.MEMORY_V2_TYPES,
            statuses=lambda: memory.MEMORY_V2_STATUSES,
            blocked_sources=lambda: memory.MEMORY_V2_BLOCKED_SOURCES,
            trusted_sources=lambda: memory.MEMORY_V2_TRUSTED_SOURCES,
            observed_sources=lambda: memory.MEMORY_V2_OBSERVED_SOURCES,
        )
    )
    return policy, JsonMemoryStorage, path, canonical_hash(str(path))


def _memory_snapshot(backend, path):
    from app.application.shipment_excel_elt_security import (
        _open_directory_under_root,
        _windows_open_relative,
    )

    try:
        directory = _open_directory_under_root(Path(path.anchor), path.parent, create=False)
    except FileNotFoundError:
        return {}
    try:
        try:
            descriptor = (
                _windows_open_relative(
                    directory, path.name, directory=False, create=False, for_input=True
                )
                if os.name == "nt"
                else os.open(
                    path.name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=directory
                )
            )
        except FileNotFoundError:
            return {}
        with os.fdopen(descriptor, "rb") as stream:
            info = os.fstat(stream.fileno())
            if (
                not stat.S_ISREG(info.st_mode)
                or info.st_nlink != 1
                or not 0 < info.st_size <= 32 * 1024 * 1024
            ):
                raise ValueError("memory snapshot is not a bounded regular file")
            content = stream.read(32 * 1024 * 1024 + 1)
            if len(content) != info.st_size:
                raise ValueError("memory snapshot changed while reading")
            return backend.decode_snapshot(json.loads(content.decode("utf-8")))
    finally:
        os.close(directory)


def _memory_owner(context):
    from app.application.agent_task_context import scoped_personal_memory_id
    from app.domain.shared_services.auth_service import get_auth_service
    from app.infrastructure.auth.agent_mod_scope import _bound_actor

    actor = _bound_actor(context)
    # The existing owner-management permission includes reading back this write;
    # there is no separate Memory v2 read grant in the license/permission SSOT.
    if "memory_v2.write" not in get_auth_service().get_user_permissions(actor):
        raise PermissionError("memory management permission is required")
    if str(context.get("local_user_id") or actor.id) != str(actor.id):
        raise PermissionError("memory owner does not match the original actor")
    owner = scoped_personal_memory_id(context)
    if not owner:
        raise PermissionError("memory owner is unavailable")
    return owner


def _memory_record_proof(record: dict[str, Any] | None) -> dict[str, Any] | None:
    if record is None:
        return None
    return {
        "sha256": canonical_hash({key: value for key, value in record.items() if key != "history"}),
        "revision": record.get("revision"),
        "status": record.get("status"),
        "eligible": record.get("eligible_for_planner") is True,
        "history_sha256": canonical_hash(record.get("history") or []),
    }


def _proposed_memory_matches(policy, params, record) -> bool:
    confidence = params.get("confidence")
    expected = {
        **policy.govern_candidate(
            source=str(params.get("source") or "memory_v2_api"),
            confidence=0.5 if confidence in (None, "") else float(confidence),
            evidence=params.get("evidence") if isinstance(params.get("evidence"), list) else None,
        ),
        "memory_id": record["memory_id"],
        "memory_type": policy.normalize_type(
            str(params.get("memory_type") or params.get("type") or "preference")
        ),
        "key": str(params.get("key") or "").strip(),
        "value": params.get("value"),
        "created_at": record.get("created_at"),
        "updated_at": record.get("created_at"),
        "revision": 1,
        "history": [],
    }
    expected["status"] = "rejected" if expected["source_policy"] == "blocked" else "pending"
    expected["fingerprint"] = policy.fingerprint(
        expected["memory_type"], expected["key"], expected["value"]
    )
    if expected["status"] == "rejected":
        expected["rejected_at"] = expected["created_at"]
        expected["rejected_reason"] = "source_policy_blocked"
    return bool(expected["created_at"]) and canonical_hash(record) == canonical_hash(expected)


def _memory_mutation_matches(policy, step, before: dict[str, Any], record) -> bool:
    correction = step.params.get("correction")
    correction = correction if isinstance(correction, dict) else {}
    no_change = (
        step.action == "delete"
        and before.get("status") == "deleted"
        or step.action == "reject"
        and before.get("status") == "rejected"
        or step.action == "confirm"
        and before.get("status") == "active"
        and before.get("eligible") is True
        and not correction
    )
    if no_change:
        return before == _memory_record_proof(record) and (
            step.action != "reject" or record.get("eligible_for_planner") is False
        )
    history = record.get("history")
    if not isinstance(history, list) or not history or not isinstance(history[-1], dict):
        return False
    last = history[-1]
    previous = last.get("previous")
    if (
        not isinstance(previous, dict)
        or canonical_hash(previous) != before.get("sha256")
        or canonical_hash(history[:-1]) != before.get("history_sha256")
        or last.get("action")
        != {"confirm": "confirm", "correct": "correct", "reject": "rejected", "delete": "deleted"}[
            step.action
        ]
        or not record.get("updated_at")
        or last.get("at") != record["updated_at"]
    ):
        return False
    expected = {
        **previous,
        "revision": before["revision"] + 1,
        "updated_at": record["updated_at"],
        "history": history,
    }
    if step.action == "correct":
        if previous.get("status") not in {"active", "pending"}:
            return False
        if "key" in step.params:
            expected["key"] = str(step.params["key"]).strip()
        if step.params.get("value") is not None:
            expected["value"] = step.params["value"]
        expected["last_correction_reason"] = str(step.params.get("reason") or "")
        expected["correction_count"] = int(previous.get("correction_count") or 0) + 1
    elif step.action == "confirm":
        if (
            previous.get("status") in {"deleted", "rejected"}
            or previous.get("source_policy") == "blocked"
        ):
            return False
        if correction:
            if "memory_type" in correction:
                expected["memory_type"] = policy.normalize_type(str(correction["memory_type"]))
            if "key" in correction:
                expected["key"] = str(correction["key"] or "").strip()
            if "value" in correction:
                expected["value"] = correction["value"]
            if "confidence" in correction:
                expected["confidence"] = max(0.0, min(1.0, float(correction["confidence"])))
            expected["correction_count"] = int(previous.get("correction_count") or 0) + 1
        expected.update(
            status="active", eligible_for_planner=True, confirmed_at=record["updated_at"]
        )
    else:
        if previous.get("status") == "deleted":
            return False
        status = "rejected" if step.action == "reject" else "deleted"
        expected.update(status=status, eligible_for_planner=False)
        expected[f"{status}_at"] = record["updated_at"]
        reason = str(step.params.get("reason") or "")
        if reason:
            expected[f"{status}_reason"] = reason
    if step.action in {"correct", "confirm"}:
        if not str(expected.get("key") or "").strip():
            return False
        expected["fingerprint"] = policy.fingerprint(
            str(expected["memory_type"]), str(expected["key"]), expected.get("value")
        )
    return canonical_hash(record) == canonical_hash(expected)


def capture_memory_baseline(step, context) -> dict[str, Any]:
    """Freeze the server's original store and record before the existing writer runs."""
    from app.utils.operational_errors import RECOVERABLE_ERRORS

    try:
        owner = _memory_owner(context)
        policy, backend, path, source = _memory_source()
        memory = _memory_snapshot(backend, path).get(owner)
        records = memory.memory_v2_records if memory is not None and memory.user_id == owner else []
        if step.action == "propose_candidate":
            fingerprint = policy.fingerprint(
                policy.normalize_type(
                    str(step.params.get("memory_type") or step.params.get("type") or "preference")
                ),
                str(step.params.get("key") or "").strip(),
                step.params.get("value"),
            )
            matches = [
                row
                for row in records
                if row.get("fingerprint") == fingerprint
                and row.get("status") in {"pending", "active", "rejected"}
            ]
        else:
            target = str(step.params.get("memory_id") or step.params.get("id") or "").strip()
            matches = [row for row in records if row.get("memory_id") == target]
        if len(matches) > 1:
            raise ValueError("memory snapshot contains ambiguous identities")
        return {
            "store_sha256": source,
            "owner_sha256": canonical_hash(owner),
            "record": _memory_record_proof(matches[0] if matches else None),
        }
    except (PermissionError, OSError) + RECOVERABLE_ERRORS:
        return {}


def verify_memory_mutation(step, call, output, context) -> dict[str, Any]:
    """Read the original durable receipt and JSON authority without replay or projection IO."""
    from app.application.agent_orchestrator.tool_permission import (
        _fingerprint,
        _reread_claim,
        idempotency_scope_key,
    )
    from app.application.agent_orchestrator.verification_readback import _report

    source = "memory_json"
    try:
        owner = _memory_owner(context)
    except PermissionError:
        return _report("inconclusive", "result_read_permission_unavailable", source)
    caller = str(context.get("local_user_id") or context.get("actor_id") or "")
    if any(str(step.params.get(field) or caller) != caller for field in ("user_id", "userId")):
        return _report("failed", "result_memory_scope_mismatch", source)
    key = idempotency_scope_key(context, step.tool_id, step.action, step.params)
    receipt = _reread_claim(key, durable_read_only=True)
    if not receipt or receipt.get("inflight") or not isinstance(receipt.get("output"), dict):
        return _report("inconclusive", "result_memory_receipt_unavailable", source)
    if receipt.get("fingerprint") != _fingerprint(step.params, context) or canonical_hash(
        receipt["output"]
    ) != canonical_hash(output):
        return _report("failed", "result_memory_receipt_mismatch", source)
    policy, backend, path, store_sha = _memory_source()
    baseline = (call.metadata.get("verification_contract") or {}).get("memory_baseline")
    if not isinstance(baseline, dict) or not baseline.get("store_sha256"):
        return _report("inconclusive", "result_memory_baseline_unavailable", source)
    if baseline["store_sha256"] != store_sha or baseline.get("owner_sha256") != canonical_hash(
        owner
    ):
        return _report("failed", "result_memory_source_mismatch", source)
    returned = output.get("candidate" if step.action == "propose_candidate" else "memory")
    if not isinstance(returned, dict) or not returned.get("memory_id"):
        return _report("failed", "result_memory_identity_mismatch", source)
    memory = _memory_snapshot(backend, path).get(owner)
    if memory is None or memory.user_id != owner:
        return _report("inconclusive", "result_memory_owner_unavailable", source)
    matches = [
        row for row in memory.memory_v2_records if row.get("memory_id") == returned["memory_id"]
    ]
    if len(matches) != 1 or canonical_hash(matches[0]) != canonical_hash(returned):
        return _report("failed", "result_memory_state_mismatch", source)
    record = matches[0]
    before = baseline.get("record")
    revision = record.get("revision")
    if type(revision) is not int or revision <= 0:
        return _report("failed", "result_memory_revision_mismatch", source)
    if step.action == "propose_candidate":
        valid = record.get("fingerprint") == policy.fingerprint(
            policy.normalize_type(
                str(step.params.get("memory_type") or step.params.get("type") or "preference")
            ),
            str(step.params.get("key") or "").strip(),
            step.params.get("value"),
        )
        valid = valid and (
            (output.get("created") is False and before == _memory_record_proof(record))
            if before is not None
            else (
                output.get("created") is True
                and _proposed_memory_matches(policy, step.params, record)
            )
        )
    else:
        if not isinstance(before, dict) or type(before.get("revision")) is not int:
            return _report("failed", "result_memory_revision_mismatch", source)
        valid = record["memory_id"] == str(
            step.params.get("memory_id") or step.params.get("id") or ""
        ).strip() and _memory_mutation_matches(policy, step, before, record)
    owned_preferences = {
        key: item
        for key, item in memory.preferences.items()
        if isinstance(item, dict) and item.get("memory_id") == record["memory_id"]
    }
    if record.get("status") == "active" and record.get("memory_type") == "preference":
        preference = owned_preferences.get(record.get("key")) or {}
        valid = (
            valid
            and set(owned_preferences) == {record.get("key")}
            and (canonical_hash(preference.get("value")) == canonical_hash(record.get("value")))
        )
    else:
        valid = valid and not owned_preferences
    if not valid:
        return _report("failed", "result_memory_effect_mismatch", source)
    return _report(
        "verified",
        "result_verified",
        source,
        scope="memory_current_state",
        memory_id=record["memory_id"],
        revision=revision,
        record_sha256=canonical_hash(record),
        store_sha256=store_sha,
        owner_sha256=canonical_hash(owner),
        receipt_key_sha256=canonical_hash(key),
        params_sha256=canonical_hash(step.params),
    )
