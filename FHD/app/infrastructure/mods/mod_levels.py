"""Mod 分层 SSOT。

产品层级固定为：

    L1 宿主核心 -> L2 系统 Mod -> L3 行业/定制 Mod -> L4 可插拔员工

``mod_levels.json`` 只保存策略和旧包兼容分类；新包应在 manifest 中显式声明
``mod_level`` / ``mod_kind``。旧 manifest 仍可通过兼容表被识别，但不会因此获得
市场安装资格。
"""

from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import Any, Iterable

from .artifact_constants import ARTIFACT_EMPLOYEE_PACK, normalize_artifact

logger = logging.getLogger(__name__)

HOST_CORE_ID = "xcagi-host-core"
UNIFIED_ERP_ID = "xcagi-erp"

HOST_CORE_LEVEL = 1
SYSTEM_MOD_LEVEL = 2
DOMAIN_MOD_LEVEL = 3
EMPLOYEE_PACK_LEVEL = 4

KIND_HOST_CORE = "host_core"
KIND_SYSTEM_MOD = "system_mod"
KIND_INDUSTRY_MOD = "industry_mod"
KIND_CUSTOM_MOD = "custom_mod"
KIND_EMPLOYEE_PACK = "employee_pack"

_KNOWN_KINDS = frozenset(
    {
        KIND_HOST_CORE,
        KIND_SYSTEM_MOD,
        KIND_INDUSTRY_MOD,
        KIND_CUSTOM_MOD,
        KIND_EMPLOYEE_PACK,
    }
)


@dataclass(frozen=True)
class ModLayerDescriptor:
    """解析后的 Mod 分层身份，不代表该 Mod 当前是否已加载。"""

    kind: str
    level: int
    parent_mod_id: str = ""
    parent_mod_ids: tuple[str, ...] = field(default_factory=tuple)
    lifecycle: str = "legacy"
    market_installable: bool = False
    employee_mode: str = ""
    fixed_employees: tuple[str, ...] = field(default_factory=tuple)
    employee_slots: tuple[str, ...] = field(default_factory=tuple)
    composite_owner: str = ""
    internal_component: bool = False
    legacy: bool = False


def _config_path() -> Path | None:
    candidates: list[Path] = []
    for parent in Path(__file__).resolve().parents:
        candidate = parent / "config" / "mod_levels.json"
        if candidate.is_file():
            candidates.append(candidate)
            break
    raw_root = str(os.environ.get("XCAGI_FHD_ROOT") or "").strip()
    if raw_root:
        candidate = Path(raw_root).expanduser() / "config" / "mod_levels.json"
        if candidate.is_file() and candidate not in candidates:
            candidates.insert(0, candidate)
    return candidates[0] if candidates else None


@lru_cache(maxsize=1)
def load_mod_levels_policy() -> dict[str, Any]:
    path = _config_path()
    if path is None:
        logger.warning("Mod layer SSOT not found; using safe built-in policy")
        return {
            "schema_version": 1,
            "virtual_ids": {"host_core": HOST_CORE_ID, "unified_erp": UNIFIED_ERP_ID},
            "levels": {},
            "kinds": {},
            "legacy_classification": {},
            "compatibility": {},
        }
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(data, dict):
            return data
    except (OSError, json.JSONDecodeError) as exc:
        logger.error("读取 Mod 分层 SSOT 失败 %s: %s", path, exc)
    return {}


def _ids(section: str) -> frozenset[str]:
    raw = (load_mod_levels_policy().get("legacy_classification") or {}).get(section, [])
    return frozenset(str(x).strip() for x in raw if str(x).strip())


def _kind_policy(kind: str) -> dict[str, Any]:
    raw = (load_mod_levels_policy().get("kinds") or {}).get(kind)
    return raw if isinstance(raw, dict) else {}


def _composites() -> dict[str, dict[str, Any]]:
    raw = load_mod_levels_policy().get("composites")
    if not isinstance(raw, dict):
        return {}
    return {str(k).strip(): v for k, v in raw.items() if str(k).strip() and isinstance(v, dict)}


def composite_definition(mod_id: str) -> dict[str, Any]:
    token = str(mod_id or "").strip()
    if not token:
        return {}
    direct = _composites().get(token)
    if direct:
        return direct
    for owner, definition in _composites().items():
        members = _string_list(definition.get("members"))
        if token in members:
            return {**definition, "id": owner}
    return {}


