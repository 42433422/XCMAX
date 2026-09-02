"""按行业聚合「要补哪些基础线」——供首启引导与扩展市场推荐。"""

from __future__ import annotations

from functools import lru_cache
from typing import Any, cast

from app.mod_sdk.host_profile import resolve_fhd_config_dir
from app.mod_sdk.industry_baseline_plans import (
    build_industry_baseline_plan,
)
from app.mod_sdk.industry_baseline_plans import (
    ensure_industries_selectable as _ensure_industries_selectable,
)
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
    fallback = industries.get("通用")
    return cast("dict[str, Any]", fallback) if isinstance(fallback, dict) else {}


def _industry_package(industry_id: str) -> dict[str, Any]:
    doc = load_industry_baseline_document()
    packages = doc.get("industry_packages") or {}
    row = packages.get(str(industry_id or "").strip())
    return row if isinstance(row, dict) else {}


def _industry_package_mod_ids_for(industry_key: str) -> list[str]:
    pkg = _industry_package(industry_key)
    mid = str(pkg.get("mod_id") or "").strip()
    return [mid] if mid else []


def _industry_capability_mod_ids_for(row: dict[str, Any]) -> list[str]:
    """行业可组合的通用业务模块；不改变客户所属行业。"""
    return _dedupe([str(x) for x in (row.get("capability_mod_ids") or []) if x])


def _industry_mod_ids_for(industry_key: str, row: dict[str, Any]) -> list[str]:
    """兼容字段：行业包与可组合业务模块的并集。"""
    return _dedupe(
        _industry_package_mod_ids_for(industry_key)
        + _industry_capability_mod_ids_for(row)
        + [str(x) for x in (row.get("industry_mod_ids") or []) if x]
    )


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
    if not isinstance(onboarding, dict):
        onboarding = {}
    hint = str(onboarding.get("custom_line_hint") or onboarding.get("hint") or "").strip()
    if not hint:
        hint = "按行业定制 Mod 加载；装后菜单与 AI 员工随行业变化"
    raw_ids = onboarding.get("custom_mod_ids")
    if raw_ids is None:
        raw_ids = data.get("custom_mod_ids")
    extra = _dedupe([str(x) for x in (raw_ids or []) if x and str(x).strip() != mid])
    # manifest dependencies 中除 xcagi 外的 Mod 依赖也纳入定制线
    deps = data.get("dependencies") if isinstance(data.get("dependencies"), dict) else {}
    for dep_id in deps or []:
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
    doc_level = _dedupe([str(x) for x in (doc.get("custom_employee_extension_mod_ids") or []) if x])
    row_level = _dedupe([str(x) for x in (row.get("custom_employee_extension_mod_ids") or []) if x])
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
    if not isinstance(preset, dict):
        preset = {}
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
    # 开放引导行业(涂料/考勤等中性行业包随产品分发)在引导期始终可选，
    # 不受"市场客户 Mod 权益"限制——否则新注册企业账号选不到自己注册的行业。
    try:
        doc = load_industry_baseline_document()
        open_ids = {
            str(x).strip()
            for x in (doc.get("onboarding_open_industry_ids") or [])
            if str(x or "").strip()
        }
        if iid in open_ids:
            return True
    except RECOVERABLE_ERRORS:
        pass
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

    preview_pkgs: list[Any] = []
    for pkg in catalog.get("preview_packages") or []:
        if not isinstance(pkg, dict):
            preview_pkgs.append(pkg)
            continue
        iid = str(pkg.get("industry_id") or "").strip()
        row = dict(pkg)
        if iid and iid not in open_by_id and industry_entitled_for_client_mods(iid, entitled):
            row["selectable"] = True
            open_pkgs.append(row)
            open_by_id.add(iid)
        else:
            preview_pkgs.append(row)
    preview_ids = {
        str(p.get("industry_id") or "").strip() for p in preview_pkgs if isinstance(p, dict)
    }
    for row in demoted:
        iid = str(row.get("industry_id") or "").strip()
        if iid and iid in preview_ids:
            continue
        preview_pkgs.append(row)
        if iid:
            preview_ids.add(iid)
    out = dict(catalog)
    out["open_packages"] = open_pkgs
    out["preview_packages"] = preview_pkgs
    out["open_industry_ids"] = [
        str(p.get("industry_id") or "").strip()
        for p in open_pkgs
        if isinstance(p, dict) and str(p.get("industry_id") or "").strip()
    ]
    return out


def _user_industry_id(user: Any) -> str:
    if user is None:
        return ""
    if isinstance(user, dict):
        return str(user.get("industry_id") or "").strip()
    return str(getattr(user, "industry_id", "") or "").strip()


def _user_username(user: Any) -> str:
    if user is None:
        return ""
    if isinstance(user, dict):
        return str(user.get("username") or "").strip()
    return str(getattr(user, "username", "") or "").strip()


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

    forced_ids: set[str] = set()
    user = resolve_session_user(request)
    if user is not None:
        from app.mod_sdk.customer_delivery import industry_id_for_account

        delivery_industry = industry_id_for_account(_user_username(user))
        uid_industry = delivery_industry or _user_industry_id(user)
        if uid_industry:
            forced_ids.add(uid_industry)
        owner_id = resolve_workspace_owner_id(request, user)
        if owner_id:
            meta["owner_id"] = owner_id
            prefs = get_workspace_prefs(owner_id)
            selected = delivery_industry or str(prefs.get("selected_industry_id") or "").strip()
            if selected:
                meta["selected_industry_id"] = selected
                forced_ids.add(selected)

    def _finish(cat: dict[str, Any]) -> dict[str, Any]:
        return {**_ensure_industries_selectable(cat, forced_ids), **meta}

    if not enterprise_mod_filter_active():
        return _finish(catalog)

    sid = session_id_from_request(request)
    if not sid:
        return _finish(catalog)

    await sync_entitlements_from_request(request)
    meta["enterprise_filter_applied"] = True

    if is_admin_account_session():
        return _finish(catalog)

    entitled = get_cached_entitled_client_mod_ids() or set()
    filtered = filter_onboarding_catalog_for_entitlements(catalog, entitled)
    return _finish(filtered)


def build_onboarding_industry_catalog() -> dict[str, Any]:
    doc = load_industry_baseline_document()
    open_ids = _dedupe([str(x) for x in (doc.get("onboarding_open_industry_ids") or []) if x])

    presets_doc: dict[str, Any] = {}
    try:
        from app.mod_sdk.host_profile import load_industry_presets_document

        presets_doc = load_industry_presets_document()
    except RECOVERABLE_ERRORS:
        presets_doc = {}
    presets: dict[str, Any] = (
        cast("dict[str, Any]", presets_doc.get("presets"))
        if isinstance(presets_doc.get("presets"), dict)
        else {}
    )

    open_packages = [
        _onboarding_package_row(iid, selectable=True, presets=presets) for iid in open_ids
    ]

    preset_ids = presets_doc.get("preset_ids")
    if not isinstance(preset_ids, list):
        preset_ids = list((presets or {}).keys())
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
    from app.infrastructure.auth.dependencies import resolve_session_user, session_id_from_request

    entitled: set[str] | None = None
    skip_account_custom = False
    account_username = ""

    user = resolve_session_user(request)
    if user is not None:
        if isinstance(user, dict):
            account_username = str(user.get("username") or "").strip()
        else:
            account_username = str(getattr(user, "username", "") or "").strip()

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
        account_username=account_username,
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
