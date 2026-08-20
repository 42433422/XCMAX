"""Catalog promotion and baseline-plan assembly for industry onboarding."""

from __future__ import annotations

from typing import Any, cast


def ensure_industries_selectable(catalog: dict[str, Any], industry_ids: set[str]) -> dict[str, Any]:
    """Promote account/workspace industries into selectable catalog rows."""
    from app.mod_sdk import industry_baseline as facade

    wanted = {str(value).strip() for value in industry_ids if str(value or "").strip()}
    if not wanted:
        return catalog
    open_packages = [
        dict(package)
        for package in (catalog.get("open_packages") or [])
        if isinstance(package, dict)
    ]
    open_ids = {
        str(package.get("industry_id") or "").strip()
        for package in open_packages
        if str(package.get("industry_id") or "").strip()
    }
    presets_doc: dict[str, Any] = {}
    try:
        from app.mod_sdk.host_profile import load_industry_presets_document

        presets_doc = load_industry_presets_document()
    except facade.RECOVERABLE_ERRORS:
        presets_doc = {}
    presets = (
        cast("dict[str, Any]", presets_doc.get("presets"))
        if isinstance(presets_doc.get("presets"), dict)
        else {}
    )
    preview_packages: list[Any] = []
    for package in catalog.get("preview_packages") or []:
        industry_id = (
            str(package.get("industry_id") or "").strip() if isinstance(package, dict) else ""
        )
        if industry_id and industry_id in wanted and industry_id not in open_ids:
            row = dict(package)
            row["selectable"] = True
            open_packages.append(row)
            open_ids.add(industry_id)
        else:
            preview_packages.append(package)
    for industry_id in wanted:
        if industry_id not in open_ids:
            open_packages.append(
                facade._onboarding_package_row(industry_id, selectable=True, presets=presets)
            )
            open_ids.add(industry_id)
    result = dict(catalog)
    result["open_packages"] = open_packages
    result["preview_packages"] = preview_packages
    result["open_industry_ids"] = [
        str(package.get("industry_id") or "").strip()
        for package in open_packages
        if isinstance(package, dict) and str(package.get("industry_id") or "").strip()
    ]
    return result


