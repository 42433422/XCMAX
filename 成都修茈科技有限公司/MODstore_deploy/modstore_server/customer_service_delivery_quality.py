"""客户定制交付的生产质量门。"""

from __future__ import annotations

from typing import Any


def custom_delivery_gate(snapshot: dict[str, Any]) -> tuple[bool, str]:
    if str(snapshot.get("status") or "") != "done":
        return False, str(snapshot.get("error") or "生产尚未完成")
    artifact = snapshot.get("artifact") if isinstance(snapshot.get("artifact"), dict) else {}
    intent = str(snapshot.get("intent") or "")
    if intent == "mod":
        validation = (
            artifact.get("validation_summary")
            if isinstance(artifact.get("validation_summary"), dict)
            else {}
        )
        if not artifact.get("mod_id"):
            return False, "Mod 生产完成但缺少产物 ID"
        if validation.get("ok") is not True:
            return False, "Mod 沙箱或员工可用性门未通过"
        return True, "Mod 产物和质量门已通过"
    quality = (
        snapshot.get("quality_report") if isinstance(snapshot.get("quality_report"), dict) else {}
    )
    if not artifact.get("pack_id"):
        return False, "AI 员工生产完成但缺少员工包 ID"
    if quality.get("critical_failed") is True or quality.get("runnable") is not True:
        return False, "AI 员工可运行性或关键质量门未通过"
    return True, "AI 员工包、沙箱和关键质量门已通过"
