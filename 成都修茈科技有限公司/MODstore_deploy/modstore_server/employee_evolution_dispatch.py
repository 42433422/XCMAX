"""Execute approved curator suggestions against the installed employee pack."""

from __future__ import annotations

import base64
import hashlib
import io
import json
import os
import tempfile
import zipfile
from pathlib import Path
from typing import Any, cast
from uuid import NAMESPACE_URL, uuid5

from modman.archive_import import MAX_FILES, MAX_MANIFEST_BYTES
from modman.manifest_util import validate_manifest_dict
from modstore_server.customer_service_tools import json_dumps, json_loads
from modstore_server.models import (
    EmployeeEvolutionRecord,
    EmployeeExecutionMetric,
    EmployeeSuggestion,
    User,
    get_session_factory,
)
from modstore_server.operational_errors import RECOVERABLE_ERRORS
from modstore_server.retort_evolution import run_lock

_CURATOR = "employee-pack-curator"
_SIGNATURE_MEMBER = "META-INF/signature.json"
_MAX_ARTIFACT_BYTES = 32 * 1024 * 1024


class CuratorCandidateDenied(ValueError):
    """Safe, stable failure reason for an approved application's inputs."""


def _candidate_archive(
    source: Path, expected_sha: str, record: EmployeeEvolutionRecord
) -> tuple[bytes, dict]:
    with source.open("rb") as handle:
        original = handle.read(_MAX_ARTIFACT_BYTES + 1)
    if len(original) > _MAX_ARTIFACT_BYTES or hashlib.sha256(original).hexdigest() != expected_sha:
        raise CuratorCandidateDenied("employee_pack_source_integrity_failed")
    entry = f"{record.employee_id}/manifest.json"
    with zipfile.ZipFile(io.BytesIO(original)) as current:
        names = current.namelist()
        if (
            len(names) != len(set(names))
            or len(names) > MAX_FILES
            or sum(info.file_size for info in current.infolist()) > _MAX_ARTIFACT_BYTES
            or [
                name
                for name in names
                if name == "manifest.json"
                or name.count("/") == 1
                and name.endswith("/manifest.json")
            ]
            != [entry]
            or current.getinfo(entry).file_size > MAX_MANIFEST_BYTES
        ):
            raise CuratorCandidateDenied("invalid_employee_pack_archive")
        manifest = json.loads(current.read(entry))
        if not isinstance(manifest, dict) or manifest.get("id") != record.employee_id:
            raise CuratorCandidateDenied("employee_pack_identity_mismatch")
        agent = manifest.get("employee_config_v2", {}).get("cognition", {}).get("agent", {})
        before, after = str(record.prompt_before or ""), str(record.prompt_after or "")
        if not before or not after or before == after:
            raise CuratorCandidateDenied("invalid_prompt_change")
        if str(agent.get("system_prompt") or "").strip()[:30000] != before:
            raise CuratorCandidateDenied("employee_pack_baseline_changed")
        agent["system_prompt"] = after
        if validate_manifest_dict(manifest):
            raise CuratorCandidateDenied("invalid_candidate_manifest")
        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, "w") as staged:
            for member in current.infolist():
                # A previous signature covers the old manifest. Signing remains
                # part of the official release path.
                if member.filename.casefold() == _SIGNATURE_MEMBER.casefold():
                    continue
                # Copy each member without extracting paths or invoking archive code.
                staged.writestr(
                    member,
                    (
                        json_dumps(manifest).encode()
                        if member.filename == entry
                        else current.read(member)
                    ),
                )
    return buffer.getvalue(), manifest


