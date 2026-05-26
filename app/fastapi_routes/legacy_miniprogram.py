from __future__ import annotations

import json
import logging

from fastapi import APIRouter, Body, Header, Query
from fastapi.responses import JSONResponse

from app.fastapi_routes.legacy_helpers import (
    _mp_generate_order_no,
    _mp_json_response,
    _mp_jwt_user_id,
    _mp_paginate,
    _mp_uid_or_401,
)

logger = logging.getLogger(__name__)

router = APIRouter(tags=["legacy-miniprogram"])


@router.get("/api/mp/v1/product/list")
def mp_product_list(
    page: int = Query(default=1),
    page_size: int = Query(default=20),
    keyword: str = Query(default=""),
    category: str = Query(default=""),
    sort_by: str = Query(default="newest"),
):
    page = max(1, page)
    page_size = min(100, max(1, page_size))
    keyword = keyword.strip()
    category = category.strip()
    from app.db.models import Product
    from app.db.session import get_db

    with get_db() as db:
        query = db.query(Product).filter(Product.is_active == 1)
        if keyword:
            query = query.filter(
                (Product.name.ilike(f"%{keyword}%"))
                | (Product.model_number.ilike(f"%{keyword}%"))
                | (Product.description.ilike(f"%{keyword}%"))
            )
        if category:
            query = query.filter(Product.category == category)
        if sort_by == "price_asc":
            query = query.order_by(Product.price.asc())
        elif sort_by == "price_desc":
            query = query.order_by(Product.price.desc())
        else:
            query = query.order_by(Product.created_at.desc())
        total = query.count()
        items = query.offset((page - 1) * page_size).limit(page_size).all()
        result = []
        for p in items:
            result.append(
                {
                    "id": p.id,
                    "name": p.name,
                    "model_number": p.model_number or "",
                    "specification": p.specification or "",
                    "price": float(p.price) if p.price else 0,
                    "unit": p.unit or "个",
                    "brand": p.brand or "",
                    "category": p.category or "",
                    "description": (p.description or "")[:200],
                }
            )
        return _mp_paginate(result, total, page, page_size)


@router.get("/api/mp/v1/product/detail/{product_id}")
def mp_product_detail(
    product_id: int, x_user_id: str | None = Header(default=None, alias="X-User-ID")
):
    from app.db.models import Product
    from app.db.session import get_db

    user_id = int(x_user_id) if x_user_id and str(x_user_id).isdigit() else None
    with get_db() as db:
        product = db.query(Product).filter(Product.id == product_id, Product.is_active == 1).first()
        if not product:
            return _mp_json_response(404, "商品不存在", success=False)
        if user_id:
            try:
                from app.db.models import MpBrowseHistory

                existing = (
                    db.query(MpBrowseHistory)
                    .filter(
                        MpBrowseHistory.user_id == user_id, MpBrowseHistory.product_id == product_id
                    )
                    .first()
                )
                if existing:
                    from sqlalchemy.sql import func

                    existing.viewed_at = func.now()
                else:
                    db.add(MpBrowseHistory(user_id=user_id, product_id=product_id))
                db.commit()
            except Exception:
                db.rollback()
        return _mp_json_response(
            200,
            "success",
            {
                "id": product.id,
                "name": product.name,
                "model_number": product.model_number or "",
                "specification": product.specification or "",
                "price": float(product.price) if product.price else 0,
                "unit": product.unit or "个",
                "brand": product.brand or "",
                "category": product.category or "",
                "description": product.description or "",
            },
        )


@router.get("/api/mp/v1/product/categories")
def mp_product_categories():
    from sqlalchemy import distinct

    from app.db.models import Product
    from app.db.session import get_db

    with get_db() as db:
        rows = (
            db.query(distinct(Product.category))
            .filter(Product.is_active == 1, Product.category.isnot(None))
            .all()
        )
        cats = sorted([r[0] for r in rows if r[0]])
        return _mp_json_response(200, "success", cats)


@router.get("/api/mp/v1/product/search")
def mp_product_search(
    keyword: str = Query(default=""),
    page: int = Query(default=1),
    page_size: int = Query(default=20),
):
    return mp_product_list(
        page=page, page_size=page_size, keyword=keyword, category="", sort_by="newest"
    )


@router.get("/api/mp/v1/product/price/{product_id}")
def mp_product_price(product_id: int):
    from app.db.models import Product
    from app.db.session import get_db

    with get_db() as db:
        p = db.query(Product).filter(Product.id == product_id, Product.is_active == 1).first()
        if not p:
            return _mp_json_response(404, "商品不存在", success=False)
        return _mp_json_response(
            200,
            "success",
            {"product_id": p.id, "price": float(p.price) if p.price else 0, "unit": p.unit or "个"},
        )


