"""Deliverable status aggregate for acceptance, onboarding, and support."""

from __future__ import annotations

import os
from typing import Any

from fastapi import FastAPI

from app.mod_sdk.edition_policy import bundled_mods_dir, resolve_edition
from app.mod_sdk.platform_shell import (
    GENERIC_HOST_MOD_IDS,
    MINIMAL_HOST_MOD_IDS,
    build_platform_shell_payload,
)
from app.mod_sdk.product_skus import (
    ENTERPRISE_HOST_MOD_IDS,
    PERSONAL_HOST_MOD_IDS,
    bundled_mod_ids_for_sku,
    resolve_product_sku,
)
from app.runtime_integrity import runtime_integrity_snapshot
from app.utils.operational_errors import RECOVERABLE_ERRORS


def _installed_mod_ids() -> list[str]:
    try:
        from app.infrastructure.mods.mod_manager import get_mod_manager

        mm = get_mod_manager()
        loaded = [m.id for m in (mm.list_loaded_mods() or []) if getattr(m, "id", None)]
        scanned = [m.id for m in mm.scan_mods() if getattr(m, "id", None)]
        if scanned or loaded:
            seen: set[str] = set()
            out: list[str] = []
            for mid in scanned + loaded:
                s = str(mid or "").strip()
                if s and s not in seen:
                    seen.add(s)
                    out.append(s)
            return out
        return []
    except RECOVERABLE_ERRORS:
        return []


def _mods_routes_loaded(app: FastAPI | None = None) -> bool | None:
    """Read mod-route mount state from running FastAPI app; None if no app."""
    if app is not None:
        return bool(getattr(app.state, "mods_routes_loaded", False))
    try:
        from app.fastapi_app.factory import _app_singleton

        if _app_singleton is not None:
            return bool(getattr(_app_singleton.state, "mods_routes_loaded", False))
    except RECOVERABLE_ERRORS:
        pass
    return None


