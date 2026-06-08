# -*- coding: utf-8 -*-
"""按行业聚合「要补哪些基础线」——供首启引导与扩展市场推荐。"""

from __future__ import annotations

from functools import lru_cache
from typing import Any

from app.mod_sdk.host_profile import resolve_fhd_config_dir


def _load_json(path):
    import json

    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None


@lru_cache(maxsize=1)
def load_industry_baseline_document() -> dict[str, Any]:
    cfg = resolve_fhd_config_dir()
    if cfg:
        doc = _load_json(cfg / "industry_baseline.json")
        if doc and isinstance(doc.get("industries"), dict):
            return doc
    return {
        "schema_version": 1,
        "core_mod_ids": ["xcagi-planner-bridge", "xcagi-neuro-bus-bridge"],
        "mod_labels": {},
        "industries": {"通用": {"host_mod_ids": [], "optional_host_mod_ids": [], "industry_mod_ids": []}},
    }


def _installed_mod_ids() -> list[str]:
    try:
        from app.infrastructure.mods.mod_manager import get_mod_manager

        mm = get_mod_manager()
        ids = [m.id for m in (mm.list_loaded_mods() or []) if getattr(m, "id", None)]
        if ids:
            return ids
        return [m.id for m in mm.scan_mods() if getattr(m, "id", None)]
    except Exception:
        return []


def _dedupe(seq: list[str]) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    for raw in seq:
        mid = str(raw or "").strip()
        if not mid or mid in seen:
            continue
        seen.add(mid)
        out.append(mid)
    return out


def _industry_row(industry_id: str) -> dict[str, Any]:
    doc = load_industry_baseline_document()
    industries = doc.get("industries") or {}
    key = str(industry_id or "").strip() or "通用"
    row = industries.get(key)
    if isinstance(row, dict):
        return row
    return industries.get("通用") if isinstance(industries.get("通用"), dict) else {}


def _industry_package(industry_id: str) -> dict[str, Any]:
    doc = load_industry_baseline_document()
    packages = doc.get("industry_packages") or {}
    row = packages.get(str(industry_id or "").strip())
    return row if isinstance(row, dict) else {}


def _industry_mod_ids_for(industry_key: str, row: dict[str, Any]) -> list[str]:
    pkg = _industry_package(industry_key)
    mid = str(pkg.get("mod_id") or "").strip()
    if mid:
        return [mid]
    return _dedupe([str(x) for x in (row.get("industry_mod_ids") or []) if x])


def _label_for_mod(mod_id: str, industry_key: str, labels: dict[str, str]) -> str:
    pkg = _industry_package(industry_key)
    if str(pkg.get("mod_id") or "").strip() == mod_id:
        name = str(pkg.get("product_name") or "").strip()
        if name:
            return name
    return labels.get(mod_id, mod_id)


