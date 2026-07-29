"""Catalog projection helpers for Mod layer metadata."""

from __future__ import annotations

from typing import Any

from .mod_levels import descriptor_for_manifest
from .mod_levels_validation import market_catalog_row_allowed


def mod_layer_fields(row: dict[str, Any], mod_id: str) -> dict[str, Any]:
    layer = descriptor_for_manifest({**row, "id": mod_id})
    return {
        "mod_level": layer.level,
        "mod_kind": layer.kind,
        "parent_mod_id": layer.parent_mod_id,
        "parent_mod_ids": list(layer.parent_mod_ids),
        "lifecycle": layer.lifecycle,
        "market_installable": layer.market_installable,
        "employee_mode": layer.employee_mode,
    }


def validate_market_package(
    package_path: str, package_id: str
) -> tuple[str, dict[str, Any]] | None:
    """Return a rejection message/data pair for non-installable catalog packages."""
    from .artifact_constants import ARTIFACT_EMPLOYEE_PACK
    from .artifact_package import peek_artifact, peek_manifest_from_zip
    from .mod_levels_validation import market_install_block_reason

    try:
        artifact = peek_artifact(package_path)
    except (OSError, ValueError) as exc:
        return f"市场包无效：{exc}", {"id": package_id}
    if artifact != ARTIFACT_EMPLOYEE_PACK:
        return (
            "当前市场仅允许安装 AI 员工包；系统、行业和定制 Mod 不允许从市场安装",
            {"id": package_id, "artifact": artifact},
        )
    try:
        manifest = peek_manifest_from_zip(package_path)
    except (OSError, ValueError) as exc:
        return f"员工包 manifest 无效：{exc}", {"id": package_id}
    blocked = market_install_block_reason(manifest)
    return (blocked, {"id": package_id}) if blocked else None


__all__ = ["market_catalog_row_allowed", "mod_layer_fields", "validate_market_package"]
