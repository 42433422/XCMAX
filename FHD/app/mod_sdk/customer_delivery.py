"""客户交付清单 SSOT 加载器。

真相源：``config/customer_delivery.json``（``docs/SSOT_INDEX.md`` · customer-delivery）。

字段分工：
- ``industry_id`` / ``industry_mod_id``：客户所属行业及行业包——不进生产员工私有交付
- ``legacy_mod_id``：客户定制权益与进度身份；integrated_feature 不要求独立运行包
- ``runtime_mod_id``：当前实际运行包（太阳鸟为 attendance-industry）
- ``tracks.modules[]`` / ``tracks.employees[]``：双轨节点；节点各自有制作进度
  （例：太阳鸟「考勤表转化」= 模块轨节点）
"""

from __future__ import annotations

from functools import lru_cache
from typing import Any, cast

from app.mod_sdk.host_profile import resolve_fhd_config_dir
from app.utils.operational_errors import RECOVERABLE_ERRORS

TRACK_MODULES = "modules"
TRACK_EMPLOYEES = "employees"
# 历史状态文件曾用 business 作为模块轨键
TRACK_MODULES_LEGACY = "business"
CANONICAL_TRACKS = (TRACK_MODULES, TRACK_EMPLOYEES)


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


def delivery_model() -> dict[str, Any]:
    """双轨模型元数据（轨道定义 / 规则 / 阶段）。"""
    raw = load_customer_delivery_document().get("delivery_model")
    return dict(raw) if isinstance(raw, dict) else {}


def _is_unified_industry_delivery(row: dict[str, Any]) -> bool:
    return str(row.get("delivery_mode") or "").strip() == "unified_industry"


def normalize_track_id(track: str) -> str:
    """把历史 ``business`` 归一为 ``modules``。"""
    tid = str(track or "").strip()
    if tid == TRACK_MODULES_LEGACY:
        return TRACK_MODULES
    return tid


def track_nodes_for_custom_mod(mod_id: str) -> dict[str, list[dict[str, Any]]]:
    """返回定制 Mod 在 SSOT 中声明的双轨节点；无声明则空列表（调用方可回退 manifest）。"""
    row = delivery_for_account_custom_mod(mod_id)
    empty: dict[str, list[dict[str, Any]]] = {TRACK_MODULES: [], TRACK_EMPLOYEES: []}
    if not row:
        return empty
    tracks = row.get("tracks")
    if not isinstance(tracks, dict):
        return empty
    out: dict[str, list[dict[str, Any]]] = {TRACK_MODULES: [], TRACK_EMPLOYEES: []}
    for track in CANONICAL_TRACKS:
        raw_nodes = tracks.get(track)
        if track == TRACK_MODULES and not isinstance(raw_nodes, list):
            raw_nodes = tracks.get(TRACK_MODULES_LEGACY)
        if not isinstance(raw_nodes, list):
            continue
        for item in raw_nodes:
            if not isinstance(item, dict):
                continue
            nid = str(item.get("id") or "").strip()
            label = str(item.get("label") or nid).strip()
            if not nid or not label:
                continue
            out[track].append(
                {
                    "id": nid,
                    "label": label,
                    "summary": str(item.get("summary") or "").strip(),
                }
            )
    return out


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


def delivery_for_account(account_username: str) -> dict[str, Any] | None:
    """按企业账号查客户交付 SSOT；匹配不区分大小写。"""
    username = str(account_username or "").strip().casefold()
    if not username:
        return None
    for row in list_customer_deliveries():
        account = str(row.get("customer_account") or "").strip().casefold()
        if account and account == username:
            return row
    return None


def industry_id_for_account(account_username: str) -> str:
    """返回交付 SSOT 固定的客户行业，覆盖旧库里错误/过时的行业值。"""
    row = delivery_for_account(account_username)
    return str(row.get("industry_id") or "").strip() if row else ""


