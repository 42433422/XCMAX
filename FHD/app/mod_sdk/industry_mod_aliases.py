# -*- coding: utf-8 -*-
"""行业 Mod 中性 id ↔ 客户 legacy mod id 解析。"""

from __future__ import annotations

import json
from functools import lru_cache
from typing import Any

from app.mod_sdk.host_profile import resolve_fhd_config_dir
from app.utils.operational_errors import RECOVERABLE_ERRORS


def _load_json(path) -> dict[str, Any] | None:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else None
    except RECOVERABLE_ERRORS:
        return None


@lru_cache(maxsize=1)
def load_industry_mod_aliases_document() -> dict[str, Any]:
    cfg = resolve_fhd_config_dir()
    if cfg:
        doc = _load_json(cfg / "industry_mod_aliases.json")
        if doc:
            return doc
    return {
        "schema_version": 1,
        "legacy_to_canonical": {
            "taiyangniao-pro": "attendance-industry",
            "sz-qsm-pro": "coating-industry",
        },
        "industry_to_canonical_mod_id": {
            "考勤": "attendance-industry",
            "涂料": "coating-industry",
        },
    }


def canonical_mod_id(mod_id: str) -> str:
    mid = str(mod_id or "").strip()
    if not mid:
        return ""
    mapping = load_industry_mod_aliases_document().get("legacy_to_canonical") or {}
    return str(mapping.get(mid) or mid).strip()


def legacy_mod_ids_for(canonical_mod_id: str) -> tuple[str, ...]:
    cid = str(canonical_mod_id or "").strip()
    if not cid:
        return ()
    mapping = load_industry_mod_aliases_document().get("legacy_to_canonical") or {}
    out = [str(k) for k, v in mapping.items() if str(v).strip() == cid]
    return tuple(out)


def canonical_mod_id_for_industry(industry_id: str) -> str:
    iid = str(industry_id or "").strip()
    mapping = load_industry_mod_aliases_document().get("industry_to_canonical_mod_id") or {}
    return str(mapping.get(iid) or "").strip()


__all__ = [
    "canonical_mod_id",
    "canonical_mod_id_for_industry",
    "legacy_mod_ids_for",
    "load_industry_mod_aliases_document",
]
