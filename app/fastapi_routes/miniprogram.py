"""
归档 ``miniprogram_api`` 蓝图 —— 全量原生迁移。

**与主站分流**（在 ``register_fastapi_compat_routes`` 中于 ``xcagi_compat`` **之后**注册）的路径：

- ``GET /api/products``、``POST /api/shipment/create``、``GET /api/shipment/list``
- ``GET /api/print/label/{id}``、``GET /api/print/labels/{id}/list``

``POST /api/ai/chat`` 由 ``xcagi_compat``（Planner）注册并优先匹配；小程序专用对话见 ``POST /api/mp/v1/ai/chat``。

``GET /api/shipment/list``：无 Bearer 或桌面请求 → ``query_shipment_orders`` 原形态；\
``Authorization: Bearer`` + 有效小程序 JWT → ``code/message/data`` 分页列表（与归档一致，支持 ``unit_name`` 或 ``unit``）。

与主站同路径的 **客户 / 产品详情** 在 ``xcagi_compat`` 中按 Bearer 分流（见该模块）。

``/api/wx/miniprogram/*`` 仍保留，与写死子路径的旧客户端兼容。
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import logging
import os
import re
import time
from datetime import datetime
from typing import Any

from fastapi import APIRouter, Body, Header, Query, Request
from fastapi.responses import FileResponse, JSONResponse
from sqlalchemy import or_

logger = logging.getLogger(__name__)

router = APIRouter(tags=["miniprogram-api"])


def _secret_key() -> str:
    return os.environ.get("SECRET_KEY", "xcagi-dev-secret")


def _verify_mp_jwt(token: str) -> dict[str, Any] | None:
    try:
        secret = _secret_key().encode("utf-8")
        parts = token.split(".")
        if len(parts) != 3:
            return None

        def b64url_decode(data: str) -> bytes:
            padding = "=" * (4 - len(data) % 4)
            return base64.urlsafe_b64decode(data + padding)

        payload = json.loads(b64url_decode(parts[1]).decode("utf-8"))
        signature = b64url_decode(parts[2])
        message = f"{parts[0]}.{parts[1]}".encode("utf-8")
        expected = hmac.new(secret, message, hashlib.sha256).digest()
        if not hmac.compare_digest(signature, expected):
            return None
        if int(payload.get("exp", 0)) < int(time.time()):
            return None
        return payload
    except Exception:
        return None


def _mp_json(code: int, message: str, data: Any = None, *, success: bool = True) -> JSONResponse:
    body: dict[str, Any] = {"code": code, "message": message, "success": success}
    if data is not None:
        body["data"] = data
    return JSONResponse(body, status_code=code)


def _parse_mp_auth(authorization: str | None) -> dict[str, Any] | JSONResponse:
    if not authorization or not authorization.startswith("Bearer "):
        return _mp_json(401, "未授权", {"error": "缺少 token"}, success=False)
    token = authorization[7:].strip()
    payload = _verify_mp_jwt(token)
    if not payload:
        return _mp_json(401, "token 无效或已过期", {"error": "invalid_token"}, success=False)
    return payload


def classify_miniprogram_bearer(authorization: str | None) -> tuple[str, dict[str, Any] | None]:
    """
    ``("none", None)`` — 无 Bearer，走桌面逻辑；\
    ``("invalid", None)`` — Bearer 存在但非有效小程序 JWT；\
    ``("ok", payload)`` — 小程序 JWT 有效。
    """
    if not authorization or not authorization.startswith("Bearer "):
        return ("none", None)
    payload = _verify_mp_jwt(authorization[7:].strip())
    if not payload:
        return ("invalid", None)
    return ("ok", payload)


def _doc_order_number_from_parsed(parsed_data: Any) -> str | None:
    if not isinstance(parsed_data, str) or not parsed_data.strip():
        return None
    try:
        j = json.loads(parsed_data)
        on = (j.get("document") or {}).get("order_number")
        return str(on).strip() if on is not None else None
    except Exception:
        return None


def build_mp_customers_list_response(
    keyword: str | None,
    page: int,
    per_page: int,
) -> JSONResponse:
    from app.db.models import Customer
    from app.db.session import get_db
    from app.utils.mobile_api import parse_pagination_params

    try:
        args: dict[str, Any] = {"page": page, "per_page": per_page}
        page, per_page = parse_pagination_params(args)
        kw = (keyword or "").strip()

        with get_db() as db:
            query = db.query(Customer)
            if kw:
                query = query.filter(
                    or_(
                        Customer.customer_name.like(f"%{kw}%"),
                        Customer.contact_person.like(f"%{kw}%"),
                        Customer.contact_phone.like(f"%{kw}%"),
                    )
                )
            total = query.count()
            customers = query.offset((page - 1) * per_page).limit(per_page).all()
            customer_list = [
                {
                    "id": c.id,
                    "customer_name": c.customer_name,
                    "contact_person": c.contact_person,
                    "contact_phone": c.contact_phone,
                    "contact_address": c.contact_address,
                }
                for c in customers
            ]
            return _mp_json(
                200,
                "获取成功",
                {
                    "items": customer_list,
                    "pagination": {
                        "total": total,
                        "page": page,
                        "per_page": per_page,
                        "total_pages": (total + per_page - 1) // per_page,
                        "has_next": page * per_page < total,
                        "has_prev": page > 1,
                    },
                },
            )
    except Exception as e:
        logger.error("小程序客户列表失败: %s", e, exc_info=True)
        return _mp_json(500, f"查询失败：{str(e)}", success=False)


def build_mp_customer_detail_response(customer_id: int) -> JSONResponse:
    from app.db.models import Customer
    from app.db.session import get_db

    try:
        with get_db() as db:
            customer = db.query(Customer).filter(Customer.id == customer_id).first()
            if not customer:
                return _mp_json(404, "客户不存在", success=False)
            customer_data = {
                "id": customer.id,
                "customer_name": customer.customer_name,
                "contact_person": customer.contact_person,
                "contact_phone": customer.contact_phone,
                "contact_address": customer.contact_address,
                "created_at": _iso(customer.created_at),
                "updated_at": _iso(customer.updated_at),
            }
            return _mp_json(200, "获取成功", customer_data)
    except Exception as e:
        logger.error("小程序客户详情失败: %s", e)
        return _mp_json(500, f"查询失败：{str(e)}", success=False)


def build_mp_product_detail_response(product_id: int) -> JSONResponse:
    from app.db.models import Product
    from app.db.session import get_db

    try:
        with get_db() as db:
            product = (
                db.query(Product)
                .filter(Product.id == product_id, Product.is_active == 1)
                .first()
            )
            if not product:
                return _mp_json(404, "产品不存在", success=False)

            product_data = {
                "id": product.id,
                "name": product.name,
                "model_number": product.model_number,
                "specification": product.specification,
                "price": float(product.price) if product.price else None,
                "unit": product.unit,
                "brand": product.brand,
                "category": product.category,
                "description": product.description,
                "quantity": product.quantity,
            }
            return _mp_json(200, "获取成功", product_data)
    except Exception as e:
        logger.error("小程序产品详情失败: %s", e)
        return _mp_json(500, f"查询失败：{str(e)}", success=False)


def build_mp_shipment_list_response(
    unit_name: str | None,
    start_date: str | None,
    end_date: str | None,
    page: int,
    per_page: int,
) -> JSONResponse:
    from app.db.models import ShipmentRecord
    from app.db.session import get_db
    from app.utils.mobile_api import parse_pagination_params

    try:
        page, per_page = parse_pagination_params({"page": page, "per_page": per_page})
        un = (unit_name or "").strip()

        with get_db() as db:
            query = db.query(ShipmentRecord)
            if un:
                query = query.filter(ShipmentRecord.purchase_unit.like(f"%{un}%"))
            if start_date:
                start = datetime.strptime(start_date, "%Y-%m-%d")
                query = query.filter(ShipmentRecord.created_at >= start)
            if end_date:
                end = datetime.strptime(end_date, "%Y-%m-%d")
                query = query.filter(ShipmentRecord.created_at <= end)

            query = query.order_by(ShipmentRecord.created_at.desc())
            total = query.count()
            shipments = query.offset((page - 1) * per_page).limit(per_page).all()

            shipment_list = []
            for s in shipments:
                on = _doc_order_number_from_parsed(getattr(s, "parsed_data", None))
                shipment_list.append(
                    {
                        "id": s.id,
                        "order_number": on or str(s.id),
                        "unit_name": s.purchase_unit,
                        "total_amount": float(s.amount) if s.amount is not None else None,
                        "status": s.status,
                        "created_at": _iso(s.created_at),
                        "printed_at": _iso(s.printed_at),
                    }
                )

            return _mp_json(
                200,
                "获取成功",
                {
                    "items": shipment_list,
                    "pagination": {
                        "total": total,
                        "page": page,
                        "per_page": per_page,
                        "total_pages": (total + per_page - 1) // per_page,
                        "has_next": page * per_page < total,
                        "has_prev": page > 1,
                    },
                },
            )
    except Exception as e:
        logger.error("小程序发货单列表失败: %s", e, exc_info=True)
        return _mp_json(500, f"查询失败：{str(e)}", success=False)


def _iso(dt: Any) -> str | None:
    if dt is None:
        return None
    if hasattr(dt, "isoformat"):
        return dt.isoformat()
    return str(dt)


def _build_items_from_mp_products(products: list[Any]) -> list[dict[str, Any]]:
    from app.db.models import Product
    from app.db.session import get_db

    out: list[dict[str, Any]] = []
    with get_db() as db:
        for p in products:
            if not isinstance(p, dict):
                continue
            pid = p.get("product_id")
            qty = int(p.get("quantity") or 0)
            price = float(p.get("price") or 0)
            if pid is None or qty <= 0:
                continue
            prod = (
                db.query(Product)
                .filter(Product.id == int(pid), Product.is_active == 1)
                .first()
            )
            if not prod:
                continue
            out.append(
                {
                    "product_name": prod.name or "",
                    "model_number": prod.model_number or "",
                    "quantity_tins": qty,
                    "tin_spec": 10.0,
                    "unit_price": price,
                    "amount": float(price) * float(qty),
                }
            )
    return out


def _order_prefixes_for_shipment_row(row: dict[str, Any]) -> list[str]:
    seen: list[str] = []
    pd = row.get("parsed_data")
    if isinstance(pd, str) and pd.strip():
        try:
            j = json.loads(pd)
            doc = j.get("document") or {}
            on = doc.get("order_number")
            if on is not None and str(on).strip():
                seen.append(str(on).strip())
        except Exception:
            pass
    rid = row.get("id")
    if rid is not None:
        seen.append(str(rid))
    out: list[str] = []
    for s in seen:
        if s and s not in out:
            out.append(s)
    return out


# ----- 与 Flask 路由优先级一致（先于 xcagi 注册）-----


@router.get("/api/products")
def mp_get_products(
    keyword: str | None = Query(None),
    model_number: str | None = Query(None),
    page: int = Query(1, ge=1),
    per_page: int = Query(20, ge=1, le=100),
):
    from app.db.models import Product
    from app.db.session import get_db
    from app.utils.mobile_api import parse_pagination_params, parse_search_params

    try:
        args: dict[str, Any] = {"page": page, "per_page": per_page}
        if keyword is not None:
            args["keyword"] = keyword
        if model_number is not None:
            args["model_number"] = model_number
        page, per_page = parse_pagination_params(args)
        search_params = parse_search_params(args, ["keyword", "model_number"])

        with get_db() as db:
            query = db.query(Product).filter(Product.is_active == 1)

            if search_params.get("keyword"):
                kw = f"%{search_params['keyword']}%"
                query = query.filter(
                    or_(
                        Product.name.like(kw),
                        Product.model_number.like(kw),
                    )
                )

            if search_params.get("model_number"):
                query = query.filter(
                    Product.model_number.like(f"%{search_params['model_number']}%")
                )

            total = query.count()
            products = query.offset((page - 1) * per_page).limit(per_page).all()

            product_list = [
                {
                    "id": p.id,
                    "name": p.name,
                    "model_number": p.model_number,
                    "specification": p.specification,
                    "price": float(p.price) if p.price else None,
                    "unit": p.unit,
                    "brand": p.brand,
                    "category": p.category,
                }
                for p in products
            ]

            return _mp_json(
                200,
                "获取成功",
                {
                    "items": product_list,
                    "pagination": {
                        "total": total,
                        "page": page,
                        "per_page": per_page,
                        "total_pages": (total + per_page - 1) // per_page,
                        "has_next": page * per_page < total,
                        "has_prev": page > 1,
                    },
                },
            )
    except Exception as e:
        logger.error("小程序产品列表失败: %s", e, exc_info=True)
        return _mp_json(500, f"查询失败：{str(e)}", success=False)


@router.post("/api/shipment/create")
def mp_create_shipment(
    body: dict[str, Any] = Body(default_factory=dict),
    authorization: str | None = Header(None),
):
    _auth = _parse_mp_auth(authorization)
    if isinstance(_auth, JSONResponse):
        return _auth

    unit_name = str(body.get("unit_name") or "").strip()
    products = body.get("products") or []
    if not unit_name:
        return _mp_json(400, "单位名称不能为空", success=False)
    if not products:
        return _mp_json(400, "产品列表不能为空", success=False)

    items_data = _build_items_from_mp_products(products)
    if not items_data:
        return _mp_json(400, "没有有效的产品行", success=False)

    from app.bootstrap import get_shipment_app_service

    svc = get_shipment_app_service()
    result = svc.create_shipment(unit_name, items_data)
    if not result.get("success"):
        return _mp_json(500, str(result.get("message") or "创建失败"), success=False)

    ship = result.get("shipment") or {}
    return _mp_json(
        201,
        "创建成功",
        {
            "id": ship.get("id"),
            "order_number": ship.get("order_number"),
            "unit_name": ship.get("purchase_unit") or unit_name,
            "total_amount": ship.get("total_amount"),
            "status": ship.get("status"),
            "created_at": ship.get("created_at"),
        },
    )


@router.get("/api/shipment/list", response_model=None)
def api_shipment_list_unified(
    request: Request,
    authorization: str | None = Header(None),
    unit: str | None = Query(None, description="桌面端查询参数，等同购买单位过滤"),
    unit_name: str | None = Query(None, description="小程序归档参数，与 unit 合并"),
    start_date: str | None = Query(None),
    end_date: str | None = Query(None),
    page: int = Query(1, ge=1),
    per_page: int = Query(20, ge=1, le=500),
):
    """桌面：``query_shipment_orders``；小程序 JWT：归档 ``code/message/data`` 列表。"""
    from app.bootstrap import get_shipment_app_service

    auth_header = authorization or request.headers.get("Authorization")
    kind, _payload = classify_miniprogram_bearer(auth_header)
    eff_unit = (unit_name or unit or "").strip() or None

    if kind == "ok":
        return build_mp_shipment_list_response(
            eff_unit, start_date, end_date, page, per_page
        )
    if kind == "invalid":
        return _mp_json(401, "token 无效或已过期", {"error": "invalid_token"}, success=False)

    result = get_shipment_app_service().query_shipment_orders(
        unit_name=eff_unit,
        start_date=start_date,
        end_date=end_date,
        page=page,
        per_page=per_page,
    )
    return JSONResponse(result, status_code=200)


@router.get("/api/print/label/{shipment_id:int}")
def mp_get_label_png(
    shipment_id: int,
    authorization: str | None = Header(None),
):
    _auth = _parse_mp_auth(authorization)
    if isinstance(_auth, JSONResponse):
        return _auth

    from app.bootstrap import get_shipment_app_service
    from app.utils.path_utils import get_resource_path

    row = get_shipment_app_service().get_order(str(shipment_id))
    if not row:
        return _mp_json(404, "发货单不存在", success=False)

    labels_dir = get_resource_path("ai_assistant", "商标导出")
    if not labels_dir or not os.path.isdir(labels_dir):
        return _mp_json(404, "标签目录不存在", success=False)

    prefixes = _order_prefixes_for_shipment_row(row)
    label_files: list[str] = []
    for name in os.listdir(labels_dir):
        if not name.lower().endswith(".png"):
            continue
        if any(name.startswith(pref) for pref in prefixes):
            label_files.append(name)

    if not label_files:
        return _mp_json(404, "未找到标签文件", success=False)

    label_path = os.path.join(labels_dir, label_files[0])
    return FileResponse(
        label_path,
        media_type="image/png",
        filename=label_files[0],
    )


@router.get("/api/print/labels/{shipment_id:int}/list")
def mp_list_labels(
    shipment_id: int,
    authorization: str | None = Header(None),
):
    _auth = _parse_mp_auth(authorization)
    if isinstance(_auth, JSONResponse):
        return _auth

    from app.bootstrap import get_shipment_app_service
    from app.utils.path_utils import get_resource_path

    row = get_shipment_app_service().get_order(str(shipment_id))
    if not row:
        return _mp_json(404, "发货单不存在", success=False)

    labels_dir = get_resource_path("ai_assistant", "商标导出")
    if not labels_dir or not os.path.isdir(labels_dir):
        return _mp_json(200, "标签目录不存在", {"labels": [], "order_number": "", "count": 0})

    prefixes = _order_prefixes_for_shipment_row(row)
    primary_order = prefixes[0] if prefixes else str(shipment_id)

    label_files = [
        f
        for f in os.listdir(labels_dir)
        if f.lower().endswith(".png") and any(f.startswith(pref) for pref in prefixes)
    ]

    labels: list[dict[str, str]] = []
    for filename in sorted(label_files):
        match = re.match(r".+?_?第？?(\d+)?项？\.png", filename, re.IGNORECASE)
        label_number = match.group(1) if match else "1"
        labels.append(
            {
                "filename": filename,
                "label_number": label_number,
                "url": f"/api/print/label/{shipment_id}",
            }
        )

    return _mp_json(
        200,
        "获取成功",
        {
            "order_number": primary_order,
            "labels": labels,
            "count": len(labels),
        },
    )


# ----- 归档中存在但被其它 Flask 蓝图覆盖；显式子路径保留小程序 JSON 形态 -----


@router.get("/api/wx/miniprogram/products/{product_id:int}")
def mp_get_product_shadow(
    product_id: int,
):
    return build_mp_product_detail_response(product_id)


@router.get("/api/wx/miniprogram/customers")
def mp_get_customers_shadow(
    authorization: str | None = Header(None),
    keyword: str | None = Query(None),
    page: int = Query(1, ge=1),
    per_page: int = Query(20, ge=1, le=100),
):
    _auth = _parse_mp_auth(authorization)
    if isinstance(_auth, JSONResponse):
        return _auth
    return build_mp_customers_list_response(keyword, page, per_page)


@router.get("/api/wx/miniprogram/customers/{customer_id:int}")
def mp_get_customer_shadow(
    customer_id: int,
    authorization: str | None = Header(None),
):
    _auth = _parse_mp_auth(authorization)
    if isinstance(_auth, JSONResponse):
        return _auth
    return build_mp_customer_detail_response(customer_id)


@router.get("/api/wx/miniprogram/shipment/list")
def mp_shipment_list_shadow(
    authorization: str | None = Header(None),
    unit_name: str | None = Query(None),
    start_date: str | None = Query(None),
    end_date: str | None = Query(None),
    page: int = Query(1, ge=1),
    per_page: int = Query(20, ge=1, le=100),
):
    _auth = _parse_mp_auth(authorization)
    if isinstance(_auth, JSONResponse):
        return _auth
    return build_mp_shipment_list_response(
        unit_name, start_date, end_date, page, per_page
    )