def delivery_for_industry_mod(industry_mod_id: str) -> dict[str, Any] | None:
    """按行业包或归并后的运行模块查单条交付清单。"""
    mid = str(industry_mod_id or "").strip()
    if not mid:
        return None
    for row in list_customer_deliveries():
        configured = str(row.get("industry_mod_id") or "").strip()
        runtime = str(row.get("runtime_mod_id") or "").strip()
        if mid in {configured, runtime}:
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
    if iid and not rows:
        row = delivery_for_industry_mod(iid)
        rows = [row] if row else []
    if iid and not rows:
        try:
            from app.mod_sdk.industry_mod_aliases import canonical_mod_id

            canonical = canonical_mod_id(iid)
            row = delivery_for_industry_mod(canonical)
            rows = [row] if row else []
        except RECOVERABLE_ERRORS:
            rows = []
    for row in rows:
        if str(row.get("legacy_mod_id") or "").strip() == mid:
            return row
    return None


def delivery_for_runtime_mod(
    mod_id: str,
    *,
    account_username: str = "",
) -> dict[str, Any] | None:
    """按当前运行 Mod 查账号交付；账号专属行必须同时匹配用户名。"""
    mid = str(mod_id or "").strip()
    username = str(account_username or "").strip().casefold()
    if not mid:
        return None
    for row in list_customer_deliveries():
        runtime_mod_id = str(row.get("runtime_mod_id") or row.get("industry_mod_id") or "").strip()
        if runtime_mod_id != mid:
            continue
        customer_account = str(row.get("customer_account") or "").strip().casefold()
        if customer_account and customer_account != username:
            continue
        return row
    return None


def delivery_seed_package_for_mod(
    mod_id: str,
    industry_id: str | None = None,
    *,
    account_username: str = "",
) -> dict[str, Any] | None:
    """返回当前运行 Mod 绑定的账号交付种子包元数据。"""
    row = delivery_for_account_custom_mod(mod_id, industry_id)
    if row and row.get("delivery_mode") in {"unified_industry", "integrated_feature"}:
        row = None
    if row is None:
        row = delivery_for_runtime_mod(mod_id, account_username=account_username)
    if not row:
        return None
    pkg = row.get("delivery_seed_package")
    return dict(pkg) if isinstance(pkg, dict) and str(pkg.get("pkg_id") or "").strip() else None


def list_account_custom_mod_ids() -> set[str]:
    """客户交付清单中的账号定制 Mod（``legacy_mod_id``），不含通用行业包。"""
    out: set[str] = set()
    for row in list_customer_deliveries():
        if _is_unified_industry_delivery(row):
            continue
        legacy = str(row.get("legacy_mod_id") or "").strip()
        if legacy:
            out.add(legacy)
    return out


def list_industry_mod_ids_from_delivery() -> set[str]:
    """客户交付清单里的行业包与归并后运行模块 id。"""
    out: set[str] = set()
    for row in list_customer_deliveries():
        mid = str(row.get("industry_mod_id") or "").strip()
        if mid:
            out.add(mid)
        runtime_mid = str(row.get("runtime_mod_id") or "").strip()
        if runtime_mid:
            out.add(runtime_mid)
    return out


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
        if _is_unified_industry_delivery(row):
            continue
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
    "CANONICAL_TRACKS",
    "TRACK_EMPLOYEES",
    "TRACK_MODULES",
    "TRACK_MODULES_LEGACY",
    "account_custom_mod_ids_for_industry",
    "delivery_for_account_custom_mod",
    "delivery_for_account",
    "delivery_model",
    "deliveries_for_industry",
    "delivery_for_industry_mod",
    "delivery_for_runtime_mod",
    "delivery_seed_package_for_mod",
    "label_for_account_custom_mod",
    "industry_id_for_account",
    "list_account_custom_mod_ids",
    "list_customer_deliveries",
    "list_industry_mod_ids_from_delivery",
    "load_customer_delivery_document",
    "normalize_track_id",
    "track_nodes_for_custom_mod",
]
