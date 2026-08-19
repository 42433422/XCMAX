"""Map industry manifest subsystems → onboarding demo ORM payloads."""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from decimal import Decimal
from pathlib import Path
from typing import Any

from app.mod_sdk.industry_seed import industry_mod_id_for

_DEMO_PREFIX = "XC 演示"
_FALLBACK_CUSTOMER = f"{_DEMO_PREFIX}客户"
_FALLBACK_PRODUCT = f"{_DEMO_PREFIX}产品"

_SEMANTIC_DEFAULTS: dict[str, Any] = {
    "entity_name": lambda ctx: f"{_DEMO_PREFIX}{ctx.get('entity', '记录')}",
    "model": "DEMO-001",
    "spec": "标准",
    "price": Decimal("99.00"),
    "primary_qty": 1,
    "secondary_qty": 8,
    "foreign_ref": lambda ctx: ctx.get("customer_demo_name") or _FALLBACK_CUSTOMER,
    "batch": "BATCH-001",
    "expiry": None,
    "derived": Decimal("99.00"),
}


@dataclass
class OnboardingSeedProfile:
    industry_id: str
    mod_id: str | None = None
    customer_entity: str = "客户"
    product_entity: str = "产品"
    demo_customer_name: str = _FALLBACK_CUSTOMER
    demo_product_name: str = _FALLBACK_PRODUCT
    customer_query_hint: str = _FALLBACK_CUSTOMER
    subsystems_meta: dict[str, dict[str, str]] = field(default_factory=dict)


def _fhd_mods_root() -> Path:
    override = (os.environ.get("XCAGI_MODS_ROOT") or "").strip()
    if override:
        return Path(override)
    return Path(__file__).resolve().parents[2] / "mods"


def _resolve_mod_manifest_root(mod_id: str) -> Path | None:
    """先查 FHD/mods（编辑源 SSOT），fallback 到 FHD/XCAGI/mods（导出副本）。

    与 app/infrastructure/mods/mod_manager.py 双份 mods 查找一致；
    attendance-industry 等已迁移至 XCAGI/mods/ 的包由此 fallback 找到。
    """
    fhd_root = Path(__file__).resolve().parents[2]
    for candidate in (fhd_root / "mods", fhd_root / "XCAGI" / "mods"):
        if (candidate / mod_id / "manifest.json").is_file():
            return candidate
    return None


def load_industry_manifest(industry_id: str) -> dict[str, Any] | None:
    mod_id = industry_mod_id_for(industry_id)
    if not mod_id:
        return None
    mods_root = _resolve_mod_manifest_root(mod_id) or _fhd_mods_root()
    manifest_path = mods_root / mod_id / "manifest.json"
    if not manifest_path.is_file():
        return None
    try:
        data = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return data if isinstance(data, dict) else None


def resolve_onboarding_seed_profile(industry_id: str) -> OnboardingSeedProfile:
    iid = str(industry_id or "通用").strip() or "通用"
    manifest = load_industry_manifest(iid)
    mod_id = industry_mod_id_for(iid)
    profile = OnboardingSeedProfile(industry_id=iid, mod_id=mod_id)

    if not manifest:
        return profile

    industry = manifest.get("industry") if isinstance(manifest.get("industry"), dict) else {}
    if not isinstance(industry, dict):
        industry = {}
    subsystems = industry.get("subsystems") if isinstance(industry.get("subsystems"), dict) else {}

    if not isinstance(subsystems, dict):
        subsystems = {}
    customers = subsystems.get("customers") if isinstance(subsystems.get("customers"), dict) else {}
    products = subsystems.get("products") if isinstance(subsystems.get("products"), dict) else {}

    if customers:
        profile.customer_entity = str(customers.get("entity") or "客户")
        profile.demo_customer_name = f"{_DEMO_PREFIX}{profile.customer_entity}"
        profile.subsystems_meta["customers"] = {
            "entity": profile.customer_entity,
            "label": str(customers.get("label") or profile.customer_entity),
        }
    if products:
        profile.product_entity = str(products.get("entity") or "产品")
        profile.demo_product_name = f"{_DEMO_PREFIX}{profile.product_entity}"
        profile.subsystems_meta["products"] = {
            "entity": profile.product_entity,
            "label": str(products.get("label") or profile.product_entity),
        }

    profile.customer_query_hint = profile.demo_customer_name
    return profile


