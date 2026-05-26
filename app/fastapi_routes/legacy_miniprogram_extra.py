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

router = APIRouter(tags=["legacy-miniprogram-extra"])


@router.get("/api/mp/v1/favorite/list")
def mp_favorite_list(
    authorization: str | None = Header(default=None),
    page: int = Query(default=1),
    page_size: int = Query(default=20),
):
    uid = _mp_jwt_user_id(authorization)
    if uid is None:
        return _mp_json_response(401, "未授权", {"message": "missing_token"}, success=False)
    page = max(1, page)
    page_size = min(50, max(1, page_size))
    from app.db.models import MpFavorite, Product
    from app.db.session import get_db

    with get_db() as db:
        query = (
            db.query(MpFavorite)
            .filter(MpFavorite.user_id == uid)
            .order_by(MpFavorite.created_at.desc())
        )
        total = query.count()
        favorites = query.offset((page - 1) * page_size).limit(page_size).all()
        items = []
        for fav in favorites:
            product = db.query(Product).filter(Product.id == fav.product_id).first()
            if product and product.is_active == 1:
                items.append(
                    {
                        "fav_id": fav.id,
                        "product_id": product.id,
                        "product_name": product.name,
                        "price": float(product.price) if product.price else 0,
                        "unit": product.unit or "个",
                        "created_at": fav.created_at.isoformat() if fav.created_at else None,
                    }
                )
        return _mp_paginate(items, total, page, page_size)


@router.get("/api/mp/v1/favorite/check/{product_id}")
def mp_favorite_check(product_id: int, authorization: str | None = Header(default=None)):
    uid = _mp_jwt_user_id(authorization)
    if uid is None:
        return _mp_json_response(401, "未授权", {"message": "missing_token"}, success=False)
    from app.db.models import MpFavorite
    from app.db.session import get_db

    with get_db() as db:
        fav = (
            db.query(MpFavorite)
            .filter(MpFavorite.user_id == uid, MpFavorite.product_id == product_id)
            .first()
        )
        return _mp_json_response(
            200, "success", {"is_favorited": fav is not None, "fav_id": fav.id if fav else None}
        )


@router.delete("/api/mp/v1/favorite/remove/{fav_id}")
def mp_favorite_remove(fav_id: int, authorization: str | None = Header(default=None)):
    uid = _mp_jwt_user_id(authorization)
    if uid is None:
        return _mp_json_response(401, "未授权", {"message": "missing_token"}, success=False)
    from app.db.models import MpFavorite
    from app.db.session import get_db

    with get_db() as db:
        deleted = (
            db.query(MpFavorite).filter(MpFavorite.id == fav_id, MpFavorite.user_id == uid).delete()
        )
        if not deleted:
            return _mp_json_response(404, "收藏记录不存在", success=False)
        db.commit()
        return _mp_json_response(200, "取消收藏成功")


@router.post("/api/mp/v1/favorite/add")
def mp_favorite_add(
    authorization: str | None = Header(default=None), body: dict = Body(default_factory=dict)
):
    uid, err = _mp_uid_or_401(authorization)
    if err:
        return err
    from app.db.models import MpFavorite, Product
    from app.db.session import get_db

    data = body or {}
    product_id = data.get("product_id")
    if not product_id:
        return _mp_json_response(400, "商品ID不能为空", None, success=False)
    with get_db() as db:
        product = db.query(Product).filter(Product.id == product_id, Product.is_active == 1).first()
        if not product:
            return _mp_json_response(404, "商品不存在", None, success=False)
        existing = (
            db.query(MpFavorite)
            .filter(MpFavorite.user_id == uid, MpFavorite.product_id == product_id)
            .first()
        )
        if existing:
            return _mp_json_response(200, "已收藏", None)
        nf = MpFavorite(user_id=uid, product_id=product_id)
        db.add(nf)
        db.commit()
        return _mp_json_response(200, "收藏成功", {"fav_id": nf.id})