def build_industry_baseline_plan(
    industry_id: str,
    installed_mod_ids: list[str] | None = None,
    *,
    entitled_mod_ids: set[str] | None = None,
    skip_account_custom_gate: bool = False,
) -> dict[str, Any]:
    """Assemble installation readiness for one industry and account."""
    from app.mod_sdk import industry_baseline as facade

    document = facade.load_industry_baseline_document()
    labels = {
        str(key): str(value) for key, value in (document.get("mod_labels") or {}).items() if key
    }
    core_ids = facade._dedupe(
        [str(value) for value in (document.get("core_mod_ids") or []) if value]
    )
    row = facade._industry_row(industry_id)
    industry_key = str(industry_id or "").strip() or "通用"
    required_ids = facade._dedupe(
        core_ids + [str(value) for value in (row.get("host_mod_ids") or []) if value]
    )
    optional_ids = facade._dedupe(
        [
            str(value).strip()
            for value in (row.get("optional_host_mod_ids") or [])
            if str(value or "").strip() and str(value).strip() not in required_ids
        ]
    )
    industry_mod_ids = facade._industry_mod_ids_for(industry_key, row)
    installed = set(facade._installed_mod_ids() if installed_mod_ids is None else installed_mod_ids)

    def item(
        mod_id: str,
        tier: str,
        required: bool,
        *,
        show_mod_id: bool | None = None,
        label: str | None = None,
    ) -> dict[str, Any]:
        visible_id = (
            tier in ("core", "host", "optional", "account_custom")
            if show_mod_id is None
            else show_mod_id
        )
        resolved_label = label
        if not resolved_label:
            if tier == "account_custom":
                from app.mod_sdk.customer_delivery import label_for_account_custom_mod

                resolved_label = label_for_account_custom_mod(mod_id, industry_key)
            elif tier == "custom":
                resolved_label = facade._label_for_custom_mod(mod_id, industry_key, labels)
            else:
                resolved_label = facade._label_for_mod(mod_id, industry_key, labels)
        return {
            "mod_id": mod_id,
            "label": resolved_label,
            "tier": tier,
            "required": required,
            "installed": facade._mod_installed(mod_id, installed),
            "show_mod_id": visible_id,
        }

    custom_hint, _ = facade._custom_line_spec(industry_mod_ids[0] if industry_mod_ids else "")
    from app.mod_sdk.customer_delivery import account_custom_mod_ids_for_industry

    account_custom_base = account_custom_mod_ids_for_industry(industry_key, entitled_mod_ids)
    employee_extension_ids = (
        facade._custom_employee_extension_ids(industry_key, row, document)
        if account_custom_base
        else []
    )
    account_custom_ids = facade._dedupe(account_custom_base + employee_extension_ids)
    custom_mod_ids = facade._dedupe(industry_mod_ids + account_custom_ids)
    groups: list[dict[str, Any]] = [
        {
            "id": "core",
            "title": "侧栏对话底座",
            "hint": "干净起步：侧栏挂上智能对话与智能生态入口（宿主桥接，非员工数据）",
            "items": [item(mod_id, "core", True) for mod_id in core_ids],
        },
        {
            "id": "host",
            "title": "行业侧栏基础线",
            "hint": "按行业补侧栏业务菜单与表格工具等宿主能力卡片（不含 AI 员工）",
            "items": [
                item(mod_id, "host", True) for mod_id in required_ids if mod_id not in core_ids
            ],
        },
    ]
    if industry_mod_ids:
        groups.append(
            {
                "id": "industry_package",
                "title": "行业包",
                "hint": custom_hint or "行业通用 Mod：侧栏与业务门面（不含账号定制员工）",
                "items": [
                    item(mod_id, "industry_package", False, show_mod_id=False)
                    for mod_id in industry_mod_ids
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
                    item(mod_id, "account_custom", True, show_mod_id=True)
                    for mod_id in account_custom_ids
                ],
            }
        )
    groups.append(
        {
            "id": "optional",
            "title": "可选增强",
            "hint": "用到再装，不阻塞进入对话",
            "items": [item(mod_id, "optional", False) for mod_id in optional_ids],
        }
    )
    groups = [group for group in groups if group.get("items")]
    flat_items = [entry for group in groups for entry in group["items"]]
    missing_required = [
        entry["mod_id"] for entry in flat_items if entry["required"] and not entry["installed"]
    ]
    missing_optional = [
        entry["mod_id"] for entry in flat_items if not entry["required"] and not entry["installed"]
    ]
    missing_industry = [
        entry["mod_id"]
        for entry in flat_items
        if entry["tier"] in ("industry_package", "custom") and not entry["installed"]
    ]
    missing_account_custom = [
        entry["mod_id"]
        for entry in flat_items
        if entry["tier"] == "account_custom" and entry["required"] and not entry["installed"]
    ]
    seed_packages: list[dict[str, Any]] = []
    if account_custom_ids:
        from app.mod_sdk.customer_delivery import delivery_seed_package_for_mod

        for mod_id in account_custom_ids:
            package = delivery_seed_package_for_mod(mod_id, industry_key)
            if not package:
                continue
            seed_packages.append({"mod_id": mod_id, **package})
            for entry in flat_items:
                if entry.get("mod_id") == mod_id:
                    entry["delivery_seed_package"] = dict(package)

    host_ready = not missing_required
    industry_ready = not missing_industry
    account_ready = skip_account_custom_gate or not missing_account_custom
    industry_package = None
    package = facade._industry_package(industry_key)
    if package.get("mod_id"):
        industry_package = {
            "mod_id": str(package.get("mod_id") or "").strip(),
            "product_name": str(package.get("product_name") or "").strip(),
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
        "account_delivery_seed_packages": seed_packages,
        "host_baseline_ready": host_ready,
        "account_custom_ready": account_ready,
        "custom_employee_extension_mod_ids": employee_extension_ids,
        "baseline_ready": host_ready,
        "full_stack_ready": host_ready and account_ready and industry_ready,
        "industry_mod_ready": industry_ready,
    }
