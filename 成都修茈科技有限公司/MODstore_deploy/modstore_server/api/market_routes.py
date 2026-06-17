"""XC AGI 在线市场 API：认证、钱包、购买、个人商店。"""

from __future__ import annotations

import hashlib
import os
import shutil
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from fastapi import (
    APIRouter,
    BackgroundTasks,
    Depends,
    File,
    Form,
    Header,
    HTTPException,
    Query,
    Request,
    Response,
    UploadFile,
)
from pydantic import BaseModel, Field

from modstore_server import account_level_service, catalog_sync
from modstore_server.api.deps import get_current_user, require_admin
from modstore_server.auth_service import (
    authenticate_user,
    create_access_token,
    create_refresh_token,
    decode_access_token,
    decode_refresh_token,
    get_user_by_id,
    hash_password,
    register_user,
    verify_password,
)
from modstore_server.duty_roster import is_planned_duty_employee_pack
from modstore_server.email_service import (
    assert_email_outbound_configured,
    find_user_by_email,
    generate_verification_code,
    send_verification_email,
)
from modstore_server.models import (
    CatalogItem,
    Entitlement,
    Favorite,
    Purchase,
    Review,
    Transaction,
    User,
    VerificationCode,
    Wallet,
    get_session_factory,
    init_db,
)

router = APIRouter(prefix="/api", tags=["market"])

# ── Auth helpers (legacy aliases) ───────────────────────────────
_get_current_user = get_current_user
_require_admin = require_admin

# 企业版桌面：管理员可分配给用户的行业/客户 Mod（与 FHD protected_client_mod_ids 对齐）
ENTERPRISE_ASSIGNABLE_MODS: dict[str, str] = {
    "attendance-industry": "考勤行业包",
    "coating-industry": "涂料行业包",
    "taiyangniao-pro": "太阳鸟 PRO",
    "sz-qsm-pro": "深圳国商茂 PRO",
}


def _enterprise_assignable_mod_ids() -> frozenset[str]:
    return frozenset(ENTERPRISE_ASSIGNABLE_MODS.keys())


def _assert_enterprise_assignable_mod_id(mod_id: str) -> str:
    mid = (mod_id or "").strip()
    if not mid:
        raise HTTPException(400, "mod_id 无效")
    if mid not in _enterprise_assignable_mod_ids():
        raise HTTPException(
            400,
            f"mod_id 不在可分配客户 Mod 列表内（允许: {', '.join(sorted(_enterprise_assignable_mod_ids()))}）",
        )
    return mid


def _user_mod_ids_map(user_ids: list[int]) -> dict[int, list[str]]:
    if not user_ids:
        return {}
    from modstore_server.models_catalog import UserMod

    sf = get_session_factory()
    out: dict[int, list[str]] = {int(uid): [] for uid in user_ids}
    with sf() as session:
        rows = (
            session.query(UserMod.user_id, UserMod.mod_id)
            .filter(UserMod.user_id.in_(user_ids))
            .all()
        )
    for uid, mid in rows:
        key = int(uid)
        if mid and mid not in out.get(key, []):
            out.setdefault(key, []).append(str(mid))
    for uid in out:
        out[uid] = sorted(out[uid])
    return out


def _get_optional_user(authorization: Optional[str] = Header(None)) -> Optional[User]:
    """可选登录依赖：Authorization 头存在且有效则返回 User，否则返回 None。
    使用 Depends(lambda) 无法让 FastAPI 注入 Header，必须用正式依赖函数。
    """
    if not authorization:
        return None
    try:
        return _get_current_user(authorization)
    except HTTPException:
        return None


# ── DTOs ─────────────────────────────────────────────────────


class RegisterDTO(BaseModel):
    username: str = Field(..., min_length=2, max_length=64)
    password: str = Field(..., min_length=6)
    email: str = Field(..., min_length=5, max_length=128, description="必填，用于接收验证码")
    verification_code: str = Field(..., min_length=4, max_length=16, description="邮箱验证码")


class LoginDTO(BaseModel):
    username: str
    password: str


class SendCodeDTO(BaseModel):
    email: str


class LoginWithCodeDTO(BaseModel):
    email: str
    code: str


class RefreshTokenDTO(BaseModel):
    refresh_token: str


class ResetPasswordDTO(BaseModel):
    email: str
    code: str = Field(..., min_length=4, max_length=16)
    new_password: str = Field(..., min_length=6, max_length=128)


class AdminResetUserPasswordDTO(BaseModel):
    """线下运维：凭 MODSTORE_ADMIN_RECHARGE_TOKEN 重置指定用户密码（无邮件场景）。"""

    username: str = Field(..., min_length=1, max_length=64)
    new_password: str = Field(..., min_length=6, max_length=128)


class RechargeDTO(BaseModel):
    amount: float = Field(..., gt=0)
    description: str = ""
    recharge_token: str = ""


class AdminSelfCreditDTO(BaseModel):
    """管理员为本人钱包加款（无共享 Token）；金额上限见环境变量。"""

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


def _normalize_email(raw: str) -> str:
    return (raw or "").strip().lower()


def _delete_unused_verification_code(email: str, code: str) -> None:
    """发信失败时删除未使用的一条验证码，避免用户拿到无效码。"""
    sf = get_session_factory()
    with sf() as session:
        session.query(VerificationCode).filter(
            VerificationCode.email == email,
            VerificationCode.code == code,
            VerificationCode.used == False,
        ).delete(synchronize_session=False)
        session.commit()


def _background_send_verification_email(email: str, code: str, purpose: str) -> None:
    import logging

    try:
        send_verification_email(email, code, purpose)
    except Exception:
        logging.exception(
            "Background verification email failed email=%s purpose=%s",
            email,
            purpose,
        )
        try:
            _delete_unused_verification_code(email, code)
        except Exception:
            logging.exception("Failed to remove verification code after email failure")


def _verify_and_consume_verification_code(email: str, code: str) -> None:
    """校验并作废一条未过期的邮箱验证码（email 须已小写归一化）。"""
    code = (code or "").strip()
    if not code:
        raise HTTPException(400, "请填写验证码")
    sf = get_session_factory()
    with sf() as session:
        vc = (
            session.query(VerificationCode)
            .filter(
                VerificationCode.email == email,
                VerificationCode.code == code,
                VerificationCode.used == False,
                VerificationCode.expires_at > datetime.now(timezone.utc),
            )
            .order_by(VerificationCode.created_at.desc())
            .first()
        )
        if not vc:
            raise HTTPException(401, "验证码无效或已过期")
        vc.used = True
        session.commit()


# ── Auth endpoints ───────────────────────────────────────────


