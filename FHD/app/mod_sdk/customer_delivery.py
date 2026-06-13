# -*- coding: utf-8 -*-
"""客户交付清单：行业包 ↔ 账号定制 Mod（legacy id）映射。"""

from __future__ import annotations

from functools import lru_cache
from typing import Any

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
            return doc
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


def _entitled_matches_mod(mod_id: str, entitled: set[str]) -> bool:
    mid = str(mod_id or "").strip()
    if not mid or not entitled:
        return False
    if mid in entitled:
        return True
    try:
        from app.mod_sdk.industry_mod_aliases import canonical_mod_id, legacy_mod_ids_for

        cid = canonical_mod_id(mid)
        if cid in entitled:
            return True
        for leg in legacy_mod_ids_for(cid):
            if leg in entitled:
                return True
        for raw in entitled:
            if canonical_mod_id(raw) == cid:
                return True
    except RECOVERABLE_ERRORS:
        pass
    return False


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
    "deliveries_for_industry",
    "label_for_account_custom_mod",
    "load_customer_delivery_document",
]
