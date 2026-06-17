# -*- coding: utf-8 -*-
"""按行业聚合「要补哪些基础线」——供首启引导与扩展市场推荐。"""

from __future__ import annotations

from functools import lru_cache
from typing import Any, cast

from app.mod_sdk.host_profile import resolve_fhd_config_dir
from app.utils.operational_errors import RECOVERABLE_ERRORS


def _load_json(path):
    import json

    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except RECOVERABLE_ERRORS:
        return None


@lru_cache(maxsize=1)
def load_industry_baseline_document() -> dict[str, Any]:
    cfg = resolve_fhd_config_dir()
    if cfg:
        doc = _load_json(cfg / "industry_baseline.json")
        if doc and isinstance(doc.get("industries"), dict):
            return cast("dict[str, Any]", doc)
    return {
        "schema_version": 1,
        "core_mod_ids": ["xcagi-planner-bridge", "xcagi-neuro-bus-bridge"],
        "mod_labels": {},
        "industries": {
            "通用": {"host_mod_ids": [], "optional_host_mod_ids": [], "industry_mod_ids": []}
        },
    }


def _installed_mod_ids() -> list[str]:
    try:
        from app.infrastructure.mods.mod_manager import get_mod_manager

        mm = get_mod_manager()
        loaded = [m.id for m in (mm.list_loaded_mods() or []) if getattr(m, "id", None)]
        scanned = [m.id for m in mm.scan_mods() if getattr(m, "id", None)]
        if scanned or loaded:
            return _dedupe(scanned + loaded)
        return []
    except RECOVERABLE_ERRORS:
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
    except RECOVERABLE_ERRORS:
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
    except RECOVERABLE_ERRORS:
        pass
    return False


def _custom_employee_extension_ids(
    industry_key: str,
    row: dict[str, Any],
    doc: dict[str, Any],
) -> list[str]:
    """账号定制阶段随定制 Mod 一并安装的 AI 员工桥接（非侧栏基准线）。"""
    doc_level = _dedupe(
        [str(x) for x in (doc.get("custom_employee_extension_mod_ids") or []) if x]
    )
    row_level = _dedupe(
        [str(x) for x in (row.get("custom_employee_extension_mod_ids") or []) if x]
    )
    return _dedupe(doc_level + row_level)


def _label_for_custom_mod(mod_id: str, industry_key: str, labels: dict[str, str]) -> str:
    label = _label_for_mod(mod_id, industry_key, labels)
    if label != mod_id:
        return label
    data = _read_mod_manifest_json(mod_id)
    name = str(data.get("name") or "").strip()
    return name or mod_id


def _onboarding_package_row(
    industry_id: str,
    *,
    selectable: bool,
    presets: dict[str, Any],
) -> dict[str, Any]:
    iid = str(industry_id or "").strip()
    pkg = _industry_package(iid)
    preset = presets.get(iid) if isinstance(presets.get(iid), dict) else {}
    name = str(preset.get("name") or iid).strip()
    scenario = str(preset.get("scenario") or "").strip()
    return {
        "industry_id": iid,
        "name": name,
        "scenario": scenario,
        "product_name": str(pkg.get("product_name") or f"{iid}行业包").strip(),
        "mod_id": str(pkg.get("mod_id") or "").strip(),
        "selectable": selectable,
    }


def industry_entitled_for_client_mods(industry_id: str, entitled_mod_ids: set[str]) -> bool:
    """企业 entitlement：行业是否对当前账号开放（含 legacy mod id 别名）。"""
    from app.mod_sdk.industry_mod_aliases import (
        canonical_mod_id,
        canonical_mod_id_for_industry,
        legacy_mod_ids_for,
    )

    iid = str(industry_id or "").strip()
    if not iid:
        return False
    canonical = canonical_mod_id_for_industry(iid)
    if not canonical:
        return False
    entitled = {str(x).strip() for x in entitled_mod_ids if str(x).strip()}
    entitled_canonical = {canonical_mod_id(mid) for mid in entitled} | entitled
    if canonical in entitled_canonical:
        return True
    for leg in legacy_mod_ids_for(canonical):
        if leg in entitled:
            return True
    return False


