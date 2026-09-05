# mypy: disable-error-code="arg-type, assignment"
"""Owner-authorized immutable private releases for desktop update discovery."""

from __future__ import annotations

import json
import re
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from modstore_server.catalog_publication_policy import stable_version
from modstore_server.customer_delivery_package import verify_delivery_package
from modstore_server.customer_delivery_receipts import canonical_sha256
from modstore_server.customer_service_delivery_models import (
    custom_delivery_commerce_blockers,
)
from modstore_server.customer_service_tools import json_dumps, json_loads
from modstore_server.models import get_session_factory, get_user_mod_ids
from modstore_server.models_cs import CustomerServiceTicket
from modstore_server.operational_errors import BOUNDARY_ERRORS


def authorized_runtime_ids(owner_id: int) -> set[str]:
    allowed = set(get_user_mod_ids(owner_id))
    path = Path(__file__).resolve().parents[3] / "FHD/config/customer_delivery.json"
    if path.is_file():
        for row in json.loads(path.read_text(encoding="utf-8")).get("deliveries", []):
            if row.get("legacy_mod_id") in allowed and row.get("runtime_mod_id"):
                allowed.add(str(row["runtime_mod_id"]))
    return allowed


def private_release_rows(owner_id: int, library: Path) -> dict[str, dict[str, Any]]:
    allowed = authorized_runtime_ids(owner_id)
    root = library.resolve().parent / "customer-delivery-artifacts" / str(owner_id)
    if not root.is_dir():
        return {}
    # Accepted signed deliveries are discoverable before first installation.
    # Every candidate still passes the owner/ticket/generation/commerce checks
    # below; discovery does not itself grant runtime or source-sync privileges.
    allowed.update(path.name for path in root.iterdir() if path.is_dir() and not path.is_symlink())
    rows: dict[str, dict[str, Any]] = {}
    with get_session_factory()() as db:
        for mod_id in sorted(allowed):
            folder = root / mod_id
            if not folder.resolve().is_relative_to(root) or not folder.is_dir():
                continue
            for path in folder.glob("*.xcmod"):
                try:
                    if path.is_symlink():
                        continue
                    raw = path.read_bytes()
                    signed = verify_delivery_package(raw)
                    manifest = signed["manifest"]
                    ticket_id = int(manifest.get("delivery_ticket_id") or 0)
                    if (
                        manifest.get("id") != mod_id
                        or manifest.get("delivery_owner_user_id") != owner_id
                    ):
                        continue
                    ticket = (
                        db.query(CustomerServiceTicket)
                        .filter_by(id=ticket_id, user_id=owner_id, intent="custom_delivery")
                        .first()
                    )
                    if ticket is None:
                        continue
                    evidence = json_loads(ticket.evidence_json, {})
                    runs = evidence.get("runs") or []
                    generation = str(
                        evidence.get("delivery_generation")
                        or (runs[-1].get("session_id") if runs else "")
                        or ""
                    )
                    if (
                        not generation
                        or manifest.get("delivery_generation") != generation
                        or evidence.get("acceptance_status") != "accepted"
                        or custom_delivery_commerce_blockers(evidence)
                    ):
                        continue
                    version = str(manifest.get("version") or "")
                    if mod_id in rows and stable_version(rows[mod_id]["version"]) >= stable_version(
                        version
                    ):
                        continue
                    stable_version(version)
                    rows[mod_id] = {
                        "id": mod_id,
                        "name": manifest.get("name") or mod_id,
                        "version": version,
                        "package_sha256": signed["package_sha256"],
                        "sha256": signed["package_sha256"],
                        "size": len(raw),
                        "installable": True,
                        "publication_status": "signed_release",
                        "owner_user_id": owner_id,
                        "ticket_id": ticket_id,
                        "delivery_ticket_id": ticket_id,
                        "generation": generation,
                        "_package_path": str(path),
                    }
                except BOUNDARY_ERRORS:
                    continue
    return rows


def read_catalog_release(record: dict[str, Any]) -> bytes:
    raw = Path(record["_package_path"]).read_bytes()
    signed = verify_delivery_package(raw)
    manifest = signed["manifest"]
    if signed["package_sha256"] != record["package_sha256"] or any(
        manifest.get(key) != record[value]
        for key, value in (
            ("id", "id"),
            ("version", "version"),
            ("delivery_owner_user_id", "owner_user_id"),
            ("delivery_ticket_id", "ticket_id"),
            ("delivery_generation", "generation"),
        )
    ):
        raise ValueError("正式私有产物身份或摘要发生变化")
    return raw


