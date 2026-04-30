"""MODstore 在线市场 API：认证、钱包、购买、个人商店。"""

from __future__ import annotations

import os
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, Header, HTTPException, Query
from pydantic import BaseModel, Field

from modstore_server.auth_service import (
    authenticate_user,
    create_access_token,
    decode_access_token,
    get_user_by_id,
    register_user,
)
from modstore_server.models import (
    CatalogItem,
    Purchase,
    Transaction,
    User,
    Wallet,
    get_session_factory,
    init_db,
)

router = APIRouter(prefix="/api", tags=["market"])

# ── Auth helpers ──────────────────────────────────────────────


def _get_current_user(authorization: Optional[str] = Header(None)) -> User:
    raw = (authorization or "").strip()
    if not raw.startswith("Bearer "):
        raise HTTPException(401, "缺少认证凭证")
    token = raw[7:]
    payload = decode_access_token(token)
    if not payload:
        raise HTTPException(401, "凭证无效或已过期")
    user_id = int(payload["sub"])
    user = get_user_by_id(user_id)
    if not user:
        raise HTTPException(401, "用户不存在")
    return user


def _require_admin(user: User = Depends(_get_current_user)) -> User:
    if not user.is_admin:
        raise HTTPException(403, "需要管理员权限")
    return user


def _get_optional_user(authorization: Optional[str] = Header(None)) -> Optional[User]:
    """公开接口可选登录：无/非法 Token 时视为匿名，不抛 401。"""
    raw = (authorization or "").strip()
    if not raw.startswith("Bearer "):
        return None
    payload = decode_access_token(raw[7:])
    if not payload:
        return None
    try:
        user_id = int(payload["sub"])
    except (KeyError, ValueError, TypeError):
        return None
    return get_user_by_id(user_id)


# ── DTOs ─────────────────────────────────────────────────────


class RegisterDTO(BaseModel):
    username: str = Field(..., min_length=2, max_length=64)
    password: str = Field(..., min_length=6)
    email: str = ""


class LoginDTO(BaseModel):
    username: str
    password: str


class RechargeDTO(BaseModel):
    amount: float = Field(..., gt=0)
    description: str = ""


class BuyDTO(BaseModel):
    pass


class UploadCatalogDTO(BaseModel):
    pkg_id: str = Field(..., min_length=1, max_length=128)
    version: str = Field(..., min_length=1, max_length=32)
    name: str = Field(..., min_length=1, max_length=256)
    description: str = ""
    price: float = Field(..., ge=0)
    artifact: str = "mod"


# ── Auth endpoints ───────────────────────────────────────────


@router.post("/auth/register")
def api_register(body: RegisterDTO):
    try:
        user = register_user(body.username, body.password, body.email)
    except ValueError as e:
        raise HTTPException(409, str(e))
    token = create_access_token(user.id, user.username)
    return {
        "ok": True,
        "token": token,
        "user": {"id": user.id, "username": user.username, "email": user.email},
    }


@router.post("/auth/login")
def api_login(body: LoginDTO):
    user = authenticate_user(body.username, body.password)
    if not user:
        raise HTTPException(401, "用户名或密码错误")
    token = create_access_token(user.id, user.username)
    return {
        "ok": True,
        "token": token,
        "user": {"id": user.id, "username": user.username, "email": user.email},
    }


@router.get("/auth/me")
def api_me(user: User = Depends(_get_current_user)):
    return {
        "id": user.id,
        "username": user.username,
        "email": user.email,
        "is_admin": user.is_admin,
        "created_at": user.created_at.isoformat() if user.created_at else "",
    }


# ── Wallet endpoints ─────────────────────────────────────────


@router.get("/wallet/balance")
def api_wallet_balance(user: User = Depends(_get_current_user)):
    sf = get_session_factory()
    with sf() as session:
        wallet = session.query(Wallet).filter(Wallet.user_id == user.id).first()
        if not wallet:
            wallet = Wallet(user_id=user.id, balance=0.0)
            session.add(wallet)
            session.commit()
        return {"balance": wallet.balance, "updated_at": wallet.updated_at.isoformat() if wallet.updated_at else ""}