def composite_owner_for_mod_id(mod_id: str) -> str:
    token = str(mod_id or "").strip()
    if not token:
        return ""
    if token in _composites():
        return token
    for owner, definition in _composites().items():
        if token in _string_list(definition.get("members")):
            return owner
    return ""


def composite_member_ids(owner: str) -> tuple[str, ...]:
    definition = _composites().get(str(owner or "").strip()) or {}
    return _string_list(definition.get("members"))


def composite_fixed_employee_ids(owner: str) -> tuple[str, ...]:
    definition = _composites().get(str(owner or "").strip()) or {}
    return _string_list(definition.get("fixed_employee_mod_ids"))


def public_mod_id(mod_id: str) -> str:
    """返回面向用户的 Mod 身份；legacy bridge 只保留为内部实现组件。"""
    return composite_owner_for_mod_id(mod_id) or str(mod_id or "").strip()


def _level_for_kind(kind: str) -> int:
    configured = _kind_policy(kind).get("level")
    try:
        level = int(configured)
    except (TypeError, ValueError):
        level = 0
    if level > 0:
        return level
    return {
        KIND_HOST_CORE: HOST_CORE_LEVEL,
        KIND_SYSTEM_MOD: SYSTEM_MOD_LEVEL,
        KIND_INDUSTRY_MOD: DOMAIN_MOD_LEVEL,
        KIND_CUSTOM_MOD: DOMAIN_MOD_LEVEL,
        KIND_EMPLOYEE_PACK: EMPLOYEE_PACK_LEVEL,
    }[kind]


def _string_list(value: Any) -> tuple[str, ...]:
    if isinstance(value, str):
        value = [value]
    if not isinstance(value, (list, tuple, set)):
        return ()
    out: list[str] = []
    for item in value:
        token = str(item or "").strip()
        if token and token not in out:
            out.append(token)
    return tuple(out)


def _explicit_kind(manifest: dict[str, Any]) -> str:
    raw = manifest.get("mod_kind") or manifest.get("layer_kind")
    return str(raw or "").strip().lower()


def _explicit_level(manifest: dict[str, Any]) -> int | None:
    raw = manifest.get("mod_level")
    try:
        level = int(raw)
    except (TypeError, ValueError):
        return None
    return level if level > 0 else None


def _parent_ids(manifest: dict[str, Any]) -> tuple[str, ...]:
    raw = manifest.get("parent_mod_ids")
    if raw is None:
        raw = manifest.get("parent_mod_id") or manifest.get("parent")
    return _string_list(raw)


def _manifest_fixed_employees(manifest: dict[str, Any], *, kind: str = "") -> tuple[str, ...]:
    raw = manifest.get("fixed_employees")
    if raw is None:
        raw = (
            (manifest.get("employees") or {}).get("fixed")
            if isinstance(manifest.get("employees"), dict)
            else None
        )
    if raw is None and kind in {KIND_HOST_CORE, KIND_SYSTEM_MOD}:
        workflow_rows = manifest.get("workflow_employees")
        if isinstance(workflow_rows, list):
            raw = [
                row.get("id")
                for row in workflow_rows
                if isinstance(row, dict) and str(row.get("id") or "").strip()
            ]
    return _string_list(raw)


