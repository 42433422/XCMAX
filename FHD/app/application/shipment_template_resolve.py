"""打单意图 → 模版库选模版（生产级解析）。

优先级：
1. 显式 ``template_id``（db:/fs:/shipment …）
2. 用户偏好 / 槽位 ``preferred``（id 或名称）
3. 显式 ``template_name``（路径 / 文件名 / 库内名称）
4. 按客户名匹配版式模版（名称含 unit_name）
5. 按意图默认类型打分（布局优先，数据表降权）
6. TemplateStore.get_default_for_type
7. 回退 None（交 legacy DEFAULT_TEMPLATE；strict 时失败）

环境变量：
- ``XCAGI_SHIPMENT_TEMPLATE_STRICT=1``：无可用模版时不回退 legacy
"""

from __future__ import annotations

import logging
import os
import re
import threading
import time
from pathlib import Path
from typing import Any

from app.utils.operational_errors import RECOVERABLE_ERRORS

logger = logging.getLogger(__name__)

_INTENT_TEMPLATE_TYPES: dict[str, tuple[str, ...]] = {
    "shipment_generate": ("发货单", "出货明细", "出货记录", "Excel"),
    "shipment": ("发货单", "出货明细", "出货记录", "Excel"),
    "delivery": ("发货单", "出货明细", "Excel"),
    "orders": ("出货明细", "发货单", "Excel"),
}

_SHIPMENT_NAME_HINTS = ("发货", "送货", "出货", "shipment", "delivery")
_LAYOUT_EXTS = {".xlsx", ".xls", ".xlsm"}
_DATA_SCOPES = frozenset({"products", "materials", "customers", "salesReport"})
_LIST_CACHE_TTL_SEC = 30.0

_list_cache_lock = threading.Lock()
_list_cache: tuple[float, list[dict[str, Any]]] | None = None


def shipment_template_strict_enabled(explicit: bool | None = None) -> bool:
    if explicit is not None:
        return bool(explicit)
    return os.environ.get("XCAGI_SHIPMENT_TEMPLATE_STRICT", "").strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }


def clear_template_list_cache() -> None:
    global _list_cache
    with _list_cache_lock:
        _list_cache = None


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


def _normalize_unit_token(value: str) -> str:
    text = str(value or "").strip().lower()
    if not text:
        return ""
    text = re.sub(r"(有限责任公司|有限公司|公司|家私|家具|商贸|贸易|建材|装饰)", "", text)
    text = re.sub(r"[\s\-_()（）【】\[\]·,，.。/\\]+", "", text)
    return text


def _is_layout_file(path: str) -> bool:
    return Path(path).suffix.lower() in _LAYOUT_EXTS


def _row_active(row: dict[str, Any]) -> bool:
    flag = row.get("is_active", 1)
    return flag not in (0, False, "0", "false", "False")


def _list_templates_cached(store: Any) -> list[dict[str, Any]]:
    global _list_cache
    now = time.monotonic()
    with _list_cache_lock:
        if _list_cache and (now - _list_cache[0]) < _LIST_CACHE_TTL_SEC:
            return list(_list_cache[1])
    try:
        rows = list(store.list_templates() or [])
    except RECOVERABLE_ERRORS:
        rows = []
    with _list_cache_lock:
        _list_cache = (now, rows)
    return list(rows)


def _score_template(
    row: dict[str, Any],
    *,
    preferred_types: tuple[str, ...],
    unit_name: str = "",
) -> int:
    if not _row_active(row):
        return -1
    path = str(row.get("path") or "")
    if not path or not os.path.isfile(path) or not _is_layout_file(path):
        return -1

    score = 0
    ttype = str(row.get("template_type") or "").strip()
    name = str(row.get("name") or row.get("filename") or "").lower()
    scope = str(row.get("business_scope") or "").strip()

    if ttype in preferred_types:
        score += 100 - preferred_types.index(ttype) * 10
    if any(h in name for h in _SHIPMENT_NAME_HINTS):
        score += 30
    if str(row.get("source") or "") == "db":
        score += 20
    if scope in _DATA_SCOPES:
        score -= 40
    if ttype in {"Excel", "PPTX", "PDF"} and "发货" not in preferred_types[:1]:
        score -= 5

    unit_token = _normalize_unit_token(unit_name)
    name_token = _normalize_unit_token(name)
    if unit_token and name_token:
        if unit_token == name_token or unit_token in name_token or name_token in unit_token:
            score += 80

    try:
        score += min(int(row.get("db_id") or 0), 50)
    except (TypeError, ValueError):
        pass
    return score