@router.post("/wallet/recharge")
def api_wallet_recharge(body: RechargeDTO, user: User = Depends(_get_current_user)):
    admin_token = (os.environ.get("MODSTORE_ADMIN_RECHARGE_TOKEN") or "").strip()
    if not admin_token:
        raise HTTPException(503, "未配置 MODSTORE_ADMIN_RECHARGE_TOKEN，无法充值")

    sf = get_session_factory()
    with sf() as session:
        wallet = session.query(Wallet).filter(Wallet.user_id == user.id).first()
        if not wallet:
            wallet = Wallet(user_id=user.id, balance=0.0)
            session.add(wallet)
        wallet.balance += body.amount
        wallet.updated_at = datetime.now(timezone.utc)
        txn = Transaction(
            user_id=user.id,
            amount=body.amount,
            txn_type="recharge",
            status="completed",
            description=body.description or "管理员充值",
        )
        session.add(txn)
        session.commit()
        return {"ok": True, "new_balance": wallet.balance}


@router.get("/wallet/transactions")
def api_wallet_transactions(
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    user: User = Depends(_get_current_user),
):
    sf = get_session_factory()
    with sf() as session:
        total = session.query(Transaction).filter(Transaction.user_id == user.id).count()
        rows = (
            session.query(Transaction)
            .filter(Transaction.user_id == user.id)
            .order_by(Transaction.created_at.desc())
            .offset(offset)
            .limit(limit)
            .all()
        )
        return {
            "transactions": [
                {
                    "id": r.id,
                    "amount": r.amount,
                    "type": r.txn_type,
                    "status": r.status,
                    "description": r.description,
                    "created_at": r.created_at.isoformat() if r.created_at else "",
                }
                for r in rows
            ],
            "total": total,
        }


# ── Market catalog ───────────────────────────────────────────


@router.get("/market/catalog")
def api_market_catalog(
    q: Optional[str] = Query(None),
    artifact: Optional[str] = Query(None),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    user: Optional[User] = Depends(_get_optional_user),
):
    sf = get_session_factory()
    with sf() as session:
        query = session.query(CatalogItem).filter(CatalogItem.is_public == True)
        if q:
            ql = q.lower()
            query = query.filter(
                (CatalogItem.name.ilike(f"%{ql}%"))
                | (CatalogItem.pkg_id.ilike(f"%{ql}%"))
                | (CatalogItem.description.ilike(f"%{ql}%"))
            )
        if artifact:
            query = query.filter(CatalogItem.artifact == artifact)
        total = query.count()
        rows = query.order_by(CatalogItem.created_at.desc()).offset(offset).limit(limit).all()

        purchased_ids = set()
        if user:
            purchased_rows = session.query(Purchase.catalog_id).filter(Purchase.user_id == user.id).all()
            purchased_ids = {r[0] for r in purchased_rows}

        return {
            "items": [
                {
                    "id": r.id,
                    "pkg_id": r.pkg_id,
                    "version": r.version,
                    "name": r.name,
                    "description": r.description,
                    "price": r.price,
                    "artifact": r.artifact,
                    "author_id": r.author_id,
                    "purchased": r.id in purchased_ids,
                    "created_at": r.created_at.isoformat() if r.created_at else "",
                }
                for r in rows
            ],
            "total": total,
        }


@router.get("/market/catalog/{item_id}")
def api_market_catalog_detail(
    item_id: int,
    user: Optional[User] = Depends(_get_optional_user),
):
    sf = get_session_factory()
    with sf() as session:
        item = session.query(CatalogItem).filter(CatalogItem.id == item_id).first()
        if not item:
            raise HTTPException(404, "商品不存在")
        purchased = False
        if user:
            purchased = (
                session.query(Purchase)
                .filter(Purchase.user_id == user.id, Purchase.catalog_id == item.id)
                .first()
                is not None
            )
        return {
            "id": item.id,
            "pkg_id": item.pkg_id,
            "version": item.version,
            "name": item.name,
            "description": item.description,
            "price": item.price,
            "artifact": item.artifact,
            "author_id": item.author_id,
            "purchased": purchased,
            "created_at": item.created_at.isoformat() if item.created_at else "",
        }


# ── Purchase ─────────────────────────────────────────────────


