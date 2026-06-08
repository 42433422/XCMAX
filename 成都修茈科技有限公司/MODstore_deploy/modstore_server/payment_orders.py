"""MODstore 支付订单存储（JSON 文件落盘）。

注意：当 ``PAYMENT_BACKEND=java`` 时，订单/钱包数据的真实来源是 Java + PostgreSQL。
本模块在 Java 模式下应当成为只读兜底，任何写入都会通过 ``logger`` 发出
``PAYMENT_BACKEND=java`` 警告，便于及时发现「双写」造成的数据漂移。
"""

from __future__ import annotations

import json
import logging
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

_ORDERS_DIR_VAR = "MODSTORE_PAYMENT_ORDERS_DIR"

logger = logging.getLogger(__name__)


def is_local_source_of_truth() -> bool:
    """``PAYMENT_BACKEND`` 决定本地 JSON 是否仍为真实数据源。

    Phase B：此函数将在 Java 稳定后被硬编码为 ``return False``，随后整个 JSON
    写入路径（``create``、``merge_fields``、``update_status`` 等）将被删除。

    目前取值：
    - ``java``：Java + PostgreSQL 拥有订单/钱包数据，本模块进入只读保护模式。
    - 其他取值（``python``、空、未识别）：仍把本地 JSON 视为权威来源，保持兼容。
    """

    backend = (os.environ.get("PAYMENT_BACKEND") or "").strip().lower()
    return backend != "java"


_JAVA_READONLY_MSG = (
    "PAYMENT_BACKEND=java: local payment_orders JSON is read-only; "
    "use Java payment service (PostgreSQL) as the single source of truth"
)


def _reject_local_write(action: str, out_trade_no: str) -> bool:
    """Return True if write must be blocked (Java owns SoT)."""
    if is_local_source_of_truth():
        return False
    logger.warning(
        "blocked local payment_orders %s for %s (%s)",
        action,
        out_trade_no,
        _JAVA_READONLY_MSG,
    )
    return True


def _orders_dir() -> Path:
    d = Path(
        os.environ.get(_ORDERS_DIR_VAR, "") or (Path(__file__).resolve().parent / "payment_orders")
    )
    d.mkdir(parents=True, exist_ok=True)
    return d


def _path(out_trade_no: str) -> Path:
    return _orders_dir() / f"order_{out_trade_no}.json"


def _now_iso() -> str:
    from datetime import datetime, timezone

    return datetime.now(timezone.utc).isoformat()


def create(
    *,
    out_trade_no: str,
    subject: str,
    total_amount: str,
    user_id: int = 0,
    item_id: int = 0,
    plan_id: str = "",
    order_kind: str = "",
    qr_code: str | None = None,
    pay_type: str | None = None,
) -> dict[str, Any]:
    """创建订单记录。``order_kind``: ``plan`` | ``item`` | ``wallet``。"""
    if _reject_local_write("create", out_trade_no):
        return {"ok": False, "message": _JAVA_READONLY_MSG, "code": "java_sot_readonly"}
    p = _path(out_trade_no)
    if p.is_file():
        return {"ok": False, "message": f"订单 {out_trade_no} 已存在"}
    kind = order_kind or ("item" if item_id else "plan" if plan_id else "wallet")
    doc: dict[str, Any] = {
        "out_trade_no": out_trade_no,
        "subject": subject,
        "total_amount": total_amount,
        "user_id": user_id,
        "item_id": item_id,
        "plan_id": plan_id or "",
        "order_kind": kind,
        "status": "pending",
        "trade_no": None,
        "buyer_id": None,
        "paid_at": None,
        "created_at": _now_iso(),
        "updated_at": _now_iso(),
        "notify_count": 0,
        "fulfilled": False,
        "qr_code": qr_code,
        "pay_type": pay_type,
    }
    p.write_text(json.dumps(doc, ensure_ascii=False, indent=2), encoding="utf-8")
    return {"ok": True, "order": doc}


def merge_fields(out_trade_no: str, **kwargs: Any) -> bool:
    """合并更新订单 JSON（用于写入二维码、支付类型、fulfilled 等）。"""
    if _reject_local_write("merge_fields", out_trade_no):
        return False
    doc = find(out_trade_no)
    if not doc:
        return False
    for k, v in kwargs.items():
        if v is not None:
            doc[k] = v
    doc["updated_at"] = _now_iso()
    p = _path(out_trade_no)
    try:
        p.write_text(json.dumps(doc, ensure_ascii=False, indent=2), encoding="utf-8")
        return True
    except OSError:
        return False


def find(out_trade_no: str) -> Optional[dict[str, Any]]:
    p = _path(out_trade_no)
    if not p.is_file():
        return None
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return None


def update_status(
    *,
    out_trade_no: str,
    status: str,
    trade_no: Optional[str] = None,
    buyer_id: Optional[str] = None,
    paid_at: Optional[str] = None,
) -> bool:
    if _reject_local_write("update_status", out_trade_no):
        return False
    doc = find(out_trade_no)
    if not doc:
        return False
    doc["status"] = status
    doc["updated_at"] = _now_iso()
    if trade_no:
        doc["trade_no"] = trade_no
    if buyer_id:
        doc["buyer_id"] = buyer_id
    if paid_at:
        doc["paid_at"] = paid_at
    doc["notify_count"] = doc.get("notify_count", 0) + 1
    p = _path(out_trade_no)
    try:
        p.write_text(json.dumps(doc, ensure_ascii=False, indent=2), encoding="utf-8")
        return True
    except Exception:
        return False


def list_orders(
    *,
    user_id: int = 0,
    status: Optional[str] = None,
    limit: int = 50,
    offset: int = 0,
) -> tuple[list[dict[str, Any]], int]:
    """按创建时间倒序列出订单。"""
    rows = []
    for p in _orders_dir().glob("order_*.json"):
        try:
            doc = json.loads(p.read_text(encoding="utf-8"))
            if user_id and doc.get("user_id") != user_id:
                continue
            if status and doc.get("status") != status:
                continue
            rows.append(doc)
        except Exception:
            continue

    rows.sort(key=lambda d: d.get("created_at", ""), reverse=True)
    total = len(rows)
    return rows[offset : offset + limit], total


def _parse_iso(value: Any) -> Optional[datetime]:
    if not isinstance(value, str) or not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def close_pending_older_than(*, minutes: int = 30) -> int:
    """把超过 ``minutes`` 分钟仍处于 ``pending`` 的订单标记为 ``closed``。

    在 ``PAYMENT_BACKEND=java`` 模式下短路返回 0，避免和 Java 调度器双写：
    Java 拥有订单数据，本地 JSON 不应再被改写。
    """

    if not is_local_source_of_truth():
        return 0

    cutoff = datetime.now(timezone.utc).timestamp() - max(0, int(minutes)) * 60
    closed = 0
    for path in _orders_dir().glob("order_*.json"):
        try:
            doc = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if doc.get("status") != "pending":
            continue
        ts = _parse_iso(doc.get("created_at"))
        if ts is None:
            continue
        if ts.timestamp() > cutoff:
            continue
        doc["status"] = "closed"
        doc["updated_at"] = _now_iso()
        try:
            path.write_text(json.dumps(doc, ensure_ascii=False, indent=2), encoding="utf-8")
            closed += 1
        except OSError:
            continue
    return closed
