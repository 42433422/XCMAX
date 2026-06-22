# CI SSOT: generated from FHD/config/duty_roster.json + mods/_employees/*/manifest.json — DO NOT EDIT BY HAND
"""远端 Catalog 行是否应对 XCAGI 商店展示（与 AI 市场 /api/market/catalog 对齐）。"""

from __future__ import annotations

from typing import Any

from app.mod_sdk.duty_roster import all_planned_duty_employee_ids

# 编制内全部岗位 ID（运行时从 FHD/config/duty_roster.json 派生，不再硬编码）
_PLANNED_DUTY_EMPLOYEE_IDS: frozenset[str] = all_planned_duty_employee_ids()


def is_internal_duty_catalog_id(pkg_id: str) -> bool:
    pid = str(pkg_id or "").strip()
    return bool(pid) and pid in _PLANNED_DUTY_EMPLOYEE_IDS


def is_planned_duty_employee_pack(pkg_id: str, artifact: str | None) -> bool:
    if is_internal_duty_catalog_id(pkg_id):
        return True
    if str(artifact or "").strip().lower() != "employee_pack":
        return False
    return is_internal_duty_catalog_id(pkg_id)


def is_public_catalog_row(row: dict[str, Any]) -> bool:
    """过滤：编制内岗、草稿、无下载地址、未上架 employee_pack。"""
    if not isinstance(row, dict):
        return False
    pid = str(row.get("id") or row.get("pkg_id") or "").strip()
    if not pid:
        return False
    ver = str(row.get("version") or "").strip()
    artifact = str(row.get("artifact") or "mod").strip().lower()

    if is_internal_duty_catalog_id(pid):
        return False

    if row.get("public_listing") is False:
        return False

    channel = str(row.get("release_channel") or "stable").strip().lower()
    if channel == "draft" or ver.startswith("draft-"):
        return False

    stored = bool(str(row.get("stored_filename") or "").strip())
    download_url = bool(str(row.get("download_url") or "").strip())
    if not stored and not download_url:
        return False

    if row.get("public_listing") is True:
        return True
    if artifact == "employee_pack":
        return False
    return True