@router.post("/auth/register")
def api_register(body: RegisterDTO):
    email_norm = _normalize_email(body.email)
    if not email_norm or "@" not in email_norm:
        raise HTTPException(400, "请填写有效邮箱")
    vcode = (body.verification_code or "").strip()
    if not vcode:
        raise HTTPException(400, "请填写邮箱验证码，并先通过「获取验证码」收取邮件")
    _verify_and_consume_verification_code(email_norm, vcode)
    try:
        user = register_user(body.username, body.password, email_norm)
    except ValueError as e:
        raise HTTPException(409, str(e))
    access_token = create_access_token(user.id, user.username, is_admin=bool(user.is_admin))
    refresh_token = create_refresh_token(user.id, user.username)
    return {
        "ok": True,
        "access_token": access_token,
        "refresh_token": refresh_token,
        "user": {
            "id": user.id,
            "username": user.username,
            "email": user.email,
            "is_admin": bool(user.is_admin),
            "is_enterprise": bool(getattr(user, "is_enterprise", False)),
            "company": getattr(user, "company", "") or "",
        },
    }


@router.post("/auth/login")
def api_login(body: LoginDTO):
    user = authenticate_user(body.username, body.password)
    if not user:
        raise HTTPException(401, "用户名或密码错误")
    access_token = create_access_token(user.id, user.username, is_admin=bool(user.is_admin))
    refresh_token = create_refresh_token(user.id, user.username)
    return {
        "ok": True,
        "access_token": access_token,
        "refresh_token": refresh_token,
        "user": {
            "id": user.id,
            "username": user.username,
            "email": user.email,
            "is_admin": bool(user.is_admin),
            "is_enterprise": bool(getattr(user, "is_enterprise", False)),
            "company": getattr(user, "company", "") or "",
        },
    }


@router.get("/auth/me")
def api_me(user: Optional[User] = Depends(_get_optional_user)):
    # 未登录用 200，避免 SPA 控制台刷 401（语义由 ok/success 表达）。
    if not user:
        return {"ok": False, "success": False, "error": "请先登录"}
    # 经验值与等级档由前端导航栏 / 设置页直接消费；缺失会导致用户停在 Lv.1
    exp = int(getattr(user, "experience", 0) or 0)
    level_profile = account_level_service.build_level_profile(exp).to_dict()
    from modstore_server.user_avatar_service import public_avatar_url_for_user

    return {
        "id": user.id,
        "username": user.username,
        "email": user.email,
        "is_admin": user.is_admin,
        "is_enterprise": bool(getattr(user, "is_enterprise", False)),
        "company": getattr(user, "company", "") or "",
        "created_at": user.created_at.isoformat() if user.created_at else "",
        "experience": exp,
        "level_profile": level_profile,
        "avatar_url": public_avatar_url_for_user(user),
    }


@router.post("/auth/send-code", status_code=202)
def api_send_code(body: SendCodeDTO, background_tasks: BackgroundTasks):
    email_norm = _normalize_email(body.email)
    if not email_norm:
        raise HTTPException(400, "请填写邮箱")

    user = find_user_by_email(email_norm)
    if not user:
        raise HTTPException(404, "该邮箱未注册")

    try:
        assert_email_outbound_configured()
    except RuntimeError as e:
        raise HTTPException(500, str(e))

    code = generate_verification_code()
    sf = get_session_factory()
    with sf() as session:
        vc = VerificationCode(
            email=email_norm,
            code=code,
            expires_at=datetime.now(timezone.utc) + timedelta(minutes=5),
        )
        session.add(vc)
        session.commit()

    background_tasks.add_task(_background_send_verification_email, email_norm, code, "login")

    return {
        "ok": True,
        "message": "验证码已受理，邮件正在发送（约数秒内送达），5 分钟内有效",
        "queued": True,
    }


@router.post("/auth/send-register-code", status_code=202)
def api_send_register_code(body: SendCodeDTO, background_tasks: BackgroundTasks):
    """向未注册邮箱发送注册验证码：先 202 落库，再异步 SMTP。"""
    email_norm = _normalize_email(body.email)
    if not email_norm:
        raise HTTPException(400, "请填写邮箱")

    if find_user_by_email(email_norm):
        raise HTTPException(409, "该邮箱已注册")

    try:
        assert_email_outbound_configured()
    except RuntimeError as e:
        raise HTTPException(500, str(e))

    code = generate_verification_code()
    sf = get_session_factory()
    with sf() as session:
        vc = VerificationCode(
            email=email_norm,
            code=code,
            expires_at=datetime.now(timezone.utc) + timedelta(minutes=5),
        )
        session.add(vc)
        session.commit()

    background_tasks.add_task(_background_send_verification_email, email_norm, code, "register")

    return {
        "ok": True,
        "message": "验证码已受理，邮件正在发送（约数秒内送达），5 分钟内有效",
        "queued": True,
    }


@router.post("/auth/login-with-code")
def api_login_with_code(body: LoginWithCodeDTO):
    email_norm = _normalize_email(body.email)
    if not email_norm:
        raise HTTPException(400, "请填写邮箱")

    user = find_user_by_email(email_norm)
    if not user:
        raise HTTPException(404, "该邮箱未注册")

    sf = get_session_factory()
    with sf() as session:
        vc = (
            session.query(VerificationCode)
            .filter(
                VerificationCode.email == email_norm,
                VerificationCode.code == (body.code or "").strip(),
                VerificationCode.used == False,
                VerificationCode.expires_at > datetime.now(timezone.utc),
            )
            .order_by(VerificationCode.created_at.desc())
            .first()
        )
        if not vc:
            raise HTTPException(401, "验证码无效或已过期")

        vc.used = True
        session.commit()

    access_token = create_access_token(user.id, user.username, is_admin=bool(user.is_admin))
    refresh_token = create_refresh_token(user.id, user.username)
    return {
        "ok": True,
        "access_token": access_token,
        "refresh_token": refresh_token,
        "user": {"id": user.id, "username": user.username, "email": user.email},
    }


@router.post("/auth/send-reset-password-code", status_code=202)
def api_send_reset_password_code(body: SendCodeDTO, background_tasks: BackgroundTasks):
    """忘记密码：向已注册邮箱发送验证码（未注册邮箱返回相同提示，不泄露是否存在）。"""
    email_norm = _normalize_email(body.email)
    if not email_norm:
        raise HTTPException(400, "请填写邮箱")
    user = find_user_by_email(email_norm)
    if not user:
        return {
            "ok": True,
            "message": "如果该邮箱已注册，将收到验证码邮件",
            "queued": True,
        }
    try:
        assert_email_outbound_configured()
    except RuntimeError as e:
        raise HTTPException(500, str(e))

    code = generate_verification_code()
    sf = get_session_factory()
    with sf() as session:
        vc = VerificationCode(
            email=email_norm,
            code=code,
            expires_at=datetime.now(timezone.utc) + timedelta(minutes=10),
        )
        session.add(vc)
        session.commit()

    background_tasks.add_task(_background_send_verification_email, email_norm, code, "reset")

    return {
        "ok": True,
        "message": "如果该邮箱已注册，将收到验证码邮件",
        "queued": True,
    }


