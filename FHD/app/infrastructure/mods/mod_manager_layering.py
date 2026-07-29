"""Layer-aware helpers kept outside the core ModManager module."""

from __future__ import annotations

import logging
import os
from typing import Any

from .manifest import ModMetadata, validate_dependencies
from .mod_levels import (
    composite_definition,
    composite_member_ids,
    composite_owner_for_mod_id,
    descriptor_for_metadata,
    sort_mods_for_loading,
)

logger = logging.getLogger(__name__)


def load_composite_mod(manager: Any, requested_id: str) -> bool | None:
    """Load a public composite and return ``None`` for ordinary Mod ids."""
    composite_owner = composite_owner_for_mod_id(requested_id)
    if composite_owner != requested_id:
        return None
    members = set(composite_member_ids(composite_owner))
    scanned = [m for m in sort_mods_for_loading(manager.scan_mods()) if m.id in members]
    if not scanned:
        manager._record_load_failure(
            requested_id,
            "composite",
            "统一 ERP 没有可加载的内部系统组件",
        )
        return False
    root_id = str(composite_definition(composite_owner).get("legacy_root_id") or "").strip()
    root = [item for item in scanned if item.id == root_id]
    scanned = root + [item for item in scanned if item.id != root_id]
    success = False
    for metadata in scanned:
        if manager.load_mod(metadata.id):
            success = True
    return success


def unload_composite_mod(manager: Any, requested_id: str) -> bool | None:
    """Unload composite members in reverse order, or return ``None`` for ordinary ids."""
    if composite_owner_for_mod_id(requested_id) != requested_id:
        return None
    success = True
    for member_id in reversed(composite_member_ids(requested_id)):
        if member_id in manager._loaded_mods:
            success = manager.unload_mod(member_id) and success
    return success


def metadata_layer_fields(metadata: ModMetadata) -> dict[str, Any]:
    """Project layer metadata without inflating ModManager's API adapter."""
    return {
        "mod_level": int(getattr(metadata, "mod_level", 0) or 0),
        "mod_kind": str(getattr(metadata, "mod_kind", "") or ""),
        "parent_mod_id": str(getattr(metadata, "parent_mod_id", "") or ""),
        "parent_mod_ids": list(getattr(metadata, "parent_mod_ids", ()) or ()),
        "lifecycle": str(getattr(metadata, "lifecycle", "") or ""),
        "market_installable": bool(getattr(metadata, "market_installable", False)),
        "employee_mode": str(getattr(metadata, "employee_mode", "") or ""),
        "fixed_employees": list(getattr(metadata, "fixed_employees", ()) or ()),
        "employee_slots": list(getattr(metadata, "employee_slots", ()) or ()),
        "composite_owner": str(getattr(metadata, "composite_owner", "") or ""),
        "internal_component": bool(getattr(metadata, "internal_component", False)),
        "public_mod_id": str(
            getattr(metadata, "composite_owner", "") or getattr(metadata, "id", "") or ""
        ),
        "legacy_layer": bool(getattr(metadata, "legacy_layer", False)),
    }


def manifest_layer_fields(manifest: dict[str, Any], errors: list[str]) -> dict[str, int]:
    from .mod_levels import descriptor_for_manifest
    from .mod_levels_validation import validate_layer_manifest

    errors.extend(validate_layer_manifest(manifest, strict=False))
    layer = descriptor_for_manifest(manifest)
    return {"mod_level": layer.level, "mod_kind": layer.kind}


def collapse_public_composite_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """将内部 bridge 组件投影为一个公开的统一系统 Mod。"""
    output: list[dict[str, Any]] = []
    grouped: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        owner = str(row.get("composite_owner") or "").strip()
        if owner and owner != str(row.get("id") or "").strip():
            grouped.setdefault(owner, []).append(row)
        else:
            output.append(row)

    for owner, members in grouped.items():
        definition = composite_definition(owner)
        root_id = str(definition.get("legacy_root_id") or "").strip()
        root = next((row for row in members if row.get("id") == root_id), members[0])
        component_ids = [str(row.get("id") or "").strip() for row in members]
        component_ids = [mid for mid in component_ids if mid]
        fixed_employees: list[str] = []
        workflow_employees: list[dict[str, Any]] = []
        for row in members:
            for employee_id in row.get("fixed_employees") or []:
                token = str(employee_id or "").strip()
                if token and token not in fixed_employees:
                    fixed_employees.append(token)
            for employee in row.get("workflow_employees") or []:
                if isinstance(employee, dict) and employee not in workflow_employees:
                    workflow_employees.append(employee)
        projected = dict(root)
        projected.update(
            {
                "id": owner,
                "name": str(definition.get("label") or "统一 ERP 系统 Mod"),
                "description": "宿主内置的统一系统 Mod；legacy bridge 仅作为内部实现组件。",
                "mod_level": int(definition.get("level") or 2),
                "mod_kind": str(definition.get("kind") or "system_mod"),
                "parent_mod_id": "xcagi-host-core",
                "parent_mod_ids": ["xcagi-host-core"],
                "lifecycle": str(definition.get("lifecycle") or "bundled"),
                "market_installable": False,
                "employee_mode": "fixed",
                "fixed_employees": fixed_employees,
                "workflow_employees": workflow_employees,
                "composite_owner": owner,
                "public_mod_id": owner,
                "internal_component": False,
                "composite": True,
                "component_ids": component_ids,
                "component_count": len(component_ids),
                "legacy_ids": component_ids,
            }
        )
        output.append(projected)
    return output


