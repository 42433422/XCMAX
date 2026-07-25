"""打单意图 → 模版库选模版（打通 ingest 与 generate 断点）。

优先级：
1. 显式 ``template_id``（db:/fs:/shipment …）
2. 显式 ``template_name``（已是路径 / 文件名则原样；否则按名称在库中匹配）
3. 按意图默认类型从 TemplateStore 取最新可用模版
4. 回退 None（交 legacy DEFAULT_TEMPLATE）
"""

from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Any

from app.utils.operational_errors import RECOVERABLE_ERRORS

logger = logging.getLogger(__name__)

# 意图 / 业务用途 → 模版类型候选（按优先级）
_INTENT_TEMPLATE_TYPES: dict[str, tuple[str, ...]] = {
    "shipment_generate": ("发货单", "出货明细", "出货记录", "Excel"),
    "shipment": ("发货单", "出货明细", "出货记录", "Excel"),
    "delivery": ("发货单", "出货明细", "Excel"),
    "orders": ("出货明细", "发货单", "Excel"),
}

_SHIPMENT_NAME_HINTS = ("发货", "送货", "出货", "shipment", "delivery")


def _get_template_store():
    try:
        from app.bootstrap import get_template_app_service

        svc = get_template_app_service()
        store = getattr(svc, "_template_service", None)
        if store is not None:
            return store
    except RECOVERABLE_ERRORS:
        pass
    from app.infrastructure.templates.template_store_impl import FileSystemTemplateStore
    from app.utils.path_utils import get_base_dir

    return FileSystemTemplateStore(base_dir=get_base_dir())


def _score_template(row: dict[str, Any], *, preferred_types: tuple[str, ...]) -> int:
    if not row.get("path") or not os.path.exists(str(row.get("path") or "")):
        return -1
    score = 0
    ttype = str(row.get("template_type") or "").strip()
    name = str(row.get("name") or row.get("filename") or "").lower()
    if ttype in preferred_types:
        score += 100 - preferred_types.index(ttype) * 10
    if any(h in name for h in _SHIPMENT_NAME_HINTS):
        score += 30
    if str(row.get("source") or "") == "db":
        score += 20
    score += min(int(row.get("db_id") or 0), 50)
    return score


def resolve_shipment_template(
    *,
    template_id: str | None = None,
    template_name: str | None = None,
    intent: str = "shipment_generate",
) -> dict[str, Any]:
    """解析打单应使用的模版文件。

    Returns:
        ``{ok, path, template_id, template_name, template_type, source, reason}``
    """
    tid = str(template_id or "").strip()
    tname = str(template_name or "").strip()
    intent_key = str(intent or "shipment_generate").strip() or "shipment_generate"
    preferred = _INTENT_TEMPLATE_TYPES.get(intent_key, _INTENT_TEMPLATE_TYPES["shipment_generate"])

    try:
        store = _get_template_store()
    except RECOVERABLE_ERRORS as exc:
        logger.warning("模版库不可用，打单回退 legacy: %s", exc)
        return {
            "ok": False,
            "path": tname or None,
            "template_id": tid or None,
            "template_name": tname or None,
            "reason": "store_unavailable",
        }

    # 1) template_id
    if tid:
        path = store.resolve_template_file(tid)
        if path and os.path.isfile(path):
            return {
                "ok": True,
                "path": path,
                "template_id": tid,
                "template_name": Path(path).name,
                "source": "template_id",
                "reason": "resolved_by_id",
            }

    # 2) 显式路径 / 文件名
    if tname:
        as_path = Path(tname).expanduser()
        if as_path.is_file():
            return {
                "ok": True,
                "path": str(as_path.resolve()),
                "template_id": tid or None,
                "template_name": as_path.name,
                "source": "explicit_path",
                "reason": "resolved_by_path",
            }
        # 名称匹配库内条目
        try:
            rows = store.list_templates() or []
        except RECOVERABLE_ERRORS:
            rows = []
        needle = tname.lower()
        for row in rows:
            name = str(row.get("name") or "").lower()
            filename = str(row.get("filename") or "").lower()
            if needle in {name, filename} or needle == str(row.get("id") or "").lower():
                path = str(row.get("path") or "")
                if path and os.path.isfile(path):
                    return {
                        "ok": True,
                        "path": path,
                        "template_id": str(row.get("id") or ""),
                        "template_name": row.get("name") or Path(path).name,
                        "template_type": row.get("template_type"),
                        "source": row.get("source") or "name_match",
                        "reason": "resolved_by_name",
                    }
        # 交给 legacy 按文件名搜索
        return {
            "ok": True,
            "path": tname,
            "template_id": tid or None,
            "template_name": tname,
            "source": "legacy_name",
            "reason": "passthrough_filename",
        }

    # 3) 意图默认：按候选类型 + 名称启发打分
    try:
        rows = store.list_templates() or []
    except RECOVERABLE_ERRORS:
        rows = []

    best: dict[str, Any] | None = None
    best_score = -1
    for row in rows:
        score = _score_template(row, preferred_types=preferred)
        if score > best_score:
            best_score = score
            best = row

    if best and best_score >= 0:
        path = str(best.get("path") or "")
        return {
            "ok": True,
            "path": path,
            "template_id": str(best.get("id") or ""),
            "template_name": best.get("name") or Path(path).name,
            "template_type": best.get("template_type"),
            "source": best.get("source") or "intent_default",
            "reason": f"intent_default:{intent_key}",
            "score": best_score,
        }

    # 4) TemplateStore 官方默认（仅精确类型）
    for ttype in preferred:
        try:
            row = store.get_default_for_type(ttype)
        except RECOVERABLE_ERRORS:
            row = None
        if row and row.get("path") and os.path.isfile(str(row["path"])):
            return {
                "ok": True,
                "path": str(row["path"]),
                "template_id": str(row.get("id") or ""),
                "template_name": row.get("name") or Path(str(row["path"])).name,
                "template_type": row.get("template_type") or ttype,
                "source": row.get("source") or "store_default",
                "reason": f"store_default:{ttype}",
            }

    return {
        "ok": False,
        "path": None,
        "template_id": None,
        "template_name": None,
        "reason": "no_template_found",
    }


def resolve_products_for_unit(unit_name: str, *, limit: int = 1) -> list[dict[str, Any]]:
    """打单缺产品明细时，用该客户最近出货记录明细兜底。"""
    name = str(unit_name or "").strip()
    if not name:
        return []
    try:
        from app.bootstrap import get_shipment_app_service

        svc = get_shipment_app_service()
        # 优先专用 API；无则从订单列表取最近一条
        getter = getattr(svc, "get_latest_products_for_unit", None)
        if callable(getter):
            rows = getter(name, limit=limit)
            if isinstance(rows, list) and rows:
                return list(rows)
        orders = svc.get_orders(20) or []
        for order in orders:
            if not isinstance(order, dict):
                continue
            customer = str(
                order.get("customer_name")
                or order.get("unit_name")
                or order.get("purchase_unit")
                or ""
            ).strip()
            if customer and (customer == name or name in customer or customer in name):
                items = order.get("products") or order.get("items") or []
                if isinstance(items, list) and items:
                    return list(items)
    except RECOVERABLE_ERRORS as exc:
        logger.debug("resolve_products_for_unit failed: %s", exc, exc_info=True)
    return []