def descriptor_for_manifest(manifest: dict[str, Any]) -> ModLayerDescriptor:
    """从新字段优先、旧清单兼容表其次解析分层。"""
    manifest = manifest if isinstance(manifest, dict) else {}
    mod_id = str(manifest.get("id") or "").strip()
    artifact = normalize_artifact(manifest)
    explicit_kind = _explicit_kind(manifest)
    explicit_level = _explicit_level(manifest)
    legacy = False

    composite_owner = str(
        manifest.get("composite_owner") or manifest.get("system_owner") or ""
    ).strip()
    if not composite_owner:
        composite_owner = composite_owner_for_mod_id(mod_id)
    if explicit_kind:
        kind = explicit_kind
    elif mod_id in _composites():
        definition = _composites()[mod_id]
        kind = str(definition.get("kind") or KIND_SYSTEM_MOD).strip().lower()
    elif artifact == ARTIFACT_EMPLOYEE_PACK:
        kind = KIND_EMPLOYEE_PACK
    elif mod_id in _ids("legacy_employee_mod_ids"):
        kind = KIND_EMPLOYEE_PACK
        legacy = True
    elif mod_id in _ids("system_mod_ids"):
        kind = KIND_SYSTEM_MOD
        legacy = True
    elif mod_id in _ids("custom_mod_ids"):
        kind = KIND_CUSTOM_MOD
        legacy = True
    elif mod_id in _ids("industry_mod_ids") or isinstance(manifest.get("industry"), dict):
        kind = KIND_INDUSTRY_MOD
        legacy = True
    else:
        # 未声明的旧普通 Mod 不自动变成系统能力；按 L3 定制兼容读取，
        # 但仍然保持 market_installable=False，避免绕过市场准入策略。
        kind = KIND_CUSTOM_MOD
        legacy = True

    if kind not in _KNOWN_KINDS:
        kind = KIND_CUSTOM_MOD
        legacy = True

    default_level = _level_for_kind(kind)
    level = explicit_level or default_level

    cfg = manifest.get("config") if isinstance(manifest.get("config"), dict) else {}
    emp = manifest.get("employee") if isinstance(manifest.get("employee"), dict) else {}
    owner_layer = (
        str(manifest.get("owner_layer") or emp.get("owner_layer") or cfg.get("owner_layer") or "")
        .strip()
        .lower()
    )
    employee_mode = str(manifest.get("employee_mode") or "").strip().lower()
    if kind == KIND_EMPLOYEE_PACK and not employee_mode:
        employee_mode = (
            "fixed"
            if cfg.get("host_foundation_pack") or owner_layer in {KIND_HOST_CORE, KIND_SYSTEM_MOD}
            else "pluggable"
        )

    lifecycle = str(manifest.get("lifecycle") or "").strip().lower()
    if not lifecycle:
        if kind == KIND_EMPLOYEE_PACK:
            lifecycle = "bundled" if employee_mode == "fixed" else "market"
        elif kind == KIND_INDUSTRY_MOD:
            lifecycle = "seeded"
        elif kind == KIND_SYSTEM_MOD:
            lifecycle = "bundled"
        else:
            lifecycle = "admin" if kind == KIND_CUSTOM_MOD else "bundled"

    market_flag = manifest.get("market_installable")
    market_installable = (
        bool(market_flag)
        if isinstance(market_flag, bool)
        else bool(
            _kind_policy(kind).get("market_installable", kind == KIND_EMPLOYEE_PACK)
            and (kind != KIND_EMPLOYEE_PACK or employee_mode != "fixed")
        )
    )

    fixed_employees = _manifest_fixed_employees(manifest, kind=kind)
    if kind == KIND_EMPLOYEE_PACK and employee_mode == "fixed":
        employee_id = str(emp.get("id") or "").strip()
        if employee_id and employee_id not in fixed_employees:
            fixed_employees = (*fixed_employees, employee_id)

    parents = _parent_ids(manifest)
    internal_component = bool(composite_owner and mod_id != composite_owner)
    return ModLayerDescriptor(
        kind=kind,
        level=level,
        parent_mod_id=parents[0] if parents else "",
        parent_mod_ids=parents,
        lifecycle=lifecycle,
        market_installable=market_installable,
        employee_mode=employee_mode,
        fixed_employees=fixed_employees,
        employee_slots=_string_list(manifest.get("employee_slots")),
        composite_owner=composite_owner,
        internal_component=internal_component,
        legacy=legacy,
    )


def canonical_mod_id(mod_id: str) -> str:
    token = str(mod_id or "").strip()
    aliases = (load_mod_levels_policy().get("compatibility") or {}).get("canonical_aliases") or {}
    return str(aliases.get(token) or token).strip()


def dependency_ids_for_metadata(metadata: Any) -> tuple[str, ...]:
    deps = getattr(metadata, "dependencies", {})
    raw: list[str] = []
    if isinstance(deps, dict):
        raw.extend(str(k).strip() for k in deps if str(k).strip() and str(k).strip() != "xcagi")
    parents = getattr(metadata, "parent_mod_ids", ()) or ()
    raw.extend(str(x).strip() for x in parents if str(x).strip())
    out: list[str] = []
    for item in raw:
        canonical = canonical_mod_id(item)
        if canonical and canonical not in out:
            out.append(canonical)
    return tuple(out)


