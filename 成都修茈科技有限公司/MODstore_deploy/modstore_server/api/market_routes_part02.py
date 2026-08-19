# ruff: noqa
"""Implementation extracted from the public facade module."""
from __future__ import annotations
import importlib


def _facade():
    return importlib.import_module("modstore_server.api.market_routes")


@_facade().router.get("/admin/ops-ssh-hint")
def api_admin_ops_ssh_hint(user: _facade().User = _facade().Depends(_facade()._require_admin)):
    """运维终端 SSH 连接信息（仅管理员；凭据来自环境变量，勿写入前端）。"""
    host = (_facade().os.environ.get("MODSTORE_OPS_SSH_HOST") or "119.27.178.147").strip()
    user_name = (_facade().os.environ.get("MODSTORE_OPS_SSH_USER") or "root").strip()
    password = (_facade().os.environ.get("MODSTORE_OPS_SSH_PASSWORD") or "").strip()
    command = (
        _facade().os.environ.get("MODSTORE_OPS_SSH_COMMAND") or ""
    ).strip() or f"ssh -o StrictHostKeyChecking=no {user_name}@{host}"
    return {"ok": True, "command": command, "password": password}


@_facade().router.get("/wallet/balance")
def api_wallet_balance(user: _facade().User = _facade().Depends(_facade()._get_current_user)):
    sf = _facade().get_session_factory()
    with sf() as session:
        wallet = session.query(_facade().Wallet).filter(_facade().Wallet.user_id == user.id).first()
        if not wallet:
            wallet = _facade().Wallet(user_id=user.id, balance=0.0)
            session.add(wallet)
            session.commit()
        return {
            "balance": wallet.balance,
            "updated_at": wallet.updated_at.isoformat() if wallet.updated_at else "",
        }


