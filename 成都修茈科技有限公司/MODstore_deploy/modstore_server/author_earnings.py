"""作者分润结算 API。

分润模型：
  gross          = 订单实付金额
  platform_fee   = gross × PLATFORM_FEE_RATE（默认 30%）
  net            = gross − platform_fee

触发时机：ItemFulfilStrategy.fulfill() 成功后由 payment_fulfilment 写入
AuthorEarning(status="pending")。

API 端点：
  GET  /api/author/earnings                    — 作者查看自己的分润流水
  POST /api/author/withdraw                    — 作者申请提现
  GET  /api/admin/author-earnings              — 管理员查看全平台分润
  POST /api/admin/author-earnings/settle       — 管理员批量标记 settled
  GET  /api/admin/author-withdrawals           — 管理员查看提现申请
  POST /api/admin/author-withdrawals/action    — 管理员审批/拒绝提现
"""

from __future__ import annotations

import logging
import os
from datetime import datetime, timezone
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import func

from modstore_server.api.auth_deps import require_user
from modstore_server.models import (
    AuthorEarning,
    AuthorWithdrawal,
    User,
    get_session_factory,
)

logger = logging.getLogger(__name__)

router = APIRouter(tags=["author-earnings"])

PLATFORM_FEE_RATE: float = float(os.environ.get("PLATFORM_FEE_RATE", "0.30"))
MIN_WITHDRAW_AMOUNT: float = float(os.environ.get("MIN_WITHDRAW_AMOUNT", "10.0"))


# ---------------------------------------------------------------- DTOs


class WithdrawDTO(BaseModel):
    amount: float = Field(..., gt=0, description="提现金额（元），不得超过可提现余额")


class SettleDTO(BaseModel):
    earning_ids: List[int] = Field(..., min_length=1)


class WithdrawalActionDTO(BaseModel):
    withdrawal_id: int
    action: str = Field(..., pattern="^(approve|reject)$")
    admin_note: str = ""


# ---------------------------------------------------------------- 工具函数


def compute_net(gross: float, fee_rate: float = PLATFORM_FEE_RATE) -> float:
    """给定毛收入和平台费率，返回作者净收益（保留 2 位小数）。"""
    return round(gross * (1.0 - fee_rate), 2)


def _earning_row(r: AuthorEarning) -> dict:
    return {
        "id": r.id,
        "order_id": r.order_id,
        "author_id": r.author_id,
        "item_id": r.item_id,
        "gross": r.gross,
        "platform_fee_rate": r.platform_fee_rate,
        "net": r.net,
        "status": r.status,
        "created_at": r.created_at.isoformat() if r.created_at else None,
        "settled_at": r.settled_at.isoformat() if r.settled_at else None,
    }


# ---------------------------------------------------------------- 作者端


@router.get("/api/author/earnings")
def get_author_earnings(
    status: Optional[str] = Query(None, description="过滤状态：pending/settled/withdrawn"),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=200),
    user: User = Depends(require_user),
):
    """作者查看自己的分润流水（按创建时间倒序）。"""
    sf = get_session_factory()
    with sf() as session:
        q = session.query(AuthorEarning).filter(AuthorEarning.author_id == user.id)
        if status:
            q = q.filter(AuthorEarning.status == status)
        total = q.count()
        rows = (
            q.order_by(AuthorEarning.created_at.desc())
            .offset((page - 1) * page_size)
            .limit(page_size)
            .all()
        )
        pending_net = (
            session.query(func.sum(AuthorEarning.net))
            .filter(AuthorEarning.author_id == user.id, AuthorEarning.status == "pending")
            .scalar()
            or 0.0
        )
        return {
            "ok": True,
            "total": total,
            "page": page,
            "page_size": page_size,
            "pending_net": round(float(pending_net), 2),
            "platform_fee_rate": PLATFORM_FEE_RATE,
            "min_withdraw_amount": MIN_WITHDRAW_AMOUNT,
            "items": [_earning_row(r) for r in rows],
        }


@router.post("/api/author/withdraw")
def post_author_withdraw(
    body: WithdrawDTO,
    user: User = Depends(require_user),
):
    """作者发起提现申请（仅校验额度，实际打款由管理员在后台操作）。"""
    sf = get_session_factory()
    with sf() as session:
        pending_net = float(
            session.query(func.sum(AuthorEarning.net))
            .filter(AuthorEarning.author_id == user.id, AuthorEarning.status == "pending")
            .scalar()
            or 0.0
        )
        if body.amount > pending_net:
            raise HTTPException(
                400,
                f"提现金额（{body.amount:.2f}）超过可提现余额（{pending_net:.2f}）",
            )
        if body.amount < MIN_WITHDRAW_AMOUNT:
            raise HTTPException(
                400,
                f"提现金额不得低于最低限额（{MIN_WITHDRAW_AMOUNT:.2f} 元）",
            )
        w = AuthorWithdrawal(author_id=user.id, amount=body.amount, status="pending")
        session.add(w)
        session.commit()
        session.refresh(w)
        return {
            "ok": True,
            "withdrawal_id": w.id,
            "amount": w.amount,
            "status": w.status,
            "created_at": w.created_at.isoformat() if w.created_at else None,
        }