@router.post("/auth/reset-password")
def api_reset_password(body: ResetPasswordDTO):
    email_norm = _normalize_email(body.email)
    if not email_norm:
        raise HTTPException(400, "请填写邮箱")
    _verify_and_consume_verification_code(email_norm, body.code)
    u = find_user_by_email(email_norm)
    if not u:
        raise HTTPException(404, "用户不存在")
    sf = get_session_factory()
    with sf() as session:
        row = session.query(User).filter(User.id == u.id).first()
        if not row:
            raise HTTPException(404, "用户不存在")
        row.password_hash = hash_password(body.new_password)
        session.commit()
    return {"ok": True}


class ProfileUpdateDTO(BaseModel):
    username: str | None = Field(None, min_length=2, max_length=64)
    company: str | None = Field(None, max_length=256)


class PasswordChangeDTO(BaseModel):
    current_password: str = Field(..., min_length=1)
    new_password: str = Field(..., min_length=6, max_length=128)


@router.put("/auth/profile")
def api_update_profile(body: ProfileUpdateDTO, user: User = Depends(_get_current_user)):
    un = (body.username or "").strip() if body.username is not None else ""
    company = (body.company or "").strip() if body.company is not None else None
    sf = get_session_factory()
    with sf() as session:
        row = session.query(User).filter(User.id == user.id).first()
        if not row:
            raise HTTPException(404, "用户不存在")
        if un:
            taken = session.query(User).filter(User.username == un, User.id != user.id).first()
            if taken:
                raise HTTPException(409, "用户名已被占用")
            row.username = un
        if company is not None:
            row.company = company[:256]
        session.commit()
    return {
        "ok": True,
        "username": row.username,
        "company": getattr(row, "company", "") or "",
    }


@router.post("/auth/change-password")
def api_change_password(body: PasswordChangeDTO, user: User = Depends(_get_current_user)):
    sf = get_session_factory()
    with sf() as session:
        row = session.query(User).filter(User.id == user.id).first()
        if not row:
            raise HTTPException(404, "用户不存在")
        if not verify_password(body.current_password, row.password_hash):
            raise HTTPException(400, "当前密码不正确")
        row.password_hash = hash_password(body.new_password)
        session.commit()
    return {"ok": True}


@router.post("/admin/reset-user-password")
def api_admin_reset_user_password(
    body: AdminResetUserPasswordDTO,
    request: Request,
):
    """凭 ``MODSTORE_ADMIN_RECHARGE_TOKEN`` 重置用户密码；请求头 ``X-Modstore-Recharge-Token`` 与钱包直充一致。"""
    admin_token = (os.environ.get("MODSTORE_ADMIN_RECHARGE_TOKEN") or "").strip()
    if not admin_token:
        raise HTTPException(503, "未配置 MODSTORE_ADMIN_RECHARGE_TOKEN，无法执行管理员密码重置")
    client_token = (request.headers.get("X-Modstore-Recharge-Token") or "").strip()
    if client_token != admin_token:
        raise HTTPException(403, "无效的管理员授权")

    un = (body.username or "").strip()
    if not un:
        raise HTTPException(400, "请填写用户名")

    sf = get_session_factory()
    with sf() as session:
        row = session.query(User).filter(User.username == un).first()
        if not row:
            raise HTTPException(404, "用户不存在")
        row.password_hash = hash_password(body.new_password)
        session.commit()
    return {"ok": True}


@router.post("/auth/refresh")
def api_refresh_token(body: RefreshTokenDTO):
    """使用刷新令牌获取新的访问令牌"""
    refresh_token = body.refresh_token
    if not refresh_token:
        raise HTTPException(400, "缺少刷新令牌")

    payload = decode_refresh_token(refresh_token)
    if not payload:
        raise HTTPException(401, "刷新令牌无效或已过期")

    user_id = int(payload["sub"])
    username = payload["username"]

    # 验证用户是否存在
    user = get_user_by_id(user_id)
    if not user:
        raise HTTPException(401, "用户不存在")

    # 生成新的访问令牌和刷新令牌
    new_access_token = create_access_token(user_id, username, is_admin=bool(user.is_admin))
    new_refresh_token = create_refresh_token(user_id, username)

    return {
        "ok": True,
        "access_token": new_access_token,
        "refresh_token": new_refresh_token,
        "user": {"id": user.id, "username": user.username, "email": user.email},
    }


@router.get("/admin/status")
def api_admin_status(user: User = Depends(_require_admin)):
    """管理员状态检查。"""
    sf = get_session_factory()
    with sf() as session:
        total_items = session.query(CatalogItem).count()
        total_users = session.query(User).count()
        return {
            "ok": True,
            "is_admin": True,
            "total_catalog_items": total_items,
            "total_users": total_users,
        }