@_facade().router.post("/wallet/recharge")
def api_wallet_recharge(
    body: _facade().RechargeDTO,
    request: _facade().Request,
    user: _facade().User = _facade().Depends(_facade()._get_current_user),
):
    """管理员线下直充（需密钥）。用户日常充值请使用「支付宝」在钱包页发起。"""
    if not user.is_admin:
        raise _facade().HTTPException(
            403, "仅管理员可使用 Token 直充接口，且只能为当前登录账号加款"
        )
    admin_token = (_facade().os.environ.get("MODSTORE_ADMIN_RECHARGE_TOKEN") or "").strip()
    if not admin_token:
        raise _facade().HTTPException(503, "未配置 MODSTORE_ADMIN_RECHARGE_TOKEN，无法直充")
    client_token = (request.headers.get("X-Modstore-Recharge-Token") or "").strip() or (
        body.recharge_token or ""
    ).strip()
    if client_token != admin_token:
        raise _facade().HTTPException(403, "无效的充值授权")
    sf = _facade().get_session_factory()
    with sf() as session:
        wallet = (
            session.query(_facade().Wallet)
            .filter(_facade().Wallet.user_id == user.id)
            .with_for_update()
            .first()
        )
        if not wallet:
            wallet = _facade().Wallet(user_id=user.id, balance=0.0)
            session.add(wallet)
            session.flush()
        wallet.balance += body.amount
        wallet.updated_at = _facade().datetime.now(_facade().timezone.utc)
        txn = _facade().Transaction(
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
    raw = (_facade().os.environ.get("MODSTORE_ADMIN_SELF_CREDIT_CAP") or "").strip()
    if not raw:
        return 100000.0
    try:
        return max(1.0, float(raw))
    except ValueError:
        return 100000.0


@_facade().router.post("/wallet/admin-self-credit")
def api_wallet_admin_self_credit(
    body: _facade().AdminSelfCreditDTO,
    user: _facade().User = _facade().Depends(_facade()._get_current_user),
):
    """管理员为本人钱包加款（仅 JWT 鉴权，不依赖 MODSTORE_ADMIN_RECHARGE_TOKEN）。"""
    if not user.is_admin:
        raise _facade().HTTPException(403, "仅管理员可为本人钱包加款")
    cap = _facade()._admin_self_credit_cap()
    if body.amount > cap:
        raise _facade().HTTPException(400, f"单次加款不能超过 {cap:g} 元")
    sf = _facade().get_session_factory()
    with sf() as session:
        wallet = (
            session.query(_facade().Wallet)
            .filter(_facade().Wallet.user_id == user.id)
            .with_for_update()
            .first()
        )
        if not wallet:
            wallet = _facade().Wallet(user_id=user.id, balance=0.0)
            session.add(wallet)
            session.flush()
        wallet.balance += body.amount
        wallet.updated_at = _facade().datetime.now(_facade().timezone.utc)
        txn = _facade().Transaction(
            user_id=user.id,
            amount=body.amount,
            txn_type="admin_self_credit",
            status="completed",
            description=(body.description or "").strip() or "管理员本人加款",
        )
        session.add(txn)
        session.commit()
        return {"ok": True, "new_balance": wallet.balance, "balance": wallet.balance}


@_facade().router.post("/admin/users/{user_id}/wallet/credit")
def api_admin_credit_user_wallet(
    user_id: int,
    body: _facade().AdminSelfCreditDTO,
    user: _facade().User = _facade().Depends(_facade()._require_admin),
):
    """管理员为指定用户钱包加款。"""
    amount = _facade()._wallet_money(body.amount)
    if amount <= _facade().Decimal("0.00"):
        raise _facade().HTTPException(400, "加款金额必须大于 0")
    description = (body.description or "").strip() or "后台加款"
    sf = _facade().get_session_factory()
    with sf() as session:
        target = session.query(_facade().User).filter(_facade().User.id == user_id).first()
        if not target:
            raise _facade().HTTPException(404, "用户不存在")
        wallet = (
            session.query(_facade().Wallet)
            .filter(_facade().Wallet.user_id == user_id)
            .with_for_update()
            .first()
        )
        if not wallet:
            wallet = _facade().Wallet(user_id=user_id, balance=0.0)
            session.add(wallet)
            session.flush()
        wallet.balance = _facade()._wallet_money(wallet.balance) + amount
        wallet.updated_at = _facade().datetime.now(_facade().timezone.utc)
        txn = _facade().Transaction(
            user_id=user_id,
            amount=amount,
            txn_type="admin_credit",
            status="completed",
            description=description,
            idempotency_key=f"admin_credit:{user_id}:{_facade().uuid.uuid4().hex}",
        )
        session.add(txn)
        session.commit()
        return {
            "ok": True,
            "user_id": user_id,
            "amount": _facade()._wallet_money_str(amount),
            "balance": _facade()._wallet_money_str(wallet.balance),
            "new_balance": _facade()._wallet_money_str(wallet.balance),
        }


def _wallet_money(value: _facade().Any) -> _facade().Decimal:
    try:
        return (
            _facade()
            .Decimal(str(value or "0"))
            .quantize(_facade().Decimal("0.01"), rounding=_facade().ROUND_HALF_UP)
        )
    except Exception:
        return _facade().Decimal("0.00")


def _wallet_money_str(value: _facade().Any) -> str:
    return format(_facade()._wallet_money(value), "f")


def _ai_hold_no(user_id: int, idempotency_key: str) -> str:
    raw = f"{int(user_id)}:{idempotency_key}".encode("utf-8")
    return "AIH" + _facade().hashlib.sha256(raw).hexdigest()[:16].upper()


def _ai_wallet_meta(**payload: _facade().Any) -> str:
    return "ai_wallet:" + _facade().json.dumps(
        payload, ensure_ascii=False, sort_keys=True, default=str
    )


def _parse_ai_wallet_meta(description: str) -> dict[str, _facade().Any]:
    raw = str(description or "")
    if not raw.startswith("ai_wallet:"):
        return {}
    try:
        data = _facade().json.loads(raw[len("ai_wallet:") :])
    except (TypeError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def _ai_wallet_transaction_payload(txn: _facade().Transaction) -> dict[str, _facade().Any]:
    meta = _facade()._parse_ai_wallet_meta(txn.description)
    return {
        "id": txn.id,
        "amount": _facade()._wallet_money_str(txn.amount),
        "txn_type": txn.txn_type,
        "status": txn.status,
        "hold_no": meta.get("hold_no") or "",
        "provider": meta.get("provider") or "",
        "model": meta.get("model") or "",
        "request_id": meta.get("request_id") or "",
        "idempotency_key": getattr(txn, "idempotency_key", "") or "",
        "created_at": txn.created_at.isoformat() if txn.created_at else "",
    }


def _find_ai_preauth_by_hold(
    session: _facade().Any, user_id: int, hold_no: str
) -> _facade().Transaction | None:
    rows = (
        session.query(_facade().Transaction)
        .filter(
            _facade().Transaction.user_id == user_id, _facade().Transaction.txn_type == "ai_preauth"
        )
        .order_by(_facade().Transaction.created_at.desc())
        .limit(200)
        .all()
    )
    for row in rows:
        if str(_facade()._parse_ai_wallet_meta(row.description).get("hold_no") or "") == hold_no:
            return row
    return None


def _find_ai_txn_by_key(
    session: _facade().Any, user_id: int, txn_type: str, idempotency_key: str
) -> _facade().Transaction | None:
    return (
        session.query(_facade().Transaction)
        .filter(
            _facade().Transaction.user_id == user_id,
            _facade().Transaction.txn_type == txn_type,
            _facade().Transaction.idempotency_key == idempotency_key,
        )
        .first()
    )


def _ai_txns_for_hold(
    session: _facade().Any, user_id: int, txn_type: str, hold_no: str
) -> list[_facade().Transaction]:
    rows = (
        session.query(_facade().Transaction)
        .filter(
            _facade().Transaction.user_id == user_id, _facade().Transaction.txn_type == txn_type
        )
        .order_by(_facade().Transaction.created_at.desc())
        .limit(200)
        .all()
    )
    return [
        row
        for row in rows
        if str(_facade()._parse_ai_wallet_meta(row.description).get("hold_no") or "") == hold_no
    ]


def _ai_settled_amount_for_hold(
    session: _facade().Any, user_id: int, hold_no: str
) -> _facade().Decimal:
    settled = _facade().Decimal("0.00")
    for row in _facade()._ai_txns_for_hold(session, user_id, "ai_settle", hold_no):
        meta = _facade()._parse_ai_wallet_meta(row.description)
        settled = max(
            settled, _facade()._wallet_money(meta.get("actual_amount") or abs(row.amount or 0))
        )
    return settled


def _ai_refunded_amount_for_hold(
    session: _facade().Any, user_id: int, hold_no: str
) -> _facade().Decimal:
    return sum(
        (
            _facade()._wallet_money(row.amount)
            for row in _facade()._ai_txns_for_hold(session, user_id, "ai_refund", hold_no)
        ),
        _facade().Decimal("0.00"),
    )


def _ai_hold_payload(
    preauth: _facade().Transaction, *, status: str, settled_amount: _facade().Any = 0
) -> dict[str, _facade().Any]:
    meta = _facade()._parse_ai_wallet_meta(preauth.description)
    return {
        "hold_no": meta.get("hold_no") or "",
        "amount": _facade()._wallet_money_str(abs(_facade()._wallet_money(preauth.amount))),
        "settled_amount": _facade()._wallet_money_str(settled_amount),
        "status": status,
        "provider": meta.get("provider") or "",
        "model": meta.get("model") or "",
        "request_id": meta.get("request_id") or "",
        "preauth_transaction_id": preauth.id,
        "created_at": preauth.created_at.isoformat() if preauth.created_at else "",
    }


@_facade().router.post("/wallet/ai/preauthorize")
def api_wallet_ai_preauthorize(
    body: _facade().AiWalletPreauthorizeDTO,
    user: _facade().User = _facade().Depends(_facade()._get_current_user),
):
    """Python 支付后端的 AI 钱包预授权；Java 后端同路径由 proxy 透传。"""
    amount = _facade()._wallet_money(body.amount)
    key = body.idempotency_key.strip()
    sf = _facade().get_session_factory()
    with sf() as session:
        existing = _facade()._find_ai_txn_by_key(session, user.id, "ai_preauth", key)
        wallet = (
            session.query(_facade().Wallet)
            .filter(_facade().Wallet.user_id == user.id)
            .with_for_update()
            .first()
        )
        if not wallet:
            wallet = _facade().Wallet(user_id=user.id, balance=0.0)
            session.add(wallet)
            session.flush()
        if existing:
            return {
                "ok": True,
                "hold": _facade()._ai_hold_payload(existing, status="held"),
                "balance": _facade()._wallet_money_str(wallet.balance),
                "idempotent": True,
            }
        balance_before = _facade()._wallet_money(wallet.balance)
        if balance_before < amount:
            raise _facade().HTTPException(
                402,
                f"余额不足，需要 ¥{_facade()._wallet_money_str(amount)}，当前 ¥{_facade()._wallet_money_str(balance_before)}",
            )
        hold_no = _facade()._ai_hold_no(user.id, key)
        wallet.balance = balance_before - amount
        wallet.updated_at = _facade().datetime.now(_facade().timezone.utc)
        txn = _facade().Transaction(
            user_id=user.id,
            amount=-amount,
            txn_type="ai_preauth",
            status="completed",
            description=_facade()._ai_wallet_meta(
                hold_no=hold_no,
                provider=body.provider[:64],
                model=body.model[:128],
                request_id=body.request_id[:128],
            ),
            idempotency_key=key,
        )
        session.add(txn)
        session.commit()
        session.refresh(txn)
        return {
            "ok": True,
            "hold": _facade()._ai_hold_payload(txn, status="held"),
            "balance": _facade()._wallet_money_str(wallet.balance),
        }


@_facade().router.post("/wallet/ai/settle")
def api_wallet_ai_settle(
    body: _facade().AiWalletSettleDTO,
    user: _facade().User = _facade().Depends(_facade()._get_current_user),
):
    """结算 AI 预授权：实际金额低于预授权则释放差额，高于则补扣差额。"""
    actual = _facade()._wallet_money(body.actual_amount)
    key = body.idempotency_key.strip()
    sf = _facade().get_session_factory()
    with sf() as session:
        existing = _facade()._find_ai_txn_by_key(session, user.id, "ai_settle", key)
        wallet = (
            session.query(_facade().Wallet)
            .filter(_facade().Wallet.user_id == user.id)
            .with_for_update()
            .first()
        )
        if not wallet:
            wallet = _facade().Wallet(user_id=user.id, balance=0.0)
            session.add(wallet)
            session.flush()
        preauth = _facade()._find_ai_preauth_by_hold(session, user.id, body.hold_no.strip())
        if not preauth:
            raise _facade().HTTPException(404, "预授权不存在")
        if existing:
            return {
                "ok": True,
                "hold": _facade()._ai_hold_payload(
                    preauth, status="settled", settled_amount=actual
                ),
                "balance": _facade()._wallet_money_str(wallet.balance),
                "idempotent": True,
            }
        reserved = abs(_facade()._wallet_money(preauth.amount))
        delta = actual - reserved
        balance_before = _facade()._wallet_money(wallet.balance)
        if delta > 0 and balance_before < delta:
            raise _facade().HTTPException(
                402,
                f"余额不足，需要 ¥{_facade()._wallet_money_str(delta)}，当前 ¥{_facade()._wallet_money_str(balance_before)}",
            )
        wallet.balance = balance_before - delta
        wallet.updated_at = _facade().datetime.now(_facade().timezone.utc)
        txn = _facade().Transaction(
            user_id=user.id,
            amount=-delta,
            txn_type="ai_settle",
            status="completed",
            description=_facade()._ai_wallet_meta(
                hold_no=body.hold_no.strip(),
                actual_amount=_facade()._wallet_money_str(actual),
                reserved_amount=_facade()._wallet_money_str(reserved),
            ),
            idempotency_key=key,
        )
        session.add(txn)
        session.commit()
        return {
            "ok": True,
            "hold": _facade()._ai_hold_payload(preauth, status="settled", settled_amount=actual),
            "balance": _facade()._wallet_money_str(wallet.balance),
        }


@_facade().router.post("/wallet/ai/release")
def api_wallet_ai_release(
    body: _facade().AiWalletReleaseDTO,
    user: _facade().User = _facade().Depends(_facade()._get_current_user),
):
    """释放 AI 预授权；已结算的 hold 不再退回，保持幂等。"""
    key = body.idempotency_key.strip()
    sf = _facade().get_session_factory()
    with sf() as session:
        existing = _facade()._find_ai_txn_by_key(session, user.id, "ai_release", key)
        wallet = (
            session.query(_facade().Wallet)
            .filter(_facade().Wallet.user_id == user.id)
            .with_for_update()
            .first()
        )
        if not wallet:
            wallet = _facade().Wallet(user_id=user.id, balance=0.0)
            session.add(wallet)
            session.flush()
        preauth = _facade()._find_ai_preauth_by_hold(session, user.id, body.hold_no.strip())
        if not preauth:
            raise _facade().HTTPException(404, "预授权不存在")
        if existing:
            return {
                "ok": True,
                "hold": _facade()._ai_hold_payload(preauth, status="released", settled_amount=0),
                "balance": _facade()._wallet_money_str(wallet.balance),
                "idempotent": True,
            }
        settled = (
            session.query(_facade().Transaction)
            .filter(
                _facade().Transaction.user_id == user.id,
                _facade().Transaction.txn_type == "ai_settle",
            )
            .order_by(_facade().Transaction.created_at.desc())
            .limit(200)
            .all()
        )
        if any(
            (
                str(_facade()._parse_ai_wallet_meta(row.description).get("hold_no") or "")
                == body.hold_no.strip()
                for row in settled
            )
        ):
            return {
                "ok": True,
                "hold": _facade()._ai_hold_payload(preauth, status="settled", settled_amount=0),
                "balance": _facade()._wallet_money_str(wallet.balance),
                "idempotent": True,
            }
        reserved = abs(_facade()._wallet_money(preauth.amount))
        wallet.balance = _facade()._wallet_money(wallet.balance) + reserved
        wallet.updated_at = _facade().datetime.now(_facade().timezone.utc)
        txn = _facade().Transaction(
            user_id=user.id,
            amount=reserved,
            txn_type="ai_release",
            status="completed",
            description=_facade()._ai_wallet_meta(
                hold_no=body.hold_no.strip(), reason=(body.reason or "release")[:128]
            ),
            idempotency_key=key,
        )
        session.add(txn)
        session.commit()
        return {
            "ok": True,
            "hold": _facade()._ai_hold_payload(preauth, status="released", settled_amount=0),
            "balance": _facade()._wallet_money_str(wallet.balance),
        }


@_facade().router.post("/wallet/ai/refund")
def api_wallet_ai_refund(
    body: _facade().AiWalletRefundDTO,
    user: _facade().User = _facade().Depends(_facade()._get_current_user),
):
    """Refund a settled AI wallet hold. The idempotency key makes retries safe."""
    key = body.idempotency_key.strip()
    hold_no = body.hold_no.strip()
    refund_amount = _facade()._wallet_money(body.refund_amount)
    sf = _facade().get_session_factory()
    with sf() as session:
        existing = _facade()._find_ai_txn_by_key(session, user.id, "ai_refund", key)
        wallet = (
            session.query(_facade().Wallet)
            .filter(_facade().Wallet.user_id == user.id)
            .with_for_update()
            .first()
        )
        if not wallet:
            wallet = _facade().Wallet(user_id=user.id, balance=0.0)
            session.add(wallet)
            session.flush()
        preauth = _facade()._find_ai_preauth_by_hold(session, user.id, hold_no)
        if not preauth:
            raise _facade().HTTPException(404, "预授权不存在")
        settled_amount = _facade()._ai_settled_amount_for_hold(session, user.id, hold_no)
        if settled_amount <= 0:
            raise _facade().HTTPException(400, "预授权尚未结算，不能退款")
        if existing:
            return {
                "ok": True,
                "refund": {
                    "hold_no": hold_no,
                    "amount": _facade()._wallet_money_str(existing.amount),
                    "status": "refunded",
                    "refund_transaction_id": existing.id,
                },
                "hold": _facade()._ai_hold_payload(
                    preauth, status="refunded", settled_amount=settled_amount
                ),
                "balance": _facade()._wallet_money_str(wallet.balance),
                "idempotent": True,
            }
        refunded_before = _facade()._ai_refunded_amount_for_hold(session, user.id, hold_no)
        refundable = settled_amount - refunded_before
        if refund_amount > refundable:
            raise _facade().HTTPException(
                400,
                f"退款金额超过可退余额：申请 ¥{_facade()._wallet_money_str(refund_amount)}，可退 ¥{_facade()._wallet_money_str(refundable)}",
            )
        wallet.balance = _facade()._wallet_money(wallet.balance) + refund_amount
        wallet.updated_at = _facade().datetime.now(_facade().timezone.utc)
        txn = _facade().Transaction(
            user_id=user.id,
            amount=refund_amount,
            txn_type="ai_refund",
            status="completed",
            description=_facade()._ai_wallet_meta(
                hold_no=hold_no,
                refund_amount=_facade()._wallet_money_str(refund_amount),
                settled_amount=_facade()._wallet_money_str(settled_amount),
                refunded_total_after=_facade()._wallet_money_str(refunded_before + refund_amount),
                reason=(body.reason or "refund")[:128],
            ),
            idempotency_key=key,
        )
        session.add(txn)
        session.commit()
        session.refresh(txn)
        return {
            "ok": True,
            "refund": {
                "hold_no": hold_no,
                "amount": _facade()._wallet_money_str(refund_amount),
                "status": "refunded",
                "refund_transaction_id": txn.id,
            },
            "hold": _facade()._ai_hold_payload(
                preauth, status="refunded", settled_amount=settled_amount
            ),
            "balance": _facade()._wallet_money_str(wallet.balance),
        }


@_facade().router.get("/wallet/transactions")
def api_wallet_transactions(
    limit: int = _facade().Query(50, ge=1, le=200),
    offset: int = _facade().Query(0, ge=0),
    user: _facade().User = _facade().Depends(_facade()._get_current_user),
):
    sf = _facade().get_session_factory()
    with sf() as session:
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


@_facade().router.post("/market/catalog/{item_id}/buy")
def api_buy_item(
    item_id: int, user: _facade().User = _facade().Depends(_facade()._get_current_user)
):
    sf = _facade().get_session_factory()
    with sf() as session:
        item = (
            session.query(_facade().CatalogItem).filter(_facade().CatalogItem.id == item_id).first()
        )
        if not item:
            raise _facade().HTTPException(404, "商品不存在")
        if _facade().is_planned_duty_employee_pack(item.pkg_id, item.artifact):
            raise _facade().HTTPException(404, "商品不存在")
        if item.price <= 0:
            existing = (
                session.query(_facade().Purchase)
                .filter(
                    _facade().Purchase.user_id == user.id, _facade().Purchase.catalog_id == item.id
                )
                .first()
            )
            from modstore_server.market_shared import _grant_catalog_entitlement

            if existing:
                _grant_catalog_entitlement(
                    session, user_id=user.id, item=item, source="free_catalog"
                )
                session.commit()
                return {"ok": True, "message": "已拥有"}
            purchase = _facade().Purchase(user_id=user.id, catalog_id=item.id, amount=0)
            session.add(purchase)
            _grant_catalog_entitlement(session, user_id=user.id, item=item, source="free_catalog")
            session.commit()
            return {"ok": True, "message": "免费领取成功"}
        existing = (
            session.query(_facade().Purchase)
            .filter(_facade().Purchase.user_id == user.id, _facade().Purchase.catalog_id == item.id)
            .first()
        )
        if existing:
            return {"ok": True, "message": "已拥有"}
        wallet = (
            session.query(_facade().Wallet)
            .filter(_facade().Wallet.user_id == user.id)
            .with_for_update()
            .first()
        )
        if not wallet:
            session.add(_facade().Wallet(user_id=user.id, balance=0.0))
            session.flush()
            wallet = (
                session.query(_facade().Wallet)
                .filter(_facade().Wallet.user_id == user.id)
                .with_for_update()
                .first()
            )
        if not wallet or wallet.balance < item.price:
            raise _facade().HTTPException(
                402, f"余额不足，需要 ¥{item.price}，当前 ¥{(wallet.balance if wallet else 0)}"
            )
        wallet.balance -= item.price
        wallet.updated_at = _facade().datetime.now(_facade().timezone.utc)
        purchase = _facade().Purchase(user_id=user.id, catalog_id=item.id, amount=item.price)
        txn = _facade().Transaction(
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


@_facade().router.get("/market/catalog/{item_id}/download")
def api_download_item(
    item_id: int, user: _facade().User = _facade().Depends(_facade()._get_current_user)
):
    sf = _facade().get_session_factory()
    with sf() as session:
        item = (
            session.query(_facade().CatalogItem).filter(_facade().CatalogItem.id == item_id).first()
        )
        if not item:
            raise _facade().HTTPException(404, "商品不存在")
        if _facade().is_planned_duty_employee_pack(item.pkg_id, item.artifact):
            raise _facade().HTTPException(404, "商品不存在")
        if item.price > 0:
            purchased = (
                session.query(_facade().Purchase)
                .filter(
                    _facade().Purchase.user_id == user.id, _facade().Purchase.catalog_id == item.id
                )
                .first()
            )
            if not purchased:
                raise _facade().HTTPException(403, "未购买此商品，请先购买后下载")
        if not item.stored_filename:
            raise _facade().HTTPException(404, "该商品无文件可下载")
        from fastapi.responses import StreamingResponse
        from modstore_server.catalog_store import files_dir

        path = _facade()._existing_child_file(files_dir(), item.stored_filename)
        if path is None:
            raise _facade().HTTPException(404, "文件缺失")

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


@_facade().router.get("/my-store")
def api_my_store(
    limit: int = _facade().Query(50, ge=1, le=200),
    offset: int = _facade().Query(0, ge=0),
    user: _facade().User = _facade().Depends(_facade()._get_current_user),
):
    sf = _facade().get_session_factory()
    with sf() as session:
        total = (
            session.query(_facade().Purchase).filter(_facade().Purchase.user_id == user.id).count()
        )
        rows = (
            session.query(_facade().Purchase)
            .filter(_facade().Purchase.user_id == user.id)
            .order_by(_facade().Purchase.created_at.desc())
            .offset(offset)
            .limit(limit)
            .all()
        )
        items = []
        for p in rows:
            item = (
                session.query(_facade().CatalogItem)
                .filter(_facade().CatalogItem.id == p.catalog_id)
                .first()
            )
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


def _catalog_files_dir() -> _facade().Path:
    """市场文件存储目录。"""
    d = _facade().Path(__file__).resolve().parent / "market_files"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _upload_chunks_dir() -> _facade().Path:
    """分块上传临时目录。"""
    d = _facade().Path(__file__).resolve().parent / "upload_chunks"
    d.mkdir(parents=True, exist_ok=True)
    return d