def _result(
    *,
    ok: bool,
    path: str | None = None,
    template_id: str | None = None,
    template_name: str | None = None,
    template_type: str | None = None,
    source: str | None = None,
    reason: str,
    error_code: str | None = None,
    score: int | None = None,
    unit_name: str | None = None,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "ok": ok,
        "path": path,
        "template_id": template_id,
        "template_name": template_name,
        "template_type": template_type,
        "source": source,
        "reason": reason,
        "error_code": error_code or (None if ok else reason),
    }
    if score is not None:
        payload["score"] = score
    if unit_name:
        payload["unit_name"] = unit_name
    return payload


def _match_row_by_name(rows: list[dict[str, Any]], needle: str) -> dict[str, Any] | None:
    key = needle.lower().strip()
    if not key:
        return None
    for row in rows:
        name = str(row.get("name") or "").lower()
        filename = str(row.get("filename") or "").lower()
        rid = str(row.get("id") or "").lower()
        if key in {name, filename, rid}:
            path = str(row.get("path") or "")
            if path and os.path.isfile(path) and _is_layout_file(path) and _row_active(row):
                return row
    return None


def _log_template_usage(
    template_id: str | None,
    *,
    action: str,
    result_text: str,
) -> None:
    tid = str(template_id or "").strip()
    db_id: int | None = None
    if tid.startswith("db:"):
        try:
            db_id = int(tid.split(":", 1)[1])
        except ValueError:
            db_id = None
    elif tid.isdigit():
        db_id = int(tid)
    if db_id is None:
        return
    try:
        from sqlalchemy import text

        from app.db.session import get_db

        with get_db() as db:
            db.execute(
                text(
                    """
                    INSERT INTO template_usage_log (template_id, action, result)
                    VALUES (:template_id, :action, :result)
                    """
                ),
                {
                    "template_id": db_id,
                    "action": action[:64],
                    "result": str(result_text or "")[:500],
                },
            )
            db.commit()
    except RECOVERABLE_ERRORS as exc:
        logger.debug("template_usage_log skip: %s", exc)


def log_template_usage(
    template_id: str | None,
    *,
    action: str,
    result_text: str,
) -> None:
    """对外审计入口（generate 成功后写入 template_usage_log）。"""
    _log_template_usage(template_id, action=action, result_text=result_text)