@router.get("/admin/ops-ssh-hint")
def api_admin_ops_ssh_hint(user: User = Depends(_require_admin)):
    """运维终端 SSH 连接信息（仅管理员；凭据来自环境变量，勿写入前端）。"""
    host = (os.environ.get("MODSTORE_OPS_SSH_HOST") or "119.27.178.147").strip()
    user_name = (os.environ.get("MODSTORE_OPS_SSH_USER") or "root").strip()
    password = (os.environ.get("MODSTORE_OPS_SSH_PASSWORD") or "").strip()
    command = (
        os.environ.get("MODSTORE_OPS_SSH_COMMAND") or ""
    ).strip() or f"ssh -o StrictHostKeyChecking=no {user_name}@{host}"
    return {
        "ok": True,
        "command": command,
        "password": password,
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
        return {
            "balance": wallet.balance,
            "updated_at": wallet.updated_at.isoformat() if wallet.updated_at else "",
        }


@router.post("/wallet/recharge")
def api_wallet_recharge(
    body: RechargeDTO,
    request: Request,
    user: User = Depends(_get_current_user),
):
    """管理员线下直充（需密钥）。用户日常充值请使用「支付宝」在钱包页发起。"""
    if not user.is_admin:
        raise HTTPException(403, "仅管理员可使用 Token 直充接口，且只能为当前登录账号加款")
    admin_token = (os.environ.get("MODSTORE_ADMIN_RECHARGE_TOKEN") or "").strip()
    if not admin_token:
        raise HTTPException(503, "未配置 MODSTORE_ADMIN_RECHARGE_TOKEN，无法直充")
    client_token = (request.headers.get("X-Modstore-Recharge-Token") or "").strip() or (
        body.recharge_token or ""
    ).strip()
    if client_token != admin_token:
        raise HTTPException(403, "无效的充值授权")

    sf = get_session_factory()
    with sf() as session:
        wallet = session.query(Wallet).filter(Wallet.user_id == user.id).with_for_update().first()
        if not wallet:
            wallet = Wallet(user_id=user.id, balance=0.0)
            session.add(wallet)
            session.flush()
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


def _admin_self_credit_cap() -> float:
    raw = (os.environ.get("MODSTORE_ADMIN_SELF_CREDIT_CAP") or "").strip()
    if not raw:
        return 100_000.0
    try:
        return max(1.0, float(raw))
    except ValueError:
        return 100_000.0


@router.post("/wallet/admin-self-credit")
def api_wallet_admin_self_credit(body: AdminSelfCreditDTO, user: User = Depends(_get_current_user)):
    """管理员为本人钱包加款（仅 JWT 鉴权，不依赖 MODSTORE_ADMIN_RECHARGE_TOKEN）。"""
    if not user.is_admin:
        raise HTTPException(403, "仅管理员可为本人钱包加款")
    cap = _admin_self_credit_cap()
    if body.amount > cap:
        raise HTTPException(400, f"单次加款不能超过 {cap:g} 元")

    sf = get_session_factory()
    with sf() as session:
        wallet = session.query(Wallet).filter(Wallet.user_id == user.id).with_for_update().first()
        if not wallet:
            wallet = Wallet(user_id=user.id, balance=0.0)
            session.add(wallet)
            session.flush()
        wallet.balance += body.amount
        wallet.updated_at = datetime.now(timezone.utc)
        txn = Transaction(
            user_id=user.id,
            amount=body.amount,
            txn_type="admin_self_credit",
            status="completed",
            description=(body.description or "").strip() or "管理员本人加款",
        )
        session.add(txn)
        session.commit()
        return {"ok": True, "new_balance": wallet.balance, "balance": wallet.balance}


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


# ── Market catalog GET routes ─────────────────────────────────
# NOTE: GET /market/facets, GET /market/catalog, GET /market/catalog/{item_id},
# and GET /market/catalog/{item_id}/reviews are served by market_catalog_api.py,
# which is registered after this router in app_factory.py.
# They were removed here to eliminate the route-shadow bug where this router's
# older/simpler handlers were silently taking priority over the richer ones.
# See: docs/ADR-routes-registry-retirement.md


class ReviewSubmitDTO(BaseModel):
    rating: int = Field(..., ge=1, le=5)
    content: str = Field(default="", max_length=4000)


@router.post("/market/catalog/{item_id}/review")
def api_submit_review(
    item_id: int,
    body: ReviewSubmitDTO,
    user: User = Depends(_get_current_user),
):
    sf = get_session_factory()
    with sf() as session:
        item = session.query(CatalogItem).filter(CatalogItem.id == item_id).first()
        if not item:
            raise HTTPException(404, "商品不存在")
        ent = (
            session.query(Entitlement)
            .filter(
                Entitlement.user_id == user.id,
                Entitlement.catalog_id == item_id,
                Entitlement.is_active == True,
            )
            .first()
        )
        purchase = (
            session.query(Purchase)
            .filter(Purchase.user_id == user.id, Purchase.catalog_id == item_id)
            .first()
        )
        if not ent and not purchase:
            raise HTTPException(403, "购买后方可评价")
        exists = (
            session.query(Review)
            .filter(Review.user_id == user.id, Review.catalog_id == item_id)
            .first()
        )
        if exists:
            raise HTTPException(400, "已评价过")
        session.add(
            Review(
                user_id=user.id,
                catalog_id=item_id,
                rating=int(body.rating),
                content=(body.content or "").strip(),
            )
        )
        session.commit()
    return {"ok": True}


@router.post("/market/catalog/{item_id}/favorite")
def api_toggle_favorite(item_id: int, user: User = Depends(_get_current_user)):
    sf = get_session_factory()
    with sf() as session:
        item = session.query(CatalogItem).filter(CatalogItem.id == item_id).first()
        if not item:
            raise HTTPException(404, "商品不存在")
        existing = (
            session.query(Favorite)
            .filter(Favorite.user_id == user.id, Favorite.catalog_id == item_id)
            .first()
        )
        if existing:
            session.delete(existing)
            session.commit()
            return {"ok": True, "favorited": False}
        session.add(Favorite(user_id=user.id, catalog_id=item_id))
        session.commit()
        return {"ok": True, "favorited": True}


# ── Purchase ─────────────────────────────────────────────────


@router.post("/market/catalog/{item_id}/buy")
def api_buy_item(item_id: int, user: User = Depends(_get_current_user)):
    sf = get_session_factory()
    with sf() as session:
        item = session.query(CatalogItem).filter(CatalogItem.id == item_id).first()
        if not item:
            raise HTTPException(404, "商品不存在")
        if is_planned_duty_employee_pack(item.pkg_id, item.artifact):
            raise HTTPException(404, "商品不存在")
        if item.price <= 0:
            existing = (
                session.query(Purchase)
                .filter(Purchase.user_id == user.id, Purchase.catalog_id == item.id)
                .first()
            )
            from modstore_server.market_shared import _grant_catalog_entitlement

            if existing:
                _grant_catalog_entitlement(
                    session, user_id=user.id, item=item, source="free_catalog"
                )
                session.commit()
                return {"ok": True, "message": "已拥有"}
            purchase = Purchase(user_id=user.id, catalog_id=item.id, amount=0)
            session.add(purchase)
            _grant_catalog_entitlement(session, user_id=user.id, item=item, source="free_catalog")
            session.commit()
            return {"ok": True, "message": "免费领取成功"}

        existing = (
            session.query(Purchase)
            .filter(Purchase.user_id == user.id, Purchase.catalog_id == item.id)
            .first()
        )
        if existing:
            return {"ok": True, "message": "已拥有"}

        wallet = session.query(Wallet).filter(Wallet.user_id == user.id).with_for_update().first()
        if not wallet:
            session.add(Wallet(user_id=user.id, balance=0.0))
            session.flush()
            wallet = (
                session.query(Wallet).filter(Wallet.user_id == user.id).with_for_update().first()
            )
        if not wallet or wallet.balance < item.price:
            raise HTTPException(
                402, f"余额不足，需要 ¥{item.price}，当前 ¥{wallet.balance if wallet else 0}"
            )

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
        if is_planned_duty_employee_pack(item.pkg_id, item.artifact):
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
        from fastapi.responses import StreamingResponse

        from modstore_server.catalog_store import files_dir

        path = files_dir() / item.stored_filename
        if not path.is_file():
            raise HTTPException(404, "文件缺失")

        # 流式下载大文件
        def generate():
            with open(path, "rb") as f:
                while chunk := f.read(8192):
                    yield chunk

        return StreamingResponse(
            generate(),
            media_type="application/zip",
            headers={
                "Content-Disposition": f"attachment; filename={item.pkg_id}.zip",
                "Content-Length": str(path.stat().st_size),
            },
        )


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
                        "artifact": item.artifact or "mod",
                        "price_paid": p.amount,
                        "purchased_at": p.created_at.isoformat() if p.created_at else "",
                    }
                )
        return {"items": items, "total": total}


