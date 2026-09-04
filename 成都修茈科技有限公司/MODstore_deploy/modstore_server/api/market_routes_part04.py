# mypy: disable-error-code="valid-type, attr-defined, no-any-return"
"""Implementation extracted from the public facade module."""

from __future__ import annotations

import importlib
import os

import httpx

from modstore_server.operational_errors import RECOVERABLE_ERRORS


def _facade():
    return importlib.import_module("modstore_server.api.market_routes")


@_facade().router.get("/admin/users")
def api_admin_list_users(
    limit: int = _facade().Query(50, ge=1, le=200),
    offset: int = _facade().Query(0, ge=0),
    is_enterprise: bool | None = _facade().Query(
        None, description="true=仅企业级，false=仅非企业级"
    ),
    user: _facade().User = _facade().Depends(_facade()._require_admin),
):
    sf = _facade().get_session_factory()
    with sf() as session:
        q = session.query(_facade().User)
        if is_enterprise is True:
            q = q.filter(_facade().User.is_enterprise.is_(True))
        elif is_enterprise is False:
            q = q.filter(_facade().User.is_enterprise.is_(False))
        total = q.count()
        rows = q.order_by(_facade().User.created_at.desc()).offset(offset).limit(limit).all()
        uid_list = [int(r.id) for r in rows]
        mod_map = _facade()._user_mod_ids_map(uid_list)
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


@_facade().router.put("/admin/users/{user_id}/admin")
def api_admin_set_admin_status(
    user_id: int,
    is_admin: bool = _facade().Query(...),
    user: _facade().User = _facade().Depends(_facade()._require_admin),
):
    sf = _facade().get_session_factory()
    with sf() as session:
        target = session.query(_facade().User).filter(_facade().User.id == user_id).first()
        if not target:
            raise _facade().HTTPException(404, "用户不存在")
        target.is_admin = is_admin
        session.commit()
        return {"ok": True, "user_id": user_id, "is_admin": is_admin}


@_facade().router.put("/admin/users/{user_id}/enterprise")
def api_admin_set_enterprise_status(
    user_id: int,
    is_enterprise: bool = _facade().Query(...),
    user: _facade().User = _facade().Depends(_facade()._require_admin),
):
    sf = _facade().get_session_factory()
    with sf() as session:
        target = session.query(_facade().User).filter(_facade().User.id == user_id).first()
        if not target:
            raise _facade().HTTPException(404, "用户不存在")
        target.is_enterprise = is_enterprise
        target.account_state = (
            _facade().ACCOUNT_ACTIVE if is_enterprise else _facade().ACCOUNT_PENDING_PLAN
        )
        session.commit()
        return {
            "ok": True,
            "user_id": user_id,
            "is_enterprise": is_enterprise,
            **_facade().lifecycle_for_user(session, target).to_dict(),
        }


class EnterpriseIdentityDTO(_facade().BaseModel):
    """Single-assignment legal identity backed by reviewed source material."""

    enterprise_subject_id: str = _facade().Field(..., min_length=4, max_length=128)
    legal_name: str = _facade().Field(..., min_length=2, max_length=256)
    verification_sha256: str = _facade().Field(
        ..., pattern="^[0-9a-fA-F]{64}$"
    )


def _freeze_java_enterprise_identity(
    *, user_id: int, verified_by_user_id: int, subject_id: str, legal_name: str, digest: str
) -> None:
    if os.environ.get("PAYMENT_BACKEND", "").strip().lower() != "java":
        return
    key = (
        os.environ.get("MODSTORE_INTERNAL_API_KEY")
        or os.environ.get("XCAGI_MARKET_INTERNAL_API_KEY")
        or ""
    ).strip()
    if not key:
        raise _facade().HTTPException(503, "Java 支付身份同步密钥未配置")
    base = (
        os.environ.get("JAVA_PAYMENT_SERVICE_URL") or "http://127.0.0.1:8080"
    ).rstrip("/")
    try:
        response = httpx.post(
            f"{base}/api/internal/payment/enterprise-identities",
            headers={"X-Internal-Api-Key": key},
            json={
                "user_id": user_id,
                "verified_by_user_id": verified_by_user_id,
                "enterprise_subject_id": subject_id,
                "legal_name": legal_name,
                "verification_sha256": digest,
            },
            timeout=10.0,
        )
        if response.status_code == 409:
            raise _facade().HTTPException(409, "Java 支付企业主体已冻结且不一致")
        response.raise_for_status()
        payload = response.json()
    except _facade().HTTPException:
        raise
    except (httpx.HTTPError, TypeError, ValueError) as exc:
        raise _facade().HTTPException(503, "Java 支付企业身份同步失败") from exc
    if (
        not isinstance(payload, dict)
        or payload.get("ok") is not True
        or payload.get("source") != "java_postgresql"
        or payload.get("frozen") is not True
        or str(payload.get("enterprise_subject_id") or "") != subject_id
    ):
        raise _facade().HTTPException(503, "Java 支付企业身份同步回执无效")