def is_primary_root_mod(manager: Any, metadata: ModMetadata) -> bool:
    """L3 只接受主 mods 根中的已安装实体。"""
    try:
        root = os.path.abspath(manager.mods_root)
        raw_mod_path = str(getattr(metadata, "mod_path", "") or "").strip()
        if not raw_mod_path:
            return True
        mod_path = os.path.abspath(raw_mod_path)
        return os.path.commonpath([root, mod_path]) == root
    except (OSError, ValueError):
        return False


def handle_layer_load(
    manager: Any,
    metadata: ModMetadata,
    loaded: list[str],
    handled_composites: set[str],
) -> bool:
    """Handle composite grouping and L3 source-root policy before ordinary loading."""
    layer = descriptor_for_metadata(metadata)
    if layer.composite_owner:
        owner = layer.composite_owner
        if owner in handled_composites:
            return True
        handled_composites.add(owner)
        if manager.load_mod(owner):
            loaded.append(owner)
            loaded.extend(
                mid
                for mid in composite_member_ids(owner)
                if mid in manager._loaded_mods and mid not in loaded
            )
        return True
    if layer.level == 3 and not is_primary_root_mod(manager, metadata):
        logger.info(
            "[ModManager] Skipping %s layer=%s outside active user mods root: %s",
            metadata.id,
            layer.kind,
            metadata.mod_path,
        )
        manager._record_load_failure(
            metadata.id,
            "runtime_layer_policy",
            "L3 行业/定制 Mod 只允许从当前主 mods 根加载；预制行业包需先完成 seed",
        )
        return True
    return False


def load_all_mods(manager: Any) -> list[str]:
    """Run the layer-aware load pipeline without inflating ModManager."""
    from app.utils.operational_errors import RECOVERABLE_ERRORS

    manager._recent_load_failures = []
    manager._blueprint_failures = []
    mods = sort_mods_for_loading(manager.scan_mods())
    logger.info("[ModManager] load_all_mods: scanned %s mods", len(mods))
    loaded: list[str] = []
    handled_composites: set[str] = set()

    for metadata in mods:
        if handle_layer_load(manager, metadata, loaded, handled_composites):
            continue
        try:
            from app.enterprise.mod_entitlements import is_mod_visible_for_enterprise

            if not is_mod_visible_for_enterprise(metadata.id):
                logger.info("[ModManager] Skipping mod %s (enterprise entitlement)", metadata.id)
                continue
        except RECOVERABLE_ERRORS:
            pass
        logger.info("[ModManager] Checking dependencies for mod: %s", metadata.id)
        if metadata.dependencies and not validate_dependencies(metadata, loaded):
            logger.warning(
                "[ModManager] Skipping mod %s due to unsatisfied dependencies", metadata.id
            )
            manager._record_load_failure(
                metadata.id,
                "dependencies",
                "load_all 阶段依赖未满足（可能需先加载其他 mod）",
            )
            continue
        if manager.load_mod(metadata.id):
            loaded.append(metadata.id)
            logger.info("[ModManager] Successfully loaded mod: %s", metadata.id)
        else:
            logger.warning("[ModManager] Failed to load mod: %s", metadata.id)

    logger.info("[ModManager] load_all_mods result: %s", loaded)
    return loaded


__all__ = [
    "collapse_public_composite_rows",
    "handle_layer_load",
    "is_primary_root_mod",
    "load_composite_mod",
    "load_all_mods",
    "metadata_layer_fields",
    "unload_composite_mod",
]