# ── Admin: upload catalog item with file ─────────────────────


def _catalog_files_dir() -> Path:
    """市场文件存储目录。"""
    d = Path(__file__).resolve().parent / "market_files"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _upload_chunks_dir() -> Path:
    """分块上传临时目录。"""
    d = Path(__file__).resolve().parent / "upload_chunks"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _compute_sha256(file_path: Path) -> str:
    """计算文件 SHA256。"""
    h = hashlib.sha256()
    with file_path.open("rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


class UploadSession(BaseModel):
    """上传会话信息"""

    session_id: str
    file_name: str
    total_size: int
    chunk_size: int
    total_chunks: int


class UploadChunk(BaseModel):
    """文件块信息"""

    session_id: str
    chunk_index: int
    chunk_data: bytes


class CompleteUpload(BaseModel):
    """完成上传请求"""

    session_id: str
    pkg_id: str
    version: str
    name: str
    description: str = ""
    price: float = 0.0
    artifact: str = "mod"
    industry: str = "通用"


class CatalogItemAdminPatchDTO(BaseModel):
    """管理员调整目录行是否进入公开 AI 市场。"""

    is_public: bool


@router.post("/admin/catalog", summary="管理员上传 MOD 到市场（支持文件上传）")
async def api_admin_upload_catalog(
    pkg_id: str = Form(..., min_length=1, max_length=128),
    version: str = Form(..., min_length=1, max_length=32),
    name: str = Form(..., min_length=1, max_length=256),
    description: str = Form(""),
    price: float = Form(0, ge=0),
    artifact: str = Form("mod"),
    industry: str = Form("通用"),
    is_public: bool = Form(False),
    file: UploadFile = File(None),
    user: User = Depends(_require_admin),
):
    sf = get_session_factory()
    with sf() as session:
        existing = (
            session.query(CatalogItem)
            .filter(CatalogItem.pkg_id == pkg_id, CatalogItem.version == version)
            .first()
        )
        if existing:
            raise HTTPException(409, f"pkg_id '{pkg_id}' + version '{version}' 已存在")

        stored_filename = ""
        sha256 = ""

        if file and file.filename:
            suffix = Path(file.filename).suffix.lower()
            if suffix not in {".zip", ".xcmod", ".xcemp"}:
                raise HTTPException(400, "仅支持 .zip / .xcmod / .xcemp 格式")

            dest_dir = _catalog_files_dir()
            dest_name = f"{pkg_id}-{version}{suffix}"
            dest_path = dest_dir / dest_name

            content = await file.read()
            if len(content) > 100 * 1024 * 1024:
                raise HTTPException(400, "文件过大（>100MB）")

            dest_path.write_bytes(content)
            stored_filename = dest_name
            sha256 = _compute_sha256(dest_path)

        ind = (industry or "").strip() or "通用"
        item = CatalogItem(
            pkg_id=pkg_id,
            version=version,
            name=name,
            description=description,
            price=price,
            author_id=user.id,
            artifact=artifact,
            industry=ind,
            stored_filename=stored_filename,
            sha256=sha256,
            is_public=bool(is_public),
        )
        session.add(item)
        session.commit()
        session.refresh(item)
        return {
            "ok": True,
            "id": item.id,
            "pkg_id": item.pkg_id,
            "stored_filename": item.stored_filename,
        }


@router.patch("/admin/catalog/{item_id}", summary="更新商品是否对 AI 市场公开展示")
def api_admin_patch_catalog_item(
    item_id: int,
    body: CatalogItemAdminPatchDTO,
    user: User = Depends(_require_admin),
):
    """入库默认不公开展示；需要上架时 ``PATCH {"is_public": true}``。"""
    sf = get_session_factory()
    with sf() as session:
        item = session.query(CatalogItem).filter(CatalogItem.id == item_id).first()
        if not item:
            raise HTTPException(404, "商品不存在")
        item.is_public = bool(body.is_public)
        session.commit()
    from modstore_server.market_catalog_api import _invalidate_market_catalog_caches

    _invalidate_market_catalog_caches()
    return {"ok": True, "id": item_id, "is_public": bool(body.is_public)}


@router.post(
    "/admin/catalog/sync-from-xc-packages", summary="从 XC catalog_store 同步缺失条目到市场库"
)
def api_admin_sync_xc_catalog_packages(user: User = Depends(_require_admin)):
    """将 ``packages.json`` 中尚未出现在 ``catalog_items`` 的包插入数据库（可选复制文件）。"""
    sf = get_session_factory()
    with sf() as session:
        out = catalog_sync.sync_packages_json_to_catalog_items(session, admin_user_id=user.id)
        session.commit()
    return {"ok": True, **out}


@router.get("/admin/catalog")
def api_admin_list_catalog(
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    user: User = Depends(_require_admin),
):
    sf = get_session_factory()
    with sf() as session:
        total = session.query(CatalogItem).count()
        rows = (
            session.query(CatalogItem)
            .order_by(CatalogItem.created_at.desc())
            .offset(offset)
            .limit(limit)
            .all()
        )
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
                    "industry": getattr(r, "industry", None) or "通用",
                    "stored_filename": r.stored_filename,
                    "sha256": r.sha256,
                    "is_public": r.is_public,
                    "created_at": r.created_at.isoformat() if r.created_at else "",
                }
                for r in rows
            ],
            "total": total,
        }


@router.post("/admin/upload/initiate", summary="初始化分块上传")
def api_initiate_upload(
    file_name: str = Form(...),
    total_size: int = Form(...),
    chunk_size: int = Form(...),
    user: User = Depends(_require_admin),
):
    """初始化分块上传会话"""
    import uuid

    session_id = str(uuid.uuid4())
    total_chunks = (total_size + chunk_size - 1) // chunk_size

    # 创建上传会话目录
    session_dir = _upload_chunks_dir() / session_id
    session_dir.mkdir(parents=True, exist_ok=True)

    # 存储会话信息
    session_info = {
        "session_id": session_id,
        "file_name": file_name,
        "total_size": total_size,
        "chunk_size": chunk_size,
        "total_chunks": total_chunks,
        "created_at": datetime.now(timezone.utc).isoformat(),
    }

    with open(session_dir / "session.json", "w", encoding="utf-8") as f:
        json.dump(session_info, f)

    return {"ok": True, "session_id": session_id, "total_chunks": total_chunks}