def filter_onboarding_catalog_for_entitlements(
    catalog: dict[str, Any],
    entitled_mod_ids: set[str],
) -> dict[str, Any]:
    """按企业客户 Mod 权益裁剪开放行业；未 entitlement 的开放项降级为 preview。"""
    entitled = {str(x).strip() for x in entitled_mod_ids if str(x).strip()}
    open_pkgs: list[dict[str, Any]] = []
    demoted: list[dict[str, Any]] = []
    open_by_id: set[str] = set()
    for pkg in catalog.get("open_packages") or []:
        if not isinstance(pkg, dict):
            continue
        iid = str(pkg.get("industry_id") or "").strip()
        row = dict(pkg)
        if industry_entitled_for_client_mods(iid, entitled):
            row["selectable"] = True
            open_pkgs.append(row)
            if iid:
                open_by_id.add(iid)
        else:
            row["selectable"] = False
            demoted.append(row)

    preview_pkgs = [
        dict(p) if isinstance(p, dict) else p for p in (catalog.get("preview_packages") or [])
    ]
    try:
        from app.mod_sdk.host_profile import load_industry_presets_document

        presets_doc = load_industry_presets_document()
    except RECOVERABLE_ERRORS:
        presets_doc = {}
    presets = presets_doc.get("presets") if isinstance(presets_doc.get("presets"), dict) else {}

    doc = load_industry_baseline_document()
    package_ids = [
        str(iid or "").strip()
        for iid in (doc.get("industry_packages") or {}).keys()
        if str(iid or "").strip()
    ]
    for iid in _dedupe(package_ids):
        if iid in open_by_id:
            continue
        if not industry_entitled_for_client_mods(iid, entitled):
            continue
        moved = False
        next_preview: list[dict[str, Any]] = []
        for pkg in preview_pkgs:
            if isinstance(pkg, dict) and str(pkg.get("industry_id") or "").strip() == iid:
                row = dict(pkg)
                row["selectable"] = True
                open_pkgs.append(row)
                open_by_id.add(iid)
                moved = True
            else:
                next_preview.append(pkg)
        preview_pkgs = next_preview
        if not moved:
            open_pkgs.append(_onboarding_package_row(iid, selectable=True, presets=presets))
            open_by_id.add(iid)

    preview_ids = {
        str(p.get("industry_id") or "").strip()
        for p in preview_pkgs
        if isinstance(p, dict) and str(p.get("industry_id") or "").strip()
    }
    for pkg in demoted:
        iid = str(pkg.get("industry_id") or "").strip()
        if iid and iid not in preview_ids:
            preview_pkgs.append(pkg)
            preview_ids.add(iid)

    open_ids = [
        str(p.get("industry_id") or "").strip()
        for p in open_pkgs
        if str(p.get("industry_id") or "").strip()
    ]
    return {
        **catalog,
        "open_industry_ids": open_ids,
        "open_packages": open_pkgs,
        "preview_packages": preview_pkgs,
    }


async def build_onboarding_industry_catalog_for_request(request) -> dict[str, Any]:
    """按会话感知：企业 entitlement 二级筛选 + 租户已选行业。"""
    from app.application.tenant_workspace_prefs import (
        get_workspace_prefs,
        resolve_workspace_owner_id,
    )
    from app.enterprise.mod_entitlements import (
        enterprise_mod_filter_active,
        get_cached_entitled_client_mod_ids,
        is_admin_account_session,
        sync_entitlements_from_request,
    )
    from app.infrastructure.auth.dependencies import resolve_session_user, session_id_from_request

    catalog = build_onboarding_industry_catalog()
    meta: dict[str, Any] = {
        "enterprise_filter_applied": False,
        "owner_id": None,
        "selected_industry_id": None,
    }

    user = resolve_session_user(request)
    if user is not None:
        owner_id = resolve_workspace_owner_id(request, user)
        if owner_id:
            meta["owner_id"] = owner_id
            prefs = get_workspace_prefs(owner_id)
            selected = str(prefs.get("selected_industry_id") or "").strip()
            if selected:
                meta["selected_industry_id"] = selected

    if not enterprise_mod_filter_active():
        return {**catalog, **meta}

    sid = session_id_from_request(request)
    if not sid:
        return {**catalog, **meta}

    await sync_entitlements_from_request(request)
    meta["enterprise_filter_applied"] = True

    if is_admin_account_session():
        return {**catalog, **meta}

    entitled = get_cached_entitled_client_mod_ids() or set()
    filtered = filter_onboarding_catalog_for_entitlements(catalog, entitled)
    return {**filtered, **meta}


