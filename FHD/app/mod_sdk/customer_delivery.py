# -*- coding: utf-8 -*-
"""客户交付清单（合同 / 安装包 metadata）；不含于通用 industry_baseline。"""

from __future__ import annotations

import json
from functools import lru_cache
from typing import Any

from app.mod_sdk.host_profile import resolve_fhd_config_dir
from app.utils.operational_errors import OPERATIONAL_ERRORS


@lru_cache(maxsize=1)
def load_customer_delivery_document() -> dict[str, Any]:
    cfg = resolve_fhd_config_dir()
    if cfg:
        path = cfg / "customer_delivery.json"
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                return data
        except OPERATIONAL_ERRORS:
            pass
    return {"schema_version": 1, "deliveries": []}


def list_customer_deliveries() -> list[dict[str, Any]]:
    doc = load_customer_delivery_document()
    rows = doc.get("deliveries")
    if not isinstance(rows, list):
        return []
    return [r for r in rows if isinstance(r, dict)]


def delivery_for_industry_mod(industry_mod_id: str) -> dict[str, Any] | None:
    mid = str(industry_mod_id or "").strip()
    if not mid:
        return None
    for row in list_customer_deliveries():
        if str(row.get("industry_mod_id") or "").strip() == mid:
            return row
    return None


__all__ = [
    "delivery_for_industry_mod",
    "list_customer_deliveries",
    "load_customer_delivery_document",
]