@router.post("/admin/upload/chunk", summary="上传文件块")
async def api_upload_chunk(
    session_id: str = Form(...),
    chunk_index: int = Form(...),
    file: UploadFile = File(...),
    user: User = Depends(_require_admin),
):
    """上传单个文件块"""
    session_dir = _upload_chunks_dir() / session_id
    if not session_dir.exists():
        raise HTTPException(404, "上传会话不存在")

    # 读取会话信息
    with open(session_dir / "session.json", "r", encoding="utf-8") as f:
        session_info = json.load(f)

    if chunk_index >= session_info["total_chunks"]:
        raise HTTPException(400, "无效的块索引")

    # 保存文件块
    chunk_path = session_dir / f"chunk_{chunk_index}"
    content = await file.read()

    with open(chunk_path, "wb") as f:
        f.write(content)

    return {"ok": True, "chunk_index": chunk_index}


@router.post("/admin/upload/complete", summary="完成分块上传")
def api_complete_upload(
    session_id: str = Form(...),
    pkg_id: str = Form(...),
    version: str = Form(...),
    name: str = Form(...),
    description: str = Form(""),
    price: float = Form(0.0),
    artifact: str = Form("mod"),
    industry: str = Form("通用"),
    is_public: bool = Form(False),
    user: User = Depends(_require_admin),
):
    """完成分块上传并合并文件"""
    session_dir = _upload_chunks_dir() / session_id
    if not session_dir.exists():
        raise HTTPException(404, "上传会话不存在")

    # 读取会话信息
    with open(session_dir / "session.json", "r", encoding="utf-8") as f:
        session_info = json.load(f)

    # 检查所有块是否上传完成
    missing_chunks = []
    for i in range(session_info["total_chunks"]):
        chunk_path = session_dir / f"chunk_{i}"
        if not chunk_path.exists():
            missing_chunks.append(i)

    if missing_chunks:
        raise HTTPException(400, f"缺少文件块: {missing_chunks}")

    # 合并文件
    suffix = Path(session_info["file_name"]).suffix.lower()
    if suffix not in {".zip", ".xcmod", ".xcemp"}:
        raise HTTPException(400, "仅支持 .zip / .xcmod / .xcemp 格式")

    dest_dir = _catalog_files_dir()
    dest_name = f"{pkg_id}-{version}{suffix}"
    dest_path = dest_dir / dest_name

    # 合并所有块
    with open(dest_path, "wb") as out_file:
        for i in range(session_info["total_chunks"]):
            chunk_path = session_dir / f"chunk_{i}"
            with open(chunk_path, "rb") as in_file:
                out_file.write(in_file.read())

    # 计算文件哈希
    sha256 = _compute_sha256(dest_path)

    # 清理临时文件
    import shutil

    shutil.rmtree(session_dir)

    # 保存到数据库
    sf = get_session_factory()
    with sf() as session:
        existing = (
            session.query(CatalogItem)
            .filter(CatalogItem.pkg_id == pkg_id, CatalogItem.version == version)
            .first()
        )
        if existing:
            raise HTTPException(409, f"pkg_id '{pkg_id}' + version '{version}' 已存在")

        ind = (industry or "").strip() or "通用"
        item = CatalogItem(
            pkg_id=pkg_id,
            version=version,
            name=name,
            description=description,
            price=price,
            author_id=user.id,
            artifact=artifact,
            industry=ind,
            stored_filename=dest_name,
            sha256=sha256,
            is_public=bool(is_public),
        )
        session.add(item)
        session.commit()
        session.refresh(item)

        return {
            "ok": True,
            "id": item.id,
            "pkg_id": item.pkg_id,
            "stored_filename": item.stored_filename,
            "file_size": session_info["total_size"],
        }


@router.delete("/admin/catalog/{item_id}")
def api_admin_delete_catalog(item_id: int, user: User = Depends(_require_admin)):
    """管理员下架商品（幂等 soft-delete）。

    - 不再 hard delete 行：``Purchase`` / ``Review`` / ``Favorite`` / ``Entitlement``
      均通过 ``ForeignKey(catalog_items.id)`` 引用本表（部分 ``nullable=False``），
      硬删会破坏对账与历史，且重复点击会立即触发 404。
    - 改为打 ``compliance_status='delisted'`` + ``is_public=False``：公开目录
      （``CatalogItem.compliance_status != 'delisted'``）即不再展示，
      与前端按钮文案 “下架后 AI 市场将不再展示该商品” 语义一致。
    - 同步从 ``packages.json``（``/v1/packages`` 数据源）移除条目，删除其下
      ``catalog_data/files/`` 中的二进制；``market_files/`` 中的副本保留以便
      管理员后续 ``restore``。
    - 幂等：行不存在或已下架时返回 ``ok: True`` 且不报 404，避免前端列表因
      60s 缓存或多实例 (``upstream modstore_api``) 视图差异在重复点击时失败。
    """
    from modstore_server import catalog_store

    sf = get_session_factory()
    with sf() as session:
        item = session.query(CatalogItem).filter(CatalogItem.id == item_id).first()
        if not item:
            return {
                "ok": True,
                "deleted_id": item_id,
                "already_missing": True,
                "already_delisted": False,
                "removed_catalog_store": 0,
            }

        already_delisted = (item.compliance_status or "") == "delisted"
        pkg_id = item.pkg_id or ""

        if not already_delisted:
            item.is_public = False
            item.compliance_status = "delisted"
            item.delist_reason = "管理员手动下架"
            item.rank_score = 0.0
            session.commit()

    n_json = catalog_store.remove_package(pkg_id, version=None) if pkg_id else 0

    try:
        from modstore_server.market_catalog_api import _invalidate_market_catalog_caches

        _invalidate_market_catalog_caches()
    except Exception:
        pass

    return {
        "ok": True,
        "deleted_id": item_id,
        "already_missing": False,
        "already_delisted": already_delisted,
        "removed_catalog_store": n_json,
    }


@router.delete("/admin/employee-packs/{pkg_id:path}")
def api_admin_delete_employee_pack(pkg_id: str, user: User = Depends(_require_admin)):
    """删除员工包：清掉本地 ``/v1`` catalog（``packages.json`` + ``files/``）中该 ``pkg_id`` 全部版本，并删除 ``catalog_items`` 中 ``artifact=employee_pack`` 的登记行。"""
    from modstore_server import catalog_store
    from modstore_server.duty_roster import all_planned_employee_ids

    pid = catalog_store.norm_pkg_id(pkg_id)
    if not pid:
        raise HTTPException(400, "pkg_id 无效")
    if pid in all_planned_employee_ids():
        raise HTTPException(
            403,
            "该员工包属于编制在岗岗位（duty_roster / 员工工作流管理矩阵），禁止删除。"
            "若确需移除，请先从 yuangon 编制与 duty_roster.py 中调整岗位列表后再操作。",
        )

    n_json = catalog_store.remove_package(pid, version=None)
    removed_db = False
    sf = get_session_factory()
    with sf() as session:
        rows = session.query(CatalogItem).filter(CatalogItem.artifact == "employee_pack").all()
        to_delete = [x for x in rows if catalog_store.norm_pkg_id(x.pkg_id) == pid]
        for item in to_delete:
            if item.stored_filename:
                file_path = _catalog_files_dir() / item.stored_filename
                if file_path.is_file():
                    file_path.unlink()
            session.delete(item)
        if to_delete:
            session.commit()
            removed_db = True
    # 幂等：列表已刷新或重复点击删除时，本地与库可能均已无记录，不再报 404
    return {
        "ok": True,
        "removed_catalog_store": n_json,
        "removed_db": removed_db,
        "already_absent": n_json == 0 and not removed_db,
    }


