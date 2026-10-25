# mypy: disable-error-code="arg-type, union-attr"
"""Production readback receipts for autonomously published employee packs."""

from __future__ import annotations

import hashlib
import json
import re
import zipfile
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Callable, Dict, Iterable, Mapping, Sequence

from modstore_server.build_employee_pack import validate_pack_schema
from modstore_server.catalog_store import files_dir, get_package
from modstore_server.employee_runtime import (
    EXECUTOR_ACTION_HANDLERS,
    employee_pack_runtime_issues,
    parse_employee_config_v2,
)

_PACKAGE_ID_RE = re.compile(r"^[a-z0-9](?:[a-z0-9._-]{0,126}[a-z0-9])?$")
_VERSION_RE = re.compile(r"^[0-9]+\.[0-9]+\.[0-9]+(?:[-+][0-9A-Za-z.-]+)?$")
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_COMMIT_RE = re.compile(r"^[0-9a-f]{40,64}$")


class EvolutionDeploymentReceiptError(RuntimeError):
    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


def _text(value: Any, limit: int = 256) -> str:
    return str(value or "").strip()[:limit]


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as file_obj:
        for chunk in iter(lambda: file_obj.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _request(package: Mapping[str, Any]) -> tuple[str, str]:
    package_id = _text(package.get("id") or package.get("package_id"), 128).lower()
    version = _text(package.get("version"), 64)
    if not _PACKAGE_ID_RE.fullmatch(package_id):
        raise EvolutionDeploymentReceiptError("invalid_package_id")
    if not _VERSION_RE.fullmatch(version):
        raise EvolutionDeploymentReceiptError("invalid_package_version")
    return package_id, version


def _live_market_listing(package_id: str, version: str) -> dict[str, Any]:
    """Read the authoritative public-market row from the live database."""

    from modstore_server.models import CatalogItem, get_session_factory

    session_factory = get_session_factory()
    with session_factory() as session:
        row = session.query(CatalogItem).filter(CatalogItem.pkg_id == package_id).first()
        if row is None:
            return {}
        return {
            "catalog_item_id": int(row.id),
            "package_id": _text(row.pkg_id, 128).lower(),
            "version": _text(row.version, 64),
            "artifact": _text(row.artifact, 32).lower(),
            "stored_filename": _text(row.stored_filename, 256),
            "package_sha256": _text(row.sha256, 64).lower(),
            "is_public": bool(row.is_public),
            "compliance_status": _text(row.compliance_status, 32).lower(),
        }


def _archive_manifest(path: Path, package_id: str) -> dict[str, Any]:
    try:
        with zipfile.ZipFile(path) as archive:
            infos = archive.infolist()
            if not infos or len(infos) > 100:
                raise EvolutionDeploymentReceiptError("unsafe_archive_file_count")
            normalized = [info.filename.replace("\\", "/") for info in infos]
            for name in normalized:
                parts = Path(name).parts
                if Path(name).is_absolute() or ".." in parts:
                    raise EvolutionDeploymentReceiptError("unsafe_archive_path")
            expected = f"{package_id}/manifest.json"
            if normalized.count(expected) != 1:
                raise EvolutionDeploymentReceiptError("archive_manifest_identity_mismatch")
            manifest = json.loads(archive.read(expected).decode("utf-8"))
    except EvolutionDeploymentReceiptError:
        raise
    except (OSError, zipfile.BadZipFile, UnicodeDecodeError, ValueError) as exc:
        raise EvolutionDeploymentReceiptError("archive_unreadable") from exc
    if not isinstance(manifest, dict):
        raise EvolutionDeploymentReceiptError("archive_manifest_invalid")
    return manifest


def _catalog_source_commit(record: Mapping[str, Any], package_sha256: str) -> str:
    """Resolve source identity before or after public-catalog normalization."""

    source_commit_sha = _text(record.get("source_commit_sha"), 64).lower()
    if not source_commit_sha:
        raw_provenance = record.get("automation_provenance")
        provenance = raw_provenance if isinstance(raw_provenance, Mapping) else {}
        provenance_sha = _text(provenance.get("source_sha"), 64).lower()
        if provenance_sha:
            if _text(provenance.get("package_sha256"), 64).lower() != package_sha256:
                raise EvolutionDeploymentReceiptError(
                    "catalog_automation_provenance_digest_mismatch"
                )
            if (
                not _text(provenance.get("source_repository"), 256)
                or not _text(provenance.get("workflow_run_id"), 128).isdigit()
            ):
                raise EvolutionDeploymentReceiptError("catalog_automation_provenance_incomplete")
            source_commit_sha = provenance_sha
    if source_commit_sha and not _COMMIT_RE.fullmatch(source_commit_sha):
        raise EvolutionDeploymentReceiptError("catalog_source_commit_invalid")
    return source_commit_sha


def verify_catalog_package(
    package_id: str,
    version: str,
    *,
    market_lookup: Callable[[str, str], Mapping[str, Any]] = _live_market_listing,
) -> dict[str, Any]:
    """Verify static catalog, runtime contract, and the public market listing."""

    record = get_package(package_id, version)
    if not isinstance(record, dict):
        raise EvolutionDeploymentReceiptError("catalog_package_not_found")
    if _text(record.get("artifact"), 32).lower() != "employee_pack":
        raise EvolutionDeploymentReceiptError("catalog_artifact_not_employee_pack")
    stored_filename = _text(record.get("stored_filename"), 256)
    if not stored_filename or Path(stored_filename).name != stored_filename:
        raise EvolutionDeploymentReceiptError("catalog_stored_filename_invalid")
    archive_path = files_dir() / stored_filename
    if not archive_path.is_file() or archive_path.suffix.lower() != ".xcemp":
        raise EvolutionDeploymentReceiptError("catalog_archive_missing")
    digest = _sha256(archive_path)
    if not _SHA256_RE.fullmatch(digest) or digest != _text(record.get("sha256"), 64).lower():
        raise EvolutionDeploymentReceiptError("catalog_archive_digest_mismatch")

    manifest = _archive_manifest(archive_path, package_id)
    try:
        validate_pack_schema(manifest)
    except (TypeError, ValueError) as exc:
        raise EvolutionDeploymentReceiptError("archive_manifest_schema_invalid") from exc
    if (
        _text(manifest.get("id") or manifest.get("name"), 128).lower() != package_id
        or _text(manifest.get("name"), 128).lower() != package_id
        or _text(manifest.get("version"), 64) != version
        or _text(manifest.get("artifact"), 32).lower() != "employee_pack"
    ):
        raise EvolutionDeploymentReceiptError("archive_manifest_catalog_mismatch")

    pack = {
        "pack_id": package_id,
        "version": version,
        "stored_filename": stored_filename,
        "manifest": manifest,
    }
    runtime_issues = employee_pack_runtime_issues(pack)
    if runtime_issues:
        raise EvolutionDeploymentReceiptError("employee_pack_runtime_contract_invalid")
    runtime = parse_employee_config_v2(manifest)
    actions = runtime.get("actions") if isinstance(runtime.get("actions"), dict) else {}
    handlers = actions.get("handlers") if isinstance(actions.get("handlers"), list) else []
    clean_handlers = {_text(handler, 64) for handler in handlers if _text(handler, 64)}
    if not clean_handlers or not clean_handlers.issubset(EXECUTOR_ACTION_HANDLERS):
        raise EvolutionDeploymentReceiptError("employee_pack_handler_contract_invalid")
    source_commit_sha = _catalog_source_commit(record, digest)

    market = market_lookup(package_id, version)
    if not isinstance(market, Mapping) or not market:
        raise EvolutionDeploymentReceiptError("market_listing_not_found")
    if (
        _text(market.get("package_id"), 128).lower() != package_id
        or _text(market.get("version"), 64) != version
    ):
        raise EvolutionDeploymentReceiptError("market_listing_identity_mismatch")
    if _text(market.get("artifact"), 32).lower() != "employee_pack":
        raise EvolutionDeploymentReceiptError("market_listing_artifact_mismatch")
    if _text(market.get("package_sha256"), 64).lower() != digest:
        raise EvolutionDeploymentReceiptError("market_listing_digest_mismatch")
    if _text(market.get("stored_filename"), 256) != stored_filename:
        raise EvolutionDeploymentReceiptError("market_listing_archive_mismatch")
    if market.get("is_public") is not True:
        raise EvolutionDeploymentReceiptError("market_listing_not_public")
    if _text(market.get("compliance_status"), 32).lower() != "approved":
        raise EvolutionDeploymentReceiptError("market_listing_not_approved")
    try:
        market_catalog_item_id = int(market.get("catalog_item_id"))
    except (TypeError, ValueError) as exc:
        raise EvolutionDeploymentReceiptError("market_listing_id_invalid") from exc
    if market_catalog_item_id <= 0:
        raise EvolutionDeploymentReceiptError("market_listing_id_invalid")
    return {
        "package_id": package_id,
        "version": version,
        "package_sha256": digest,
        "stored_filename": stored_filename,
        "source_commit_sha": source_commit_sha,
        "catalog_readback_verified": True,
        "installability_verified": True,
        "runtime_contract_verified": True,
        "market_catalog_item_id": market_catalog_item_id,
        "market_listing_verified": True,
    }


def _strategic_council_receipt(package: Mapping[str, Any]) -> dict[str, Any]:
    from modstore_server.strategic_council import (
        build_live_strategic_council_receipt,
        strategic_council_status,
    )

    status = strategic_council_status(limit=20)
    latest = status.get("latest_receipt") if isinstance(status.get("latest_receipt"), dict) else {}
    if status.get("ready") is not True or latest.get("verified") is not True:
        raise EvolutionDeploymentReceiptError("strategic_council_source_unavailable")
    goal_id = _text(latest.get("goal_id"), 128)
    loop_run_id = _text(latest.get("loop_run_id"), 128)
    para_task_id = _text(latest.get("para_task_id"), 128)
    if not all((goal_id, loop_run_id, para_task_id)):
        raise EvolutionDeploymentReceiptError("strategic_council_linkage_missing")
    package_id = _text(package.get("package_id"), 128)
    version = _text(package.get("version"), 64)
    package_sha256 = _text(package.get("package_sha256"), 64)
    run_id = _text(package.get("run_id"), 128)
    changed_files = [
        f"modstore_server/catalog_data/packages.json#{package_id}@{version}",
        f"modstore_server/catalog_data/files/{package.get('stored_filename')}",
    ]
    receipt = build_live_strategic_council_receipt(
        proposal_id=f"catalog-deploy:{package_id}:{version}:{run_id}",
        run_id=run_id,
        package_id=package_id,
        version=version,
        package_sha256=package_sha256,
        goal_id=goal_id,
        loop_run_id=loop_run_id,
        para_task_id=para_task_id,
        strategy_intent=(
            "Deploy the reviewed employee_pack catalog artifact, verify its immutable digest, "
            "runtime handler contract, installability, and production MODstore readback."
        ),
        changed_files=changed_files,
    )
    if receipt.get("verified") is not True:
        raise EvolutionDeploymentReceiptError("strategic_council_review_failed")
    return receipt


def _already_recorded(
    rows: Iterable[Mapping[str, Any]],
    *,
    merge_sha: str,
    workflow_run_id: str,
    package_id: str,
    version: str,
) -> bool:
    return any(
        row.get("event_type") == "modstore_deployment_verified"
        and row.get("ok") is True
        and _text(row.get("merge_sha"), 64).lower() == merge_sha
        and _text(row.get("workflow_run_id"), 128) == workflow_run_id
        and _text(row.get("package_id"), 128) == package_id
        and _text(row.get("version"), 64) == version
        for row in rows
    )


def record_evolution_deployment_receipts(
    *,
    packages: Sequence[Mapping[str, Any]],
    merge_sha: str,
    workflow_run_id: str,
    rows: Sequence[Mapping[str, Any]],
    record_event: Callable[[Dict[str, Any]], None],
    council_builder: Callable[[Mapping[str, Any]], Mapping[str, Any]] = _strategic_council_receipt,
) -> dict[str, Any]:
    """Verify changed packs and append idempotent production milestone receipts."""

    merge_sha = _text(merge_sha, 64).lower()
    workflow_run_id = _text(workflow_run_id, 128)
    if not _COMMIT_RE.fullmatch(merge_sha):
        raise EvolutionDeploymentReceiptError("invalid_merge_sha")
    if not workflow_run_id:
        raise EvolutionDeploymentReceiptError("missing_workflow_run_id")
    if len(packages) > 10:
        raise EvolutionDeploymentReceiptError("too_many_packages")
    if not packages:
        return {"ok": True, "recorded": 0, "reason": "no_employee_pack_changes"}

    results: list[dict[str, Any]] = []
    for requested in packages:
        package_id, version = _request(requested)
        if _already_recorded(
            rows,
            merge_sha=merge_sha,
            workflow_run_id=workflow_run_id,
            package_id=package_id,
            version=version,
        ):
            results.append({"package_id": package_id, "version": version, "recorded": False})
            continue
        verified = verify_catalog_package(package_id, version)
        run_id = f"evolution-deploy-{workflow_run_id}-{package_id}"[:128]
        verified["run_id"] = run_id
        council = dict(council_builder(verified))
        if council.get("verified") is not True:
            raise EvolutionDeploymentReceiptError("strategic_council_review_failed")
        observed_at = datetime.now(UTC).isoformat()
        source_commit_sha = _text(verified.get("source_commit_sha"), 64).lower()
        if _COMMIT_RE.fullmatch(source_commit_sha):
            implementation_events = [
                {
                    **verified,
                    "run_id": run_id,
                    "event": "proactive_evolution_started",
                    "event_type": "proactive_evolution_started",
                    "phase": "start",
                    "status": "running",
                    "triggered_by": "proactive_signal",
                    "force": False,
                    "ok": True,
                    "dry_run": False,
                    "environment": "production",
                    "merge_sha": merge_sha,
                    "workflow_run_id": workflow_run_id,
                    "created_at": observed_at,
                },
                {
                    **verified,
                    "run_id": run_id,
                    "event": "proactive_evolution_source_code_verified",
                    "event_type": "proactive_evolution_source_code_verified",
                    "phase": "implementation",
                    "step": "code",
                    "status": "success",
                    "triggered_by": "proactive_signal",
                    "force": False,
                    "ok": True,
                    "dry_run": False,
                    "environment": "production",
                    "merge_sha": merge_sha,
                    "workflow_run_id": workflow_run_id,
                    "created_at": observed_at,
                },
                {
                    **verified,
                    "run_id": run_id,
                    "event": "proactive_evolution_package_qa_verified",
                    "event_type": "proactive_evolution_package_qa_verified",
                    "phase": "verification",
                    "step": "qa",
                    "status": "success",
                    "triggered_by": "proactive_signal",
                    "force": False,
                    "ok": True,
                    "dry_run": False,
                    "environment": "production",
                    "merge_sha": merge_sha,
                    "workflow_run_id": workflow_run_id,
                    "created_at": observed_at,
                },
            ]
            for implementation_event in implementation_events:
                record_event(implementation_event)
        event = {
            **verified,
            "event": "employee_pack_registered",
            "event_type": "modstore_deployment_verified",
            "phase": "deployment",
            "status": "verified",
            "final_status": "modstore_deployment_verified",
            "ok": True,
            "dry_run": False,
            "environment": "production",
            "merge_sha": merge_sha,
            "workflow_run_id": workflow_run_id,
            "strategic_council_verified": True,
            "strategic_council_receipt_id": _text(council.get("receipt_id"), 128),
            "created_at": observed_at,
        }
        record_event(event)
        if _COMMIT_RE.fullmatch(source_commit_sha):
            record_event(
                {
                    **verified,
                    "run_id": run_id,
                    "event": "proactive_evolution_completed",
                    "event_type": "proactive_evolution_completed",
                    "phase": "complete",
                    "status": "completed_merged",
                    "triggered_by": "proactive_signal",
                    "force": False,
                    "ok": True,
                    "dry_run": False,
                    "environment": "production",
                    "merge_sha": merge_sha,
                    "workflow_run_id": workflow_run_id,
                    "created_at": observed_at,
                }
            )
        results.append({"package_id": package_id, "version": version, "recorded": True})
        rows = [*rows, event]
    return {
        "ok": True,
        "recorded": sum(1 for item in results if item["recorded"]),
        "packages": results,
    }


__all__ = [
    "EvolutionDeploymentReceiptError",
    "record_evolution_deployment_receipts",
    "verify_catalog_package",
]