def _verified_ticket_artifacts(
    ticket: CustomerServiceTicket, evidence: dict[str, Any], generation: str
) -> list[dict[str, Any]]:
    """Verify the complete recorded bundle, never infer it from available ZIPs."""
    from modstore_server.customer_delivery_build import read_verified_artifact
    from modstore_server.mod_scaffold_runner import modstore_library_path

    runs = evidence.get("runs") or []
    latest = runs[-1] if runs else {}
    if latest and latest.get("session_id") != generation:
        raise ValueError("交付清单与当前生产轮次不匹配")
    records = list(latest.get("verified_artifacts") or [])
    existing = list(evidence.get("delivery_artifacts") or [])
    if not records and not existing:
        # Older accepted tickets may only have the immutable factory record in
        # the persisted workbench session. Read that exact owner/session only.
        from modstore_server import workbench_api

        snapshot = workbench_api._load_workbench_session_unlocked(generation)
        if (
            snapshot
            and snapshot.get("id") == generation
            and snapshot.get("user_id") == int(ticket.user_id)
            and snapshot.get("status") == "done"
        ):
            records = list(snapshot.get("verified_artifacts") or [])
    if not records and not existing:
        raise ValueError("当前工单缺少完整的正式交付清单，请恢复生产记录")
    expected: dict[tuple[str, str], dict[str, Any]] = {}
    for row in [*records, *existing]:
        kind, artifact_id = str(row.get("kind") or ""), str(row.get("id") or "")
        if kind not in {"module", "employee"} or not re.fullmatch(
            r"[a-z0-9][a-z0-9_-]{0,127}", artifact_id
        ):
            raise ValueError("正式交付清单含非法产物身份")
        version = str(row.get("version") or "")
        stable_version(version)
        key = kind, artifact_id
        previous = expected.get(key)
        if previous and any(
            previous.get(field) != row.get(field) for field in ("version", "package_sha256")
        ):
            raise ValueError("正式交付清单版本或摘要不一致")
        expected[key] = {**row, **(previous or {})}
    root = (
        modstore_library_path().resolve().parent
        / "customer-delivery-artifacts"
        / str(ticket.user_id)
    )
    artifacts = []
    for (kind, artifact_id), row in expected.items():
        suffix = ".xcmod" if kind == "module" else ".xcemp"
        record = {
            "ticket_id": int(ticket.id),
            "generation": generation,
            "signed_package_path": str(
                root / artifact_id / f"{artifact_id}-{row['version']}{suffix}"
            ),
            **row,
        }
        if record["generation"] != generation:
            raise ValueError("正式交付清单包含其他生产轮次")
        _, signed = read_verified_artifact(
            record, owner_id=int(ticket.user_id), ticket_id=int(ticket.id)
        )
        manifest = signed["manifest"]
        actual_kind = "employee" if manifest.get("artifact") == "employee_pack" else "module"
        if actual_kind != kind:
            raise ValueError("正式交付清单产物类型不一致")
        artifacts.append(record)
    return artifacts


def issue_release_download(record: dict[str, Any], raw: bytes) -> dict[str, str]:
    """Issue the existing ticket receipt grant for this exact immutable library ZIP."""
    signed = verify_delivery_package(raw)
    manifest = signed["manifest"]
    probe = manifest.get("delivery_verification") or {}
    case_id = str(probe.get("case_id") or "")
    if probe.get("handler") != "verify_delivery" or not case_id:
        raise ValueError("正式产物未绑定业务验证用例")
    with get_session_factory()() as db:
        ticket = (
            db.query(CustomerServiceTicket)
            .filter_by(
                id=record["ticket_id"],
                user_id=record["owner_user_id"],
                intent="custom_delivery",
            )
            .one()
        )
        evidence = json_loads(ticket.evidence_json, {})
        runs = evidence.get("runs") or []
        generation = str(
            evidence.get("delivery_generation")
            or (runs[-1].get("session_id") if runs else "")
            or ""
        )
        if (
            generation != record["generation"]
            or evidence.get("acceptance_status") != "accepted"
            or custom_delivery_commerce_blockers(evidence)
        ):
            raise ValueError("交付授权或生产轮次已变化，请重新获取发布目录")
        artifacts = _verified_ticket_artifacts(ticket, evidence, generation)
        if not any(
            row["kind"] == "module"
            and row["id"] == manifest.get("id") == record["id"]
            and row["version"] == manifest.get("version") == record["version"]
            and row["package_sha256"] == signed["package_sha256"] == record["package_sha256"]
            for row in artifacts
        ):
            raise ValueError("下载产物不在当前工单正式交付清单中")
        evidence["delivery_artifacts"] = artifacts
        evidence["delivery_generation"] = generation
        token = uuid.uuid4().hex
        grants = list(evidence.get("download_grants") or [])
        grants.append(
            {
                "token": token,
                "kind": "module",
                "id": record["id"],
                "version": record["version"],
                "package_sha256": record["package_sha256"],
                "owner_user_id": record["owner_user_id"],
                "generation": generation,
                "verification_case_id": case_id,
                "runtime_files_sha256": canonical_sha256(signed["files_sha256"]),
                "issued_at": datetime.now(UTC).isoformat(),
            }
        )
        evidence["download_grants"] = grants[-20:]
        from modstore_server.customer_delivery_entitlements import grant_verified_delivery_access

        grant_verified_delivery_access(
            db, ticket, evidence, manifest, owner_id=record["owner_user_id"]
        )
        ticket.evidence_json = json_dumps(evidence)
        db.commit()
    return {
        "X-Delivery-Ticket-ID": str(record["ticket_id"]),
        "X-Delivery-Receipt-Token": token,
        "X-Delivery-Artifact-SHA256": record["package_sha256"],
        "X-Delivery-Artifact-Version": record["version"],
        "X-Delivery-Verification-Case": case_id,
        "X-Delivery-Entitlements-Refresh": "1",
    }
