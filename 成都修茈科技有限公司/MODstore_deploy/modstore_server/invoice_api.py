"""发票/税务管理 API（MVP 版本）。

MVP 范围：管理员手工操作，无需对接第三方开票服务（百望云/航天信息）。
后续集成点：将 api_admin_issue_invoice 中的 pdf_url 替换为自动调用开票平台接口。

API 端点：
  POST  /api/invoice/apply           — 用户申请开具发票
  GET   /api/invoice/list            — 用户查看自己的发票列表
  GET   /api/admin/invoices          — 管理员查看全部发票申请
  PATCH /api/admin/invoices/{id}     — 管理员审核（issued/rejected）并上传 PDF 链接
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from modstore_server import payment_orders as _po
from modstore_server.api.auth_deps import require_user
from modstore_server.models import Invoice, User, get_session_factory

logger = logging.getLogger(__name__)

router = APIRouter(tags=["invoices"])

DEFAULT_TAX_RATE: float = 0.06


def create_invoice_for_order(
    *,
    out_trade_no: str,
    user_id: int,
    amount: float,
    subject: str,
) -> None:
    """NeuroBus ``payment.paid`` 订阅者钩子：按需自动占位发票（当前 MVP 不启用自动申请）。"""
    _ = (out_trade_no, user_id, amount, subject)
    # 用户仍通过 POST /api/invoice/apply 主动申请开票；此处保留扩展点。


# ---------------------------------------------------------------- DTOs


class InvoiceApplyDTO(BaseModel):
    order_ids: List[str] = Field(
        ..., min_length=1, description="需要开票的订单号列表（已支付且未退款）"
    )
    invoice_type: str = Field("personal", pattern="^(personal|company)$")
    title: str = Field(
        ..., min_length=1, max_length=256, description="发票抬头（个人姓名或公司名称）"
    )
    tax_no: str = Field("", description="税号（公司发票必填）")
    email: str = Field("", description="发票接收邮箱（可选）")


class InvoiceReviewDTO(BaseModel):
    action: str = Field(..., pattern="^(issue|reject)$")
    pdf_url: str = Field("", description="已开具发票的 PDF 下载链接（action=issue 时填写）")
    reject_reason: str = Field("", description="拒绝原因（action=reject 时填写）")


# ---------------------------------------------------------------- 用户端


@router.post("/api/invoice/apply")
def api_invoice_apply(
    body: InvoiceApplyDTO,
    user: User = Depends(require_user),
):
    """用户对已支付订单申请开具发票。同一订单不得重复申请。"""
    if body.invoice_type == "company" and not body.tax_no.strip():
        raise HTTPException(400, "公司发票必须填写税号")

    # 校验所有订单：必须已支付、未退款、属于当前用户
    total_amount = 0.0
    for oid in body.order_ids:
        order = _po.find(oid)
        if not order:
            raise HTTPException(404, f"订单不存在：{oid}")
        if order.get("status") != "paid":
            raise HTTPException(400, f"订单 {oid} 未处于已支付状态")
        if order.get("refunded"):
            raise HTTPException(400, f"订单 {oid} 已退款，不可开票")
        if str(order.get("user_id", "")) != str(user.id):
            raise HTTPException(403, f"订单 {oid} 不属于当前账号")
        total_amount += float(order.get("total_amount") or 0)

    sf = get_session_factory()
    with sf() as session:
        # 检查订单是否已被其他发票申请占用
        # 使用 Python 侧解析 JSON，避免 LIKE 子串误判（如 "12" 命中包含 "123" 的记录）
        all_invoices = session.query(Invoice).filter(Invoice.status != "rejected").all()
        occupied: dict[str, int] = {}
        for inv in all_invoices:
            try:
                ids = json.loads(inv.order_ids_json or "[]")
            except Exception:
                continue
            for oid_in_inv in ids:
                occupied[str(oid_in_inv)] = inv.id
        for oid in body.order_ids:
            if str(oid) in occupied:
                existing_id = occupied[str(oid)]
                raise HTTPException(
                    400,
                    f"订单 {oid} 已存在发票申请（发票 ID={existing_id}）",
                )

        inv = Invoice(
            user_id=user.id,
            order_ids_json=json.dumps(body.order_ids, ensure_ascii=False),
            amount=round(total_amount, 2),
            tax_rate=DEFAULT_TAX_RATE,
            invoice_type=body.invoice_type,
            title=body.title.strip(),
            tax_no=body.tax_no.strip(),
            status="pending",
        )
        session.add(inv)
        session.commit()
        session.refresh(inv)
        return {
            "ok": True,
            "invoice_id": inv.id,
            "amount": inv.amount,
            "status": inv.status,
            "created_at": inv.created_at.isoformat() if inv.created_at else None,
        }


@router.get("/api/invoice/list")
def api_invoice_list(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=200),
    user: User = Depends(require_user),
):
    """用户查看自己提交的发票申请列表（按申请时间倒序）。"""
    sf = get_session_factory()
    with sf() as session:
        q = session.query(Invoice).filter(Invoice.user_id == user.id)
        total = q.count()
        rows = (
            q.order_by(Invoice.created_at.desc())
            .offset((page - 1) * page_size)
            .limit(page_size)
            .all()
        )
        return {
            "ok": True,
            "total": total,
            "page": page,
            "page_size": page_size,
            "items": [_invoice_row(r) for r in rows],
        }


# ---------------------------------------------------------------- 管理员端


@router.get("/api/admin/invoices")
def admin_list_invoices(
    status: Optional[str] = Query(None, description="过滤状态：pending/issued/rejected"),
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=500),
    user: User = Depends(require_user),
):
    """管理员查看全部发票申请（可按状态过滤）。"""
    if not user.is_admin:
        raise HTTPException(403, "需要管理员权限")
    sf = get_session_factory()
    with sf() as session:
        q = session.query(Invoice)
        if status:
            q = q.filter(Invoice.status == status)
        total = q.count()
        rows = (
            q.order_by(Invoice.created_at.desc())
            .offset((page - 1) * page_size)
            .limit(page_size)
            .all()
        )
        return {
            "ok": True,
            "total": total,
            "page": page,
            "page_size": page_size,
            "items": [_invoice_row(r) for r in rows],
        }


@router.patch("/api/admin/invoices/{invoice_id}")
def admin_review_invoice(
    invoice_id: int,
    body: InvoiceReviewDTO,
    user: User = Depends(require_user),
):
    """管理员审核发票申请：issue（已开具，填写 pdf_url）或 reject（拒绝，填写拒绝原因）。"""
    if not user.is_admin:
        raise HTTPException(403, "需要管理员权限")
    if body.action == "issue" and not body.pdf_url.strip():
        raise HTTPException(400, "开具发票时必须提供 pdf_url")
    if body.action == "reject" and not body.reject_reason.strip():
        raise HTTPException(400, "拒绝时必须提供 reject_reason")

    now = datetime.now(timezone.utc).replace(tzinfo=None)
    sf = get_session_factory()
    with sf() as session:
        inv = session.query(Invoice).filter(Invoice.id == invoice_id).first()
        if not inv:
            raise HTTPException(404, "发票申请不存在")
        if inv.status != "pending":
            raise HTTPException(400, f"发票当前状态为 {inv.status}，无法重复审核")
        if body.action == "issue":
            inv.status = "issued"
            inv.pdf_url = body.pdf_url.strip()
            inv.issued_at = now
            inv.reject_reason = ""
        else:
            inv.status = "rejected"
            inv.reject_reason = body.reject_reason.strip()
        inv.updated_at = now
        session.commit()
        return {"ok": True, "invoice_id": inv.id, "status": inv.status}


# ---------------------------------------------------------------- 工具


def _invoice_row(r: Invoice) -> dict:
    try:
        order_ids = json.loads(r.order_ids_json or "[]")
    except Exception:
        order_ids = []
    return {
        "id": r.id,
        "user_id": r.user_id,
        "order_ids": order_ids,
        "amount": r.amount,
        "tax_rate": r.tax_rate,
        "invoice_type": r.invoice_type,
        "title": r.title,
        "tax_no": r.tax_no,
        "status": r.status,
        "reject_reason": r.reject_reason,
        "pdf_url": r.pdf_url,
        "issued_at": r.issued_at.isoformat() if r.issued_at else None,
        "created_at": r.created_at.isoformat() if r.created_at else None,
        "updated_at": r.updated_at.isoformat() if r.updated_at else None,
    }


__all__ = ["router"]