@router.post("/admin/employee-packs/align-llm-from-deepseek")
async def api_admin_align_employee_llm_from_deepseek(
    dry_run: bool = Query(False, description="为 true 时只返回将要修改的内容，不写库"),
    user: User = Depends(_require_admin),
):
    """把仍为 ``provider=deepseek`` 的员工包批量改为当前环境下首个可用 LLM（平台密钥或作者 BYOK），并执行与 employee-save 相同的落盘。"""
    from modstore_server.employee_pack_deepseek_align import (
        align_catalog_employee_packs_llm_from_deepseek,
    )

    return await align_catalog_employee_packs_llm_from_deepseek(user, dry_run=dry_run)


@router.post("/admin/employee-packs/align-llm-to-auto")
async def api_admin_align_employee_llm_to_auto(
    dry_run: bool = Query(False, description="为 true 时只返回将要修改的内容，不写库"),
    user: User = Depends(_require_admin),
):
    """把仍为 ``provider=deepseek`` 的员工包改为 manifest 内 ``provider=model_name=auto``（工作台「自动」），与 employee-save 相同落盘。"""
    from modstore_server.employee_pack_deepseek_align import (
        align_catalog_employee_packs_llm_to_auto_sentinel,
    )

    return await align_catalog_employee_packs_llm_to_auto_sentinel(user, dry_run=dry_run)


@router.post("/admin/employee-packs/{pkg_id}/align-llm-to-auto-single")
async def api_admin_align_single_employee_llm_to_auto(
    pkg_id: str,
    dry_run: bool = Query(False, description="为 true 时只返回将要修改的内容，不写库"),
    user: User = Depends(_require_admin),
):
    """单个员工包的 LLM 绑定改为 ``provider=model_name=auto``，不再受 provider==deepseek 过滤。

    用于「无密钥」修复路径：管理员在 dg-stats 上直接点单条「改为自动」时调用。
    """
    from modstore_server.employee_pack_deepseek_align import align_single_employee_pack_llm_to_auto

    result = await align_single_employee_pack_llm_to_auto(user, pkg_id, dry_run=dry_run)
    if not result.get("ok"):
        raise HTTPException(400, str(result.get("error") or "对齐失败"))
    return result


@router.post("/admin/employee-packs/purge-all")
def api_admin_purge_all_employee_packs(user: User = Depends(_require_admin)):
    """一键清空所有员工包：``packages.json`` 中 ``artifact=employee_pack`` 全部行 +
    ``files/`` 下对应文件 + ``catalog_items`` 中 ``artifact=employee_pack`` 全部行。

    比前端循环逐条删更彻底——之前出现的「老是删不完」是因为 packages.json 与
    数据库登记两边的 pkg_id 不重合（以及 norm_pkg_id 归一化差异），逐条对账时
    会遗漏一边，这里统一在后端原子清空。"""
    from modstore_server import catalog_store

    removed_packages = 0
    removed_files = 0
    with catalog_store._lock:  # type: ignore[attr-defined]
        data = catalog_store.load_store()
        kept = []
        for r in data.get("packages") or []:
            if str((r or {}).get("artifact") or "") == "employee_pack":
                fn = str((r or {}).get("stored_filename") or "").strip()
                if fn:
                    p = catalog_store.files_dir() / fn
                    if p.is_file():
                        try:
                            p.unlink()
                            removed_files += 1
                        except OSError:
                            pass
                removed_packages += 1
                continue
            kept.append(r)
        data["packages"] = kept
        catalog_store.save_store(data)

    removed_db = 0
    sf = get_session_factory()
    with sf() as session:
        rows = session.query(CatalogItem).filter(CatalogItem.artifact == "employee_pack").all()
        for item in rows:
            stored = (item.stored_filename or "").strip()
            if stored:
                p = _catalog_files_dir() / stored
                if p.is_file():
                    try:
                        p.unlink()
                        removed_files += 1
                    except OSError:
                        pass
            session.delete(item)
        if rows:
            session.commit()
            removed_db = len(rows)

    return {
        "ok": True,
        "removed_packages_json": removed_packages,
        "removed_db_rows": removed_db,
        "removed_files": removed_files,
    }


@router.post("/admin/mods/purge-all")
def api_admin_purge_all_mods(user: User = Depends(_require_admin)):
    """一键清空 mod 源码库：删除 ``library/`` 下所有 mod 目录（仅限带 manifest.json
    的子目录），并截断 ``user_mods`` 关联表。

    用于「重置仓库」语义——前端列表合并了多个数据源，逐条删除容易因 list 缓存、
    norm 不一致、user_mods 关联残留导致「老是删不完」。这里一次性原子清空。"""
    from modman.repo_config import load_config, resolved_library
    from modman.store import iter_mod_dirs
    from modstore_server.models import UserMod

    lib = resolved_library(load_config())
    removed_dirs: List[str] = []
    if lib.is_dir():
        for d in list(iter_mod_dirs(lib)):
            try:
                shutil.rmtree(d, ignore_errors=False)
                removed_dirs.append(d.name)
            except OSError:
                pass

    sf = get_session_factory()
    with sf() as session:
        removed_user_mod_rows = session.query(UserMod).delete()
        session.commit()

    return {
        "ok": True,
        "removed_dirs": removed_dirs,
        "removed_dir_count": len(removed_dirs),
        "removed_user_mod_rows": int(removed_user_mod_rows or 0),
    }


@router.get("/admin/users")
def api_admin_list_users(
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    is_enterprise: bool | None = Query(None, description="true=仅企业级，false=仅非企业级"),
    user: User = Depends(_require_admin),
):
    sf = get_session_factory()
    with sf() as session:
        q = session.query(User)
        if is_enterprise is True:
            q = q.filter(User.is_enterprise.is_(True))
        elif is_enterprise is False:
            q = q.filter(User.is_enterprise.is_(False))
        total = q.count()
        rows = q.order_by(User.created_at.desc()).offset(offset).limit(limit).all()
        uid_list = [int(r.id) for r in rows]
        mod_map = _user_mod_ids_map(uid_list)
        return {
            "users": [
                {
                    "id": r.id,
                    "username": r.username,
                    "email": r.email,
                    "is_admin": r.is_admin,
                    "is_enterprise": bool(getattr(r, "is_enterprise", False)),
                    "mod_ids": mod_map.get(int(r.id), []),
                    "created_at": r.created_at.isoformat() if r.created_at else "",
                }
                for r in rows
            ],
            "total": total,
        }