def _read_mod_manifest_json(mod_id: str) -> dict[str, Any]:
    try:
        from app.infrastructure.mods.mod_manager import get_mod_manager

        mm = get_mod_manager()
        mod_path = mm.resolve_mod_directory(mod_id)
        if not mod_path:
            return {}
        import json
        from pathlib import Path

        mf = Path(mod_path) / "manifest.json"
        if not mf.is_file():
            return {}
        data = json.loads(mf.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def _custom_line_spec(industry_mod_id: str) -> tuple[str, list[str]]:
    """从行业/定制 Mod manifest 读取定制线 hint 与额外 mod id（不含行业包本身）。"""
    mid = str(industry_mod_id or "").strip()
    if not mid:
        return "按行业定制 Mod 加载；装后菜单与 AI 员工随行业变化", []
    data = _read_mod_manifest_json(mid)
    onboarding = data.get("onboarding") if isinstance(data.get("onboarding"), dict) else {}
    hint = str(onboarding.get("custom_line_hint") or onboarding.get("hint") or "").strip()
    if not hint:
        hint = "按行业定制 Mod 加载；装后菜单与 AI 员工随行业变化"
    raw_ids = onboarding.get("custom_mod_ids")
    if raw_ids is None:
        raw_ids = data.get("custom_mod_ids")
    extra = _dedupe([str(x) for x in (raw_ids or []) if x and str(x).strip() != mid])
    # manifest dependencies 中除 xcagi 外的 Mod 依赖也纳入定制线
    deps = data.get("dependencies") if isinstance(data.get("dependencies"), dict) else {}
    for dep_id in deps:
        dep = str(dep_id or "").strip()
        if dep and dep != "xcagi" and dep != mid:
            extra.append(dep)
    return hint, _dedupe(extra)


def _mod_installed(mod_id: str, installed: set[str]) -> bool:
    mid = str(mod_id or "").strip()
    if not mid:
        return False
    if mid in installed:
        return True
    try:
        from app.mod_sdk.industry_mod_aliases import canonical_mod_id, legacy_mod_ids_for

        cid = canonical_mod_id(mid)
        if cid in installed:
            return True
        for leg in legacy_mod_ids_for(cid):
            if leg in installed:
                return True
    except Exception:
        pass
    return False


def _label_for_custom_mod(mod_id: str, industry_key: str, labels: dict[str, str]) -> str:
    label = _label_for_mod(mod_id, industry_key, labels)
    if label != mod_id:
        return label
    data = _read_mod_manifest_json(mod_id)
    name = str(data.get("name") or "").strip()
    return name or mod_id


def build_onboarding_industry_catalog() -> dict[str, Any]:
    doc = load_industry_baseline_document()
    open_ids = _dedupe(
        [str(x) for x in (doc.get("onboarding_open_industry_ids") or []) if x]
    )
    open_packages: list[dict[str, Any]] = []
    for iid in open_ids:
        pkg = _industry_package(iid)
        open_packages.append(
            {
                "industry_id": iid,
                "product_name": str(pkg.get("product_name") or f"{iid}行业包").strip(),
                "mod_id": str(pkg.get("mod_id") or "").strip(),
            }
        )
    return {
        "schema_version": doc.get("schema_version", 1),
        "open_industry_ids": open_ids,
        "open_packages": open_packages,
    }


def build_industry_baseline_plan(
    industry_id: str,
    installed_mod_ids: list[str] | None = None,
) -> dict[str, Any]:
    doc = load_industry_baseline_document()
    labels: dict[str, str] = {
        str(k): str(v) for k, v in (doc.get("mod_labels") or {}).items() if k
    }
    core_ids = _dedupe([str(x) for x in (doc.get("core_mod_ids") or []) if x])
    row = _industry_row(industry_id)
    industry_key = str(industry_id or "").strip() or "通用"

    required_ids = _dedupe(
        core_ids
        + [str(x) for x in (row.get("host_mod_ids") or []) if x]
    )
    optional_ids = _dedupe(
        [
            str(x).strip()
            for x in (row.get("optional_host_mod_ids") or [])
            if str(x or "").strip() and str(x).strip() not in required_ids
        ]
    )
    industry_mod_ids = _industry_mod_ids_for(industry_key, row)

    installed = set(installed_mod_ids or _installed_mod_ids())

    def _item(mod_id: str, tier: str, required: bool, *, show_mod_id: bool | None = None) -> dict[str, Any]:
        if show_mod_id is None:
            show_mod_id = tier in ("core", "host", "optional")
        return {
            "mod_id": mod_id,
            "label": _label_for_mod(mod_id, industry_key, labels)
            if tier != "custom"
            else _label_for_custom_mod(mod_id, industry_key, labels),
            "tier": tier,
            "required": required,
            "installed": _mod_installed(mod_id, installed),
            "show_mod_id": show_mod_id,
        }

    custom_hint, custom_extra_ids = _custom_line_spec(industry_mod_ids[0] if industry_mod_ids else "")
    custom_mod_ids = _dedupe(industry_mod_ids + custom_extra_ids)

    groups: list[dict[str, Any]] = [
        {
            "id": "core",
            "title": "对话底座",
            "hint": "干净页面所需：智能对话与智能生态",
            "items": [_item(mid, "core", True) for mid in core_ids],
        },
        {
            "id": "host",
            "title": "行业基础线",
            "hint": "按所选行业建议安装的宿主 Mod",
            "items": [
                _item(mid, "host", True)
                for mid in required_ids
                if mid not in core_ids
            ],
        },
    ]
    if custom_mod_ids:
        groups.append(
            {
                "id": "custom",
                "title": "定制线",
                "hint": custom_hint,
                "items": [
                    _item(mid, "custom", False, show_mod_id=False)
                    if mid in industry_mod_ids
                    else _item(mid, "custom", False, show_mod_id=True)
                    for mid in custom_mod_ids
                ],
            }
        )
    groups.extend(
        [
            {
                "id": "optional",
                "title": "可选增强",
                "hint": "用到再装，不阻塞进入对话",
                "items": [_item(mid, "optional", False) for mid in optional_ids],
            },
        ]
    )
    groups = [g for g in groups if g.get("items")]

    flat_items = [it for g in groups for it in g["items"]]
    missing_required = [it["mod_id"] for it in flat_items if it["required"] and not it["installed"]]
    missing_optional = [
        it["mod_id"] for it in flat_items if not it["required"] and not it["installed"]
    ]
    missing_industry = [
        it["mod_id"]
        for it in flat_items
        if it["tier"] == "custom" and not it["installed"]
    ]

    pkg = _industry_package(industry_key)
    industry_package = None
    if pkg.get("mod_id"):
        industry_package = {
            "mod_id": str(pkg.get("mod_id") or "").strip(),
            "product_name": str(pkg.get("product_name") or "").strip(),
        }

    return {
        "schema_version": 1,
        "industry_id": industry_key,
        "summary": str(row.get("summary") or "").strip(),
        "industry_package": industry_package,
        "groups": groups,
        "required_mod_ids": required_ids,
        "optional_mod_ids": optional_ids,
        "industry_mod_ids": industry_mod_ids,
        "custom_mod_ids": custom_mod_ids,
        "missing_required_mod_ids": missing_required,
        "missing_optional_mod_ids": missing_optional,
        "missing_industry_mod_ids": missing_industry,
        "baseline_ready": len(missing_required) == 0,
        "industry_mod_ready": len(missing_industry) == 0,
    }


__all__ = [
    "build_industry_baseline_plan",
    "build_onboarding_industry_catalog",
    "load_industry_baseline_document",
]
