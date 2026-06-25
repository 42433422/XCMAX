"""客户交付清单：行业包 ↔ 账号定制 Mod（legacy id）映射。"""

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
def load_customer_delivery_document() -> dict[str, Any]:
    cfg = resolve_fhd_config_dir()
    if cfg:
        doc = _load_json(cfg / "customer_delivery.json")
        if doc and isinstance(doc.get("deliveries"), list):
            return cast("dict[str, Any]", doc)
    return {"schema_version": 1, "deliveries": []}


def deliveries_for_industry(industry_id: str) -> list[dict[str, Any]]:
    iid = str(industry_id or "").strip()
    if not iid:
        return []
    out: list[dict[str, Any]] = []
    for row in load_customer_delivery_document().get("deliveries") or []:
        if not isinstance(row, dict):
            continue
        if str(row.get("industry_id") or "").strip() == iid:
            out.append(dict(row))
    return out


def list_customer_deliveries() -> list[dict[str, Any]]:
    """全部客户交付清单（每行含 ``industry_mod_id`` / ``customer_brand`` 等）。"""
    out: list[dict[str, Any]] = []
    for row in load_customer_delivery_document().get("deliveries") or []:
        if isinstance(row, dict):
            out.append(dict(row))
    return out


def delivery_for_industry_mod(industry_mod_id: str) -> dict[str, Any] | None:
    """按 canonical ``industry_mod_id``（如 ``attendance-industry``）查单条交付清单。"""
    mid = str(industry_mod_id or "").strip()
    if not mid:
        return None
    for row in list_customer_deliveries():
        if str(row.get("industry_mod_id") or "").strip() == mid:
            return row
    return None


def delivery_for_account_custom_mod(
    mod_id: str,
    industry_id: str | None = None,
) -> dict[str, Any] | None:
    """按账号定制 ``legacy_mod_id`` 查客户交付清单。"""
    mid = str(mod_id or "").strip()
    iid = str(industry_id or "").strip()
    if not mid:
        return None
    rows = deliveries_for_industry(iid) if iid else list_customer_deliveries()
    for row in rows:
        if str(row.get("legacy_mod_id") or "").strip() == mid:
            return row
    return None


def delivery_seed_package_for_mod(
    mod_id: str,
    industry_id: str | None = None,
) -> dict[str, Any] | None:
    """返回账号定制 Mod 绑定的客户交付种子包元数据。"""
    row = delivery_for_account_custom_mod(mod_id, industry_id)
    if not row:
        return None
    pkg = row.get("delivery_seed_package")
    return dict(pkg) if isinstance(pkg, dict) and str(pkg.get("pkg_id") or "").strip() else None


def _entitled_matches_mod(mod_id: str, entitled: set[str]) -> bool:
    mid = str(mod_id or "").strip()
    if not mid or not entitled:
        return False
    return mid in entitled


def account_custom_mod_ids_for_industry(
    industry_id: str,
    entitled: set[str] | None,
) -> list[str]:
    """当前行业下、账号已 entitlement 的客户定制 Mod（legacy_mod_id）。"""
    entitled_set = {str(x).strip() for x in (entitled or set()) if str(x).strip()}
    if not entitled_set:
        return []

    seen: set[str] = set()
    out: list[str] = []
    for row in deliveries_for_industry(industry_id):
        legacy = str(row.get("legacy_mod_id") or "").strip()
        if not legacy or legacy in seen:
            continue
        if not _entitled_matches_mod(legacy, entitled_set):
            continue
        seen.add(legacy)
        out.append(legacy)
    return out


def label_for_account_custom_mod(mod_id: str, industry_id: str) -> str:
    mid = str(mod_id or "").strip()
    iid = str(industry_id or "").strip()
    for row in deliveries_for_industry(iid):
        if str(row.get("legacy_mod_id") or "").strip() == mid:
            brand = str(row.get("customer_brand") or row.get("customer_name") or "").strip()
            if brand:
                return brand
    return mid


__all__ = [
    "account_custom_mod_ids_for_industry",
    "delivery_for_account_custom_mod",
    "deliveries_for_industry",
    "delivery_for_industry_mod",
    "delivery_seed_package_for_mod",
    "label_for_account_custom_mod",
    "list_customer_deliveries",
    "load_customer_delivery_document",
]
