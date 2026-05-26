from __future__ import annotations

import logging

from fastapi import APIRouter, Body, Header, Query

from app.fastapi_routes.legacy_helpers import (
    _mp_generate_order_no,
    _mp_json_response,
    _mp_jwt_user_id,
    _mp_paginate,
    _mp_uid_or_401,
)

logger = logging.getLogger(__name__)

router = APIRouter(tags=["legacy-miniprogram-order"])


@router.get("/api/mp/v1/order/list")
def mp_order_list(
    authorization: str | None = Header(default=None),
    page: int = Query(default=1),
    page_size: int = Query(default=20),
    status: str = Query(default=""),
):
    uid = _mp_jwt_user_id(authorization)
    if uid is None:
        return _mp_json_response(401, "未授权", {"message": "missing_token"}, success=False)
    page = max(1, page)
    page_size = min(50, max(1, page_size))
    status_filter = status.strip()
    from app.db.models import MpOrder
    from app.db.session import get_db

    with get_db() as db:
        query = db.query(MpOrder).filter(MpOrder.user_id == uid)
        if status_filter and status_filter != "all":
            query = query.filter(MpOrder.status == status_filter)
        query = query.order_by(MpOrder.created_at.desc())
        total = query.count()
        orders = query.offset((page - 1) * page_size).limit(page_size).all()
        result = []
        for o in orders:
            first_item = o.items[0] if o.items else None
            result.append(
                {
                    "id": o.id,
                    "order_no": o.order_no,
                    "status": o.status,
                    "pay_status": o.pay_status,
                    "total_amount": float(o.total_amount),
                    "pay_amount": float(o.pay_amount) if o.pay_amount else None,
                    "item_count": len(o.items),
                    "first_item_name": first_item.product_name if first_item else "",
                    "created_at": o.created_at.isoformat() if o.created_at else None,
                }
            )
        return _mp_paginate(result, total, page, page_size)


@router.get("/api/mp/v1/order/detail/{order_id}")
def mp_order_detail(order_id: int, authorization: str | None = Header(default=None)):
    uid = _mp_jwt_user_id(authorization)
    if uid is None:
        return _mp_json_response(401, "未授权", {"message": "missing_token"}, success=False)
    from app.db.models import MpOrder
    from app.db.session import get_db

    with get_db() as db:
        order = db.query(MpOrder).filter(MpOrder.id == order_id, MpOrder.user_id == uid).first()
        if not order:
            return _mp_json_response(404, "订单不存在", success=False)
        items = []
        for item in order.items:
            items.append(
                {
                    "id": item.id,
                    "product_id": item.product_id,
                    "product_name": item.product_name,
                    "product_sku": item.product_sku or "",
                    "quantity": item.quantity,
                    "unit_price": float(item.unit_price),
                    "subtotal": float(item.subtotal),
                }
            )
        return _mp_json_response(
            200,
            "success",
            {
                "id": order.id,
                "order_no": order.order_no,
                "status": order.status,
                "pay_status": order.pay_status,
                "total_amount": float(order.total_amount),
                "pay_amount": float(order.pay_amount) if order.pay_amount else None,
                "pay_time": order.pay_time.isoformat() if order.pay_time else None,
                "delivery_name": order.delivery_name or "",
                "delivery_phone": order.delivery_phone or "",
                "delivery_address": order.delivery_address or "",
                "remark": order.remark or "",
                "items": items,
                "created_at": order.created_at.isoformat() if order.created_at else None,
                "updated_at": order.updated_at.isoformat() if order.updated_at else None,
            },
        )