@router.post("/market/catalog/{item_id}/buy")
def api_buy_item(item_id: int, user: User = Depends(_get_current_user)):
    sf = get_session_factory()
    with sf() as session:
        item = session.query(CatalogItem).filter(CatalogItem.id == item_id).first()
        if not item:
            raise HTTPException(404, "商品不存在")
        if item.price <= 0:
            existing = (
                session.query(Purchase)
                .filter(Purchase.user_id == user.id, Purchase.catalog_id == item.id)
                .first()
            )
            if existing:
                return {"ok": True, "message": "已拥有"}
            purchase = Purchase(user_id=user.id, catalog_id=item.id, amount=0)
            session.add(purchase)
            session.commit()
            return {"ok": True, "message": "免费领取成功"}

        existing = (
            session.query(Purchase)
            .filter(Purchase.user_id == user.id, Purchase.catalog_id == item.id)
            .first()
        )
        if existing:
            return {"ok": True, "message": "已拥有"}

        wallet = session.query(Wallet).filter(Wallet.user_id == user.id).first()
        if not wallet or wallet.balance < item.price:
            raise HTTPException(402, f"余额不足，需要 ¥{item.price}，当前 ¥{wallet.balance if wallet else 0}")

        wallet.balance -= item.price
        wallet.updated_at = datetime.now(timezone.utc)
        purchase = Purchase(user_id=user.id, catalog_id=item.id, amount=item.price)
        txn = Transaction(
            user_id=user.id,
            amount=-item.price,
            txn_type="purchase",
            status="completed",
            description=f"购买 {item.name} ({item.pkg_id})",
        )
        session.add(purchase)
        session.add(txn)
        session.commit()
        return {"ok": True, "message": "购买成功", "new_balance": wallet.balance}


@router.get("/market/catalog/{item_id}/download")
def api_download_item(item_id: int, user: User = Depends(_get_current_user)):
    sf = get_session_factory()
    with sf() as session:
        item = session.query(CatalogItem).filter(CatalogItem.id == item_id).first()
        if not item:
            raise HTTPException(404, "商品不存在")
        if item.price > 0:
            purchased = (
                session.query(Purchase)
                .filter(Purchase.user_id == user.id, Purchase.catalog_id == item.id)
                .first()
            )
            if not purchased:
                raise HTTPException(403, "未购买此商品，请先购买后下载")
        if not item.stored_filename:
            raise HTTPException(404, "该商品无文件可下载")
        from modstore_server.catalog_store import files_dir
        from fastapi.responses import FileResponse

        path = files_dir() / item.stored_filename
        if not path.is_file():
            raise HTTPException(404, "文件缺失")
        return FileResponse(path, filename=item.pkg_id + ".zip", media_type="application/zip")


# ── My store ─────────────────────────────────────────────────


@router.get("/my-store")
def api_my_store(
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    user: User = Depends(_get_current_user),
):
    sf = get_session_factory()
    with sf() as session:
        total = session.query(Purchase).filter(Purchase.user_id == user.id).count()
        rows = (
            session.query(Purchase)
            .filter(Purchase.user_id == user.id)
            .order_by(Purchase.created_at.desc())
            .offset(offset)
            .limit(limit)
            .all()
        )
        items = []
        for p in rows:
            item = session.query(CatalogItem).filter(CatalogItem.id == p.catalog_id).first()
            if item:
                items.append(
                    {
                        "purchase_id": p.id,
                        "catalog_id": item.id,
                        "pkg_id": item.pkg_id,
                        "version": item.version,
                        "name": item.name,
                        "price_paid": p.amount,
                        "purchased_at": p.created_at.isoformat() if p.created_at else "",
                    }
                )
        return {"items": items, "total": total}


# ── Admin: upload catalog item ───────────────────────────────


@router.post("/admin/catalog")
def api_admin_upload_catalog(body: UploadCatalogDTO, user: User = Depends(_require_admin)):
    sf = get_session_factory()
    with sf() as session:
        existing = session.query(CatalogItem).filter(CatalogItem.pkg_id == body.pkg_id).first()
        if existing:
            raise HTTPException(409, f"pkg_id '{body.pkg_id}' 已存在")
        item = CatalogItem(
            pkg_id=body.pkg_id,
            version=body.version,
            name=body.name,
            description=body.description,
            price=body.price,
            author_id=user.id,
            artifact=body.artifact,
        )
        session.add(item)
        session.commit()
        session.refresh(item)
        return {"ok": True, "id": item.id}


@router.get("/admin/catalog")
def api_admin_list_catalog(
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    user: User = Depends(_require_admin),
):
    sf = get_session_factory()
    with sf() as session:
        total = session.query(CatalogItem).count()
        rows = session.query(CatalogItem).order_by(CatalogItem.created_at.desc()).offset(offset).limit(limit).all()
        return {
            "items": [
                {
                    "id": r.id,
                    "pkg_id": r.pkg_id,
                    "version": r.version,
                    "name": r.name,
                    "price": r.price,
                    "stored_filename": r.stored_filename,
                    "created_at": r.created_at.isoformat() if r.created_at else "",
                }
                for r in rows
            ],
            "total": total,
        }


# ── Init on import ──────────────────────────────────────────

init_db()