@router.put("/admin/users/{user_id}/admin")
def api_admin_set_admin_status(
    user_id: int,
    is_admin: bool = Query(...),
    user: User = Depends(_require_admin),
):
    sf = get_session_factory()
    with sf() as session:
        target = session.query(User).filter(User.id == user_id).first()
        if not target:
            raise HTTPException(404, "用户不存在")
        target.is_admin = is_admin
        session.commit()
        return {"ok": True, "user_id": user_id, "is_admin": is_admin}


@router.put("/admin/users/{user_id}/enterprise")
def api_admin_set_enterprise_status(
    user_id: int,
    is_enterprise: bool = Query(...),
    user: User = Depends(_require_admin),
):
    sf = get_session_factory()
    with sf() as session:
        target = session.query(User).filter(User.id == user_id).first()
        if not target:
            raise HTTPException(404, "用户不存在")
        target.is_enterprise = is_enterprise
        session.commit()
        return {"ok": True, "user_id": user_id, "is_enterprise": is_enterprise}


@router.get("/admin/enterprise/assignable-mods")
def api_admin_enterprise_assignable_mods(user: User = Depends(_require_admin)):
    """返回管理员可分配给企业的客户 Mod 列表。"""
    mods = [
        {"id": mid, "name": ENTERPRISE_ASSIGNABLE_MODS[mid]}
        for mid in sorted(_enterprise_assignable_mod_ids())
    ]
    return {"ok": True, "mods": mods}


@router.get("/admin/users/{user_id}/mods")
def api_admin_list_user_mods(
    user_id: int,
    user: User = Depends(_require_admin),
):
    from modstore_server.models_db import get_user_mod_ids

    sf = get_session_factory()
    with sf() as session:
        target = session.query(User).filter(User.id == user_id).first()
        if not target:
            raise HTTPException(404, "用户不存在")
    mod_ids = sorted(get_user_mod_ids(user_id))
    return {
        "ok": True,
        "user_id": user_id,
        "username": target.username,
        "is_enterprise": bool(getattr(target, "is_enterprise", False)),
        "mod_ids": mod_ids,
    }


@router.post("/admin/users/{user_id}/mods/{mod_id}")
def api_admin_bind_user_mod(
    user_id: int,
    mod_id: str,
    user: User = Depends(_require_admin),
):
    """将 Mod 绑定到用户 user_mods（企业版桌面 entitlement 数据源）。"""
    from modstore_server.models_db import add_user_mod

    mid = _assert_enterprise_assignable_mod_id(mod_id)
    sf = get_session_factory()
    with sf() as session:
        if session.query(User).filter(User.id == user_id).first() is None:
            raise HTTPException(404, "用户不存在")
    add_user_mod(user_id, mid)
    return {"ok": True, "user_id": user_id, "mod_id": mid}


@router.delete("/admin/users/{user_id}/mods/{mod_id}")
def api_admin_unbind_user_mod(
    user_id: int,
    mod_id: str,
    user: User = Depends(_require_admin),
):
    from modstore_server.models_db import remove_user_mod

    mid = _assert_enterprise_assignable_mod_id(mod_id)
    sf = get_session_factory()
    with sf() as session:
        if session.query(User).filter(User.id == user_id).first() is None:
            raise HTTPException(404, "用户不存在")
    remove_user_mod(user_id, mid)
    return {"ok": True, "user_id": user_id, "mod_id": mid}


@router.get("/enterprise/entitled-mod-ids")
def api_enterprise_entitled_mod_ids(user: User = Depends(get_current_user)):
    """企业版桌面专用：仅返回 user_mods 绑定的 Mod id（不因 is_admin 返回全库）。"""
    from modstore_server.models_db import get_user_mod_ids

    mod_ids = sorted(get_user_mod_ids(user.id))
    return {
        "ok": True,
        "user_id": user.id,
        "username": user.username,
        "mod_ids": mod_ids,
    }


@router.get("/admin/wallets")
def api_admin_list_wallets(
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
    user: User = Depends(_require_admin),
):
    sf = get_session_factory()
    with sf() as session:
        total = session.query(Wallet).count()
        rows = session.query(Wallet).order_by(Wallet.id).offset(offset).limit(limit).all()
        return {
            "items": [
                {
                    "id": w.id,
                    "user_id": w.user_id,
                    "balance": w.balance,
                    "updated_at": w.updated_at.isoformat() if w.updated_at else "",
                }
                for w in rows
            ],
            "total": total,
        }


@router.get("/admin/transactions")
def api_admin_list_transactions(
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
    user: User = Depends(_require_admin),
):
    sf = get_session_factory()
    with sf() as session:
        total = session.query(Transaction).count()
        rows = (
            session.query(Transaction)
            .order_by(Transaction.created_at.desc())
            .offset(offset)
            .limit(limit)
            .all()
        )
        return {
            "items": [
                {
                    "id": t.id,
                    "user_id": t.user_id,
                    "amount": t.amount,
                    "txn_type": t.txn_type,
                    "status": t.status,
                    "description": t.description,
                    "created_at": t.created_at.isoformat() if t.created_at else "",
                }
                for t in rows
            ],
            "total": total,
        }


# ── Wallet overview ──────────────────────────────────────────


@router.get("/wallet/overview")
def api_wallet_overview(
    limit: int = Query(20, ge=1, le=200),
    offset: int = Query(0, ge=0),
    user: User = Depends(_get_current_user),
):
    """钱包概览：余额 + 最近交易流水（前端 walletOverview 消费此接口）。"""
    sf = get_session_factory()
    with sf() as session:
        wallet = session.query(Wallet).filter(Wallet.user_id == user.id).first()
        balance = wallet.balance if wallet else 0.0
        updated_at = wallet.updated_at.isoformat() if wallet and wallet.updated_at else ""
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
            "wallet": {
                "balance": balance,
                "updated_at": updated_at,
            },
            "balance": balance,
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


# ── Package audit (standalone) ────────────────────────────────


@router.post("/package-audit")
async def api_package_audit(
    file: UploadFile = File(...),
    metadata: Optional[str] = Form(None),
    user: User = Depends(_get_current_user),
):
    """通用包审计接口（前端 auditPackage 消费此接口）。上传 .zip/.xcemp，返回五维审核结论。"""
    import json as _json

    from modstore_server.package_sandbox_audit import run_package_audit_async

    raw = await file.read()
    meta: dict = {}
    if metadata:
        try:
            meta = _json.loads(metadata)
        except Exception:
            pass
    result = await run_package_audit_async(raw, meta or None)
    return result


# ── Init on import ──────────────────────────────────────────

init_db()
