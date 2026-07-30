"""Validation and market admission rules for Mod layer manifests."""

from __future__ import annotations

from typing import Any

from .artifact_constants import ARTIFACT_EMPLOYEE_PACK, normalize_artifact
from .mod_levels import (
    _KNOWN_KINDS,
    KIND_CUSTOM_MOD,
    KIND_EMPLOYEE_PACK,
    KIND_INDUSTRY_MOD,
    KIND_SYSTEM_MOD,
    _explicit_kind,
    _explicit_level,
    _level_for_kind,
    composite_member_ids,
    descriptor_for_manifest,
)


def validate_layer_manifest(manifest: dict[str, Any], *, strict: bool = False) -> list[str]:
    """校验分层声明；旧包默认兼容，strict 供新包/发布门禁使用。"""
    manifest = manifest if isinstance(manifest, dict) else {}
    errors: list[str] = []
    descriptor = descriptor_for_manifest(manifest)
    explicit_kind = _explicit_kind(manifest)
    explicit_level = _explicit_level(manifest)
    if strict and not explicit_kind:
        errors.append("manifest 缺少 mod_kind")
    if strict and explicit_level is None:
        errors.append("manifest 缺少 mod_level")
    if descriptor.level not in (1, 2, 3, 4):
        errors.append(f"mod_level 无效: {descriptor.level}")
    expected = _level_for_kind(descriptor.kind) if descriptor.kind in _KNOWN_KINDS else None
    if expected is not None and descriptor.level != expected:
        errors.append(f"mod_kind={descriptor.kind} 必须使用 mod_level={expected}")
    if descriptor.kind == KIND_EMPLOYEE_PACK and descriptor.employee_mode == "pluggable":
        if strict and not descriptor.parent_mod_ids:
            errors.append("可插拔员工必须声明 parent_mod_id 或 parent_mod_ids")
        scope = str(manifest.get("scope") or "").strip().lower()
        allowed_scopes = {"", "global", "tenant"}
        if not strict:
            allowed_scopes.add("host")
        if scope not in allowed_scopes:
            errors.append("可插拔员工 scope 仅支持 global 或 tenant")
    if (
        descriptor.kind in {KIND_INDUSTRY_MOD, KIND_CUSTOM_MOD}
        and strict
        and not descriptor.parent_mod_ids
    ):
        errors.append("行业/定制 Mod 必须声明 parent_mod_id 或 parent_mod_ids")
    if (
        descriptor.kind != KIND_EMPLOYEE_PACK
        and normalize_artifact(manifest) == ARTIFACT_EMPLOYEE_PACK
    ):
        errors.append("artifact=employee_pack 必须使用 mod_kind=employee_pack")
    mod_id = str(manifest.get("id") or "").strip()
    if descriptor.composite_owner:
        if descriptor.composite_owner == mod_id:
            if descriptor.kind != KIND_SYSTEM_MOD:
                errors.append("统一系统 Mod composite_owner 必须是 system_mod")
        elif mod_id not in composite_member_ids(descriptor.composite_owner):
            errors.append("Mod 不在声明的统一系统 Mod members 中")
    return errors


def market_install_block_reason(manifest: dict[str, Any]) -> str | None:
    """市场下载安装的唯一允许类型：非固定的 employee_pack。"""
    descriptor = descriptor_for_manifest(manifest)
    if (
        normalize_artifact(manifest) != ARTIFACT_EMPLOYEE_PACK
        or descriptor.kind != KIND_EMPLOYEE_PACK
    ):
        return "当前市场仅允许安装 AI 员工包；系统、行业和定制 Mod 不允许从市场安装"
    layer_errors = validate_layer_manifest(manifest, strict=True)
    if layer_errors:
        return f"市场员工包分层声明无效：{'; '.join(layer_errors)}"
    config = manifest.get("config") if isinstance(manifest.get("config"), dict) else {}
    if (
        not descriptor.market_installable
        or descriptor.employee_mode == "fixed"
        or bool(config.get("host_foundation_pack"))
    ):
        return "宿主核心/系统固定员工由产品内置，不允许从市场单独安装"
    return None


def market_catalog_row_allowed(row: dict[str, Any]) -> bool:
    """市场展示过滤：已声明 artifact 的条目只能是 employee_pack。"""
    if not isinstance(row, dict):
        return False
    raw = row.get("artifact") or row.get("kind")
    return not raw or str(raw).strip().lower() == ARTIFACT_EMPLOYEE_PACK


__all__ = [
    "market_catalog_row_allowed",
    "market_install_block_reason",
    "validate_layer_manifest",
]