def _demo_value_for_field(field: dict[str, Any], *, ctx: dict[str, Any]) -> Any:
    semantic = str(field.get("semantic") or "").strip()
    ftype = str(field.get("type") or "text").strip()
    key = str(field.get("key") or "").strip()

    if semantic in _SEMANTIC_DEFAULTS:
        val = _SEMANTIC_DEFAULTS[semantic]
        return val(ctx) if callable(val) else val

    if ftype == "number":
        return Decimal("1")
    if ftype == "enum":
        validators = field.get("validators") or []
        for v in validators:
            if isinstance(v, dict) and v.get("type") == "oneOf":
                params = v.get("params") or []
                if params:
                    return str(params[0])
        return "选项A"
    if key == "contact_phone":
        return "13800000000"
    if key == "contact_person":
        return "演示联系人"
    if key in ("address", "contact_address"):
        return f"{ctx.get('industry_id', '通用')} · 首启演示地址"
    if key == "unit":
        return "个"
    return f"演示{field.get('label') or key or '值'}"


def build_customer_row(*, tenant_id: int, profile: OnboardingSeedProfile) -> dict[str, Any]:
    manifest = load_industry_manifest(profile.industry_id)
    subsystems = (
        (manifest or {}).get("industry", {}).get("subsystems", {})
        if isinstance((manifest or {}).get("industry"), dict)
        else {}
    )
    schema = subsystems.get("customers") if isinstance(subsystems.get("customers"), dict) else {}
    if not isinstance(schema, dict):
        schema = {}
    fields = schema.get("fields") if isinstance(schema.get("fields"), list) else []

    row: dict[str, Any] = {"tenant_id": tenant_id}
    ctx = {"industry_id": profile.industry_id, "entity": profile.customer_entity}

    if fields:
        mapped: dict[str, Any] = {}
        for f in fields:
            if not isinstance(f, dict):
                continue
            key = str(f.get("key") or "").strip()
            if not key:
                continue
            mapped[key] = _demo_value_for_field(f, ctx=ctx)
        if "customer_name" in mapped:
            mapped["customer_name"] = profile.demo_customer_name
        row.update(
            {
                "customer_name": mapped.get("customer_name") or profile.demo_customer_name,
                "contact_person": mapped.get("contact_person", "演示联系人"),
                "contact_phone": mapped.get("contact_phone", "13800000000"),
                "contact_address": mapped.get("address")
                or mapped.get("contact_address")
                or f"{profile.industry_id} · 首启演示地址",
            }
        )
    else:
        row.update(
            {
                "customer_name": profile.demo_customer_name,
                "contact_person": "演示联系人",
                "contact_phone": "13800000000",
                "contact_address": f"{profile.industry_id} · 首启演示地址",
            }
        )
    return row


def build_product_row(*, tenant_id: int, profile: OnboardingSeedProfile) -> dict[str, Any]:
    manifest = load_industry_manifest(profile.industry_id)
    subsystems = (
        (manifest or {}).get("industry", {}).get("subsystems", {})
        if isinstance((manifest or {}).get("industry"), dict)
        else {}
    )
    schema = subsystems.get("products") if isinstance(subsystems.get("products"), dict) else {}
    if not isinstance(schema, dict):
        schema = {}
    fields = schema.get("fields") if isinstance(schema.get("fields"), list) else []

    ctx = {
        "industry_id": profile.industry_id,
        "entity": profile.product_entity,
        "customer_demo_name": profile.demo_customer_name,
    }

    mapped: dict[str, Any] = {}
    for f in fields or []:
        if not isinstance(f, dict):
            continue
        key = str(f.get("key") or "").strip()
        if not key:
            continue
        mapped[key] = _demo_value_for_field(f, ctx=ctx)

    name = profile.demo_product_name
    if mapped.get("name"):
        name = profile.demo_product_name

    return {
        "tenant_id": tenant_id,
        "name": name,
        "model_number": str(mapped.get("model_number") or "DEMO-001"),
        "specification": str(mapped.get("specification") or f"{profile.industry_id} 首启样例 SKU"),
        "price": mapped.get("price")
        if isinstance(mapped.get("price"), Decimal)
        else Decimal("99.00"),
        "quantity": int(mapped.get("quantity") or 10),
        "category": profile.industry_id,
        "brand": "XCAGI",
        "unit": str(mapped.get("unit") or "个"),
        "is_active": 1,
    }


__all__ = [
    "OnboardingSeedProfile",
    "build_customer_row",
    "build_product_row",
    "load_industry_manifest",
    "resolve_onboarding_seed_profile",
]