def resolve_shipment_template(
    *,
    template_id: str | None = None,
    template_name: str | None = None,
    preferred: str | None = None,
    unit_name: str | None = None,
    intent: str = "shipment_generate",
    strict: bool | None = None,
    log_usage: bool = False,
) -> dict[str, Any]:
    """解析打单应使用的模版文件。"""
    tid = str(template_id or "").strip()
    tname = str(template_name or "").strip()
    pref = str(preferred or "").strip()
    unit = str(unit_name or "").strip()
    intent_key = str(intent or "shipment_generate").strip() or "shipment_generate"
    preferred_types = _INTENT_TEMPLATE_TYPES.get(
        intent_key, _INTENT_TEMPLATE_TYPES["shipment_generate"]
    )
    strict_mode = shipment_template_strict_enabled(strict)

    try:
        store = _get_template_store()
    except RECOVERABLE_ERRORS as exc:
        logger.warning("模版库不可用，打单回退 legacy: %s", exc)
        return _result(
            ok=False,
            path=tname or None,
            template_id=tid or None,
            template_name=tname or None,
            reason="store_unavailable",
            error_code="TEMPLATE_STORE_UNAVAILABLE",
            unit_name=unit or None,
        )

    # 1) template_id
    if tid:
        path = store.resolve_template_file(tid)
        if path and os.path.isfile(path) and _is_layout_file(path):
            out = _result(
                ok=True,
                path=path,
                template_id=tid,
                template_name=Path(path).name,
                source="template_id",
                reason="resolved_by_id",
                unit_name=unit or None,
            )
            if log_usage:
                _log_template_usage(tid, action="resolve", result_text=out["reason"])
            return out
        if strict_mode:
            return _result(
                ok=False,
                template_id=tid,
                reason="template_id_not_found",
                error_code="TEMPLATE_ID_NOT_FOUND",
                unit_name=unit or None,
            )

    # 1.5) 用户偏好 / 槽位 preferred（可是 id 或名称）
    if pref and not tid:
        if pref.startswith(("db:", "fs:", "shipment")) or pref.isdigit():
            path = store.resolve_template_file(
                pref if pref.startswith(("db:", "fs:")) else f"db:{pref}"
            )
            if path and os.path.isfile(path) and _is_layout_file(path):
                out = _result(
                    ok=True,
                    path=path,
                    template_id=pref if pref.startswith("db:") else f"db:{pref}",
                    template_name=Path(path).name,
                    source="user_preference",
                    reason="resolved_by_preference_id",
                    unit_name=unit or None,
                )
                if log_usage:
                    _log_template_usage(
                        out["template_id"], action="resolve", result_text=out["reason"]
                    )
                return out
        rows = _list_templates_cached(store)
        row = _match_row_by_name(rows, pref)
        if row:
            path = str(row["path"])
            out = _result(
                ok=True,
                path=path,
                template_id=str(row.get("id") or ""),
                template_name=row.get("name") or Path(path).name,
                template_type=row.get("template_type"),
                source="user_preference",
                reason="resolved_by_preference_name",
                unit_name=unit or None,
            )
            if log_usage:
                _log_template_usage(
                    out["template_id"], action="resolve", result_text=out["reason"]
                )
            return out

    # 2) 显式路径 / 文件名
    if tname:
        as_path = Path(tname).expanduser()
        if as_path.is_file() and _is_layout_file(str(as_path)):
            out = _result(
                ok=True,
                path=str(as_path.resolve()),
                template_id=tid or None,
                template_name=as_path.name,
                source="explicit_path",
                reason="resolved_by_path",
                unit_name=unit or None,
            )
            return out
        rows = _list_templates_cached(store)
        row = _match_row_by_name(rows, tname)
        if row:
            path = str(row["path"])
            out = _result(
                ok=True,
                path=path,
                template_id=str(row.get("id") or ""),
                template_name=row.get("name") or Path(path).name,
                template_type=row.get("template_type"),
                source=row.get("source") or "name_match",
                reason="resolved_by_name",
                unit_name=unit or None,
            )
            if log_usage:
                _log_template_usage(
                    out["template_id"], action="resolve", result_text=out["reason"]
                )
            return out
        # 交给 legacy 按文件名搜索（非 strict）
        if not strict_mode:
            return _result(
                ok=True,
                path=tname,
                template_id=tid or None,
                template_name=tname,
                source="legacy_name",
                reason="passthrough_filename",
                unit_name=unit or None,
            )
        return _result(
            ok=False,
            template_name=tname,
            reason="template_name_not_found",
            error_code="TEMPLATE_NAME_NOT_FOUND",
            unit_name=unit or None,
        )

    rows = _list_templates_cached(store)

    # 3) 客户名匹配版式
    if unit:
        best_unit: dict[str, Any] | None = None
        best_unit_score = -1
        for row in rows:
            score = _score_template(row, preferred_types=preferred_types, unit_name=unit)
            # 仅当客户名真正命中才走本分支（避免被通用高分抢走）
            name_token = _normalize_unit_token(
                str(row.get("name") or row.get("filename") or "")
            )
            unit_token = _normalize_unit_token(unit)
            unit_hit = bool(
                unit_token
                and name_token
                and (unit_token == name_token or unit_token in name_token or name_token in unit_token)
            )
            if unit_hit and score > best_unit_score:
                best_unit_score = score
                best_unit = row
        if best_unit and best_unit_score >= 0:
            path = str(best_unit.get("path") or "")
            out = _result(
                ok=True,
                path=path,
                template_id=str(best_unit.get("id") or ""),
                template_name=best_unit.get("name") or Path(path).name,
                template_type=best_unit.get("template_type"),
                source=best_unit.get("source") or "unit_match",
                reason=f"unit_match:{unit}",
                score=best_unit_score,
                unit_name=unit,
            )
            if log_usage:
                _log_template_usage(
                    out["template_id"], action="resolve", result_text=out["reason"]
                )
            return out

    # 4) 意图默认打分
    best: dict[str, Any] | None = None
    best_score = -1
    for row in rows:
        score = _score_template(row, preferred_types=preferred_types, unit_name=unit)
        if score > best_score:
            best_score = score
            best = row
    if best and best_score >= 0:
        path = str(best.get("path") or "")
        out = _result(
            ok=True,
            path=path,
            template_id=str(best.get("id") or ""),
            template_name=best.get("name") or Path(path).name,
            template_type=best.get("template_type"),
            source=best.get("source") or "intent_default",
            reason=f"intent_default:{intent_key}",
            score=best_score,
            unit_name=unit or None,
        )
        if log_usage:
            _log_template_usage(out["template_id"], action="resolve", result_text=out["reason"])
        return out

    # 5) Store 官方默认
    for ttype in preferred_types:
        try:
            row = store.get_default_for_type(ttype)
        except RECOVERABLE_ERRORS:
            row = None
        if (
            row
            and row.get("path")
            and os.path.isfile(str(row["path"]))
            and _is_layout_file(str(row["path"]))
        ):
            out = _result(
                ok=True,
                path=str(row["path"]),
                template_id=str(row.get("id") or ""),
                template_name=row.get("name") or Path(str(row["path"])).name,
                template_type=row.get("template_type") or ttype,
                source=row.get("source") or "store_default",
                reason=f"store_default:{ttype}",
                unit_name=unit or None,
            )
            if log_usage:
                _log_template_usage(
                    out["template_id"], action="resolve", result_text=out["reason"]
                )
            return out

    return _result(
        ok=False,
        path=None,
        template_id=None,
        template_name=None,
        reason="no_template_found",
        error_code="TEMPLATE_NOT_FOUND",
        unit_name=unit or None,
    )


def resolve_products_for_unit(unit_name: str, *, limit: int = 1) -> list[dict[str, Any]]:
    """打单缺产品明细时，用该客户最近出货记录明细兜底。"""
    name = str(unit_name or "").strip()
    if not name:
        return []
    try:
        from app.bootstrap import get_shipment_app_service

        svc = get_shipment_app_service()
        getter = getattr(svc, "get_latest_products_for_unit", None)
        if callable(getter):
            rows = getter(name, limit=limit)
            if isinstance(rows, list) and rows:
                return list(rows)
        orders = svc.get_orders(20) or []
        unit_token = _normalize_unit_token(name)
        for order in orders:
            if not isinstance(order, dict):
                continue
            customer = str(
                order.get("customer_name")
                or order.get("unit_name")
                or order.get("purchase_unit")
                or ""
            ).strip()
            cust_token = _normalize_unit_token(customer)
            if customer and (
                customer == name
                or name in customer
                or customer in name
                or (unit_token and cust_token and unit_token in cust_token)
            ):
                items = order.get("products") or order.get("items") or []
                if isinstance(items, list) and items:
                    return list(items)
    except RECOVERABLE_ERRORS as exc:
        logger.debug("resolve_products_for_unit failed: %s", exc, exc_info=True)
    return []