@_facade().router.put("/admin/users/{user_id}/enterprise-identity")
def api_admin_verify_enterprise_identity(
    user_id: int,
    body: EnterpriseIdentityDTO,
    user: _facade().User = _facade().Depends(_facade()._require_admin),
):
    """Freeze a verified enterprise identity before its qualifying payment.

    Existing identity cannot be replaced through the API.  A correction must
    use a new customer account so historical orders retain their original legal
    entity instead of being silently reassigned.
    """

    subject_id = body.enterprise_subject_id.strip()
    legal_name = body.legal_name.strip()
    digest = body.verification_sha256.lower()
    sf = _facade().get_session_factory()
    with sf() as session:
        target = session.query(_facade().User).filter(_facade().User.id == user_id).first()
        if not target:
            raise _facade().HTTPException(404, "用户不存在")
        if target.is_admin:
            raise _facade().HTTPException(409, "管理员账号不能计为客户企业主体")
        existing = (
            str(getattr(target, "enterprise_subject_id", "") or ""),
            str(getattr(target, "enterprise_legal_name", "") or ""),
            str(getattr(target, "enterprise_verification_sha256", "") or "").lower(),
        )
        requested = (subject_id, legal_name, digest)
        if any(existing) and existing != requested:
            raise _facade().HTTPException(409, "企业主体已冻结，不允许覆盖历史身份")
        _freeze_java_enterprise_identity(
            user_id=user_id,
            verified_by_user_id=int(user.id),
            subject_id=subject_id,
            legal_name=legal_name,
            digest=digest,
        )
        if not any(existing):
            target.enterprise_subject_id = subject_id
            target.enterprise_legal_name = legal_name
            target.enterprise_verification_sha256 = digest
            target.enterprise_verified_at = _facade().datetime.now(
                _facade().timezone.utc
            ).replace(tzinfo=None)
            target.enterprise_verified_by_user_id = int(user.id)
        target.is_enterprise = True
        session.commit()
        return {
            "ok": True,
            "user_id": user_id,
            "enterprise_subject_id": subject_id,
            "legal_name": legal_name,
            "verification_sha256": digest,
            "frozen": True,
        }


@_facade().router.get("/admin/enterprise/assignable-mods")
def api_admin_enterprise_assignable_mods(
    user: _facade().User = _facade().Depends(_facade()._require_admin),
):
    """返回管理员可分配给企业的客户 Mod 列表。"""
    mods = [
        {"id": mid, "name": _facade().ENTERPRISE_ASSIGNABLE_MODS[mid]}
        for mid in sorted(_facade()._enterprise_assignable_mod_ids())
    ]
    return {"ok": True, "mods": mods}


@_facade().router.get("/admin/users/{user_id}/mods")
def api_admin_list_user_mods(
    user_id: int, user: _facade().User = _facade().Depends(_facade()._require_admin)
):
    from modstore_server.models_db import get_user_mod_ids

    sf = _facade().get_session_factory()
    with sf() as session:
        target = session.query(_facade().User).filter(_facade().User.id == user_id).first()
        if not target:
            raise _facade().HTTPException(404, "用户不存在")
    mod_ids = sorted(get_user_mod_ids(user_id))
    return {
        "ok": True,
        "user_id": user_id,
        "username": target.username,
        "is_enterprise": bool(getattr(target, "is_enterprise", False)),
        "mod_ids": mod_ids,
    }


