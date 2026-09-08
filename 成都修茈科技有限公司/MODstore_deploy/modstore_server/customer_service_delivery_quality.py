"""客户定制交付的生产质量门。"""

from __future__ import annotations

from typing import Any


def custom_delivery_gate(snapshot: dict[str, Any]) -> tuple[bool, str]:
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
            _, signed = read_verified_artifact(
                row,
                owner_id=int(row.get("owner_user_id") or 0),
                ticket_id=int(row.get("ticket_id") or 0),
            )
            probe = signed["manifest"].get("delivery_verification") or {}
            if probe.get("handler") != "verify_delivery" or probe.get("case_id") != row.get(
                "verification_case_id"
            ):
                return False, "签名产物缺少绑定业务探针"
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
        validation: dict[str, Any] = raw_validation if isinstance(raw_validation, dict) else {}
        if not artifact.get("mod_id"):
            return False, "Mod 生产完成但缺少产物 ID"
        if validation.get("ok") is not True:
            return False, "Mod 沙箱或员工可用性门未通过"
        return True, "Mod 产物和质量门已通过"
    raw_quality = snapshot.get("quality_report")
    quality: dict[str, Any] = raw_quality if isinstance(raw_quality, dict) else {}
    if not artifact.get("pack_id"):
        return False, "AI 员工生产完成但缺少员工包 ID"
    if quality.get("critical_failed") is True or quality.get("runnable") is not True:
        return False, "AI 员工可运行性或关键质量门未通过"
    return True, "AI 员工包、沙箱和关键质量门已通过"
