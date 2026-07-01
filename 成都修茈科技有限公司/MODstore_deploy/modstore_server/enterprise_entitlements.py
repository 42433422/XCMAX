"""Enterprise desktop entitlement helpers."""

from __future__ import annotations

ENTERPRISE_ASSIGNABLE_MODS: dict[str, str] = {
    "attendance-industry": "考勤行业包",
    "coating-industry": "涂料行业包",
    "taiyangniao-pro": "太阳鸟 PRO",
    "sz-qsm-pro": "深圳国商茂 PRO",
}


def enterprise_assignable_mod_ids() -> frozenset[str]:
    return frozenset(ENTERPRISE_ASSIGNABLE_MODS.keys())


def assert_enterprise_assignable_mod_id(mod_id: str) -> str:
    mid = (mod_id or "").strip()
    if not mid:
        raise ValueError("mod_id 无效")
    allowed = enterprise_assignable_mod_ids()
    if mid not in allowed:
        raise ValueError(f"mod_id 不在可分配客户 Mod 列表内（允许: {', '.join(sorted(allowed))}）")
    return mid


def normalize_enterprise_entitlement_mod_ids(
    mod_ids: list[str] | tuple[str, ...] | None,
) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    for raw in mod_ids or []:
        mid = assert_enterprise_assignable_mod_id(str(raw or ""))
        if mid in seen:
            continue
        seen.add(mid)
        out.append(mid)
    return out