# ---------------------------------------------------------------- 管理员端


@router.get("/api/admin/author-earnings")
def admin_list_author_earnings(
    author_id: Optional[int] = Query(None),
    status: Optional[str] = Query(None),
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=500),
    user: User = Depends(require_user),
):
    """管理员查看全平台分润流水（可按作者、状态过滤）。"""
    if not user.is_admin:
        raise HTTPException(403, "需要管理员权限")
    sf = get_session_factory()
    with sf() as session:
        q = session.query(AuthorEarning)
        if author_id:
            q = q.filter(AuthorEarning.author_id == author_id)
        if status:
            q = q.filter(AuthorEarning.status == status)
        total = q.count()
        rows = (
            q.order_by(AuthorEarning.created_at.desc())
            .offset((page - 1) * page_size)
            .limit(page_size)
            .all()
        )
        total_pending = float(
            session.query(func.sum(AuthorEarning.net))
            .filter(AuthorEarning.status == "pending")
            .scalar()
            or 0.0
        )
        return {
            "ok": True,
            "total": total,
            "total_pending_net": round(total_pending, 2),
            "page": page,
            "page_size": page_size,
            "items": [_earning_row(r) for r in rows],
        }


@router.post("/api/admin/author-earnings/settle")
def admin_settle_earnings(
    body: SettleDTO,
    user: User = Depends(require_user),
):
    """管理员批量将 pending 分润标记为 settled（表示已核算入账）。"""
    if not user.is_admin:
        raise HTTPException(403, "需要管理员权限")
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    sf = get_session_factory()
    with sf() as session:
        rows = (
            session.query(AuthorEarning)
            .filter(
                AuthorEarning.id.in_(body.earning_ids),
                AuthorEarning.status == "pending",
            )
            .all()
        )
        if not rows:
            raise HTTPException(404, "未找到符合条件的 pending 分润记录")
        for r in rows:
            r.status = "settled"
            r.settled_at = now
        session.commit()
        return {"ok": True, "settled_count": len(rows)}


@router.get("/api/admin/author-withdrawals")
def admin_list_withdrawals(
    status: Optional[str] = Query(None),
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=500),
    user: User = Depends(require_user),
):
    """管理员查看提现申请列表。"""
    if not user.is_admin:
        raise HTTPException(403, "需要管理员权限")
    sf = get_session_factory()
    with sf() as session:
        q = session.query(AuthorWithdrawal)
        if status:
            q = q.filter(AuthorWithdrawal.status == status)
        total = q.count()
        rows = (
            q.order_by(AuthorWithdrawal.created_at.desc())
            .offset((page - 1) * page_size)
            .limit(page_size)
            .all()
        )
        return {
            "ok": True,
            "total": total,
            "items": [
                {
                    "id": r.id,
                    "author_id": r.author_id,
                    "amount": r.amount,
                    "status": r.status,
                    "admin_note": r.admin_note,
                    "created_at": r.created_at.isoformat() if r.created_at else None,
                    "processed_at": r.processed_at.isoformat() if r.processed_at else None,
                }
                for r in rows
            ],
        }


@router.post("/api/admin/author-withdrawals/action")
def admin_process_withdrawal(
    body: WithdrawalActionDTO,
    user: User = Depends(require_user),
):
    """管理员审批/拒绝提现申请。
    approve → 将该作者足额的 settled 分润标记为 withdrawn。
    reject  → 申请退回 pending，作者可重新申请。
    """
    if not user.is_admin:
        raise HTTPException(403, "需要管理员权限")
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    sf = get_session_factory()
    with sf() as session:
        w = (
            session.query(AuthorWithdrawal)
            .filter(AuthorWithdrawal.id == body.withdrawal_id)
            .first()
        )
        if not w:
            raise HTTPException(404, "提现申请不存在")
        if w.status != "pending":
            raise HTTPException(400, f"申请当前状态为 {w.status}，无法操作")
        if body.action == "approve":
            w.status = "done"
            settled = (
                session.query(AuthorEarning)
                .filter(AuthorEarning.author_id == w.author_id, AuthorEarning.status == "settled")
                .order_by(AuthorEarning.settled_at)
                .all()
            )
            remaining = float(w.amount)
            for r in settled:
                if remaining <= 0:
                    break
                r.status = "withdrawn"
                remaining -= float(r.net)
        else:
            w.status = "rejected"
        w.admin_note = body.admin_note or ""
        w.processed_at = now
        session.commit()
        return {"ok": True, "withdrawal_id": w.id, "status": w.status}


__all__ = ["router", "compute_net", "PLATFORM_FEE_RATE"]