@router.get("/api/mp/v1/cart/list")
def mp_cart_list(authorization: str | None = Header(default=None)):
    uid = _mp_jwt_user_id(authorization)
    if uid is None:
        return _mp_json_response(401, "未授权", {"message": "missing_token"}, success=False)
    from app.db.models import MpCart, Product
    from app.db.session import get_db

    with get_db() as db:
        carts = (
            db.query(MpCart).filter(MpCart.user_id == uid).order_by(MpCart.created_at.desc()).all()
        )
        items = []
        total_amount = 0.0
        selected_count = 0
        for cart in carts:
            product = db.query(Product).filter(Product.id == cart.product_id).first()
            if not product or product.is_active != 1:
                continue
            unit_price = float(product.price) if product.price else 0
            subtotal = round(unit_price * cart.quantity, 2)
            items.append(
                {
                    "cart_id": cart.id,
                    "product_id": product.id,
                    "product_name": product.name,
                    "model_number": product.model_number or "",
                    "specification": product.specification or "",
                    "unit_price": unit_price,
                    "quantity": cart.quantity,
                    "selected": cart.selected,
                    "subtotal": subtotal,
                    "unit": product.unit or "个",
                }
            )
            if cart.selected:
                total_amount += subtotal
                selected_count += cart.quantity
        return _mp_json_response(
            200,
            "success",
            {
                "items": items,
                "summary": {
                    "total_amount": round(total_amount, 2),
                    "selected_count": selected_count,
                    "total_types": len(items),
                },
            },
        )


@router.delete("/api/mp/v1/cart/clear")
def mp_cart_clear(authorization: str | None = Header(default=None)):
    uid = _mp_jwt_user_id(authorization)
    if uid is None:
        return _mp_json_response(401, "未授权", {"message": "missing_token"}, success=False)
    from app.db.models import MpCart
    from app.db.session import get_db

    with get_db() as db:
        db.query(MpCart).filter(MpCart.user_id == uid).delete()
        db.commit()
        return _mp_json_response(200, "购物车已清空")


@router.delete("/api/mp/v1/cart/remove")
def mp_cart_remove(
    authorization: str | None = Header(default=None), body: dict = Body(default_factory=dict)
):
    uid = _mp_jwt_user_id(authorization)
    if uid is None:
        return _mp_json_response(401, "未授权", {"message": "missing_token"}, success=False)
    product_id = body.get("product_id")
    if not product_id:
        return _mp_json_response(400, "商品ID不能为空", success=False)
    from app.db.models import MpCart
    from app.db.session import get_db

    with get_db() as db:
        deleted = (
            db.query(MpCart).filter(MpCart.user_id == uid, MpCart.product_id == product_id).delete()
        )
        if deleted == 0:
            return _mp_json_response(404, "购物车中不存在该商品", success=False)
        db.commit()
        return _mp_json_response(200, "删除成功")


@router.post("/api/mp/v1/cart/add")
def mp_cart_add(
    authorization: str | None = Header(default=None), body: dict = Body(default_factory=dict)
):
    uid, err = _mp_uid_or_401(authorization)
    if err:
        return err
    from app.db.models import MpCart, Product
    from app.db.session import get_db

    data = body or {}
    product_id = data.get("product_id")
    quantity = max(1, int(data.get("quantity", 1) or 1))
    if not product_id:
        return _mp_json_response(400, "商品ID不能为空", None, success=False)
    with get_db() as db:
        product = db.query(Product).filter(Product.id == product_id, Product.is_active == 1).first()
        if not product:
            return _mp_json_response(404, "商品不存在", None, success=False)
        existing = (
            db.query(MpCart).filter(MpCart.user_id == uid, MpCart.product_id == product_id).first()
        )
        if existing:
            existing.quantity += quantity
        else:
            existing = MpCart(user_id=uid, product_id=product_id, quantity=quantity, selected=True)
            db.add(existing)
        db.commit()
        return _mp_json_response(200, "添加成功", {"cart_id": existing.id})


@router.put("/api/mp/v1/cart/update")
def mp_cart_update(
    authorization: str | None = Header(default=None), body: dict = Body(default_factory=dict)
):
    uid, err = _mp_uid_or_401(authorization)
    if err:
        return err
    from app.db.models import MpCart
    from app.db.session import get_db

    data = body or {}
    product_id = data.get("product_id")
    quantity = data.get("quantity")
    if not product_id:
        return _mp_json_response(400, "商品ID不能为空", None, success=False)
    if quantity is None or int(quantity) < 1:
        return _mp_json_response(400, "数量必须大于0", None, success=False)
    with get_db() as db:
        cart = (
            db.query(MpCart).filter(MpCart.user_id == uid, MpCart.product_id == product_id).first()
        )
        if not cart:
            return _mp_json_response(404, "购物车中不存在该商品", None, success=False)
        cart.quantity = int(quantity)
        db.commit()
        return _mp_json_response(200, "更新成功", None)


@router.put("/api/mp/v1/cart/select")
def mp_cart_select(
    authorization: str | None = Header(default=None), body: dict = Body(default_factory=dict)
):
    uid, err = _mp_uid_or_401(authorization)
    if err:
        return err
    from app.db.models import MpCart
    from app.db.session import get_db

    data = body or {}
    product_id = data.get("product_id")
    selected = data.get("selected", True)
    if not product_id:
        return _mp_json_response(400, "商品ID不能为空", None, success=False)
    with get_db() as db:
        cart = (
            db.query(MpCart).filter(MpCart.user_id == uid, MpCart.product_id == product_id).first()
        )
        if not cart:
            return _mp_json_response(404, "购物车中不存在该商品", None, success=False)
        cart.selected = bool(selected)
        db.commit()
        return _mp_json_response(200, "操作成功", None)