@router.get("/api/mp/v1/address/list")
def mp_address_list(authorization: str | None = Header(default=None)):
    uid = _mp_jwt_user_id(authorization)
    if uid is None:
        return _mp_json_response(401, "未授权", {"message": "missing_token"}, success=False)
    from app.db.models import MpAddress
    from app.db.session import get_db

    with get_db() as db:
        addresses = (
            db.query(MpAddress)
            .filter(MpAddress.user_id == uid)
            .order_by(MpAddress.is_default.desc(), MpAddress.created_at.desc())
            .all()
        )
        result = []
        for addr in addresses:
            result.append(
                {
                    "id": addr.id,
                    "contact_name": addr.contact_name,
                    "contact_phone": addr.contact_phone,
                    "province": addr.province,
                    "city": addr.city,
                    "district": addr.district,
                    "detail_address": addr.detail_address,
                    "full_address": f"{addr.province}{addr.city}{addr.district}{addr.detail_address}",
                    "is_default": addr.is_default,
                }
            )
        return _mp_json_response(200, "success", result)


@router.delete("/api/mp/v1/address/delete/{address_id}")
def mp_address_delete(address_id: int, authorization: str | None = Header(default=None)):
    uid = _mp_jwt_user_id(authorization)
    if uid is None:
        return _mp_json_response(401, "未授权", {"message": "missing_token"}, success=False)
    from app.db.models import MpAddress
    from app.db.session import get_db

    with get_db() as db:
        address = (
            db.query(MpAddress).filter(MpAddress.id == address_id, MpAddress.user_id == uid).first()
        )
        if not address:
            return _mp_json_response(404, "地址不存在", success=False)
        db.delete(address)
        db.commit()
        return _mp_json_response(200, "地址删除成功")


@router.post("/api/mp/v1/address/create")
def mp_address_create(
    authorization: str | None = Header(default=None), body: dict = Body(default_factory=dict)
):
    uid, err = _mp_uid_or_401(authorization)
    if err:
        return err
    from app.db.models import MpAddress
    from app.db.session import get_db

    data = body or {}
    required_fields = [
        "contact_name",
        "contact_phone",
        "province",
        "city",
        "district",
        "detail_address",
    ]
    for field in required_fields:
        if not data.get(field):
            return _mp_json_response(400, f"{field} 不能为空", None, success=False)
    with get_db() as db:
        is_default = data.get("is_default", False)
        if is_default:
            db.query(MpAddress).filter(MpAddress.user_id == uid).update({"is_default": False})
        count = db.query(MpAddress).filter(MpAddress.user_id == uid).count()
        if count == 0:
            is_default = True
        address = MpAddress(
            user_id=uid,
            contact_name=data["contact_name"],
            contact_phone=data["contact_phone"],
            province=data["province"],
            city=data["city"],
            district=data["district"],
            detail_address=data["detail_address"],
            is_default=is_default,
        )
        db.add(address)
        db.commit()
        db.refresh(address)
        return _mp_json_response(
            200, "地址添加成功", {"id": address.id, "is_default": address.is_default}
        )


@router.put("/api/mp/v1/address/update/{address_id}")
def mp_address_update(
    address_id: int,
    authorization: str | None = Header(default=None),
    body: dict = Body(default_factory=dict),
):
    uid, err = _mp_uid_or_401(authorization)
    if err:
        return err
    from app.db.models import MpAddress
    from app.db.session import get_db

    data = body or {}
    with get_db() as db:
        address = (
            db.query(MpAddress).filter(MpAddress.id == address_id, MpAddress.user_id == uid).first()
        )
        if not address:
            return _mp_json_response(404, "地址不存在", None, success=False)
        updatable = [
            "contact_name",
            "contact_phone",
            "province",
            "city",
            "district",
            "detail_address",
        ]
        for field in updatable:
            if field in data and data[field]:
                setattr(address, field, data[field])
        if data.get("is_default") and not address.is_default:
            db.query(MpAddress).filter(MpAddress.user_id == uid, MpAddress.id != address_id).update(
                {"is_default": False}
            )
            address.is_default = True
        db.commit()
        return _mp_json_response(200, "地址更新成功", None)


@router.put("/api/mp/v1/address/default/{address_id}")
def mp_address_default(
    address_id: int,
    authorization: str | None = Header(default=None),
):
    uid, err = _mp_uid_or_401(authorization)
    if err:
        return err
    from app.db.models import MpAddress
    from app.db.session import get_db

    with get_db() as db:
        address = (
            db.query(MpAddress).filter(MpAddress.id == address_id, MpAddress.user_id == uid).first()
        )
        if not address:
            return _mp_json_response(404, "地址不存在", None, success=False)
        db.query(MpAddress).filter(MpAddress.user_id == uid).update({"is_default": False})
        address.is_default = True
        db.commit()
        return _mp_json_response(200, "默认地址设置成功", None)