def _audit_manifest(manifest: dict, pack: dict, actor_id: int) -> dict:
    from modstore_server.duty_workforce_contracts import load_reviewed_duty_manifest
    from modstore_server.employee_executor import _action_direct_python

    config = load_reviewed_duty_manifest(_CURATOR)["employee_config_v2"]["actions"]
    direct = config["direct_python"]
    if (
        config["handlers"] != ["direct_python"]
        or direct["action"] != "audit_manifest"
        or direct["module"] != "employee_pack_curator"
        or direct.get("read_only") is not True
    ):
        raise CuratorCandidateDenied("reviewed_curator_contract_mismatch")
    result = _action_direct_python(
        config,
        {
            "input": {
                "_trusted_duty_contract_execution": True,
                "manifest": manifest,
                "registry_record": {"id": pack["pack_id"], "version": pack["version"]},
            }
        },
        "audit approved employee evolution candidate",
        _CURATOR,
        user_id=actor_id,
    )
    output = result.get("output")
    if (
        result.get("ok") is not True
        or not isinstance(output, dict)
        or output.get("ready_for_packaging") is not True
        or output.get("read_only") is not True
        or output.get("side_effects") != []
    ):
        raise CuratorCandidateDenied("curator_audit_rejected")
    return output


def _receipt_id(suggestion_id: int) -> str:
    return str(uuid5(NAMESPACE_URL, f"xcmax:employee-evolution:{suggestion_id}"))


def completed_curator_receipt(db, suggestion: EmployeeSuggestion) -> dict[str, Any]:
    from modstore_server.infrastructure.private_asset_storage import require_private_directory
    from modstore_server.integrations.repository_packages import load_repository_module

    payload = json_loads(cast(str | None, suggestion.payload_json), {})
    receipt = payload.get("curator_execution") if isinstance(payload, dict) else None
    unverified = {"ok": False, "error": "curator_receipt_unverified"}
    if not isinstance(receipt, dict):
        return unverified
    metric_id, digest = receipt.get("metric_id"), receipt.get("candidate_sha256")
    if (
        type(metric_id) is not int
        or json_loads(cast(str | None, suggestion.created_task_ids_json), []) != [metric_id]
        or not isinstance(digest, str)
        or len(digest) != 64
        or any(c not in "0123456789abcdef" for c in digest)
        or receipt.get("signature_status") != "awaiting_release_signature"
    ):
        return unverified
    metric = db.get(EmployeeExecutionMetric, metric_id)
    if (
        metric is None
        or metric.status != "success"
        or metric.employee_id != _CURATOR
        or metric.user_id != suggestion.approved_by_user_id
        or metric.task != f"employee-evolution:{suggestion.id}"
    ):
        return unverified
    path = f"retort-evidence/{_receipt_id(cast(int, suggestion.id))}/{digest}.json"
    runtime = os.environ.get("MODSTORE_RUNTIME_DIR")
    if not runtime or receipt.get("artifact_ref") != path:
        return unverified
    try:
        private = load_repository_module("retort_engine.secure_artifacts")
        artifact = private.read_private_json(
            require_private_directory(Path(runtime) / path), allow_legacy=False
        )
        original = json.loads(base64.b64decode(artifact["files"]["receipt.json"]))
        candidate = base64.b64decode(artifact["files"]["candidate.xcemp"])
        if (
            artifact["artifact_digest"] != digest
            or original["suggestion_id"] != suggestion.id
            or original["actor_user_id"] != metric.user_id
            or hashlib.sha256(candidate).hexdigest() != digest
        ):
            return unverified
    except RECOVERABLE_ERRORS:
        return unverified
    return {
        "ok": True,
        "suggestion_id": suggestion.id,
        "status": "done",
        "metric_id": metric_id,
        "candidate_sha256": digest,
        "artifact_ref": path,
        "signature_status": "awaiting_release_signature",
    }


