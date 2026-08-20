# mypy: disable-error-code="valid-type, attr-defined, no-any-return"
# isort: skip_file
"""Implementation extracted from the public facade module."""

from __future__ import annotations

from modstore_server.operational_errors import RECOVERABLE_ERRORS
import importlib
from modstore_server.api.market_routes_part01_part01_part01 import AdminSelfCreditDTO
from modstore_server.api.market_routes_part01_part01_part01 import (
    AiWalletPreauthorizeDTO,
)
from modstore_server.api.market_routes_part01_part01_part01 import RechargeDTO


def _facade():
    return importlib.import_module("modstore_server.api.market_routes")


@_facade().router.get("/admin/ops-ssh-hint")
def api_admin_ops_ssh_hint(
    user: _facade().User = _facade().Depends(_facade()._require_admin),
):
    """运维终端 SSH 连接信息（仅管理员；凭据来自环境变量，勿写入前端）。"""
    host = (_facade().os.environ.get("MODSTORE_OPS_SSH_HOST") or "119.27.178.147").strip()
    user_name = (_facade().os.environ.get("MODSTORE_OPS_SSH_USER") or "root").strip()
    password = (_facade().os.environ.get("MODSTORE_OPS_SSH_PASSWORD") or "").strip()
    command = (
        _facade().os.environ.get("MODSTORE_OPS_SSH_COMMAND") or ""
    ).strip() or f"ssh -o StrictHostKeyChecking=no {user_name}@{host}"
    return {"ok": True, "command": command, "password": password}


@_facade().router.get("/wallet/balance")
def api_wallet_balance(
    user: _facade().User = _facade().Depends(_facade()._get_current_user),
):
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
    body: RechargeDTO,
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
    body: AdminSelfCreditDTO,
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
    body: AdminSelfCreditDTO,
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
    except RECOVERABLE_ERRORS:
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


def _ai_wallet_transaction_payload(
    txn: _facade().Transaction,
) -> dict[str, _facade().Any]:
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
            _facade().Transaction.user_id == user_id,
            _facade().Transaction.txn_type == "ai_preauth",
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
            _facade().Transaction.user_id == user_id,
            _facade().Transaction.txn_type == txn_type,
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
            settled,
            _facade()._wallet_money(meta.get("actual_amount") or abs(row.amount or 0)),
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
    body: AiWalletPreauthorizeDTO,
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