@router.post("/api/mp/v1/order/create")
def mp_order_create(
    authorization: str | None = Header(default=None), body: dict = Body(default_factory=dict)
):
    uid, err = _mp_uid_or_401(authorization)
    if err:
        return err
    from app.db.models import MpAddress, MpCart, MpOrder, MpOrderItem, Product
    from app.db.session import get_db

    data = body or {}
    address_id = data.get("address_id")
    remark = data.get("remark", "")
    cart_item_ids = data.get("cart_item_ids", [])
    if not address_id:
        return _mp_json_response(400, "请选择收货地址", None, success=False)
    with get_db() as db:
        address = (
            db.query(MpAddress).filter(MpAddress.id == address_id, MpAddress.user_id == uid).first()
        )
        if not address:
            return _mp_json_response(404, "收货地址不存在", None, success=False)
        if cart_item_ids:
            carts = (
                db.query(MpCart)
                .filter(
                    MpCart.id.in_(cart_item_ids), MpCart.user_id == uid, MpCart.selected == True
                )
                .all()
            )
        else:
            carts = db.query(MpCart).filter(MpCart.user_id == uid, MpCart.selected == True).all()
        if not carts:
            return _mp_json_response(400, "请选择要结算的商品", None, success=False)
        order_items_data = []
        total_amount = 0.0
        for cart in carts:
            product = db.query(Product).filter(Product.id == cart.product_id).first()
            if not product or product.is_active != 1:
                continue
            unit_price = float(product.price) if product.price else 0
            subtotal = round(unit_price * cart.quantity, 2)
            total_amount += subtotal
            order_items_data.append(
                {
                    "product_id": product.id,
                    "product_name": product.name,
                    "product_sku": product.model_number or "",
                    "quantity": cart.quantity,
                    "unit_price": unit_price,
                    "subtotal": subtotal,
                }
            )
        if not order_items_data:
            return _mp_json_response(400, "没有有效的商品", None, success=False)
        order = MpOrder(
            order_no=_mp_generate_order_no(),
            user_id=uid,
            status="pending",
            total_amount=round(total_amount, 2),
            pay_status="unpaid",
            delivery_name=address.contact_name,
            delivery_phone=address.contact_phone,
            delivery_address=f"{address.province}{address.city}{address.district}{address.detail_address}",
            delivery_province=address.province,
            delivery_city=address.city,
            delivery_district=address.district,
            remark=remark,
        )
        db.add(order)
        db.flush()
        for item_data in order_items_data:
            item = MpOrderItem(order_id=order.id, **item_data)
            db.add(item)
        db.query(MpCart).filter(MpCart.id.in_([c.id for c in carts])).delete(
            synchronize_session=False
        )
        db.commit()
        db.refresh(order)
        return _mp_json_response(
            200,
            "订单创建成功",
            {
                "order_id": order.id,
                "order_no": order.order_no,
                "total_amount": float(order.total_amount),
                "status": order.status,
            },
        )


@router.put("/api/mp/v1/order/cancel/{order_id}")
def mp_order_cancel(order_id: int, authorization: str | None = Header(default=None)):
    uid, err = _mp_uid_or_401(authorization)
    if err:
        return err
    from app.db.models import MpOrder
    from app.db.session import get_db

    with get_db() as db:
        order = db.query(MpOrder).filter(MpOrder.id == order_id, MpOrder.user_id == uid).first()
        if not order:
            return _mp_json_response(404, "订单不存在", None, success=False)
        if order.status not in ("pending", "paid"):
            return _mp_json_response(400, "当前状态不允许取消", None, success=False)
        order.status = "cancelled"
        db.commit()
        return _mp_json_response(200, "订单已取消", {"order_id": order.id, "status": order.status})


@router.put("/api/mp/v1/order/confirm/{order_id}")
def mp_order_confirm(order_id: int, authorization: str | None = Header(default=None)):
    uid, err = _mp_uid_or_401(authorization)
    if err:
        return err
    from app.db.models import MpOrder
    from app.db.session import get_db

    with get_db() as db:
        order = db.query(MpOrder).filter(MpOrder.id == order_id, MpOrder.user_id == uid).first()
        if not order:
            return _mp_json_response(404, "订单不存在", None, success=False)
        if order.status != "shipped":
            return _mp_json_response(400, "当前状态无法确认收货", None, success=False)
        order.status = "completed"
        db.commit()
        return _mp_json_response(
            200, "确认收货成功", {"order_id": order.id, "status": order.status}
        )


@router.post("/api/mp/v1/order/rebuy/{order_id}")
def mp_order_rebuy(order_id: int, authorization: str | None = Header(default=None)):
    uid, err = _mp_uid_or_401(authorization)
    if err:
        return err
    from app.db.models import MpCart, MpOrder
    from app.db.session import get_db

    with get_db() as db:
        order = db.query(MpOrder).filter(MpOrder.id == order_id, MpOrder.user_id == uid).first()
        if not order:
            return _mp_json_response(404, "订单不存在", None, success=False)
        for item in order.items:
            existing = (
                db.query(MpCart)
                .filter(MpCart.user_id == uid, MpCart.product_id == item.product_id)
                .first()
            )
            if existing:
                existing.quantity += item.quantity
                existing.selected = True
            else:
                db.add(
                    MpCart(
                        user_id=uid,
                        product_id=item.product_id,
                        quantity=item.quantity,
                        selected=True,
                    )
                )
        db.commit()
        return _mp_json_response(200, "已加入购物车", None)