def build_deliverable_status(
    installed_mod_ids: list[str] | None = None,
    *,
    app: FastAPI | None = None,
) -> dict[str, Any]:
    from app.mod_sdk.host_foundation import (
        host_foundation_bridges_ready,
        host_foundation_employee_present,
        try_materialize_host_foundation_if_needed,
    )

    materialize_hint: dict[str, Any] | None = None
    # Auto-expand only on real probe; tests with installed_mod_ids/PYTEST skip disk.
    in_pytest = bool(os.environ.get("PYTEST_CURRENT_TEST") or os.environ.get("PYTEST_VERSION"))
    if (
        not in_pytest
        and installed_mod_ids is None
        and host_foundation_employee_present()
        and not host_foundation_bridges_ready()
    ):
        materialize_hint = try_materialize_host_foundation_if_needed()
        if materialize_hint and materialize_hint.get("ready"):
            installed_mod_ids = None

    installed = list(installed_mod_ids or _installed_mod_ids())
    installed_set = set(installed)
    shell = build_platform_shell_payload(installed)
    edition = shell.get("edition") or resolve_edition()
    product_sku = resolve_product_sku()
    minimal_ready = bool(shell.get("minimal_pack_installed"))
    generic_ready = bool(shell.get("generic_pack_installed"))

    sku_expected = bundled_mod_ids_for_sku()
    if sku_expected:
        expected = list(sku_expected)
    elif product_sku == "personal":
        expected = list(PERSONAL_HOST_MOD_IDS)
    elif product_sku == "enterprise":
        expected = list(ENTERPRISE_HOST_MOD_IDS)
    else:
        expected = list(MINIMAL_HOST_MOD_IDS if edition == "minimal" else GENERIC_HOST_MOD_IDS)
        if edition == "full":
            expected = []

    missing = [mid for mid in expected if mid not in installed_set]
    blockers: list[dict[str, Any]] = []
    pack_ready = not missing

    from app.mod_sdk.host_profile import get_profile_validation_errors

    profile_errors = get_profile_validation_errors(product_sku)
    for err in profile_errors:
        blockers.append(
            {
                "code": "PROFILE_SCHEMA_MISMATCH",
                "message": err,
            }
        )
        pack_ready = False

    if product_sku == "enterprise":
        from app.mod_sdk.erp_domain_compat import ERP_DOMAIN_BRIDGE_MOD_ID

        if ERP_DOMAIN_BRIDGE_MOD_ID not in installed_set:
            blockers.append(
                {
                    "code": "ENTERPRISE_ERP_MISSING",
                    "message": "Enterprise ERP baseline mods not ready",
                    "missing_mod_ids": [ERP_DOMAIN_BRIDGE_MOD_ID],
                }
            )
            pack_ready = False
    elif product_sku == "personal":
        if missing:
            blockers.append(
                {
                    "code": "SKU_PACK_INCOMPLETE",
                    "message": f"{product_sku} SKU bundled mod pack incomplete",
                    "missing_mod_ids": missing,
                }
            )
            pack_ready = False
    elif edition == "generic" and not generic_ready:
        from app.mod_sdk.host_foundation import host_foundation_employee_present

        msg = "general?? Mod ????,?????????? bootstrap-edition-pack"
        if host_foundation_employee_present():
            msg = (
                "Installed host baseline employee pack; "
                "click one-click install to expand internal bridges into local mods."
            )
        blockers.append(
            {
                "code": "GENERIC_PACK_INCOMPLETE",
                "message": msg,
                "missing_mod_ids": missing,
            }
        )
        pack_ready = False
    elif edition == "minimal" and not minimal_ready:
        blockers.append(
            {
                "code": "MINIMAL_PACK_INCOMPLETE",
                "message": "Minimal host mod pack incomplete",
                "missing_mod_ids": missing,
            }
        )
        pack_ready = False

    bundle = bundled_mods_dir()
    bundle_missing = []
    if bundle and expected:
        for mid in expected:
            if not (bundle / mid).is_dir():
                bundle_missing.append(mid)

    mods_routes = _mods_routes_loaded(app)

    runtime_integrity = runtime_integrity_snapshot(app)
    for failure in runtime_integrity["blockers"]:
        blockers.append(
            {
                "code": "RUNTIME_COMPONENT_UNAVAILABLE",
                "message": str(failure.get("detail") or failure.get("component")),
                "component": failure.get("component"),
            }
        )

    if mods_routes is False and expected and installed_mod_ids is None:
        blockers.append(
            {
                "code": "MOD_ROUTES_NOT_MOUNTED",
                "message": "Mod HTTP routes not mounted; restart app",
            }
        )

    if product_sku:
        edition_ready = pack_ready
    else:
        edition_ready = (
            edition == "full"
            or (edition == "generic" and generic_ready)
            or (edition == "minimal" and minimal_ready)
        )
    deliverable = edition_ready and not any(
        b["code"] in ("MOD_ROUTES_NOT_MOUNTED", "RUNTIME_COMPONENT_UNAVAILABLE")
        for b in blockers
    )

    product_flow_step = "daily_use"
    if product_sku == "personal":
        product_flow_step = "industry_mod" if deliverable else "host_pack"
    elif edition == "full" or product_sku == "enterprise":
        product_flow_step = "daily_use" if deliverable else "host_pack"
    elif not edition_ready:
        product_flow_step = "host_pack"
    elif deliverable:
        product_flow_step = "industry_mod"

    host_employee = host_foundation_employee_present()
    host_bridges = host_foundation_bridges_ready()

    return {
        "schema_version": 1,
        "deliverable": deliverable,
        "host_foundation_employee_installed": host_employee,
        "host_foundation_bridges_ready": host_bridges,
        "host_foundation_materialize": materialize_hint,
        "product_flow": {
            "recommended_step": product_flow_step,
            "steps": [
                {"id": "install", "label": "Install host"},
                {"id": "first_launch", "label": "First launch"},
                {"id": "host_pack", "label": "Host pack ready"},
                {"id": "industry_mod", "label": "Industry MOD (optional)"},
                {"id": "daily_use", "label": "Daily use"},
            ],
            "ui_route": "/onboarding",
        },
        "edition": edition,
        "product_sku": product_sku,
        "edition_ready": edition_ready,
        "minimal_pack_installed": minimal_ready,
        "generic_pack_installed": generic_ready,
        "installed_mod_count": len(installed_set),
        "expected_mod_ids": expected,
        "missing_mod_ids": missing,
        "bundled_mods_dir": str(bundle) if bundle else None,
        "bundled_mods_missing": bundle_missing,
        "mods_routes_loaded": bool(mods_routes) if mods_routes is not None else False,
        "platform_shell_mode": shell.get("platform_shell_mode"),
        "blockers": blockers,
        "runtime_integrity": runtime_integrity,
        "next_actions": _next_actions(edition, blockers, deliverable),
        "desktop_mode": (os.environ.get("XCAGI_DESKTOP_MODE") or "").strip().lower()
        in {"1", "true", "yes"},
    }


def _next_actions(
    edition: str,
    blockers: list[dict[str, Any]],
    deliverable: bool,
) -> list[str]:
    if deliverable:
        return ["open_chat", "install_industry_mod_from_store"]
    actions = []
    if any(b.get("code") == "GENERIC_PACK_INCOMPLETE" for b in blockers):
        actions.append("POST /api/mod-store/bootstrap-edition-pack?edition=generic")
        actions.append("open_mod_store")
    if any(b.get("code") == "MINIMAL_PACK_INCOMPLETE" for b in blockers):
        actions.append("POST /api/mod-store/bootstrap-edition-pack?edition=minimal")
        actions.append("open_mod_store")
    if edition == "generic":
        actions.append("verify_bundled_mods_in_installer")
    return actions


__all__ = ["build_deliverable_status"]