def sort_mods_for_loading(mods: Iterable[Any]) -> list[Any]:
    """按依赖拓扑排序，等级只用于同层就绪节点的稳定排序。"""
    items = list(mods)
    by_id = {
        str(getattr(m, "id", "")).strip(): m for m in items if str(getattr(m, "id", "")).strip()
    }
    loaded: set[str] = set()
    remaining = set(by_id)
    result: list[Any] = []

    def key(mid: str) -> tuple[int, int, str]:
        item = by_id[mid]
        descriptor = descriptor_for_metadata(item)
        kind_order = {
            KIND_SYSTEM_MOD: 0,
            KIND_INDUSTRY_MOD: 1,
            KIND_CUSTOM_MOD: 2,
            KIND_EMPLOYEE_PACK: 3,
        }.get(descriptor.kind, 9)
        return descriptor.level, kind_order, mid.lower()

    while remaining:
        ready: list[str] = []
        for mid in remaining:
            deps = dependency_ids_for_metadata(by_id[mid])
            if all(
                dep in loaded or dep == HOST_CORE_ID
                for dep in deps
                if dep in by_id or dep == HOST_CORE_ID
            ):
                # 对声明了但本次未扫描到的依赖，留给原有校验产生明确失败日志。
                ready.append(mid)
        if not ready:
            # 环或不完整依赖图：保留稳定顺序，load_mod 会阻止真正不满足的节点。
            result.extend(by_id[mid] for mid in sorted(remaining, key=key))
            break
        for mid in sorted(ready, key=key):
            result.append(by_id[mid])
            loaded.add(mid)
            remaining.remove(mid)
    return result


def descriptor_for_metadata(metadata: Any) -> ModLayerDescriptor:
    raw_id = getattr(metadata, "id", "")
    metadata_id = raw_id.strip() if isinstance(raw_id, str) else ""
    raw_composite_owner = getattr(metadata, "composite_owner", "")
    composite_owner = raw_composite_owner.strip() if isinstance(raw_composite_owner, str) else ""
    if not composite_owner and metadata_id:
        composite_owner = composite_owner_for_mod_id(metadata_id)
    raw_internal_component = getattr(metadata, "internal_component", False)
    return ModLayerDescriptor(
        kind=str(getattr(metadata, "mod_kind", "") or "").strip()
        or descriptor_for_manifest({"id": getattr(metadata, "id", "")}).kind,
        level=int(getattr(metadata, "mod_level", 0) or 0)
        or descriptor_for_manifest({"id": getattr(metadata, "id", "")}).level,
        parent_mod_id=str(getattr(metadata, "parent_mod_id", "") or "").strip(),
        parent_mod_ids=tuple(getattr(metadata, "parent_mod_ids", ()) or ()),
        lifecycle=str(getattr(metadata, "lifecycle", "") or "legacy").strip(),
        market_installable=bool(getattr(metadata, "market_installable", False)),
        employee_mode=str(getattr(metadata, "employee_mode", "") or "").strip(),
        fixed_employees=tuple(getattr(metadata, "fixed_employees", ()) or ()),
        employee_slots=tuple(getattr(metadata, "employee_slots", ()) or ()),
        composite_owner=composite_owner,
        internal_component=(
            raw_internal_component if isinstance(raw_internal_component, bool) else False
        ),
        legacy=bool(getattr(metadata, "legacy_layer", False)),
    )


from .mod_levels_validation import (  # noqa: E402,F401,I001
    market_catalog_row_allowed,
    market_install_block_reason,
    validate_layer_manifest,
)


__all__ = [
    "HOST_CORE_ID",
    "UNIFIED_ERP_ID",
    "HOST_CORE_LEVEL",
    "SYSTEM_MOD_LEVEL",
    "DOMAIN_MOD_LEVEL",
    "EMPLOYEE_PACK_LEVEL",
    "KIND_HOST_CORE",
    "KIND_SYSTEM_MOD",
    "KIND_INDUSTRY_MOD",
    "KIND_CUSTOM_MOD",
    "KIND_EMPLOYEE_PACK",
    "ModLayerDescriptor",
    "load_mod_levels_policy",
    "descriptor_for_manifest",
    "descriptor_for_metadata",
    "validate_layer_manifest",
    "market_install_block_reason",
    "market_catalog_row_allowed",
    "composite_definition",
    "composite_owner_for_mod_id",
    "composite_member_ids",
    "composite_fixed_employee_ids",
    "public_mod_id",
    "canonical_mod_id",
    "dependency_ids_for_metadata",
    "sort_mods_for_loading",
]