def execute_approved_evolution(suggestion_id: int) -> dict[str, Any]:
    """Record a private, auditable .xcemp candidate without promoting the live pack."""
    from modstore_server.catalog_store import market_archive_path, read_package_manifest_from_zip
    from modstore_server.employee_runtime import load_employee_pack_resolved
    from modstore_server.retort_github_workspace import _retain_artifact

    receipt_id = _receipt_id(suggestion_id)
    with run_lock(receipt_id), get_session_factory()() as db:
        suggestion = db.get(EmployeeSuggestion, suggestion_id, with_for_update=True)
        actor = (
            db.get(User, suggestion.approved_by_user_id)
            if suggestion and suggestion.approved_by_user_id
            else None
        )
        if (
            suggestion is None
            or suggestion.kind != "employee_evolution"
            or suggestion.source_employee_id != "evolution-engine"
            or json_loads(cast(str | None, suggestion.target_employee_ids_json), []) != [_CURATOR]
            or suggestion.approved_at is None
            or actor is None
            or not actor.is_admin
            or actor.deleted_at is not None
            or suggestion.status not in {"approved", "dispatched", "done"}
        ):
            return {"ok": False, "error": "curator_approval_required"}
        if suggestion.status == "done":
            return completed_curator_receipt(db, suggestion)
        record = (
            db.query(EmployeeEvolutionRecord)
            .filter(EmployeeEvolutionRecord.created_suggestion_id == suggestion_id)
            .one_or_none()
        )
        payload = json_loads(cast(str | None, suggestion.payload_json), {})
        if (
            record is None
            or not isinstance(payload, dict)
            or payload.get("employee_id") != record.employee_id
            or payload.get("prompt_before") != record.prompt_before
            or payload.get("prompt_after") != record.prompt_after
        ):
            return {"ok": False, "error": "evolution_record_mismatch"}
        try:
            pack = load_employee_pack_resolved(db, record.employee_id, user_id=actor.id)
            archive = market_archive_path(pack["stored_filename"], pack.get("sha256"))
            if (
                pack["pack_id"] != record.employee_id
                or archive is None
                or archive.suffix.lower() != ".xcemp"
            ):
                raise CuratorCandidateDenied("installed_pack_archive_unavailable")
            candidate, manifest = _candidate_archive(archive, pack["sha256"], record)
            audit = _audit_manifest(manifest, pack, actor.id)
            artifact_sha = hashlib.sha256(candidate).hexdigest()
            with tempfile.TemporaryDirectory(prefix="curator-evolution-") as staging:
                root = Path(staging)
                artifact = root / "candidate.xcemp"
                artifact.write_bytes(candidate)
                if read_package_manifest_from_zip(artifact) != manifest:
                    raise CuratorCandidateDenied("candidate_archive_readback_failed")
                (root / "receipt.json").write_text(
                    json_dumps(
                        {
                            "suggestion_id": suggestion_id,
                            "evolution_record_id": record.id,
                            "actor_user_id": actor.id,
                            "artifact_sha256": artifact_sha,
                            "source_sha256": pack["sha256"],
                            "signature_status": "awaiting_release_signature",
                            "audit": audit,
                        }
                    ),
                    encoding="utf-8",
                )
                reference = _retain_artifact(receipt_id, artifact_sha, root)
        except RECOVERABLE_ERRORS as exc:
            error = (
                str(exc)
                if isinstance(exc, CuratorCandidateDenied)
                else "curator_candidate_not_verified"
            )
            metric = EmployeeExecutionMetric(
                user_id=actor.id,
                employee_id=_CURATOR,
                task=f"employee-evolution:{suggestion_id}",
                status="failed",
                error=error,
            )
            db.add(metric)
            db.flush()
            suggestion.created_task_ids_json = json_dumps([metric.id])
            suggestion.status = "dispatched"
            db.commit()
            return {"ok": False, "error": error, "metric_id": metric.id}

        metric = EmployeeExecutionMetric(
            user_id=actor.id,
            employee_id=_CURATOR,
            task=f"employee-evolution:{suggestion_id}",
            status="success",
        )
        db.add(metric)
        db.flush()
        receipt = {
            "metric_id": metric.id,
            "candidate_sha256": artifact_sha,
            "artifact_ref": reference,
            "signature_status": "awaiting_release_signature",
        }
        suggestion.created_task_ids_json = json_dumps([metric.id])
        suggestion.payload_json = json_dumps({**payload, "curator_execution": receipt})
        suggestion.status = "done"
        db.commit()
        return {"ok": True, "status": "done", "suggestion_id": suggestion_id, **receipt}
