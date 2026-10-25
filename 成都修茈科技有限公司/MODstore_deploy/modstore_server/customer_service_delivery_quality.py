"""客户定制交付的生产质量门。"""

from __future__ import annotations

import re
from datetime import UTC, datetime, timedelta
from typing import Any


def _versioned_probe_matches(
    row: dict[str, Any], signed: dict[str, Any], runtime_identity: dict[str, Any]
) -> bool:
    report = row.get("sandbox_probe")
    manifest = signed.get("manifest") or {}
    if not isinstance(report, dict) or not isinstance(manifest, dict):
        return False
    body = {key: value for key, value in report.items() if key != "report_sha256"}
    from modstore_server.customer_delivery_receipts import canonical_sha256

    observations = report.get("observations")
    host = runtime_identity.get("host")
    runner_sha = str(runtime_identity.get("probe_runtime_sha256") or "")
    if not isinstance(host, dict) or not re.fullmatch(r"[0-9a-f]{64}", runner_sha):
        return False
    try:
        generated = datetime.fromisoformat(
            str(report.get("generated_at") or "").replace("Z", "+00:00")
        )
        expires = datetime.fromisoformat(
            str(report.get("expires_at") or "").replace("Z", "+00:00")
        )
    except ValueError:
        return False
    now = datetime.now(UTC)
    expected = {
        "mod_id": row.get("id"),
        "version": row.get("version"),
        "owner_user_id": row.get("owner_user_id"),
        "ticket_id": row.get("ticket_id"),
        "generation": row.get("generation"),
        "package_sha256": row.get("package_sha256"),
        "case_id": row.get("verification_case_id"),
    }
    manifest_expected = {
        "mod_id": manifest.get("id"),
        "version": manifest.get("version"),
        "owner_user_id": manifest.get("delivery_owner_user_id"),
        "ticket_id": manifest.get("delivery_ticket_id"),
        "generation": manifest.get("delivery_generation"),
        "package_sha256": row.get("package_sha256"),
        "case_id": (manifest.get("delivery_verification") or {}).get("case_id"),
    }
    return bool(
        report.get("passed") is True
        and report.get("report_sha256") == canonical_sha256(body)
        and all(report.get(key) == value for key, value in expected.items())
        and expected == manifest_expected
        and report.get("host_runtime") == host
        and report.get("probe_runtime_sha256") == runner_sha
        and generated.tzinfo is not None
        and expires.tzinfo is not None
        and expires == generated + timedelta(hours=24)
        and generated <= now + timedelta(minutes=2)
        and now <= expires
        and isinstance(observations, dict)
        and observations.get("owner_schema_ready") is True
        and observations.get("rows_matched") == 1
        and observations.get("monthly_formulas_link_detail") is True
        and observations.get("customer_data_written") is False
    )


def custom_delivery_gate(
    snapshot: dict[str, Any],
    *,
    owner_id: int | None = None,
    ticket_id: int | None = None,
    generation: str = "",
) -> tuple[bool, str]:
    if str(snapshot.get("status") or "") != "done":
        return False, str(snapshot.get("error") or "生产尚未完成")
    raw_artifact = snapshot.get("artifact")
    artifact: dict[str, Any] = raw_artifact if isinstance(raw_artifact, dict) else {}
    verified = snapshot.get("verified_artifacts") or []
    if not verified:
        return False, "产物尚未完成 runtime 前端编译、业务探针与正式签包"
    from modstore_server.customer_delivery_build import read_verified_artifact
    from modstore_server.operational_errors import BOUNDARY_ERRORS

    try:
        identities = set()
        for row in verified:
            if row.get("source_mode") == "versioned_main":
                if (
                    not owner_id
                    or not ticket_id
                    or not generation
                    or int(snapshot.get("user_id") or 0) != owner_id
                    or int(snapshot.get("ticket_id") or 0) != ticket_id
                    or str(snapshot.get("id") or "") != generation
                    or row.get("owner_user_id") != owner_id
                    or row.get("ticket_id") != ticket_id
                    or row.get("generation") != generation
                    or snapshot.get("delivery_source_mode") != "versioned_main"
                ):
                    return False, "主线交付缺少当前账号、原工单或生产轮次上下文"
                from modstore_server.customer_delivery_sources import (
                    verified_snapshot_library,
                )

                verified_snapshot_library(snapshot, owner_id, generation, ticket_id)
            _, signed = read_verified_artifact(
                row,
                owner_id=int(row.get("owner_user_id") or 0),
                ticket_id=int(row.get("ticket_id") or 0),
            )
            probe = signed["manifest"].get("delivery_verification") or {}
            if probe.get("handler") != "verify_delivery" or probe.get(
                "case_id"
            ) != row.get("verification_case_id"):
                return False, "签名产物缺少绑定业务探针"
            if row.get(
                "source_mode"
            ) == "versioned_main" and not _versioned_probe_matches(
                row, signed, snapshot.get("delivery_runtime_identity") or {}
            ):
                return False, "主线太阳鸟正式签名包缺少匹配的隔离业务探针回执"
            identities.add(row["id"])
        if any(
            str(artifact[key]) not in identities
            for key in ("mod_id", "pack_id")
            if artifact.get(key)
        ):
            return False, "组合产物尚未全部完成正式签包"
    except BOUNDARY_ERRORS as exc:
        return False, f"正式签名产物校验失败：{exc}"
    intent = str(snapshot.get("intent") or "")
    if intent == "mod":
        raw_validation = artifact.get("validation_summary")
        validation: dict[str, Any] = (
            raw_validation if isinstance(raw_validation, dict) else {}
        )
        if not artifact.get("mod_id"):
            return False, "Mod 生产完成但缺少产物 ID"
        if validation.get("ok") is not True:
            return False, "Mod 沙箱或员工可用性门未通过"
        if any(
            row.get("source_mode") == "versioned_main" for row in verified
        ) and not any(
            row.get("sandbox_probe", {}).get("report_sha256")
            == validation.get("signed_probe_sha256")
            for row in verified
        ):
            return False, "主线太阳鸟质量摘要未绑定已验签的业务探针回执"
        return True, "Mod 产物和质量门已通过"
    raw_quality = snapshot.get("quality_report")
    quality: dict[str, Any] = raw_quality if isinstance(raw_quality, dict) else {}
    if not artifact.get("pack_id"):
        return False, "AI 员工生产完成但缺少员工包 ID"
    if quality.get("critical_failed") is True or quality.get("runnable") is not True:
        return False, "AI 员工可运行性或关键质量门未通过"
    return True, "AI 员工包、沙箱和关键质量门已通过"