@_facade().router.post("/admin/users/{user_id}/mods/{mod_id}")
def api_admin_bind_user_mod(
    user_id: int,
    mod_id: str,
    user: _facade().User = _facade().Depends(_facade()._require_admin),
):
    """将 Mod 绑定到用户 user_mods（企业版桌面 entitlement 数据源）。"""
    from modstore_server.models_db import add_user_mod

    mid = _facade()._assert_enterprise_assignable_mod_id(mod_id)
    sf = _facade().get_session_factory()
    with sf() as session:
        if session.query(_facade().User).filter(_facade().User.id == user_id).first() is None:
            raise _facade().HTTPException(404, "用户不存在")
    add_user_mod(user_id, mid)
    return {"ok": True, "user_id": user_id, "mod_id": mid}


@_facade().router.delete("/admin/users/{user_id}/mods/{mod_id}")
def api_admin_unbind_user_mod(
    user_id: int,
    mod_id: str,
    user: _facade().User = _facade().Depends(_facade()._require_admin),
):
    from modstore_server.models_db import remove_user_mod

    mid = _facade()._assert_enterprise_assignable_mod_id(mod_id)
    sf = _facade().get_session_factory()
    with sf() as session:
        if session.query(_facade().User).filter(_facade().User.id == user_id).first() is None:
            raise _facade().HTTPException(404, "用户不存在")
    remove_user_mod(user_id, mid)
    return {"ok": True, "user_id": user_id, "mod_id": mid}


@_facade().router.get("/enterprise/entitled-mod-ids")
def api_enterprise_entitled_mod_ids(
    user: _facade().User = _facade().Depends(_facade().get_current_user),
):
    """企业版桌面专用：仅返回 user_mods 绑定的 Mod id（不因 is_admin 返回全库）。"""
    from modstore_server.models_db import get_user_mod_ids

    mod_ids = sorted(get_user_mod_ids(user.id))
    return {
        "ok": True,
        "user_id": user.id,
        "username": user.username,
        "mod_ids": mod_ids,
    }


@_facade().router.get("/enterprise/customer-delivery-seeds/{pkg_id}/{version}/download")
def api_enterprise_customer_delivery_seed_download(
    pkg_id: str,
    version: str,
    mod_id: str = _facade().Query(""),
    user: _facade().User = _facade().Depends(_facade().get_current_user),
):
    """Download an account-scoped customer seed after enterprise entitlement checks."""
    from fastapi.responses import FileResponse

    from modstore_server.catalog_store import files_dir, get_package
    from modstore_server.models_db import get_user_mod_ids

    pkg = get_package(pkg_id, version)
    if not pkg:
        raise _facade().HTTPException(404, "交付种子包不存在")
    artifact = str(pkg.get("artifact") or "").strip().lower()
    if artifact != "customer_delivery_seed":
        raise _facade().HTTPException(404, "不是客户交付种子包")
    account_mod_id = str(pkg.get("account_mod_id") or "").strip()
    if not account_mod_id:
        raise _facade().HTTPException(403, "交付种子包未绑定客户 Mod")
    requested_mod_id = str(mod_id or account_mod_id).strip()
    if requested_mod_id != account_mod_id:
        raise _facade().HTTPException(403, "交付种子包与请求 Mod 不匹配")
    entitled = set(get_user_mod_ids(int(user.id)))
    if account_mod_id not in entitled:
        raise _facade().HTTPException(403, "当前账号未授权该客户交付包")
    name = str(pkg.get("stored_filename") or "").strip()
    if not name:
        raise _facade().HTTPException(404, "交付种子包无本地文件")
    path = files_dir() / name
    if not path.is_file():
        raise _facade().HTTPException(404, "交付种子文件缺失")
    return FileResponse(path, filename=path.name, media_type="application/zip")


@_facade().router.get("/admin/wallets")
def api_admin_list_wallets(
    limit: int = _facade().Query(100, ge=1, le=500),
    offset: int = _facade().Query(0, ge=0),
    user: _facade().User = _facade().Depends(_facade()._require_admin),
):
    """Return one wallet row per account, including users whose balance is still zero.

    A wallet record is created lazily on first wallet use.  Listing the ``wallets`` table alone
    therefore made untouched accounts look as if their balance could not be queried.
    """
    sf = _facade().get_session_factory()
    with sf() as session:
        total = session.query(_facade().User).count()
        rows = (
            session.query(_facade().User, _facade().Wallet)
            .outerjoin(_facade().Wallet, _facade().Wallet.user_id == _facade().User.id)
            .order_by(_facade().User.created_at.desc(), _facade().User.id.desc())
            .offset(offset)
            .limit(limit)
            .all()
        )
        return {
            "items": [
                {
                    "id": wallet.id if wallet else None,
                    "user_id": account.id,
                    "balance": wallet.balance if wallet else 0.0,
                    "updated_at": (
                        wallet.updated_at.isoformat()
                        if wallet is not None and wallet.updated_at
                        else ""
                    ),
                }
                for (account, wallet) in rows
            ],
            "total": total,
        }


