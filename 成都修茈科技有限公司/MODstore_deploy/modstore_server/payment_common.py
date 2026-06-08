"""支付公共工具：签名、防重放、金额校验、套餐常量与辅助函数。"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import threading
import time
from datetime import datetime, timedelta, timezone
from decimal import ROUND_HALF_UP, Decimal
from typing import Any, Optional

from fastapi import HTTPException
from pydantic import BaseModel, Field

from modstore_server.models import (
    CatalogItem,
    PlanTemplate,
    Purchase,
    UserPlan,
    get_session_factory,
)

logger = logging.getLogger(__name__)

REPLAY_WINDOW = 300


class _ReplayGuard:
    """进程内带 TTL 的防重放 nonce 集合。

    多 worker 不共享：依赖 ``payment_contract`` 文档约定的"高并发场景必须用 Redis"。
    本结构只解决单 worker 长时间运行的内存泄漏（旧实现 ``set()`` 永不淘汰）。

    元素到期后在下一次 ``add`` / ``__contains__`` 时被惰性回收；当字典超过
    ``soft_limit`` 时强制全量 prune，确保最坏情况下内存占用有界。
    """

    __slots__ = ("_data", "_lock", "_window", "_soft_limit", "_calls_since_prune")

    def __init__(self, *, window_seconds: float = REPLAY_WINDOW, soft_limit: int = 50_000) -> None:
        self._data: dict[str, float] = {}
        self._lock = threading.Lock()
        self._window = float(window_seconds)
        self._soft_limit = int(soft_limit)
        self._calls_since_prune = 0

    def __contains__(self, key: str) -> bool:
        now = time.time()
        with self._lock:
            expiry = self._data.get(key)
            if expiry is None:
                return False
            if expiry <= now:
                self._data.pop(key, None)
                return False
            return True

    def add(self, key: str) -> None:
        now = time.time()
        with self._lock:
            self._data[key] = now + self._window
            self._calls_since_prune += 1
            if self._calls_since_prune >= 100 or len(self._data) >= self._soft_limit:
                self._prune_locked(now)
                self._calls_since_prune = 0

    def discard(self, key: str) -> None:
        with self._lock:
            self._data.pop(key, None)

    def clear(self) -> None:
        with self._lock:
            self._data.clear()
            self._calls_since_prune = 0

    def __len__(self) -> int:
        with self._lock:
            return len(self._data)

    # Phase B: compat shim — a few legacy spots / tests check
    # ``request_id in processed_requests`` and ``processed_requests.add(request_id)``.
    # Once all callers are updated to use ``contains()`` / ``mark_processed()`` directly,
    # remove these aliases and the ``__iter__`` method below.
    def __iter__(self):
        with self._lock:
            return iter(list(self._data.keys()))

    def _prune_locked(self, now: float) -> None:
        expired = [k for k, exp in self._data.items() if exp <= now]
        for k in expired:
            self._data.pop(k, None)


processed_requests = _ReplayGuard()

_AMOUNT_TOLERANCE = 0.01

SVIP_TIER_PLAN_IDS: frozenset[str] = frozenset(
    {
        "plan_enterprise",
        "plan_svip2",
        "plan_svip3",
        "plan_svip4",
        "plan_svip5",
        "plan_svip6",
        "plan_svip7",
        "plan_svip8",
    }
)
SVIP_LOCKED_PLAN_IDS: frozenset[str] = frozenset(
    {
        "plan_svip2",
        "plan_svip3",
        "plan_svip4",
        "plan_svip5",
        "plan_svip6",
        "plan_svip7",
        "plan_svip8",
    }
)
MEMBERSHIP_TIER_ORDER: dict[str, int] = {
    "plan_basic": 0,
    "plan_pro": 1,
    "plan_enterprise": 2,
    "plan_svip2": 3,
    "plan_svip3": 4,
    "plan_svip4": 5,
    "plan_svip5": 6,
    "plan_svip6": 7,
    "plan_svip7": 8,
    "plan_svip8": 9,
}


class SignCheckoutBody(BaseModel):
    """服务端签名请求体（不含 request_id / timestamp / signature）。"""

    plan_id: str = ""
    item_id: int = 0
    total_amount: float = 0
    subject: str = ""
    wallet_recharge: bool = False


class CheckoutDTO(BaseModel):
    """下单请求。"""

    plan_id: str = ""
    item_id: int = 0
    total_amount: float = 0
    subject: str = ""
    wallet_recharge: bool = False
    pay_channel: str = Field(default="alipay", description="alipay 或 wechat，不参与签名字段")
    request_id: str = Field(..., description="请求唯一标识")
    timestamp: int = Field(..., description="请求时间戳")
    signature: str = Field(..., description="请求签名")


class RefundDTO(BaseModel):
    """退款请求体。"""

    out_trade_no: str
    reason: str = "用户申请退款"
    refund_reason: Optional[str] = Field(
        None,
        description="结构化退款原因（用于风控/对账归档）。空时取 reason 兜底。",
        max_length=256,
    )


def generate_signature(data: dict, secret: str) -> str:
    sorted_keys = sorted(data.keys())
    sign_string = "&".join([f"{k}={data[k]}" for k in sorted_keys])
    sign_string += secret
    return hashlib.sha256(sign_string.encode("utf-8")).hexdigest()


def verify_signature(data: dict, secret: str, signature: str) -> bool:
    return generate_signature(data, secret) == signature


def check_replay_attack(request_id: str, timestamp: int) -> bool:
    current_time = int(time.time())
    if abs(current_time - timestamp) > REPLAY_WINDOW:
        return True
    if request_id is None or not str(request_id).strip():
        return True
    rid = str(request_id)
    if rid in processed_requests:
        return True
    processed_requests.add(rid)
    return False


def _parse_money(value: Any) -> Optional[float]:
    """将订单或回调中的金额字段解析为 float；无法解析则返回 None。"""
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    s = str(value).strip().replace(",", "")
    if not s:
        return None
    try:
        return float(s)
    except (TypeError, ValueError):
        return None


def _amounts_match(order_amount: Any, paid_amount: Any, *, tol: float = _AMOUNT_TOLERANCE) -> bool:
    """比较本地订单金额与支付宝返回金额是否在容差内。"""
    a = _parse_money(order_amount)
    b = _parse_money(paid_amount)
    if a is None or b is None:
        return False
    return abs(a - b) <= tol


def _amount_sign_str(x: Any) -> str:
    """与前端 ``amountSignStr`` 一致：整数不带小数，小数最多 6 位并去尾 0。"""
    try:
        xf = float(x or 0)
    except (TypeError, ValueError):
        return "0"
    if xf == int(xf):
        return str(int(xf))
    s = f"{xf:.6f}".rstrip("0").rstrip(".")
    return s if s else "0"


def canonical_checkout_sign_data(body: CheckoutDTO) -> dict[str, str]:
    """下单签名的七字段 canonical 形态（键排序后与前端相同）。"""
    return {
        "item_id": str(int(body.item_id or 0)),
        "plan_id": (body.plan_id or "").strip(),
        "request_id": str(body.request_id),
        "subject": (body.subject or "").strip(),
        "timestamp": str(int(body.timestamp)),
        "total_amount": _amount_sign_str(body.total_amount),
        "wallet_recharge": "true" if body.wallet_recharge else "false",
    }


def _catalog_entitlement_metadata(item: CatalogItem, source: str) -> str:
    material_category = (getattr(item, "material_category", "") or "").strip()
    if not material_category:
        art = (getattr(item, "artifact", "") or "").strip()
        material_category = {
            "employee_pack": "ai_employee",
            "workflow_template": "workflow_template",
            "surface": "page_style",
            "bundle": "mod_asset",
            "mod": "mod_asset",
        }.get(art, "other")
    license_scope = (getattr(item, "license_scope", "") or "").strip()
    if not license_scope:
        license_scope = "commercial" if float(getattr(item, "price", 0) or 0) > 0 else "personal"
    return json.dumps(
        {
            "source": source,
            "license_scope": license_scope,
            "material_category": material_category,
            "origin_type": (getattr(item, "origin_type", "") or "original").strip(),
            "ip_risk_level": (getattr(item, "ip_risk_level", "") or "low").strip(),
        },
        ensure_ascii=False,
        separators=(",", ":"),
    )


def _plan_rows(session) -> list[PlanTemplate]:
    rows = list(session.query(PlanTemplate).filter(PlanTemplate.is_active == True).all())
    rows.sort(
        key=lambda p: (
            MEMBERSHIP_TIER_ORDER.get(p.id, 9999),
            p.id or "",
        )
    )
    return rows


def _plan_required_predecessor(plan_id: str | None) -> str | None:
    """SVIP2~SVIP8 必须先持有 svip 入门档（plan_enterprise），其余套餐无前置依赖。"""
    pid = (plan_id or "").strip()
    return "plan_enterprise" if pid in SVIP_LOCKED_PLAN_IDS else None


def _user_max_membership_tier_order(session, user_id: int) -> int:
    """用户当前所有 active UserPlan 中、已知套餐 ID 里最高的档位序。无 known 行则 -1。"""
    if not user_id:
        return -1
    rows = (
        session.query(UserPlan.plan_id)
        .filter(UserPlan.user_id == user_id, UserPlan.is_active == True)
        .all()
    )
    m = -1
    for (pid,) in rows:
        s = (pid or "").strip()
        r = MEMBERSHIP_TIER_ORDER.get(s, -1)
        if r > m:
            m = r
    return m


def _user_owns_svip_tier(session, user_id: int) -> bool:
    """判断用户当前是否拥有任一 SVIP 档（含 svip 入门档）。"""
    if not user_id:
        return False
    rows = (
        session.query(UserPlan.plan_id)
        .filter(UserPlan.user_id == user_id, UserPlan.is_active == True)
        .all()
    )
    return any((pid or "") in SVIP_TIER_PLAN_IDS for (pid,) in rows)


def _plan_as_dict(row: PlanTemplate) -> dict[str, Any]:
    try:
        features = __import__("json").loads(row.features_json or "[]")
    except Exception:
        features = []
    return {
        "id": row.id,
        "name": row.name,
        "description": row.description or "",
        "price": float(row.price or 0),
        "features": features if isinstance(features, list) else [],
        "requires_plan": _plan_required_predecessor(row.id),
    }


def _plan_quotas(row: PlanTemplate) -> dict[str, int]:
    try:
        q = __import__("json").loads(row.quotas_json or "{}")
    except Exception:
        q = {}
    if not isinstance(q, dict):
        return {}
    out: dict[str, int] = {}
    for k, v in q.items():
        try:
            out[str(k)] = int(v)
        except (TypeError, ValueError):
            continue
    return out


def _membership_meta(plan_id: str | None) -> dict[str, Any]:
    pid = (plan_id or "").strip()
    meta = {
        "plan_basic": ("vip", "VIP", True, False),
        "plan_pro": ("vip_plus", "VIP+", True, True),
        "plan_enterprise": ("svip1", "svip", True, True),
        "plan_svip2": ("svip2", "SVIP2", True, True),
        "plan_svip3": ("svip3", "SVIP3", True, True),
        "plan_svip4": ("svip4", "SVIP4", True, True),
        "plan_svip5": ("svip5", "SVIP5", True, True),
        "plan_svip6": ("svip6", "SVIP6", True, True),
        "plan_svip7": ("svip7", "SVIP7", True, True),
        "plan_svip8": ("svip8", "SVIP8", True, True),
    }.get(pid, ("free", "普通用户", False, False))
    return {"tier": meta[0], "label": meta[1], "is_member": meta[2], "can_byok": meta[3]}


def _resolve_checkout_fields(
    session,
    body: SignCheckoutBody,
    user_id: int | None = None,
) -> tuple[str, float, int, str, str, bool]:
    """解析下单业务字段（与 ``/checkout`` 逻辑一致）。

    返回 ``(subject, total_amount, item_id, plan_id, order_kind, wallet_recharge)``。

    ``user_id`` 可选；若提供，则会对 SVIP2~SVIP8 套餐做"必须已是 SVIP"前置检查。
    """
    subject = (body.subject or "").strip() or "XC AGI 订单"
    total_amount = float(body.total_amount or 0)
    plan_id = ""
    item_id = 0
    order_kind = ""
    wallet_recharge = bool(body.wallet_recharge)

    if wallet_recharge:
        if not total_amount or total_amount <= 0:
            raise HTTPException(400, "请填写大于 0 的充值金额")
        subject = (body.subject or "").strip() or "XC AGI 钱包充值"
        order_kind = "wallet"
    elif body.plan_id:
        plan_row = (
            session.query(PlanTemplate)
            .filter(PlanTemplate.id == body.plan_id, PlanTemplate.is_active == True)
            .first()
        )
        if not plan_row:
            raise HTTPException(404, f"套餐 {body.plan_id} 不存在")
        if (body.plan_id or "").strip() in SVIP_LOCKED_PLAN_IDS:
            if not user_id or not _user_owns_svip_tier(session, int(user_id)):
                raise HTTPException(403, "需要先购买 svip 档后才能购买 SVIP2~SVIP8")
        pid = (body.plan_id or "").strip()
        t_new = MEMBERSHIP_TIER_ORDER.get(pid, -1)
        if user_id and t_new >= 0:
            t_cur = _user_max_membership_tier_order(session, int(user_id))
            if t_cur >= 0 and t_new < t_cur:
                raise HTTPException(400, "已拥有更高等级会员，不能购买此低档套餐")
        plan = _plan_as_dict(plan_row)
        total_amount = float(plan["price"])
        subject = str(plan["name"])
        plan_id = body.plan_id.strip()
        order_kind = "plan"
        wallet_recharge = False
    elif body.item_id:
        item = session.query(CatalogItem).filter(CatalogItem.id == body.item_id).first()
        if not item:
            raise HTTPException(404, "商品不存在")
        if not item.is_public or (getattr(item, "compliance_status", "") or "") == "delisted":
            raise HTTPException(403, "该商品已下架，无法购买")
        if item.price <= 0:
            raise HTTPException(400, "免费商品，无需支付")
        total_amount = float(item.price)
        subject = str(item.name)
        item_id = int(body.item_id)
        order_kind = "item"
        wallet_recharge = False
        if user_id:
            dup = (
                session.query(Purchase)
                .filter(Purchase.user_id == int(user_id), Purchase.catalog_id == int(body.item_id))
                .first()
            )
            if dup:
                raise HTTPException(400, "您已购买过该商品，无需重复支付")
    else:
        raise HTTPException(400, "请使用 wallet_recharge、plan_id 或 item_id 之一下单")

    if total_amount <= 0:
        raise HTTPException(400, "金额必须大于 0")

    return subject, total_amount, item_id, plan_id, order_kind, wallet_recharge


def _checkout_return_url(request, out_trade_no: str) -> str | None:
    """收银台回跳地址（page/wap pay 的 return_url / quit_url）。"""
    origin = (os.environ.get("MODSTORE_PUBLIC_ORIGIN") or "").strip().rstrip("/")
    if not origin:
        origin = str(request.base_url).rstrip("/")
    prefix = (os.environ.get("MODSTORE_MARKET_PREFIX") or "/market").strip()
    if prefix and not prefix.startswith("/"):
        prefix = "/" + prefix
    prefix = prefix.rstrip("/")
    path = f"{prefix}/checkout/{out_trade_no}" if prefix else f"/checkout/{out_trade_no}"
    return f"{origin}{path}"