def build_onboarding_industry_catalog() -> dict[str, Any]:
    doc = load_industry_baseline_document()
    open_ids = _dedupe([str(x) for x in (doc.get("onboarding_open_industry_ids") or []) if x])

    presets_doc: dict[str, Any] = {}
    try:
        from app.mod_sdk.host_profile import load_industry_presets_document

        presets_doc = load_industry_presets_document()
    except RECOVERABLE_ERRORS:
        presets_doc = {}
    presets = presets_doc.get("presets") if isinstance(presets_doc.get("presets"), dict) else {}

    open_packages = [
        _onboarding_package_row(iid, selectable=True, presets=presets) for iid in open_ids
    ]

    preset_ids = presets_doc.get("preset_ids")
    if not isinstance(preset_ids, list):
        preset_ids = list(presets.keys())
    preview_ids = _dedupe(
        [str(x) for x in preset_ids if str(x or "").strip() and str(x).strip() not in open_ids]
    )
    preview_packages = [
        _onboarding_package_row(iid, selectable=False, presets=presets) for iid in preview_ids
    ]

    return {
        "schema_version": doc.get("schema_version", 1),
        "open_industry_ids": open_ids,
        "open_packages": open_packages,
        "preview_packages": preview_packages,
    }


def build_industry_baseline_plan(
    industry_id: str,
    installed_mod_ids: list[str] | None = None,
    *,
    entitled_mod_ids: set[str] | None = None,
    skip_account_custom_gate: bool = False,
) -> dict[str, Any]:
    doc = load_industry_baseline_document()
    labels: dict[str, str] = {str(k): str(v) for k, v in (doc.get("mod_labels") or {}).items() if k}
    core_ids = _dedupe([str(x) for x in (doc.get("core_mod_ids") or []) if x])
    row = _industry_row(industry_id)
    industry_key = str(industry_id or "").strip() or "通用"

    required_ids = _dedupe(core_ids + [str(x) for x in (row.get("host_mod_ids") or []) if x])
    optional_ids = _dedupe(
        [
            str(x).strip()
            for x in (row.get("optional_host_mod_ids") or [])
            if str(x or "").strip() and str(x).strip() not in required_ids
        ]
    )
    industry_mod_ids = _industry_mod_ids_for(industry_key, row)

    if installed_mod_ids is None:
        installed = set(_installed_mod_ids())
    else:
        installed = set(installed_mod_ids)

    def _item(
        mod_id: str,
        tier: str,
        required: bool,
        *,
        show_mod_id: bool | None = None,
        label: str | None = None,
    ) -> dict[str, Any]:
        if show_mod_id is None:
            show_mod_id = tier in ("core", "host", "optional", "account_custom")
        resolved_label = label
        if not resolved_label:
            if tier == "account_custom":
                from app.mod_sdk.customer_delivery import label_for_account_custom_mod

                resolved_label = label_for_account_custom_mod(mod_id, industry_key)
            elif tier == "industry_package":
                resolved_label = _label_for_mod(mod_id, industry_key, labels)
            elif tier == "custom":
                resolved_label = _label_for_custom_mod(mod_id, industry_key, labels)
            else:
                resolved_label = _label_for_mod(mod_id, industry_key, labels)
        return {
            "mod_id": mod_id,
            "label": resolved_label,
            "tier": tier,
            "required": required,
            "installed": _mod_installed(mod_id, installed),
            "show_mod_id": show_mod_id,
        }

    custom_hint, _custom_extra_ids = _custom_line_spec(
        industry_mod_ids[0] if industry_mod_ids else ""
    )

    from app.mod_sdk.customer_delivery import account_custom_mod_ids_for_industry

    account_custom_base = account_custom_mod_ids_for_industry(industry_key, entitled_mod_ids)
    employee_extension_ids = (
        _custom_employee_extension_ids(industry_key, row, doc) if account_custom_base else []
    )
    account_custom_ids = _dedupe(account_custom_base + employee_extension_ids)
    custom_mod_ids = _dedupe(industry_mod_ids + account_custom_ids)

    groups: list[dict[str, Any]] = [
        {
            "id": "core",
            "title": "侧栏对话底座",
            "hint": "干净起步：侧栏挂上智能对话与智能生态入口（宿主桥接，非员工数据）",
            "items": [_item(mid, "core", True) for mid in core_ids],
        },
        {
            "id": "host",
            "title": "行业侧栏基础线",
            "hint": "按行业补侧栏业务菜单与表格工具等宿主能力卡片（不含 AI 员工）",
            "items": [_item(mid, "host", True) for mid in required_ids if mid not in core_ids],
        },
    ]
    if industry_mod_ids:
        groups.append(
            {
                "id": "industry_package",
                "title": "行业包",
                "hint": custom_hint or "行业通用 Mod：侧栏与业务门面（不含账号定制员工）",
                "items": [
                    _item(mid, "industry_package", False, show_mod_id=False)
                    for mid in industry_mod_ids
                ],
            }
        )
    if account_custom_ids:
        groups.append(
            {
                "id": "account_custom",
                "title": "账号定制",
                "hint": "账号定制 Mod：装齐后解锁定制能力与定制 AI 员工",
                "items": [
                    _item(mid, "account_custom", True, show_mod_id=True)
                    for mid in account_custom_ids
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
        if it["tier"] in ("industry_package", "custom") and not it["installed"]
    ]
    missing_account_custom = [
        it["mod_id"]
        for it in flat_items
        if it["tier"] == "account_custom" and it["required"] and not it["installed"]
    ]
    account_delivery_seed_packages: list[dict[str, Any]] = []
    if account_custom_ids:
        from app.mod_sdk.customer_delivery import delivery_seed_package_for_mod

        for mid in account_custom_ids:
            pkg_meta = delivery_seed_package_for_mod(mid, industry_key)
            if not pkg_meta:
                continue
            account_delivery_seed_packages.append({"mod_id": mid, **pkg_meta})
            for item in flat_items:
                if item.get("mod_id") == mid:
                    item["delivery_seed_package"] = dict(pkg_meta)

    host_baseline_ready = len(missing_required) == 0
    industry_mod_ready = len(missing_industry) == 0
    account_custom_ready = skip_account_custom_gate or len(missing_account_custom) == 0

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
        "account_custom_mod_ids": account_custom_ids,
        "missing_account_custom_mod_ids": missing_account_custom,
        "account_delivery_seed_packages": account_delivery_seed_packages,
        "host_baseline_ready": host_baseline_ready,
        "account_custom_ready": account_custom_ready,
        "custom_employee_extension_mod_ids": employee_extension_ids,
        "baseline_ready": host_baseline_ready,
        "full_stack_ready": host_baseline_ready and account_custom_ready and industry_mod_ready,
        "industry_mod_ready": industry_mod_ready,
    }


async def build_industry_baseline_plan_for_request(
    request, industry_id: str = "通用"
) -> dict[str, Any]:
    """会话感知：同步 market entitlement，管理员可跳过账号定制强制。"""
    from app.enterprise.mod_entitlements import (
        enterprise_mod_filter_active,
        get_cached_entitled_client_mod_ids,
        is_admin_account_session,
        sync_entitlements_from_request,
    )
    from app.infrastructure.auth.dependencies import session_id_from_request

    entitled: set[str] | None = None
    skip_account_custom = False

    if enterprise_mod_filter_active():
        sid = session_id_from_request(request)
        if sid:
            await sync_entitlements_from_request(request)
            if is_admin_account_session():
                skip_account_custom = True
            entitled = get_cached_entitled_client_mod_ids() or set()

    return build_industry_baseline_plan(
        industry_id,
        entitled_mod_ids=entitled,
        skip_account_custom_gate=skip_account_custom,
    )


__all__ = [
    "build_industry_baseline_plan",
    "build_industry_baseline_plan_for_request",
    "build_onboarding_industry_catalog",
    "build_onboarding_industry_catalog_for_request",
    "filter_onboarding_catalog_for_entitlements",
    "industry_entitled_for_client_mods",
    "load_industry_baseline_document",
]