@_facade().router.get("/admin/transactions")
def api_admin_list_transactions(
    limit: int = _facade().Query(100, ge=1, le=500),
    offset: int = _facade().Query(0, ge=0),
    user: _facade().User = _facade().Depends(_facade()._require_admin),
):
    sf = _facade().get_session_factory()
    with sf() as session:
        total = session.query(_facade().Transaction).count()
        rows = (
            session.query(_facade().Transaction)
            .order_by(_facade().Transaction.created_at.desc())
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


@_facade().router.get("/admin/orders")
def api_admin_list_orders(
    status: _facade().Optional[str] = _facade().Query(None),
    limit: int = _facade().Query(100, ge=1, le=500),
    offset: int = _facade().Query(0, ge=0),
    user: _facade().User = _facade().Depends(_facade()._require_admin),
):
    """管理员订单/经营看板：分页订单列表 + 全量经营聚合。

    数据源：PAYMENT_BACKEND=java 时 Java PostgreSQL 为 SoT，本地 JSON 为只读兜底；
    其余模式本地 JSON 为权威来源。返回 ``source`` 供前端标注数据来源。
    """
    from modstore_server import payment_orders

    rows, total = payment_orders.list_orders(user_id=0, status=status, limit=limit, offset=offset)
    all_rows, _ = payment_orders.list_orders(user_id=0, status=None, limit=100000, offset=0)
    summary: dict[str, _facade().Any] = {
        "total_orders": len(all_rows),
        "paid_orders": 0,
        "pending_orders": 0,
        "paid_revenue": 0.0,
        "by_status": {},
    }
    for o in all_rows:
        st = str(o.get("status") or "unknown")
        summary["by_status"][st] = summary["by_status"].get(st, 0) + 1
        if st == "paid":
            summary["paid_orders"] += 1
            try:
                summary["paid_revenue"] += _facade().Decimal(str(o.get("total_amount") or "0"))
            except RECOVERABLE_ERRORS:
                pass
        elif st == "pending":
            summary["pending_orders"] += 1
    summary["paid_revenue"] = float(summary["paid_revenue"])
    return {
        "items": rows,
        "total": total,
        "summary": summary,
        "source": "python_json" if payment_orders.is_local_source_of_truth() else "java",
    }


@_facade().router.get("/wallet/overview")
def api_wallet_overview(
    limit: int = _facade().Query(20, ge=1, le=200),
    offset: int = _facade().Query(0, ge=0),
    user: _facade().User = _facade().Depends(_facade()._get_current_user),
):
    """钱包概览：余额 + 最近交易流水（前端 walletOverview 消费此接口）。"""
    sf = _facade().get_session_factory()
    with sf() as session:
        wallet = session.query(_facade().Wallet).filter(_facade().Wallet.user_id == user.id).first()
        balance = wallet.balance if wallet else 0.0
        updated_at = wallet.updated_at.isoformat() if wallet and wallet.updated_at else ""
        total = (
            session.query(_facade().Transaction)
            .filter(_facade().Transaction.user_id == user.id)
            .count()
        )
        rows = (
            session.query(_facade().Transaction)
            .filter(_facade().Transaction.user_id == user.id)
            .order_by(_facade().Transaction.created_at.desc())
            .offset(offset)
            .limit(limit)
            .all()
        )
        return {
            "wallet": {"balance": balance, "updated_at": updated_at},
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


@_facade().router.post("/package-audit")
async def api_package_audit(
    file: _facade().UploadFile = _facade().File(...),
    metadata: _facade().Optional[str] = _facade().Form(None),
    user: _facade().User = _facade().Depends(_facade()._get_current_user),
):
    """通用包审计接口（前端 auditPackage 消费此接口）。上传 .zip/.xcemp，返回五维审核结论。"""
    import json as _json

    from modstore_server.package_sandbox_audit import run_package_audit_async

    raw = await file.read()
    meta: dict = {}
    if metadata:
        try:
            meta = _json.loads(metadata)
        except RECOVERABLE_ERRORS:
            pass
    result = await run_package_audit_async(raw, meta or None)
    return result
